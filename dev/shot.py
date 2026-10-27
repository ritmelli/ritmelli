"""Print de uma pagina pelo Chrome headless (CDP), com passos de JS antes do print e
os erros do console no fim. Pra quem desenha tema conferir o proprio trabalho.

    python dev/shot.py http://127.0.0.1:8811/t/meu-tema/ out.png
        [--size 1440x900] [--wait 2.5] [--js "document.querySelector('#x').click()"]...
        [--full] [--tab N] [--reduced-motion] [--offline-ok]

Cada --js roda em ordem, com --wait segundos depois de cada um, todos no mesmo escopo
global da pagina (const repetido entre passos da erro: use uma IIFE). Sai 1 se a pagina
lancou excecao ou logou console.error.
"""
import argparse
import asyncio
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


async def run(a):
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

            async def reader():
                async for raw in ws:
                    m = json.loads(raw)
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
            await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h,
                      deviceScaleFactor=1, mobile=w < 600)
            # sem isso a aba headless nunca tem foco e :focus-visible nao aparece no print
            await cmd("Emulation.setFocusEmulationEnabled", enabled=True)
            if a.reduced_motion:
                await cmd("Emulation.setEmulatedMedia",
                          features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
            await cmd("Page.navigate", url=a.url)
            await asyncio.sleep(a.wait)
            for js in a.js:
                r = await cmd("Runtime.evaluate", expression=js, awaitPromise=True,
                              returnByValue=True)
                if r.get("exceptionDetails"):
                    errors.append(f"--js falhou: {js[:80]} -> "
                                  f"{r['exceptionDetails'].get('exception', {}).get('description', '')}")
                elif r.get("result", {}).get("value") is not None:
                    print(f"js> {json.dumps(r['result']['value'], ensure_ascii=False)[:4000]}")
                await asyncio.sleep(a.wait)
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
        chrome.kill()
        chrome.wait()
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
    ap.add_argument("--wait", type=float, default=2.5)
    ap.add_argument("--js", action="append", default=[])
    ap.add_argument("--full", action="store_true", help="pagina inteira (ate 6000 px)")
    ap.add_argument("--reduced-motion", action="store_true")
    ap.add_argument("--tab", type=int, default=0, help="aperta Tab N vezes antes do print (anel de foco)")
    ap.add_argument("--offline-ok", action="store_true",
                    help="nao conta como erro a reconexao do /api/events com o servidor fora")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
