"""dev/theme_listeners.py on a page of its own, in a headless Chrome: the listeners of a MediaQueryList, of
navigator.connection and of a node are in the table of what is on, a listener added and removed before the table is
read is in the table of the calls, and taking out the MediaQueryList's listener, or the add and remove pair, makes the
two tables differ. Exit 1 if a check fails."""
import asyncio
import importlib
import sys
import types
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
theme_listeners = importlib.import_module("theme_listeners")
missing_script = importlib.import_module("missing_script")

PAGE = """<!doctype html><div id="box"></div><script>
'use strict';
const wide = matchMedia('(min-width: 10px)'), same = matchMedia('(min-width: 10px)');
function onWide() {}
function first(e) { e.stopImmediatePropagation(); }
wide.addEventListener('change', first);
%s
if (navigator.connection) navigator.connection.addEventListener('change', function onNetwork() {});
function gone() {}
%s
document.getElementById('box').addEventListener('click', function onClick() {}, {passive: true});
</script>"""
MEDIA = "wide.addEventListener('change', onWide);"
OTHER_INSTANCE = "same.addEventListener('change', onWide);"
PAIR = "addEventListener('resize', gone); removeEventListener('resize', gone);"
LOADED_S = 10.0


async def read(tab, source):
    loads = tab.loads
    await tab.cmd("Page.navigate", url="data:text/html," + urllib.parse.quote(source))
    await tab.tab_reaches(lambda: tab.loads > loads, LOADED_S)
    return await theme_listeners.read_tables(tab)


async def pages(tab):
    await tab.cmd("Page.addScriptToEvaluateOnNewDocument", source=theme_listeners.RECORDER)
    return [await read(tab, PAGE % parts) for parts in ((MEDIA, PAIR), ("", PAIR), (MEDIA, ""), (OTHER_INSTANCE, PAIR))]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    full, no_media, no_pair, other_instance = asyncio.run(missing_script.with_tab(types.SimpleNamespace(base="http://127.0.0.1:9"),
                                                                  pages))
    on = {key[1:]: [row[-1] for row in rows] for key, rows in full.items() if key[0] == "on"}
    calls = {key[1:]: [(row[0], row[-1]) for row in rows] for key, rows in full.items() if key[0] == "calls"}
    checks = [
        (on.get(("matchMedia((min-width: 10px)) #1", "change")) == ["function first(e) { e.stopImmediatePropagation(); }",
                                                                    "function onWide() {}"],
         f"the MediaQueryList's change listeners are on, named by its query ({on})"),
        (on.get(("navigator.connection", "change")) == ["function onNetwork() {}"],
         "the navigator.connection change listener is on"),
        (full.get(("on", "#box", "click")) == [(False, True, False, "function onClick() {}")],
         f"the node's listener is on with its flags ({full.get(('on', '#box', 'click'))})"),
        (("window", "resize") not in on and calls.get(("window", "resize")) == [("add", "function gone() {}"),
                                                                                  ("remove", "function gone() {}")],
         f"the listener added and removed before the read is only in the calls ({calls.get(('window', 'resize'))})"),
        (any(line.startswith("matchMedia((min-width: 10px)) #1 change")
             for line in theme_listeners.differences(full, no_media)),
         "without the MediaQueryList's listener, the tables differ on it"),
        ({line for line in theme_listeners.differences(full, other_instance) if not line.startswith(" ")}
         == {"matchMedia((min-width: 10px)) #1 change:", "matchMedia((min-width: 10px)) #2 change:",
             "matchMedia((min-width: 10px)) #1 change (the calls):",
             "matchMedia((min-width: 10px)) #2 change (the calls):"},
         "a listener moved to another MediaQueryList of the same query, after one that stops the event, differs"),
        (any(line.startswith("window resize (the calls)") for line in theme_listeners.differences(full, no_pair)),
         "without the add and remove pair, the calls differ on it"),
        (not theme_listeners.differences(full, full), "the same page gives no difference"),
    ]
    for ok, message in checks:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
