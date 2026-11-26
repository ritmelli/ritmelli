import argparse
import asyncio
import http.client
import importlib
import itertools
import json
import queue
import re
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
compara = importlib.import_module("compara")
so_mock = importlib.import_module("so_mock")
fitcheck = importlib.import_module("fitcheck")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
i18n = importlib.import_module("i18n")

THEME = "/t/ritmelli/"
LANGUAGES = ("en", "pt_BR")
STATE = ("({card: document.getElementById('fora')?.hidden === false,"
         " cardSeen: document.getElementById('fora')?.checkVisibility({visibilityProperty: true}) === true,"
         " pairing: document.getElementById('tela-parear')?.hidden === false,"
         " title: document.getElementById('fora-tt')?.textContent,"
         " text: document.getElementById('fora-p')?.textContent,"
         " online: typeof S === 'undefined' ? null : S.online})")
WAIT_IN_PAGE = """new Promise(done => {
  const state = () => %s;
  const met = s => %s;
  const observer = new MutationObserver(() => { if (met(state())) { observer.disconnect(); done(state()); } });
  observer.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  setTimeout(() => { observer.disconnect(); done(state()); }, %d);
  if (met(state())) { observer.disconnect(); done(state()); }
})"""
DEVTOOLS = re.compile(r"DevTools listening on (ws://\S+)")
MARKUP = re.compile(r"</?(?:b|code)>")
KEEP_EVENT_SOURCES = ("window.eventSources = []; window.EventSource = class extends EventSource {"
                      " constructor(...a) { super(...a); eventSources.push(this); } };")
CHROME_UP_S = 20.0
PAGE_READY_S = 15.0
CARD_SHOWS_S = 10.0


class FileTags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.files, self.bodies, self.open = [], [], None

    def handle_starttag(self, tag, attrs):
        a = {}
        for name, value in attrs:
            a.setdefault(name, value)
        if tag == "script" and "src" in a:
            self.files.append(("script", a["src"]))
        elif tag == "link" and "stylesheet" in (a.get("rel") or "").lower().split():
            self.files.append(("style", a.get("href")))
        elif tag in ("script", "style"):
            self.open = [tag, ""]
            self.bodies.append(self.open)

    def handle_data(self, data):
        if self.open is not None:
            self.open[1] += data

    def handle_endtag(self, tag):
        if self.open is not None and tag == self.open[0]:
            self.open = None


def file_tags(html):
    tags = FileTags()
    tags.feed(html)
    tags.close()
    return tags


def page_files(raiz, path):
    folder = raiz / ("gallery" if path.startswith("/?") else "themes/ritmelli")
    found = []
    for kind, name in file_tags((folder / "index.html").read_text(encoding="utf-8")).files:
        source = raiz / "themes" / name.removeprefix("/t/") if name.startswith("/t/") else folder / name
        found.append((kind, name, "\n" + source.read_text(encoding="utf-8")))
    return found


def first_lost(expected, bodies):
    left = iter(bodies)
    return next((name for kind, name, text in expected if [kind, text] not in left), None)


class Tab:
    def __init__(self, ws, base):
        self.ws, self.base = ws, base
        self.seq, self.pending, self.tasks = itertools.count(1), {}, set()
        self.loads, self.contexts, self.scripts, self.thrown, self.failing = 0, 0, [], [], set()
        self.sent, self.failed = {}, []
        self.changed = asyncio.Event()

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def on_event(self, m):
        method = m.get("method")
        if method == "Fetch.requestPaused":
            self.spawn(self.route(m["params"]))
        elif method == "Page.loadEventFired":
            self.loads += 1
            self.changed.set()
        elif method == "Runtime.executionContextCreated" and m["params"]["context"].get("origin") == self.base:
            self.contexts += 1
            self.changed.set()
        elif method == "Runtime.exceptionThrown":
            details = m["params"]["exceptionDetails"]
            self.thrown.append(details.get("exception", {}).get("description") or details.get("text"))
            self.changed.set()
        elif method == "Network.requestWillBeSent":
            self.sent[m["params"]["requestId"]] = urllib.parse.urlsplit(m["params"]["request"]["url"]).path
        elif method == "Network.loadingFailed":
            self.failed.append(self.sent.get(m["params"]["requestId"]))
            self.changed.set()
        elif method == "Debugger.scriptParsed":
            self.scripts.append(m["params"])

    async def cmd(self, method, **params):
        n = next(self.seq)
        future = asyncio.get_running_loop().create_future()
        self.pending[n] = future
        await self.ws.send(json.dumps({"id": n, "method": method, "params": params}))
        return (await asyncio.wait_for(future, 30)).get("result", {})

    async def route(self, p):
        url = p["request"]["url"]
        if not so_mock.mesma_origem(url, self.base):
            await self.cmd("Fetch.failRequest", requestId=p["requestId"], errorReason="BlockedByClient")
        elif urllib.parse.urlsplit(url).path in self.failing:
            await self.cmd("Fetch.failRequest", requestId=p["requestId"], errorReason="ConnectionRefused")
        else:
            await self.cmd("Fetch.continueRequest", requestId=p["requestId"])

    async def js(self, expression):
        r = await self.cmd("Runtime.evaluate", expression=expression, returnByValue=True)
        return r.get("result", {}).get("value")

    async def page_reaches(self, condition, seconds):
        r = await self.cmd("Runtime.evaluate", awaitPromise=True, returnByValue=True,
                           expression=WAIT_IN_PAGE % (STATE, condition, int(seconds * 1000)))
        return r.get("result", {}).get("value") or {}

    async def tab_reaches(self, test, seconds):
        async def watch():
            while not test():
                self.changed.clear()
                await self.changed.wait()
        try:
            await asyncio.wait_for(watch(), seconds)
        except TimeoutError:
            return False
        return True


def devtools_address(chrome, seconds):
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in chrome.stderr], daemon=True).start()
    while True:
        found = DEVTOOLS.search(lines.get(timeout=seconds))
        if found:
            return found.group(1)


async def with_tab(srv, run):
    profile = tempfile.mkdtemp(prefix="ritmelli-missing-")
    chrome = subprocess.Popen([fitcheck.CHROME, "--headless=new", "--remote-debugging-port=0",
                               f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                               "--window-size=1440,900", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                              errors="replace")
    try:
        browser = urllib.parse.urlsplit(devtools_address(chrome, CHROME_UP_S))
        with urllib.request.urlopen(f"http://{browser.netloc}/json") as r:
            ws_url = next(t["webSocketDebuggerUrl"] for t in json.load(r) if t["type"] == "page")
        async with fitcheck.conecta_cdp(ws_url) as ws:
            tab = Tab(ws, srv.base)
            tab.srv = srv
            reader = asyncio.create_task(fitcheck.le_cdp(ws, tab.pending, tab.on_event))
            await tab.cmd("Page.enable")
            await tab.cmd("Runtime.enable")
            await tab.cmd("Fetch.enable", patterns=[{"urlPattern": "*"}])
            result = await run(tab)
            for task in [*tab.tasks, reader]:
                task.cancel()
            return result
    finally:
        fitcheck.fecha_chrome(chrome, profile)


async def open_page(tab, query=""):
    url = tab.base + THEME + query
    so_mock.confere(url)
    await tab.cmd("Page.navigate", url=url)
    await tab.tab_reaches(lambda: tab.contexts >= 1, PAGE_READY_S)


def pc_call(srv, method, route):
    srv.confere()
    conn = http.client.HTTPConnection("127.0.0.1", srv.porta, timeout=10)
    try:
        conn.request(method, route, headers={"Host": f"localhost:{srv.porta}"})
        return json.loads(conn.getresponse().read())
    finally:
        conn.close()


def pc_pairing_code(srv):
    return pc_call(srv, "GET", "/api/pareamento")["codigo"]


def served_pages(srv, role, raiz):
    results = []
    for path in [f"{THEME}?lang={lang}" for lang in LANGUAGES] + [f"{THEME}index.html?lang=en"] + \
            [f"/?lang={lang}" for lang in LANGUAGES]:
        so_mock.confere(srv.base + path)
        with urllib.request.urlopen(srv.base + path, timeout=10) as r:
            tags = file_tags(r.read().decode("utf-8"))
        expected = page_files(raiz, path)
        lost = first_lost(expected, tags.bodies)
        results.append((not tags.files and expected and not lost,
                        f"{role}: {path} has no <script src> and no stylesheet <link> "
                        f"({[f'{k} {n}' for k, n in tags.files] or 'none'}), and the text of its {len(expected)} files "
                        f"inside it, in order ({f'not from {lost} on' if lost else 'all of them'})"))
    return results


def expected_card(raiz, role, language):
    d = i18n.dados(raiz / "themes" / "ritmelli" / "i18n", language)
    text = {**d["reserva"], **d["textos"]}
    if role == "pc":
        body = text["offline.downText"].replace("{folder}", "%LOCALAPPDATA%\\Ritmelli\\logs")
        return text["offline.stopped"], MARKUP.sub("", body)
    return text["offline.phone.title"], text["offline.phone.text"]


async def paired_phone(tab, by_qr):
    if by_qr:
        await open_page(tab, f"?lang={tab.language}&parear={pc_pairing_code(tab.srv)}")
        asked = {"pairing": True}
    else:
        await open_page(tab, f"?lang={tab.language}")
        asked = await tab.page_reaches("s.pairing", PAGE_READY_S)
        await tab.js(f"document.querySelector('#pa-in').value = '{pc_pairing_code(tab.srv)}'; "
                     "document.querySelector('#form-parear').requestSubmit()")
    online = await tab.page_reaches("s.online === true && !s.card", PAGE_READY_S)
    return asked.get("pairing") is True and online.get("online") is True


def the_server_drops(raiz, role, language):
    async def run(tab):
        tab.language = language
        results = []
        if role == "phone":
            by_qr = language == LANGUAGES[1]
            ready = await paired_phone(tab, by_qr)
            if by_qr:
                search = await tab.js("location.search")
                results.append((ready and "parear" not in search,
                                f"phone in {language}: paired by the QR link, the page takes the code out of its address "
                                f"({search!r})"))
        else:
            await open_page(tab, f"?lang={language}")
            ready = (await tab.page_reaches("s.online === true && !s.card", PAGE_READY_S)).get("online") is True
        tab.srv.mata()
        card = await tab.page_reaches("s.cardSeen", CARD_SHOWS_S)
        title, text = expected_card(raiz, role, language)
        said = "the expected text" if card.get("text") == text else f"{card.get('text')!r}, not {text!r}"
        results.append((ready and card.get("cardSeen") and card.get("title") == title and card.get("text") == text,
                        f"{role} in {language}: the server drops after the page connected, and the off-air card, "
                        f"{'visible' if card.get('cardSeen') else 'not visible'}, says {card.get('title')!r} (expected "
                        f"{title!r}) over {said}"))
        return results
    return run


async def disconnected_without_network(tab):
    tab.language = LANGUAGES[0]
    await tab.cmd("Network.enable")
    await tab.cmd("Page.addScriptToEvaluateOnNewDocument", source=KEEP_EVENT_SOURCES)
    ready = await paired_phone(tab, by_qr=False)
    tab.failing.add("/api/state")
    thrown = len(tab.thrown)
    await tab.js("eventSources.at(-1).dispatchEvent(new MessageEvent('desconectado', {data: '{}'}))")
    asked = await tab.page_reaches("s.pairing", CARD_SHOWS_S)
    failed = await tab.tab_reaches(lambda: "/api/state" in tab.failed, CARD_SHOWS_S)
    await tab.js("0")
    tab.failing.clear()
    return [(ready and asked.get("pairing") is True and failed and not tab.thrown[thrown:],
             f"phone: the computer's disconnect arrives while the phone's network fails: the code screen opens, with no "
             f"uncaught error (paired {ready}, code screen {asked.get('pairing')}, the state call failed {failed}, "
             f"{tab.thrown[thrown:] or 'no error'})")]


def scenarios(raiz):
    results = []
    for role, extras in (("pc", []), ("phone", ["--papel-local", "celular"])):
        runs = [the_server_drops(raiz, role, language) for language in LANGUAGES]
        if role == "phone":
            runs.insert(0, disconnected_without_network)
        for n, run in enumerate(runs):
            with tempfile.TemporaryDirectory(prefix=f"ritmelli-missing-{role}-") as folder:
                tmp = Path(folder)
                with open(tmp / "server.log", "w", encoding="utf-8") as log:
                    srv = compara.sobe_servidor(tmp, so_mock.free_port(), log, raiz=raiz,
                                                config={"boas_vindas": True}, extras=extras)
                    try:
                        if n == 0:
                            results += served_pages(srv, role, raiz)
                        results += asyncio.run(with_tab(srv, run))
                    finally:
                        if srv.srv.poll() is None:
                            compara.para_servidor(srv)
    return results


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="The theme page as the server sends it, against --mock servers of its "
                                             "own (one as the PC, one as a phone): every script and style sheet "
                                             "inside the page, in both languages, and, in a headless Chrome, the "
                                             "off-air card with the text of the role when the server drops. Exit 1 if "
                                             "a check fails.")
    ap.add_argument("--raiz", type=Path, default=RAIZ, help="the checkout whose server.py and theme are served")
    args = ap.parse_args(argv)
    results = scenarios(args.raiz.resolve())
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if results and all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
