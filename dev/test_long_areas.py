import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("testa_tudo", ROOT / "dev" / "testa_tudo.py")
testa_tudo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(testa_tudo)

BENCH, CAPTURE = "bench", "capture"
failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def without(*gone):
    return lambda rel: None if rel in gone else testa_tudo.read_disk(rel)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    check(set(testa_tudo.LONG_TEST_ENTRIES) == set(testa_tudo.LONG_TESTS), "every long test has its entry points")
    bench = testa_tudo.local_imports(testa_tudo.LONG_TEST_ENTRIES[BENCH], testa_tudo.read_disk)
    needed = {"dev/testa_passagem.py", "dev/bumbo_mede.py", "engine.py", "batida.py", "transicao.py", "sonoridade.py",
              "fx.py", "microfone/preset.py", "microfone/voz.py"}
    check(needed <= bench, f"the inputs of the bench hold what it imports ({sorted(needed - bench)} missing)")
    both, nothing = [BENCH, CAPTURE], []
    cases = {"engine.py": both, "batida.py": both, "microfone/preset.py": both, "dev/testa_passagem.py": [BENCH],
             "dev/bumbo_mede.py": [BENCH], "comandos.py": [CAPTURE], "ritmelli.py": [CAPTURE],
             "andamento.py": [CAPTURE], "dev/compara.py": [CAPTURE], "dev/test_capture.py": [CAPTURE],
             "dev/testa_tudo.py": both, "instalador/ffmpeg/bin/ffmpeg.exe": both, "modelos/compasso.onnx": both,
             "vozes.json": both, "icone/ritmelli.ico": both, "themes/ritmelli/deck.js": both,
             "requirements-dev.txt": both, "instalador/travas.txt": both, ".github/workflows/testa.yml": both,
             "README.md": nothing, "docs/arquitetura/dev.md": nothing, "dev/celular.py": nothing,
             "dev/test_long_areas.py": nothing}
    for changed, expected in cases.items():
        got = testa_tudo.long_tests_for([changed])
        check(got == expected, f"a PR that changes {changed} runs {expected or 'no long test'} ({got})")
    removed = ["dev/bumbo_mede.py"]
    check(testa_tudo.long_tests_for(removed, read=without(*removed)) == [],
          "a module removed here is not an input of the tree here")
    got = testa_tudo.long_tests_for(removed, base="HEAD", read=without(*removed))
    check(got == [BENCH], f"a module the bench imports at the base, removed by the PR, still runs the bench ({got})")
    p = subprocess.run([sys.executable, "dev/testa_tudo.py", "--long", "bench", "--base", "HEAD"], cwd=ROOT,
                       env=dict(os.environ, PYTHONUTF8="1"), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    out = p.stdout + p.stderr
    check(p.returncode == 0 and "0 of 0 passed" in out and "testa_passagem" not in out,
          f"--long bench --base with nothing changed runs no long test (exit {p.returncode})")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
