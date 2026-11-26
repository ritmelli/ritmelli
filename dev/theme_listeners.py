import argparse
import asyncio
import difflib
import importlib
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
compara = importlib.import_module("compara")
so_mock = importlib.import_module("so_mock")
missing_script = importlib.import_module("missing_script")

RAIZ = Path(__file__).resolve().parent.parent
USAGE = """Proof that a theme change keeps the page's event listeners: the theme of two commits (the head defaults to the
working tree) opened in a headless Chrome against a --mock server of each, at the PC size (the DJ desk) and at a phone
size, once the page is connected. Two tables are compared:
- the listeners on at that moment, read in the order they were added (the DevTools getEventListeners), with the
  capture, passive and once flags and the handler's source text, each line without its indentation: those of every
  node, the document and the window, of navigator.connection, of every MediaQueryList the page made with a listener
  on (matchMedia(<its query>) #<n>, numbered per query in the order of its first add or remove call, then of its
  making) and of the other targets the page added a listener to, by their kind;
- every addEventListener, removeEventListener, addListener and removeListener call the page made since it began, per
  target and event type, in order, with the options as given and the handler's text (a node by its path at its first
  call, with #<n> when another node had that path): a listener added and removed before the table is read shows
  here.
Exit 0 only when both commits give the same tables; otherwise the differences are printed and the exit is 1. The file a
handler lives in is not compared: moving a handler between files, or into a function, keeps the tables. The <script>
tags are left out: their only listener is the onerror="scriptFailed(this)" that dev/testa_i18n.py requires on each of
them."""
KEY = "Symbol.for('ritmelli-listeners')"
RECORDER = """(() => {
  'use strict';
  const add = EventTarget.prototype.addEventListener, remove = EventTarget.prototype.removeEventListener;
  const list = MediaQueryList.prototype, listen = list.addListener, unlisten = list.removeListener;
  const media = window.matchMedia;
  const calls = [], targets = [], made = [], nodes = new Map(), paths = new Map();
  const path = e => {
    const parts = [];
    for (let n = e; n && n.nodeType === 1; n = n.parentElement) {
      if (n.id) { parts.unshift('#' + n.id); break; }
      const same = [...(n.parentElement ? n.parentElement.children : [])].filter(x => x.tagName === n.tagName);
      parts.unshift(n.tagName.toLowerCase() + (same.length > 1 ? `:nth-of-type(${same.indexOf(n) + 1})` : ''));
    }
    return parts.join(' > ');
  };
  const queries = new Map();
  const query = t => {
    if (!queries.has(t)) queries.set(t, [...queries.keys()].filter(q => q.media === t.media).length + 1);
    return `matchMedia(${t.media}) #${queries.get(t)}`;
  };
  const name = t => t === window ? 'window' : t === document ? 'document' : t instanceof Node ? path(t)
    : t instanceof MediaQueryList ? query(t) : t === navigator.connection ? 'navigator.connection'
    : t.constructor.name;
  const node = t => {
    if (!nodes.has(t)) {
      const p = path(t), n = (paths.get(p) ?? 0) + 1;
      paths.set(p, n);
      nodes.set(t, n > 1 ? `${p} #${n}` : p);
    }
    return nodes.get(t);
  };
  const options = o => o !== null && typeof o === 'object' ? [o.capture ?? null, o.passive ?? null, o.once ?? null]
    : [o ?? null, null, null];
  const record = (op, target, type, listener, o) => {
    if (!(target instanceof Node) && target !== window && !targets.includes(target)) targets.push(target);
    const handler = typeof listener === 'function' ? listener : listener?.handleEvent ?? listener;
    calls.push([target instanceof Node && target !== document ? node(target) : name(target), type, op, ...options(o),
                String(handler)]);
  };
  EventTarget.prototype.addEventListener = function addEventListener(type, listener, o) {
    record('add', this ?? window, type, listener, o);
    return add.call(this, type, listener, o);
  };
  EventTarget.prototype.removeEventListener = function removeEventListener(type, listener, o) {
    record('remove', this ?? window, type, listener, o);
    return remove.call(this, type, listener, o);
  };
  list.addListener = function addListener(listener) {
    record('addListener', this, 'change', listener);
    return listen.call(this, listener);
  };
  list.removeListener = function removeListener(listener) {
    record('removeListener', this, 'change', listener);
    return unlisten.call(this, listener);
  };
  window.matchMedia = function matchMedia(query) {
    const found = media.call(window, query);
    made.push(found);
    return found;
  };
  Object.defineProperty(window, %s, {value: {calls, targets, made, name}});
})()""" % KEY
READ = """(() => {
  const {calls, targets, made, name} = window[%s];
  const others = [...targets, ...made.filter(m => !targets.includes(m) && Object.keys(getEventListeners(m)).length),
                  ...(navigator.connection && !targets.includes(navigator.connection) ? [navigator.connection] : [])];
  const rows = [];
  for (const [where, target] of [['window', window], ['document', document], ...others.map(t => [name(t), t]),
                                 ...[...document.querySelectorAll(':not(script)')].map(e => [name(e), e])])
    for (const [kind, list] of Object.entries(getEventListeners(target)))
      for (const x of list) rows.push([where, kind, x.useCapture, x.passive, x.once, String(x.listener)]);
  return {rows, calls};
})()""" % KEY
SIZES = {"pc": None, "phone": {"width": 390, "height": 844, "deviceScaleFactor": 3, "mobile": True}}
READY_S = 15.0


def checkout(rev, folder):
    if rev is None:
        return RAIZ
    data = subprocess.run(["git", "-C", str(RAIZ), "archive", rev], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=BytesIO(data)) as tar:
        tar.extractall(folder, filter="data")
    return folder


async def table(tab, size):
    if size:
        await tab.cmd("Emulation.setDeviceMetricsOverride", **size)
    await tab.cmd("Page.addScriptToEvaluateOnNewDocument", source=RECORDER)
    await missing_script.open_page(tab)
    await tab.tab_reaches(lambda: tab.loads >= 1, READY_S)
    ready = await tab.page_reaches("s.online === true", READY_S)
    return ready.get("online") is True, await read_tables(tab)


async def read_tables(tab):
    found = await tab.cmd("Runtime.evaluate", expression=READ, includeCommandLineAPI=True, returnByValue=True)
    rows = {}
    for where, kind, capture, passive, once, text in found["result"]["value"]["rows"]:
        rows.setdefault(("on", where, kind), []).append((capture, passive, once, unindented(text)))
    for where, kind, op, capture, passive, once, text in found["result"]["value"]["calls"]:
        rows.setdefault(("calls", where, kind), []).append((op, capture, passive, once, unindented(text)))
    return rows


def unindented(text):
    return "\n".join(line.strip() for line in text.splitlines())


def tables(raiz):
    out = {}
    with tempfile.TemporaryDirectory(prefix="ritmelli-listeners-") as folder:
        tmp = Path(folder)
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = compara.sobe_servidor(tmp, so_mock.free_port(), log, raiz=raiz, config={"boas_vindas": True})
            try:
                for name, size in SIZES.items():
                    async def run(tab, size=size):
                        return await table(tab, size)
                    out[name] = asyncio.run(missing_script.with_tab(srv, run))
            finally:
                compara.para_servidor(srv)
    return out


def differences(a, b):
    lines = []
    for key in sorted(set(a) | set(b)):
        if a.get(key) != b.get(key):
            table, where, kind = key
            lines.append(f"{where} {kind}{' (the calls)' if table == 'calls' else ''}:")
            old, new = a.get(key, []), b.get(key, [])
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
                if tag != "equal":
                    lines += [f"  - {flags[:-1]} {flags[-1][:160]!r}" for flags in old[i1:i2]]
                    lines += [f"  + {flags[:-1]} {flags[-1][:160]!r}" for flags in new[j1:j2]]
    return lines


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("head", nargs="?")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="ritmelli-listeners-base-") as base_dir, \
            tempfile.TemporaryDirectory(prefix="ritmelli-listeners-head-") as head_dir:
        base = tables(checkout(args.base, Path(base_dir)))
        head = tables(checkout(args.head, Path(head_dir)))
    same = True
    for name in SIZES:
        (base_ready, a), (head_ready, b) = base[name], head[name]
        diff = differences(a, b)
        count = sum(len(v) for k, v in b.items() if k[0] == "on")
        made = sum(len(v) for k, v in b.items() if k[0] == "calls")
        print(f"{name}: {args.base} {'connected' if base_ready else 'NOT connected'}, "
              f"{args.head or 'working tree'} {'connected' if head_ready else 'NOT connected'}; "
              f"{count} listeners, {made} calls, "
              f"{len([x for x in diff if not x.startswith('  ')])} target(s) differ")
        print("\n".join(diff))
        same = same and base_ready and head_ready and not diff
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
