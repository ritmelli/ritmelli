import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("testa_tudo", ROOT / "dev" / "testa_tudo.py")
testa_tudo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(testa_tudo)

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


UNCOMMITTED = "\nthrow new Error('ritmelli-test-uncommitted-edit');\n"
KEY = "import sys; sys.path.insert(0, 'dev'); import testa_tudo; print(testa_tudo.chave_captura(sys.argv[1]))"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="ritmelli-captura-") as tmp:
        tmp = Path(tmp)
        cache, tela, output, wt = tmp / "cache", tmp / "tela", tmp / "github_output", tmp / "wt"
        output.touch()
        subprocess.run(["git", "worktree", "add", "--detach", str(wt), head], cwd=ROOT, check=True,
                       capture_output=True)
        try:
            for script in ("dev/testa_tudo.py", *testa_tudo.CAPTURA):
                shutil.copy2(ROOT / script, wt / script)
            with open(wt / "themes" / "ritmelli" / "ui-events.js", "a", encoding="utf-8") as f:
                f.write(UNCOMMITTED)
            p = subprocess.run([sys.executable, "dev/testa_tudo.py", "--captura", str(cache), "--pasta", str(tela)],
                               cwd=wt, env=dict(os.environ, PYTHONUTF8="1", GITHUB_OUTPUT=str(output)),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            expected = subprocess.run([sys.executable, "-c", KEY, head], cwd=wt, capture_output=True, text=True,
                                      encoding="utf-8").stdout.strip()
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT, capture_output=True)
        print((p.stdout + p.stderr)[-3000:].rstrip())
        check(p.returncode == 0 and "ritmelli-test-uncommitted-edit" not in p.stdout + p.stderr,
              f"the --captura renders the commit, not an uncommitted edit of the theme (exit {p.returncode})")
        check("head_cache=true" in output.read_text(encoding="utf-8").splitlines(),
              "it tells the workflow to save the capture (head_cache=true)")
        key = (cache / "captura.txt").read_text(encoding="utf-8").strip() if (cache / "captura.txt").is_file() else ""
        check(bool(expected) and key == expected, f"the cache folder holds the key of the HEAD ({key})")
        taken = sorted(f.name for f in (tela / "compara" / "ref").glob("*.png"))
        saved = sorted(f.name for f in cache.glob("*.png"))
        check(bool(taken) and saved == taken, f"the cache folder holds every print taken ({len(saved)} of {len(taken)})")
        check(testa_tudo.le_captura(cache, expected) != [],
              "a PR with the HEAD as its base reads the capture back from that folder")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
