"""Confere se a tela do celular mudou: prints do tema em estados fixos, comparados pixel a pixel com os de
referencia. E o gate da passagem do PC para pixel art: o celular tem que sair identico.

    python dev/compara.py --ref     (antes de mexer no tema: grava os prints de referencia)
    python dev/compara.py           (depois: tira de novo e compara; sai 1 se algo mudou)
        [--pasta logs/compara] [--sizes 390x844@3,360x780@2.625] [--wait 0.6] [--lang pt_BR]

Sobe o proprio servidor (server.py --mock numa porta livre, pelo dev/so_mock.py: nunca a 8799, nem uma porta em que
alguem ja responde, e so manda pedido a ele enquanto ele esta vivo e responde como --mock) com uma prateleira de
mentira, sempre a mesma, e os dados numa pasta temporaria (com a LOCALAPPDATA trocada: o Ritmelli de verdade nem fica
sabendo). Os prints saem pelo Chrome headless, como no dev/shot.py, na densidade de tela de cada celular (o @ do
tamanho). Para o mesmo tema dar o mesmo print toda vez:
- as capas sao desenhos em data: URI e as fontes moram no tema (themes/ritmelli/fonts/; o bloqueio do
  Google Fonts fica de guarda, caso alguma volte a apontar para la): nada vem da internet;
- os tick do SSE chegam com os niveis zerados (a voz falsa do --mock mexeria nos VUs);
- animacoes reduzidas, e cada estado sai duas vezes: se os dois prints diferem, o estado e instavel e
  o script avisa em vez de comparar.

Dois cenarios: vazio (nada no prato) e tocando (um disco pausado no meio, um efeito ligado e dois discos na
fila). Em cada um, a pagina inicial e o palco aberto, rolando de tela em tela; no vazio tambem o menu de
um disco e o dialogo Microfone e fone. Os prints ficam em <pasta>/ref e <pasta>/agora; o que mudou vai
para <pasta>/diff, em vermelho por cima do print novo apagado.
"""
import argparse
import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path
from urllib.parse import quote

import numpy as np
import websockets
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import so_mock  # noqa: E402
from fitcheck import CHROME, barra_outra_origem, fecha_chrome  # noqa: E402
from so_mock import free_port  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
# o celular pequeno, o de sempre, o grande e o tablet em pe (abaixo de 900 px tambem e o layout do celular)
SIZES = "360x780@2.625,390x844@3,430x932@3,768x1024@2"

# id, titulo, canal, duracao (s), capa (de, ate, cor, forma; None = a capa que o tema gera), onde parou (s), vezes
DISCOS = [
    ("disco-01", "Banda do Bairro - Sereno da Madrugada", "Banda do Bairro", 214,
     ("#3B1F5C", "#E0703A", "#F7D36B", "sol"), 0, 9),
    ("disco-02", "Coral de Quintal - Cirandeiro (Ao Vivo no Teatro Municipal)", "Coral de Quintal", 263,
     ("#0E3B43", "#2A9D8F", "#E9C46A", "faixas"), 81.5, 8),
    ("disco-03", "Trio Ferro e Fole - Xote da Estação", "Trio Ferro e Fole", 198, None, 0, 7),
    ("disco-04", "MC Exemplo - Rua Sem Saída (prod. Fulano)", "MC Exemplo", 176,
     ("#1B1B1B", "#5C5C5C", "#D62828", "serra"), 38.2, 6),
    ("disco-05", "Orquestra Imaginária - Suíte nº 2: Abertura", "Orquestra Imaginária", 412,
     ("#F1E3C8", "#B08850", "#5A3A1A", "vinil"), 0, 5),
    ("disco-06", "Chuva na Janela - 1 hora de lo-fi para estudar", "Rádio Sossego", 3600,
     ("#22333B", "#5E7C8B", "#EAE0D5", "faixas"), 1325, 4),
    ("disco-07", "Samba de Roda do Recôncavo", "Grupo de Roda", 240, None, 0, 3),
    ("disco-08", "Tema de Abertura", "Ritmelli", 95, ("#6A040F", "#E85D04", "#FFBA08", "sol"), 0, 2),
    ("disco-09", "Forró pé de serra", "Sanfona Velha", 187, ("#283618", "#606C38", "#FEFAE0", "serra"), 0, 1),
    ("disco-10", "Valsa para um toca-discos", "Quarteto de Cordas", 305, None, 0, 1),
    ("disco-11", "Boletim do trânsito", "Rádio Exemplo FM", 62, ("#023047", "#219EBC", "#FFB703", "vinil"), 0, 0),
    ("disco-12", "Ensaio aberto", "Banda do Bairro", 248, ("#3A0CA3", "#7209B7", "#F72585", "sol"), 0, 0),
    ("som-01", "Buzina", None, 3.2, None, 0, 0),
    ("som-02", "Aplausos da plateia", None, 8.5, ("#5F0F40", "#9A031E", "#FB8B24", "faixas"), 0, 0),
    ("som-03", "Tambor rufando", None, 12, None, 0, 0),
]
RAPIDOS = {"disco-08"}          # posto nos Sons rapidos pela mao
NO_PRATO = "disco-01"           # o do cenario tocando, o unico com arquivo (silencio)
PAUSA_EM = 86.0                 # 40% dele
NA_FILA = ("disco-03", "disco-05")

# antes de qualquer script do tema: o tick passa com a posicao, mas com os niveis zerados
SEM_NIVEIS = """(() => {
  const add = EventSource.prototype.addEventListener;
  EventSource.prototype.addEventListener = function (tipo, fn, ...resto) {
    if (tipo !== 'tick') return add.call(this, tipo, fn, ...resto);
    return add.call(this, tipo, e => {
      const t = JSON.parse(e.data);
      t.levels = { mic: 0, track: 0, out: 0 };
      fn({ data: JSON.stringify(t) });
    }, ...resto);
  };
})();"""
PRONTO = ("document.readyState === 'complete' && document.fonts.status === 'loaded' && !!S.state && "
          "S.lib.length > 0 && [...document.images].every(i => i.complete)")
PALCO = "document.querySelector('#palco')"


def capa(de, ate, cor, forma):
    """Capa de mentira em data: URI, no formato das do YouTube (16:9)."""
    desenho = {
        "sol": f"<circle cx='212' cy='78' r='52' fill='{cor}'/><rect y='128' width='320' height='52' fill-opacity='.35'/>",
        "faixas": "".join(f"<rect y='{y}' width='320' height='16' fill='{cor}' fill-opacity='.55'/>"
                          for y in range(14, 180, 40)),
        "serra": f"<path d='M0 180 L96 64 L150 122 L222 38 L320 180Z' fill='{cor}'/>",
        "vinil": f"<circle cx='160' cy='90' r='72' fill='#141414'/><circle cx='160' cy='90' r='24' fill='{cor}'/>",
    }[forma]
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='320' height='180' viewBox='0 0 320 180'>"
           f"<defs><linearGradient id='g' x2='1' y2='1'><stop offset='0' stop-color='{de}'/>"
           f"<stop offset='1' stop-color='{ate}'/></linearGradient></defs>"
           f"<rect width='320' height='180' fill='url(#g)'/>{desenho}</svg>")
    return "data:image/svg+xml," + quote(svg, safe="")


def prateleira():
    itens = []
    for i, (iid, titulo, canal, dur, c, parou, vezes) in enumerate(DISCOS):
        it = {"id": iid, "title": titulo, "file": f"{iid}.wav" if iid == NO_PRATO else f"{iid}.webm",
              "duration": dur, "youtube_id": None, "thumb": capa(*c) if c else None, "channel": canal,
              "added": f"2026-10-{i + 1:02d}T12:00:00", "last_pos": parou, "plays": vezes}
        if iid in RAPIDOS:
            it["rapido"] = True
        itens.append(it)
    return itens


def sobe_servidor(tmp, porta, log):
    """O servidor --mock na porta, com a prateleira de mentira: o so_mock.Filho dele. Sai antes de qualquer pedido se a
    porta e a 8799, se alguem ja responde nela ou se quem responde nao e o filho vivo com o "mock": true."""
    dados, lib = tmp / "dados", tmp / "local" / "Ritmelli" / "library"
    dados.mkdir(parents=True)
    lib.mkdir(parents=True)
    (dados / "library.json").write_text(json.dumps(prateleira(), ensure_ascii=False), encoding="utf-8")
    dur = next(d[3] for d in DISCOS if d[0] == NO_PRATO)
    with wave.open(str(lib / f"{NO_PRATO}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(bytes(2 * 8000 * dur))
    # sys.executable e o python de verdade: o "python" do PATH, com a LOCALAPPDATA trocada, instalaria outro
    try:
        return so_mock.sobe([sys.executable, str(RAIZ / "server.py"), "--mock", "--no-browser", "--port", str(porta),
                             "--data-dir", str(dados)], porta, cwd=RAIZ, stdout=log, stderr=subprocess.STDOUT,
                            env=dict(os.environ, LOCALAPPDATA=str(tmp / "local")))
    except so_mock.Recusa as ex:
        sys.exit(f"{ex} (ver {log.name})")


def para_servidor(srv):
    """O /api/shutdown so ao filho vivo que responde como --mock; se nao, o handle dele."""
    srv.encerra()


def monta_tocando(srv):
    """O disco pausado no meio, um efeito ligado e dois discos na fila. Cada pedido confere antes o filho e o marcador
    (so_mock.Filho.api); se a conferencia falha, so o filho sai."""
    try:
        _monta_tocando(srv.api)
    except so_mock.Recusa as ex:
        srv.mata()
        sys.exit(f"o cenario tocando parou: {ex}")


def _monta_tocando(api):
    ef = next(e["id"] for e in api("GET", "/api/effects") if e["grupo"])
    api("POST", "/api/settings", {"effect": ef})
    api("POST", "/api/play", {"id": NO_PRATO, "start": PAUSA_EM})
    for _ in range(100):
        if api("GET", "/api/state")["status"] == "playing":
            break
        time.sleep(0.1)
    api("POST", "/api/pause")
    api("POST", "/api/seek", {"t": PAUSA_EM})
    for iid in NA_FILA:
        api("POST", "/api/queue", {"id": iid})
    s = api("GET", "/api/state")
    if s["status"] != "paused" or len(s["queue"]) != len(NA_FILA):
        sys.exit(f"o cenario tocando nao montou: status {s['status']}, {len(s['queue'])} na fila")


class Chrome:
    def __init__(self, ws, base):
        self.ws, self.seq, self.pend, self.erros, self.barrados = ws, 0, {}, [], []
        self.fetch = barra_outra_origem(ws, base, self.barrados)  # o documento de outra origem, barrado

    async def le(self):
        async for raw in self.ws:
            m = json.loads(raw)
            if m.get("id") in self.pend:
                self.pend.pop(m["id"]).set_result(m)
            elif self.fetch(m):
                pass
            elif m.get("method") == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                self.erros.append("excecao: " + (d.get("exception", {}).get("description") or d.get("text", "")))
            elif m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] == "error":
                self.erros.append("console.error: " + " ".join(str(x.get("value", x.get("description", "")))
                                                                for x in m["params"]["args"]))

    async def cmd(self, metodo, **params):
        self.seq += 1
        fut = asyncio.get_running_loop().create_future()
        self.pend[self.seq] = fut
        await self.ws.send(json.dumps({"id": self.seq, "method": metodo, "params": params}))
        r = await asyncio.wait_for(fut, 30)
        if "error" in r:
            raise RuntimeError(f"{metodo}: {r['error']}")
        return r.get("result", {})

    async def js(self, expr):
        r = await self.cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(f"js falhou: {expr[:80]} -> {r['exceptionDetails'].get('exception', {}).get('description')}")
        return r.get("result", {}).get("value")

    async def png(self):
        return base64.b64decode((await self.cmd("Page.captureScreenshot", format="png"))["data"])


def pixels(png):
    return np.asarray(Image.open(io.BytesIO(png) if isinstance(png, bytes) else png).convert("RGB"))


def diferenca(pa, pb, arquivo):
    """Os pixels que mudaram; se mudou algum, grava o print novo apagado com eles em vermelho."""
    m = (pa != pb).any(axis=2)
    if m.any():
        img = (pb * .3).astype(np.uint8)
        img[m] = (255, 0, 0)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(img).save(arquivo)
    return m


async def prints(a, srv, destino):
    instaveis = []
    prof = tempfile.mkdtemp(prefix="sbcomp_")
    cport = free_port()
    # desenho por software: com a GPU, o braco girado e o degrade das capas mudavam de 1 a 129 mil pixels (ate 32
    # de 255) entre dois prints seguidos do mesmo estado
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={cport}", f"--user-data-dir={prof}",
                               "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
                               "--disable-gpu", "--force-color-profile=srgb", "--disable-lcd-text",
                               "--disable-partial-raster", "--disable-skia-runtime-opts", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{cport}/json"))
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                break
            except Exception:  # noqa: BLE001 - o Chrome ainda esta subindo
                time.sleep(0.1)
        if not ws_url:
            sys.exit("chrome headless nao subiu")
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            c = Chrome(ws, srv.base)
            leitor = asyncio.create_task(c.le())
            for d in ("Page", "Runtime", "Network"):
                await c.cmd(f"{d}.enable")
            await c.cmd("Network.setBlockedURLs", urls=["*fonts.googleapis.com*", "*fonts.gstatic.com*"])
            await c.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
            await c.cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            await c.cmd("Page.addScriptToEvaluateOnNewDocument", source=SEM_NIVEIS)
            await c.cmd("Fetch.enable", patterns=so_mock.DOCUMENTOS)

            async def estado(nome):
                await asyncio.sleep(a.wait)
                p1 = await c.png()
                await asyncio.sleep(0.5)
                p2 = await c.png()
                if c.barrados:  # a pagina foi embora durante o estado: o print nao vale
                    sys.exit(f"{nome}: a pagina tentou ir para outra origem ({c.barrados[0]}): barrada")
                (destino / f"{nome}.png").write_bytes(p2)
                if p1 != p2:
                    pa, pb = pixels(p1), pixels(p2)
                    m = diferenca(pa, pb, destino.parent / "instavel" / f"{nome}.png")
                    if m.any():
                        delta = int(np.abs(pa.astype(int) - pb.astype(int)).max())
                        instaveis.append(f"{nome}: {int(m.sum())} pixels, ate {delta} de 255")
                print(f"  {nome}", flush=True)

            for cenario in ("vazio", "tocando"):
                if cenario == "tocando":
                    monta_tocando(srv)
                for sz in a.sizes.split(","):
                    tam, dpr = sz.split("@")
                    w, h = map(int, tam.split("x"))
                    pre = f"{cenario}-{tam}"
                    await c.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=float(dpr),
                                mobile=True)
                    try:
                        srv.confere()  # a pagina so do filho vivo que responde como --mock
                    except so_mock.Recusa as ex:
                        sys.exit(f"{pre}: {ex}")
                    await c.cmd("Page.navigate", url=f"{srv.base}/t/ritmelli/?lang={a.lang}")
                    for _ in range(200):
                        await asyncio.sleep(0.1)
                        if c.barrados:
                            sys.exit(f"{pre}: a pagina tentou ir para outra origem ({c.barrados[0]}): barrada")
                        try:
                            if await c.js(PRONTO):
                                break
                        except RuntimeError:  # a pagina ainda nao tem o S
                            pass
                    else:
                        sys.exit(f"{pre}: o tema nao ficou pronto em 20 s")
                    await asyncio.sleep(1)
                    for i in range(await c.js("Math.ceil(document.documentElement.scrollHeight / innerHeight)")):
                        await c.js(f"scrollTo(0, {i} * innerHeight)")
                        await estado(f"{pre}-inicio-{i}")
                    await c.js("scrollTo(0, 0)")
                    if cenario == "vazio":
                        await c.js("document.querySelector('#estante li[data-id] .capa').dispatchEvent("
                                   "new MouseEvent('contextmenu', { bubbles: true, cancelable: true }))")
                        await estado(f"{pre}-menu")
                        await c.js("fecharMenu(false)")
                        await c.js("document.querySelector('#b-disp').click()")
                        # os aparelhos chegam depois de abrir: na primeira vez o servidor ainda le os do Windows (mais
                        # que o --wait), e os dois prints do estado saiam um sem a lista e o outro com ela (#128)
                        for _ in range(150):
                            if await c.js("!document.querySelector('#dd-mic').disabled && "
                                          "!document.querySelector('#dd-msg').textContent"):
                                break
                            await asyncio.sleep(0.1)
                        await estado(f"{pre}-dialogo")
                        await c.js("document.querySelector('#dlg-disp').close()")
                    await c.js("document.querySelector('#mini-abrir').click()")
                    await asyncio.sleep(0.5)
                    for i in range(await c.js(f"(p => Math.ceil(p.scrollHeight / p.clientHeight))({PALCO})")):
                        await c.js(f"(p => {{ p.scrollTop = {i} * p.clientHeight; }})({PALCO})")
                        await estado(f"{pre}-palco-{i}")
            leitor.cancel()
            return c.erros, instaveis
    finally:
        fecha_chrome(chrome, prof)   # com o chrome_crashpad_handler, que segurava o perfil (#126)


def compara(pasta, tamanhos):
    ref, agora, diff = pasta / "ref", pasta / "agora", pasta / "diff"
    shutil.rmtree(diff, ignore_errors=True)
    # so os tamanhos desta rodada: com --sizes, os outros nao sumiram
    desta = {p.name for p in ref.glob("*.png") if any(f"-{t}-" in p.name for t in tamanhos)}
    nomes = sorted(desta | {p.name for p in agora.glob("*.png")})
    mudou = 0
    for nome in nomes:
        a, b = ref / nome, agora / nome
        if not a.exists() or not b.exists():
            print(f"{'NOVO ' if b.exists() else 'SUMIU'}  {nome[:-4]}")
            mudou += 1
            continue
        pa, pb = pixels(a), pixels(b)
        if pa.shape != pb.shape:
            print(f"MUDOU  {nome[:-4]}: o print era {pa.shape[1]}x{pa.shape[0]} e agora e {pb.shape[1]}x{pb.shape[0]}")
            mudou += 1
            continue
        m = diferenca(pa, pb, diff / nome)
        if not m.any():
            continue
        mudou += 1
        ys, xs = np.nonzero(m)
        print(f"MUDOU  {nome[:-4]}: {int(m.sum())} pixels, de ({xs.min()}, {ys.min()}) a ({xs.max()}, {ys.max()})")
    print(f"{len(nomes) - mudou} de {len(nomes)} prints iguais" + (f"; a diferenca em {diff}" if mudou else ""))
    return mudou


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", action="store_true", help="grava os prints de referencia (no tema de antes da mudanca)")
    ap.add_argument("--pasta", default=str(RAIZ / "logs" / "compara"))
    ap.add_argument("--sizes", default=SIZES, help="largura x altura @ densidade, separados por virgula")
    ap.add_argument("--wait", type=float, default=0.6, help="segundos entre cada passo e o print")
    # o Chrome sem cabeca pede ingles: sem o ?lang=, a tela sairia na lingua dele, e nao na das referencias
    ap.add_argument("--lang", default="pt_BR", help="a lingua da tela (pt_BR ou en); a referencia e a comparacao na mesma")
    a = ap.parse_args()
    pasta = Path(a.pasta)
    if not a.ref and not (pasta / "ref").exists():
        sys.exit(f"sem referencia em {pasta / 'ref'}: rode antes com --ref, no tema de antes da mudanca")
    # a referencia nova nasce ao lado da antiga: refazer a antiga pede o tema de antes da mudanca
    destino = pasta / ("ref.novo" if a.ref else "agora")
    shutil.rmtree(destino, ignore_errors=True)
    shutil.rmtree(pasta / "instavel", ignore_errors=True)
    destino.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="ritmelli-compara-"))
    porta = free_port()
    with open(pasta / "servidor.log", "w", encoding="utf-8") as log:
        srv = sobe_servidor(tmp, porta, log)
        try:
            erros, instaveis = asyncio.run(prints(a, srv, destino))
        finally:
            para_servidor(srv)
            shutil.rmtree(tmp, ignore_errors=True)
    for e in erros:
        print(f"ERRO   {e}")
    for i in instaveis:
        print(f"INSTAVEL {i} (dois prints seguidos sairam diferentes)")
    if a.ref:
        if erros or instaveis:
            print(f"a referencia de antes fica: os prints novos estao em {destino}")
            return 1
        shutil.rmtree(pasta / "ref", ignore_errors=True)
        destino.rename(pasta / "ref")
        print(f"{len(list((pasta / 'ref').glob('*.png')))} prints de referencia em {pasta / 'ref'}")
        return 0
    return 1 if compara(pasta, [s.split("@")[0] for s in a.sizes.split(",")]) or erros or instaveis else 0


if __name__ == "__main__":
    sys.exit(main())
