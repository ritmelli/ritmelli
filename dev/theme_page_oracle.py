import argparse
import asyncio
import http.server
import importlib
import sys
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


def pages(raiz):
    found = [(f"the {name} template", (raiz / folder / "index.html").read_text(encoding="utf-8"))
             for name, folder in (("theme", "themes/ritmelli"), ("gallery", "gallery"))]
    found += [(what, f"<head>\n{tag}\n") for what, (tag, _, _) in theme_page_cases.REFUSED.items()]
    return found + [(what, tag) for what, (tag, _) in theme_page_cases.KEPT.items()]


def built_view(html):
    try:
        return [[tag, HTML, attrs] for tag, attrs in theme_page.template(html).elements]
    except theme_page.ThemePageError:
        return None


class Pages(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        number = self.path.removeprefix("/")
        if not number.isdigit() or int(number) >= len(self.server.pages):
            self.send_error(404)
            return
        body = self.server.pages[int(number)].encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


async def chrome_views(base, count):
    async def run(tab):
        await tab.cmd("Emulation.setScriptExecutionDisabled", value=True)
        views = []
        for n in range(count):
            loads = tab.loads
            await tab.cmd("Page.navigate", url=f"{base}/{n}")
            loaded = await tab.tab_reaches(lambda: tab.loads > loads, LOADED_S)
            views.append(await tab.js(READ) if loaded else f"page {n} did not load in {LOADED_S:.0f} s")
        return views
    return await missing_script.with_tab(types.SimpleNamespace(base=base), run)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="The theme page's grammar against Chrome: for the theme, the gallery and "
                                             "every case of dev/theme_page_cases.py the build accepts, the scripts, "
                                             "styles and links the build reads (src, href, rel and type) are the ones "
                                             "Chrome's DOM has, in order. Exit 1 if one differs.")
    ap.parse_args(argv)
    accepted = [(what, html, view) for what, html in pages(RAIZ) if (view := built_view(html)) is not None]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", so_mock.free_port()), Pages)
    server.pages = [html for _, html, _ in accepted]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        views = asyncio.run(chrome_views(f"http://127.0.0.1:{server.server_address[1]}", len(accepted)))
    finally:
        server.shutdown()
        server.server_close()
    results = [(len(accepted) > 2 and accepted[0][0] == "the theme template" and accepted[1][0] == "the gallery template",
                f"the build accepts the theme, the gallery and {len(accepted) - 2} of the cases")]
    for (what, _, built), seen in zip(accepted, views):
        results.append((built == seen, f"{what}: the build reads the scripts, styles and links Chrome has "
                                       f"({len(built)}{'' if built == seen else f'; build {built}, Chrome {seen}'})"))
    for ok, message in results:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
