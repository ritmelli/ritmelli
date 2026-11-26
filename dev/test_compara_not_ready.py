import asyncio
import contextlib
import io
import os
import re
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
import fitcheck
compara.PRONTO = sys.argv[4]
fitcheck.PRONTA_S = 3.0
sys.argv = ["compara.py", "--ref", "--sizes", sys.argv[2], "--pasta", sys.argv[3]]
sys.exit(compara.main())
"""

sys.path.insert(0, str(ROOT / "dev"))
import compara  # noqa: E402
import fitcheck  # noqa: E402

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
        check(p.returncode != 0 and f"vazio-{size}: the theme was not ready in 3 s" in out
              and (" (without the body.mesa-dj)" in out) == mesa and "browser went away" not in out,
              f"on {where}, a theme that never gets ready fails the capture (exit {p.returncode})")
        names = [n for n, _ in compara.READY_CONDITIONS] + ["shelf on screen"] + (["body.mesa-dj"] if mesa else [])
        for name in names:
            check(any(line.startswith(f"  {name}: ") for line in lines), f"on {where}, it prints the condition {name}")
        check(any(line.startswith("  console: ") and CONSOLE_MARK in line for line in lines),
              f"on {where}, it prints the console.error of the page")
        check(any(line.startswith("  browser: ") and SCRIPT_MARK in line for line in lines),
              f"on {where}, it prints the browser's line for the script that did not load")
        check(any(re.fullmatch(rf"  response: 404 http://127\.0\.0\.1:\d+/.*{re.escape(SCRIPT_MARK)}", line)
                  for line in lines),
              f"on {where}, it prints the 404 of the script, read from Network.responseReceived")
        print_file = Path(tmp) / "nao-pronto" / f"vazio-{size}.png"
        check(print_file.is_file() and print_file.stat().st_size > 0, f"on {where}, it saves a print of the page")


class ClosedChrome:
    barrados = []

    def __init__(self, error):
        self.error = error
        self.calls = []
        self.events = fitcheck.PageEvents()
        self.events.page_errors.append("console.error: collected before the close")
        self.events.browser_errors.append("Failed to load resource: collected.js")
        self.events.failed_responses.append("404 http://127.0.0.1:1/collected.js")

    async def cmd(self, method, **params):
        self.calls.append(method)
        raise self.error


def closed_connection(error):
    kind = type(error).__name__
    chrome = ClosedChrome(error)
    outcome = asyncio.run(asyncio.wait_for(fitcheck.wait_ready(chrome.cmd, "true", [], 20), 5))
    check(outcome is fitcheck.Ready.CHROME_GONE,
          f"with a {kind}, the wait for the ready signal gives up at once as a Chrome that went away ({outcome})")
    out = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="ritmelli-nao-pronto-") as tmp, contextlib.redirect_stdout(out):
        try:
            asyncio.run(compara.report_not_ready(chrome, "vazio-1x1", outcome, False, Path(tmp)))
            ended = None
        except SystemExit as ex:
            ended = str(ex)
        shots = list(Path(tmp).rglob("*.png"))
    text = out.getvalue()
    print(text.rstrip())
    check(ended is not None and "browser went away" in ended and "not ready" not in ended
          and "console: console.error: collected before the close" in text
          and "browser: Failed to load resource: collected.js" in text
          and "response: 404 http://127.0.0.1:1/collected.js" in text and not shots,
          f"with a {kind}, the diagnostic says the Chrome went away, not that the theme was not ready, and prints "
          f"what it collected ({ended})")


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
