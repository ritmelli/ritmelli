import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
theme_rebuild = importlib.import_module("theme_rebuild")

TWO = "<script src=\"x.js\"></script><script src=\"y.js\"></script>"
CALL, DECLARATION = "globalThis.result = f();", "function f() { return 1; }"
FOUR_LINES = "function f() {\n  const x = 1;\n  return x;\n}"
NESTED = "@media (min-width: 1px) {\n  a { color: red; }\n  @container (max-width: 1rem) { .b::after { content: %s; } }\n}\n"
FONT = "@font-face { font-family: 'A'; src: url(fonts/a.woff2) format('woff2'); }\n"
PEDAL = '<script src="pedal.js" onerror="scriptFailed(this)"></script>'
HIDDEN = "html:not(.i18n-ok) body { visibility: hidden; }"
TWO_INLINED = "<!-- inline-script: s.js -->\n<!-- inline-script: t.js -->\n"
TRANSLATED = {"index.html": "<!-- i18n -->\n", "i18n/i18n_en.properties": "", "i18n/i18n_pt_BR.properties": ""}
NOTICE = '<script src="notice.js" onerror="scriptFailed(this)"></script>'
CANNOT = "cannot judge"
LEFT, CAME = "declaration left its script", "declaration came into the script"


def inline(*scripts):
    return {"index.html": "".join(f"<script>\n{body}\n</script>\n" for body in scripts)}


def styled(css):
    return {"index.html": "<link rel=\"stylesheet\" href=\"a.css\">\n", "a.css": css}


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
    ("a script that gains an attribute", {"index.html": "<script src=\"x.js\"></script>", "x.js": "x();\n"},
     {"index.html": "<script src=\"x.js\" defer></script>", "x.js": "x();\n"}, ["script tag or strict mode"]),
    ("a script with a comment before 'use strict' that loses it",
     {"index.html": "<script src=\"x.js\"></script>", "x.js": "/* c */\n'use strict';\nx();\n"},
     {"index.html": "<script src=\"x.js\"></script>", "x.js": "/* c */\nx();\n"}, ["script tag or strict mode", "gone"]),
    ("a script that does not parse", {"index.html": "<script src=\"x.js\"></script>", "x.js": "x();\n"},
     {"index.html": "<script src=\"x.js\"></script>", "x.js": "x(;\n"}, ["does not parse", "gone", "new"]),
    ("a script renamed", {"index.html": "<script src=\"x.js\"></script>", "x.js": "'use strict';\nx();\n"},
     {"index.html": "<script src=\"y.js\"></script>", "y.js": "'use strict';\nx();\n"}, ["script tag or strict mode"]),
    ("a script moved before a div", {"index.html": "<div id=\"a\"></div>\n<script src=\"x.js\"></script>", "x.js": "x();"},
     {"index.html": "<script src=\"x.js\"></script>\n<div id=\"a\"></div>", "x.js": "x();"}, ["moved out of order"]),
    ("a style rule moved out of order", styled("a { }\nb { }\n"), styled("b { }\na { }\n"), ["moved out of order"]),
    ("a style rule moved to the next stylesheet", {"index.html": "<link rel=\"stylesheet\" href=\"a.css\">\n"
                                                                 "<link rel=\"stylesheet\" href=\"b.css\">\n",
                                                   "a.css": "a { }\nb { }\n", "b.css": "c { }\n"},
     {"index.html": "<link rel=\"stylesheet\" href=\"a.css\">\n<link rel=\"stylesheet\" href=\"b.css\">\n",
      "a.css": "a { }\n", "b.css": "b { }\nc { }\n"}, []),
    ("a style rule moved into a stylesheet for print", {"index.html": "<link rel=\"stylesheet\" href=\"a.css\">\n"
                                                                      "<link rel=\"stylesheet\" href=\"b.css\" media=\"print\">\n",
                                                        "a.css": "a { }\nb { }\n", "b.css": "c { }\n"},
     {"index.html": "<link rel=\"stylesheet\" href=\"a.css\">\n<link rel=\"stylesheet\" href=\"b.css\" media=\"print\">\n",
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
     CANNOT),
    ("a // <!-- in an inlined script turned into // <!-- <script>",
     {"index.html": TWO_INLINED, "s.js": "f();\n// <!--\n", "t.js": "g();\n"},
     {"index.html": TWO_INLINED, "s.js": "f();\n// <!-- <script>\n", "t.js": "g();\n"},
     CANNOT),
    ("a // <!-- --> in an inlined script turned into // <!-- <script></script> -->",
     {"index.html": TWO_INLINED, "s.js": "f();\n// <!-- -->\n", "t.js": "g();\n"},
     {"index.html": TWO_INLINED, "s.js": "f();\n// <!-- <script></script> -->\n", "t.js": "g();\n"}, CANNOT),
    ("a <script> put after the --> of a // <!-- --> in an inlined script",
     {"index.html": TWO_INLINED, "s.js": "f();\n// <!-- -->\n", "t.js": "g();\n"},
     {"index.html": TWO_INLINED, "s.js": "f();\n// <!-- --> <script>\n", "t.js": "g();\n"}, CANNOT),
    ("the </script> of the last script of the page taken out",
     {"index.html": "<p>x</p>\n<script src=\"x.js\"></script>\n", "x.js": "f();\n"},
     {"index.html": "<p>x</p>\n<script src=\"x.js\">\n", "x.js": "f();\n"}, CANNOT),
    ("the markup a <script src> with no </script> swallows changed",
     {"index.html": "<script src=\"x.js\">\n<p>1</p>\n</script>\n", "x.js": "f();\n"},
     {"index.html": "<script src=\"x.js\">\n<p>2</p>\n</script>\n", "x.js": "f();\n"}, CANNOT),
    ("a stylesheet renamed with a # in its name", styled(HIDDEN),
     {"index.html": "<link rel=\"stylesheet\" href=\"a#copy.css\">\n", "a#copy.css": HIDDEN}, CANNOT),
    ("an empty script file taken out", {"index.html": "<script src=\"x.js\"></script>\n", "x.js": ""},
     {"index.html": "<script src=\"x.js\"></script>\n"}, CANNOT),
    ("the indentation inside a template changed in a script of type Text/JavaScript",
     {"index.html": "<script type=\"Text/JavaScript\">\nconst t = `\n  a\n`;\n</script>\n"},
     {"index.html": "<script type=\"Text/JavaScript\">\nconst t = `\n    a\n`;\n</script>\n"}, ["gone", "new"]),
    ("two spaces put around the = of a quoted value with a > in the end tag of a script",
     {"index.html": "<script src=\"x.js\"></script>\n", "x.js": "f();\n"},
     {"index.html": "<script src=\"x.js\"></script x  =  \"a>b\">\n", "x.js": "f();\n"}, CANNOT),
    ("a title with a character reference put on a script", {"index.html": "<script src=\"x.js\"></script>\n", "x.js": ""},
     {"index.html": "<script src=\"x.js\" title=\"a&amp;b\"></script>\n", "x.js": ""}, ["script tag or strict mode"]),
    ("a stylesheet linked with a query", styled(HIDDEN),
     {"index.html": "<link rel=\"stylesheet\" href=\"a.css?v=2\">\n", "a.css": HIDDEN}, CANNOT),
    ("a </script y> in a quoted value of the start tag of a script turned into </script z>",
     {"index.html": '<script x="a></script y>">\nf();\n</script>\n'},
     {"index.html": '<script x="a></script z>">\nf();\n</script>\n'}, ["script tag or strict mode"]),
    ("a space put after the \\ that ends a translation",
     {**TRANSLATED, "i18n/i18n_en.properties": "a=b\\\n"}, {**TRANSLATED, "i18n/i18n_en.properties": "a=b\\ \n"},
     ["translation gone", "translation new"]),
    ("a space put after a translation", {**TRANSLATED, "i18n/i18n_en.properties": "a=b\n"},
     {**TRANSLATED, "i18n/i18n_en.properties": "a=b \n"}, []),
    ("a vertical tab in place of the space before + in a calc()", styled("a { padding: calc(14px + 1px); }\n"),
     styled("a { padding: calc(14px\v+ 1px); }\n"), ["gone", "new"]),
    ("a vertical tab after the space before + in a calc()", styled("a { padding: calc(14px + 1px); }\n"),
     styled("a { padding: calc(14px \v+ 1px); }\n"), ["gone", "new"]),
    ("a lone carriage return put after return", inline("function d() { return !!x; }"),
     {"index.html": theme_rebuild.text_of(b"<script>\nfunction d() { return\r!!x; }\n</script>\n")}, [LEFT, CAME]),
    ("a no-break space put before a button", {"index.html": "<div>\n  <button></button>\n</div>\n"},
     {"index.html": "<div>\n \u00a0<button></button>\n</div>\n"}, ["gone", "new"]),
    ("a rule moved from an inline style to a linked stylesheet",
     {"index.html": f"<style>\n{HIDDEN}\n</style>\n<link rel=\"stylesheet\" href=\"base.css\">\n", "base.css": "a { }\n"},
     {"index.html": "<style>\n</style>\n<link rel=\"stylesheet\" href=\"base.css\">\n", "base.css": HIDDEN + "\na { }\n"},
     ["gone", "new"]),
    ("a comment in place of the space before + in a calc()", styled("a { padding: calc(14px + 1px); }\n"),
     styled("a { padding: calc(14px/* c */+ 1px); }\n"), ["gone", "new"]),
    ("a stylesheet with a font moved to another folder", {"index.html": "<link rel=\"stylesheet\" href=\"base.css\">\n",
                                                          "base.css": FONT},
     {"index.html": "<link rel=\"stylesheet\" href=\"gerado/base.css\">\n", "gerado/base.css": FONT}, ["gone", "new"]),
    ("a line break put after throw", inline("function g(x) {\n  throw x;\n}"),
     inline("function g(x) {\n  throw\n  x;\n}"), ["does not parse", LEFT, CAME]),
    ("a line break put after the comment between return and its template",
     inline("function g() { return /* a */ `1`; }"), inline("function g() { return /* a */\n`1`; }"), [LEFT, CAME]),
    ("two functions of one name swapped, one written with an escape",
     inline("function f() { return 1; }\nfunction \\u0066() { return 2; }\nf();"),
     inline("function \\u0066() { return 2; }\nfunction f() { return 1; }\nf();"),
     ["declarations of one name in another order"]),
    ("a rule moved to a style after a script that reads it",
     {"index.html": "<style>\nbody { color: red; }\n</style>\n<script>\nf();\n</script>\n<style>\n</style>\n"},
     {"index.html": "<style>\n</style>\n<script>\nf();\n</script>\n<style>\nbody { color: red; }\n</style>\n"},
     ["gone", "new"]),
    ("a rule moved between two styles with no script between them",
     {"index.html": "<style>\nbody { color: red; }\n</style>\n<style>\n</style>\n"},
     {"index.html": "<style>\n</style>\n<style>\nbody { color: red; }\n</style>\n"}, []),
    ("two functions of one name swapped", inline("function f() { return 1; }\nfunction f() { return 2; }\nf();"),
     inline("function f() { return 2; }\nfunction f() { return 1; }\nf();"),
     ["declarations of one name in another order"]),
)


DOUBTFUL = (
    ("an href in capitals", {"index.html": "<link rel=\"stylesheet\" HREF=\"ba%73e.css\">\n"}),
    ("an href written twice", {"index.html": "<link rel=\"stylesheet\" href=\"ba%73e.css\" href=\"base.css\">\n"}),
    ("a stylesheet from the root of the site", {"index.html": "<link rel=\"stylesheet\" href=\"/t/ritmelli/a.css\">\n"}),
    ("an alternate stylesheet", {"index.html": "<link rel=\"alternate stylesheet\" href=\"a.css\">\n"}),
    ("a script from a folder above", {"index.html": "<script src=\"../x.js\"></script>\n"}),
    ("an element the theme does not use", {"index.html": "<marquee>a</marquee>\n<script src=\"x.js\"></script>\n"}),
    ("a math element", {"index.html": "<math></math>\n<script src=\"x.js\"></script>\n"}),
    ("a <p> inside an svg", {"index.html": "<svg><p></p><textarea>a</textarea></svg>\n<script src=\"x.js\"></script>\n"}),
    ("a </p> inside an svg", {"index.html": "<svg></p><noscript>a</noscript></svg>\n<script src=\"x.js\"></script>\n"}),
    ("a <g> after an svg closed in itself", {"index.html": "<svg/><g></g>\n"}),
    ("a </p> and a <g> inside an svg", {"index.html": "<svg><path d=\"\"></path></p><g></g></svg>\n"}),
    ("a tag inside the title", {"index.html": "<title>a <b>c</b></title>\n"}),
    ("a -- inside a comment", {"index.html": "<!-- a -- > <div title=\" --> \"></div>\n"}),
    ("a srcdoc", {"index.html": "<iframe srcdoc=\"&lt;script src=x.js&gt;&lt;/script&gt;\"></iframe>\n"}),
    ("a tag inside a select", {"index.html": "<select><style>a { }</style></select>\n"}),
    ("a prefetch", {"index.html": "<link rel=\"prefetch\" href=\"x.js\">\n"}),
    ("a script module", {"index.html": "<script type=\" Module \">f();</script>\n"}),
    ("a & in a rel", {"index.html": "<link rel=\"style&#115;heet\" href=\"a.css\">\n"}),
    ("a NUL in a value", {"index.html": "<link rel=\"icon\" href=\"a\0b.png\">\n"}),
    ("an @import in a style", {"index.html": "<style>@im\\70 ort \"a.css\";</style>\n"}),
    ("an @namespace in a style", {"index.html": "<style>@namespace svg url(http://www.w3.org/2000/svg);</style>\n"}),
    ("an @namespace in a linked stylesheet", {"index.html": "<link rel=\"stylesheet\" href=\"a.css\">\n",
                                              "a.css": "@namespace svg url(http://www.w3.org/2000/svg);\n"}),
    ("a linked stylesheet that is not in the theme", {"index.html": "<link rel=\"stylesheet\" href=\"gone.css\">\n"}),
    ("an inline-script that is not in the theme", {"index.html": "<!-- inline-script: gone.js -->\n"}),
    ("an @scope in a style", {"index.html": "<style>@scope { p { color: red; } }</style>\n"}),
    ("an @scope in a linked stylesheet", {"index.html": "<link rel=\"stylesheet\" href=\"a.css\">\n",
                                          "a.css": "@sco\\70 e { p { color: red; } }\n"}),
    ("an @import in a linked stylesheet", {"index.html": "<link rel=\"stylesheet\" href=\"a.css\">\n",
                                           "a.css": "/* @import \"b.css\"; */\n"}),
    ("a value in single quotes", {"index.html": "<script src='x.js'></script>\n"}),
    ("a value with no quotes", {"index.html": "<div id=a></div>\n<script src=\"x.js\"></script>\n"}),
    ("a tag name in capitals", {"index.html": "<SCRIPT src=\"x.js\"></SCRIPT>\n"}),
    ("a < in the text", {"index.html": "<p>a < b</p>\n<script src=\"x.js\"></script>\n"}),
    ("a <script/>", {"index.html": "<script src=\"x.js\"/></script>\n"}),
    ("a <style/>", {"index.html": "<style/>a { }</style>\n"}),
    ("a style with a </style x> before its </style>", {"index.html": "<style>a { }</style x>b { }</style>\n"}),
    ("text inside a <script src>", {"index.html": "<script src=\"x.js\">f();</script>\n"}),
    ("a script inside an svg", {"index.html": "<svg><script src=\"x.js\"></script></svg>\n"}),
    ("a preload of a script", {"index.html": "<link rel=\"preload\" as=\"script\" href=\"x.js\">\n"}),
    ("a & that is not a whole reference in a value", {"index.html": "<div title=\"a&b\"></div>\n"}),
    ("a </script in an inlined script", {"index.html": "<!-- inline-script: s.js -->\n", "s.js": "// </script>\n"}),
    ("an escaped separator in an href", {"index.html": "<link rel=\"stylesheet\" href=\"x%5C..%2F..%2Fa.css\">\n"}),
    ("a backslash in a src", {"index.html": "<script src=\"x\\..\\x.js\"></script>\n"}),
    ("a / and a quote in an unquoted value of an end tag",
     {"index.html": "<script src=\"x.js\"></script x=a/b=\"><p>Visible text</p>\">\n"}),
    ("an end tag with a value whose quote is not at its start",
     {"index.html": "<script src=\"x.js\"></script x=x=\"><p>Visible text</p>\">\n"}),
    ("a quote in an unquoted value of an end tag",{"index.html": "<script src=\"x.js\"></script x=a\"b>\n"}),
    ("a quote in an attribute name of an end tag", {"index.html": "<script src=\"x.js\"></script a\"b>\n"}),
    ("a = opening an unquoted value of a start tag", {"index.html": "<script src=\"x.js\" x==a></script>\n"}),
    ("a script inside a textarea", {"index.html": "<textarea><script src=\"x.js\"></script></textarea>\n"}),
    ("a tag inside a closed textarea", {"index.html": "<textarea><b>a</b></textarea>\n<script src=\"x.js\"></script>\n"}),
    ("a title that never closes", {"index.html": "<title>Ritmelli\n<script src=\"x.js\"></script>\n"}),
    ("a base URL", {"index.html": "<base href=\"other/\">\n<script src=\"x.js\"></script>\n"}),
    ("a comment closed by its own <!-->", {"index.html": "<!--> <script src=\"x.js\"></script> -->\n"}),
    ("a comment closed by --!>", {"index.html": "<!-- a --!> <script src=\"x.js\"></script> -->\n"}),
    ("a comment that never closes", {"index.html": "<script src=\"x.js\"></script>\n<!-- a\n"}),
    ("a CDATA section", {"index.html": "<![CDATA[ a ]]>\n<script src=\"x.js\"></script>\n"}),
    ("a character reference in a src", {"index.html": "<script src=\"x&#46;js\"></script>\n"}),
    ("a character reference in a src after one in another value",
     {"index.html": "<script title=\"src=a\" src=x&#46;js></script>\n"}),
    ("a character reference in an href", {"index.html": "<link rel=\"stylesheet\" href=\"a&#46;css\">\n"}),
    ("a script start tag that never ends", {"index.html": "<script src=\"x.js\"\n"}),
)


def built(read, files=None):
    try:
        return theme_rebuild.assemble(read, files)
    except theme_rebuild.Doubt as unsure:
        return unsure


def theme_mutant(changes):
    read = theme_rebuild.reader(None, "ritmelli")
    return lambda name: changes[name](read(name), read) if name in changes \
        else read(name)


def swapped(html, _):
    notice, covers = NOTICE, '<script src="covers.js" onerror="scriptFailed(this)"></script>'
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
    samples = [(title, built(base.get), built(head.get), expected) for title, base, head, expected in SAMPLES]
    files = theme_rebuild.listing(None, "ritmelli")
    theme = theme_rebuild.assemble(theme_rebuild.reader(None, "ritmelli"), files)
    other_grain = {**files, "texturas/veio.webp": files["texturas/veio-v.webp"]}
    shelf_moved = {"shelf.js": lambda text, _: text.replace(binder(text), "") if binder(text) else "",
                   "start.js": lambda text, read: text + binder(read("shelf.js"))}
    mutants = [(title, built(theme_mutant(changes), files), expected) for title, changes, expected in (
        ("notice.js and covers.js swapped", {"index.html": swapped}, "moved to another script"),
        ("desk-buttons.js and start.js before ui-events.js", {"index.html": early}, "moved to another script"),
        ("bindShelfClick moved from shelf.js to the end of start.js", shelf_moved, LEFT),
        ("a line break after the first throw of api.js",
         {"api.js": lambda text, _: text.replace("throw x;", "throw\nx;", 1) if "throw x;" in text else ""},
         "does not parse"),
        *((f"a {end} in a comment on the first line of start.js",
           {"start.js": lambda text, _, end=end: text.replace("'use strict';", f"'use strict'; // {end}", 1)
            if "'use strict';" in text else ""}, CANNOT) for end in ("</script>", "</script/>", "</script x>")),
        ("start.js loaded from its file instead of inline",
         {"index.html": lambda html, _: html.replace("<!-- inline-script: start.js -->", '<script src="start.js"></script>')
          if "<!-- inline-script: start.js -->" in html else ""}, "script tag or strict mode"),
        ("the </script> of pedal.js taken out",
         {"index.html": lambda html, _: html.replace(PEDAL, PEDAL.removesuffix("</script>")) if PEDAL in html else ""},
         CANNOT),
        ("the </script> of pedal.js with an open quote in it",
         {"index.html": lambda html, _: html.replace(PEDAL, PEDAL.replace("</script>", '</script x=">'))
          if PEDAL in html else ""}, CANNOT),
        ("a translation changed", {"i18n/i18n_en.properties": lambda text, _: text.replace(
            "nav.backToShelf=Back to the shelf", "nav.backToShelf=Close the app") if "nav.backToShelf=" in text else ""},
         "translation new"),
        ("a translation line repeated", {"i18n/i18n_en.properties": lambda text, _: text.replace(
            "nav.backToShelf=Back to the shelf", "nav.backToShelf=Back to the shelf\nnav.backToShelf=Back to the shelf")
            if "nav.backToShelf=" in text else ""}, "translation new"),
        ("a translation line moved to the end", {"i18n/i18n_en.properties": lambda text, _: text.replace(
            "nav.backToShelf=Back to the shelf\n", "") + "nav.backToShelf=Back to the shelf\n"
            if "nav.backToShelf=" in text else ""}, "translations in another order"),
        ("base.css renamed to base.txt",
         {"index.html": lambda html, _: html.replace('href="base.css"', 'href="base.txt"')
          if 'href="base.css"' in html else "",
          "base.txt": lambda _, read: read("base.css")}, "gone"),
        ("a translation put after a vertical tab in a comment", {"i18n/i18n_en.properties": lambda text, _: text.replace(
            "# Geral:", "#\vnav.backToShelf=Close the app\v# Geral:") if "# Geral:" in text else ""},
         "translation new"),
        ("a line break put between return and the template of desenharQR",
         {"phone.js": lambda text, _: text.replace("  return `<svg", "  return\n`<svg")}, LEFT),
        ("a vertical tab put before the first .btn rule of buttons.css",
         {"buttons.css": lambda text, _: text.replace("\n.btn", "\n\v.btn", 1)}, "does not parse"),
        ("pedal.css linked from the root of the site",
         {"index.html": lambda html, _: html.replace('href="pedal.css"', 'href="/t/ritmelli/pedal.css"')}, CANNOT),
        ("the rules of pedal.css moved to the end of mix.css and pedal.css deleted",
         {"mix.css": lambda text, read: text + read("pedal.css"), "pedal.css": lambda *_: None}, CANNOT),
        ("transporte.js renamed",
         {"index.html": lambda html, _: html.replace('src="transporte.js"', 'src="transporte-new.js"')
          if 'src="transporte.js"' in html else "",
          "transporte-new.js": lambda _, read: read("transporte.js")}, "script tag or strict mode"))]
    mutants.append(("texturas/veio.webp holding the image of veio-v.webp",
                    built(theme_rebuild.reader(None, "ritmelli"), other_grain), "file changed"))
    pages = [theme, *(page for _, a, b, _ in samples for page in (a, b)), *(page for _, page, _ in mutants)]
    compiles = theme_rebuild.syntax([page for page in pages if isinstance(page, theme_rebuild.Page)])
    results = []
    for title, base, head, expected in samples:
        refused = [str(x) for x in (base, head) if isinstance(x, theme_rebuild.Doubt)]
        found = refused and CANNOT or [kind for kind, _, _ in theme_rebuild.compare(base, head, compiles).changes]
        results.append((found == expected, f"{title}: {refused or found or 'only moves code'}"))
    for title, head, expected in mutants:
        if isinstance(head, theme_rebuild.Doubt):
            results.append((expected == CANNOT, f"the theme with {title}: cannot judge ({head})"))
            continue
        found = sorted({kind for kind, _, _ in theme_rebuild.compare(theme, head, compiles).changes})
        results.append((len(head.blocks) == len(theme.blocks) and expected in found,
                        f"the theme with {title} does more than move code ({found})"))
    quiet = {"say": lambda *_: None}
    for title, head, _ in [*mutants[:2], *(x for x in mutants if "desenharQR" in x[0])]:
        code = theme_rebuild.judge(theme, head, compiles, **quiet)
        results.append((code == 1, f"the verdict on the theme with {title} is {code}"))
    allowed = next((a, b) for title, a, b, _ in samples if title == "two functions swapped")
    code = theme_rebuild.judge(*allowed, compiles, **quiet)
    results.append((code == 0, f"the verdict on two functions swapped is {code}"))
    for title, page in DOUBTFUL:
        unsure = built({**page, "x.js": "f();\n"}.get)
        results.append((isinstance(unsure, theme_rebuild.Doubt), f"{title}: cannot judge ({unsure})"))
    for page in ("themes/ritmelli/index.html", "gallery/index.html"):
        try:
            theme_rebuild.strict(theme_rebuild.text_of((theme_rebuild.RAIZ / page).read_bytes()), page)
            results.append((True, f"{page} is in the strict form"))
        except theme_rebuild.Doubt as unsure:
            results.append((False, f"{page} is not in the strict form: {unsure}"))
    refused = [x for x in DOUBTFUL if x[0] in (DOUBTFUL[0][0], "an inline-script that is not in the theme")]
    kept = theme_rebuild.reader, theme_rebuild.listing
    for title, page in refused:
        pages = {"base": inline("f();"), "head": dict(page)}
        theme_rebuild.reader, theme_rebuild.listing = (lambda rev, _: pages[rev].get), (lambda rev, _: {})
        try:
            code = theme_rebuild.main(["base", "head"])
        finally:
            theme_rebuild.reader, theme_rebuild.listing = kept
        results.append((code == theme_rebuild.CANNOT_JUDGE, f"the verdict on {title} is {code}"))
    report = theme_rebuild.compare(theme, theme, compiles)
    results.append((not report.changes and report.declarations > 100,
                    f"the theme against itself only moves code ({report.declarations} declarations compared)"))
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
