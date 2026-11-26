"""Mede o atraso da voz com efeito no microfone do jogo, sem o audiodg e sem som: o filtro de verdade (micfx.cpp, pela
banca_filtro.dll do dev/testa_filtro.py) roda a cada 10 ms numa thread, como o audiodg, com um estalo na voz a cada
250 ms; o motor e o MockEngine (sem o relogio dele) com o Injetor de verdade e o efeito Eco (sem atraso proprio: o
som seco do estalo sai na hora, o eco 280 ms depois, fora da janela).

    microfone\\apo\\compila.bat teste
    python dev/mede_voz.py [--segundos 10] [--pelo-app] [--efeito eco]

Sem --pelo-app o efeito roda no filtro (issue #63); com ele, o preset fica de fora e a voz faz a ida e volta pelo app,
como antes. Imprime mediana, p95 e maximo do atraso em ms, do estalo na voz crua ate o pico na saida do filtro.
"""
import argparse
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
os.environ["MICFX_MAPA"] = f"Local\\RitmelliMedeVoz-{os.getpid()}"
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))
import engine as eng
from testa_filtro import Banca

from microfone import injeta, preset

BLOCO = 480
ESTALO_A_CADA = 25  # blocos: um estalo a cada 250 ms


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--segundos", type=float, default=10.0)
    ap.add_argument("--pelo-app", action="store_true", help="o caminho de antes: a voz vai ao app e volta")
    ap.add_argument("--efeito", default="eco")
    a = ap.parse_args(argv)
    if a.pelo_app:
        # o filtro nao ganha o preset (o Injetor manda o anel vazio) e a voz vai pelo app. O preset.preset fica: a cadeia
        # do app (o voz.dll do Engine._cadeia) sai dele, e sem ele a voz voltava crua, com 0 ms
        preset.pede = lambda *_: None
    banca = Banca()
    motor = eng.MockEngine("", "")
    motor.monitor_on = False
    motor._alvo = injeta.hash_microfone("{mede-voz}")
    motor.set_effect(a.efeito)
    entrou, saiu = [], []
    vai = threading.Event()
    vai.set()

    def audiodg():
        winmm = __import__("ctypes").WinDLL("winmm")
        winmm.timeBeginPeriod(1)
        k, prox = 0, time.perf_counter()
        while vai.is_set():
            x = np.zeros(BLOCO, np.float32)
            if k % ESTALO_A_CADA == 0 and k:
                x[0] = 1.0
            entrou.append(x)
            saiu.append(banca.passa(x)[:, 0].copy())
            k += 1
            prox += 0.01
            time.sleep(max(0.0, prox - time.perf_counter()))
        winmm.timeEndPeriod(1)

    th = threading.Thread(target=audiodg, daemon=True)
    th.start()
    time.sleep(0.05)
    inj = eng.Injetor(motor)
    try:
        time.sleep(a.segundos)
        no_filtro = inj.estado()["efeito_no_filtro"]
    finally:
        inj.para()
        vai.clear()
        th.join()
        banca.fecha()
    e, s = np.concatenate(entrou[100:]), np.concatenate(saiu[100:])  # o primeiro segundo e a partida
    at = []
    for p in np.flatnonzero(e > 0.5):
        janela = np.abs(s[p:p + ESTALO_A_CADA * BLOCO])
        if len(janela) == ESTALO_A_CADA * BLOCO and janela.max() > 0.05:
            at.append(int(np.argmax(janela)) * 1000 / eng.SR)
    if not at:
        print("nenhum estalo chegou")
        return 1
    at = np.array(at)
    print(f"voz com {a.efeito} ({'no filtro' if no_filtro else 'pelo app'}): {len(at)} estalos, mediana "
          f"{np.median(at):.1f} ms, p95 {np.percentile(at, 95):.1f} ms, max {at.max():.1f} ms, min {at.min():.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
