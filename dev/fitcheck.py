"""Confere se um tema cabe na tela em varios tamanhos (regra: se adequar a qualquer tela).

    python dev/fitcheck.py http://127.0.0.1:8806/t/ritmelli/ [--sizes 1366x657,1920x1080]
        [--shots <pasta>] [--js "document.querySelector('#mini-seta').click()"] [--boas-vindas]
    python dev/fitcheck.py --metricas

O --metricas confere o aviso dos dados de uso (o #dlg-metricas), e nao o tamanho: sobe os proprios --mock
--metricas-teste, um por situacao e por botao, pelo sobe_servidor do dev/compara.py, com a rede presa numa armadilha
(o cenario_metricas abaixo diz o que confere). O testa.yml roda num passo proprio do job da tela.

O --js roda depois da carga, antes da conferencia (abrir uma pagina ou um painel e conferir ela tambem).

Uma excecao sem tratamento ou um console.error da pagina, da navegacao ao fim da conferencia, tambem reprova o tamanho.

So fala com um servidor --mock (dev/so_mock.py): antes de abrir a pagina, recusa a porta 8799 e a origem cujo
/api/state nao traz o "mock": true (sem seguir redirecionamento); no Chrome, barra o documento de outra origem; antes de
agir, confere de novo a origem da pagina e o marcador.

A tela de boas-vindas (a da primeira vez, com a prateleira vazia) cobre a pagina: antes de conferir, o fitcheck a fecha
pelo servidor, como o botao do fim dela (#126). Com o --boas-vindas ela fica aberta, e a conferida e ela: a janela
dentro da tela e cada controle dela alcancavel, em todos os tamanhos.

Regra por tamanho:
- tela de computador (largura >= 900): a pagina nao rola, nem na vertical nem na
  horizontal; o que nao cabe rola por dentro de um painel (lista, prateleira). O celular
  grande deitado (915x412, 932x430) passa de 900 e cai no layout do computador: vale a mesma regra;
- celular e tablet em pe (largura < 900): rola so na vertical, nunca de lado.
Alem disso confere cada controle (botao, link, campo, slider) fora de painel que rola:
o centro dele tem que estar na tela e ser dele mesmo, nao recortado por um pai com
overflow hidden nem coberto por outra camada (o controle existe, mas ninguem alcanca).
Sai 1 se algum tamanho reprovar.
"""
import argparse
import asyncio
import base64
import enum
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import websockets
from websockets.exceptions import ConnectionClosed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import so_mock
from so_mock import free_port  # o compara, o perfcheck e o texturas pegam daqui

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SIZES = ("1024x600,1280x650,1280x720,1366x657,1366x768,1436x765,1440x900,1536x730,"
         "1600x900,1920x960,1920x1080,2560x1300,1180x820,915x412,932x430,390x844,360x780,768x1024")

# soDialogo (o --boas-vindas): os controles conferidos sao so os da janela aberta por cima da pagina, e a propria janela
# tem que caber na tela
PROBE = r"""(soDialogo => {
  const vw = innerWidth, vh = innerHeight, d = document.documentElement;
  const dlg = soDialogo ? document.querySelector('dialog[open]') : null;
  // dentro de painel que rola = alcançavel rolando o painel
  const noPainel = el => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (/(auto|scroll)/.test(cs.overflowY + cs.overflowX) &&
          (p.scrollHeight > p.clientHeight + 1 || p.scrollWidth > p.clientWidth + 1)) return true;
    }
    return false;
  };
  const nome = el => `${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/)[0] : ''}` +
                     ` "${(el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30)}"`;
  const cortados = [];
  if (soDialogo) {
    if (!dlg) return {vw, vh, sh: d.scrollHeight, sw: d.scrollWidth, cortados: ['nenhuma janela aberta'], n: 1};
    const b = dlg.getBoundingClientRect();
    if (b.top < -1 || b.left < -1 || b.bottom > vh + 1 || b.right > vw + 1)
      cortados.push(`a janela passa da tela (${Math.round(b.width)}x${Math.round(b.height)})`);
  }
  for (const el of document.querySelectorAll('button, a[href], input, select, textarea, [role=slider], [role=button], [tabindex]:not([tabindex="-1"])')) {
    if (soDialogo ? !dlg.contains(el) : el.closest('dialog')) continue;
    if (el.closest('[hidden], [inert], .so-leitor, .sr-only, .visually-hidden')) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0 || el.disabled) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || r.right < 0 || r.left > vw * 3) continue;  // escondido de proposito
    if (noPainel(el)) continue;
    const cx = Math.min(Math.max(r.left + r.width / 2, 0), vw - 1), cy = Math.min(Math.max(r.top + r.height / 2, 0), vh - 1);
    const foraDaTela = r.top + r.height / 2 > vh || r.left + r.width / 2 > vw;
    let motivo = foraDaTela ? 'fora da tela' : null;
    if (!motivo) {
      // o centro do controle tem que ser dele: senao esta recortado por um pai ou coberto
      const hit = document.elementFromPoint(cx, cy);
      const lbl = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
      const dono = hit && (hit === el || el.contains(hit) || hit.contains(el) || (lbl && (lbl === hit || lbl.contains(hit))) ||
                           (hit.closest && hit.closest('label') && hit.closest('label').contains(el)));
      if (!dono) motivo = hit ? `coberto por ${nome(hit)}` : 'invisivel';
    }
    if (motivo) cortados.push(`${nome(el)} (${motivo})`);
  }
  return {vw, vh, sh: d.scrollHeight, sw: d.scrollWidth, cortados: cortados.slice(0, 8), n: cortados.length};
})"""


# the page is ready to be checked: loaded, the fonts in, the first /api/state of the theme applied and every image
# decoded. The compara waits for the same, plus its fake shelf. In a try: before the theme script runs, S does not exist
READY_CONDITIONS = (("document complete", "document.readyState === 'complete'"),
                    ("fonts loaded", "document.fonts.status === 'loaded'"),
                    ("S.state", "!!S.state"),
                    ("images complete", "[...document.images].every(i => i.complete)"))
PRONTA = ("(() => { try { return " + " && ".join(js for _, js in READY_CONDITIONS) +
          "; } catch (e) { return false; } })()")
PRONTA_S = 20.0
JS_WAIT_S = 1.5
CDP_GONE = (ConnectionClosed, ConnectionError)
DIAGNOSTIC_DOMAINS = ("Page", "Runtime", "Network", "Log")


class Ready(enum.Enum):
    READY = "ready"
    TIMED_OUT = "timed out"
    LEFT = "left for another origin"
    CHROME_GONE = "chrome gone"


async def wait_ready(cmd, expr, blocked, timeout_s):
    deadline = time.monotonic() + timeout_s
    while not blocked:
        if (left := deadline - time.monotonic()) <= 0:
            return Ready.TIMED_OUT
        try:
            r = await asyncio.wait_for(cmd("Runtime.evaluate", expression=expr, returnByValue=True), left)
        except CDP_GONE:
            return Ready.CHROME_GONE
        except (RuntimeError, TimeoutError):
            r = {}
        if blocked:
            return Ready.LEFT
        if time.monotonic() > deadline:
            return Ready.TIMED_OUT
        if r.get("result", {}).get("value") is True:
            return Ready.READY
        await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    return Ready.LEFT


async def navigate_and_wait(cmd, url, expr, blocked, timeout_s):
    try:
        await cmd("Page.navigate", url=url)
    except CDP_GONE:
        return Ready.CHROME_GONE
    return await wait_ready(cmd, expr, blocked, timeout_s)


async def wait_for_state(events, reader, timeout_s):
    deadline = time.monotonic() + timeout_s
    while events.state_at is None:
        events.state_changed.clear()
        waiter = asyncio.ensure_future(events.state_changed.wait())
        done, _ = await asyncio.wait({waiter, reader}, timeout=max(0.0, deadline - time.monotonic()),
                                     return_when=asyncio.FIRST_COMPLETED)
        waiter.cancel()
        if reader in done:
            return Ready.CHROME_GONE
        if not done:
            return Ready.TIMED_OUT
    return Ready.READY


async def wait_notice(cmd, deadline):
    while (left := deadline - time.monotonic()) > 0:
        try:
            r = await asyncio.wait_for(cmd("Runtime.evaluate", expression=NOTICE_OPEN, returnByValue=True), left)
        except TimeoutError:
            return False
        if time.monotonic() > deadline:
            return False
        if r.get("result", {}).get("value") is True:
            return True
        await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    return False


async def calibrate_clock(cmd, events):
    await cmd("Performance.enable")
    before = time.monotonic()
    metrics = (await cmd("Performance.getMetrics")).get("metrics", [])
    after = time.monotonic()
    ticks = next((m["value"] for m in metrics if m.get("name") == "Timestamp"), None)
    if ticks is None:
        raise RuntimeError("Performance.getMetrics gave no Timestamp to set the CDP clock against")
    events.mono_minus_ticks = (before + after) / 2 - ticks


class PageEvents:
    def __init__(self, origin=None):
        self.page_errors, self.browser_errors, self.failed_responses = [], [], []
        self.state_changed, self.origin, self.mono_minus_ticks = asyncio.Event(), origin, None
        self.new_load()

    def new_load(self):
        self.browser_errors.clear()
        self.failed_responses.clear()
        self.state_requests, self.state_ok, self.state_done, self.loads = {}, set(), {}, {}
        self.loader = None

    def monotonic_of(self, ticks):
        if ticks is None or self.mono_minus_ticks is None:
            return None
        return ticks + self.mono_minus_ticks

    @property
    def state_at(self):
        return self.monotonic_of(self.state_done.get(self.loader))

    @property
    def load_at(self):
        return self.monotonic_of(self.loads.get(self.loader))

    def is_state(self, url):
        u = urllib.parse.urlsplit(url)
        return u.path == "/api/state" and (self.origin is None or f"{u.scheme}://{u.netloc}" == self.origin)

    def take(self, m):
        method, params = m.get("method"), m.get("params", {})
        request_id = params.get("requestId")
        if e := erro_da_pagina(m):
            self.page_errors.append(e)
        elif method == "Log.entryAdded" and params["entry"].get("level") == "error":
            entry = params["entry"]
            self.browser_errors.append(f"{entry.get('text', '')} {entry.get('url', '')}".strip())
        elif method == "Network.requestWillBeSent":
            request = params.get("request", {})
            self.state_ok.discard(request_id)
            if request.get("method") == "GET" and self.is_state(request.get("url", "")):
                self.state_requests[request_id] = params.get("loaderId")
            else:
                self.state_requests.pop(request_id, None)
        elif method == "Network.responseReceived":
            response = params["response"]
            if response.get("status", 0) >= 400:
                self.failed_responses.append(f"{response['status']} {response.get('url', '')}")
            elif (200 <= response.get("status", 0) < 300 and request_id in self.state_requests
                  and self.is_state(response.get("url", ""))):
                self.state_ok.add(request_id)
        elif method == "Network.loadingFinished" and request_id in self.state_requests.keys() & self.state_ok:
            self.state_done.setdefault(self.state_requests[request_id], params.get("timestamp"))
            self.state_changed.set()
        elif method == "Page.lifecycleEvent" and params.get("name") == "load":
            self.loads.setdefault(params.get("loaderId"), params.get("timestamp"))


def diagnostic_js(conditions):
    parts = [*conditions,
             ("document.readyState", "document.readyState"), ("document.fonts.status", "document.fonts.status"),
             ("images not complete", "[...document.images].filter(i => !i.complete).map(i => i.src.slice(0, 120))"),
             ("scripts not loaded", "[...document.scripts].filter(s => s.src && "
                                    "!performance.getEntriesByName(s.src).length).map(s => s.src)")]
    body = ", ".join(f"{json.dumps(name)}: c(() => {js})" for name, js in parts)
    return ("(() => { const c = f => { try { return f(); } catch (e) { return 'error: ' + e.message; } }; "
            f"return {{{body}}}; }})()")


async def report_not_ready(cmd, label, outcome, conditions, events, timeout_s, shot=None):
    if outcome is Ready.CHROME_GONE:
        verdict = (f"{label}: the Chrome DevTools connection closed before the theme was ready: the browser went "
                   "away, so the theme was not judged")
    elif outcome is Ready.LEFT:
        verdict = f"{label}: the page tried to leave for another origin before it was ready"
    else:
        verdict = f"{label}: the theme was not ready in {timeout_s:.0f} s"
    print(f"{verdict}; what the page showed:", flush=True)
    if outcome is not Ready.CHROME_GONE:
        try:
            r = await cmd("Runtime.evaluate", expression=diagnostic_js(conditions), returnByValue=True)
            for name, value in (r.get("result", {}).get("value") or {}).items():
                print(f"  {name}: {json.dumps(value, ensure_ascii=False)}", flush=True)
        except (RuntimeError, TimeoutError, *CDP_GONE) as ex:
            print(f"  (the conditions did not come: {type(ex).__name__} {ex})", flush=True)
    for kind, found in (("console", events.page_errors), ("browser", events.browser_errors),
                        ("response", events.failed_responses)):
        for e in found or ["(none)"]:
            print(f"  {kind}: {e}", flush=True)
    if shot is not None and outcome is not Ready.CHROME_GONE:
        try:
            png = base64.b64decode((await cmd("Page.captureScreenshot", format="png"))["data"])
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(png)
            print(f"  print: {shot}", flush=True)
        except (RuntimeError, TimeoutError, KeyError, OSError, *CDP_GONE) as ex:
            print(f"  (the print did not come: {type(ex).__name__} {ex})", flush=True)
    return verdict


def conecta_cdp(ws_url):
    """The websocket to a tab of the headless Chrome. Without the keepalive ping: on a busy machine the pong came late,
    the library closed the connection with 1011 in the middle of a check, and the next command waited out its whole
    timeout. On the loopback, to a Chrome this process started, a keepalive has nothing to find."""
    return websockets.connect(ws_url, max_size=64 * 1024 * 1024, ping_interval=None)


async def le_cdp(ws, pend, evento):
    """Reads the CDP messages: the answer to a command goes to its future in pend (unless that command already gave
    up), every other message to evento(m). When the connection ends, the commands still waiting fail at once with the
    reason, instead of each one waiting out its timeout."""
    motivo = "closed"
    try:
        async for raw in ws:
            m = json.loads(raw)
            if m.get("id") in pend:
                f = pend.pop(m["id"])
                if not f.done():
                    f.set_result(m)
            else:
                evento(m)
    except Exception as ex:  # the connection closed, or a message that broke the reading
        motivo = str(ex) or type(ex).__name__
    for f in pend.values():
        if not f.done():
            f.set_exception(ConnectionError(f"the DevTools connection ended ({motivo})"))
    pend.clear()
    await ws.close()  # a command sent after this fails at once on the closed socket, instead of waiting its timeout


def fecha_chrome(chrome, prof):
    """Fecha o Chrome sem tela e apaga o perfil dele, que antes ficava no %TEMP% a cada rodada. Vai a arvore inteira (o
    taskkill /T): o kill so fecha o processo principal, e o chrome_crashpad_handler, filho dele, seguia segurando um
    arquivo do perfil."""
    subprocess.run(["taskkill", "/PID", str(chrome.pid), "/T", "/F"], capture_output=True)
    chrome.kill()  # sem o taskkill, ou se ele nao pegou
    chrome.wait()
    for _ in range(40):
        shutil.rmtree(prof, ignore_errors=True)
        if not os.path.exists(prof):
            return
        time.sleep(0.25)


# como conseguir a tela de boas-vindas: num PC com o Ritmelli, o --mock sem --data-dir copia a prateleira de quem usa
SEM_BOAS_VINDAS = ("ela so aparece com a prateleira vazia e nunca fechada (um --mock novo num PC sem o Ritmelli, ou "
                   "com um --data-dir novo e um library.json vazio: [])")


def _rota_boas_vindas(url):
    u = urllib.parse.urlsplit(url)
    return f"{u.scheme}://{u.netloc}/api/boas-vindas"


def boas_vindas_pendentes(url):
    """O servidor do url ainda mostraria a tela de boas-vindas (a prateleira vazia e ela nunca fechada)? None quando
    ele nao tem a rota ou esta fora do ar."""
    try:
        with so_mock.abre(_rota_boas_vindas(url), 5) as r:
            return bool(json.load(r).get("mostrar"))
    except (OSError, ValueError):
        return None


def fecha_boas_vindas(url):
    """Fecha a tela de boas-vindas pelo servidor, quando ele ainda a mostraria: o mesmo POST /api/boas-vindas do botao
    do fim dela (#126). Aberta, ela cobre a pagina inteira. O servidor guarda que ela foi vista (no --mock sem
    --data-dir, numa pasta temporaria). True se fechou; sem nada a fechar, ou sem a rota, False, e tudo segue."""
    if not boas_vindas_pendentes(url):
        return False
    so_mock.confere(url)  # o POST so a um --mock
    req = urllib.request.Request(_rota_boas_vindas(url), data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with so_mock.abre(req, 5):
            return True
    except OSError:
        return False


async def espera_boas_vindas(cmd):
    """Espera ate 5 s a tela de boas-vindas abrir na pagina (ela abre depois da carga, quando chega a resposta do GET
    dela). cmd: o comando do CDP de quem chama. True se abriu."""
    for _ in range(50):
        r = await cmd("Runtime.evaluate", expression="!!document.querySelector('#dlg-boas')?.open", returnByValue=True)
        if r.get("result", {}).get("value"):
            return True
        await asyncio.sleep(0.1)
    return False


def barra_outra_origem(ws, base, barrados):
    """O tratador do Fetch.requestPaused (so_mock.DOCUMENTOS): o documento de outra origem e barrado e anotado. Volta a
    funcao que recebe cada mensagem do CDP e diz se a tratou. As respostas vao com ids de outra faixa, que nenhum
    comando de quem chama usa."""
    ids, vivas = itertools.count(1 << 30), set()

    async def responde(params):
        metodo, p = so_mock.libera_ou_barra(params, base)
        if metodo == "Fetch.failRequest":
            barrados.append(params["request"]["url"])
        await ws.send(json.dumps({"id": next(ids), "method": metodo, "params": p}))

    def trata(m):
        if m.get("method") != "Fetch.requestPaused":
            return False
        t = asyncio.create_task(responde(m["params"]))
        vivas.add(t)  # o loop so guarda referencia fraca da tarefa
        t.add_done_callback(vivas.discard)
        return True
    return trata


def erro_da_pagina(m):
    """O texto do erro, se a mensagem do CDP e uma excecao sem tratamento ou um console.error da pagina; None se nao.
    Pede o Runtime.enable."""
    if m.get("method") == "Runtime.exceptionThrown":
        d = m["params"]["exceptionDetails"]
        return "excecao: " + (d.get("exception", {}).get("description") or d.get("text", ""))
    if m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] == "error":
        return "console.error: " + " ".join(str(x.get("value", x.get("description", ""))) for x in m["params"]["args"])
    return None


async def confere_pagina(cmd, url, barrados):
    """Antes de agir: a pagina na origem do url, nenhum documento barrado e o servidor ainda um --mock."""
    if barrados:
        raise so_mock.Recusa(f"a pagina tentou ir para outra origem ({barrados[0]}): barrada")
    r = await cmd("Runtime.evaluate", expression="location.origin", returnByValue=True)
    so_mock.confere_pagina(url, r.get("result", {}).get("value"))


async def run(a):
    try:
        base = so_mock.confere(a.url)  # antes de tudo: o POST das boas-vindas e a pagina so num --mock
    except so_mock.Recusa as ex:
        print(f"FALHA  {ex}")
        return 1
    if a.boas_vindas:
        pendente = boas_vindas_pendentes(a.url)
        if pendente is None:
            print(f"FALHA  o servidor nao respondeu em {_rota_boas_vindas(a.url)}")
            return 1
        if not pendente:
            print(f"FALHA  a tela de boas-vindas nao abre neste servidor: {SEM_BOAS_VINDAS}")
            return 1
    elif fecha_boas_vindas(a.url):
        print("(a tela de boas-vindas estava pendente: fechada pelo servidor, como o botao do fim dela)")
    port = free_port()
    prof = tempfile.mkdtemp(prefix="sbfit_")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}",
                               f"--user-data-dir={prof}", "--no-first-run",
                               "--no-default-browser-check", "--hide-scrollbars", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    falhas = 0
    try:
        ws_url = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                break
            except Exception:  # subindo
                time.sleep(0.1)
        async with conecta_cdp(ws_url) as ws:
            seq, pend, barrados, events = [0], {}, [], PageEvents()
            erros = events.page_errors
            fetch = barra_outra_origem(ws, base, barrados)

            def evento(m):
                if not fetch(m):
                    events.take(m)

            tarefa = asyncio.create_task(le_cdp(ws, pend, evento))

            async def cmd(method, **params):
                seq[0] += 1
                f = asyncio.get_running_loop().create_future()
                pend[seq[0]] = f
                await ws.send(json.dumps({"id": seq[0], "method": method, "params": params}))
                return (await asyncio.wait_for(f, 30)).get("result", {})

            for domain in DIAGNOSTIC_DOMAINS:
                await cmd(f"{domain}.enable")
            await cmd("Fetch.enable", patterns=so_mock.DOCUMENTOS)
            for sz in a.sizes.split(","):
                w, h = map(int, sz.split("x"))
                await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h,
                          deviceScaleFactor=1, mobile=w < 600)
                try:
                    so_mock.confere(a.url)  # antes de cada navegacao: a porta pode ter mudado de dono
                    erros.clear()
                    events.new_load()
                    ready = await navigate_and_wait(cmd, a.url, PRONTA, barrados, PRONTA_S)
                    if ready is not Ready.READY:
                        shot = Path(a.shots) / f"not-ready_{sz}.png" if a.shots else None
                        verdict = await report_not_ready(cmd, f"{sz:>10}", ready, READY_CONDITIONS, events, PRONTA_S,
                                                         shot)
                        falhas += 1
                        if ready is Ready.TIMED_OUT:
                            print(f"FALHA  {verdict}")
                            continue
                        print(f"FALHA  {verdict}; nothing more checked")
                        break
                    await confere_pagina(cmd, a.url, barrados)  # a page that left for another origin is refused here
                    await asyncio.sleep(a.wait)
                    await confere_pagina(cmd, a.url, barrados)
                    if a.js:
                        await cmd("Runtime.evaluate", expression=a.js)
                        await asyncio.sleep(max(a.wait, JS_WAIT_S))  # what the --js opens has no ready signal
                    if a.boas_vindas:  # se nao abrir, o PROBE diz "nenhuma janela aberta"
                        await espera_boas_vindas(cmd)
                    await confere_pagina(cmd, a.url, barrados)  # o --js e a espera podem ter levado a pagina embora
                except so_mock.Recusa as ex:
                    print(f"FALHA  {sz:>10}  {ex}; nada mais conferido")
                    falhas += 1
                    break
                r = await cmd("Runtime.evaluate", expression=f"{PROBE}({'true' if a.boas_vindas else 'false'})",
                              returnByValue=True)
                v = r.get("result", {}).get("value")
                if r.get("exceptionDetails") or not isinstance(v, dict):
                    d = r.get("exceptionDetails", {})
                    print(f"FALHA  {sz:>10}  the check did not run on the page: "
                          f"{d.get('exception', {}).get('description') or d.get('text') or r}"[:400])
                    falhas += 1
                    continue
                desk = w >= 900
                rola_v = v["sh"] > v["vh"] + 1
                rola_h = v["sw"] > v["vw"] + 1
                # a janela por cima nao rola com a pagina: o que nao se alcanca nela reprova em qualquer tamanho
                confere = desk or a.boas_vindas
                ok = not rola_h and (not rola_v or not desk) and (v["n"] == 0 or not confere) and not erros
                falhas += not ok
                msg = []
                if rola_v:
                    msg.append(f"pagina rola {v['sh'] - v['vh']} px na vertical"
                               + ("" if desk else " (ok no celular)"))
                if rola_h:
                    msg.append(f"pagina rola {v['sw'] - v['vw']} px de lado")
                if v["n"] and confere:
                    msg.append(f"{v['n']} controle(s) cortado(s): " + "; ".join(v["cortados"]))
                if erros:
                    msg.append(f"{len(erros)} erro(s) na pagina: " + "; ".join(e[:200] for e in erros[:3]))
                print(f"{'OK   ' if ok else 'FALHA'} {sz:>10}  " + (" | ".join(msg) or "cabe"))
                if a.shots:
                    os.makedirs(a.shots, exist_ok=True)
                    s = await cmd("Page.captureScreenshot", format="png")
                    with open(os.path.join(a.shots, f"fit_{sz}.png"), "wb") as f:
                        f.write(base64.b64decode(s["data"]))
            tarefa.cancel()
    finally:
        fecha_chrome(chrome, prof)
    return 1 if falhas else 0


# o --metricas: (o nome, o config.json do mock, se o aviso abre ao carregar, os botoes). Todo config leva
# boas_vindas: true, senao as boas-vindas abririam antes e o aviso so viria quando elas fechassem. O "ligar" e o
# Comecar a enviar do Microfone e fone, de quem esta desligado
SITUACOES = [
    ("decidir (ninguem escolheu)", {}, True, ("esc", "nao", "sim")),
    ("ligada no texto 1 (sem metricas_texto)", {"metricas": True}, True, ("esc", "nao", "sim")),
    ("ligada no texto 2", {"metricas": True, "metricas_texto": 2}, False, (None,)),
    ("desligada no texto 1", {"metricas": False}, False, ("ligar",)),
    ("desligada no texto 2", {"metricas": False, "metricas_texto": 2}, False, ("ligar",)),
]
BOTOES = {"esc": "o Esc", "nao": "o Nao enviar", "sim": "o Enviar", "ligar": "o Comecar a enviar do Microfone e fone"}
AVISO_ESPERA_S = 6.0
NOTICE_OPEN = "!!document.querySelector('#dlg-metricas')?.open"


def armadilha():
    """A rede presa: um HTTP_PROXY numa porta daqui, que o urllib, o yt-dlp e a ytmusicapi do servidor seguem (como no
    dev/testa_mock.py). Cada conexao vira uma tentativa anotada, e nenhuma chega a internet. Volta (o socket, as
    tentativas, as variaveis para o servidor)."""
    import socket
    import threading
    tentativas = []
    arm = socket.create_server(("127.0.0.1", 0))

    def atende():
        while True:
            try:
                c, _ = arm.accept()
            except OSError:
                return
            with c:
                try:
                    c.settimeout(2)
                    tentativas.append(c.recv(300).split(b"\r\n", 1)[0].decode("latin-1"))
                except OSError:
                    tentativas.append("?")
    threading.Thread(target=atende, daemon=True).start()
    proxy = f"http://127.0.0.1:{arm.getsockname()[1]}"
    return arm, tentativas, {"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "ALL_PROXY": proxy,
                             "NO_PROXY": "127.0.0.1,localhost"}


async def aviso_no_chrome(base, botao):
    """Opens the theme of the mock at base in a headless Chrome and waits for the #dlg-metricas. Open, it presses the
    button (esc, nao or sim); with "ligar", it presses the Comecar a enviar of Microfone e fone and, if the notice
    opens, its Enviar. Returns {"abriu", "ao_ligar" (the notice opened from Comecar a enviar), "foco" (the value or id
    of what had the focus in the notice), "fechou", "reabriu" (esc only: the page opened again shows the notice again),
    "erros", "not_ready" (the verdict when the page never got its state) and "load_to_state_s" (from the load event
    to the end of the page's GET /api/state)}."""
    url = f"{base}/t/ritmelli/?lang=pt_BR"
    port, prof = free_port(), tempfile.mkdtemp(prefix="sbfit_")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
                               "--no-first-run", "--no-default-browser-check", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r = {"abriu": False, "ao_ligar": None, "antes_do_enviar": None, "foco": None, "fechou": None, "reabriu": None,
         "erros": [], "not_ready": [], "load_to_state_s": None}
    try:
        ws_url = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                break
            except Exception:  # subindo
                time.sleep(0.1)
        async with conecta_cdp(ws_url) as ws:
            seq, pend, barrados, events = [0], {}, [], PageEvents(base)
            events.page_errors = r["erros"]
            fetch = barra_outra_origem(ws, base, barrados)

            def evento(m):
                if not fetch(m):
                    events.take(m)
            tarefa = asyncio.create_task(le_cdp(ws, pend, evento))

            async def cmd(method, **params):
                seq[0] += 1
                f = asyncio.get_running_loop().create_future()
                pend[seq[0]] = f
                await ws.send(json.dumps({"id": seq[0], "method": method, "params": params}))
                return (await asyncio.wait_for(f, 30)).get("result", {})

            async def js(expr):
                return (await cmd("Runtime.evaluate", expression=expr, returnByValue=True)).get("result", {}).get("value")

            async def load_and_wait_notice():
                so_mock.confere(url)
                events.new_load()
                try:
                    events.loader = (await cmd("Page.navigate", url=url)).get("loaderId")
                    ready = await wait_for_state(events, tarefa, PRONTA_S)
                except CDP_GONE:
                    ready = Ready.CHROME_GONE
                if ready is not Ready.READY:
                    r["not_ready"].append(await report_not_ready(cmd, "notice", ready, READY_CONDITIONS, events,
                                                                 PRONTA_S))
                    return False
                return await wait_notice(cmd, events.state_at + AVISO_ESPERA_S)

            foco = "(e => e && (e.value || e.id || e.tagName))(document.activeElement)"
            for domain in DIAGNOSTIC_DOMAINS:
                await cmd(f"{domain}.enable")
            await cmd("Page.setLifecycleEventsEnabled", enabled=True)
            await calibrate_clock(cmd, events)
            await cmd("Fetch.enable", patterns=so_mock.DOCUMENTOS)
            r["abriu"] = await load_and_wait_notice()
            if events.load_at is not None and events.state_at is not None:
                r["load_to_state_s"] = events.state_at - events.load_at
            if r["not_ready"]:
                tarefa.cancel()
                return r
            await confere_pagina(cmd, url, barrados)
            if botao == "ligar" and not r["abriu"]:
                # o Microfone e fone aberto pelo botao dele, e o Comecar a enviar da linha dos dados de uso
                await js("document.querySelector('#b-disp').click()")
                for _ in range(50):
                    if await js("document.querySelector('#dlg-disp').open && !document.querySelector('#dd-met').hidden"):
                        break
                    await asyncio.sleep(0.1)
                await js("document.querySelector('#dd-met-btn').click()")
                r["ao_ligar"] = await wait_notice(cmd, time.monotonic() + 3.0)
                if r["ao_ligar"]:
                    r["foco"] = await js(foco)
                    # com o aviso na tela, nada foi gravado ainda: a escolha sai do Enviar dele
                    r["antes_do_enviar"] = (await cmd("Runtime.evaluate", awaitPromise=True, returnByValue=True,
                                                      expression="fetch('/api/metricas').then(r => r.json())")
                                            ).get("result", {}).get("value")
                    await js("document.querySelector('#dlg-metricas button[value=sim]').click()")
                # o POST sai do close do aviso: o Chrome fica ate a linha do Microfone e fone mostrar a escolha nova
                for _ in range(50):
                    if await js("!document.querySelector('#dlg-metricas').open && "
                                "document.querySelector('#dd-met-btn').dataset.ligar === '0'"):
                        break
                    await asyncio.sleep(0.1)
            elif r["abriu"] and botao:
                r["foco"] = await js(foco)
                if botao == "esc":
                    for tipo in ("keyDown", "keyUp"):
                        await cmd("Input.dispatchKeyEvent", type=tipo, key="Escape", code="Escape",
                                  windowsVirtualKeyCode=27, nativeVirtualKeyCode=27)
                else:
                    await js(f"document.querySelector('#dlg-metricas button[value={botao}]').click()")
                await asyncio.sleep(1.0)
                r["fechou"] = not await js("document.querySelector('#dlg-metricas').open")
                if botao == "esc":  # o Esc nao escolhe: na proxima abertura, o aviso de novo
                    r["reabriu"] = await load_and_wait_notice()
            tarefa.cancel()
    finally:
        fecha_chrome(chrome, prof)
    return r


def _sobe_e(tmp, config, env, faz):
    """Sobe um --mock --metricas-teste com o config.json dado (pelo sobe_servidor do compara), roda faz(srv), encerra
    pelo para_servidor e volta (o que faz voltou, o config.json gravado, o log do servidor)."""
    import compara  # numpy, pillow: so no --metricas
    with open(tmp / "servidor.log", "w", encoding="utf-8") as log:
        srv = compara.sobe_servidor(tmp, free_port(), log, config=config, extras=["--metricas-teste"], env=env)
        try:
            r = faz(srv)
            gravado = json.loads((tmp / "dados" / "config.json").read_text(encoding="utf-8"))
        finally:
            compara.para_servidor(srv)
    return r, gravado, (tmp / "servidor.log").read_text(encoding="utf-8", errors="replace")


def cenario_metricas():
    """O --metricas: o aviso dos dados de uso no tema, contra um --mock --metricas-teste por situacao e por botao (pelo
    sobe_servidor do dev/compara.py, com as recusas do dev/so_mock.py), com a rede presa numa armadilha. Abre com
    decidir e com ligada no texto 1 (com o foco no Enviar), nao abre com ligada no texto 2 nem com desligada; o Esc
    nao grava nada e o aviso volta na proxima abertura, o Nao enviar grava metricas: false e o Enviar metricas: true,
    os dois com o metricas_texto 2; o Comecar a enviar de quem desligou no texto 1 abre o aviso antes de ligar, e no
    texto 2 liga direto. Nenhum pedido sai pela rede, e o servidor diz no log quantos eventos guardou na memoria (pelo
    menos um quando a pessoa liga). Num mock a parte, no fim, uma busca (o que a pessoa pede vai ao YouTube) tem de
    cair na armadilha: e ela que mostra que a armadilha pega."""
    import re
    from pathlib import Path
    arm, tentativas, env = armadilha()
    falhas = 0

    def diz(ok, msg):
        nonlocal falhas
        falhas += not ok
        print(f"{'OK   ' if ok else 'FALHA'} {msg}", flush=True)

    def le_config(tmp, liga):
        """O POST da escolha, gravado sob a trava do cfg: espera ate 5 s pela escolha (liga) no texto 2 e, ao ligar,
        pelo "dia" no metricas.json, que o vigia grava depois de por o "ativo" na fila (o evento que o log conta)."""
        for _ in range(50):
            try:
                g = json.loads((tmp / "dados" / "config.json").read_text(encoding="utf-8"))
                if g.get("metricas") is liga and g.get("metricas_texto") == 2:
                    if not liga or json.loads((tmp / "dados" / "metricas.json").read_text(encoding="utf-8")).get("dia"):
                        break
            except (OSError, ValueError):
                pass  # o arquivo no meio da troca (save_json), ou o metricas.json ainda por gravar
            time.sleep(0.1)

    try:
        for nome, cfg, abre, botoes in SITUACOES:
            for botao in botoes:
                inicial = {"boas_vindas": True, **cfg}
                tmp = Path(tempfile.mkdtemp(prefix="ritmelli-metricas-"))
                liga = botao in ("sim", "ligar")

                def faz(srv, botao=botao, tmp=tmp, liga=liga):
                    r = asyncio.run(aviso_no_chrome(srv.base, botao))
                    if botao in ("nao", "sim", "ligar"):
                        le_config(tmp, liga)
                    return r
                try:
                    r, gravado, saida = _sobe_e(tmp, inicial, env, faz)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
                o_que = f"{nome}{', ' + BOTOES[botao] if botao else ''}"
                diz(r["abriu"] == abre, f"{o_que}: o aviso {'abre' if r['abriu'] else 'nao abre'} ao carregar")
                diz(not r["erros"], f"{o_que}: sem erro na pagina ({r['erros'][:2]})")
                diz(not r["not_ready"], f"{o_que}: the page got ready before the wait for the notice ({r['not_ready']})")
                if botao == "ligar":
                    texto2 = cfg.get("metricas_texto") == 2
                    diz(r["ao_ligar"] is (not texto2),
                        f"{o_que}: {'liga direto' if texto2 else 'o aviso abre antes de ligar, com o foco no Enviar'}"
                        f" ({r['ao_ligar']}, foco {r['foco']})")
                    if not texto2:
                        diz(r["foco"] == "sim", f"{o_que}: o foco no Enviar do aviso ({r['foco']})")
                        a = r["antes_do_enviar"] or {}
                        diz((a.get("situacao"), a.get("texto")) == ("desligada", 1),
                            f"{o_que}: com o aviso na tela, nada gravado ainda ({a.get('situacao')}, texto "
                            f"{a.get('texto')})")
                elif botao and r["abriu"]:
                    if cfg.get("metricas") is True:
                        diz(r["foco"] == "sim", f"{o_que}: para quem ja enviava, o foco no Enviar ({r['foco']})")
                    diz(r["fechou"], f"{o_que}: o aviso fecha")
                    if botao == "esc":
                        diz(gravado == inicial and r["reabriu"],
                            f"{o_que}: nada gravado ({gravado}), e o aviso volta na proxima abertura ({r['reabriu']})")
                if botao in ("nao", "sim", "ligar"):
                    quer = {**inicial, "metricas": liga, "metricas_texto": 2}
                    diz({k: gravado.get(k) for k in quer} == quer,
                        f"{o_que}: grava metricas {liga} e o metricas_texto 2 ({gravado})")
                guardou = [linha for linha in saida.splitlines() if linha.startswith("metrics test:")]
                n = int(re.search(r"(\d+) event", guardou[0]).group(1)) if len(guardou) == 1 else -1
                diz(n >= (1 if liga else 0) and "nothing sent" in (guardou or [""])[0],
                    f"{o_que}: o servidor guardou na memoria{' (ao ligar, ao menos um evento)' if liga else ''} "
                    f"({guardou[:1] or 'sem a linha no log'})")
        sozinho = list(tentativas)
        diz(not sozinho, f"nenhum pedido saiu pela rede, de nenhum dos servidores ({sozinho[:3]})")
        # o controle, num mock a parte: a busca que a pessoa pede vai ao YouTube, e tem de cair na armadilha
        tmp = Path(tempfile.mkdtemp(prefix="ritmelli-metricas-"))

        def busca(srv):
            try:
                srv.api("GET", "/api/search?q=teste&n=1", espera=20)
            except OSError:
                pass  # a armadilha fecha a conexao: o que conta e ter tentado
            for _ in range(100):
                if len(tentativas) > len(sozinho):
                    break
                time.sleep(0.1)
        try:
            _sobe_e(tmp, {"boas_vindas": True}, env, busca)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        diz(len(tentativas) > len(sozinho),
            f"a busca que a pessoa pede cai na armadilha: ela pega ({tentativas[len(sozinho):][:1]})")
    except so_mock.Recusa as ex:
        diz(False, f"o cenario parou: {ex}")
    finally:
        arm.close()
    return 1 if falhas else 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="o tema num --mock (sem ele, so com o --metricas)")
    ap.add_argument("--metricas", action="store_true",
                    help="o aviso dos dados de uso: sobe os proprios --mock --metricas-teste, um por situacao e botao")
    ap.add_argument("--sizes", default=SIZES)
    ap.add_argument("--wait", type=float, default=0.5,
                    help="seconds after the page is ready (and at least 1.5 after the --js)")
    ap.add_argument("--shots", help="pasta para salvar um print por tamanho")
    ap.add_argument("--js", help="JS que roda depois da carga, antes da conferencia")
    ap.add_argument("--boas-vindas", action="store_true",
                    help="confere a tela de boas-vindas em vez da pagina (com a prateleira vazia e ela nunca fechada)")
    a = ap.parse_args()
    if a.metricas:
        sys.exit(cenario_metricas())
    if not a.url:
        ap.error("falta o url do tema (ou o --metricas)")
    sys.exit(asyncio.run(run(a)))


if __name__ == "__main__":
    main()
