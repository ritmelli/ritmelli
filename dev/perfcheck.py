"""Custo de um tema com musica tocando, como num celular (390x844, 3x, CPU 4x mais lenta).

    python dev/perfcheck.py http://127.0.0.1:8806/t/ritmelli/ --play <id da biblioteca>
    python dev/perfcheck.py http://127.0.0.1:8806/t/ritmelli/ --play <id> --size 1366x768@1 --cpu 1

Grava 3 s de trace do Chrome com a faixa tocando e conta por segundo: quadros do thread
principal, pinturas e rasterizacoes (o que trava a rolagem no celular), e de onde vem a
invalidacao (o elemento que muda a cada quadro). Contar quadros por requestAnimationFrame
nao serve: no headless a rolagem e do compositor e sai lisa mesmo com a pagina sendo
redesenhada a cada quadro.

Referencia (18/10, mock, Vanessa da Mata): parado, o tema fica em ~30 pinturas e ~15
rasterizacoes por segundo; antes da correcao, tocando, ia a 66 e 208 (agulha do VU dentro
do svg e quadrado do disco girando sem recorte). So fala com um servidor --mock (dev/so_mock.py): antes de abrir a
pagina, recusa a porta 8799 e a origem cujo /api/state nao traz o "mock": true (sem seguir redirecionamento); no Chrome,
barra o documento de outra origem; antes do play e do stop, confere de novo a origem da pagina e o marcador.
"""
import argparse
import asyncio
import collections
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import so_mock  # noqa: E402
from fitcheck import CHROME, barra_outra_origem, confere_pagina  # noqa: E402
from so_mock import free_port  # noqa: E402

CATS = ("devtools.timeline,disabled-by-default-devtools.timeline,"
        "disabled-by-default-devtools.timeline.invalidationTracking,cc,benchmark")
INVAL = ("StyleRecalcInvalidationTracking", "LayoutInvalidationTracking",
         "StyleInvalidatorInvalidationTracking")


async def run(a):
    try:
        base = so_mock.confere(a.url)  # antes de abrir a pagina: abrir o tema ja liga o SSE
    except so_mock.Recusa as ex:
        print(f"recusado: {ex}")
        return 1
    port = free_port()
    prof = tempfile.mkdtemp(prefix="sbperf_")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}",
                               f"--user-data-dir={prof}", "--no-first-run",
                               "--no-default-browser-check", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                break
            except Exception:  # noqa: BLE001 - subindo
                time.sleep(0.1)
        async with websockets.connect(ws_url, max_size=512 * 1024 * 1024) as ws:
            seq, pend, evs, fim, barrados = [0], {}, [], asyncio.Event(), []
            fetch = barra_outra_origem(ws, base, barrados)

            async def leitor():
                async for raw in ws:
                    m = json.loads(raw)
                    if fetch(m):
                        continue
                    if m.get("id") in pend:
                        pend.pop(m["id"]).set_result(m.get("result", {}))
                    elif m.get("method") == "Tracing.dataCollected":
                        evs.extend(m["params"]["value"])
                    elif m.get("method") == "Tracing.tracingComplete":
                        fim.set()

            tarefa = asyncio.create_task(leitor())

            async def cmd(method, **params):
                seq[0] += 1
                f = asyncio.get_running_loop().create_future()
                pend[seq[0]] = f
                await ws.send(json.dumps({"id": seq[0], "method": method, "params": params}))
                return await asyncio.wait_for(f, 60)

            async def post(rota, corpo):
                await confere_pagina(cmd, a.url, barrados)  # o POST so pela pagina que segue no --mock
                r = await cmd("Runtime.evaluate", awaitPromise=True, returnByValue=True, expression=(
                    f"fetch('/api/{rota}', {{method: 'POST', redirect: 'error', headers: {{'Content-Type': "
                    f"'application/json'}}, body: {json.dumps(json.dumps(corpo))}}})"
                    ".then(r => r.status, e => String(e))"))  # o redirecionamento vira erro, e nao e seguido
                status = r.get("result", {}).get("value")
                if not (isinstance(status, int) and 200 <= status < 300):
                    raise SystemExit(f"o POST /api/{rota} falhou ({status}); nada medido")

            await cmd("Page.enable")
            await cmd("Fetch.enable", patterns=so_mock.DOCUMENTOS)
            tam, dpr = a.size.split("@")
            w, h = map(int, tam.split("x"))
            await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h,
                      deviceScaleFactor=float(dpr), mobile=w < 900)
            if w < 900:
                await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            await cmd("Emulation.setCPUThrottlingRate", rate=a.cpu)
            await cmd("Page.navigate", url=a.url)
            await asyncio.sleep(2.5)
            await confere_pagina(cmd, a.url, barrados)  # a medida e da pagina do --mock pedido
            if a.play:
                await post("play", {"id": a.play, "por_cima": False})
            await asyncio.sleep(2)
            await cmd("Tracing.start", categories=CATS, transferMode="ReportEvents")
            await asyncio.sleep(a.seg)
            await cmd("Tracing.end")
            await fim.wait()
            if a.play:
                await post("stop", {})
            tarefa.cancel()
    except so_mock.Recusa as ex:
        print(f"recusado: {ex}; nada medido")
        return 1
    finally:
        chrome.kill()
        chrome.wait()

    n, inval = collections.Counter(), collections.Counter()
    for e in evs:
        if e.get("ph") == "X" and e["name"] in ("ProxyMain::BeginMainFrame", "Paint", "RasterTask"):
            n[e["name"]] += 1
        elif e.get("name") in INVAL:
            d = e.get("args", {}).get("data", {})
            inval[f"{d.get('nodeName', '?')[:70]} ({d.get('reason', '')})"] += 1
    s = a.seg
    print(f"por segundo: {n['ProxyMain::BeginMainFrame'] / s:.0f} quadros do thread principal, "
          f"{n['Paint'] / s:.0f} pinturas, {n['RasterTask'] / s:.0f} rasterizacoes")
    for k, v in inval.most_common(a.top):
        print(f"  {v / s:5.0f}/s  {k}")
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--play", help="id da biblioteca para tocar antes de medir")
    ap.add_argument("--size", default="390x844@3", help="largura x altura @ densidade (de 900 de largura para cima, a tela do computador)")
    ap.add_argument("--cpu", type=float, default=4, help="quantas vezes mais lenta que o PC")
    ap.add_argument("--seg", type=float, default=3)
    ap.add_argument("--top", type=int, default=6, help="quantas fontes de invalidacao mostrar")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
