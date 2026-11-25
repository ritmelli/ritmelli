import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("testa_tudo", ROOT / "dev" / "testa_tudo.py")
testa_tudo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(testa_tudo)

PASSAGEM, CAPTURA = "dev/testa_passagem.py", "dev/test_captura.py"
failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    motor = set(testa_tudo.AREAS["motor"])
    needed = {"dev/testa_passagem.py", "dev/bumbo_mede.py", "engine.py", "batida.py", "transicao.py", "sonoridade.py",
              "fx.py", "microfone/preset.py", "microfone/voz.py", "requirements.txt"}
    check(needed <= motor, f"the motor area holds what the bench imports ({sorted(needed - motor)} missing)")
    check(set(testa_tudo.BANCA_AREA) == set(testa_tudo.BANCA), "every BANCA test has an area")
    cases = {("engine.py",): [PASSAGEM], ("batida.py",): [PASSAGEM], ("microfone/preset.py",): [PASSAGEM],
             ("themes/ritmelli/deck.js",): [CAPTURA], ("dev/compara.py",): [CAPTURA], ("README.md",): [],
             ("docs/arquitetura/dev.md",): [], (".github/workflows/testa.yml",): [PASSAGEM, CAPTURA],
             ("instalador/travas.txt",): [PASSAGEM, CAPTURA]}
    for files, expected in cases.items():
        got = testa_tudo.banca_da_vez(testa_tudo.areas(list(files)))
        check(got == expected, f"a PR that changes {files[0]} runs {expected or 'no long test'} in the Banca ({got})")
    p = subprocess.run([sys.executable, "dev/testa_tudo.py", "--banca", "--base", "HEAD"], cwd=ROOT,
                       env=dict(os.environ, PYTHONUTF8="1"), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    out = p.stdout + p.stderr
    check(p.returncode == 0 and "0 of 0 passed" in out and "testa_passagem" not in out,
          f"--banca --base with nothing changed runs no long test (exit {p.returncode})")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
