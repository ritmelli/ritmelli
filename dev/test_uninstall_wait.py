import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "instalador" / "testa-atualizador.ps1"
ME = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def uninstall_wait():
    text = SCRIPT.read_text(encoding="utf-8")
    helpers = [line for line in text.splitlines() if re.match(r"function \w+\b.*\}\s*$", line)]
    found = re.search(r"Start-Process \"\$app\\unins000\.exe\".*\n.*?Espera 120 (\{.*\})\)\) \{", text)
    return helpers, found.group(1) if found else None


def run(helpers, condition, app):
    code = "\n".join(["$ErrorActionPreference = 'Stop'", *helpers, "$app = $env:RITMELLI_TEST_APP", "$pasta = \"$app\\atualizacao\"",
                      f"$cond = {condition}",
                      "try { $null = Test-Path $pasta; 'direct=ok' } catch { \"direct=$($_.FullyQualifiedErrorId)\" }",
                      "try { \"result=$(& $cond)\" } catch { \"threw=$($_.FullyQualifiedErrorId)\" }"])
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", code], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120,
                       env=dict(os.environ, RITMELLI_TEST_APP=str(app)))
    return (p.stdout + p.stderr).strip().splitlines()


def icacls(*args):
    subprocess.run(["icacls", *map(str, args)], capture_output=True, check=False)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    helpers, condition = uninstall_wait()
    check(condition is not None, f"the uninstaller wait of {SCRIPT.name} is found ({condition})")
    if condition is None:
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="ritmelli-uninstall-wait-"))
    try:
        app = tmp / "Ritmelli"
        (app / "atualizacao").mkdir(parents=True)
        out = run(helpers, condition, app)
        check(out == ["direct=ok", "result=False"], f"an update folder still there keeps the wait going ({out})")
        icacls(app / "atualizacao", "/deny", f"{ME}:(RA,REA,RD,X)")
        icacls(app, "/deny", f"{ME}:(RD)")
        try:
            out = run(helpers, condition, app)
        finally:
            icacls(app, "/reset", "/T", "/Q")
            icacls(app / "atualizacao", "/reset", "/Q")
        check(out[:1] == ["direct=ItemExistsUnauthorizedAccessError,Microsoft.PowerShell.Commands.TestPathCommand"],
              f"the ACL makes a plain Test-Path of the update folder throw access denied, as on CI ({out})")
        check(out[1:] == ["result=False"], "an update folder whose check is refused (access denied, as while the "
                                           f"uninstaller deletes it) counts as still there and keeps the wait going ({out})")
        (app / "atualizacao").rmdir()
        out = run(helpers, condition, app)
        check(out[1:] == ["result=True"], f"with the app and the update folder gone, the wait ends ({out})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
