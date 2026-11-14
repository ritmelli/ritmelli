"""Mede o reamostra.h compilado (teste_reamostra.dll) nas taxas de microfone comuns.

    compila.bat teste      gera saida\\teste_reamostra.dll
    python teste_reamostra.py

Para cada taxa: THD+N de um tom de 1 kHz, resposta de 8 a 20 kHz, quanto um tom acima da Nyquist da saida dobra
pra dentro da banda e se a saida bate com o prototipo em numpy (mesmo filtro, conta em double). O anel simulado
e pequeno (4096 quadros) e os blocos sao tortos pra forcar volta do anel e fome do leitor. Sai 1 se algum limite
falhar.
"""
import ctypes
import os
import sys
from math import gcd

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
dll = ctypes.CDLL(os.path.join(AQUI, "..", "saida", "teste_reamostra.dll"))
P = ctypes.POINTER(ctypes.c_float)
dll.reamostra.argtypes = (P, ctypes.c_int, P, ctypes.c_int, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                          ctypes.c_longlong)
U = ctypes.POINTER(ctypes.c_uint)
dll.modo.argtypes = (ctypes.c_uint, U, U, U)
MODOS = {0: "direto", 1: "sinc", 2: "linear"}


def roda(x, taxa, leitor=441, escritor=997, anel=4096):
    x = np.ascontiguousarray(np.repeat(x[:, None], 2, axis=1) if x.ndim == 1 else x, dtype=np.float32)
    n = int(len(x) * taxa / 48000) - 400
    y = np.zeros((n, 2), np.float32)
    g = dll.reamostra(x.ctypes.data_as(P), len(x), y.ctypes.data_as(P), n, taxa, leitor, escritor, anel)
    return y[:g, 0].astype(np.float64)


def thdn(y, sr, f0):
    y = y[sr // 5: -sr // 5]
    t = np.arange(len(y)) / sr
    b = np.stack([np.sin(2 * np.pi * f0 * t), np.cos(2 * np.pi * f0 * t), np.ones_like(t)], 1)
    c, *_ = np.linalg.lstsq(b, y, rcond=None)
    fora = y - b @ c
    return 10 * np.log10(np.mean(fora ** 2) / np.mean((b[:, :2] @ c[:2]) ** 2)), np.hypot(c[0], c[1])


def prototipo(x, taxa, base=128, beta=11.2, corte=0.967):
    g = gcd(taxa, 48000)
    L, M = taxa // g, 48000 // g
    razao = min(1.0, L / M)
    fc = 0.5 * razao * corte
    taps = int(np.ceil(base / razao / 4) * 4)
    k = np.arange(taps)
    h = np.empty((L, taps))
    for r in range(L):
        t = r / L + taps / 2 - 1 - k
        w = np.i0(beta * np.sqrt(np.clip(1 - (t / (taps / 2)) ** 2, 0, None))) / np.i0(beta)
        h[r] = 2 * fc * np.sinc(2 * fc * t) * w
    xp = np.concatenate([np.zeros(taps), x])
    n = (len(x) - taps) * L // M
    i = np.arange(n) * M // L + taps
    r = (np.arange(n) * M) % L
    idx = i[:, None] - taps // 2 + 1 + np.arange(taps)[None, :]
    return np.einsum("nk,nk->n", xp[idx], h[r])


def main():
    t = np.arange(48000 * 2) / 48000
    falhou = False
    for taxa in (48000, 44100, 32000, 24000, 16000, 8000, 96000, 88200, 192000):
        L, M, taps = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        modo = MODOS[dll.modo(taxa, ctypes.byref(L), ctypes.byref(M), ctypes.byref(taps))]
        tom = 0.5 * np.sin(2 * np.pi * 1000 * t)
        y = roda(tom, taxa)
        d, _ = thdn(y, taxa, 1000)
        linha = f"{taxa:6d} {modo:6s} L {L.value:3d} M {M.value:3d} taps {taps.value:3d}: THD+N 1k {d:7.1f} dB"
        pior = 0.0
        for f in (8000, 12000, 16000, 18000, 20000):
            if f < taxa / 2 * 0.9:
                _, a = thdn(roda(0.5 * np.sin(2 * np.pi * f * t), taxa), taxa, f)
                pior = max(pior, abs(20 * np.log10(a / 0.5)))
        linha += f", resposta ate {min(20000, int(taxa / 2 * 0.9)) // 1000}k dentro de {pior:.3f} dB"
        if taxa < 48000:
            fa = min(23500.0, 0.56 * taxa)
            ya = roda(0.5 * np.sin(2 * np.pi * fa * t), taxa)
            dobra = 20 * np.log10(max(np.sqrt(2 * np.mean(ya[taxa // 5:-taxa // 5] ** 2)), 1e-12) / 0.5)
            linha += f", tom de {fa / 1000:.1f}k dobra a {dobra:.1f} dB"
            falhou |= dobra > -110
        if modo == "sinc":
            ref = prototipo(tom, taxa)
            n = min(len(ref), len(y)) - 200
            dif = np.max(np.abs(ref[:n] - y[:n]))
            linha += f", contra o prototipo {20 * np.log10(max(dif, 1e-15)):.0f} dBFS"
            falhou |= dif > 1e-5
        elif modo == "direto":
            n = len(y)
            exato = np.array_equal(y.astype(np.float32), tom[:n].astype(np.float32))
            linha += ", bit a bit " + ("sim" if exato else "NAO")
            falhou |= not exato
        falhou |= d > -120 or pior > 0.01
        print(linha)
    print("FALHOU" if falhou else "ok")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
