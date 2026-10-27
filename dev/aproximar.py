"""Prototipo do "aproximar": faz a voz de quem fala longe do microfone soar como colada nele.
Duas partes num STFT so (janela de 960, salto de 480 = um bloco do motor, 10 ms de atraso):
- tira a sala: estimativa da reverberacao tardia por faixa (Lebart: a potencia de 50 ms
  atras, decaida pelo RT60 da sala) e ganho espectral que a abaixa;
- casa o timbre: curva de EQ tirada das gravacoes de referencia do mesmo texto de perto e de longe
  (espectro medio de perto menos o de longe ja sem sala), que devolve o grave de
  proximidade e o agudo que a distancia leva.

    python dev/aproximar.py   (precisa de logs/efeitos/_locucao_real.wav e _locucao_longe.wav)
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import efeitos as ef  # noqa: E402
import fx  # noqa: E402

SR, B = fx.SR, 480
N = 2 * B
F = np.fft.rfftfreq(N, 1 / SR)


class Aproximar:
    """STFT com janela raiz de Hann (analise e sintese), salto de um bloco: sai o bloco
    anterior pronto, entao o atraso e de 480 amostras (10 ms)."""

    def __init__(self, curva_db=None, rt60=0.4, atraso_tardio=0.05, excesso=1.2, piso_db=-18):
        self.janela = np.sqrt(np.hanning(N + 1)[:N])
        self.entrada = np.zeros(N, np.float32)
        self.saida = np.zeros(N, np.float64)
        self.curva = np.ones(len(F)) if curva_db is None else 10 ** (np.asarray(curva_db) / 20)
        quadros = max(1, int(round(atraso_tardio * SR / B)))
        self.hist = [np.zeros(len(F)) for _ in range(quadros)]
        self.decai = np.exp(-2 * (3 * np.log(10) / rt60) * atraso_tardio)
        self.excesso, self.piso = excesso, 10 ** (piso_db / 20)
        self.p = np.zeros(len(F))
        self.g = np.ones(len(F))

    def __call__(self, blk):
        self.entrada = np.concatenate([self.entrada[B:], blk])
        X = np.fft.rfft(self.entrada * self.janela)
        pot = np.abs(X) ** 2
        self.p = 0.5 * self.p + 0.5 * pot  # potencia suavizada no tempo
        tardia = self.decai * self.hist[0]
        self.hist = self.hist[1:] + [self.p.copy()]
        alvo = np.maximum(1 - self.excesso * tardia / (self.p + 1e-12), self.piso)
        self.g = 0.6 * self.g + 0.4 * alvo  # suaviza o ganho: menos "agua" no som
        y = np.fft.irfft(X * self.g * self.curva, N) * self.janela
        self.saida[:N - B] = self.saida[B:]
        self.saida[N - B:] = 0
        self.saida += y
        return self.saida[:B].astype(np.float32)


def aparar(x):
    rms = np.sqrt(np.mean(x[:len(x) // B * B].reshape(-1, B) ** 2, axis=1))
    idx = np.where(rms > 10 ** (-55 / 20))[0]
    x = x[:min(len(x), (idx[-1] + 50) * B)]
    return x[:len(x) // B * B]


def rt60(x):
    """Estima o RT60 pela queda de energia (500 a 2000 Hz) logo depois do fim de cada frase."""
    from scipy import signal
    sos = signal.butter(4, [500, 2000], btype="band", fs=SR, output="sos")
    y = signal.sosfilt(sos, x)
    e = 10 * np.log10(np.convolve(y ** 2, np.ones(240) / 240, "same")[::240] + 1e-14)  # 5 ms
    inclinacoes = []
    for i in range(20, len(e) - 40):
        if e[i] > np.max(e[i + 1:i + 40]) + 15 and e[i] > np.percentile(e, 70):  # fim de frase
            trecho = e[i:i + 30]  # 150 ms de queda
            fim = np.argmax(trecho < trecho[0] - 25) or len(trecho)
            if fim > 4:
                a = np.polyfit(np.arange(fim) * 0.005, trecho[:fim], 1)[0]
                if a < -20:
                    inclinacoes.append(a)
    return float(np.clip(-60 / np.median(inclinacoes), 0.15, 1.2)) if inclinacoes else 0.4


def ltas(x):
    """Espectro medio (dB) dos quadros de fala, nas faixas do rfft de N."""
    w = np.hanning(N)
    pot = []
    for i in range(0, len(x) - N, B):
        q = x[i:i + N]
        if np.sqrt(np.mean(q * q)) > 10 ** (-50 / 20):
            pot.append(np.abs(np.fft.rfft(q * w)) ** 2)
    return 10 * np.log10(np.mean(pot, axis=0) + 1e-14)


def suaviza(c, oitava=1 / 3):
    out = np.empty_like(c)
    for k, f in enumerate(F):
        m = (F >= f * 2 ** (-oitava / 2)) & (F <= f * 2 ** (oitava / 2)) if f > 0 else F == 0
        out[k] = c[m].mean()
    return out


def curva_de_casamento(perto, longe_sem_sala):
    c = suaviza(ltas(perto)) - suaviza(ltas(longe_sem_sala))
    c -= c[(F >= 300) & (F <= 3000)].mean()  # so a forma: o volume e com o nivelador
    c = np.clip(c, -12, 15)
    c[F < 70] = np.minimum(c[F < 70], 0)  # nao reforca ronco abaixo de 70 Hz
    c[F > 16000] = np.minimum(c[F > 16000], 0)
    return c


def stream(proc, x):
    return np.concatenate([proc(x[i:i + B]) for i in range(0, len(x), B)])


def cauda_db(x, perto_ref=None):
    """Energia nos 60 a 250 ms depois do fim de cada frase, relativa a fala: quanto de sala."""
    rms = np.sqrt(np.mean(x[:len(x) // B * B].reshape(-1, B) ** 2, axis=1))
    fala = rms > np.percentile(rms, 60)
    caudas = [rms[i + 6:i + 25].mean() for i in range(len(rms) - 25) if fala[i] and not fala[i + 1:i + 6].any()]
    return 20 * np.log10(np.mean(caudas) / np.median(rms[fala])) if caudas else float("nan")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    perto = aparar(ef.ler_wav(ef.OUT / "_locucao_real.wav"))
    longe = aparar(ef.ler_wav(ef.OUT / "_locucao_longe.wav"))
    t60 = rt60(longe)
    sem_sala = stream(Aproximar(rt60=t60), longe)
    curva = curva_de_casamento(perto, sem_sala)
    aprox = stream(Aproximar(curva, rt60=t60), longe)
    (ef.OUT / "curva_aproximar.json").write_text(json.dumps(
        {"rt60": t60, "freq": F.tolist(), "curva_db": curva.tolist()}), encoding="utf-8")
    faixa = (F >= 100) & (F <= 8000)
    dif = lambda a, b: suaviza(ltas(a)) - suaviza(ltas(b))
    norm = lambda d: d - d[(F >= 300) & (F <= 3000)].mean()
    print(f"RT60 estimado da sala: {t60:.2f} s")
    print("curva (dB) em " + " ".join(f"{f}Hz {curva[np.argmin(abs(F - f))]:+.1f}" for f in (100, 150, 250, 500, 1000, 3000, 6000, 10000)))
    for nome, y in (("longe cru", longe), ("longe aproximado", aprox)):
        d = norm(dif(y, perto))[faixa]
        print(f"{nome:17s}: timbre x perto, desvio medio {np.sqrt(np.mean(d ** 2)):.1f} dB | cauda de sala {cauda_db(y):+.1f} dB")
    print(f"{'perto (referencia)':17s}: cauda de sala {cauda_db(perto):+.1f} dB")
    ef.gravar_wav(ef.OUT / "longe_aproximado.wav", aprox)
    return perto, longe, aprox, curva, t60


if __name__ == "__main__":
    main()
