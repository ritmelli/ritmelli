"""Banco de teste dos efeitos de voz: passa uma fala por cada efeito em blocos de 10 ms
(como o motor faz), confere tamanho, valores, CPU por bloco e, nos de tom, a nota, e
grava um .wav por efeito em logs/efeitos/ para ouvir.

    python dev/efeitos.py [--entrada logs/efeitos/_original.wav]
"""
import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fx  # noqa: E402

SR, B = fx.SR, 480
FAIXA = {"radio-policia": 25, "megafone": 20}  # dB abaixo do meio (1,5 kHz)
# efeito x voz crua pelo ouvido: em 17/10 ficou ate ~+2 dB no nivel real do usuario e +3,4 com
# o microfone 12 dB mais fraco; o limite pega regressao grande (ja houve +17,9 dB)
LIMITE_VOLUME = 4.0
OUT = Path(__file__).resolve().parent.parent / "logs" / "efeitos"


def ler_wav(p):
    with wave.open(str(p)) as w:
        assert w.getframerate() == SR and w.getsampwidth() == 2, "precisa de wav 48 kHz 16 bits"
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        return x.reshape(-1, w.getnchannels()).mean(axis=1)


def gravar_wav(p, x):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def stream(e, x):
    out, ts = [], []
    for i in range(0, len(x) - len(x) % B, B):
        t0 = time.perf_counter()
        y = e(x[i:i + B]) if e else x[i:i + B]
        ts.append(time.perf_counter() - t0)
        out.append(y)
    return np.concatenate(out), np.array(ts) * 1000


def freq_pico(x):
    s = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.fft.rfftfreq(len(x), 1 / SR)[np.argmax(s)]


def volume_x_entrada(eid, fala, ganhos=(6, 0, -12, -24)):
    """Diferenca de volume pelo ouvido (Audibilidade, o mesmo modelo do nivelador) entre o
    efeito e a voz crua, com a entrada deslocada pelos ganhos, so nos trechos de fala
    depois de 1 s (o nivelador assenta)."""
    import audibilidade as au
    out = []
    for g in ganhos:
        x = fala * 10 ** (g / 20)
        x = x[:len(x) // B * B]
        m = np.sqrt(np.mean(x.reshape(-1, B) ** 2, axis=1)) > 10 ** (-50 / 20)
        m[:SR // B] = False
        y, _ = stream(fx.criar(eid), x)
        out.append(au.diferenca_db(x, y, m))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", default=str(OUT / "_original.wav"))
    a = ap.parse_args()
    fala = ler_wav(a.entrada)
    # 1 s de silencio no fim: e onde o radio solta o bip de cambio
    fala = np.concatenate([fala, np.zeros(SR, np.float32)])
    seno = (0.3 * np.sin(2 * np.pi * 300 * np.arange(SR) / SR)).astype(np.float32)
    real = ler_wav(OUT / "_microfone_real.wav") if (OUT / "_microfone_real.wav").exists() else None
    falhas = 0
    for _, eid, nome, _, _ in fx.CATALOGO:
        e = fx.criar(eid)
        y, ts = stream(e, fala)
        ok = len(y) == len(fala) - len(fala) % B and np.isfinite(y).all() and np.abs(y).max() <= 1
        nota = ""
        ps = [f for f in (e.antes if e else []) if isinstance(f, fx.PitchShifter)]
        if ps:
            esperado = 300 * (1 - ps[0].i)  # a leitura anda a 2^(s/12) = 1 - i
            ys, _ = stream(fx.criar(eid), seno)
            got = freq_pico(ys[SR // 4:])
            ok &= abs(got - esperado) / esperado < 0.03
            nota = f" tom 300 Hz -> {got:.0f} Hz (esperado {esperado:.0f})"
        if eid == "radio-policia":
            # o bip vem SILENCIO blocos depois do ultimo bloco de fala
            rms = np.sqrt(np.mean(fala[:len(fala) // B * B].reshape(-1, B) ** 2, axis=1))
            fim = (np.where(rms > fx.CambioRadio.LIGA)[0][-1] + fx.CambioRadio.SILENCIO) * B
            cauda = y[fim:fim + int(0.3 * SR)]
            tem_bip = float(np.sqrt(np.mean(cauda ** 2))) > 0.01
            # o chiado do canal aberto (antes do bip) nao pode subir ate a voz: 18 dB abaixo
            ob = np.sqrt(np.mean(y[:len(y) // B * B].reshape(-1, B) ** 2, axis=1))
            ult = np.where(rms > fx.CambioRadio.LIGA)[0][-1]
            voz = np.median(ob[:len(rms)][rms > fx.CambioRadio.LIGA])
            respiro = 20 * np.log10(np.median(ob[ult + 10:ult + 60]) / voz)
            ok &= tem_bip and respiro <= -18
            nota = f" bip de câmbio no silêncio: {'sim' if tem_bip else 'NÃO'}, chiado {respiro:.0f} dB da voz"
        if eid in FAIXA:
            # ruido branco: fora da faixa de radio/megafone tem que cair de verdade
            ruido = np.random.default_rng(1).standard_normal(4 * SR).astype(np.float32) * 0.05
            yr, _ = stream(fx.criar(eid), ruido)
            f = np.fft.rfftfreq(len(yr), 1 / SR)
            sy, sx = np.abs(np.fft.rfft(yr)) ** 2, np.abs(np.fft.rfft(ruido[:len(yr)])) ** 2
            g = {c: 10 * np.log10(sy[(f > c * .9) & (f < c * 1.1)].mean() / sx[(f > c * .9) & (f < c * 1.1)].mean())
                 for c in (100, 1500, 8000)}
            corte = min(g[1500] - g[100], g[1500] - g[8000])
            ok &= corte >= FAIXA[eid]
            nota += f" corte fora da faixa {corte:.0f} dB (min {FAIXA[eid]})"
        vol = volume_x_entrada(eid, fala)
        ok &= max(abs(v) for v in vol) <= LIMITE_VOLUME
        nota += " | volume pelo ouvido (+6/0/-12/-24): " + "/".join(f"{v:+.1f}" for v in vol)
        if real is not None and eid == "megafone":
            # megafone e de boca colada: o fundo do microfone nao pode subir (portao)
            yr, _ = stream(fx.criar(eid), real[:len(real) // B * B])
            ri = np.sqrt(np.mean(real[:len(real) // B * B].reshape(-1, B) ** 2, axis=1))
            ro = np.sqrt(np.mean(yr.reshape(-1, B) ** 2, axis=1))
            fundo, voz = ri < np.percentile(ri, 15), ri > 10 ** (-40 / 20)
            folga = 20 * np.log10(np.median(ro[voz]) / (np.median(ro[fundo]) + 1e-12))
            ok &= folga >= 40
            nota += f" | fala {folga:.0f} dB acima do fundo (min 40)"
            # latido sintetico nas pausas: o de 18 dB ou mais abaixo da fala tem que sumir
            import latido as lt
            xl, _, fl, marcas = lt.montar()
            yl, _ = stream(fx.criar(eid), xl)
            rel = dict(zip([n for *_, n in marcas], lt.relativo(yl, fl, marcas)))
            sumiu = all(rel[n] < -40 for n in rel if n <= -18)
            ok &= sumiu
            nota += f" | latido -18 dB {rel[-18]:+.0f} dB da fala ({'some' if sumiu else 'PASSA'})"
        if real is not None:  # a gravacao do microfone do usuario, quando existe neste PC
            vr = volume_x_entrada(eid, real, (6, 0, -12))
            ok &= max(abs(v) for v in vr) <= LIMITE_VOLUME
            nota += " | voz real (+6/0/-12): " + "/".join(f"{v:+.1f}" for v in vr)
        falhas += not ok
        gravar_wav(OUT / f"{eid}.wav", y)
        print(f"{'OK   ' if ok else 'FALHA'} {nome:24s} cpu {ts.mean():.3f}/{ts.max():.2f} ms"
              f"  pico {np.abs(y).max():.2f}  atraso ~{e.latencia_ms if e else 0} ms{nota}")
    print(f"wavs em {OUT}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
