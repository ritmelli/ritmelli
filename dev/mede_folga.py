"""Mede quanto a saida para o jogo (engine.Injetor) chega perto de secar o anel do filtro, num microfone de verdade.

Toca um arquivo pelo motor num microfone com o filtro, sem fone, e conta: as voltas da thread do Injetor, o menor tanto
que o anel teve quando ela chegou e quantas vezes ele estava vazio (o filtro soltou silencio no lugar da musica: um
engasgo no jogo). Opcoes:
    --carga N             N processos ocupam a CPU (o jogo); o dobro dos nucleos faz o papel de um PC mais fraco
    --passagem outra.webm o motor prepara sem parar a passagem para outra musica (decodifica o fim desta e o comeco da
                          outra e mede as batidas, o trabalho pesado do servidor; de verdade e uma vez por musica)
    --ciclo outra.webm    o que o servidor faz numa troca de musica, em ciclos de ~40 s: esta comeca CICLO_S antes do
                          fim, a outra e preparada, a passagem toca ate virar e a outra segue uns segundos
    --sem-mmcss           a thread sem a prioridade de audio do Windows, para comparar
    --folga N             troca o INJ_FOLGA (blocos de 10 ms)
    --onde [MS]           nas paradas da thread de mais de MS ms (30 sem numero), guarda onde as outras threads estavam

    python dev/mede_folga.py "IN 2" musica.webm [--segundos 60] [--carga N] [--passagem outra.webm | --ciclo outra.webm]
                             [--sem-mmcss]
                             [--folga N] [--onde [MS]]

Mede como o app roda (o executavel e console=False; o pythonw tambem nao tem console): com a saida redirecionada, o
script se solta do console antes de abrir o motor. Preso a um console, toda thread nova pergunta ao conhost o idioma
dele ao nascer e todo io.open (o Popen faz um por PIPE) chama o GetConsoleMode segurando o interpretador; com a CPU
cheia o conhost demora e o interpretador fica preso ~10 ms (14/11, rastro do xperf): paradas que o app nao tem.
--console mantem o console (para ver essa diferenca).

Toca de verdade nesse microfone: quem estiver ouvindo ele (uma call, um jogo) ouve. Para sem tocar nada num microfone
sem o filtro pronto (o motor rodaria a tarefa do instalador, que reinicia o audio do Windows). E manual, para um Windows
de teste: com o Ritmelli ligado (a porta 8799 aceitando conexao), sai com erro antes de abrir o anel (dev/so_mock.py).
"""
import argparse
import collections
import json
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as eng

sys.path.insert(0, str(Path(__file__).resolve().parent))
import so_mock

AQUECE_S = 3.0  # o comeco (ffmpeg abrindo, o modelo da rede carregando) fica fora da medida
CICLO_S = 40.0  # no --ciclo, esta musica comeca isso antes do fim


def _percentil(hist, p):
    acum = np.cumsum(hist)
    return int(np.searchsorted(acum, p * acum[-1]))


def _passagens(e, a_path, b_path, para, feitas):
    """A preparacao da passagem, de novo a cada plano pronto: esta musica perto do fim e a outra no segundo deck."""
    da, db = eng.probe_duration(a_path), eng.probe_duration(b_path)
    while not para.is_set():
        e.load({"id": "mede-a", "path": a_path, "duration": da}, start=max(0.0, da - eng.TRANS_PREP_S + 10))
        e.preparar({"id": "mede-b", "path": b_path, "duration": db}, "mede")
        limite = time.monotonic() + 30
        while e.planejando and time.monotonic() < limite and not para.is_set():
            time.sleep(0.05)
        feitas.append(time.monotonic())


def _ciclos(e, a_path, b_path, para, feitas):
    """Uma troca de musica de verdade por ciclo: esta perto do fim, a outra preparada, a virada e a outra tocando."""
    da, db = eng.probe_duration(a_path), eng.probe_duration(b_path)
    while not para.is_set():
        e.load({"id": "mede-a", "path": a_path, "duration": da}, start=max(0.0, da - CICLO_S))
        time.sleep(1.0)
        e.preparar({"id": "mede-b", "path": b_path, "duration": db}, "mede")
        limite = time.monotonic() + CICLO_S + 15
        while (e.track or {}).get("id") != "mede-b" and time.monotonic() < limite and not para.is_set():
            time.sleep(0.05)
        feitas.append(time.monotonic())
        para.wait(3.0)


def _onde(inj, ultima, para, paradas, parada_s):
    """Vigia a thread do Injetor: parada mais que parada_s, conta onde estao as outras threads nesse instante. A que
    segurou o interpretador acabou de soltar, entao ela aparece logo depois do trecho que segurou; somando as paradas, o
    trecho que se repete e o culpado."""
    vista, eu = None, threading.get_ident()
    while not para.is_set():
        time.sleep(0.005)
        t = ultima[0]
        parada = time.perf_counter() - t
        if parada < parada_s or vista == t:
            continue
        vista = t
        nomes = {th.ident: th.name for th in threading.enumerate()}
        for ident, f in sys._current_frames().items():
            if ident in (eu, inj._th.ident):
                continue
            pilha = traceback.extract_stack(f)[-3:]
            paradas[f"{nomes.get(ident, ident)}: " + " <- ".join(
                f"{Path(q.filename).name}:{q.lineno} {q.name}" for q in reversed(pilha))] += 1
        paradas["(paradas)"] += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mic")
    ap.add_argument("arquivo")
    ap.add_argument("--segundos", type=float, default=60.0)
    ap.add_argument("--carga", type=int, default=0)
    ap.add_argument("--passagem")
    ap.add_argument("--ciclo")
    ap.add_argument("--sem-mmcss", action="store_true")
    ap.add_argument("--folga", type=int, default=eng.INJ_FOLGA)
    ap.add_argument("--onde", type=float, nargs="?", const=30.0)
    ap.add_argument("--console", action="store_true")
    a = ap.parse_args()
    so_mock.sai_se_o_app_ligado("o mede_folga")  # antes de abrir o anel e o microfone
    if not a.console and not sys.stdout.isatty() and not sys.stderr.isatty():
        import ctypes
        ctypes.windll.kernel32.FreeConsole()  # sem console, como o executavel: a saida ja vai para arquivo ou cano
    eng.INJ_FOLGA = a.folga
    eng.INJ_MMCSS = not a.sem_mmcss

    nome = eng.find_dev(a.mic, "in")[1]["name"]
    st = eng._do_microfone(nome)
    if not (st and st["filtro"] and st["melhorias"]):
        sys.exit(f"{nome}: sem o filtro pronto ({st}); nada tocado")

    e = eng.Engine(nome, "")
    e.start()
    inj = e._injetor
    limite = time.monotonic() + 15
    while inj.leitores == 0 and time.monotonic() < limite:
        time.sleep(0.1)
    if inj.leitores == 0:
        e.close()
        sys.exit(f"{nome}: o filtro nao leu o anel em 15 s; nada medido")

    arquivo = str(Path(a.arquivo).resolve())
    e.load({"id": "mede-folga", "path": arquivo, "duration": eng.probe_duration(arquivo)})
    time.sleep(AQUECE_S)
    inj.folga_min, inj.secas, inj.volta_max = None, 0, 0.0
    inj.voltas[:] = 0

    para = threading.Event()
    paradas = collections.Counter()
    if a.onde is not None:
        ultima, volta = [time.perf_counter()], inj._volta

        def _marca(s):
            ultima[0] = time.perf_counter()
            volta(s)
        inj._volta = _marca
        threading.Thread(target=_onde, args=(inj, ultima, para, paradas, a.onde / 1000), daemon=True).start()
    feitas = []
    if a.passagem or a.ciclo:
        threading.Thread(target=_passagens if a.passagem else _ciclos,
                         args=(e, arquivo, str(Path(a.passagem or a.ciclo).resolve()), para, feitas), daemon=True).start()
    carga = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(a.carga)]
    try:
        fim = time.monotonic() + a.segundos
        while time.monotonic() < fim:
            time.sleep(min(10.0, max(0.0, fim - time.monotonic())))
            print(json.dumps(inj.estado()), file=sys.stderr, flush=True)
    finally:
        para.set()
        for p in carga:
            p.kill()
        e.close()

    h = inj.voltas
    bloco_ms = eng.BLOCK * 1000 / eng.SR
    folga_ms = a.folga * bloco_ms
    menor = None if inj.folga_min is None else inj.folga_min * 1000 / eng.SR
    print(json.dumps({
        "microfone": nome, "segundos": a.segundos, "carga": a.carga, "mmcss": inj.mmcss,
        "passagens": len(feitas) if a.passagem or a.ciclo else None, "folga_ms": folga_ms, "voltas": int(h.sum()),
        "volta_ms": {"p50": _percentil(h, 0.5), "p99": _percentil(h, 0.99), "p99_9": _percentil(h, 0.999),
                     "max": round(inj.volta_max * 1000, 1)},
        # o anel completa ate folga_ms e a thread volta quando ele tem folga_ms - 10 ou menos: o menor tanto na chegada
        # e quanto da folga a pior demora gastou (gasto igual a folga_ms - 10 = secou)
        "menor_no_anel_ms": None if menor is None else round(menor, 1),
        "gasto_ms": None if menor is None else round(folga_ms - bloco_ms - menor, 1),
        "secas": inj.secas,
    }, ensure_ascii=False))
    for onde, n in paradas.most_common(25):
        print(f"{n:4} {onde}", file=sys.stderr)


if __name__ == "__main__":
    main()
