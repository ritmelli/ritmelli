"""Mede a vitrola no Chrome do celular de verdade (USB, depuracao ligada), so rolando e puxando:
nunca toca em botao (o som do 8799 sai no jogo).

    python dev/celular.py rolagem [--recarregar] [--css "<regra injetada>"] [--trace saida.json]
    python dev/celular.py puxao [--css ...]       # puxa o palco aberto 150 px para baixo e volta
    python dev/celular.py abrir                   # abre e fecha o palco pela funcao do app
    python dev/celular.py custo                   # ms de estilo das classes que o palco troca
    python dev/celular.py dedo [--segundos 15] [--esperar]   # so grava, enquanto o usuario rola com o dedo

Antes: adb no PATH (ou ADB=<caminho do adb.exe>) e o celular autorizado em `adb devices`; o
script faz o forward da porta 9222 e so mexe na aba :8799/t/vitrola (as outras abas sao do usuario).
O celular de teste e um Galaxy S20 FE: tela de 120 Hz (um quadro a cada 8,3 ms), densidade 3. O
emulado do Chrome no PC nao reproduz o que trava la (no 18/10, as agulhas e as texturas so
travavam no aparelho). Leitura do resultado da rolagem:
- janky / vsyncs_perdidos / lacunas: medida do proprio Chrome (ScrollJankV4) do que o dedo sente;
  lacuna de N = um quadro que ficou N vsyncs sem chegar;
- alvo_no_main: inicios de rolagem em que o Chrome perguntou ao processador principal o que rolar;
- memoria_estourada: blocos que nao couberam na memoria da GPU (refeitos ao voltar);
- falhas_gpu: animacoes que o Chrome nao levou para a GPU (1024 = transform em elemento SVG);
- fps_rolagens: quadros que chegaram a tela (viz) em cada rolagem, do inicio do gesto ao fim do
  fling, e os intervalos em vsyncs (1 = na hora; a tela so fica em 120 Hz enquanto algo se mexe).
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from collections import Counter

import websockets

BASE = "http://127.0.0.1:9222"
CATS = ["devtools.timeline", "disabled-by-default-devtools.timeline", "disabled-by-default-devtools.timeline.frame",
        "cc", "viz", "gpu", "benchmark", "input", "blink", "blink.animations", "toplevel"]


def adb_forward(esperar=False):
    adb = os.environ.get("ADB") or shutil.which("adb")
    if not adb:
        sys.exit("adb nao achado: ponha no PATH ou em ADB=<caminho do adb.exe>")
    for _ in range(300 if esperar else 1):   # --esperar: ate 10 min pelo cabo
        lista = subprocess.run([adb, "devices"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        if any(l.endswith("\tdevice") for l in lista.splitlines()):
            break
        if esperar:
            time.sleep(2)
    else:
        sys.exit(f"nenhum celular autorizado no adb:\n{lista}")
    subprocess.run([adb, "forward", "tcp:9222", "localabstract:chrome_devtools_remote"], check=True,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")


class Aba:
    def __init__(self, ws):
        self.ws, self.n, self.pend, self.on = ws, 0, {}, {}

    async def laco(self):
        async for raw in self.ws:
            r = json.loads(raw)
            if "id" in r and r["id"] in self.pend:
                self.pend.pop(r["id"]).set_result(r)
            elif r.get("method") in self.on:
                self.on[r["method"]](r["params"])

    async def cmd(self, m, **p):
        self.n += 1
        f = asyncio.get_event_loop().create_future()
        self.pend[self.n] = f
        await self.ws.send(json.dumps({"id": self.n, "method": m, "params": p}))
        r = await f
        if "error" in r:
            raise RuntimeError(f"{m}: {r['error']}")
        return r.get("result", {})

    async def js(self, x):
        r = await self.cmd("Runtime.evaluate", expression=x, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description"))
        return r.get("result", {}).get("value")

    async def css(self, regra):
        await self.js(f"(() => {{ document.getElementById('__medida')?.remove(); if (!{json.dumps(regra)}) return;"
                      f" const s = document.createElement('style'); s.id = '__medida'; s.textContent = {json.dumps(regra)}; document.head.append(s); }})()")

    async def gravar(self, corpo):
        """roda corpo() com o trace ligado e devolve os eventos"""
        ev, fim = [], asyncio.Event()
        self.on["Tracing.dataCollected"] = lambda p: ev.extend(p["value"])
        self.on["Tracing.tracingComplete"] = lambda p: fim.set()
        await self.cmd("Tracing.start", traceConfig={"includedCategories": CATS, "recordMode": "recordAsMuchAsPossible"}, transferMode="ReportEvents")
        await asyncio.sleep(0.3)
        await corpo()
        await self.cmd("Tracing.end")
        await asyncio.wait_for(fim.wait(), 120)
        return ev


async def conectar():
    abas = [t for t in json.load(urllib.request.urlopen(BASE + "/json")) if t["type"] == "page" and ":8799/t/vitrola" in t["url"]]
    if len(abas) != 1:
        sys.exit(f"esperava uma aba da vitrola no celular, achei {len(abas)}")
    a = Aba(await websockets.connect(abas[0]["webSocketDebuggerUrl"], max_size=1 << 30))
    asyncio.create_task(a.laco())
    await a.cmd("Runtime.enable")
    await a.cmd("Page.enable")
    return a


def resumo(ev):
    j = [e["args"]["scroll_jank_v4"] for e in ev if e["name"] == "ScrollJankV4" and e.get("ph") == "b"]
    bmf = [e["dur"] / 1000 for e in ev if e["name"] == "ProxyMain::BeginMainFrame" and e.get("ph") == "X"]
    rs = [e["dur"] / 1000 for e in ev if e["name"] == "Document::recalcStyle" and e.get("ph") == "X"]
    ras = [e["dur"] / 1000 for e in ev if e["name"] == "RendererRasterWorker" and e.get("ph") == "X"]
    falhas, alvos = Counter(), {}
    for e in ev:
        if e["name"] == "Animation":
            d = (e.get("args") or {}).get("data") or {}
            i = (e.get("id2") or {}).get("local")
            if e["ph"] == "b":
                alvos[i] = (d.get("nodeName") or "")[:30]
            elif e["ph"] == "n" and d.get("compositeFailed"):
                falhas[f"{alvos.get(i)}:{d['compositeFailed']}"] += 1
    c = Counter(e["name"] for e in ev)
    out = {"Draw": c["DrawFrame"], "Dropped": c["DroppedFrame"],
           "processador_principal_ms": [len(bmf), round(sum(bmf)), round(max(bmf or [0]), 1)],
           "estilo_max_ms": round(max(rs or [0]), 1), "raster_gpu_ms": [len(ras), round(sum(ras)), round(max(ras or [0]), 1)],
           "memoria_estourada": c["TileManager::AssignGpuMemory tile violates memory policy"],
           "alvo_no_main": c["WidgetInputHandlerManager::FindScrollTargetOnMainThread"], "falhas_gpu": dict(falhas)}
    if j:
        out = {"quadros_rolagem": len(j), "janky": sum(x.get("is_janky", False) for x in j),
               "vsyncs_perdidos": sum(r["missed_vsyncs"] for x in j for r in x.get("missed_vsyncs_per_jank_reason", [])),
               "lacunas": dict(sorted(Counter(x.get("vsyncs_since_previous_frame", 1) for x in j).items())), **out}
        out["fps_rolagens"] = fps_rolagens(ev)
    return out


def fps_rolagens(ev):
    """quadros apresentados (viz) por rolagem, do comeco do gesto ao ultimo passo do fling"""
    sw = sorted(e["ts"] for e in ev if e["name"] == "Display::DrawAndSwap" and e.get("ph") == "X")
    ini = sorted(e["ts"] for e in ev if e["name"] == "InputHandlerProxy::HandleGestureScrollBegin")
    passos = sorted(e["ts"] for e in ev if e["name"] in ("InputHandler::ScrollUpdate", "ScrollTree::ScrollBy"))
    out = []
    for i, t0 in enumerate(ini):
        t1 = ini[i + 1] if i + 1 < len(ini) else float("inf")
        us = [u for u in passos if t0 <= u < t1]
        fr = [t for t in sw if us and t0 <= t <= max(us) + 20000]
        if len(fr) < 10:   # gesto que nao rolou (ja no fim) nao conta
            continue
        d = [(b - a) / 1000 for a, b in zip(fr, fr[1:])]
        out.append({"ms": round((fr[-1] - fr[0]) / 1000), "fps": round(1000 * len(d) / sum(d), 1),
                    "intervalos": dict(sorted(Counter(max(1, round(x / 8.333)) for x in d).items()))})
    return out


async def palco_aberto(a):
    if not await a.js("S.palco"):
        await a.js("abrirPalcoComHistoria()")
        await asyncio.sleep(1.5)
    await a.js("document.querySelector('#palco').scrollTop = 0")
    await asyncio.sleep(1.0)


async def rolagem(a, args):
    if args.recarregar:
        await a.cmd("Page.reload", ignoreCache=True)
        await asyncio.sleep(5)
    await a.css(args.css)
    await palco_aberto(a)

    async def gesto():
        for dy in (-520, -520, -520, 520, 520, 520):   # tres puxoes ate os pedais e tres de volta, com fling
            await a.cmd("Input.synthesizeScrollGesture", x=180, y=420, yDistance=dy, speed=1800, gestureSourceType="touch", preventFling=False)
            await asyncio.sleep(1.2)
    return await a.gravar(gesto)


async def puxao(a, args):
    await a.css(args.css)
    await palco_aberto(a)

    async def gesto():
        await a.cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": 180, "y": 300}])
        for y in list(range(300, 452, 8)) + list(range(452, 299, -8)):   # desce 150 px e volta: nao fecha
            t = time.perf_counter()
            await a.cmd("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": 180, "y": y}])
            await asyncio.sleep(max(0, 0.016 - (time.perf_counter() - t)))
        await a.cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        await asyncio.sleep(0.8)
    return await a.gravar(gesto)


async def abrir(a, args):
    if await a.js("S.palco"):
        await a.js("fecharPalco()")
        await asyncio.sleep(1.5)
    saidas = {}
    for acao in ("abrirPalcoComHistoria()", "fecharPalco()"):
        async def gesto(acao=acao):
            await a.js(acao)
            await asyncio.sleep(1.0)
        ev = await a.gravar(gesto)
        bmf = sorted((e["dur"] / 1000 for e in ev if e["name"] == "ProxyMain::BeginMainFrame" and e.get("ph") == "X"), reverse=True)
        saidas[acao] = {**resumo(ev), "maiores_quadros_ms": [round(x, 1) for x in bmf[:3]]}
        await asyncio.sleep(0.8)
    return saidas


async def dedo(a, args):
    """espera o usuario abrir o palco e comecar a rolar (ate 5 min) e grava --segundos sem injetar nada:
    a rolagem e a do dedo do usuario"""
    topo = None
    for _ in range(600):
        y = await a.js("S.palco ? document.querySelector('#palco').scrollTop : null")
        if y is not None and topo is not None and abs(y - topo) > 4:
            break
        topo = y if y is not None else None
        await asyncio.sleep(0.5)
    print(f"gravando {args.segundos:g} s: pode rolar", file=sys.stderr, flush=True)
    return await a.gravar(lambda: asyncio.sleep(args.segundos))


async def custo(a, args):
    return await a.js("""(() => {
      const p = document.querySelector('#palco'), b = document.body;
      const mede = (f, desf) => { const xs = []; for (let i = 0; i < 4; i++) { b.offsetHeight; const t0 = performance.now(); f(); b.offsetHeight;
        xs.push(+(performance.now() - t0).toFixed(1)); desf(); b.offsetHeight; } return xs; };
      const troca = (el, c) => mede(() => el.classList.toggle(c), () => el.classList.toggle(c));
      return { elementos: document.querySelectorAll('*').length, 'palco.no-topo': troca(p, 'no-topo'), 'palco.puxando': troca(p, 'puxando'),
               'body.com-palco': troca(b, 'com-palco'), 'classe qualquer': troca(p, 'x-medida') }; })()""")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("medida", choices=("rolagem", "puxao", "abrir", "custo", "dedo"))
    ap.add_argument("--recarregar", action="store_true")
    ap.add_argument("--css", default="")
    ap.add_argument("--trace")
    ap.add_argument("--segundos", type=float, default=15)
    ap.add_argument("--esperar", action="store_true", help="espera o celular aparecer no adb (ate 10 min)")
    args = ap.parse_args()
    adb_forward(args.esperar)
    a = await conectar()
    try:
        r = await {"rolagem": rolagem, "puxao": puxao, "abrir": abrir, "custo": custo, "dedo": dedo}[args.medida](a, args)
        if isinstance(r, list):
            if args.trace:
                with open(args.trace, "w", encoding="utf-8") as f:
                    json.dump(r, f)
            r = resumo(r)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    finally:
        await a.css("")
        await a.js("document.querySelector('#palco').scrollTop = 0")
        await a.ws.close()


if __name__ == "__main__":
    asyncio.run(main())
