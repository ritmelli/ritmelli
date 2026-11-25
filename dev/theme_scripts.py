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
PROLOGUE = re.compile(r"(?:\s+|/\*[\s\S]*?\*/|//[^\n]*)*(?:(['\"])use strict\1\s*;?)?")
SNAPSHOT = ("(() => { const m = new Map(); for (const n of Object.getOwnPropertyNames(globalThis)) {"
            " const d = Object.getOwnPropertyDescriptor(globalThis, n); m.set(n, 'value' in d ? d.value : d.get); }"
            " globalThis[Symbol.for('names before')] = m; })()")
CHANGED = ("(() => { const m = globalThis[Symbol.for('names before')];"
           " return Object.getOwnPropertyNames(globalThis).filter(n => {"
           " const d = Object.getOwnPropertyDescriptor(globalThis, n);"
           " return !m.has(n) || !Object.is(m.get(n), 'value' in d ? d.value : d.get); }); })()")
SAMPLES = (
    ("a function in two scripts", ("'use strict';\nfunction a() {}", "'use strict';\nfunction a() {}"), {"a"}),
    ("a let in two scripts", ("'use strict';\nlet b = 1;", "'use strict';\nlet b = 2;"), {"b"}),
    ("a const and a class", ("'use strict';\nconst c = 1;", "'use strict';\nclass c {}"), {"c"}),
    ("a var in two scripts", ("var d;", "var d = 1;"), {"d"}),
    ("a function and a let", ("function e() {}", "let e;"), {"e"}),
    ("a name the window already has", ("function open() {}", "function open() {}"), {"open"}),
    ("names inside functions and blocks", ("'use strict';\nfunction f() { var x; let y; }\n{ let z; }",
                                           "'use strict';\nfunction g() { var x; let y; }\n{ let z; }"), set()),
    ("a block function after the strict mode", ("/* A-INICIO */\n'use strict';\n{ function h() {} }",
                                               "// B\n'use strict';\n{ function h() {} }"), set()),
)
BROKEN_SAMPLE = "'use strict';\nlet i = ;"
FEATURE_HANDLERS = (
    ("search.js", "#q", "input"), ("search.js", "#q", "keydown"), ("search.js", "#form-busca", "submit"),
    ("search.js", "#b-voltar", "click"), ("search.js", "#b-sair-busca", "click"), ("search.js", "#b-limpar-q", "click"),
    ("voice-effects.js", "#gaveta", "click"), ("voice-effects.js", "#gaveta-dir", "click"),
    ("voice-effects.js", "#desliga-ef", "click"), ("voice-effects.js", "#b-efeito", "click"),
    ("voice-effects.js", "#b-fechar-gav", "click"),
)
SEARCH_OPEN = ("(() => { const q = document.getElementById('q'); q.value = 'abc';"
               " document.getElementById('form-busca').requestSubmit(); })()")
OUTSIDE_TOUCH = ("document.getElementById('estante').dispatchEvent(new PointerEvent('pointerdown', {bubbles: true,"
                 " cancelable: true, composed: true, isPrimary: true, pointerId: 7, pointerType: 'touch', button: 0,"
                 " clientX: 11, clientY: 13}))")
PAGE_READY_S = 15.0


def guarded(source):
    end = PROLOGUE.match(source).end()
    return source[:end] + "\n;throw 0;" + source[end:]


async def until(tab, state, condition, seconds):
    r = await tab.cmd("Runtime.evaluate", awaitPromise=True, returnByValue=True,
                      expression=missing_script.WAIT_IN_PAGE % (state, condition, int(seconds * 1000)))
    return r.get("result", {}).get("value") or {}


async def names_of(tab, frame, label, source):
    ctx = (await tab.cmd("Page.createIsolatedWorld", frameId=frame, worldName=f"names of {label}"))["executionContextId"]
    await tab.cmd("Runtime.evaluate", expression=SNAPSHOT, contextId=ctx)
    compiled = await tab.cmd("Runtime.compileScript", expression=guarded(source), sourceURL=label, persistScript=True,
                             executionContextId=ctx)
    if "exceptionDetails" in compiled:
        return None, compiled["exceptionDetails"]["exception"].get("description", "does not compile")
    ran = await tab.cmd("Runtime.runScript", scriptId=compiled["scriptId"], executionContextId=ctx, returnByValue=True)
    thrown = ran.get("exceptionDetails", {}).get("exception", {})
    if thrown.get("value") != 0:
        return None, f"does not stop before its first statement ({thrown.get('description') or ran.get('result')})"
    lexical = (await tab.cmd("Runtime.globalLexicalScopeNames", executionContextId=ctx))["names"]
    changed = await tab.cmd("Runtime.evaluate", expression=CHANGED, contextId=ctx, returnByValue=True)
    return set(lexical) | set(changed["result"]["value"]), None


async def top_level_names(tab, frame, scripts):
    owners, errors = {}, []
    for label, source in scripts:
        names, error = await names_of(tab, frame, label, source)
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
    frame = (await tab.cmd("Page.getFrameTree"))["frameTree"]["frame"]["id"]
    results = []

    for title, sources, expected in SAMPLES:
        twice, errors = await top_level_names(tab, frame, [(f"{title} {n}", s) for n, s in enumerate(sources, 1)])
        results.append((not errors and set(twice) == expected,
                        f"the name reader on {title}: {sorted(twice) or 'no name'} in more than one script"
                        f"{', ' + '; '.join(errors) if errors else ''}"))
    _, errors = await top_level_names(tab, frame, [("a broken script", BROKEN_SAMPLE)])
    results.append((bool(errors), f"the name reader on a script that does not compile reports it ({errors})"))

    scripts = await page_scripts(tab)
    twice, errors = await top_level_names(tab, frame, scripts)
    results.append((ready.get("mesa") and len(scripts) == ready.get("scripts") and not twice and not errors,
                    f"every top-level name of the theme page is declared by one script ({len(scripts)} scripts read, "
                    f"{ready.get('scripts')} in the page; {twice or 'no name twice'}"
                    f"{'; ' + '; '.join(errors) if errors else ''})"))

    for file, selector, kind in FEATURE_HANDLERS:
        files = await handler_files(tab, selector, kind)
        results.append((files == [file], f"the {kind} handler of {selector} is in {file} ({files})"))

    await tab.js(SEARCH_OPEN)
    opened = await until(tab, "({open: !!S.busca && !document.getElementById('vista-busca').hidden})", "s.open", 5.0)
    await tab.js(OUTSIDE_TOUCH)
    after = await tab.js("({closed: S.busca === null, touch: ultimoToque})")
    results.append((opened.get("open") and after.get("closed") and after.get("touch") == {"x": 11, "y": 13},
                    f"a touch outside the search on the mesa closes it, and queue.js still sees that touch ({after})"))
    return results


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="The theme's scripts in a headless Chrome against a --mock server of its "
                                             "own: every top-level name declared by one script only (read by V8), the "
                                             "search and effects drawer handlers in their own files, and the search's "
                                             "outside touch on the mesa. Exit 1 if a check fails.")
    ap.add_argument("--raiz", type=Path, default=RAIZ, help="the checkout whose server.py and theme are served")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="ritmelli-scripts-") as folder:
        tmp = Path(folder)
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = compara.sobe_servidor(tmp, so_mock.free_port(), log, raiz=args.raiz.resolve(),
                                        config={"boas_vindas": True})
            try:
                results = asyncio.run(missing_script.with_tab(srv, checks))
            finally:
                compara.para_servidor(srv)
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if results and all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
