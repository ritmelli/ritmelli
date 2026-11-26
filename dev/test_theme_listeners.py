"""dev/theme_listeners.py on a page of its own, in a headless Chrome: the listeners of a MediaQueryList (by
addEventListener, by addListener and by onchange), of navigator.connection (both ways) and of a node are in the table
of what is on, a listener added and removed, or an onchange set and cleared, before the table is read is in the table
of the calls, and taking out or moving any of them makes the two tables differ. Exit 1 if a check fails."""
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
const b1 = document.createElement('button'), b2 = document.createElement('button');
function onWide() {}
function first(e) { e.stopImmediatePropagation(); }
function onOld() {}
function onButton() {}
function gone() {}
wide.addEventListener('change', first);
document.getElementById('box').addEventListener('click', function onClick() {}, {passive: true});
{media}
{cleared_media}
{cleared_network}
{order}
{connection}
{pair}
{legacy}
{property}
{network}
{buttons}
</script>"""
PARTS = {
    "media": "wide.addEventListener('change', onWide);",
    "cleared_media": "const temporary = matchMedia('(min-width: 40px)'); temporary.onchange = function onCleared() {};"
                     " temporary.onchange = null;",
    "cleared_network": "if (navigator.connection) { navigator.connection.onchange = function onNetworkCleared() {};"
                       " navigator.connection.onchange = null; }",
    "order": "const [l1, l2, l3] = [1, 2, 3].map(() => matchMedia('(min-width: 50px)'));"
             " l1.addEventListener('change', onOld); l2.addEventListener('change', onWide);",
    "connection": "if (navigator.connection) navigator.connection.addEventListener('change', function onNetwork() {});",
    "pair": "addEventListener('resize', gone); removeEventListener('resize', gone);",
    "legacy": "matchMedia('(min-width: 20px)').addListener(onOld);",
    "property": "matchMedia('(min-width: 30px)').onchange = function onProperty() {};",
    "network": "if (navigator.connection) navigator.connection.onchange = function onNetworkProperty() {};",
    "buttons": "b1.addEventListener('click', onButton); b2.addEventListener('click', onButton);"
               " b1.removeEventListener('click', onButton);",
}
VARIANTS = {
    "without the MediaQueryList's listener": ({"media": ""}, "matchMedia((min-width: 10px)) #1 change:"),
    "with the listener moved to another MediaQueryList of the same query, after one that stops the event": (
        {"media": "same.addEventListener('change', onWide);"}, "matchMedia((min-width: 10px)) #2 change:"),
    "without the add and remove pair": ({"pair": ""}, "window resize (the calls):"),
    "without the addListener": ({"legacy": ""}, "matchMedia((min-width: 20px)) #1 change:"),
    "without the onchange of a MediaQueryList": ({"property": ""}, "matchMedia((min-width: 30px)) #1 change:"),
    "without the onchange of navigator.connection": ({"network": ""}, "navigator.connection change:"),
    "without an onchange set and cleared on a MediaQueryList": (
        {"cleared_media": ""}, "matchMedia((min-width: 40px)) #1 change (the calls):"),
    "without an onchange set and cleared on navigator.connection": (
        {"cleared_network": ""}, "navigator.connection change (the calls):"),
    "with a listener moved to a MediaQueryList of the same query made later, which the browser tells after": (
        {"order": "const [l1, l2, l3] = [1, 2, 3].map(() => matchMedia('(min-width: 50px)'));"
                  " l3.addEventListener('change', onOld); l2.addEventListener('change', onWide);"},
        "matchMedia((min-width: 50px)) #1 change:"),
    "with the remove call moved to the other button out of the page": (
        {"buttons": "b1.addEventListener('click', onButton); b2.addEventListener('click', onButton);"
                    " b2.removeEventListener('click', onButton);"}, "button click (the calls):"),
}
ONLY_ONCHANGE = {"connection": ""}
LOADED_S = 10.0


def page(parts):
    text = PAGE
    for slot, code in {**PARTS, **parts}.items():
        text = text.replace("{" + slot + "}", code)
    return text


async def read(tab, source):
    loads = tab.loads
    await tab.cmd("Page.navigate", url="data:text/html," + urllib.parse.quote(source))
    await tab.tab_reaches(lambda: tab.loads > loads, LOADED_S)
    return await theme_listeners.read_tables(tab)


async def pages(tab):
    await tab.cmd("Page.addScriptToEvaluateOnNewDocument", source=theme_listeners.RECORDER)
    return [await read(tab, page(parts)) for parts in [{}, ONLY_ONCHANGE, *(parts for parts, _ in VARIANTS.values())]]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    full, only_onchange, *variants = asyncio.run(missing_script.with_tab(types.SimpleNamespace(base="http://127.0.0.1:9"), pages))
    on = {key[1:]: [row[-1] for row in rows] for key, rows in full.items() if key[0] == "on"}
    calls = {key[1:]: [(row[0], row[-1]) for row in rows] for key, rows in full.items() if key[0] == "calls"}
    checks = [
        (on.get(("matchMedia((min-width: 10px)) #1", "change")) == ["function first(e) { e.stopImmediatePropagation(); }",
                                                                    "function onWide() {}"],
         f"the MediaQueryList's change listeners are on, named by its query ({on})"),
        (on.get(("matchMedia((min-width: 20px)) #1", "change")) == ["function onOld() {}"]
         and calls.get(("matchMedia((min-width: 20px)) #1", "change")) == [("addListener", "function onOld() {}")],
         "the listener of addListener is on and in the calls"),
        (on.get(("matchMedia((min-width: 30px)) #1", "change")) == ["function onProperty() {}"],
         "the onchange of a MediaQueryList is on"),
        (on.get(("navigator.connection", "change")) == ["function onNetwork() {}", "function onNetworkProperty() {}"],
         f"both navigator.connection change listeners are on ({on.get(('navigator.connection', 'change'))})"),
        (only_onchange.get(("on", "navigator.connection", "change"), [[None]])[0][-1]
         == "function onNetworkProperty() {}", "the onchange of navigator.connection is on with no other listener there"),
        (full.get(("on", "#box", "click")) == [(False, True, False, "function onClick() {}")],
         f"the node's listener is on with its flags ({full.get(('on', '#box', 'click'))})"),
        (("window", "resize") not in on and calls.get(("window", "resize")) == [("add", "function gone() {}"),
                                                                                  ("remove", "function gone() {}")],
         f"the listener added and removed before the read is only in the calls ({calls.get(('window', 'resize'))})"),
        (calls.get(("button", "click")) == [("add", "function onButton() {}"), ("remove", "function onButton() {}")]
         and calls.get(("button #2", "click")) == [("add", "function onButton() {}")],
         "two buttons out of the page with the same path keep their own calls"),
        (not theme_listeners.differences(full, full), "the same page gives no difference"),
    ]
    for (title, (_, target)), tables in zip(VARIANTS.items(), variants):
        found = theme_listeners.differences(full, tables)
        checks.append((target in found, f"{title}, the tables differ on {target} ({[x for x in found if x[0] != ' ']})"))
    for ok, message in checks:
        print(f"{'OK  ' if ok else 'FAIL'} {message}", flush=True)
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
