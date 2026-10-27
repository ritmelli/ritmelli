"""Teste do portao do megafone com latido de cachorro: insere latidos sinteticos nas
pausas da gravacao do microfone do usuario (logs/efeitos/_microfone_real.wav), em volumes
relativos a fala do usuario, e compara quanto o latido aparece em relacao a fala sem efeito e
com o efeito. Problema visto em 17/10: o megafone captava um cachorro latindo que sem
efeito nao aparecia.

    python dev/latido.py [efeito]
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import efeitos as ef  # noqa: E402
import fx  # noqa: E402

SR, B = fx.SR, 480
NIVEIS = (-6, -12, -18, -24, -30)  # latido em dB abaixo da fala mediana do usuario


def latido(seed):
    rng = np.random.default_rng(seed)
    dur = 0.18
    t = np.arange(int(dur * SR)) / SR
    f = 520 * (1 - 0.35 * t / dur)
    ph = 2 * np.pi * np.cumsum(f) / SR
    harm = sum(0.6 ** k * np.sin(k * ph) for k in range(1, 8))
    ruido = fx.FiltroBanda(600, 2500, 4)(rng.standard_normal(len(t)).astype(np.float32))
    env = np.minimum(1, t / 0.006) * np.exp(-t / 0.06)
    x = (0.7 * harm + 0.5 * ruido / (np.std(ruido) + 1e-9)) * env
    return (x / np.sqrt(np.mean(x[: int(0.06 * SR)] ** 2))).astype(np.float32)  # rms do ataque = 1


def montar():
    x = ef.ler_wav(ef.OUT / "_microfone_real.wav")
    x = x[: len(x) // B * B].copy()
    rms = np.sqrt(np.mean(x.reshape(-1, B) ** 2, axis=1))
    fala = rms > 10 ** (-40 / 20)
    voz = float(np.median(rms[fala]))
    # pausas: trechos de 300 ms ou mais com tudo abaixo de -50 dBFS, longe da fala
    quietos = rms < 10 ** (-50 / 20)
    vagas, i = [], 0
    while i < len(quietos):
        if quietos[i]:
            j = i
            while j < len(quietos) and quietos[j]:
                j += 1
            if j - i >= 30:
                vagas.append((i + 5) * B)
            i = j
        else:
            i += 1
    # se faltarem pausas, estica a gravacao com silencio do proprio fundo no fim
    fundo = x[np.repeat(quietos, B)][: SR]
    while len(vagas) < len(NIVEIS):
        vagas.append(len(x) + SR // 4)
        x = np.concatenate([x, np.tile(fundo, 1 + SR // max(len(fundo), 1))[: SR]])
    marcas = []
    for k, (pos, nivel) in enumerate(zip(vagas, NIVEIS)):
        l = latido(k) * voz * 10 ** (nivel / 20)
        x[pos:pos + len(l)] += l
        marcas.append((pos, len(l), nivel))
    return x, voz, fala, marcas


def relativo(y, fala, marcas):
    rms = np.sqrt(np.mean(y[: len(y) // B * B].reshape(-1, B) ** 2, axis=1))
    voz = float(np.median(rms[: len(fala)][fala]))
    out = []
    for pos, n, _ in marcas:
        seg = y[pos:pos + n]
        out.append(20 * np.log10(np.sqrt(np.mean(seg[: int(0.06 * SR)] ** 2)) / voz + 1e-12))
    return out


def main(eid="megafone"):
    sys.stdout.reconfigure(encoding="utf-8")
    x, _, fala, marcas = montar()
    seco = relativo(x, fala, marcas)
    y, _ = ef.stream(fx.criar(eid), x)
    com = relativo(y, fala, marcas)
    print(f"latido em relação à fala (dB), sem efeito -> {eid}:")
    for (_, _, nivel), a, b in zip(marcas, seco, com):
        print(f"  latido {nivel:+d} dB: sem efeito {a:+6.1f} | {eid} {b:+6.1f} | {'MAIS' if b > a + 1 else 'ok  '} ({b - a:+.1f})")
    return seco, com


if __name__ == "__main__":
    main(*(sys.argv[1:2] or ["megafone"]))
