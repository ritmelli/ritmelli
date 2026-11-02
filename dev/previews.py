"""Gera themes/<slug>/preview.png de todos os temas (ou dos passados) para a galeria, com o servidor --mock,
a prateleira de mentira e o disco pausado do dev/compara.py: o print nao leva a biblioteca de ninguem. O preview
entra no git, porque o instalador leva a pasta do tema como ela esta.

    python dev/previews.py [slug ...] [--port 8798]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compara  # noqa: E402

HERE = compara.RAIZ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--port", type=int, default=8798)
    a = ap.parse_args()
    slugs = a.slugs or sorted(p.name for p in (HERE / "themes").iterdir()
                              if (p / "index.html").exists())
    tmp = Path(tempfile.mkdtemp(prefix="sbprev_"))
    with open(tmp / "srv.log", "wb") as log:
        srv = compara.sobe_servidor(tmp, a.port, log)
        try:
            compara.monta_tocando(a.port)
            rc = 0
            for s in slugs:
                out = HERE / "themes" / s / "preview.png"
                r = subprocess.run([sys.executable, str(HERE / "dev" / "shot.py"), f"http://127.0.0.1:{a.port}/t/{s}/",
                                    str(out), "--wait", "3"], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")
                print(f"[{s}] {r.stdout.strip()}")
                rc |= r.returncode
            return rc
        finally:
            compara.para_servidor(srv, a.port)


if __name__ == "__main__":
    sys.exit(main())
