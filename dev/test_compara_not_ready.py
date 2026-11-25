import asyncio
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from websockets.exceptions import ConnectionClosedError

ROOT = Path(__file__).resolve().parent.parent
CONSOLE_MARK = "ritmelli-test-console-error"
SCRIPT_MARK = "ritmelli-test-missing.js"
NEVER_READY = ("(() => { if (!window.__ritmelliTest) { window.__ritmelliTest = true; console.error('" + CONSOLE_MARK +
               "'); const s = document.createElement('script'); s.src = '" + SCRIPT_MARK + "'; "
               "document.head.appendChild(s); } return false; })()")
DRIVER = r"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "dev"))
import compara
compara.PRONTO = sys.argv[4]
compara.PRONTA_S = 3.0
sys.argv = ["compara.py", "--ref", "--sizes", sys.argv[2], "--pasta", sys.argv[3]]
sys.exit(compara.main())
"""

_spec = importlib.util.spec_from_file_location("compara", ROOT / "dev" / "compara.py")
compara = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compara)

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def never_ready(size, density, mesa):
    with tempfile.TemporaryDirectory(prefix="ritmelli-nao-pronto-") as tmp:
        p = subprocess.run([sys.executable, "-c", DRIVER, str(ROOT), f"{size}@{density}", tmp, NEVER_READY], cwd=ROOT,
                           env=dict(os.environ, PYTHONUTF8="1"), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
        out = p.stdout + p.stderr
        print(out.rstrip())
        lines = out.splitlines()
        where = "the PC" if mesa else "the phone"
        check(p.returncode != 0 and f"vazio-{size}: o tema nao ficou pronto" in out
              and (" (sem o body.mesa-dj)" in out) == mesa,
              f"on {where}, a theme that never gets ready fails the capture (exit {p.returncode})")
        names = [n for n, _ in compara.PRONTA_CONDICOES] + ["shelf on screen"] + (["body.mesa-dj"] if mesa else [])
        for name in names:
            check(any(line.startswith(f"  {name}: ") for line in lines), f"on {where}, it prints the condition {name}")
        check(any(line.startswith("  console: ") and CONSOLE_MARK in line for line in lines),
              f"on {where}, it prints the console.error of the page")
        check(any(line.startswith("  browser: ") and SCRIPT_MARK in line for line in lines),
              f"on {where}, it prints the browser's line for the script that did not load")
        print_file = Path(tmp) / "nao-pronto" / f"vazio-{size}.png"
        check(print_file.is_file() and print_file.stat().st_size > 0, f"on {where}, it saves a print of the page")


class ClosedChrome:
    erros = ["console.error: collected before the close"]
    log_erros = ["Failed to load resource: collected.js"]
    barrados = []

    def __init__(self, error):
        self.error = error

    async def js(self, expr):
        raise self.error

    async def png(self):
        raise self.error


def closed_connection(error):
    kind = type(error).__name__
    started = asyncio.run(asyncio.wait_for(compara.espera_pronto(ClosedChrome(error), "true", "vazio-1x1"), 5))
    check(started is False, f"with a {kind}, the wait for the ready signal gives up at once and goes to the diagnostic")
    out = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="ritmelli-nao-pronto-") as tmp, contextlib.redirect_stdout(out):
        try:
            asyncio.run(compara.nao_ficou_pronto(ClosedChrome(error), "vazio-1x1", False, Path(tmp)))
            ended = None
        except SystemExit as ex:
            ended = str(ex)
    text = out.getvalue()
    print(text.rstrip())
    check(ended == f"vazio-1x1: o tema nao ficou pronto em {compara.PRONTA_S:.0f} s"
          and f"the conditions did not come: {kind}" in text
          and "console: console.error: collected before the close" in text
          and "browser: Failed to load resource: collected.js" in text and "the print did not come" in text,
          f"with a {kind}, the diagnostic still prints what it collected and fails")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    closed_connection(ConnectionClosedError(None, None))
    closed_connection(ConnectionError("the CDP connection ended: closed"))
    never_ready("390x844", 3, mesa=False)
    never_ready("1920x1080", 1, mesa=True)
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
