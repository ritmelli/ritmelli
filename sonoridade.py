"""A sonoridade de cada disco e o ganho automatico das musicas mais baixas.

Medidor: o LUFS integrado (EBU R128, ITU-R BS.1770-4) do audio estereo a 48 kHz que o motor decodifica, aos pedacos:
ponderacao K, blocos de 400 ms com passo de 100 ms, porta absoluta em -70 LUFS e relativa 10 LU abaixo da media. E a
medida do comeco do stream, que o leitor do motor vai passando bloco a bloco. O arquivo inteiro se mede pelo ebur128 do
ffmpeg (mede_arquivo), num processo a parte e abaixo do normal: o calculo no processo do servidor segura o interpretador
que o audio usa (por isso o andamento tambem mede fora). Os dois batem em 0,05 LU (dev/testa_ganho.py).

ganho_db: so sobe a musica mais baixa que o ALVO, ate o TETO.

Limitador: o que o ganho acrescentou nao leva o pico acima de 0 dBFS. Antecipa LIMITE_ANTES amostras (a musica sai esse
tanto atrasada, sempre, para o atraso nao mudar quando ele age): a reducao desce em rampa ate o pico e volta devagar.
Disco sem ganho passa igual, mesmo o que ja decodifica acima de 0 dBFS (muita musica alta: +3,6 dBFS no The Real Slim
Shady): o teto de cada amostra e o maior entre 0 dBFS e ela mesma sem o ganho.
"""
import re
import subprocess

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy import signal

SR = 48000
# a ponderacao K da BS.1770 a 48 kHz (a mesma do fx.KPeso): prateleira de agudo e passa-alta
K = np.array([[1.53512485958697, -2.69169618940638, 1.19839281085285, 1.0, -1.69065929318241, 0.73248077421585],
              [1.0, -2.0, 1.0, 1.0, -1.99004745483398, 0.99007225036621]])
PASSO = SR // 10  # 100 ms
# LUFS: a musica mais baixa sobe ate aqui (o alvo do modo "Alto" do Spotify, que tambem sobe a baixa com
# limitador; na prateleira de 14/11 a mediana das musicas era -9,3 e o Sultans of Swing, a -14,1, limitava
# acima de 3 dB 0,2% do tempo com -11 e 2,7% com -10)
ALVO = -11.0
TETO = 6.0  # dB: o mais que o ganho sobe
LIMITE_ANTES = 96  # amostras (2 ms) que o limitador ve adiante
LIMITE_VOLTA_S = 0.15  # o limitador volta de 6 dB de reducao a nenhuma em ~isso


class Medidor:
    """O LUFS integrado do que passou por ele (estereo float, n x 2, a 48 kHz)."""

    def __init__(self):
        self.zi = np.zeros((K.shape[0], 2, 2))
        self.soma, self.n = 0.0, 0  # o pedaco de 100 ms em curso
        self.sub = []  # a potencia (soma dos dois canais) de cada 100 ms fechado
        self.pico = 0.0
        self.amostras = 0

    def __call__(self, x):
        x = np.asarray(x, np.float64)
        if not len(x):
            return
        self.pico = max(self.pico, float(np.max(np.abs(x))))
        self.amostras += len(x)
        y, self.zi = signal.sosfilt(K, x, axis=0, zi=self.zi)
        p = np.sum(y * y, axis=1)
        i = 0
        while i < len(p):
            k = min(PASSO - self.n, len(p) - i)
            self.soma += float(np.sum(p[i:i + k]))
            self.n += k
            i += k
            if self.n == PASSO:
                self.sub.append(self.soma / PASSO)
                self.soma, self.n = 0.0, 0

    @property
    def segundos(self):
        return self.amostras / SR

    def lufs(self):
        """O LUFS integrado ate aqui, ou None (menos de 400 ms, ou tudo abaixo da porta de -70)."""
        s = np.array(self.sub)
        if len(s) < 4:
            return None
        z = (s[:-3] + s[1:-2] + s[2:-1] + s[3:]) / 4  # blocos de 400 ms, passo de 100 ms
        z = z[-0.691 + 10 * np.log10(z + 1e-30) > -70]
        if not len(z):
            return None
        rel = -0.691 + 10 * np.log10(np.mean(z)) - 10
        z = z[-0.691 + 10 * np.log10(z) > rel]
        return float(-0.691 + 10 * np.log10(np.mean(z)))


def ganho_db(lufs):
    """O ganho do disco (dB): so a mais baixa que o ALVO sobe, ate o TETO; sem medida, nada."""
    if lufs is None:
        return 0.0
    return float(min(TETO, max(0.0, ALVO - lufs)))


def mede_arquivo(path, ffmpeg="ffmpeg", criacao=0, startupinfo=None, limite_s=600):
    """O LUFS integrado do arquivo inteiro, decodificado como o motor decodifica (estereo, 48 kHz), pelo ebur128 do
    ffmpeg; None se o ffmpeg nao leu ou o arquivo e so silencio."""
    try:
        r = subprocess.run([ffmpeg, "-nostats", "-hide_banner", "-i", str(path), "-vn", "-ac", "2", "-ar", str(SR),
                            "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=limite_s,
                           creationflags=criacao, startupinfo=startupinfo)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.findall(r"^\s*I:\s+(-?[\d.]+|-inf) LUFS", r.stderr, re.M)
    if r.returncode != 0 or not m or m[-1] == "-inf" or float(m[-1]) <= -70:
        return None
    return float(m[-1])


class Limitador:
    """O limitador da musica do motor: a saida e a entrada atrasada `antes` amostras, com a reducao que deixa cada
    amostra ate o maior entre `teto` e ela mesma sem o ganho (som e cru, estereo n x 2). A reducao de cada amostra e o
    menor pedido das `antes` seguintes, numa media movel do mesmo tamanho: desce em rampa e chega ao pico ja no
    tamanho certo, sem passar. Depois volta em linha reta, `volta` por amostra. Nada aloca alem dos blocos."""

    def __init__(self, antes=LIMITE_ANTES, teto=1.0, volta_s=LIMITE_VOLTA_S):
        self.d, self.teto = int(antes), float(teto)
        self.volta = 0.5 / (volta_s * SR)  # de -6 dB (0,5) a nada em volta_s
        self.hist = np.zeros((self.d, 2), np.float32)  # as ultimas `antes` amostras que entraram e ainda nao sairam
        self.pede = np.ones(self.d)  # a reducao que cada uma delas pede
        self.mins = np.ones(self.d)  # o menor pedido adiante das ultimas `antes` que sairam (a media movel)
        self.g = 1.0  # a reducao da ultima amostra que saiu
        self.reducao_db = 0.0  # a maior do ultimo bloco, para quem quiser mostrar

    def __call__(self, som, cru=None):
        """O bloco limitado (o de `antes` amostras atras); cru None = sem ganho nenhum (o proprio som)."""
        n, d = len(som), self.d
        ext = np.concatenate([self.hist, som])
        p = np.max(np.abs(som), axis=1)
        if p.max() > self.teto:
            teto = np.maximum(self.teto, np.max(np.abs(som if cru is None else cru), axis=1))
        else:
            teto = self.teto
        pede = np.minimum(1.0, teto / np.maximum(p, 1e-30))
        self.hist = ext[n:].copy()
        if self.g >= 1.0 and pede.min() >= 1.0 and self.pede.min() >= 1.0 and self.mins.min() >= 1.0:
            self.pede = self.pede if n < d else np.ones(d)
            self.reducao_db = 0.0
            return ext[:n]  # nada a reduzir: so o atraso
        r = np.concatenate([self.pede, pede])
        m = sliding_window_view(r, d + 1).min(axis=1)  # o menor pedido de cada saida e das `antes` seguintes
        mm = np.concatenate([self.mins, m])
        g = sliding_window_view(mm, d + 1).mean(axis=1)  # a rampa ate o pico
        i = np.arange(1, n + 1)
        g = np.minimum(np.minimum.accumulate(g - self.volta * i) + self.volta * i, self.g + self.volta * i)
        g = np.minimum(g, 1.0)
        self.pede, self.mins, self.g = r[n:].copy(), mm[n:].copy(), float(g[-1])
        self.reducao_db = float(-20 * np.log10(max(g.min(), 1e-6)))
        return (ext[:n] * g[:, None]).astype(np.float32)
