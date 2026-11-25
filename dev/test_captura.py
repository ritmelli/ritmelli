import importlib.util
import os
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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="ritmelli-captura-") as tmp:
        tmp = Path(tmp)
        cache, tela, output = tmp / "cache", tmp / "tela", tmp / "github_output"
        output.touch()
        p = subprocess.run([sys.executable, "dev/testa_tudo.py", "--captura", str(cache), "--pasta", str(tela)],
                           cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1", GITHUB_OUTPUT=str(output)),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        print((p.stdout + p.stderr)[-3000:].rstrip())
        check(p.returncode == 0, f"the --captura of the HEAD passes (exit {p.returncode})")
        check("head_cache=true" in output.read_text(encoding="utf-8").splitlines(),
              "it tells the workflow to save the capture (head_cache=true)")
        key = (cache / "captura.txt").read_text(encoding="utf-8").strip() if (cache / "captura.txt").is_file() else ""
        check(key == testa_tudo.chave_captura(head), f"the cache folder holds the key of the HEAD ({key})")
        taken = sorted(f.name for f in (tela / "compara" / "ref").glob("*.png"))
        saved = sorted(f.name for f in cache.glob("*.png"))
        check(bool(taken) and saved == taken, f"the cache folder holds every print taken ({len(saved)} of {len(taken)})")
        check(testa_tudo.le_captura(cache, testa_tudo.chave_captura(head)) != [],
              "a PR with the HEAD as its base reads the capture back from that folder")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
