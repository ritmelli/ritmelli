import argparse
import asyncio
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
size, once the page is connected. For every node, the document and the window, the listeners of each event type are
read in the order they were added (the DevTools getEventListeners), with the capture, passive and once flags and the
handler's source text, each line without its indentation. Exit 0 only when both commits give the same table;
otherwise the differences are printed and the exit is 1. The file a handler lives in is not compared: moving a handler
between files, or into a function, keeps the table. The <script> tags are left out."""
READ = """(() => {
  const path = e => {
    const parts = [];
    for (let n = e; n && n.nodeType === 1; n = n.parentElement) {
      if (n.id) { parts.unshift('#' + n.id); break; }
      const same = [...(n.parentElement ? n.parentElement.children : [])].filter(x => x.tagName === n.tagName);
      parts.unshift(n.tagName.toLowerCase() + (same.length > 1 ? `:nth-of-type(${same.indexOf(n) + 1})` : ''));
    }
    return parts.join(' > ');
  };
  const rows = [];
  for (const [where, target] of [['window', window], ['document', document],
                                 ...[...document.querySelectorAll(':not(script)')].map(e => [path(e), e])])
    for (const [kind, list] of Object.entries(getEventListeners(target)))
      for (const x of list) rows.push([where, kind, x.useCapture, x.passive, x.once, String(x.listener)]);
  return rows;
})()"""
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
    await missing_script.open_page(tab)
    await tab.tab_reaches(lambda: tab.loads >= 1, READY_S)
    ready = await tab.page_reaches("s.online === true", READY_S)
    found = await tab.cmd("Runtime.evaluate", expression=READ, includeCommandLineAPI=True, returnByValue=True)
    rows = {}
    for where, kind, capture, passive, once, text in found["result"]["value"]:
        rows.setdefault((where, kind), []).append(
            (capture, passive, once, "\n".join(line.strip() for line in text.splitlines())))
    return ready.get("online") is True, rows


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
            where, kind = key
            lines.append(f"{where} {kind}:")
            lines += [f"  - {flags[:3]} {flags[3][:160]!r}" for flags in a.get(key, [])]
            lines += [f"  + {flags[:3]} {flags[3][:160]!r}" for flags in b.get(key, [])]
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
        count = sum(len(v) for v in b.values())
        print(f"{name}: {args.base} {'connected' if base_ready else 'NOT connected'}, "
              f"{args.head or 'working tree'} {'connected' if head_ready else 'NOT connected'}; "
              f"{count} listeners, {len(diff and [x for x in diff if not x.startswith('  ')])} target(s) differ")
        print("\n".join(diff))
        same = same and base_ready and head_ready and not diff
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
