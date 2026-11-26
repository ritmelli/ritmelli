import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
theme_rebuild = importlib.import_module("theme_rebuild")

TWO = "<script src='x.js'></script><script src='y.js'></script>"
CALL, DECLARATION = "globalThis.result = f();", "function f() { return 1; }"
FOUR_LINES = "function f() {\n  const x = 1;\n  return x;\n}"
NESTED = "@media (min-width: 1px) {\n  a { color: red; }\n  @container (max-width: 1rem) { .b::after { content: %s; } }\n}\n"
FONT = "@font-face { font-family: 'A'; src: url(fonts/a.woff2) format('woff2'); }\n"
PEDAL = '<script src="pedal.js" onerror="scriptFailed(this)"></script>'
LEFT, CAME ="declaration left its script", "declaration came into the script"


def inline(*scripts):
    return {"index.html": "".join(f"<script>\n{body}\n</script>\n" for body in scripts)}


def styled(css):
    return {"index.html": "<link rel='stylesheet' href='a.css'>\n", "a.css": css}


SAMPLES = (
    ("a call and the function it calls merged into one script", inline(CALL, DECLARATION),
     inline(f"{CALL}\n{DECLARATION}"), ["gone", "scripts", CAME]),
    ("a script with a call and its function split in two", inline(f"{CALL}\n{DECLARATION}"),
     inline(CALL, DECLARATION), ["new", "scripts", LEFT]),
    ("two lines with no semicolon between them split in two scripts",
     inline("window.events.push(1)\n(() => window.events.push(2))()"),
     inline("window.events.push(1)", "(() => window.events.push(2))()"), ["new", "scripts", "gone", "new", "new"]),
    ("two functions swapped", inline("'use strict';\nfunction a() {\n  return 1;\n}\nfunction b() {}\nb();"),
     inline("'use strict';\nfunction b() {}\nfunction a() {\n  return 1;\n}\nb();"), []),
    ("a four-line function moved after its call", inline(f"'use strict';\n{FOUR_LINES}\n{CALL}"),
     inline(f"'use strict';\n{CALL}\n{FOUR_LINES}"), []),
    ("a four-line function moved before its call", inline(f"'use strict';\n{CALL}\n{FOUR_LINES}"),
     inline(f"'use strict';\n{FOUR_LINES}\n{CALL}"), []),
    ("a function moved before the const it reads", inline("const K = 1;\nfunction f() { return K; }\nf();"),
     inline("function f() { return K; }\nconst K = 1;\nf();"), []),
    ("a function moved from between two lines that then join", inline(f"{CALL[:-3]}\n{DECLARATION}\n(1);"),
     inline(f"{DECLARATION}\n{CALL[:-3]}\n(1);"), ["gone", "gone", "new"]),
    ("a function moved from between an assignment and +2", inline("'use strict';\nglobalThis.result = 1\n"
                                                                  f"{DECLARATION}\n+2;\nglobalThis.other = true;"),
     inline(f"'use strict';\n{DECLARATION}\nglobalThis.result = 1\n+2;\nglobalThis.other = true;"),
     ["gone", "gone", "new"]),
    ("two consts swapped", inline("const a = 1;\nconst b = 2;\nf();"), inline("const b = 2;\nconst a = 1;\nf();"),
     ["moved out of order"]),
    ("a call moved before another", inline("function a() {}\na();\nb();"), inline("b();\nfunction a() {}\na();"),
     ["moved out of order"]),
    ("a function moved to the next script, after a call that needs it",
     {"index.html": TWO, "x.js": f"'use strict';\n{DECLARATION}\n{CALL}\n", "y.js": "'use strict';\ny();\n"},
     {"index.html": TWO, "x.js": f"'use strict';\n{CALL}\n", "y.js": f"'use strict';\ny();\n{DECLARATION}\n"},
     [LEFT, CAME]),
    ("a function moved from inside one function to inside another",
     inline("function a() {\n  function f() { return 1; }\n  return f();\n}\nfunction b() {\n  return 2;\n}"),
     inline("function a() {\n  return f();\n}\nfunction b() {\n  function f() { return 1; }\n  return 2;\n}"),
     [LEFT, CAME, LEFT, CAME]),
    ("a function moved into a block", inline("function a() {}\nx();"), inline("x();\n{\n  function a() {}\n}"),
     [LEFT, "new"]),
    ("lines reindented", inline("f();\ng();"), inline("f();\n    g();"), []),
    ("lines moved into a block", inline("f();\ng();"), inline("if (x) {\n  f();\n  g();\n}"),
     ["gone", "gone", "new"]),
    ("a template literal reindented", inline("const t = `a\nb`;\nf();"), inline("const t = `a\n  b`;\nf();"),
     ["gone", "new"]),
    ("a trailing space taken out of a template literal", inline("const t = `a\nb \n c`;\nf();"),
     inline("const t = `a\nb\n c`;\nf();"), ["gone", "new"]),
    ("a blank line taken out of a template literal", inline("const t = `a\n\nb`;\nf();"),
     inline("const t = `a\nb`;\nf();"), ["gone", "new"]),
    ("a blank line taken out between two calls", inline("f();\n\ng();"), inline("f();\ng();"), []),
    ("a block mark put inside a template literal", inline("const s = `<svg>`;\nf();"),
     inline("const s = `/* SVG-INICIO */<svg>`;\nf();"), ["gone", "new"]),
    ("a block mark taken out of the code", inline("/* X-INICIO */\nf(); /* X-FIM */"), inline("f();"), []),
    ("a block mark taken out of a call", inline("f(/* X-INICIO */1);"), inline("f(1);"), []),
    ("a comment taken out of a rule", styled("a { /* c */ color: red; }\n"), styled("a { color: red; }\n"), []),
    ("a block mark taken out from between two tokens", inline("x+/* X-INICIO */++y;"), inline("x+++y;"),
     ["gone", "new"]),
    ("a <style> line reindented inside a template literal", inline("const s = `a\n<style>\nb`;\nf();"),
     inline("const s = `a\n  <style>\nb`;\nf();"), ["gone", "new"]),
    ("a script that gains an attribute", {"index.html": "<script src='x.js'></script>", "x.js": "x();\n"},
     {"index.html": "<script src='x.js' defer></script>", "x.js": "x();\n"}, ["script tag or strict mode"]),
    ("a script with a comment before 'use strict' that loses it",
     {"index.html": "<script src='x.js'></script>", "x.js": "/* c */\n'use strict';\nx();\n"},
     {"index.html": "<script src='x.js'></script>", "x.js": "/* c */\nx();\n"}, ["script tag or strict mode", "gone"]),
    ("a script that does not parse", {"index.html": "<script src='x.js'></script>", "x.js": "x();\n"},
     {"index.html": "<script src='x.js'></script>", "x.js": "x(;\n"}, ["does not parse", "gone", "new"]),
    ("a script renamed", {"index.html": "<script src='x.js'></script>", "x.js": "'use strict';\nx();\n"},
     {"index.html": "<script src='y.js'></script>", "y.js": "'use strict';\nx();\n"}, ["script tag or strict mode"]),
    ("a script moved before a div", {"index.html": "<div id='a'></div>\n<script src='x.js'></script>", "x.js": "x();"},
     {"index.html": "<script src='x.js'></script>\n<div id='a'></div>", "x.js": "x();"}, ["moved out of order"]),
    ("a style rule moved out of order", styled("a { }\nb { }\n"), styled("b { }\na { }\n"), ["moved out of order"]),
    ("a style rule moved to the next stylesheet", {"index.html": "<link rel='stylesheet' href='a.css'>\n"
                                                                 "<link rel='stylesheet' href='b.css'>\n",
                                                   "a.css": "a { }\nb { }\n", "b.css": "c { }\n"},
     {"index.html": "<link rel='stylesheet' href='a.css'>\n<link rel='stylesheet' href='b.css'>\n",
      "a.css": "a { }\n", "b.css": "b { }\nc { }\n"}, []),
    ("a style rule moved into a stylesheet for print", {"index.html": "<link rel='stylesheet' href='a.css'>\n"
                                                                      "<link rel='stylesheet' href='b.css' media='print'>\n",
                                                        "a.css": "a { }\nb { }\n", "b.css": "c { }\n"},
     {"index.html": "<link rel='stylesheet' href='a.css'>\n<link rel='stylesheet' href='b.css' media='print'>\n",
      "a.css": "a { }\n", "b.css": "b { }\nc { }\n"}, ["gone", "new"]),
    ("a block mark put inside a CSS string", styled(".menu::before { content: \"\"; }\n"),
     styled(".menu::before { content: \"/* DIALOGS-INICIO */\"; }\n"), ["gone", "new"]),
    ("a block mark taken out of a stylesheet", styled("/* A-INICIO */\na { color: red; }\n/* A-FIM */\n"),
     styled("a { color: red; }\n"), []),
    ("a block mark put in a string of an @container inside @media", styled(NESTED % '""'),
     styled(NESTED % '"/* X-INICIO */"'), ["gone", "new"]),
    ("a space put inside a rule", styled("a { color: red; }\n"), styled("a {  color: red; }\n"), []),
    ("the space after + taken out of a calc()", styled("a { padding: calc(14px + env(safe-area-inset-bottom)); }\n"),
     styled("a { padding: calc(14px +env(safe-area-inset-bottom)); }\n"), ["gone", "new"]),
    ("a length changed", styled("a { padding: 14px; }\n"), styled("a { padding: 15px; }\n"), ["gone", "new"]),
    ("a color changed", styled("a { color: #fff; }\n"), styled("a { color: #000; }\n"), ["gone", "new"]),
    ("a comment put inside a length", styled("a { padding: calc(14px + 1px); }\n"),
     styled("a { padding: calc(14/**/px + 1px); }\n"), ["gone", "new"]),
    ("a </script> put in a comment of an inlined script",
     {"index.html": "<!-- inline-script: s.js -->\n", "s.js": "'use strict';\nf();\n"},
     {"index.html": "<!-- inline-script: s.js -->\n", "s.js": "'use strict'; // </script>\nf();\n"},
     ["new", "new", "gone"]),
    ("a vertical tab in place of the space before + in a calc()", styled("a { padding: calc(14px + 1px); }\n"),
     styled("a { padding: calc(14px\v+ 1px); }\n"), ["gone", "new"]),
    ("a vertical tab after the space before + in a calc()", styled("a { padding: calc(14px + 1px); }\n"),
     styled("a { padding: calc(14px \v+ 1px); }\n"), ["gone", "new"]),
    ("a comment in place of the space before + in a calc()", styled("a { padding: calc(14px + 1px); }\n"),
     styled("a { padding: calc(14px/* c */+ 1px); }\n"), ["gone", "new"]),
    ("a stylesheet with a font moved to another folder", {"index.html": "<link rel='stylesheet' href='base.css'>\n",
                                                          "base.css": FONT},
     {"index.html": "<link rel='stylesheet' href='gerado/base.css'>\n", "gerado/base.css": FONT}, ["gone", "new"]),
    ("a line break put after throw", inline("function g(x) {\n  throw x;\n}"),
     inline("function g(x) {\n  throw\n  x;\n}"), ["does not parse"]),
    ("two functions of one name swapped", inline("function f() { return 1; }\nfunction f() { return 2; }\nf();"),
     inline("function f() { return 2; }\nfunction f() { return 1; }\nf();"),
     ["declarations of one name in another order"]),
)


def theme_mutant(changes):
    read = theme_rebuild.reader(None, "ritmelli")
    return lambda name: changes[name](read(name) if name != "transporte-new.js" else "", read) if name in changes \
        else read(name)


def swapped(html, _):
    notice, covers = ('<script src="notice.js" onerror="scriptFailed(this)"></script>',
                      '<script src="covers.js" onerror="scriptFailed(this)"></script>')
    return html.replace(notice, "\0").replace(covers, notice).replace("\0", covers) if covers in html else ""


def early(html, _):
    inlined = "<!-- inline-script: desk-buttons.js -->\n<!-- inline-script: start.js -->\n"
    ui_events = '<script src="ui-events.js" onerror="scriptFailed(this)"></script>\n'
    return html.replace(inlined, "").replace(ui_events, inlined + ui_events) if inlined in html else ""


def binder(text):
    start = text.find("\nfunction bindShelfClick() {\n")
    end = text.find("\n}\n", start)
    return text[start + 1:end + 3] if start >= 0 and end >= 0 else ""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    samples = [(title, theme_rebuild.assemble(base.__getitem__), theme_rebuild.assemble(head.__getitem__), expected)
               for title, base, head, expected in SAMPLES]
    theme = theme_rebuild.assemble(theme_rebuild.reader(None, "ritmelli"))
    shelf_moved = {"shelf.js": lambda text, _: text.replace(binder(text), "") if binder(text) else "",
                   "start.js": lambda text, read: text + binder(read("shelf.js"))}
    mutants = [(title, theme_rebuild.assemble(theme_mutant(changes)), expected) for title, changes, expected in (
        ("notice.js and covers.js swapped", {"index.html": swapped}, "moved to another script"),
        ("desk-buttons.js and start.js before ui-events.js", {"index.html": early}, "moved to another script"),
        ("bindShelfClick moved from shelf.js to the end of start.js", shelf_moved, LEFT),
        ("a line break after the first throw of api.js",
         {"api.js": lambda text, _: text.replace("throw x;", "throw\nx;", 1) if "throw x;" in text else ""},
         "does not parse"),
        *((f"a {end} in a comment on the first line of start.js",
           {"start.js": lambda text, _, end=end: text.replace("'use strict';", f"'use strict'; // {end}", 1)
            if "'use strict';" in text else ""}, "gone") for end in ("</script>", "</script/>", "</script x>")),
        ("start.js loaded from its file instead of inline",
         {"index.html": lambda html, _: html.replace("<!-- inline-script: start.js -->", '<script src="start.js"></script>')
          if "<!-- inline-script: start.js -->" in html else ""}, "script tag or strict mode"),
        ("the </script> of pedal.js taken out",
         {"index.html": lambda html, _: html.replace(PEDAL, PEDAL.removesuffix("</script>")) if PEDAL in html else ""},
         "script tag or strict mode"),
        ("transporte.js renamed",
         {"index.html": lambda html, _: html.replace('src="transporte.js"', 'src="transporte-new.js"')
          if 'src="transporte.js"' in html else "",
          "transporte-new.js": lambda _, read: read("transporte.js")}, "script tag or strict mode"))]
    compiles = theme_rebuild.syntax([theme, *(page for _, a, b, _ in samples for page in (a, b)),
                                     *(page for _, page, _ in mutants)])
    results = []
    for title, base, head, expected in samples:
        found = [kind for kind, _, _ in theme_rebuild.compare(base, head, compiles).changes]
        results.append((found == expected, f"{title}: {found or 'only moves code'}"))
    for title, head, expected in mutants:
        found = sorted({kind for kind, _, _ in theme_rebuild.compare(theme, head, compiles).changes})
        results.append((len(head.blocks) == len(theme.blocks) and expected in found,
                        f"the theme with {title} does more than move code ({found})"))
    report = theme_rebuild.compare(theme, theme, compiles)
    results.append((not report.changes and report.declarations > 100,
                    f"the theme against itself only moves code ({report.declarations} declarations compared)"))
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
