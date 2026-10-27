"""Gera themes/<slug>/preview.png de todos os temas (ou dos passados) para a galeria,
com um servidor --mock proprio tocando o primeiro item da biblioteca.

    python dev/previews.py [slug ...] [--port 8798]
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def post(base, path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--port", type=int, default=8798)
    a = ap.parse_args()
    slugs = a.slugs or sorted(p.name for p in (HERE / "themes").iterdir()
                              if (p / "index.html").exists())
    base = f"http://127.0.0.1:{a.port}"
    srv = subprocess.Popen([sys.executable, str(HERE / "server.py"), "--mock", "--no-browser",
                            "--port", str(a.port), "--data-dir", tempfile.mkdtemp(prefix="sbprev_")])
    try:
        for _ in range(60):
            try:
                lib = json.load(urllib.request.urlopen(base + "/api/library", timeout=1))
                break
            except Exception:  # noqa: BLE001 - subindo
                time.sleep(0.25)
        else:
            sys.exit("servidor --mock nao subiu")
        if lib:
            post(base, "/api/play", {"id": lib[min(2, len(lib) - 1)]["id"], "start": 95})
        rc = 0
        for s in slugs:
            out = HERE / "themes" / s / "preview.png"
            r = subprocess.run([sys.executable, str(HERE / "dev" / "shot.py"), f"{base}/t/{s}/",
                                str(out), "--wait", "3"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            print(f"[{s}] {r.stdout.strip()}")
            rc |= r.returncode
        return rc
    finally:
        srv.kill()


if __name__ == "__main__":
    sys.exit(main())
