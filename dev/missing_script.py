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
testa_i18n = importlib.import_module("testa_i18n")

RAIZ = Path(__file__).resolve().parent.parent
THEME = "/t/ritmelli/"
STATE = ("({card: document.getElementById('fora')?.hidden === false,"
         " cardSeen: document.getElementById('fora')?.checkVisibility({visibilityProperty: true}) === true,"
         " pairing: document.getElementById('tela-parear')?.hidden === false,"
         " dialog: !!document.querySelector('dialog[open]'),"
         " devicesFailed: !!document.getElementById('dd-msg')?.classList.contains('erro'),"
         " handlersIn: document.getElementById('form-busca')?.inert === false,"
         " notice: !!document.querySelector('#aviso .aviso-t')?.textContent,"
         " focusOutside: document.activeElement !== document.body"
         " && !document.getElementById('fora')?.contains(document.activeElement),"
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
CHROME_UP_S = 20.0
CARD_SHOWS_S = 8.0
RELOAD_S = 12.0


def theme_file(url):
    path = urllib.parse.urlsplit(url).path
    return path[len(THEME):] if path.startswith(THEME) else path


class Tab:
    def __init__(self, ws, base):
        self.ws, self.base = ws, base
        self.seq, self.pending, self.tasks = itertools.count(1), {}, set()
        self.failing, self.holding, self.held = set(), set(), {}
        self.documents, self.api_calls, self.loads, self.contexts, self.loaders = [], [], 0, 0, []
        self.asked, self.scripts = {}, []
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
        elif method == "Network.requestWillBeSent" and so_mock.mesma_origem(m["params"]["request"]["url"], self.base):
            sent = m["params"]
            if sent.get("type") == "Document":
                self.loaders.append(sent["loaderId"])
            elif theme_file(sent["request"]["url"]).startswith("/api/"):
                self.api_calls.append((sent["loaderId"], theme_file(sent["request"]["url"])))
            self.changed.set()
        elif method == "Runtime.executionContextCreated" and m["params"]["context"].get("origin") == self.base:
            self.contexts += 1
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
        url, rid = p["request"]["url"], p["requestId"]
        if not so_mock.mesma_origem(url, self.base):
            await self.cmd("Fetch.failRequest", requestId=rid, errorReason="BlockedByClient")
            return
        name = theme_file(url)
        if p["resourceType"] == "Document":
            self.documents.append(url)
            if len(self.documents) > 1 and "reload" in self.holding:
                name = "reload"
        self.asked[name] = self.asked.get(name, 0) + 1
        self.changed.set()
        if name in self.failing:
            await self.cmd("Fetch.failRequest", requestId=rid, errorReason="ConnectionRefused")
        elif name in self.holding:
            self.held.setdefault(name, []).append(rid)
        else:
            await self.cmd("Fetch.continueRequest", requestId=rid)

    async def release(self, name, fail):
        self.holding.discard(name)
        for rid in self.held.pop(name, []):
            if fail:
                await self.cmd("Fetch.failRequest", requestId=rid, errorReason="ConnectionRefused")
            else:
                await self.cmd("Fetch.continueRequest", requestId=rid)

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


def start_chrome():
    profile = tempfile.mkdtemp(prefix="ritmelli-missing-")
    chrome = subprocess.Popen([fitcheck.CHROME, "--headless=new", "--remote-debugging-port=0",
                               f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                               "--window-size=1440,900", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                              errors="replace")
    return chrome, profile


async def run_in_tab(ws, srv, run):
    tab = Tab(ws, srv.base)
    tab.srv = srv
    reader = asyncio.create_task(fitcheck.le_cdp(ws, tab.pending, tab.on_event))
    await tab.cmd("Page.enable")
    await tab.cmd("Runtime.enable")
    await tab.cmd("Network.enable")
    await tab.cmd("Fetch.enable", patterns=[{"urlPattern": "*"}])
    result = await run(tab)
    for task in [*tab.tasks, reader]:
        task.cancel()
    return result


async def with_tab(srv, run):
    chrome, profile = start_chrome()
    try:
        browser = urllib.parse.urlsplit(devtools_address(chrome, CHROME_UP_S))
        with urllib.request.urlopen(f"http://{browser.netloc}/json") as r:
            ws_url = next(t["webSocketDebuggerUrl"] for t in json.load(r) if t["type"] == "page")
        async with fitcheck.conecta_cdp(ws_url) as ws:
            return await run_in_tab(ws, srv, run)
    finally:
        fitcheck.fecha_chrome(chrome, profile)


async def with_tabs(srv, runs):
    chrome, profile = start_chrome()
    results = []
    try:
        address = devtools_address(chrome, CHROME_UP_S)
        netloc = urllib.parse.urlsplit(address).netloc
        async with fitcheck.conecta_cdp(address) as ws:
            browser = Tab(ws, srv.base)
            reader = asyncio.create_task(fitcheck.le_cdp(ws, browser.pending, browser.on_event))
            for run in runs:
                context = (await browser.cmd("Target.createBrowserContext"))["browserContextId"]
                target = (await browser.cmd("Target.createTarget", url="about:blank",
                                            browserContextId=context))["targetId"]
                async with fitcheck.conecta_cdp(f"ws://{netloc}/devtools/page/{target}") as page:
                    results.append(await run_in_tab(page, srv, run))
                await browser.cmd("Target.closeTarget", targetId=target)
                await browser.cmd("Target.disposeBrowserContext", browserContextId=context)
            reader.cancel()
    finally:
        fitcheck.fecha_chrome(chrome, profile)
    return results


async def open_page(tab, query=""):
    url = tab.base + THEME + query
    so_mock.confere(url)
    await tab.cmd("Page.navigate", url=url)
    await tab.tab_reaches(lambda: tab.contexts >= 1, CARD_SHOWS_S)


async def a_file_that_fails(tab):
    tab.failing.add("deck.js")
    await open_page(tab)
    before = await tab.page_reaches("s.card", CARD_SHOWS_S)
    first_probe_failed = await tab.tab_reaches(lambda: tab.asked.get("deck.js", 0) >= 2, RELOAD_S)
    tab.failing.clear()
    reloaded = await tab.tab_reaches(lambda: tab.loads >= 2, RELOAD_S)
    calls_while_missing = [name for loader, name in tab.api_calls if tab.loaders and loader == tab.loaders[0]]
    after = await tab.page_reaches("!s.card && s.online === true", RELOAD_S) if reloaded else {}
    return [(before.get("card") and before.get("online") is not True and not calls_while_missing,
             f"deck.js fails: the off-air card, and no call to the server from that page ({before}, "
             f"{calls_while_missing})"),
            (first_probe_failed and reloaded and after.get("online") is True and not after.get("card"),
             f"deck.js answers again after a first try that failed too: the page loads again and connects ({after}, "
             f"{tab.asked.get('deck.js')} asks for deck.js, {tab.loads} loads)")]


async def a_late_call_counts_for_its_page(tab):
    tab.failing.add("deck.js")
    await open_page(tab)
    card = (await tab.page_reaches("s.card", CARD_SHOWS_S)).get("card")
    await tab.js("addEventListener('beforeunload', () => setInterval(() => fetch('/api/themes'), 50))")
    tab.holding.add("reload")
    tab.failing.clear()
    waiting = await tab.tab_reaches(lambda: bool(tab.held.get("reload")), RELOAD_S)
    before = len(tab.api_calls)
    sent = await tab.tab_reaches(lambda: any(name == "/api/themes" for _, name in tab.api_calls[before:]), 3.0)
    late = [loader for loader, name in tab.api_calls[before:] if name == "/api/themes"]
    await tab.release("reload", fail=False)
    reloaded = await tab.tab_reaches(lambda: tab.loads >= 2, RELOAD_S)
    return [(card and waiting and sent and reloaded and late and all(x == tab.loaders[0] for x in late),
             f"the calls the first page makes while its reload waits for the server count for the first page "
             f"({len(late)} calls, {len(set(late))} loader(s))")]


async def the_qr_code_survives(tab):
    tab.failing.add("dj-desk.js")
    await open_page(tab, "?parear=123456")
    card = (await tab.page_reaches("s.card", CARD_SHOWS_S)).get("card")
    tab.failing.clear()
    again = await tab.tab_reaches(lambda: len(tab.documents) >= 2, RELOAD_S)
    second = tab.documents[1] if again else ""
    return [(card and "parear=123456" in second,
             f"dj-desk.js fails on a ?parear= address: the page loads again at it ({tab.documents})")]


async def the_qr_code_stays_without_shared_js(tab):
    tab.failing.add("shared.js")
    await open_page(tab, "?parear=123456")
    card = (await tab.page_reaches("s.card", CARD_SHOWS_S)).get("card")
    search = await tab.js("location.search")
    tab.failing.clear()
    return [(card and search == "?parear=123456",
             f"shared.js fails on a ?parear= address: the address keeps the code while the off-air card is open "
             f"({search!r})")]


async def transporte_alone(tab):
    tab.failing.add("transporte.js")
    await open_page(tab)
    card = (await tab.page_reaches("s.card", CARD_SHOWS_S)).get("card")
    tab.failing.clear()
    back = await tab.page_reaches("s.online === true && !s.card", RELOAD_S)
    return [(card and back.get("online") is True and len(tab.documents) == 1,
             f"transporte.js fails alone: it connects again without loading the page again ({tab.documents})")]


async def a_dialog_opened_before(tab):
    tab.holding.add("deck.js")
    await open_page(tab)
    held = await tab.tab_reaches(lambda: bool(tab.held.get("deck.js")), CARD_SHOWS_S)
    ready = (await tab.page_reaches("s.handlersIn", CARD_SHOWS_S)).get("handlersIn")
    await tab.js("(b => { b.focus(); b.click(); })(document.querySelector('#b-disp'))")
    opened = (await tab.page_reaches("s.dialog", 3.0)).get("dialog")
    opened = opened and await tab.tab_reaches(lambda: tab.asked.get("/api/devices", 0) >= 1, 3.0)
    tab.failing.add("deck.js")
    await tab.release("deck.js", fail=True)
    after = await tab.page_reaches("s.card && !s.dialog", CARD_SHOWS_S)
    devices_asked = tab.asked.get("/api/devices", 0)
    for kind in ("keyDown", "keyUp"):
        await tab.cmd("Input.dispatchKeyEvent", type=kind, key="Enter", code="Enter", windowsVirtualKeyCode=13,
                      nativeVirtualKeyCode=13, text="\r" if kind == "keyDown" else "")
    enter = await tab.page_reaches("s.dialog", 1.5)
    for kind in ("keyDown", "keyUp"):
        await tab.cmd("Input.dispatchKeyEvent", type=kind, key="Tab", code="Tab", windowsVirtualKeyCode=9,
                      nativeVirtualKeyCode=9)
    tab_key = await tab.page_reaches("s.focusOutside", 1.5)
    return [(held and ready and opened and after.get("card") and not after.get("dialog"),
             f"a dialog opened while deck.js loads, then it fails: the dialog closes under the card ({after})"),
            (enter.get("card") and not enter.get("dialog") and tab.asked.get("/api/devices", 0) == devices_asked,
             f"then Enter on the page under the card opens nothing and asks the server nothing ({enter}, "
             f"{tab.asked.get('/api/devices', 0) - devices_asked} new /api/devices)"),
            (tab_key.get("card") and tab_key.get("focusOutside") is False,
             f"and Tab does not take the focus to the page under the card ({tab_key})")]


async def a_late_pairing_request(tab):
    tab.holding.update({"deck.js", "/api/devices"})
    await open_page(tab)
    held = await tab.tab_reaches(lambda: bool(tab.held.get("deck.js")), CARD_SHOWS_S)
    ready = (await tab.page_reaches("s.handlersIn", CARD_SHOWS_S)).get("handlersIn")
    await tab.js("document.querySelector('#b-disp').click()")
    asked = await tab.tab_reaches(lambda: bool(tab.held.get("/api/devices")), 3.0)
    tab.failing.add("deck.js")
    await tab.release("deck.js", fail=True)
    card = (await tab.page_reaches("s.card", CARD_SHOWS_S)).get("card")
    await tab.release("/api/devices", fail=False)
    after = await tab.page_reaches("s.devicesFailed", 5.0)
    return [(held and ready and asked and card and after.get("devicesFailed") and after.get("card")
             and not after.get("pairing"),
             f"an unpaired phone whose 401 comes after deck.js failed: the pairing form stays closed ({after})")]


def pc_pairing_code(srv):
    srv.confere()
    conn = http.client.HTTPConnection("127.0.0.1", srv.porta, timeout=10)
    try:
        conn.request("GET", "/api/pareamento", headers={"Host": f"localhost:{srv.porta}"})
        return json.loads(conn.getresponse().read())["codigo"]
    finally:
        conn.close()


async def a_pairing_that_answers_after_the_failure(tab):
    code = pc_pairing_code(tab.srv)
    tab.holding.update({"deck.js", "/api/parear"})
    await open_page(tab)
    held = await tab.tab_reaches(lambda: bool(tab.held.get("deck.js")), CARD_SHOWS_S)
    ready = (await tab.page_reaches("s.handlersIn", CARD_SHOWS_S)).get("handlersIn")
    await tab.js("(b => { b.focus(); b.click(); })(document.querySelector('#b-disp'))")
    form = (await tab.page_reaches("s.pairing", 5.0)).get("pairing")
    await tab.js(f"document.querySelector('#pa-in').value = '{code}'; "
                 "document.querySelector('#form-parear').requestSubmit()")
    asked = await tab.tab_reaches(lambda: bool(tab.held.get("/api/parear")), 3.0)
    tab.failing.add("deck.js")
    await tab.release("deck.js", fail=True)
    card = (await tab.page_reaches("s.card", CARD_SHOWS_S)).get("card")
    before = len(tab.api_calls)
    await tab.release("/api/parear", fail=False)
    after = await tab.page_reaches("s.notice", 5.0)
    loads = [name for loader, name in tab.api_calls[before:]
             if loader == tab.loaders[0] and name in ("/api/state", "/api/library", "/api/jobs")]
    return [(held and ready and form and asked and card and after.get("notice") and after.get("card") and not loads,
             f"a pairing that answers after deck.js failed: the card stays and the page does not load ({after}, "
             f"{loads})")]


async def the_shared_file_fails(tab):
    tab.failing.update({"shared.js", "script-failed.js"})
    await open_page(tab)
    before = await tab.page_reaches("s.card", CARD_SHOWS_S)
    tab.failing.clear()
    reloaded = await tab.tab_reaches(lambda: tab.loads >= 2, RELOAD_S)
    after = await tab.page_reaches("!s.card && s.online === true", RELOAD_S) if reloaded else {}
    return [(before.get("card") and reloaded and after.get("online") is True,
             f"shared.js fails, and script-failed.js would: the off-air card, then the page loads again and "
             f"connects ({before}, {after})")]


async def every_file_brings_the_card(tab):
    with urllib.request.urlopen(tab.base + THEME, timeout=10) as r:
        page = r.read().decode("utf-8")
    files = [a["src"] for a, *_ in testa_i18n.script_elements(page) if a.get("src") and a["src"] != "transporte.js"]
    missed = []
    for name in files:
        tab.failing = {name}
        before = tab.contexts
        await tab.cmd("Page.navigate", url=tab.base + THEME)
        await tab.tab_reaches(lambda: tab.contexts > before, CARD_SHOWS_S)
        seen = (await tab.page_reaches("s.cardSeen", CARD_SHOWS_S)).get("cardSeen")
        calls = [path for loader, path in tab.api_calls if loader == tab.loaders[-1]]
        if not seen or calls:
            missed.append((name, seen, calls))
    return [(bool(files) and not missed,
             f"each of the {len(files)} theme files but transporte.js, when it fails, brings the off-air card, visible, with "
             f"no call to the server ({missed or 'all of them'})")]


PC = (a_file_that_fails, a_late_call_counts_for_its_page, the_qr_code_survives, the_qr_code_stays_without_shared_js,
      transporte_alone, a_dialog_opened_before,
      the_shared_file_fails, every_file_brings_the_card)
PHONE = (a_late_pairing_request, a_pairing_that_answers_after_the_failure)


def scenarios(raiz):
    results = []
    for role, extras, runs in (("pc", [], PC), ("phone", ["--papel-local", "celular"], PHONE)):
        with tempfile.TemporaryDirectory(prefix=f"ritmelli-missing-{role}-") as folder:
            tmp = Path(folder)
            with open(tmp / "server.log", "w", encoding="utf-8") as log:
                srv = compara.sobe_servidor(tmp, so_mock.free_port(), log, raiz=raiz, config={"boas_vindas": True},
                                            extras=extras)
                try:
                    for run in runs:
                        results += asyncio.run(with_tab(srv, run))
                finally:
                    compara.para_servidor(srv)
    return results


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="The theme page when one of its script files does not load, in a "
                                             "headless Chrome against --mock servers of its own (one as the PC, one "
                                             "as an unpaired phone). Exit 1 if a scenario fails.")
    ap.add_argument("--raiz", type=Path, default=RAIZ, help="the checkout whose server.py and theme are served")
    args = ap.parse_args(argv)
    results = scenarios(args.raiz.resolve())
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if results and all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
