import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIZE = "390x844"
DRIVER = r"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "dev"))
import compara
compara.PRONTO = "(S.lib.length > 0 && false)"
compara.PRONTA_S = 2.0
sys.argv = ["compara.py", "--ref", "--sizes", sys.argv[2], "--pasta", sys.argv[3]]
sys.exit(compara.main())
"""

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(ROOT / "dev"))
    from fitcheck import PRONTA_CONDICOES
    with tempfile.TemporaryDirectory(prefix="ritmelli-nao-pronto-") as tmp:
        p = subprocess.run([sys.executable, "-c", DRIVER, str(ROOT), f"{SIZE}@3", tmp], cwd=ROOT,
                           env=dict(os.environ, PYTHONUTF8="1"), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
        out = p.stdout + p.stderr
        print(out.rstrip())
        lines = out.splitlines()
        check(p.returncode != 0 and f"vazio-{SIZE}: o tema nao ficou pronto" in out,
              f"a theme that never gets ready fails the capture (exit {p.returncode})")
        for name, _ in [*PRONTA_CONDICOES, ("shelf on screen", "")]:
            check(any(line.startswith(f"  {name}: ") for line in lines), f"the diagnostic prints the condition {name}")
        for kind in ("console", "browser"):
            check(any(line.startswith(f"  {kind}: ") for line in lines), f"the diagnostic prints the {kind} errors")
        print_file = Path(tmp) / "nao-pronto" / f"vazio-{SIZE}.png"
        check(print_file.is_file() and print_file.stat().st_size > 0, f"the diagnostic saves a print in {print_file}")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
