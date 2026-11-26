"""dev/theme_rebuild.py with V8, in a headless Chrome: what only moves code passes and what does more fails, on small
pages and on the theme of the working tree with its scripts out of order. Exit 1 if a check fails."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
theme_rebuild = importlib.import_module("theme_rebuild")

TWO = "<script src='x.js'></script><script src='y.js'></script>"
SAMPLES = (
    ("two scripts merged into one", {"index.html": "<script>\nwindow.events.push(1)\n</script>\n<script>\n"
                                                   "(() => window.events.push(2))()\n</script>\n"},
     {"index.html": "<script>\nwindow.events.push(1)\n(() => window.events.push(2))()\n</script>\n"},
     ["moved to another script"]),
    ("one script split in two", {"index.html": "<script>\nwindow.events.push(1)\n(() => window.events.push(2))()\n"
                                               "</script>\n"},
     {"index.html": "<script>\nwindow.events.push(1)\n</script>\n<script>\n(() => window.events.push(2))()\n"
                    "</script>\n"},
     ["moved to another script"]),
    ("two functions swapped", {"index.html": "<script>\n'use strict';\nfunction a() {\n  return 1;\n}\nfunction b() {}"
                                             "\nb();\n</script>\n"},
     {"index.html": "<script>\n'use strict';\nfunction b() {}\nfunction a() {\n  return 1;\n}\nb();\n</script>\n"}, []),
    ("two consts swapped", {"index.html": "<script>\nconst a = 1;\nconst b = 2;\nf();\n</script>\n"},
     {"index.html": "<script>\nconst b = 2;\nconst a = 1;\nf();\n</script>\n"}, ["moved out of order"]),
    ("a call moved before a function", {"index.html": "<script>\nfunction a() {}\na();\nb();\n</script>\n"},
     {"index.html": "<script>\nb();\nfunction a() {}\na();\n</script>\n"}, ["moved out of order"]),
    ("a function with a comment moved to a script of the same [strict]",
     {"index.html": TWO, "x.js": "'use strict';\n// the first\nfunction a() {}\nx();\n", "y.js": "'use strict';\ny();\n"},
     {"index.html": TWO, "x.js": "'use strict';\nx();\n", "y.js": "'use strict';\ny();\n// the first\nfunction a() {}\n"},
     []),
    ("a function moved to a sloppy script", {"index.html": TWO, "x.js": "'use strict';\nfunction a() {}\nx();\n",
                                             "y.js": "y();\n"},
     {"index.html": TWO, "x.js": "'use strict';\nx();\n", "y.js": "y();\nfunction a() {}\n"}, ["moved out of order"]),
    ("a class moved to another script", {"index.html": TWO, "x.js": "class A {}\nx();\n", "y.js": "y();\n"},
     {"index.html": TWO, "x.js": "x();\n", "y.js": "y();\nclass A {}\n"}, ["moved out of order"]),
    ("a function moved into a block", {"index.html": "<script>\nfunction a() {}\nx();\n</script>\n"},
     {"index.html": "<script>\nx();\n{\n  function a() {}\n}\n</script>\n"},
     ["moved with a new indentation", "new", "new"]),
    ("lines moved into a function", {"index.html": "<script>\nf();\ng();\n</script>\n"},
     {"index.html": "<script>\nfunction bind() {\n  f();\n  g();\n}\n</script>\n"},
     ["moved with a new indentation", "new", "new"]),
    ("a template literal moved into a function", {"index.html": "<script>\nconst t = `a\nb`;\n</script>\n"},
     {"index.html": "<script>\nfunction bind() {\n  const t = `a\n  b`;\n}\n</script>\n"},
     ["moved with a new indentation", "gone", "new", "new", "new"]),
    ("a comment reindented", {"index.html": "<script>\n/* a\n   b */\nf();\n</script>\n"},
     {"index.html": "<script>\nf();\n/* a\n b */\n</script>\n"}, ["moved out of order", "moved with a new indentation"]),
    ("a script that gains an attribute", {"index.html": "<script src='x.js'></script>", "x.js": "x();\n"},
     {"index.html": "<script src='x.js' defer></script>", "x.js": "x();\n"},
     ["a script changed its attributes or [strict]"]),
    ("a script that loses its 'use strict'", {"index.html": "<script src='x.js'></script>",
                                              "x.js": "'use strict';\nx();\n"},
     {"index.html": "<script src='x.js'></script>", "x.js": "x();\n"},
     ["a script changed its attributes or [strict]", "gone"]),
    ("a stylesheet rule moved out of order", {"index.html": "<style>\na { }\nb { }\n</style>\n"},
     {"index.html": "<style>\nb { }\na { }\n</style>\n"}, ["moved out of order"]),
    ("a script moved to another file in place", {"index.html": "<script src='x.js'></script>",
                                                 "x.js": "'use strict';\nx();\n"},
     {"index.html": "<script src='y.js'></script>", "y.js": "'use strict';\nx();\n"}, []),
)


def theme_mutant(change):
    read = theme_rebuild.reader(None, "ritmelli")
    return lambda name: change(read(name)) if name == "index.html" else read(name)


def swapped(html):
    notice, covers = ('<script src="notice.js" onerror="scriptFailed(this)"></script>',
                      '<script src="covers.js" onerror="scriptFailed(this)"></script>')
    return html.replace(notice, "\0").replace(covers, notice).replace("\0", covers) if covers in html else ""


def early(html):
    inlined = "<!-- inline-script: desk-buttons.js -->\n<!-- inline-script: start.js -->\n"
    ui_events = '<script src="ui-events.js" onerror="scriptFailed(this)"></script>\n'
    return html.replace(inlined, "").replace(ui_events, inlined + ui_events) if inlined in html else ""


async def run(v8):
    results = []
    for title, base, head, expected in SAMPLES:
        report = await theme_rebuild.compare(theme_rebuild.assemble(base.__getitem__),
                                             theme_rebuild.assemble(head.__getitem__), v8)
        found = [change.split(",")[0].split(":")[0] for change, _ in report.changes]
        results.append((found == expected, f"{title}: {found or 'only moves code'}"))
    theme = theme_rebuild.assemble(theme_rebuild.reader(None, "ritmelli"))
    for title, change in (("notice.js and covers.js swapped", swapped),
                          ("desk-buttons.js and start.js before ui-events.js", early)):
        head = theme_rebuild.assemble(theme_mutant(change))
        report = await theme_rebuild.compare(theme, head, v8)
        found = sorted({change.split(",")[0] for change, _ in report.changes})
        results.append((len(head.lines) == len(theme.lines) and "moved out of order" in found,
                        f"the theme with {title} does more than move code ({found})"))
    report = await theme_rebuild.compare(theme, theme, v8)
    results.append((not report.changes and not report.moved, "the theme against itself only moves code"))
    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    results = theme_rebuild.with_v8(run)
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
