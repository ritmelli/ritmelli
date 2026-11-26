"""Mede ao vivo o atraso da voz com efeito no microfone do jogo, como o app roda: o efeito no filtro (issue #63) contra
o caminho de antes, a voz indo ao app e voltando (issue #79).

    python dev/mede_voz_ao_vivo.py "CABLE Output" "CABLE Input" > medida.txt 2>&1
    python dev/mede_voz_ao_vivo.py --analisa captura.npz

Bancada: um microfone virtual com o filtro. No VB-Cable, o que toca no CABLE Input sai no CABLE Output, e o filtro roda
no CABLE Output como em qualquer microfone. O script toca estalos no lado de saida e grava o microfone, que e o que o
jogo ouviria. O motor (MockEngine com o Injetor de verdade, na prioridade e na thread de audio do app) roda num processo
so dele, com o alvo do anel nesse microfone e o microfone aberto, como o app.

Depois de uma fase de aquecimento (descartada: o motor recem-aberto assenta), rodadas na mesma gravacao, cada uma com
tres fases de uns estalos: sem efeito, o efeito no filtro e o efeito pelo app (o preset fica de fora e a voz faz a
ida e volta de antes); uma fase sem efeito fecha a ultima. O atraso a mais de cada fase e o do som seco do estalo (o
Eco, padrao, nao atrasa o seco: a repeticao vem 280 ms depois, fora da janela) contra a media das duas fases sem
efeito em volta da rodada. A medida e o piso (o menor atraso dos estalos da fase); a mediana vai junto. O cabo virtual
entrega em ciclos, e conforme o ponto do ciclo em que o estalo cai ele chega uns 20 ms mais tarde: a mediana pula com
isso (o intervalo entre estalos nao e multiplo de 10 ms, para cada fase passar pelo ciclo todo), o piso nao. A rodada
em que o piso das duas fases sem efeito nao bate, ou em que o motor nao estava no estado da fase, nao conta. Sai 1
com menos de duas rodadas que contam.

Com a saida redirecionada (o exemplo acima), o script e o motor se soltam do console, como o executavel e o pythonw:
preso a um console, o Python pergunta ao conhost a cada thread nova e a cada io.open, e com a CPU cheia isso prende o
interpretador de 10 a 25 ms (paradas que o app nao tem; dev/mede_folga.py). --console mantem os dois no console, para
comparar. A conta so roda depois de fechar a gravacao (conta pesada no meio faz a captura perder blocos); a captura
fica num .npz ao lado do .json, e --analisa refaz a conta dele.

Toca de verdade no microfone escolhido: quem estiver ouvindo ele (uma call, um jogo) ouve os estalos. Para sem tocar
nada num microfone sem o filtro pronto. E manual, para um Windows de teste: com o Ritmelli ligado (a porta 8799
aceitando conexao), sai com erro antes de abrir o anel (dev/so_mock.py); o --analisa, que so refaz a conta de uma
captura guardada, fica livre.
"""
import argparse
import ctypes
import faulthandler
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(AQUI))
import so_mock

SR = 48000
ESTALOS = 10           # por fase
RODADAS = 3
INTERVALO = 72047      # ~1,5 s entre estalos (o Eco acaba antes do proximo), fora do passo de 10 ms do cabo
ESTALO = 0.5
LIMIAR = 0.15          # o seco do estalo passa disso; o ruido e a cauda nao
JANELA_S = 0.4         # chegada mais de 0,4 s depois da saida nao e o seco deste estalo
TOLERANCIA_MS = 5.0    # o piso das duas fases sem efeito em volta de uma rodada
DETACHED_PROCESS = 0x00000008  # o motor nasce sem console nenhum (o CREATE_NO_WINDOW ainda cria um conhost)
FASES = [("aquecimento", "nenhum")] + [(f"{nome} ({r + 1})", c) for r in range(RODADAS)
         for nome, c in (("sem efeito", "nenhum"), ("efeito no filtro", "filtro"), ("efeito pelo app", "app"))]
FASES.append((f"sem efeito ({RODADAS + 1})", "nenhum"))
# o estado do motor em cada fase: (efeito_no_filtro, voz_pelo_app)
ESTADO = {"nenhum": (False, False), "filtro": (True, False), "app": (False, True)}


def _espera(cond, s):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < s:
        time.sleep(0.01)
    return cond()


def motor(a):
    """O processo do motor, comandado pela entrada (nenhum | filtro | app | estado | sair); responde 'ok {estado}' com a
    fase no lugar (estado so responde)."""
    import sounddevice as sd

    import engine as eng
    from microfone import injeta, preset

    eng._processo_acima()  # a prioridade do app
    pede, projeta = preset.pede, preset.preset
    e = eng.MockEngine("", "")
    e.monitor_on = False
    e._alvo = injeta.hash_microfone(a.guid)
    abertos = []
    if not a.sem_microfone:  # o app deixa o microfone aberto (o filtro fica vivo mesmo com o jogo fechado)
        i, d = eng.find_dev(a.mic, "in")
        s = sd.InputStream(device=i, channels=d["max_input_channels"], samplerate=eng.SR, blocksize=eng.BLOCK,
                           dtype="float32", extra_settings=eng.WASAPI, callback=e._mic_cb)
        s.start()
        abertos.append(s)
    inj = e._injetor = eng.Injetor(e)
    if not _espera(lambda: inj.m is not None and inj.leitores > 0, 10.0):
        print("erro: sem o anel do filtro, ou sem leitor no microfone alvo", flush=True)
        return 1
    def responde():
        print("ok " + json.dumps({"efeito_no_filtro": inj.efeito_no_filtro, "voz_pelo_app": e.voz_pelo_app(),
                                  "leitores": inj.leitores, "secas": inj.secas,
                                  "volta_max_ms": round(inj.volta_max * 1000, 1)}), flush=True)

    print("pronto", flush=True)
    for linha in sys.stdin:
        cmd = linha.strip()
        if cmd == "sair":
            break
        if cmd == "estado":
            responde()
            continue
        if cmd == "app":  # nenhum efeito tem preset: a voz vai ao app e volta, o caminho de antes
            preset.pede = preset.preset = lambda *_: None
        else:
            preset.pede, preset.preset = pede, projeta
        e.set_effect("nenhum")
        time.sleep(0.15)
        if cmd != "nenhum":
            e.set_effect(a.efeito)
            _espera(lambda: (inj.efeito_no_filtro, e.voz_pelo_app()) == ESTADO[cmd], 3.0)
        time.sleep(0.3)
        responde()
    preset.pede, preset.preset = pede, projeta
    e.set_effect("nenhum")
    inj.para()
    for s in abertos:
        s.close()
    print("fim", flush=True)
    return 0


def mede(a):
    """Toca e grava as fases, com o motor noutro processo; so depois de fechar tudo guarda a captura e faz a conta."""
    import sounddevice as sd

    import engine as eng

    i_mic, d_mic = eng.find_dev(a.mic, "in")
    i_toca = eng.find_dev(a.toca, "out")[0]
    st = eng._do_microfone(d_mic["name"])
    if not (st and st["filtro"] and st["melhorias"]):
        print(f'"{d_mic["name"]}" sem o filtro pronto (instalado e com as melhorias de audio ligadas): nada tocou')
        return 2
    saida = Path(a.saida)
    solto = not a.console and not sys.stdout.isatty() and not sys.stderr.isatty()
    if solto:
        ctypes.windll.kernel32.FreeConsole()  # sem console, como o executavel: a saida ja vai para arquivo ou cano
    print(f"microfone {d_mic['name']} (guid {st['guid']}), toca em {sd.query_devices(i_toca)['name']}, "
          f"efeito {a.efeito}, {'sem console' if solto else 'com console'}", flush=True)
    # a medida nunca fica presa: passou muito do tempo, a pilha de cada thread vai pro log e o processo sai
    faulthandler.dump_traceback_later(len(FASES) * (ESTALOS * INTERVALO / SR + 3) + 90, exit=True)

    cap, t_cap, t_out = [], [], []
    fila, n_out, trava = [np.zeros(0, np.float32)], [0], threading.Lock()

    def grava(x, n, t, status):
        cap.append(x[:, 0].copy())
        t_cap.append((t.inputBufferAdcTime, time.perf_counter()))

    def toca(out, n, t, status):
        with trava:
            m = min(n, len(fila[0]))
            out[:m] = fila[0][:m, None]
            out[m:] = 0
            fila[0] = fila[0][m:]
            t_out.append((n_out[0], t.outputBufferDacTime, time.perf_counter()))
            n_out[0] += n

    canais = min(2, d_mic["max_input_channels"])
    ent = sd.InputStream(device=i_mic, samplerate=SR, channels=canais, dtype="float32", latency="high", callback=grava)
    sai = sd.OutputStream(device=i_toca, samplerate=SR, channels=2, dtype="float32", latency="high", callback=toca)
    ent.start()
    sai.start()
    time.sleep(0.5)
    cmd = [sys.executable, "-u", str(Path(__file__).resolve()), a.mic, "--papel", "motor", "--guid", st["guid"],
           "--efeito", a.efeito] + (["--sem-microfone"] if a.sem_microfone else [])
    with open(saida.with_suffix(".motor.log"), "w", encoding="utf-8") as log_motor:
        ctl = subprocess.Popen(cmd, cwd=RAIZ, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log_motor,
                               text=True, encoding="utf-8", creationflags=DETACHED_PROCESS if solto else 0)
        linhas = queue.Queue()  # o motor responde por aqui; esperar sem limite prendia a medida quando ele travava
        threading.Thread(target=lambda: [linhas.put(x.strip()) for x in ctl.stdout], daemon=True).start()

        def resposta(s=15.0):
            try:
                return linhas.get(timeout=s)
            except queue.Empty:
                return ""

        linha = resposta(20.0)
        if linha != "pronto":
            ctl.kill()
            fecha(sai, ent)
            print(f"o motor nao subiu: {linha or 'sem resposta'} (ver {saida.with_suffix('.motor.log')})")
            return 2
        time.sleep(0.5)
        estalos = np.zeros(ESTALOS * INTERVALO, np.float32)
        picos = np.arange(ESTALOS) * INTERVALO + INTERVALO // 2
        estalos[picos] = ESTALO
        fases = []
        falha = None
        for nome, c in FASES:
            ctl.stdin.write(c + "\n")
            ctl.stdin.flush()
            resp = resposta()
            if not resp.startswith("ok "):
                falha = f"{nome}: o motor nao respondeu a fase ({resp or 'nada em 15 s'})"
                break
            with trava:
                ini = n_out[0] + len(fila[0])
                fila[0] = np.concatenate([fila[0], estalos])
            limite = time.monotonic() + len(estalos) / SR + 10.0
            while time.monotonic() < limite:
                with trava:
                    if not len(fila[0]):
                        break
                time.sleep(0.05)
            else:
                falha = f"{nome}: a saida parou de tocar os estalos"
                break
            time.sleep(0.5)
            ctl.stdin.write("estado\n")
            ctl.stdin.flush()
            fim = resposta()
            fases.append({"nome": nome, "cmd": c, "ini": int(ini), "motor": resp, "motor_fim": fim})
            secas = json.loads(fim[3:]).get("secas") if fim.startswith("ok ") else "?"
            print(f"{nome}: feita, secas ate aqui {secas}", flush=True)
        try:
            ctl.stdin.write("sair\n")
            ctl.stdin.flush()
            ctl.wait(timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            ctl.kill()
        if falha:
            fecha(sai, ent)
            print(f"parou: {falha} (ver {saida.with_suffix('.motor.log')})", flush=True)
            return 2
    fecha(sai, ent)
    faulthandler.cancel_dump_traceback_later()

    tamanhos = np.array([len(x) for x in cap])
    np.savez(saida.with_suffix(".npz"), cap=np.concatenate(cap), tamanhos=tamanhos, t_cap=np.array(t_cap),
             t_out=np.array(t_out), picos=picos, fases=json.dumps(fases), efeito=a.efeito, solto=solto)
    return conta(saida.with_suffix(".npz"), saida)


def fecha(*streams):
    """Para as pontas sem esperar o que falta no buffer (o close de um stream que ainda toca pode demorar)."""
    for st in streams:
        try:
            st.abort()
            st.close()
        except Exception as ex:  # fechando: o erro vai pro log e a conta segue
            print(f"fechando {st}: {ex}", flush=True)


def conta(npz, saida):
    """O atraso de cada estalo, pelo relogio de cada bloco (a hora em que saiu, pelo DAC, e a hora em que chegou, pelo
    ADC), sem depender de a gravacao ser continua."""
    with np.load(npz) as d:  # cada d[...] le o arquivo de novo: tudo sai daqui uma vez so
        d = {k: d[k] for k in d.files}
    fases, picos = json.loads(str(d["fases"])), d["picos"]
    t_out, t_cap, cap = d["t_out"], d["t_cap"], d["cap"]
    pa = bool(t_out[0][1])  # o PortAudio da a hora do DAC/ADC; sem ela, o perf_counter da chamada
    usa_out, usa_cap = (1, 0) if pa else (2, 1)
    chegadas = []
    for ini, n, tc in zip(np.concatenate([[0], np.cumsum(d["tamanhos"])[:-1]]), d["tamanhos"], t_cap):
        j = np.flatnonzero(np.abs(cap[ini:ini + n]) > LIMIAR)
        if len(j):
            chegadas.append(tc[usa_cap] + j[0] / SR)
    chegadas = np.array(sorted(chegadas))

    def hora_saida(idx):
        k = np.searchsorted(t_out[:, 0], idx, side="right") - 1
        return t_out[k][usa_out] + (idx - t_out[k][0]) / SR

    res = {"efeito": str(d["efeito"]), "sem_console": bool(d["solto"]), "relogio": "PortAudio" if pa else "perf_counter",
           "fases": [], "rodadas": []}
    for f in fases:
        lag = []
        for k in picos:
            h = hora_saida(f["ini"] + k)
            j = np.flatnonzero(chegadas >= h - 0.002)
            ok = len(j) and chegadas[j[0]] - h < JANELA_S
            lag.append(round(float(chegadas[j[0]] - h) * 1000, 1) if ok else None)
        vale = [v for v in lag if v is not None]
        estado = json.loads(f["motor"][3:]) if f["motor"].startswith("ok ") else {}
        fim = f.get("motor_fim", "")
        secas_fim = json.loads(fim[3:]).get("secas") if fim.startswith("ok ") else None
        conta_bem = len(vale) >= len(picos) // 2
        res["fases"].append({"nome": f["nome"], "cmd": f["cmd"], "motor": estado, "chegada_ms": lag,
                             "secas": (secas_fim - estado["secas"]) if secas_fim is not None and "secas" in estado
                             else None,
                             "mediana_ms": float(np.median(vale)) if conta_bem else None,
                             "piso_ms": float(np.min(vale)) if conta_bem else None,
                             "no_estado": (estado.get("efeito_no_filtro"), estado.get("voz_pelo_app")) ==
                             ESTADO[f["cmd"]]})
    fs = res["fases"]
    for r in range(1, len(fs) - 1, 3):  # a fase 0 e o aquecimento
        s0, fil, app, s1 = fs[r], fs[r + 1], fs[r + 2], fs[r + 3]
        rod = {"rodada": r // 3 + 1}
        pisos = [s0["piso_ms"], fil["piso_ms"], app["piso_ms"], s1["piso_ms"]]
        meds = [s0["mediana_ms"], fil["mediana_ms"], app["mediana_ms"], s1["mediana_ms"]]
        if None in meds:
            rod["nao_conta"] = "estalos demais se perderam"
        elif not all(f["no_estado"] for f in (s0, fil, app, s1)):
            rod["nao_conta"] = "o motor nao estava no estado de alguma fase"
        elif abs(pisos[3] - pisos[0]) > TOLERANCIA_MS:
            rod["nao_conta"] = f"o piso sem efeito pulou {pisos[3] - pisos[0]:+.1f} ms em volta da rodada"
        else:
            base, piso = (meds[0] + meds[3]) / 2, (pisos[0] + pisos[3]) / 2
            rod.update(base_ms=round(piso, 1), filtro_piso_ms=round(pisos[1] - piso, 1),
                       app_piso_ms=round(pisos[2] - piso, 1), filtro_ms=round(meds[1] - base, 1),
                       app_ms=round(meds[2] - base, 1))
        res["rodadas"].append(rod)
    contam = [r for r in res["rodadas"] if "nao_conta" not in r]
    res["vale"] = len(contam) >= 2
    if contam:
        res["filtro_a_mais_ms"] = round(float(np.median([r["filtro_ms"] for r in contam])), 1)
        res["app_a_mais_ms"] = round(float(np.median([r["app_ms"] for r in contam])), 1)
        res["filtro_piso_ms"] = round(float(np.median([r["filtro_piso_ms"] for r in contam])), 1)
        res["app_piso_ms"] = round(float(np.median([r["app_piso_ms"] for r in contam])), 1)
    Path(saida).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"efeito {res['efeito']}, {'sem' if res['sem_console'] else 'com'} console, relogio {res['relogio']}")
    for f in fs:
        print(f"{f['nome']}: piso {f['piso_ms']} ms, mediana {f['mediana_ms']} ms, secas {f['secas']}"
              f"{'' if f['no_estado'] else ' (MOTOR FORA DO ESTADO)'} | {f['chegada_ms']}")
    for r in res["rodadas"]:
        print(f"rodada {r['rodada']}: " + (f"nao conta, {r['nao_conta']}" if "nao_conta" in r else
                                          f"filtro {r['filtro_piso_ms']:+.1f} ms (mediana {r['filtro_ms']:+.1f}), app "
                                          f"{r['app_piso_ms']:+.1f} ms (mediana {r['app_ms']:+.1f}), piso sem efeito "
                                          f"{r['base_ms']} ms"))
    if contam:
        print(f"a mais pelo piso, mediana de {len(contam)} rodada(s): efeito no filtro {res['filtro_piso_ms']:+.1f} ms, "
              f"efeito pelo app {res['app_piso_ms']:+.1f} ms (pelas medianas: {res['filtro_a_mais_ms']:+.1f} e "
              f"{res['app_a_mais_ms']:+.1f})")
    print("rodada vale" if res["vale"] else "NAO vale: menos de duas rodadas contam")
    print(f"resultado: {saida}")
    return 0 if res["vale"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mic", nargs="?", help="o microfone com o filtro (parte do nome), ex. 'CABLE Output'")
    ap.add_argument("toca", nargs="?", help="a saida que cai nesse microfone (parte do nome), ex. 'CABLE Input'")
    ap.add_argument("--efeito", default="eco")
    ap.add_argument("--saida", default=os.path.join(tempfile.gettempdir(), "mede_voz_ao_vivo.json"),
                    help="o .json do resultado (a captura vai num .npz ao lado)")
    ap.add_argument("--console", action="store_true", help="mantem o console, para ver a diferenca")
    ap.add_argument("--sem-microfone", action="store_true", help="o motor sem o microfone aberto")
    ap.add_argument("--analisa", metavar="NPZ", help="refaz a conta de uma captura guardada")
    ap.add_argument("--papel", choices=("motor",), help=argparse.SUPPRESS)
    ap.add_argument("--guid", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.analisa:
        return conta(a.analisa, Path(a.analisa).with_suffix(".json"))
    so_mock.sai_se_o_app_ligado("o mede_voz_ao_vivo")  # antes de abrir o anel, o microfone e a saida
    if a.papel == "motor":
        return motor(a)
    if not a.mic or not a.toca:
        ap.error("diga o microfone com o filtro e a saida que cai nele")
    return mede(a)


if __name__ == "__main__":
    sys.exit(main())
