import argparse
import asyncio
import importlib
import json
import re
import sys
import tempfile
import urllib.parse
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
    ("search.js", "#q", "input"), ("search.js", "#q", "keydown"),
    ("search.js", "#form-busca", "submit"), ("search.js", "#b-voltar", "click"),
    ("search.js", "#b-sair-busca", "click"), ("search.js", "#b-limpar-q", "click"),
    ("search.js", "#resultados", "click"), ("search.js", "#resultados", "pointerdown"),
    ("search.js", "#resultados", "pointermove"), ("search.js", "#resultados", "pointerup"),
    ("search.js", "#resultados", "pointercancel"),
    ("voice-effects.js", "#gaveta", "click"), ("voice-effects.js", "#gaveta-dir", "click"),
    ("voice-effects.js", "#desliga-ef", "click"), ("voice-effects.js", "#b-efeito", "click"),
    ("voice-effects.js", "#b-fechar-gav", "click"),
    ("voice-effects.js", "#b-ouvir", "click"), ("voice-effects.js", "#mini-ef", "click"),
    ("turntable.js", "#b-anterior", "click"), ("turntable.js", "#b-proxima", "click"),
    ("turntable.js", "#b-aleatorio", "click"), ("turntable.js", "#b-repetir", "click"),
    ("turntable.js", "#seek", "input"), ("turntable.js", "#seek", "change"),
    ("turntable.js", "#seek", "keydown"),
    ("receiver.js", "#b-cortar", "click"), ("receiver.js", "#b-nivelar", "click"),
    ("receiver.js", "#f-vol", "input"), ("receiver.js", "#f-mon", "input"),
    ("receiver.js", "#f-mic", "input"), ("receiver.js", "#mini-cortar", "click"),
    ("receiver.js", "#b-mudo-topo", "click"), ("receiver.js", "#palco-cortar", "click"),
    ("commands.js", "#b-tocar", "click"), ("commands.js", "#mini-tocar", "click"),
    ("shelf.js", "#estante", "click"), ("shelf.js", "#estante", "contextmenu"),
    ("shelf.js", "#estante", "pointerdown"),
    ("shelf.js", "#chips", "click"), ("shelf.js", "#chips", "contextmenu"),
    ("shelf.js", "#cartoes", "click"),
    ("stage.js", "#mini-abrir", "click"), ("stage.js", "#mini-seta", "click"),
    ("stage.js", "#mini-ant", "click"), ("stage.js", "#mini-prox", "click"),
    ("stage.js", "#b-fechar-palco", "click"), ("stage.js", "#palco", "pointerdown"),
    ("disc-page.js", "#b-pagina", "click"),
    ("phone.js", "#b-cel", "click"), ("devices.js", "#b-disp", "click"),
    ("devices.js", "#dica-ouvir", "click"), ("devices.js", "#b-desligar", "click"),
    ("options.js", "#menu", "click"), ("options.js", "#menu", "keydown"),
    ("options.js", "#menu", "pointerdown"), ("options.js", "#menu-fundo", "click"),
    ("dialogs.js", "#dn-nao", "click"),
    ("metrics.js", "#dd-met-btn", "click"), ("metrics.js", "#dlg-metricas", "close"),
    ("devices.js", "#dd-mic", "change"), ("devices.js", "#dd-mon", "change"),
    ("phone.js", "#dlg-cel", "close"), ("phone.js", "#dcel-lista", "click"),
    ("phone.js", "#dcel-outro", "click"),
    ("update.js", "#b-atualizar", "click"), ("update.js", "#da-ok", "click"),
    ("options.js", "#menu", "scroll"), ("options.js", "#menu", "pointermove"),
    ("options.js", "#menu", "pointerup"), ("options.js", "#menu", "pointercancel"),
    ("options.js", "#menu", "touchmove"), ("options.js", "#menu", "click:capture"),
    ("options.js", "document", "pointerdown"), ("options.js", "window", "resize"),
    ("connection.js", "window", "online"), ("connection.js", "window", "offline"),
    ("pairing.js", "#form-parear", "submit"),
    ("welcome.js", "#dlg-boas", "close"), ("welcome.js", "#dlg-disp", "close"),
    ("desk-buttons.js", "#tocar-d", "click"), ("desk-buttons.js", "#prox-d", "click"),
    ("desk-buttons.js", "#m-aleatorio", "click"), ("desk-buttons.js", "#m-repetir", "click"),
    ("desk-buttons.js", "#m-parecidas", "click"), ("desk-buttons.js", "#pads-grade", "click"),
    ("desk-buttons.js", "#pads-grade", "contextmenu"),
    ("desk-buttons.js", "#prat-esq", "click"), ("desk-buttons.js", "#prat-dir", "click"),
    ("start.js", "document", "DOMContentLoaded"),
    ("desk-buttons.js", "#estante", "scroll"), ("start.js", "document", "visibilitychange"),
    ("connection.js", "navigator.connection", "change"),
    ("dj-desk.js", "mqUnica", "change"),
)
SHARED_TARGETS = ("window", "document", "navigator.connection", "mqUnica")
SHARED_HANDLERS = (("#estante", "scroll"),)
REGISTERED_WHEN = ("(() => { const add = EventTarget.prototype.addEventListener; window.visibilityWhen = [];"
                   " EventTarget.prototype.addEventListener = function (type, fn, ...rest) {"
                   " if (this === document && type === 'visibilitychange') window.visibilityWhen.push({"
                   " readyState: document.readyState, carregar: typeof carregar,"
                   " connects: String(fn).includes('conectar(') });"
                   " return add.call(this, type, fn, ...rest); }; })()")
SEARCH_OPEN = ("(() => { const q = document.getElementById('q'); q.value = 'abc';"
               " document.getElementById('form-busca').requestSubmit(); })()")
OUTSIDE_TOUCH = ("document.getElementById('estante').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true,"
                 " cancelable: true, composed: true, isPrimary: true, pointerId: 7, pointerType: 'touch', button: 0,"
                 " clientX: 11, clientY: 13}))")
REDRAWN_CANVASES = {"the mixer": "canvas.mx-px", "the monitor": "#tv > canvas.tv-px",
                    "the pads": "#pads > canvas.pads-px"}
CANVAS_REDRAWN = ("(async () => { const c = document.querySelector(%s);"
                " if (!c || !c.width) return {canvas: false};"
                " const frame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));"
                " const drawn = c.toDataURL(); c.getContext('2d').clearRect(0, 0, c.width, c.height);"
                " const cleared = c.toDataURL(); await frame(); const stays = c.toDataURL() === cleared;"
                " document.dispatchEvent(new Event('repinta-canvas')); await frame();"
                " return {canvas: true, drawn: drawn !== cleared, stays, back: c.toDataURL() === drawn}; })()")
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


async def script_name(tab, script):
    source = (await tab.cmd("Debugger.getScriptSource", scriptId=script["scriptId"]))["scriptSource"]
    path = urllib.parse.urlsplit(script["url"]).path
    if path.startswith(missing_script.THEME) and path != missing_script.THEME:
        return path.removeprefix(missing_script.THEME), source
    return tab.files.get(source), source


async def page_scripts(tab):
    found = []
    for s in tab.scripts:
        aux = s.get("executionContextAuxData") or {}
        if aux.get("isDefault") and not s.get("isModule") and so_mock.mesma_origem(s["url"], tab.base):
            name, source = await script_name(tab, s)
            found.append((name or f"index.html:{s['startLine'] + 1}", source))
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
    name, _ = await script_name(tab, next(s for s in tab.scripts if s["scriptId"] == script_id))
    return name or "index.html"


async def checks(tab):
    await tab.cmd("Debugger.enable")
    await tab.cmd("Page.addScriptToEvaluateOnNewDocument", source=REGISTERED_WHEN)
    await missing_script.open_page(tab)
    await tab.tab_reaches(lambda: tab.loads >= 1, PAGE_READY_S)
    ready = await until(tab, "({mesa: typeof MESA !== 'undefined' && MESA.montada, online: typeof S !== 'undefined'"
                             " && S.online, scripts: [...document.scripts].filter(s => !['module', 'importmap']"
                             ".includes(s.type)).length})", "s.mesa && s.online", PAGE_READY_S)
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

    for file, selector, kind in FEATURE_HANDLERS:
        files = await handler_files(tab, selector, kind)
        moved = (files == [file] if selector not in SHARED_TARGETS and (selector, kind) not in SHARED_HANDLERS
                 else bool(files) and file in files and "index.html" not in files)
        results.append((moved, f"the {kind} handler of {selector} is in {file} ({files})"))

    registered = [r for r in await tab.js("visibilityWhen") or [] if r.get("connects")]
    results.append((bool(registered) and all(r == {"readyState": "interactive", "carregar": "function", "connects": True}
                                             for r in registered),
                    f"the page starts watching its visibility in the DOMContentLoaded, once carregar() is there, so a "
                    f"tab shown while the page loads does not connect before it starts ({registered})"))

    await tab.js(SEARCH_OPEN)
    opened = await until(tab, "({open: !!S.busca && !document.getElementById('vista-busca').hidden})", "s.open", 5.0)
    await tab.js(OUTSIDE_TOUCH)
    after = await tab.js("({closed: S.busca === null, touch: ultimoToque})")
    results.append((opened.get("open") and after.get("closed") and after.get("touch") == {"x": 11, "y": 13},
                    f"a touch outside the search on the mesa closes it, and queue.js still sees that touch ({after})"))

    for what, selector in REDRAWN_CANVASES.items():
        seen = (await tab.cmd("Runtime.evaluate", expression=CANVAS_REDRAWN % json.dumps(selector), awaitPromise=True,
                              returnByValue=True)).get("result", {}).get("value") or {}
        results.append((seen == {"canvas": True, "drawn": True, "stays": True, "back": True},
                        f"the canvas of {what}, cleared, stays cleared until a repinta-canvas, and then draws it "
                        f"again ({seen})"))
    return results


def inline_scripts(raiz):
    found, _ = missing_script.page_files(raiz, missing_script.THEME)
    return {text + (missing_script.theme_page.source_url(name) if kind == "module" else ""): name
            for kind, name, text in found or [] if kind in ("script", "module")}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="The theme's scripts in a headless Chrome against a --mock server of its "
                                             "own: every top-level name declared by one script only (read by V8), "
                                             "each handler in the file of its part, the visibility watched from the "
                                             "DOMContentLoaded and the search's outside touch on the mesa. Exit 1 if a "
                                             "check fails.")
    ap.add_argument("--raiz", type=Path, default=RAIZ, help="the checkout whose server.py and theme are served")
    args = ap.parse_args(argv)
    results = []
    with tempfile.TemporaryDirectory(prefix="ritmelli-scripts-") as folder:
        tmp = Path(folder)
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = compara.sobe_servidor(tmp, so_mock.free_port(), log, raiz=args.raiz.resolve(),
                                        config={"boas_vindas": True})
            try:
                files = inline_scripts(args.raiz.resolve())

                async def run(tab):
                    tab.files = files
                    return await checks(tab)
                results += asyncio.run(missing_script.with_tab(srv, run))
            finally:
                compara.para_servidor(srv)
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if results and all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
