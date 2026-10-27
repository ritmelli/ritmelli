"""Texturas de ruido da vitrola (madeira, feltro do prato e do painel, pintura martelada dos pedais) em WebP.

    python dev/texturas.py [nome...]     (sem nome grava todas)

O desenho mora aqui, em SVG com feTurbulence; o tema usa so as imagens que este script grava em
themes/vitrola/texturas/ (image-set com a densidade, para o tamanho na tela ser o do SVG). Com o SVG
direto no CSS a GPU do celular refazia o ruido a cada pedaco de tela que entrava na rolagem do
toca-discos: no celular de teste, 10 a 16 quadros travados por rolagem com as texturas e 3 a 5 sem
(medido por adb, 18/10). Mudou o grao: muda o SVG aqui, roda de novo e confere o tema.
"""
import asyncio
import base64
import io
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fitcheck import CHROME, free_port  # noqa: E402

SAIDA = Path(__file__).resolve().parent.parent / "themes" / "vitrola" / "texturas"
# nome: (SVG em data URI, largura e altura em px de CSS, densidade da imagem gravada)
TEXTURAS = {
    "veio": ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='900' height='420'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.0025 0.07' numOctaves='3' seed='11'/%3E%3CfeColorMatrix values='0 0 0 0 0.09 0 0 0 0 0.04 0 0 0 0 0.02 0 0 0 1.25 -0.5'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23g)'/%3E%3C/svg%3E",
        900, 420, 2),
    "veio-v": ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='420' height='900'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.06 0.002' numOctaves='3' seed='5'/%3E%3CfeColorMatrix values='0 0 0 0 0.05 0 0 0 0 0.02 0 0 0 0 0.01 0 0 0 1 -0.42'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23g)'/%3E%3C/svg%3E",
        420, 900, 2),
    "pelo": ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='f'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' seed='3'/%3E%3CfeColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.6 -0.2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23f)'/%3E%3C/svg%3E",
        160, 160, 3),
    "martelado": ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='48' height='48'%3E%3Cfilter id='m' x='0' y='0' width='100%25' height='100%25'%3E%3CfeTurbulence type='turbulence' baseFrequency='.23' numOctaves='2' seed='11' stitchTiles='stitch'/%3E%3CfeColorMatrix values='1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0'/%3E%3CfeComponentTransfer%3E%3CfeFuncR type='table' tableValues='0 .15 .85 1'/%3E%3CfeFuncG type='table' tableValues='0 .14 .84 .98'/%3E%3CfeFuncB type='table' tableValues='0 .12 .80 .94'/%3E%3CfeFuncA type='table' tableValues='.22 .02 .02 .18'/%3E%3C/feComponentTransfer%3E%3C/filter%3E%3Crect width='48' height='48' filter='url(%23m)'/%3E%3C/svg%3E",
        48, 48, 3),
    # feltro do painel dos pedais no celular: penugem fina de pouco contraste e as manchas largas do
    # feltro prensado, em camadas separadas (a mancha e lisa, uma densidade basta)
    "feltro-penugem": ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='f' x='0' y='0' width='100%25' height='100%25'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.62' numOctaves='3' seed='7' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 1 0 0 0 0 .93 0 0 0 0 .84 0 0 0 .42 -.15'/%3E%3C/filter%3E%3Crect width='180' height='180' filter='url(%23f)'/%3E%3C/svg%3E",
        180, 180, 3),
    "feltro-mancha": ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='520' height='520'%3E%3Cfilter id='f' x='0' y='0' width='100%25' height='100%25'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.011' numOctaves='3' seed='4' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 .7 -.29'/%3E%3C/filter%3E%3Crect width='520' height='520' filter='url(%23f)'/%3E%3C/svg%3E",
        520, 520, 1),
}


async def main():
    SAIDA.mkdir(exist_ok=True)
    port = free_port()
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={tempfile.mkdtemp()}",
                               "--no-first-run", "--force-color-profile=srgb", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                ws_url = next(t["webSocketDebuggerUrl"] for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")) if t["type"] == "page")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        async with websockets.connect(ws_url, max_size=1 << 30) as ws:
            n = [0]

            async def cmd(m, **p):
                n[0] += 1
                i = n[0]
                await ws.send(json.dumps({"id": i, "method": m, "params": p}))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == i:
                        return r.get("result", {})
            await cmd("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
            for nome in sys.argv[1:] or TEXTURAS:
                uri, w, h, d = TEXTURAS[nome]
                await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=d, mobile=False)
                html = f"<!doctype html><style>html,body{{margin:0;background:transparent}}div{{width:{w}px;height:{h}px;background:url(\"{uri}\")}}</style><div></div>"
                await cmd("Page.navigate", url="data:text/html;base64," + base64.b64encode(html.encode()).decode())
                await asyncio.sleep(1.2)
                r = await cmd("Page.captureScreenshot", format="png", clip={"x": 0, "y": 0, "width": w, "height": h, "scale": 1})
                im = Image.open(io.BytesIO(base64.b64decode(r["data"]))).convert("RGBA")
                assert im.size == (w * d, h * d), (nome, im.size)
                destino = SAIDA / f"{nome}.webp"
                im.save(destino, "WEBP", quality=92, alpha_quality=100, method=6)
                print(f"{destino.name}: {im.size[0]}x{im.size[1]}, {destino.stat().st_size // 1024} KB")
    finally:
        chrome.kill()


if __name__ == "__main__":
    asyncio.run(main())
