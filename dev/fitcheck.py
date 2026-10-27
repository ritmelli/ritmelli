"""Confere se um tema cabe na tela em varios tamanhos (regra: se adequar a qualquer tela).

    python dev/fitcheck.py http://127.0.0.1:8806/t/vitrola/ [--sizes 1366x657,1920x1080]
        [--shots <pasta>]

Regra por tamanho:
- tela de computador (largura >= 900): a pagina nao rola, nem na vertical nem na
  horizontal; o que nao cabe rola por dentro de um painel (lista, prateleira);
- celular e tablet em pe (largura < 900): rola so na vertical, nunca de lado.
Alem disso confere cada controle (botao, link, campo, slider) fora de painel que rola:
o centro dele tem que estar na tela e ser dele mesmo, nao recortado por um pai com
overflow hidden nem coberto por outra camada (o controle existe, mas ninguem alcanca).
Sai 1 se algum tamanho reprovar.
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
SIZES = ("1024x600,1280x650,1280x720,1366x657,1366x768,1436x765,1440x900,1536x730,"
         "1600x900,1920x960,1920x1080,2560x1300,1180x820,390x844,360x780,768x1024")

PROBE = r"""(() => {
  const vw = innerWidth, vh = innerHeight, d = document.documentElement;
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
  for (const el of document.querySelectorAll('button, a[href], input, select, textarea, [role=slider], [role=button], [tabindex]:not([tabindex="-1"])')) {
    if (el.closest('dialog, [hidden], [inert], .so-leitor, .sr-only, .visually-hidden')) continue;
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
})()"""


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


async def run(a):
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
            seq = [0]

            async def cmd(method, **params):
                seq[0] += 1
                my = seq[0]
                await ws.send(json.dumps({"id": my, "method": method, "params": params}))
                while True:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 30))
                    if m.get("id") == my:
                        return m.get("result", {})

            await cmd("Page.enable")
            for sz in a.sizes.split(","):
                w, h = map(int, sz.split("x"))
                await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h,
                          deviceScaleFactor=1, mobile=w < 600)
                await cmd("Page.navigate", url=a.url)
                await asyncio.sleep(a.wait)
                r = await cmd("Runtime.evaluate", expression=PROBE, returnByValue=True)
                v = r["result"]["value"]
                desk = w >= 900
                rola_v = v["sh"] > v["vh"] + 1
                rola_h = v["sw"] > v["vw"] + 1
                ok = not rola_h and (not rola_v or not desk) and (v["n"] == 0 or not desk)
                falhas += not ok
                msg = []
                if rola_v:
                    msg.append(f"pagina rola {v['sh'] - v['vh']} px na vertical"
                               + ("" if desk else " (ok no celular)"))
                if rola_h:
                    msg.append(f"pagina rola {v['sw'] - v['vw']} px de lado")
                if v["n"] and desk:
                    msg.append(f"{v['n']} controle(s) cortado(s): " + "; ".join(v["cortados"]))
                print(f"{'OK   ' if ok else 'FALHA'} {sz:>10}  " + (" | ".join(msg) or "cabe"))
                if a.shots:
                    os.makedirs(a.shots, exist_ok=True)
                    s = await cmd("Page.captureScreenshot", format="png")
                    with open(os.path.join(a.shots, f"fit_{sz}.png"), "wb") as f:
                        f.write(base64.b64decode(s["data"]))
    finally:
        chrome.kill()
        chrome.wait()
    return 1 if falhas else 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--sizes", default=SIZES)
    ap.add_argument("--wait", type=float, default=1.5)
    ap.add_argument("--shots", help="pasta para salvar um print por tamanho")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
