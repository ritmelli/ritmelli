"""Custo de um tema com musica tocando, como num celular (390x844, 3x, CPU 4x mais lenta).

    python dev/perfcheck.py http://127.0.0.1:8806/t/vitrola/ --play <id da biblioteca>
    python dev/perfcheck.py http://127.0.0.1:8806/t/vitrola/ --play <id> --size 1366x768@1 --cpu 1

Grava 3 s de trace do Chrome com a faixa tocando e conta por segundo: quadros do thread
principal, pinturas e rasterizacoes (o que trava a rolagem no celular), e de onde vem a
invalidacao (o elemento que muda a cada quadro). Contar quadros por requestAnimationFrame
nao serve: no headless a rolagem e do compositor e sai lisa mesmo com a pagina sendo
redesenhada a cada quadro.

Referencia (18/10, mock, Vanessa da Mata): parada, a vitrola fica em ~30 pinturas e ~15
rasterizacoes por segundo; antes da correcao, tocando, ia a 66 e 208 (agulha do VU dentro
do svg e quadrado do disco girando sem recorte). Use num servidor --mock, nunca no 8799.
"""
import argparse
import asyncio
import collections
import json
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

from fitcheck import CHROME, free_port

CATS = ("devtools.timeline,disabled-by-default-devtools.timeline,"
        "disabled-by-default-devtools.timeline.invalidationTracking,cc,benchmark")
INVAL = ("StyleRecalcInvalidationTracking", "LayoutInvalidationTracking",
         "StyleInvalidatorInvalidationTracking")


async def run(a):
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
            seq, pend, evs, fim = [0], {}, [], asyncio.Event()

            async def leitor():
                async for raw in ws:
                    m = json.loads(raw)
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
                await cmd("Runtime.evaluate", awaitPromise=True, expression=(
                    f"fetch('/api/{rota}', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, "
                    f"body: {json.dumps(json.dumps(corpo))}}}).then(r => r.status)"))

            await cmd("Page.enable")
            tam, dpr = a.size.split("@")
            w, h = map(int, tam.split("x"))
            await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h,
                      deviceScaleFactor=float(dpr), mobile=w < 900)
            if w < 900:
                await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            await cmd("Emulation.setCPUThrottlingRate", rate=a.cpu)
            await cmd("Page.navigate", url=a.url)
            await asyncio.sleep(2.5)
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
