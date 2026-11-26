import argparse
import asyncio
import http.server
import importlib
import sys
import tempfile
import threading
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
theme_page = importlib.import_module("theme_page")
missing_script = importlib.import_module("missing_script")
so_mock = importlib.import_module("so_mock")
theme_page_cases = importlib.import_module("theme_page_cases")
LOADED_S = 10.0
HTML = "http://www.w3.org/1999/xhtml"
READ = ("[...document.querySelectorAll('script, style, link')].map(e => [e.localName, e.namespaceURI, "
        "Object.fromEntries(['src', 'href', 'rel', 'type'].filter(a => e.hasAttribute(a))"
        ".map(a => [a, e.getAttribute(a)]))])")
RAN = "document.documentElement.dataset.ran || ''"
NO_SCRIPTS = "script-src 'none'"
BUILT_SCRIPTS = "script-src 'unsafe-inline' data:"
MODULES = {"a.js": "import { b } from \"b.js\";\ndocument.documentElement.dataset.ran = `a after ${b}`;\n",
           "b.js": "export const b = 'b á ç ⋯ ? > # % </script> <!--';\n"}
MODULE_TEMPLATE = '<head>\n<script type="module" src="a.js"></script>\n<script type="module" src="b.js"></script>\n'


def pages(raiz):
    found = [(f"the {name} template", (raiz / folder / "index.html").read_text(encoding="utf-8"))
             for name, folder in (("theme", "themes/ritmelli"), ("gallery", "gallery"))]
    found += [(what, f"<head>\n{tag}\n") for what, (tag, _, _) in theme_page_cases.REFUSED.items()]
    return found + [(what, tag) for what, (tag, _) in theme_page_cases.KEPT.items()]


def built_view(html, built=False):
    read, _ = theme_page.strict(html, built)
    return read and [[tag, HTML, attrs] for tag, attrs in read.elements]


def module_page():
    with tempfile.TemporaryDirectory(prefix="ritmelli-oracle-") as folder:
        for name, text in MODULES.items():
            (Path(folder) / name).write_text(text, encoding="utf-8")
        return theme_page.inline_files(MODULE_TEMPLATE, Path(folder))


class Pages(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.asked.append(self.path)
        number = self.path.removeprefix("/")
        if not number.isdigit() or int(number) >= len(self.server.pages):
            self.send_error(404)
            return
        policy, html = self.server.pages[int(number)]
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", policy)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


async def chrome_views(base, count, asked):
    async def run(tab):
        views = []
        for n in range(count):
            loads, before = tab.loads, len(asked)
            await tab.cmd("Page.navigate", url=f"{base}/{n}")
            loaded = await tab.tab_reaches(lambda: tab.loads > loads, LOADED_S)
            views.append((await tab.js(READ), await tab.js(RAN), asked[before:]) if loaded
                         else (f"page {n} did not load in {LOADED_S:.0f} s", "", asked[before:]))
        return views
    return await missing_script.with_tab(types.SimpleNamespace(base=base), run)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="The theme page's grammar against Chrome: for the theme, the gallery and "
                                             "every case of dev/theme_page_cases.py the build accepts, the scripts, "
                                             "styles and links the build reads (src, href, rel and type) are the ones "
                                             "Chrome's DOM has, in order; and a built page with modules runs them all "
                                             "from the page, asking the server for the page only. Exit 1 if one "
                                             "differs.")
    ap.parse_args(argv)
    texts = {}
    for what, html in pages(RAIZ):
        texts.setdefault(html, what)
    accepted = [(what, html, view) for html, what in texts.items() if (view := built_view(html)) is not None]
    built = module_page()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", so_mock.free_port()), Pages)
    server.pages = [(NO_SCRIPTS, html) for _, html, _ in accepted] + [(BUILT_SCRIPTS, built)]
    server.asked = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        views = asyncio.run(chrome_views(base, len(server.pages), server.asked))
    finally:
        server.shutdown()
        server.server_close()
    results = [(len(accepted) > 2 and accepted[0][0] == "the theme template" and accepted[1][0] == "the gallery template",
                f"the build accepts the theme, the gallery and {len(accepted) - 2} of the cases")]
    for (what, _, view), (seen, _, _) in zip(accepted, views):
        results.append((view == seen, f"{what}: the build reads the scripts, styles and links Chrome has "
                                      f"({len(view)}{'' if view == seen else f'; build {view}, Chrome {seen}'})"))
    built_seen, ran, asked = views[-1]
    asked = [path for path in asked if path != f"/{len(accepted)}"]
    results.append((built_view(built, True) == built_seen and ran == "a after b á ç ⋯ ? > # % </script> <!--" and not asked,
                    f"a built page with modules runs them from its import map, asking the server for nothing but the "
                    f"page (ran: {ran!r}, other requests: {asked}, build {built_view(built, True)}, "
                    f"Chrome {built_seen})"))
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
