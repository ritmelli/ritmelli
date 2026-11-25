import argparse
import asyncio
import importlib
import json
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
)
RAN_BEFORE = {"queue.js": "fecharMenu", "ui-events.js": "abrirDispositivos"}
EARLIER_FAILURES = (
    ("voice-effects.js", (("index.html", "#b-disp", "click"),)),
    ("search.js", (("index.html", "#b-disp", "click"), ("queue.js", "#rolo-busca", "scroll"))),
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
    node = await tab.cmd("Runtime.evaluate", expression=f"document.querySelector({json.dumps(selector)})")
    target = node["result"].get("objectId")
    if not target:
        return None
    urls = {s["scriptId"]: s["url"] for s in tab.scripts}
    listeners = (await tab.cmd("DOMDebugger.getEventListeners", objectId=target))["listeners"]
    return sorted({missing_script.theme_file(urls.get(x["scriptId"], "")) or "index.html" for x in listeners
                   if x["type"] == kind})


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
        results.append((files == [file], f"the {kind} handler of {selector} is in {file} ({files})"))

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
        for _, at, selector, kind in FEATURE_HANDLERS:
            if at == activation:
                early[f"{kind} {selector}"] = await handler_files(tab, selector, kind)
        await tab.release(activation, fail=False)
        results = [(state.get("ran") and not any(early.values()),
                    f"with {activation} still loading, the handlers it turns on are not on yet ({early})")]
        if activation == "ui-events.js":
            results.append((state.get("ran") and state.get("inert") is True,
                            f"with ui-events.js still loading, the search form is inert ({state})"))
        return results
    return run


def after_a_failure(missing, expected):
    async def run(tab):
        await tab.cmd("Debugger.enable")
        tab.failing.add(missing)
        tab.holding.add("deck.js")
        await missing_script.open_page(tab)
        state = await until(tab, "({ran: !!document.querySelector('#ant-d svg')})", "s.ran", PAGE_READY_S)
        found = {f"{kind} {selector}": await handler_files(tab, selector, kind) for _, selector, kind in expected}
        await tab.release("deck.js", fail=False)
        return [(state.get("ran") and all(found[f"{kind} {selector}"] == [file] for file, selector, kind in expected),
                 f"with {missing} failed, the handlers registered after its binder still are ({found})")]
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
                            *(after_a_failure(m, e) for m, e in EARLIER_FAILURES)):
                    results += asyncio.run(missing_script.with_tab(srv, run))
            finally:
                compara.para_servidor(srv)
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if results and all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
