"""Print de uma pagina pelo Chrome headless (CDP), com passos de JS antes do print e
os erros do console no fim. Pra quem desenha tema conferir o proprio trabalho.

    python dev/shot.py http://127.0.0.1:8811/t/meu-tema/ out.png
        [--size 1440x900] [--dpr 2] [--wait 2.5] [--js "document.querySelector('#x').click()"]...
        [--full] [--tab N] [--reduced-motion] [--offline-ok] [--boas-vindas]

Cada --js roda em ordem, com --wait segundos depois de cada um, todos no mesmo escopo
global da pagina (const repetido entre passos da erro: use uma IIFE). Sai 1 se a pagina
lancou excecao ou logou console.error.

So fala com um servidor --mock (dev/so_mock.py): antes de abrir a pagina, recusa a porta 8799 e a origem cujo
/api/state nao traz o "mock": true (sem seguir redirecionamento); no Chrome, barra o documento de outra origem; antes de
cada --js, do Tab e do print, confere de novo a origem da pagina e o marcador. Recusado, sai 1 sem print.

A tela de boas-vindas (a da primeira vez, com a prateleira vazia) cobre a pagina: antes do print ela e fechada pelo
servidor, como o botao do fim dela (#126). Com o --boas-vindas ela fica, e o print e dela.
"""
import argparse
import asyncio
import base64
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
from fitcheck import (SEM_BOAS_VINDAS, barra_outra_origem, confere_pagina, espera_boas_vindas,  # noqa: E402
                      fecha_boas_vindas, fecha_chrome)
from so_mock import free_port  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


async def run(a):
    try:
        base = so_mock.confere(a.url)  # antes de tudo: o POST das boas-vindas e a pagina so num --mock
    except so_mock.Recusa as ex:
        print(f"recusado: {ex}")
        return 1
    if not a.boas_vindas and fecha_boas_vindas(a.url):
        print("(a tela de boas-vindas estava pendente: fechada pelo servidor, como o botao do fim dela)")
    port = free_port()
    prof = tempfile.mkdtemp(prefix="sbshot_")
    w, h = map(int, a.size.lower().split("x"))
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}",
                               f"--user-data-dir={prof}", "--no-first-run",
                               "--no-default-browser-check", "--hide-scrollbars",
                               "--autoplay-policy=no-user-gesture-required",
                               f"--window-size={w},{h}", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors = []
    try:
        ws_url = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                break
            except Exception:  # noqa: BLE001 - o Chrome ainda esta subindo
                time.sleep(0.1)
        if not ws_url:
            sys.exit("chrome headless nao subiu")
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            seq = [0]
            pending = {}
            barrados = []
            fetch = barra_outra_origem(ws, base, barrados)

            async def reader():
                async for raw in ws:
                    m = json.loads(raw)
                    if fetch(m):
                        continue
                    if "id" in m and m["id"] in pending:
                        pending.pop(m["id"]).set_result(m)
                    elif m.get("method") == "Runtime.exceptionThrown":
                        d = m["params"]["exceptionDetails"]
                        errors.append("excecao: " + (d.get("exception", {}).get("description")
                                                     or d.get("text", "")))
                    elif m.get("method") == "Runtime.consoleAPICalled":
                        p = m["params"]
                        if p["type"] in ("error", "warning"):
                            txt = " ".join(str(x.get("value", x.get("description", "")))
                                           for x in p["args"])
                            errors.append(f"console.{p['type']}: {txt}")
                    elif m.get("method") == "Log.entryAdded":
                        e = m["params"]["entry"]
                        url = e.get("url", "")
                        # favicon e a reconexao do SSE com o servidor fora sao esperados
                        if (e["level"] == "error" and "favicon" not in url
                                and not ("/api/events" in url and a.offline_ok)):
                            errors.append(f"log: {e.get('text')} {e.get('url', '')}")

            rt = asyncio.create_task(reader())

            async def cmd(method, **params):
                seq[0] += 1
                fut = asyncio.get_running_loop().create_future()
                pending[seq[0]] = fut
                await ws.send(json.dumps({"id": seq[0], "method": method, "params": params}))
                r = await asyncio.wait_for(fut, 30)
                if "error" in r:
                    raise RuntimeError(f"{method}: {r['error']}")
                return r.get("result", {})

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Log.enable")
            await cmd("Fetch.enable", patterns=so_mock.DOCUMENTOS)

            async def pode_agir():
                try:
                    await confere_pagina(cmd, a.url, barrados)
                    return True
                except so_mock.Recusa as ex:
                    print(f"recusado: {ex}; nada mais feito, sem print")
                    return False

            await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h,
                      deviceScaleFactor=a.dpr, mobile=w < 600)
            # sem isso a aba headless nunca tem foco e :focus-visible nao aparece no print
            await cmd("Emulation.setFocusEmulationEnabled", enabled=True)
            if a.reduced_motion:
                await cmd("Emulation.setEmulatedMedia",
                          features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
            await cmd("Page.navigate", url=a.url)
            await asyncio.sleep(a.wait)
            if not await pode_agir():
                return 1
            if a.boas_vindas and not await espera_boas_vindas(cmd):
                errors.append(f"a tela de boas-vindas nao abriu: {SEM_BOAS_VINDAS}")
            for js in a.js:
                if not await pode_agir():
                    return 1
                r = await cmd("Runtime.evaluate", expression=js, awaitPromise=True,
                              returnByValue=True)
                if r.get("exceptionDetails"):
                    errors.append(f"--js falhou: {js[:80]} -> "
                                  f"{r['exceptionDetails'].get('exception', {}).get('description', '')}")
                elif r.get("result", {}).get("value") is not None:
                    print(f"js> {json.dumps(r['result']['value'], ensure_ascii=False)[:4000]}")
                await asyncio.sleep(a.wait)
            if not await pode_agir():  # o ultimo --js pode ter levado a pagina embora: sem print
                return 1
            for _ in range(a.tab):
                for typ in ("rawKeyDown", "keyUp"):
                    await cmd("Input.dispatchKeyEvent", type=typ, key="Tab", code="Tab",
                              windowsVirtualKeyCode=9)
                await asyncio.sleep(0.05)
            if a.tab:
                await asyncio.sleep(0.4)
            shot = {"format": "png"}
            if a.full:
                m = await cmd("Page.getLayoutMetrics")
                cs = m["cssContentSize"]
                shot.update(captureBeyondViewport=True,
                            clip={"x": 0, "y": 0, "width": cs["width"],
                                  "height": min(cs["height"], 6000), "scale": 1})
            r = await cmd("Page.captureScreenshot", **shot)
            with open(a.out, "wb") as f:
                f.write(base64.b64decode(r["data"]))
            rt.cancel()
    finally:
        fecha_chrome(chrome, prof)
    print(f"print: {os.path.abspath(a.out)} ({a.size})")
    for e in errors:
        print(e)
    return 1 if errors else 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--dpr", type=float, default=1, help="pixels de tela por px CSS (o notebook: 2)")
    ap.add_argument("--wait", type=float, default=2.5)
    ap.add_argument("--js", action="append", default=[])
    ap.add_argument("--full", action="store_true", help="pagina inteira (ate 6000 px)")
    ap.add_argument("--reduced-motion", action="store_true")
    ap.add_argument("--tab", type=int, default=0, help="aperta Tab N vezes antes do print (anel de foco)")
    ap.add_argument("--offline-ok", action="store_true",
                    help="nao conta como erro a reconexao do /api/events com o servidor fora")
    ap.add_argument("--boas-vindas", action="store_true",
                    help="deixa a tela de boas-vindas aberta e fotografa ela (com a prateleira vazia)")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
