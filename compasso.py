"""O 1 do compasso para a passagem de DJ (o DJ deixa o compasso terminar antes de jogar para a
outra): as batidas e os 1 de um trecho de musica pelo beat_this (CPJKU, 2024, rede treinada em batida e compasso),
rodando em ONNX, sem PyTorch.

Por que a rede e nao um juiz nosso como o do batida.py: contra o gabarito dela em 280 janelas firmes de 20 musicas, o
melhor juiz de numpy (bumbo contra caixa para o par 1 e 3, mudanca de acorde e de baixo para o 1) acertava 71% e so
ficava sem erro em 13% das janelas (o bumbo do Overdose bate mais forte no 2 e no 4, o do Stay With Me no 3).

O modelo (compasso.onnx, ~83 MB, no git) sai do dev/exporta_compasso.py; sem ele, uns() devolve None e a
passagem segue sem o 1. A entrada e a mesma da rede original (mel de 128 faixas a 22050 Hz, 50 quadros por segundo,
log1p(1000 x)), refeita em numpy; a saida passa pelo pos-processamento minimo dela (pico local de 7 quadros com logit
acima de 0, o 1 grudado na batida mais perto)."""
import functools
import threading
from pathlib import Path

import numpy as np
from scipy import signal

MODELO = Path(__file__).resolve().parent / "modelos" / "compasso.onnx"
SR_REDE = 22050
NFFT, HOP = 1024, 441   # 50 quadros por segundo
MELS, F_MIN, F_MAX = 128, 30.0, 11000.0
PEDACO, BORDA = 1500, 6  # a rede ve 30 s por vez; as bordas de cada pedaco se descartam
FPS = SR_REDE / HOP
THREADS = 2              # o VRChat roda no mesmo PC

_sessao = None
_trava = threading.Lock()


def _hz_mel(f):
    """Escala mel do Slaney (linear ate 1 kHz, log depois), como o torchaudio com mel_scale='slaney'."""
    f = np.asarray(f, float)
    m = f / (200.0 / 3)
    return np.where(f >= 1000.0, 15.0 + np.log(np.maximum(f, 1e-9) / 1000.0) / (np.log(6.4) / 27), m)


def _mel_hz(m):
    m = np.asarray(m, float)
    return np.where(m >= 15.0, 1000.0 * np.exp((np.log(6.4) / 27) * (m - 15.0)), m * (200.0 / 3))


def _banco_mel():
    """Os filtros triangulares (faixas de frequencia x 128), sem normalizar a area, como o MelSpectrogram."""
    freqs = np.linspace(0, SR_REDE // 2, NFFT // 2 + 1)
    pts = _mel_hz(np.linspace(_hz_mel(F_MIN), _hz_mel(F_MAX), MELS + 2))
    dif = np.diff(pts)
    rampa = pts[None, :] - freqs[:, None]
    desce = -rampa[:, :-2] / dif[:-1]
    sobe = rampa[:, 2:] / dif[1:]
    return np.maximum(0.0, np.minimum(desce, sobe)).astype(np.float32)


_MEL = _banco_mel()


@functools.lru_cache(maxsize=4)
def _passa_baixa(sr):
    """O filtro da reamostragem para 22050 Hz com a resposta do soxr que a rede viu no treino (plano ate ~10,2 kHz,
    -3 dB em 10,5 kHz, -100 dB em 11 kHz): com o filtro padrao do resample_poly, que deixa passar ate perto de 11 kHz,
    a ultima faixa da mel saia 2,3 acima (de ~9)."""
    g = np.gcd(int(sr), SR_REDE)
    sobe, desce = SR_REDE // g, int(sr) // g
    fs = sr * sobe
    return sobe, desce, signal.firwin(int(6.6 * fs / 700.0) | 1, 10550.0, width=700.0, fs=fs)


def espectro(x, sr):
    """A entrada da rede: (quadros, 128) do audio x (mono ou estereo)."""
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = np.asarray(x, np.float64)
    if sr != SR_REDE:
        sobe, desce, h = _passa_baixa(int(sr))
        x = signal.resample_poly(x, sobe, desce, window=h)
    x = np.pad(x, NFFT // 2, mode="reflect")  # center=True do torch.stft
    n = 1 + (len(x) - NFFT) // HOP
    janela = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(NFFT) / NFFT)  # hann periodica
    quadros = np.lib.stride_tricks.as_strided(x, (n, NFFT), (x.strides[0] * HOP, x.strides[0]))
    mag = np.abs(np.fft.rfft(quadros * janela, axis=1)) / np.sqrt(NFFT)  # normalized='frame_length'
    return np.log1p(1000.0 * (mag @ _MEL)).astype(np.float32)


def _abre():
    global _sessao
    with _trava:
        if _sessao is None:
            import onnxruntime as ort
            op = ort.SessionOptions()
            op.intra_op_num_threads = THREADS
            op.inter_op_num_threads = 1
            # sem a arena e o padrao de memoria: com eles o processo ficava com 0,9 a 1,6 GB depois de analisar 30 s
            # (a atencao de 1500 x 1500 quadros vai inteira para a memoria); sem eles volta a ~160 MB, com pico de ~760
            # MB durante a analise (~1,2 s)
            op.enable_cpu_mem_arena = False
            op.enable_mem_pattern = False
            _sessao = ort.InferenceSession(str(MODELO), op, providers=["CPUExecutionProvider"])
    return _sessao


def abre_ja():
    """Abre o modelo agora, fora da hora do audio (o motor chama ao ligar): abrir segura o interpretador ~0,6 s, e o
    som que estiver tocando estala. Sem o modelo ou o onnxruntime, nada."""
    if MODELO.exists():
        try:
            _abre()
        except ImportError:
            pass


def fecha():
    """Solta o modelo (~100 MB). O motor nao solta mais (reabrir no plano estalava o audio); fica para quem mede
    num processo a parte e para os testes."""
    global _sessao
    with _trava:
        _sessao = None


def logits(spect):
    """(batida, um) por quadro, em pedacos de 30 s como a rede foi treinada (o primeiro pedaco vale na sobreposicao)."""
    s = _abre()
    n = len(spect)
    inicios = np.arange(-BORDA, n - BORDA, PEDACO - 2 * BORDA)
    if n > PEDACO - 2 * BORDA:
        inicios[-1] = n - (PEDACO - BORDA)
    b = np.full(n, -1000.0, np.float32)
    u = np.full(n, -1000.0, np.float32)
    for i0 in inicios[::-1]:
        pedaco = spect[max(i0, 0):min(i0 + PEDACO, n)]
        pedaco = np.pad(pedaco, ((max(0, -i0), max(0, min(BORDA, i0 + PEDACO - n))), (0, 0)))
        pb, pu = s.run(None, {"spect": pedaco[None]})
        pb, pu = pb[0][BORDA:-BORDA], pu[0][BORDA:-BORDA]
        a = i0 + BORDA
        m = min(len(pb), n - a)
        b[a:a + m], u[a:a + m] = pb[:m], pu[:m]
    return b, u


def _picos(lg):
    """Os quadros com logit acima de 0 que sao o maximo em +-3 quadros, com vizinhos colados virando a media."""
    from scipy.ndimage import maximum_filter1d
    p = np.nonzero((lg == maximum_filter1d(lg, 7, mode="constant", cval=-1000.0)) & (lg > 0))[0]
    r = []
    for q in p:
        if r and q - r[-1][-1] <= 1:
            r[-1].append(q)
        else:
            r.append([q])
    return np.array([np.mean(g) for g in r])


def uns(x, sr):
    """(batidas, uns) em s desde o comeco de x, ou None sem o modelo ou o onnxruntime."""
    if not MODELO.exists():
        return None
    try:
        b, u = logits(espectro(x, sr))
    except ImportError:
        return None
    bt = _picos(b) / FPS
    ut = _picos(u) / FPS
    if len(bt):
        ut = np.unique(bt[np.abs(bt[None, :] - ut[:, None]).argmin(axis=1)]) if len(ut) else ut
    return bt, ut
