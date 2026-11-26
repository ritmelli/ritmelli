"""Gera o preview de todos os temas (ou dos passados) para a galeria, com o servidor --mock, a prateleira de
mentira e o disco pausado do dev/compara.py: o print nao leva a biblioteca de ninguem. O preview entra no git,
porque o instalador leva a pasta do tema como ela esta. O tema com textos (a pasta i18n/) ganha um por lingua,
themes/<slug>/preview_<lingua>.png, cada um pelo ?lang= dele, e a galeria mostra o da lingua dela; o tema sem textos,
um preview.png so.

    python dev/previews.py [slug ...] [--port N]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compara

HERE = compara.RAIZ
sys.path.insert(0, str(HERE))
import i18n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--port", type=int, help="porta do servidor de teste; sem ela, uma livre")
    a = ap.parse_args()
    porta = a.port or compara.free_port()  # o --port 8799 sai no sobe_servidor, antes de qualquer pedido
    slugs = a.slugs or sorted(p.name for p in (HERE / "themes").iterdir()
                              if (p / "index.html").exists())
    tmp = Path(tempfile.mkdtemp(prefix="sbprev_"))
    with open(tmp / "srv.log", "wb") as log:
        srv = compara.sobe_servidor(tmp, porta, log)
        try:
            compara.monta_tocando(srv)
            rc = 0
            for s in slugs:
                pasta = HERE / "themes" / s
                linguas = i18n.LINGUAS if (pasta / "i18n").is_dir() else (None,)
                for lingua in linguas:
                    out = pasta / (f"preview_{lingua}.png" if lingua else "preview.png")
                    url = f"http://127.0.0.1:{porta}/t/{s}/" + (f"?lang={lingua}" if lingua else "")
                    # 5 s: com 3, o segundo print as vezes saia antes da conexao (prateleira vazia) ou sem a onda do visor
                    r = subprocess.run([sys.executable, str(HERE / "dev" / "shot.py"), url, str(out), "--wait", "5"],
                                       capture_output=True, text=True, encoding="utf-8", errors="replace")
                    print(f"[{s}{' ' + lingua if lingua else ''}] {r.stdout.strip()}")
                    rc |= r.returncode
            return rc
        finally:
            compara.para_servidor(srv)


if __name__ == "__main__":
    sys.exit(main())
