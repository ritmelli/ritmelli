"""O detector de ataques dos testes de passagem (o dev/bumbo.py e o dev/testa_passagem.py), independente do pente do
motor: o sinal de uma faixa (o grave abaixo de 120 Hz, o do bumbo, ou outra), o nivel dele em janelas de 5 ms, e cada
subida de 9 dB em 25 ms perto do nivel forte do trecho e um ataque, marcado onde o nivel comeca a subir. A linha de
ataques de uma musica e a fase, no periodo da batida dela, em que mais ataques caem (o bumbo do rap e sincopado: um
bumbo solto no contratempo nao muda a linha).

So numpy e scipy: nao le a prateleira (o pastas.LIB, que e do dev/bumbo.py) nem importa o motor, e o testa_passagem
roda igual contra o motor de qualquer pasta."""
import numpy as np
from scipy import signal

SR = 48000
TOL = 0.040        # ataque ate 40 ms da linha conta como em cima dela
BUMBO = (None, 120.0)


def filtro(banda, sr=SR, ordem=4):
    """O filtro (sos) da faixa (de, ate) em Hz; None num lado e sem corte ali."""
    de, ate = banda
    if de is None:
        return signal.butter(ordem, ate, "lowpass", fs=sr, output="sos")
    if ate is None:
        return signal.butter(ordem, de, "highpass", fs=sr, output="sos")
    return signal.butter(ordem, [de, ate], "bandpass", fs=sr, output="sos")


LP = filtro(BUMBO)


def ataques(x, sos=LP, sr=SR, com_nivel=False, no_pico=False):
    """Os ataques de x (mono) na faixa do filtro sos, em s desde o comeco de x; com_nivel, tambem o pico de cada um
    (dB do nivel de 5 ms nos 60 ms depois dele). no_pico: o ataque marcado no pico desses 60 ms, e nao no comeco da
    subida: o audio que passou pela Rubber Band tem um pre-eco de dezenas de ms antes do ataque, que adianta o comeco
    da subida, mas nao o pico."""
    g = signal.sosfiltfilt(sos, x)
    passo = sr // 1000
    e = np.sqrt(np.convolve(g * g, np.ones(sr // 200) / (sr // 200), mode="same"))[::passo]  # 1 valor por ms
    db = 20 * np.log10(e + 1e-6)
    sobe = np.full_like(db, -99.0)
    sobe[25:] = db[25:] - db[:-25]
    forte = np.percentile(db, 95)
    cand = np.nonzero((sobe > 9) & (db > forte - 18))[0]
    picos = []
    for i in cand:
        if picos and i - picos[-1][-1] <= 150:
            picos[-1].append(i)
        else:
            picos.append([i])
    # o ataque vale onde o nivel comeca a subir (3 dB acima do vale de antes), nao no meio da subida: o bumbo
    # grave e comprido sobe por dezenas de ms (o do Otonoke marcava 58 ms depois do ataque e reprovava a
    # primeira nota do Lose Yourself, que caiu certa)
    ts = []
    for grupo in map(np.array, picos):
        i = int(grupo[int(np.argmax(sobe[grupo]))])
        j0 = max(0, i - 60)
        vale = j0 + int(np.argmin(db[j0:i]))
        acima = np.nonzero(db[vale:i + 1] > db[vale] + 3)[0]
        ts.append(vale + (acima[0] if len(acima) else i - vale))
    ts = np.array(ts, int)
    if no_pico:
        ts = np.array([t + int(np.argmax(db[t:t + 60])) for t in ts], int)
    if not com_nivel:
        return ts / 1000.0
    return ts / 1000.0, np.array([float(db[t:t + 60].max()) for t in ts])


def bumbos(x):
    """Os bumbos de x (mono), em s desde o comeco de x."""
    return ataques(x, LP)


def desvio(ts, f, p):
    """O desvio de cada t ate a linha mais perto da grade (fase f, periodo p), de -p/2 a p/2."""
    return (ts - f + p / 2) % p - p / 2


def grade(ts, p):
    """A linha de ataques (fase em s) no periodo p: a fase, entre as dos proprios ataques, com mais ataques a ate
    TOL dela (afinada pela media deles); e quantos caem nela e no meio tempo dela."""
    cont = [int((np.abs(desvio(ts, t, p)) < TOL).sum()) for t in ts]
    t = ts[int(np.argmax(cont))]
    d = desvio(ts, t, p)
    f = (t + d[np.abs(d) < TOL].mean()) % p
    d = desvio(ts, f, p)
    return f, int((np.abs(d) < TOL).sum()), int((np.abs(np.abs(d) - p / 2) < TOL).sum())


def veredito(d, p):
    """O veredito dos desvios d (s, de -p/2 a p/2) contra a linha de periodo p: "no tempo", "contratempo" ou "fora".
    Pela mediana do desvio em modulo: no contratempo os desvios caem dos dois lados de meio periodo (-p/2 e +p/2), e
    a mediana com o sinal daria perto de zero."""
    d = np.abs(np.atleast_1d(d))
    if np.median(d) < TOL:
        return "no tempo"
    if np.median(np.abs(d - p / 2)) < TOL:
        return "contratempo"
    return "fora"
