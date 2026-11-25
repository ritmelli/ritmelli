"""Confere se um tema cabe na tela em varios tamanhos (regra: se adequar a qualquer tela).

    python dev/fitcheck.py http://127.0.0.1:8806/t/ritmelli/ [--sizes 1366x657,1920x1080]
        [--shots <pasta>] [--js "document.querySelector('#mini-seta').click()"] [--boas-vindas]

O --js roda depois da carga, antes da conferencia (abrir uma pagina ou um painel e conferir ela tambem).

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

import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import so_mock  # noqa: E402
from so_mock import free_port  # noqa: E402,F401 - o compara, o perfcheck e o texturas pegam daqui

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
            except Exception:  # noqa: BLE001 - subindo
                time.sleep(0.1)
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            seq, pend, barrados = [0], {}, []
            fetch = barra_outra_origem(ws, base, barrados)

            async def leitor():
                async for raw in ws:
                    m = json.loads(raw)
                    if m.get("id") in pend:
                        pend.pop(m["id"]).set_result(m)
                    else:
                        fetch(m)

            tarefa = asyncio.create_task(leitor())

            async def cmd(method, **params):
                seq[0] += 1
                f = asyncio.get_running_loop().create_future()
                pend[seq[0]] = f
                await ws.send(json.dumps({"id": seq[0], "method": method, "params": params}))
                return (await asyncio.wait_for(f, 30)).get("result", {})

            await cmd("Page.enable")
            await cmd("Fetch.enable", patterns=so_mock.DOCUMENTOS)
            for sz in a.sizes.split(","):
                w, h = map(int, sz.split("x"))
                await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h,
                          deviceScaleFactor=1, mobile=w < 600)
                await cmd("Page.navigate", url=a.url)
                await asyncio.sleep(a.wait)
                try:
                    await confere_pagina(cmd, a.url, barrados)
                    if a.js:
                        await cmd("Runtime.evaluate", expression=a.js)
                        await asyncio.sleep(a.wait)
                        await confere_pagina(cmd, a.url, barrados)  # o --js pode ter levado a pagina embora
                except so_mock.Recusa as ex:
                    print(f"FALHA  {sz:>10}  {ex}; nada mais conferido")
                    falhas += 1
                    break
                if a.boas_vindas:  # se nao abrir, o PROBE diz "nenhuma janela aberta"
                    await espera_boas_vindas(cmd)
                r = await cmd("Runtime.evaluate", expression=f"{PROBE}({'true' if a.boas_vindas else 'false'})",
                              returnByValue=True)
                v = r["result"]["value"]
                desk = w >= 900
                rola_v = v["sh"] > v["vh"] + 1
                rola_h = v["sw"] > v["vw"] + 1
                # a janela por cima nao rola com a pagina: o que nao se alcanca nela reprova em qualquer tamanho
                confere = desk or a.boas_vindas
                ok = not rola_h and (not rola_v or not desk) and (v["n"] == 0 or not confere)
                falhas += not ok
                msg = []
                if rola_v:
                    msg.append(f"pagina rola {v['sh'] - v['vh']} px na vertical"
                               + ("" if desk else " (ok no celular)"))
                if rola_h:
                    msg.append(f"pagina rola {v['sw'] - v['vw']} px de lado")
                if v["n"] and confere:
                    msg.append(f"{v['n']} controle(s) cortado(s): " + "; ".join(v["cortados"]))
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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--sizes", default=SIZES)
    ap.add_argument("--wait", type=float, default=1.5)
    ap.add_argument("--shots", help="pasta para salvar um print por tamanho")
    ap.add_argument("--js", help="JS que roda depois da carga, antes da conferencia")
    ap.add_argument("--boas-vindas", action="store_true",
                    help="confere a tela de boas-vindas em vez da pagina (com a prateleira vazia e ela nunca fechada)")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
