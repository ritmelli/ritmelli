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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
compara = importlib.import_module("compara")
so_mock = importlib.import_module("so_mock")
fitcheck = importlib.import_module("fitcheck")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
i18n = importlib.import_module("i18n")
theme_page = importlib.import_module("theme_page")

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


def read_page(html, where):
    read, error = theme_page.strict(html)
    return read, error and f"{where}:{error[0]}:{error[1]}: {error[2]}"


def page_files(raiz, path):
    folder = raiz / ("gallery" if path.startswith("/?") else "themes/ritmelli")
    read, error = read_page((folder / "index.html").read_text(encoding="utf-8"), f"{folder.name}/index.html")
    if error:
        return None, error
    return [(kind, name, "\n" + (raiz / "themes" / name.removeprefix("/t/") if name.startswith("/t/") else
                                 folder / name).read_text(encoding="utf-8-sig"))
            for _, _, kind, name in read.found], None


def first_lost(expected, texts):
    left = iter(texts)
    return next((name for kind, name, text in expected if (kind, text) not in left), None)


def reads_as_the_build():
    with tempfile.TemporaryDirectory(prefix="ritmelli-missing-reader-") as folder:
        theme = Path(folder) / "themes" / "ritmelli"
        theme.mkdir(parents=True)
        (theme / "index.html").write_text('<script>/*</ script><a title="*/</script><script src="first.js"></script>">'
                                          '<script src="second.js"></script>', encoding="utf-8")
        for name in ("first.js", "second.js"):
            (theme / name).write_text(f"const {name[:-3]} = 1;\n", encoding="utf-8")
        expected, error = page_files(Path(folder), THEME)
    names = [name for _, name, _ in expected or []]
    return [(names == ["first.js", "second.js"], f"the file tags of a template are the ones the build reads, past a "
                                                 f"</ script that ends nothing ({error or names})")]


class Tab:
    def __init__(self, ws, base):
        self.ws, self.base = ws, base
        self.seq, self.pending, self.tasks = itertools.count(1), {}, set()
        self.loads, self.contexts, self.scripts, self.thrown, self.failing = 0, 0, [], [], set()
        self.sent, self.failed, self.files_asked = {}, [], []
        self.changed = asyncio.Event()

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def on_event(self, m):
        method = m.get("method")
        if method == "Fetch.requestPaused":
            if m["params"]["resourceType"] in ("Script", "Stylesheet"):
                self.files_asked.append(urllib.parse.urlsplit(m["params"]["request"]["url"]).path)
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


def pc_pairing_code(srv):
    srv.confere()
    conn = http.client.HTTPConnection("127.0.0.1", srv.porta, timeout=10)
    try:
        conn.request("GET", "/api/pareamento", headers={"Host": f"localhost:{srv.porta}"})
        return json.loads(conn.getresponse().read())["codigo"]
    finally:
        conn.close()


def served_pages(srv, role, raiz):
    results = []
    for path in [f"{THEME}?lang={lang}" for lang in LANGUAGES] + [f"{THEME}index.html?lang=en"] + \
            [f"/?lang={lang}" for lang in LANGUAGES]:
        so_mock.confere(srv.base + path)
        with urllib.request.urlopen(srv.base + path, timeout=10) as r:
            served, served_error = read_page(r.read().decode("utf-8"), path)
        expected, error = page_files(raiz, path)
        if error or served_error:
            results.append((False, f"{role}: {path} and its template are read by the build's grammar "
                                   f"({error or served_error})"))
            continue
        left = [f"{kind} {name}" for _, _, kind, name in served.found]
        lost = first_lost(expected, served.texts)
        results.append((not left and expected and not lost,
                        f"{role}: {path} has no <script src> and no stylesheet <link> ({left or 'none'}), and the "
                        f"text of its {len(expected)} files inside it, in order "
                        f"({f'not from {lost} on' if lost else 'all of them'})"))
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


def asked_no_file(tab, who):
    return (not tab.files_asked, f"{who}: the page asked the server for no script and no style sheet "
                                 f"({tab.files_asked or 'none'})")


def the_server_drops(raiz, role, language):
    async def run(tab):
        tab.language = language
        results = []
        if role == "phone":
            by_qr = language == LANGUAGES[1]
            ready = await paired_phone(tab, by_qr)
            if by_qr:
                history = [e["url"] for e in (await tab.cmd("Page.getNavigationHistory"))["entries"]]
                results.append((ready and history and not any("parear" in url for url in history),
                                f"phone in {language}: paired by the QR link, no entry of the tab's history keeps the code "
                                f"({history})"))
        else:
            await open_page(tab, f"?lang={language}")
            ready = (await tab.page_reaches("s.online === true && !s.card", PAGE_READY_S)).get("online") is True
        results.append(asked_no_file(tab, f"{role} in {language}"))
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
    results = reads_as_the_build()
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
