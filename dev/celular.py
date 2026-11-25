"""Mede o tema no Chrome do celular de verdade (USB, depuracao ligada), so rolando e puxando, numa aba de um servidor
--mock do PC, nunca no Ritmelli de verdade (o som do 8799 sai no jogo).

    python dev/celular.py rolagem --url URL [--recarregar] [--css "<regra injetada>"] [--trace saida.json]
    python dev/celular.py puxao --url URL [--css ...]   # puxa o palco aberto 150 px para baixo e volta
    python dev/celular.py abrir --url URL               # abre e fecha o palco pela funcao do app
    python dev/celular.py custo --url URL               # ms de estilo das classes que o palco troca
    python dev/celular.py dedo --url URL [--segundos 15] [--esperar]   # so grava, enquanto o usuario rola com o dedo

URL e a aba de teste, a do --mock com o papel do celular (python server.py --mock --port 8801 --no-browser
--papel-local celular), sempre em 127.0.0.1: http://127.0.0.1:8801/t/ritmelli/. Antes: adb no PATH (ou ADB=<caminho do
adb.exe>) e o celular autorizado em `adb devices`. O script so fala com um --mock (dev/so_mock.py): recusa a porta 8799 e a origem cujo /api/state nao
traz o "mock": true (sem seguir redirecionamento). Faz o forward da porta 9222 e o `adb reverse` da porta do --mock (ele
so escuta em 127.0.0.1; um mapeamento que ja existia no celular nao e trocado), abre a aba de teste se ela nao estiver
aberta e so mexe nela (as outras abas sao do usuario). Nela, barra o documento de outra origem; antes de abrir a aba,
antes de cada gesto e antes de publicar a medida, confere de novo o marcador e a pagina da aba. Pelo adb reverse, o
--mock e o tema veem 127.0.0.1, que no --papel-local celular faz o papel do celular da rede de casa: a aba pede o
codigo, o script o le pelo lado do PC (o GET /api/pareamento com o Host localhost:<porta>), pareia a aba pelo tema e, no
fim, desconecta pelo PC o celular que pareou. Num --mock sem o --papel-local celular, a medida sai com o papel do PC.
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
import urllib.parse
import urllib.request
from collections import Counter

import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import so_mock  # noqa: E402
from fitcheck import barra_outra_origem, confere_pagina  # noqa: E402

BASE = "http://127.0.0.1:9222"
CATS = ["devtools.timeline", "disabled-by-default-devtools.timeline", "disabled-by-default-devtools.timeline.frame",
        "cc", "viz", "gpu", "benchmark", "input", "blink", "blink.animations", "toplevel"]


def adb_forward(url, porta, esperar=False):
    """O forward da 9222 (o DevTools do Chrome do celular) e o reverse da porta do --mock do url. Volta o adb."""
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
    try:
        so_mock.confere(url)  # de novo logo antes do reverse: o --esperar pode ter levado ate 10 min
    except so_mock.Recusa as ex:
        sys.exit(f"recusado: {ex}")
    # --no-rebind: um mapeamento que ja existia no celular nao e trocado (nem removido no fim)
    r = subprocess.run([adb, "reverse", "--no-rebind", f"tcp:{porta}", f"tcp:{porta}"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        sys.exit(f"o adb reverse da porta {porta} nao foi criado ({(r.stderr or r.stdout).strip()}); se ja existe "
                 f"(adb reverse --list), use outra porta no --mock ou tire o de antes (adb reverse --remove tcp:{porta})")
    return adb


class Aba:
    def __init__(self, ws, url, base):
        self.ws, self.url, self.n, self.pend, self.on, self.barrados = ws, url, 0, {}, {}, []
        fetch = barra_outra_origem(ws, base, self.barrados)  # o documento de outra origem, barrado (so_mock.DOCUMENTOS)
        self.on["Fetch.requestPaused"] = lambda p: fetch({"method": "Fetch.requestPaused", "params": p})

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

    async def confere(self):
        """Antes de cada gesto: a aba segue na pagina do --url (origem e caminho; a galeria da mesma origem nao conta),
        nenhum documento barrado, e ele segue um --mock."""
        await confere_pagina(self.cmd, self.url, self.barrados)
        caminho = await self.js("location.pathname")
        if caminho != urllib.parse.urlsplit(self.url).path:
            raise so_mock.Recusa(f"a aba saiu de {urllib.parse.urlsplit(self.url).path} para {caminho}")

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


def do_pc(base, metodo, rota):
    """Um pedido ao --mock pelo lado do PC: o mesmo 127.0.0.1, com o Host localhost:<porta>, que o --papel-local
    celular deixa com o papel do PC. So depois de conferir que a origem segue um --mock."""
    so_mock.confere(base)
    porta = so_mock.origem(base)[1]
    req = urllib.request.Request(base + rota, method=metodo, headers={"Host": f"localhost:{porta}"})
    with so_mock.abre(req) as r:
        return json.load(r)


async def parear_aba(a, base):
    """No --papel-local celular, a aba sem pareamento: o codigo do PC, digitado pelo tema (o parear dele, o mesmo do
    formulario), e a aba com o caps do celular. Volta os ids dos celulares que este script pareou, para desconectar."""
    # o papel de agora, pelo servidor (o api() do tema, na propria aba): o S.caps pode ser o de um --mock de antes na
    # mesma porta, e o 401 ja poe a aba na tela do codigo
    papel = await a.js("api('GET', '/api/state').then(s => s.caps && s.caps.papel,"
                       " e => { if (e.status === 401) return null; throw e; })")
    if papel == "celular":
        return []
    caminho = urllib.parse.urlsplit(a.url).path
    antes = do_pc(base, "GET", f"/api/pareamento?caminho={urllib.parse.quote(caminho)}")
    if not antes.get("codigo"):
        raise so_mock.Recusa("o --mock nao deu o codigo do pareamento (o --papel-local celular gera no 127.0.0.1)")
    await a.confere()
    await a.js(f"parear({json.dumps(antes['codigo'])})")
    for _ in range(50):
        await asyncio.sleep(0.2)
        if await a.js("!!(S.caps && S.caps.papel === 'celular') && !S.pareando"):
            break
    else:
        raise so_mock.Recusa("a aba nao pareou com o codigo do PC")
    de_antes = {c["id"] for c in antes.get("celulares", [])}
    novos = [c["id"] for c in do_pc(base, "GET", "/api/pareamento").get("celulares", []) if c["id"] not in de_antes]
    if len(novos) != 1:  # outro aparelho pareou no meio: nenhum sai, para nao desconectar o que nao e deste script
        raise so_mock.Recusa(f"esperava um aparelho novo no PC depois de parear a aba, achei {len(novos)}")
    print("aba pareada como celular", file=sys.stderr, flush=True)
    return novos


def desconectar(base, ids):
    """Desconecta pelo PC os celulares que o script pareou."""
    for aid in ids:
        try:
            do_pc(base, "DELETE", f"/api/pareamento/{urllib.parse.quote(aid)}")
        except (so_mock.Recusa, OSError, ValueError) as ex:
            print(f"o celular {aid} nao foi desconectado: {ex}", file=sys.stderr, flush=True)


async def conectar(url, base):
    """A aba de teste (a do url, com caminho e query); sem ela, abre uma em branco e, com o documento de outra origem
    barrado, navega ate o url, depois de conferir o marcador de novo."""
    abas = [t for t in json.load(urllib.request.urlopen(BASE + "/json"))
            if t["type"] == "page" and t["url"].split("#")[0] == url.split("#")[0]]
    if len(abas) > 1:
        sys.exit(f"esperava uma aba de {url} no celular, achei {len(abas)}: feche as outras")
    nova = not abas
    if nova:
        abas = [json.load(urllib.request.urlopen(urllib.request.Request(BASE + "/json/new", method="PUT")))]
    a = Aba(await websockets.connect(abas[0]["webSocketDebuggerUrl"], max_size=1 << 30), url, base)
    a.laco_t = asyncio.create_task(a.laco())  # guardada: o loop so tem referencia fraca da tarefa
    await a.cmd("Runtime.enable")
    await a.cmd("Page.enable")
    await a.cmd("Fetch.enable", patterns=so_mock.DOCUMENTOS)
    if nova:
        so_mock.confere(url)
        await a.cmd("Page.navigate", url=url)
        print(f"aba de teste aberta no celular: {url}", file=sys.stderr, flush=True)
        await asyncio.sleep(5)  # a carga do tema
    await a.confere()
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
        await a.confere()
    await a.js("document.querySelector('#palco').scrollTop = 0")
    await asyncio.sleep(1.0)


async def rolagem(a, args):
    await a.confere()
    if args.recarregar:
        await a.cmd("Page.reload", ignoreCache=True)
        await asyncio.sleep(5)
        await a.confere()
    await a.css(args.css)
    await palco_aberto(a)

    async def gesto():
        for dy in (-520, -520, -520, 520, 520, 520):   # tres puxoes ate os pedais e tres de volta, com fling
            await a.confere()
            await a.cmd("Input.synthesizeScrollGesture", x=180, y=420, yDistance=dy, speed=1800, gestureSourceType="touch", preventFling=False)
            await asyncio.sleep(1.2)
    return await a.gravar(gesto)


async def puxao(a, args):
    await a.confere()
    await a.css(args.css)
    await palco_aberto(a)

    async def gesto():
        await a.confere()
        await a.cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": 180, "y": 300}])
        for y in list(range(300, 452, 8)) + list(range(452, 299, -8)):   # desce 150 px e volta: nao fecha
            t = time.perf_counter()
            await a.cmd("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": 180, "y": y}])
            await asyncio.sleep(max(0, 0.016 - (time.perf_counter() - t)))
        await a.cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        await asyncio.sleep(0.8)
    return await a.gravar(gesto)


async def abrir(a, args):
    await a.confere()
    if await a.js("S.palco"):
        await a.js("fecharPalco()")
        await asyncio.sleep(1.5)
    saidas = {}
    for acao in ("abrirPalcoComHistoria()", "fecharPalco()"):
        async def gesto(acao=acao):
            await a.confere()
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
    await a.confere()
    topo = None
    for _ in range(600):
        y = await a.js("S.palco ? document.querySelector('#palco').scrollTop : null")
        if y is not None and topo is not None and abs(y - topo) > 4:
            break
        topo = y if y is not None else None
        await asyncio.sleep(0.5)
    await a.confere()  # a espera pode ter levado ate 5 min
    print(f"gravando {args.segundos:g} s: pode rolar", file=sys.stderr, flush=True)
    return await a.gravar(lambda: asyncio.sleep(args.segundos))


async def custo(a, args):
    await a.confere()
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
    ap.add_argument("--url", required=True, help="a aba de teste, a do --mock: http://127.0.0.1:8801/t/ritmelli/")
    ap.add_argument("--recarregar", action="store_true")
    ap.add_argument("--css", default="")
    ap.add_argument("--trace")
    ap.add_argument("--segundos", type=float, default=15)
    ap.add_argument("--esperar", action="store_true", help="espera o celular aparecer no adb (ate 10 min)")
    args = ap.parse_args()
    try:
        if urllib.parse.urlsplit(args.url).hostname != "127.0.0.1":  # o PC e o celular (adb reverse) no mesmo lugar
            raise so_mock.Recusa(f"{args.url}: a aba de teste e a do --mock em http://127.0.0.1:<porta>/...")
        base = so_mock.confere(args.url)  # antes do adb e da aba
    except so_mock.Recusa as ex:
        sys.exit(f"recusado: {ex}")
    porta = so_mock.origem(args.url)[1]
    try:  # no --papel-local celular, o 127.0.0.1 recebe o 401 do pareamento
        como_celular = so_mock.estado(base).get("parear") is True
    except (so_mock.Recusa, OSError) as ex:
        sys.exit(f"recusado: {ex}")
    adb = adb_forward(args.url, porta, args.esperar)
    if not como_celular:
        print("este --mock nao tem o --papel-local celular: pelo adb reverse, o tema ve 127.0.0.1 e a medida sai com o "
              "papel do PC", file=sys.stderr, flush=True)
    try:
        await medir(args, base, como_celular)
    except so_mock.Recusa as ex:
        sys.exit(f"recusado: {ex}; nenhum gesto a mais, e a medida nao sai")
    finally:
        subprocess.run([adb, "reverse", "--remove", f"tcp:{porta}"], capture_output=True)


async def medir(args, base, como_celular):
    a = await conectar(args.url, base)
    pareados = []
    try:
        if como_celular:
            pareados = await parear_aba(a, base)
        r = await {"rolagem": rolagem, "puxao": puxao, "abrir": abrir, "custo": custo, "dedo": dedo}[args.medida](a, args)
        await a.confere()  # a medida so vale se a aba seguiu no --mock ate o fim
        if isinstance(r, list):
            if args.trace:
                with open(args.trace, "w", encoding="utf-8") as f:
                    json.dump(r, f)
            r = resumo(r)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    finally:
        try:
            try:
                await a.confere()
                await a.css("")
                await a.js("document.querySelector('#palco').scrollTop = 0")
            except so_mock.Recusa:
                pass  # a aba saiu do --mock: nada mais nela
            await a.ws.close()
        finally:
            desconectar(base, pareados)  # mesmo se a limpeza da aba falhou


if __name__ == "__main__":
    asyncio.run(main())
