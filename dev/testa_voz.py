"""Confere o motor de efeitos do filtro (microfone/apo/voz.h, pelo voz.dll) contra a cadeia do fx.py, efeito por efeito.

A mesma fala passa pelos dois em blocos de 10 ms, como o filtro recebe. Sem --entrada, a fala e sintetica (pulso
glotal com tom variando, tres formantes, silabas e pausas, 1 s de silencio no fim para o bip do radio); com
--entrada, um wav de 48 kHz 16 bits. Mede a diferenca como SNR (a saida do fx.py sobre o erro) e confere:

- paridade a 48 kHz: cada efeito acima do limite dele (o chorus e o radio sem o chiado ficam mais baixos, ver LIMITE);
- o radio com o chiado: o volume do canal (chiado, squelch, bip) a menos de 1,5 dB do fx.py;
- outras taxas (44,1, 16 e 96 kHz): o preset monta, a saida e finita e o volume fica perto do de 48 kHz;
- a memoria de cada cadeia cabe na que o filtro separa (voz.ArenaBytes), com folga;
- preset estragado (truncado, taxa trocada, contagem absurda, NaN) e recusado, sem travar.

    microfone\\apo\\compila.bat teste
    python dev/testa_voz.py [--entrada fala.wav] [-v]

Sai 1 se algo falhar.
"""
import argparse
import struct
import sys
import time
import wave
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fx  # noqa: E402
from microfone import preset, voz  # noqa: E402

SR, B = fx.SR, 480
# paridade minima (dB de SNR) a 48 kHz; os demais, LIMITE_PADRAO. O chorus do robo e do alien segue a mesma formula
# da pedalboard com um residuo do oscilador dela (~ -43 dB num chorus sozinho): medido 41 e 35 dB em 14/11
LIMITE_PADRAO = 60.0
LIMITE = {"robo": 38.0, "alien": 32.0}


def fala_sintetica(seg=8.0, sr=SR, semente=5):
    rng = np.random.default_rng(semente)
    n = int(seg * sr)
    t = np.arange(n) / sr
    f0 = 125 + 35 * np.sin(2 * np.pi * 0.7 * t) + 15 * np.sin(2 * np.pi * 2.3 * t)
    pulso = signal.sawtooth(np.cumsum(2 * np.pi * f0 / sr))
    x = np.zeros(n)
    for f, q, g in ((700, 5, 1.0), (1200, 6, 0.6), (2600, 8, 0.35)):
        b, a = signal.iirpeak(f, q, fs=sr)
        x += g * signal.lfilter(b, a, pulso)
    silabas = np.clip(np.sin(2 * np.pi * 3.5 * t) * 1.5, 0, 1) ** 0.5
    frases = ((t % 2.4) < 1.6).astype(float)  # 1,6 s de fala e 0,8 s de pausa
    env = signal.lfilter([0.002], [1, -0.998], silabas * frases)
    x = x * env / np.max(np.abs(x * env)) * 0.5 + rng.standard_normal(n) * 0.002
    x[int((seg - 1.0) * sr):] = rng.standard_normal(int(1.0 * sr)) * 0.002
    return x.astype(np.float32)


def ler_wav(p):
    with wave.open(str(p)) as w:
        assert w.getframerate() == SR and w.getsampwidth() == 2, "precisa de wav 48 kHz 16 bits"
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        return x.reshape(-1, w.getnchannels()).mean(axis=1)


def em_blocos(f, x, b=B):
    n = len(x) - len(x) % b
    return np.concatenate([f(x[i:i + b]) for i in range(0, n, b)])


def snr(ref, y):
    erro = float(np.sum((y.astype(np.float64) - ref) ** 2))
    return 200.0 if erro == 0 else 10 * np.log10(float(np.sum(ref.astype(np.float64) ** 2)) / erro)


def db_rms(x):
    return 10 * np.log10(float(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-20)


def efeitos():
    return [c[1] for c in fx.CATALOGO + fx.MODOS if fx.criar(c[1]) is not None]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--entrada")
    ap.add_argument("-v", action="store_true", help="imprime tudo, nao so o que falhou")
    a = ap.parse_args(argv)
    x = ler_wav(a.entrada) if a.entrada else fala_sintetica()
    falhas = []

    def confere(ok, msg):
        if not ok:
            falhas.append(msg)
        if a.v or not ok:
            print(("ok    " if ok else "FALHA ") + msg)

    cap48 = voz.arena(SR)
    for eid in efeitos():
        e = fx.criar(eid)
        p = preset.compila(e, SR, extra=False)
        if e.extra is not None:
            e.extra = None  # o chiado sorteia diferente nos dois lados: a paridade e sem ele
        c = voz.Cadeia(p, SR)
        t0 = time.perf_counter()
        y = em_blocos(c, x)
        ms = (time.perf_counter() - t0) / (len(y) / B) * 1000
        ref = em_blocos(e, x)
        s = snr(ref, y)
        lim = LIMITE.get(eid, LIMITE_PADRAO)
        confere(c.finito and s >= lim, f"{eid}: paridade {s:.1f} dB (minimo {lim:.0f}), {ms:.3f} ms por bloco, "
                f"memoria {c.usado / 1024:.0f} KB de {cap48 / 1024:.0f}")
        confere(c.usado < 0.75 * cap48, f"{eid}: a memoria cabe com folga")

    # a etapa Fdn sozinha (sem o tom e a distorcao do demonio na frente, que limitam a paridade do efeito): as salas do
    # catalogo e uma que passa por todo o caminho (pre-atraso, 6 passos, modulacao funda, cortes diferentes). A conta e
    # a mesma dos dois lados, entao a paridade e quase exata; o custo e o do filtro, com o ctypes junto
    salas = [(eid, f) for eid in efeitos() for f in fx.criar(eid).depois if isinstance(f, fx.Fdn)]
    salas.append(("fdn-completa", fx.Fdn(30, (2.0, 1.5, 0.6), cortes=(400, 3000), difusao_ms=50, passos=6, pre_ms=7,
                                         mod_ms=1.0, cedo=0.5, molhado=0.2)))
    for eid, f in salas:
        e = fx.Efeito(depois=[f])
        c = voz.Cadeia(preset.compila(e, SR), SR)
        t0 = time.perf_counter()
        y = em_blocos(c, x)
        ms = (time.perf_counter() - t0) / (len(y) / B) * 1000
        s = snr(em_blocos(e, x), y)
        confere(c.finito and s >= 120, f"{eid}: a Fdn sozinha, paridade {s:.1f} dB (minimo 120)")
        confere(ms < 0.3, f"{eid}: a Fdn custa {ms:.3f} ms por bloco de 10 ms (maximo 0,3)")

    # o radio inteiro: o som do canal (chiado, squelch, bip) sai com o volume do fx.py
    e = fx.criar("radio-policia")
    c = voz.Cadeia(preset.compila(e, SR), SR)
    y, ref = em_blocos(c, x), em_blocos(e, x)
    e2 = fx.criar("radio-policia")
    e2.extra = None
    sem = em_blocos(e2, x)
    canal_nat, canal_ref = db_rms(y - sem), db_rms(ref - sem)
    confere(abs(canal_nat - canal_ref) < 1.5, f"radio-policia: canal {canal_nat:.1f} dB contra {canal_ref:.1f} do fx.py")

    # outras taxas: monta, sai finito, e o volume fica perto do de 48 kHz
    for taxa in (44100, 16000, 96000):
        xt = signal.resample_poly(x, taxa, SR).astype(np.float32)
        bt = taxa // 100
        for eid in efeitos():
            p48 = preset.compila(fx.criar(eid), SR)
            y48 = em_blocos(voz.Cadeia(p48, SR), x)
            try:
                pt = preset.compila(fx.criar(eid), taxa)
            except preset.NaoPortado as ex:
                confere(False, f"{eid} a {taxa} Hz: nao compila ({ex})")
                continue
            c = voz.Cadeia(pt, taxa)
            yt = em_blocos(c, xt, bt)
            d = db_rms(yt) - db_rms(y48)
            confere(c.finito and np.all(np.isfinite(yt)) and abs(d) < 3.0,
                    f"{eid} a {taxa} Hz: volume {d:+.1f} dB do de 48 kHz, memoria {c.usado / 1024:.0f} KB de "
                    f"{voz.arena(taxa) / 1024:.0f}")
            confere(c.usado < 0.75 * voz.arena(taxa), f"{eid} a {taxa} Hz: a memoria cabe com folga")

    # preset estragado: recusado (nunca trava, nunca monta pela metade)
    bom = preset.compila(fx.criar("locutor"), SR)
    estragados = {
        "truncado": bom[:-8],
        "sobrando": bom + b"\0" * 8,
        "magia": b"XXXX" + bom[4:],
        "etapas demais": bom[:28] + struct.pack("<I", 999) + bom[32:],
        "contagem absurda": bom[:80] + struct.pack("<II", 1, 0xFFFFFFFF) + bom[88:],
        "tipo desconhecido": bom[:80] + struct.pack("<I", 99) + bom[84:],
        "NaN no ganho": bom[:16] + struct.pack("<d", float("nan")) + bom[24:],
        "vazio": b"",
    }
    for nome, p in estragados.items():
        try:
            voz.Cadeia(p, SR)
            confere(False, f"preset {nome}: montou")
        except ValueError as ex:
            confere("invalido" in str(ex), f"preset {nome}: recusado ({ex})")
    try:
        voz.Cadeia(bom, 44100)
        confere(False, "preset de 48 kHz num microfone de 44,1 kHz: montou")
    except ValueError as ex:
        confere("taxa" in str(ex), f"preset de 48 kHz num microfone de 44,1 kHz: recusado ({ex})")
    # o filtro instavel (polo fora do circulo) e recusado
    instavel = preset.CABECALHO.pack(preset.MAGIA, preset.VERSAO, float(SR), 1.0, 0, 1, 0, 0, *(1e-5, .99, .08, 10, .23))
    instavel += struct.pack("<II6d", preset.T_SOS, 6, 1, 1, 0, 0, -2.5, 1.5)
    try:
        voz.Cadeia(instavel, SR)
        confere(False, "filtro instavel: montou")
    except ValueError as ex:
        confere("invalido" in str(ex), f"filtro instavel: recusado ({ex})")
    # a linha da Fdn que devolve mais do que recebe (polo dentro, ganho 1,2): a realimentacao cresceria sem parar
    fdn = fx.Fdn(25, (1.0, 1.0, 1.0))
    p = fdn.projeta(SR)
    dados = preset._fdn(fdn, SR)
    i = 2 + 16 * fdn.passos + 8  # o b0 do filtro da primeira linha (depois das 8 linhas)
    confere(dados[i - 8:i] == p["linhas"], "preset da Fdn: as linhas no lugar que o teste espera")
    for nome, b0 in (("ganho 1,2", 1.2), ("ganho 0,9", 0.9)):
        d = list(dados)
        d[i:i + 5] = [b0, 0.0, 0.0, 0.0, 0.0]
        q = preset.CABECALHO.pack(preset.MAGIA, preset.VERSAO, float(SR), 1.0, 0, 1, 0, 0, *(1e-5, .99, .08, 10, .23))
        q += struct.pack(f"<II{len(d)}d", preset.T_FDN, len(d), *map(float, d))
        try:
            voz.Cadeia(q, SR)
            confere(b0 < 1, f"linha da Fdn com {nome}: montou")
        except ValueError as ex:
            confere(b0 > 1 and "invalido" in str(ex), f"linha da Fdn com {nome}: recusada ({ex})")

    print(f"{'FALHOU' if falhas else 'ok'}: {len(falhas)} falha(s)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
