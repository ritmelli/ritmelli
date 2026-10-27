"""Batida de um trecho de musica para a passagem de DJ: o
andamento, a grade das batidas e se a medicao e firme. O motor so alinha duas musicas quando as duas grades
sao firmes; o resto segue no cruzamento de volume.

O metodo e o classico dos medidores de batida: a forca dos ataques ao longo do tempo (o quanto o espectro
sobe de um quadro para o outro, em escala de log) e a autocorrelacao dela para achar o periodo que se repete.
A confusao comum e com 3/4 ou 4/3 do periodo (o tresillo do pop e do reggaeton bate a cada 3/4 de tempo), entao
o periodo sai de dois juizes: o pico mais forte (puxado para perto de 120 BPM) e o que tem o compasso inteiro
forte (o periodo, o dobro e o quadruplo). Firme = os dois juizes e as duas metades do trecho concordam, a menos
de oitava, a grade cai em cima dos ataques e a caixa nao aponta outro andamento: no 3+3+2 (tresillo, tamborzao do
funk) os dois juizes ainda caem juntos no 4/3 do pulso (o Paper Planes, de 86, media 114,7 firme), e a caixa, que
bate no 2 e no 4, se repete a cada 2 tempos de verdade e nunca na grade falsa. Entre a batida e o contratempo (meio periodo depois), quem decide
e o bumbo: o ataque mais forte do trecho inteiro pode ser o chimbal ou o acorde no contratempo (o comeco do
Overdose, 21/10: a passagem caia no contratempo).
"""
from collections import namedtuple

import numpy as np
from scipy import ndimage, signal

HOP = 512           # quadros de ~10,7 ms a 48 kHz
NFFT = 2048
BPM_MIN, BPM_MAX = 60.0, 200.0
BPM_CENTRO = 120.0  # o andamento mais provavel, para escolher entre o dobro e a metade
OITAVA_DP = 1.0     # largura dessa preferencia, em oitavas
LENTA = 60.0        # a grade sai na oitava de LENTA a 2*LENTA: o tempo forte, nao a colcheia
CONCORDA = 0.02     # dois andamentos concordam ate 2% (a menos de oitava)
PICO_MIN = 0.25     # autocorrelacao minima no periodo (sem isso a batida e fraca demais para alinhar)
FASE_MAX = 0.92     # a segunda melhor fase do pente (longe da primeira) tem de ficar abaixo disso da nota dela
GRAVE_HZ = 150.0    # a faixa do bumbo, que decide entre a batida e o contratempo
GRAVE_DECIDE = 0.8  # o bumbo decide quando o meio tempo mais fraco fica abaixo disso do mais forte no pente dele
PERTO = 0.125       # a fase do trecho curto so anda isso do periodo em volta da grade do trecho longo
CAIXA_HZ = (1500.0, 5000.0)  # a faixa da caixa e da palma
CAIXA_FOLGA = 1.3   # a caixa derruba a medicao quando outro andamento (3/4, 4/3, 2/3, 3/2) bate isso mais forte nela
CAIXA_TROCA = 2.0   # com isso de folga, e as duas metades apontando o mesmo, vale o andamento da caixa
                    # (calibrado 21/10 contra o BPM publicado de 22 musicas e um tap manual no Bota Tudo Em Mim, 130)
TRECHO_MIN_S = 6.0  # menos que isso nao mede

Grade = namedtuple("Grade", "bpm periodo fase firme motivo")
# bpm na oitava lenta; periodo em s; fase = a primeira batida, em s desde o comeco do trecho;
# firme = da para alinhar; motivo = por que nao (ou o resumo da medicao), para o log


def ataques(x, sr, ate_hz=8000.0, de_hz=0.0):
    """A forca dos ataques (um valor por quadro de HOP amostras) do audio mono x, de de_hz a ate_hz (acima de
    8 kHz e ruido para batida; ate GRAVE_HZ, o bumbo; em CAIXA_HZ, a caixa)."""
    _, _, z = signal.stft(x, fs=sr, nperseg=NFFT, noverlap=NFFT - HOP, boundary=None, padded=False)
    s = np.log1p(100.0 * np.abs(z[int(de_hz * NFFT / sr): int(ate_hz * NFFT / sr) + 1]))
    o = np.maximum(np.diff(s, axis=1), 0.0).sum(axis=0)
    o = o - np.convolve(o, np.ones(17) / 17, mode="same")  # tira a tendencia lenta
    return np.maximum(o, 0.0)


def _grave_percussivo(x, sr):
    """A forca dos ataques do grave (ate GRAVE_HZ) so do que e pancada: no espectrograma, o que e largo na
    frequencia (bumbo) fica, o que sustenta no tempo (nota do baixo) sai (mascara de Fitzgerald, filtros de
    mediana). No reggaeton o baixo bate no contratempo e empatava o grave inteiro (o fim do Despacito). Em
    pedacos de 100 quadros: a mediana inteira de uma vez prende o interpretador e o audio do cabo espera."""
    _, _, z = signal.stft(x, fs=sr, nperseg=NFFT, noverlap=NFFT - HOP, boundary=None, padded=False)
    m = np.abs(z[: int(1200.0 * NFFT / sr) + 1])  # ate 1,2 kHz: a mediana na frequencia precisa de vizinhos
    ate = int(GRAVE_HZ * NFFT / sr) + 1
    p = np.empty((ate, m.shape[1]))
    for a in range(0, m.shape[1], 100):
        b0, b1 = max(0, a - 8), min(m.shape[1], a + 108)
        pedaco = m[:, b0:b1]
        h = ndimage.median_filter(pedaco, size=(1, 17))[:ate]
        pc = ndimage.median_filter(pedaco, size=(17, 1))[:ate]
        p[:, a:min(a + 100, m.shape[1])] = (pedaco[:ate] * pc ** 2 / (h ** 2 + pc ** 2 + 1e-12))[:, a - b0:a - b0 + 100]
    s = np.log1p(100.0 * p)
    o = np.maximum(np.diff(s, axis=1), 0.0).sum(axis=0)
    o = o - np.convolve(o, np.ones(17) / 17, mode="same")
    return np.maximum(o, 0.0)


def _autocorr(o):
    o = o - o.mean()
    f = np.fft.rfft(o, 2 * len(o))  # pela FFT: a direta prende o interpretador uns ms, e o audio espera
    ac = np.fft.irfft(f * np.conj(f))[: len(o)]
    return ac / (ac[0] + 1e-9)


def _juizes(ac, fps):
    """(o lag do pico mais forte, o lag do compasso mais forte, a autocorrelacao no primeiro), em quadros."""
    l0 = int(60 * fps / BPM_MAX)
    l1 = min(int(60 * fps / BPM_MIN) + 1, len(ac) // 4)
    lags = np.arange(l0, l1)
    peso = np.exp(-0.5 * (np.log2(60 * fps / lags / BPM_CENTRO) / OITAVA_DP) ** 2)
    w = ac[lags] * peso
    k = int(np.argmax(w))
    pico = float(ac[lags[k]])
    picos = np.nonzero(np.r_[False, (w[1:-1] > w[:-2]) & (w[1:-1] >= w[2:]), False])[0]
    picos = picos[np.argsort(-w[picos])][:6]
    if not len(picos):
        picos = np.array([k])
    eixo = np.arange(len(ac))
    compasso = [sum(np.interp(lags[i] * m, eixo, ac) for m in (1, 2, 4)) * peso[i] for i in picos]
    return float(lags[k]), float(lags[picos[int(np.argmax(compasso))]]), pico


def _lenta(lag, fps):
    """O lag levado para a oitava de LENTA a 2*LENTA BPM."""
    while 60 * fps / lag >= 2 * LENTA:
        lag *= 2
    while 60 * fps / lag < LENTA:
        lag /= 2
    return lag


def _concorda(a, b):
    return min(abs(a / b * m - 1) for m in (0.5, 1.0, 2.0)) <= CONCORDA


def _suave(o):
    return np.convolve(o, signal.windows.gaussian(7, 1.2), mode="same")  # o ataque vira um morrinho


def _notas(o, p, fases):
    """A media dos ataques (ja suaves) em cima de cada pente de periodo p (quadros) que comeca em cada fase."""
    k = np.arange(int((len(o) - 1 - p) // p) + 1)
    return np.interp(fases[:, None] + k[None, :] * p, np.arange(len(o)), o).mean(axis=1)


def _pente(o, lag, afinar=True, perto=None):
    """O periodo e a fase (em quadros) do pente de batidas que mais cai nos ataques, afinando o periodo em
    +-1% (o pico da autocorrelacao so acerta ate meio quadro, e 20 s de batidas afinam mais), a nota dele e a
    da melhor fase longe dela (perto de 1 = a grade pode estar no contratempo). perto (quadros): a fase so
    procura a PERTO do periodo em volta dela."""
    o = _suave(o)
    melhor = (-1.0, lag, 0.0, 0.0)
    for p in lag * np.linspace(0.99, 1.01, 41) if afinar else [lag]:
        fases = np.arange(0.0, p, 0.25)
        nota = _notas(o, p, fases)
        if perto is not None:
            d = np.abs(fases - perto % p)
            nota = np.where(np.minimum(d, p - d) <= PERTO * p, nota, -1.0)
        i = int(np.argmax(nota))
        if nota[i] > melhor[0]:
            d = np.abs(fases - fases[i])
            longe = np.minimum(d, p - d) > 0.15 * p
            rival = float(nota[longe].max() / nota[i]) if longe.any() else 0.0
            melhor = (float(nota[i]), float(p), float(fases[i]), rival)
    nota, p, f, rival = melhor
    return p, f, nota / (float(o.mean()) + 1e-9), rival


def _caixa(x, sr, lag):
    """O andamento (BPM) que a caixa aponta entre o medido e o 3/4, o 4/3, o 2/3 e o 3/2 dele, e quanto mais forte
    ela bate nele que no medido: a autocorrelacao dos ataques da caixa em 2 e 4 periodos (o compasso de 2 e de 4
    tempos), cada candidato na oitava lenta."""
    fps = sr / HOP
    ac = _autocorr(ataques(x, sr, CAIXA_HZ[1], CAIXA_HZ[0]))
    eixo = np.arange(len(ac))
    notas = []
    for r in (1.0, 4 / 3, 3 / 4, 3 / 2, 2 / 3):
        L = _lenta(lag * r, fps)
        notas.append(sum(np.interp(L * m, eixo, ac) for m in (2, 4)) if 4 * L < len(ac) - 1 else -1.0)
    i = int(np.argmax(notas))
    return 60 * fps / (lag * (1.0, 4 / 3, 3 / 4, 3 / 2, 2 / 3)[i]), notas[i] / max(notas[0], 1e-3)


def _bpm(x, sr):
    o = ataques(x, sr)
    fps = sr / HOP
    if len(o) < fps * TRECHO_MIN_S / 2:
        return None, None, 0.0, o
    l1, l2, pico = _juizes(_autocorr(o), fps)
    return 60 * fps / l1, 60 * fps / l2, pico, o


def medir(x, sr):
    """A Grade do audio x (mono ou estereo, float)."""
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = np.asarray(x, np.float32)
    fps = sr / HOP
    if len(x) < sr * TRECHO_MIN_S:
        return Grade(None, None, None, False, "trecho curto")
    b1, b2, pico, o = _bpm(x, sr)
    h = len(x) // 2
    j1, j2 = _bpm(x[:h], sr)[:2], _bpm(x[h:], sr)[:2]  # os dois juizes de cada metade
    m1, m2 = j1[1], j2[1]
    # a caixa no 2 e no 4 e o tempo forte (o que o ouvido chama de andamento): apontando outro com muita folga, e o
    # mesmo nas duas metades, vale ela, e os juizes da forca dos ataques ficam de fora (o bumbo sincopado do
    # Paper Planes e o tamborzao do funk enganam os dois juntos)
    trocou = ""
    outro, forca = _caixa(x, sr, _lenta(60 * fps / b2, fps))
    if not _concorda(outro, b2) and forca >= CAIXA_TROCA:
        lc = _lenta(60 * fps / outro, fps)
        if all(_concorda(_caixa(t, sr, lc)[0], outro) for t in (x[:h], x[h:])):
            trocou = f", a caixa trocou {60 * fps / _lenta(60 * fps / b2, fps):.1f} por {outro:.1f} ({forca:.1f} vezes)"
            ac = _autocorr(o)
            pico = float(max(np.interp(lc, np.arange(len(ac)), ac), np.interp(lc / 2, np.arange(len(ac)), ac)))
            b1 = b2 = m1 = m2 = outro
    elif (not _concorda(b1, b2) and _concorda(outro, b1) and forca >= CAIXA_FOLGA
          and all(any(_concorda(j, b1) for j in jm if j) for jm in (j1, j2))):
        # os juizes discordam e a caixa fica com o do pico: vale ele, se cada metade tiver um juiz com ele (o
        # comeco do Paper Planes: 5 s de intro sem caixa, e a caixa dos 20 s com o 86 a 1,7 vezes)
        trocou = f", a caixa desempatou {b2:.1f} x {b1:.1f} ({forca:.1f} vezes)"
        b2 = m1 = m2 = b1
    lag, fase, nota, rival = _pente(o, _lenta(60 * fps / b2, fps))
    bpm = 60 * fps / lag
    # batida ou contratempo: o meio tempo em que o bumbo cai mais forte
    meios = np.array([fase, (fase + lag / 2) % lag])
    ng = _notas(_suave(ataques(x, sr, GRAVE_HZ)), lag, meios)
    bumbo = bool(ng.min() <= GRAVE_DECIDE * ng.max())
    if not bumbo:  # o baixo empatou os dois meios tempos: so a pancada (sem o baixo que sustenta) decide
        ng = _notas(_suave(_grave_percussivo(x, sr)), lag, meios)
        bumbo = bool(ng.min() <= GRAVE_DECIDE * ng.max())
    if bumbo:
        fase = float(meios[int(np.argmax(ng))])
    resumo = (f"{bpm:.1f} BPM (juizes {b1:.1f}/{b2:.1f}, metades {m1:.1f}/{m2:.1f}, pico {pico:.2f}, "
              f"pente {nota:.1f}, fase rival {rival:.2f}, bumbo {ng.min() / (ng.max() + 1e-9):.2f}"
              f"{', virou a fase' if bumbo and fase != meios[0] else ''}{trocou})")
    if not _concorda(b1, b2):
        return Grade(bpm, lag / fps, fase / fps, False, "juizes discordam: " + resumo)
    if not (_concorda(m1, b2) and _concorda(m2, b2)):
        return Grade(bpm, lag / fps, fase / fps, False, "metades discordam: " + resumo)
    if pico < PICO_MIN:
        return Grade(bpm, lag / fps, fase / fps, False, "batida fraca: " + resumo)
    if rival > FASE_MAX and not bumbo:
        return Grade(bpm, lag / fps, fase / fps, False, "fase ambigua: " + resumo)
    outro, forca = _caixa(x, sr, lag)
    if not trocou and not _concorda(outro, bpm) and forca > CAIXA_FOLGA:
        return Grade(bpm, lag / fps, fase / fps, False, f"a caixa aponta {outro:.1f} BPM ({forca:.1f} vezes): " + resumo)
    return Grade(bpm, lag / fps, fase / fps, True, resumo)


def fase(x, sr, periodo, perto):
    """A fase da grade de periodo dado (em s) no trecho curto x, onde as duas musicas soam juntas: (a primeira
    batida em s desde o comeco de x, a nota do pente). O andamento e o lado da batida (contra o contratempo)
    saem do trecho longo, cuja grade cai em perto (s desde o comeco de x); o trecho curto so afina a posicao em
    volta dela (o pequeno erro do andamento soma ao estender a grade, e o esticamento desvia uns ms). A nota e a
    da melhor fase do trecho, em qualquer lado: ela diz se ha batida ali, nao de que lado (no dembow as pancadas
    fortes caem fora do bumbo, e a nota em volta dele ficava baixa com a batida la)."""
    if x.ndim > 1:
        x = x.mean(axis=1)
    o = ataques(np.asarray(x, np.float32), sr)
    fps = sr / HOP
    _, f, _, _ = _pente(o, periodo * fps, afinar=False, perto=perto * fps)
    nota = _pente(o, periodo * fps, afinar=False)[2]
    return f / fps, nota
