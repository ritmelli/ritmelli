import argparse
import asyncio
import importlib
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
compara = importlib.import_module("compara")
so_mock = importlib.import_module("so_mock")
missing_script = importlib.import_module("missing_script")

RAIZ = Path(__file__).resolve().parent.parent
SUSPENDED = "(function* () {%s\n;eval('');\n})()"
SAMPLES = (
    ("a function in two scripts", ("'use strict';\nfunction a() {}", "'use strict';\nfunction a() {}"), {"a"}),
    ("a let in two scripts", ("'use strict';\nlet b = 1;", "'use strict';\nlet b = 2;"), {"b"}),
    ("a const and a class", ("'use strict';\nconst c = 1;", "'use strict';\nclass c {}"), {"c"}),
    ("a var in two scripts", ("var d;", "var d = 1;"), {"d"}),
    ("a function and a let", ("function e() {}", "let e;"), {"e"}),
    ("a var the window already has", ("var name;", "var name = 'other';"), {"name"}),
    ("a var and a function the window already has", ("var open;", "function open() {}"), {"open"}),
    ("names inside functions and blocks", ("'use strict';\nfunction f() { var x; let y; }\n{ let z; }",
                                           "'use strict';\nfunction g() { var x; let y; }\n{ let z; }"), set()),
    ("a block function in strict mode", ("/* A-INICIO */\n'use strict';\n{ function h() {} }",
                                         "'custom';\n'use strict';\n{ function h() {} }"), set()),
)
KNOWN_FAILURES = (
    ("a sloppy var named arguments", ("var arguments;", "var arguments;"), {"arguments"}),
    ("a sloppy const named yield", ("const yield = 1;", "const yield = 2;"), {"yield"}),
)
BROKEN_SAMPLE = "'use strict';\nlet i = ;"
FEATURE_HANDLERS = (
    ("search.js", "ui-events.js", "#q", "input"), ("search.js", "ui-events.js", "#q", "keydown"),
    ("search.js", "ui-events.js", "#form-busca", "submit"), ("search.js", "ui-events.js", "#b-voltar", "click"),
    ("search.js", "ui-events.js", "#b-sair-busca", "click"), ("search.js", "ui-events.js", "#b-limpar-q", "click"),
    ("search.js", "queue.js", "#resultados", "click"), ("search.js", "queue.js", "#resultados", "pointerdown"),
    ("search.js", "queue.js", "#resultados", "pointermove"), ("search.js", "queue.js", "#resultados", "pointerup"),
    ("search.js", "queue.js", "#resultados", "pointercancel"),
    ("voice-effects.js", "ui-events.js", "#gaveta", "click"), ("voice-effects.js", "ui-events.js", "#gaveta-dir", "click"),
    ("voice-effects.js", "ui-events.js", "#desliga-ef", "click"), ("voice-effects.js", "ui-events.js", "#b-efeito", "click"),
    ("voice-effects.js", "ui-events.js", "#b-fechar-gav", "click"),
    ("voice-effects.js", "ui-events.js", "#b-ouvir", "click"), ("voice-effects.js", "ui-events.js", "#mini-ef", "click"),
    ("turntable.js", "ui-events.js", "#b-anterior", "click"), ("turntable.js", "ui-events.js", "#b-proxima", "click"),
    ("turntable.js", "ui-events.js", "#b-aleatorio", "click"), ("turntable.js", "ui-events.js", "#b-repetir", "click"),
    ("turntable.js", "ui-events.js", "#seek", "input"), ("turntable.js", "ui-events.js", "#seek", "change"),
    ("turntable.js", "ui-events.js", "#seek", "keydown"),
    ("receiver.js", "ui-events.js", "#b-cortar", "click"), ("receiver.js", "ui-events.js", "#b-nivelar", "click"),
    ("receiver.js", "ui-events.js", "#f-vol", "input"), ("receiver.js", "ui-events.js", "#f-mon", "input"),
    ("receiver.js", "ui-events.js", "#f-mic", "input"), ("receiver.js", "ui-events.js", "#mini-cortar", "click"),
    ("receiver.js", "ui-events.js", "#b-mudo-topo", "click"), ("receiver.js", "ui-events.js", "#palco-cortar", "click"),
    ("commands.js", "ui-events.js", "#b-tocar", "click"), ("commands.js", "ui-events.js", "#mini-tocar", "click"),
    ("shelf.js", "ui-events.js", "#estante", "click"), ("shelf.js", "ui-events.js", "#estante", "contextmenu"),
    ("shelf.js", "ui-events.js", "#estante", "pointerdown"),
    ("shelf.js", "ui-events.js", "#chips", "click"), ("shelf.js", "ui-events.js", "#chips", "contextmenu"),
    ("shelf.js", "ui-events.js", "#cartoes", "click"),
    ("stage.js", "ui-events.js", "#mini-abrir", "click"), ("stage.js", "ui-events.js", "#mini-seta", "click"),
    ("stage.js", "ui-events.js", "#mini-ant", "click"), ("stage.js", "ui-events.js", "#mini-prox", "click"),
    ("stage.js", "ui-events.js", "#b-fechar-palco", "click"), ("stage.js", "ui-events.js", "#palco", "pointerdown"),
    ("disc-page.js", "ui-events.js", "#b-pagina", "click"),
    ("phone.js", "ui-events.js", "#b-cel", "click"), ("devices.js", "ui-events.js", "#b-disp", "click"),
    ("devices.js", "ui-events.js", "#dica-ouvir", "click"), ("devices.js", "ui-events.js", "#b-desligar", "click"),
    ("options.js", "options.js", "#menu", "click"), ("options.js", "options.js", "#menu", "keydown"),
    ("options.js", "options.js", "#menu", "pointerdown"), ("options.js", "options.js", "#menu-fundo", "click"),
    ("dialogs.js", "dialogs.js", "#dn-nao", "click"),
    ("metrics.js", "metrics.js", "#dd-met-btn", "click"), ("metrics.js", "metrics.js", "#dlg-metricas", "close"),
    ("devices.js", "devices.js", "#dd-mic", "change"), ("devices.js", "devices.js", "#dd-mon", "change"),
    ("phone.js", "phone.js", "#dlg-cel", "close"), ("phone.js", "phone.js", "#dcel-lista", "click"),
    ("phone.js", "phone.js", "#dcel-outro", "click"),
    ("update.js", "update.js", "#b-atualizar", "click"), ("update.js", "update.js", "#da-ok", "click"),
    ("options.js", "options.js", "#menu", "scroll"), ("options.js", "options.js", "#menu", "pointermove"),
    ("options.js", "options.js", "#menu", "pointerup"), ("options.js", "options.js", "#menu", "pointercancel"),
    ("options.js", "options.js", "#menu", "touchmove"), ("options.js", "options.js", "#menu", "click:capture"),
    ("options.js", "options.js", "document", "pointerdown"), ("options.js", "options.js", "window", "resize"),
    ("connection.js", "connection.js", "window", "online"), ("connection.js", "connection.js", "window", "offline"),
    ("pairing.js", "pairing.js", "#form-parear", "submit"),
    ("welcome.js", "welcome.js", "#dlg-boas", "close"), ("welcome.js", "welcome.js", "#dlg-disp", "close"),
    ("desk-buttons.js", "ui-events.js", "#tocar-d", "click"), ("desk-buttons.js", "ui-events.js", "#prox-d", "click"),
    ("desk-buttons.js", "ui-events.js", "#m-aleatorio", "click"), ("desk-buttons.js", "ui-events.js", "#m-repetir", "click"),
    ("desk-buttons.js", "ui-events.js", "#m-parecidas", "click"), ("desk-buttons.js", "ui-events.js", "#pads-grade", "click"),
    ("desk-buttons.js", "ui-events.js", "#pads-grade", "contextmenu"),
    ("desk-buttons.js", "ui-events.js", "#prat-esq", "click"), ("desk-buttons.js", "ui-events.js", "#prat-dir", "click"),
    ("start.js", "start.js", "document", "DOMContentLoaded"),
    ("desk-buttons.js", "ui-events.js", "#estante", "scroll"), ("start.js", "start.js", "document", "visibilitychange"),
    ("connection.js", "connection.js", "navigator.connection", "change"),
    ("dj-desk.js", "ui-events.js", "mqUnica", "change"),
)
SHARED_TARGETS = ("window", "document", "navigator.connection", "mqUnica")
SHARED_HANDLERS = (("#estante", "scroll"),)
INLINE_STAYS = (("document", "DOMContentLoaded"),)
MARK = re.compile(r"/\* ([A-Z0-9-]+)-JS-INICIO \*/")
RAN_BEFORE = {"queue.js": "fecharMenu", "ui-events.js": "abrirDispositivos"}
STILL_ON = (("#b-disp", "click"), ("#b-cortar", "click"), ("#f-vol", "input"), ("#b-anterior", "click"),
            ("#seek", "input"), ("#estante", "click"), ("#mini-abrir", "click"), ("#b-pagina", "click"))
STILL_OFF = (("#b-ouvir", "click"), ("#gaveta", "click"), ("#q", "input"), ("#resultados", "click"))
FORM_INERT = ("the search form stays inert", "document.getElementById('form-busca')?.inert === true")
NO_STARTUP = ("the startup does not run", "document.getElementById('mini-cortar')?.innerHTML === ''")
DESK_ON = (("#tocar-d", "click"), ("#pads-grade", "click"), ("#prat-dir", "click"))
EARLIER_FAILURES = (
    ("gerado/pecas.js", (), (), (FORM_INERT,)),
    ("dj-visor.js", (("#b-disp", "click"),), STILL_OFF, (FORM_INERT,)),
    ("receiver.js", (("#estante", "click"), ("#mini-tocar", "click")), (("#mini-abrir", "click"), ("#b-disp", "click")),
     (FORM_INERT,)),
    ("turntable.js", (("#estante", "click"), ("#mini-tocar", "click"), ("#mini-cortar", "click"), ("#b-pagina", "click")),
     (("#mini-abrir", "click"), ("#b-disp", "click")), (FORM_INERT,)),
    ("voice-effects.js", STILL_ON, STILL_OFF, (FORM_INERT,)),
    ("disc-page.js", DESK_ON, (), (NO_STARTUP,)),
    ("dj-desk.js", DESK_ON, (), (NO_STARTUP,)),
    ("queue.js", DESK_ON, (), (NO_STARTUP,)),
    ("search.js", STILL_ON + (("#rolo-busca", "scroll"),), STILL_OFF,
     (("the mesa builds the effects drawer", "!!document.querySelector('#banco .aviso-gav:not([data-i18n])')"), FORM_INERT)),
)
SEARCH_OPEN = ("(() => { const q = document.getElementById('q'); q.value = 'abc';"
               " document.getElementById('form-busca').requestSubmit(); })()")
OUTSIDE_TOUCH = ("document.getElementById('estante').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true,"
                 " cancelable: true, composed: true, isPrimary: true, pointerId: 7, pointerType: 'touch', button: 0,"
                 " clientX: 11, clientY: 13}))")
PAGE_READY_S = 15.0


async def until(tab, state, condition, seconds):
    r = await tab.cmd("Runtime.evaluate", awaitPromise=True, returnByValue=True,
                      expression=missing_script.WAIT_IN_PAGE % (state, condition, int(seconds * 1000)))
    return r.get("result", {}).get("value") or {}


async def names_of(tab, source):
    made = await tab.cmd("Runtime.evaluate", expression=SUSPENDED % source)
    if "exceptionDetails" in made:
        return None, made["exceptionDetails"]["exception"].get("description", "does not compile")
    internal = (await tab.cmd("Runtime.getProperties", objectId=made["result"]["objectId"],
                              ownProperties=True)).get("internalProperties", [])
    scopes = next(p["value"]["objectId"] for p in internal if p["name"] == "[[Scopes]]")
    chain = (await tab.cmd("Runtime.getProperties", objectId=scopes, ownProperties=True))["result"]
    local = next(s["value"]["objectId"] for s in chain if s.get("value", {}).get("description") == "Local")
    names = (await tab.cmd("Runtime.getProperties", objectId=local, ownProperties=True))["result"]
    return {p["name"] for p in names} - {"arguments"}, None


async def top_level_names(tab, scripts):
    owners, errors = {}, []
    for label, source in scripts:
        names, error = await names_of(tab, source)
        if error:
            errors.append(f"{label}: {error}")
            continue
        for name in names:
            owners.setdefault(name, []).append(label)
    return {name: where for name, where in owners.items() if len(where) > 1}, errors


async def page_scripts(tab):
    found = []
    for s in tab.scripts:
        aux = s.get("executionContextAuxData") or {}
        if aux.get("isDefault") and so_mock.mesma_origem(s["url"], tab.base):
            name = missing_script.theme_file(s["url"])
            label = name if name and not name.startswith("?") else f"index.html:{s['startLine'] + 1}"
            source = (await tab.cmd("Debugger.getScriptSource", scriptId=s["scriptId"]))["scriptSource"]
            found.append((label, source))
    return found


async def handler_files(tab, selector, kind):
    kind, _, phase = kind.partition(":")
    found = selector if selector in SHARED_TARGETS else f"document.querySelector({json.dumps(selector)})"
    node = await tab.cmd("Runtime.evaluate", expression=found)
    target = node["result"].get("objectId")
    if not target:
        return None
    listeners = (await tab.cmd("DOMDebugger.getEventListeners", objectId=target))["listeners"]
    return sorted({await script_file(tab, x["scriptId"]) for x in listeners
                   if x["type"] == kind and x["useCapture"] == (phase == "capture")})


async def script_file(tab, script_id):
    url = next((s["url"] for s in tab.scripts if s["scriptId"] == script_id), "")
    name = missing_script.theme_file(url)
    if name:
        return name
    source = (await tab.cmd("Debugger.getScriptSource", scriptId=script_id))["scriptSource"]
    mark = MARK.match(source.lstrip())
    return f"{mark.group(1).lower()}.js" if mark else "index.html"


async def checks(tab):
    await tab.cmd("Debugger.enable")
    await missing_script.open_page(tab)
    await tab.tab_reaches(lambda: tab.loads >= 1, PAGE_READY_S)
    ready = await until(tab, "({mesa: typeof MESA !== 'undefined' && MESA.montada, online: typeof S !== 'undefined'"
                             " && S.online, scripts: document.scripts.length})", "s.mesa && s.online", PAGE_READY_S)
    results = []

    for title, sources, expected in SAMPLES:
        twice, errors = await top_level_names(tab, [(f"{title} {n}", s) for n, s in enumerate(sources, 1)])
        results.append((not errors and set(twice) == expected,
                        f"the name reader on {title}: {sorted(twice) or 'no name'} in more than one script"
                        f"{', ' + '; '.join(errors) if errors else ''}"))
    for title, sources, expected in KNOWN_FAILURES:
        twice, errors = await top_level_names(tab, [(f"{title} {n}", s) for n, s in enumerate(sources, 1)])
        fixed = not errors and set(twice) == expected
        results.append((not fixed, f"known failure #239 passes now on {title}: make it a regular sample and close the "
                                   f"issue" if fixed else f"known failure #239: the name reader on {title} gives "
                                                          f"{sorted(twice)}{', ' + '; '.join(errors) if errors else ''}"))
    _, errors = await top_level_names(tab, [("a broken script", BROKEN_SAMPLE)])
    results.append((bool(errors), f"the name reader on a script that does not compile reports it ({errors})"))

    scripts = await page_scripts(tab)
    twice, errors = await top_level_names(tab, scripts)
    results.append((ready.get("mesa") and len(scripts) == ready.get("scripts") and not twice and not errors,
                    f"every top-level name of the theme page is declared by one script ({len(scripts)} scripts read, "
                    f"{ready.get('scripts')} in the page; {twice or 'no name twice'}"
                    f"{'; ' + '; '.join(errors) if errors else ''})"))

    for file, _, selector, kind in FEATURE_HANDLERS:
        files = await handler_files(tab, selector, kind)
        moved = (files == [file] if selector not in SHARED_TARGETS and (selector, kind) not in SHARED_HANDLERS
                 else bool(files) and file in files
                 and ("index.html" not in files or (selector, kind) in INLINE_STAYS))
        results.append((moved, f"the {kind} handler of {selector} is in {file} ({files})"))

    await tab.js(SEARCH_OPEN)
    opened = await until(tab, "({open: !!S.busca && !document.getElementById('vista-busca').hidden})", "s.open", 5.0)
    await tab.js(OUTSIDE_TOUCH)
    after = await tab.js("({closed: S.busca === null, touch: ultimoToque})")
    results.append((opened.get("open") and after.get("closed") and after.get("touch") == {"x": 11, "y": 13},
                    f"a touch outside the search on the mesa closes it, and queue.js still sees that touch ({after})"))
    return results


def held_until(activation):
    async def run(tab):
        await tab.cmd("Debugger.enable")
        tab.holding.add(activation)
        await missing_script.open_page(tab)
        state = await until(tab, f"({{ran: typeof {RAN_BEFORE[activation]} === 'function',"
                                 " inert: document.getElementById('form-busca')?.inert})", "s.ran", PAGE_READY_S)
        early = {}
        for file, at, selector, kind in FEATURE_HANDLERS:
            if at == activation:
                files = await handler_files(tab, selector, kind)
                early[f"{kind} {selector}"] = [f for f in files or [] if f == file]
        await tab.release(activation, fail=False)
        results = [(state.get("ran") and not any(early.values()),
                    f"with {activation} still loading, the handlers it turns on are not on yet ({early})")]
        if activation == "ui-events.js":
            results.append((state.get("ran") and state.get("inert") is True,
                            f"with ui-events.js still loading, the search form is inert ({state})"))
        return results
    return run


def after_a_failure(missing, expected, off, page_checks):
    async def run(tab):
        await tab.cmd("Debugger.enable")
        tab.failing.add(missing)
        tab.holding.add("deck.js")
        await missing_script.open_page(tab)
        state = await until(tab, "({ran: !!document.querySelector('script[src=\"deck.js\"]')"
                                 + "".join(f", {json.dumps(t)}: {e}" for t, e in page_checks) + "})", "s.ran",
                            PAGE_READY_S)
        found = {f"{kind} {selector}": await handler_files(tab, selector, kind) for selector, kind in expected}
        early = {f"{kind} {selector}": await handler_files(tab, selector, kind) for selector, kind in off}
        await tab.release("deck.js", fail=False)
        results = [(state.get("ran") and all(found.values()),
                    f"with {missing} failed and deck.js loading, these handlers are on ({found})"),
                   (state.get("ran") and not any(early.values()),
                    f"with {missing} failed and deck.js loading, these handlers are not on ({early})")]
        results += [(state.get("ran") and state.get(title) is True, f"with {missing} failed, {title} ({state})")
                    for title, _ in page_checks]
        return results
    return run


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="The theme's scripts in a headless Chrome against a --mock server of its "
                                             "own: every top-level name declared by one script only (read by V8), the "
                                             "search and voice effects handlers in their own files and turned on where "
                                             "they were, even after an earlier file failed, and the search's outside touch on the mesa. Exit 1 if a check "
                                             "fails.")
    ap.add_argument("--raiz", type=Path, default=RAIZ, help="the checkout whose server.py and theme are served")
    args = ap.parse_args(argv)
    results = []
    with tempfile.TemporaryDirectory(prefix="ritmelli-scripts-") as folder:
        tmp = Path(folder)
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = compara.sobe_servidor(tmp, so_mock.free_port(), log, raiz=args.raiz.resolve(),
                                        config={"boas_vindas": True})
            try:
                for run in (checks, *(held_until(a) for a in RAN_BEFORE),
                            *(after_a_failure(*f) for f in EARLIER_FAILURES)):
                    results += asyncio.run(missing_script.with_tab(srv, run))
            finally:
                compara.para_servidor(srv)
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if results and all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
