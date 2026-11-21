"""A troca de voz ao vivo do pedal de troca de voz (#129): a voz de quem fala vira a de uma das vozes do
ritmelli-voices, bloco a bloco, sem PyTorch (numpy e ONNX Runtime: o DirectML na placa de video, ou o processador).

Os modelos vem de duas releases do ritmelli-voices (ver o vozes.py, que baixa):
- a engine: o ContentVec (contentvec_n22080_fp16.onnx: o conteudo da fala, sem a voz de quem fala), o FCPE
  (fcpe_fp16.onnx: o tom), e o ref.npz e o meta.json (as constantes do mel e dos reamostradores);
- a voz: o enc_p e o decodificador do RVC dela (<nome>_encp_q334_fp16.onnx e <nome>_dec_q32_fp16.onnx), exportados para
  a janela fixa deste motor.

O modo e o "fluxo" (o caminho de tempo real do RVC refeito para tocar sem costura audivel): a cada bloco de 80 ms o
ContentVec e o tom rodam numa janela curta, mas cada quadro de 10 ms congela o conteudo e o tom que tinha a CONGELA
quadros do futuro e nunca mais muda; o enc_p roda sobre JANELA_ENCP quadros (o passado guardado mais a ponta fresca)
e o latente de cada quadro congela a EMENDA do futuro; o decodificador roda so numa janela local (DEC_ESQ antes, o
bloco, DEC_DIR depois). O ruido de cada instante e sempre o mesmo e a fase da fonte continua de um bloco para o outro,
entao dois blocos seguidos geram a mesma onda no trecho em comum e a costura e uma passagem curta (MISTURA). A janela
do enc_p vale da frase atual para ca (o silencio acumulado puxa a atencao dele e estraga a voz depois de uma pausa).
A saida segue o volume de quem fala (o rms_mix_rate do RVC), na media de 20 ms.

O atraso do efeito e o bloco (80 ms) mais a EMENDA (300 ms) que o modelo ve de futuro.
"""
import ctypes
import json
import os
from ctypes import wintypes
from math import ceil, gcd

import numpy as np
import onnxruntime as ort

# o ONNX Runtime oficial do Windows liga a telemetria da Microsoft (eventos do Windows): aqui, desligada (PRIVACIDADE.md)
ort.disable_telemetry_events()

f32 = np.float32
SR = 48000             # a voz entra e sai a 48 kHz
N = 3840               # o bloco: 80 ms
EMENDA_S = 0.3         # o futuro que o modelo ve (e o atraso alem do bloco)
EXTRA_S = 1.0          # o passado que o ContentVec ve
MISTURA = 240          # a passagem de um bloco para o outro: 5 ms
JAN_TOM = 16000        # o tom olha o ultimo 1 s (a 16 kHz)
LIMIAR_TOM = 0.1       # confianca do FCPE abaixo disso = sem tom (respiracao e sussurro nao viram nota)
CONGELA = 20           # a idade, em quadros de 10 ms, em que o conteudo e o tom de cada quadro congelam
JANELA_ENCP = 334      # a janela do enc_p, em quadros
DEC_ESQ, DEC_DIR = 12, 12
PAUSA, MARGEM, QMIN, FALA_LARGA = 50, 20, 64, 6   # a frase atual: pausa de 0,5 s; 0,2 s do silencio de antes
SEMENTE = 7
AQUECE, AQUECE_ENXUGA = 4, 2   # passadas de aquecimento (antes e depois de enxugar a RAM)
# a saida segue o volume de quem fala: o ganho fica entre -DESCE e +SOBE dB, chega em ~20 ms (ALFA por quadro) e as
# potencias sao medias de MEDIA_Q quadros
SOBE, DESCE, ALFA, MEDIA_Q = 12.0, 24.0, 0.4, 2


def tempo_real():
    """O processo como audio de tempo real: prioridade alta, sem economia de energia do Windows (EcoQoS) e a thread
    registrada no MMCSS como "Pro Audio". Com a conta leve e em rajadas, o sistema baixa o relogio do processador e da
    placa e a conta de um bloco chega a quadruplicar."""
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    eu = k.GetCurrentProcess()
    k.SetPriorityClass(eu, 0x00000080)  # HIGH_PRIORITY_CLASS

    class Economia(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
    e = Economia(1, 0x1, 0)
    k.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.SetProcessInformation(eu, 4, ctypes.byref(e), ctypes.sizeof(e))  # 4 = ProcessPowerThrottling
    mmcss()


def mmcss():
    """A thread que chama passa a ser de audio ("Pro Audio") no agendador do Windows."""
    av = ctypes.WinDLL("avrt")
    av.AvSetMmThreadCharacteristicsW.restype = wintypes.HANDLE
    av.AvSetMmThreadCharacteristicsW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    av.AvSetMmThreadCharacteristicsW("Pro Audio", ctypes.byref(wintypes.DWORD(0)))


def enxuga_ram():
    """Os pesos ja estao na placa: o Windows tira do conjunto de trabalho o que o processo nao toca mais."""
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentProcess.restype = wintypes.HANDLE
    p = ctypes.WinDLL("psapi")
    p.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    p.EmptyWorkingSet(k.GetCurrentProcess())


def _reamostrador(nucleo, de, para, largura):
    """O reamostrador do RVC, com o nucleo do ref.npz: cada pedaco sozinho, com zeros alem das bordas."""
    g = gcd(de, para)
    de, para = de // g, para // g
    nuc = np.ascontiguousarray(nucleo[:, 0, :].T.astype(f32))  # (K, para)

    def f(x):
        y = np.pad(x, (largura, largura + de))
        q = np.lib.stride_tricks.sliding_window_view(y, nuc.shape[0])[::de]
        return (q @ nuc).reshape(-1)[: ceil(para * len(x) / de)].astype(f32)
    return f


def grosso_de(f0):
    """O tom em Hz -> a nota grossa (1 a 255) que o enc_p recebe."""
    return np.round(np.clip((1127.0 * np.log(1.0 + f0 / 700.0) - 50.0) * 254 / (1100.0 - 50.0) + 1, 1, 255)).astype(np.int64)


def _acha(pasta, fim):
    nomes = sorted(n for n in os.listdir(pasta) if n.endswith(fim))
    if len(nomes) != 1:
        raise FileNotFoundError(f"{pasta}: expected one *{fim}, found {len(nomes)}")
    return os.path.join(pasta, nomes[0])


class Conversor:
    """O motor de uma voz. bloco(x) recebe N amostras da voz de quem fala (48 kHz) e devolve N da voz convertida, do
    instante que entrou EMENDA_S + 80 ms antes. tom: o deslocamento em semitons (o ajuste do pedal, por voz).
    provedor: "dml" (a placa de video) ou "cpu"."""

    def __init__(self, engine, voz, tom=0.0, provedor="dml"):
        self.provedor = provedor
        prov = ["DmlExecutionProvider", "CPUExecutionProvider"] if provedor == "dml" else ["CPUExecutionProvider"]
        R = np.load(os.path.join(engine, "ref.npz"))
        with open(os.path.join(engine, "meta.json"), encoding="utf-8") as f:
            M = json.load(f)
        self.mm = M["mel"]
        self.MEL_JANELA, self.MEL_BASE_T = R["mel_janela"].astype(f32), R["mel_base"].T.astype(f32)
        self.CENTAVOS = R["centavos"].astype(f32)
        self.SRM, self.POR_QUADRO = int(M["sr_modelo"]), int(M["amostras_por_quadro"])
        self.re_in = _reamostrador(R["re_in_nucleo"], M["re_in"]["de"], M["re_in"]["para"], M["re_in"]["largura"])
        self.re_out = _reamostrador(R["re_out_nucleo"], M["re_out"]["de"], M["re_out"]["para"], M["re_out"]["largura"])

        # os tamanhos (16 kHz, quadros de 10 ms = 160 amostras)
        self.CF = int(EMENDA_S * SR)
        b16, cf16, ex16 = N // 3, self.CF // 3, int(EXTRA_S * 16000)
        self.conv_n = b16 + ex16 + cf16
        self.QUADROS = self.conv_n // 160
        self.P, self.FUT = b16 // 160, cf16 // 160          # o passo e o futuro, em quadros
        self.DL = DEC_ESQ + self.P + DEC_DIR                # a janela do decodificador
        self.I0 = JANELA_ENCP - (self.FUT + self.P + DEC_ESQ)
        self.AF = int(round(N / SR * self.SRM))             # amostras do modelo por bloco
        self.QMIN = max(QMIN, self.FUT + self.P + DEC_ESQ + 8)
        self.IDX = np.arange(JANELA_ENCP)
        self.fator = f32(2 ** (float(tom) / 12))

        so = ort.SessionOptions()
        so.log_severity_level = 3
        if provedor == "dml":
            so.enable_mem_pattern = False
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.s_cont = self._sessao(_acha(engine, f"contentvec_n{self.conv_n}_fp16.onnx"), so, prov)
        self.s_tom = ort.InferenceSession(_acha(engine, "fcpe_fp16.onnx"), so, providers=prov)
        self.s_encp = self._sessao(_acha(voz, f"_encp_q{JANELA_ENCP}_fp16.onnx"), so, prov, fixar=True)
        self.s_dec = self._sessao(_acha(voz, f"_dec_q{self.DL}_fp16.onnx"), so, prov, fixar=True)
        self.ENT_DEC = self.s_dec.get_inputs()[0].name
        self._zera(primeira=True)
        rng = np.random.default_rng(0)
        for _ in range(AQUECE):
            self.bloco((rng.standard_normal(N) * 0.05).astype(f32))
        if os.name == "nt":
            enxuga_ram()
        for _ in range(AQUECE_ENXUGA):  # o que o motor usa volta para a RAM aqui, antes do primeiro bloco de verdade
            self.bloco((rng.standard_normal(N) * 0.05).astype(f32))
        self._zera()

    def ajusta_tom(self, tom):
        """O deslocamento novo (semitons), com a linha do tempo zerada: o que ja estava convertido com o tom de antes
        nao emenda no de agora. Chamado da mesma thread do bloco()."""
        self.fator = f32(2 ** (float(tom) / 12))
        self._zera()

    @staticmethod
    def _sessao(caminho, so, prov, fixar=False):
        """Uma sessao do modelo. fixar: os tamanhos livres das entradas em 1 (o lote do decodificador saiu livre da
        exportacao, e com tamanho livre o DirectML nao compila o grafo inteiro: roda no a no, 2 vezes mais lento)."""
        so_a = ort.SessionOptions()
        so_a.log_severity_level, so_a.enable_mem_pattern, so_a.execution_mode = (so.log_severity_level, so.enable_mem_pattern,
                                                                                 so.execution_mode)
        if fixar:
            leve = ort.SessionOptions()
            leve.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
            ver = ort.InferenceSession(caminho, leve, providers=["CPUExecutionProvider"])
            for nome in {d for i in ver.get_inputs() for d in i.shape if isinstance(d, str)}:
                so_a.add_free_dimension_override_by_name(nome, 1)
            del ver
        return ort.InferenceSession(caminho, so_a, providers=prov)

    def _zera(self, primeira=False):
        """A linha do tempo comeca como silencio. Na primeira vez, o ruido de cada instante (o que o aquecimento anda
        fica andado: o ruido so precisa ser o mesmo para o mesmo instante dentro da sessao)."""
        self.conv = np.zeros(self.conv_n, f32)
        self.pitchf = np.zeros(self.QUADROS + 1, f32)
        self.tom_congelado = np.zeros(0, f32)
        self.guarda = np.zeros(MISTURA, f32)
        self.fase = 0.0
        self.nb = 0
        if primeira:
            self.rz = np.random.default_rng(7).standard_normal((1, 192, JANELA_ENCP)).astype(f32)
            self.rf = np.random.default_rng(8).standard_normal((self.FUT + self.P + DEC_ESQ) * self.POR_QUADRO).astype(f32)
            self.fe = np.zeros((1, JANELA_ENCP, 768), f32)
            self.f0 = np.zeros(JANELA_ENCP, f32)
            self.z = np.zeros((1, 192, JANELA_ENCP), f32)
            # o volume seguido
        self.s_ent = np.zeros(N + self.CF, f32)
        self.s_g, self.s_pe, self.s_ps = 0.0, 1e-10, 1e-10
        if not primeira:
            fe = self.s_cont.run(None, {"audio": self.conv[None]})[0]
            self.fe[0] = fe[0, fe.shape[1] // 2]
            self.f0[:] = 0
            m, lg = self.s_encp.run(None, {"phone": self.fe, "pitch": grosso_de(self.f0)[None]})
            self.z[:] = m + np.exp(lg) * self.rz * f32(0.66666)

    def mel(self, x):
        mm = self.mm
        win, salto, nfft = mm["win"], mm["salto"], mm["n_fft"]
        esq = (win - salto) // 2
        dire = max((win - salto + 1) // 2, win - len(x) - esq)
        y = np.pad(x, (esq, dire), mode="reflect" if dire < len(x) else "constant")
        q = np.lib.stride_tricks.sliding_window_view(y, nfft)[::salto]
        mag = np.sqrt(np.abs(np.fft.rfft(q * self.MEL_JANELA, axis=1)) ** 2 + 1e-9).astype(f32)
        m = np.log(np.maximum(mag @ self.MEL_BASE_T, mm["piso"])).astype(f32)
        q_ = len(x) // salto + 1
        if q_ > len(m):
            m = np.concatenate([m, m[-1:]])
        return m[None, :q_]

    def tom(self, x):
        """O tom de cada quadro de 10 ms do trecho (Hz; 0 = sem tom) e a confianca de cada um."""
        y = self.s_tom.run(None, {"mel": self.mel(x)})[0][0].astype(f32)
        pico = y.argmax(1)
        idx = np.clip(np.arange(9)[None] + pico[:, None] - 4, 0, self.mm["saidas"] - 1)
        sel = np.take_along_axis(y, idx, 1)
        soma = sel.sum(1)  # em meia precisao o quadro de silencio sai todo em zero: confianca 0, sem tom logo abaixo
        cent = (self.CENTAVOS[idx] * sel).sum(1) / np.where(soma > 0, soma, 1)
        conf = y.max(1)
        return np.where(conf <= LIMIAR_TOM, 0.0, 10.0 * 2 ** (cent / 1200.0)).astype(f32), conf

    def _segue(self, bloco):
        """O ganho (por amostra) que leva o volume do bloco que sai ao da voz de quem fala no instante que ele representa
        (a saida quase muda nunca sobe, e o pico fica em -1 dBFS)."""
        qn = N // 480
        pos = len(self.s_ent) - (N + self.CF) + np.arange(qn * 480)
        e = self.s_ent[pos].reshape(qn, 480)
        s = bloco[:qn * 480].reshape(qn, 480)
        pe, ps = (e * e).mean(axis=1), (s * s).mean(axis=1)
        teto = 20 * np.log10(0.89 / (np.abs(s).max(axis=1) + 1e-9))
        media = 1.0 / MEDIA_Q
        gq = [self.s_g]
        for i in range(qn):
            self.s_pe += (float(pe[i]) - self.s_pe) * media
            self.s_ps += (float(ps[i]) - self.s_ps) * media
            a = float(np.clip(10 * np.log10(self.s_pe / self.s_ps), -DESCE, SOBE))
            if ps[i] < 10 ** -5.5:
                a = min(a, 0.0)
            if a > teto[i] and teto[i] < self.s_g:  # so o teto do pico desce na hora; o resto anda pela media
                self.s_g = float(teto[i])
            else:
                self.s_g += (min(a, float(teto[i])) - self.s_g) * ALFA
            gq.append(self.s_g)
        centros = np.concatenate([[-240.0], np.arange(qn) * 480 + 240.0])
        return (10 ** (np.interp(np.arange(len(bloco)), centros, gq) / 20)).astype(f32)

    def bloco(self, x48):
        """N amostras da voz de quem fala -> N da voz convertida."""
        x48 = np.ascontiguousarray(x48, f32)
        x16 = self.re_in(x48)
        self.conv[:-len(x16)] = self.conv[len(x16):].copy()
        self.conv[-len(x16):] = x16
        self.s_ent[:-N] = self.s_ent[N:].copy()
        self.s_ent[-N:] = x48

        # o tom: so da janela mais recente; so os quadros que ainda vao sair mudam
        f0, _ = self.tom(self.conv[-JAN_TOM:])
        cru = f0[3:-1] if len(f0) > 4 else f0
        # o tom de quem fala (Hz, 0 = sem tom) nos P quadros que congelam neste bloco: cada quadro passa por aqui uma vez,
        # ja com os 200 ms de futuro (o ajuste do tom do pedal mede por ele)
        self.tom_congelado = cru[-(CONGELA + self.P):-CONGELA].copy() if len(cru) >= CONGELA + self.P else cru[:0].copy()
        f0 = f0 * self.fator
        iff = f0[3:-1] if len(f0) > 4 else f0
        self.pitchf[:-self.P] = self.pitchf[self.P:].copy()
        k = min(len(iff), CONGELA + self.P)
        self.pitchf[-k:] = iff[-k:]

        # o conteudo
        fe = self.s_cont.run(None, {"audio": self.conv[None]})[0]
        fe = np.repeat(np.concatenate([fe, fe[:, -1:]], 1), 2, axis=1)[:, :self.QUADROS].astype(f32)

        # a linha do tempo guardada anda um bloco; a ponta que ainda muda recebe o conteudo e o tom de agora
        k = CONGELA + self.P
        self.fe[0, :-self.P] = self.fe[0, self.P:].copy()
        self.f0[:-self.P] = self.f0[self.P:].copy()
        self.fe[0, -k:] = fe[0, -k:]
        self.f0[-k:] = self.pitchf[-k:]

        # a janela do enc_p vale da frase atual para ca: o resto, para tras, repete esse trecho
        fala = np.lib.stride_tricks.sliding_window_view(np.pad(self.f0 > 0, FALA_LARGA), 2 * FALA_LARGA + 1).any(axis=1)
        sem = np.flatnonzero(~fala)
        v0 = 0
        if len(sem) and fala.any():
            corridas = np.split(sem, np.flatnonzero(np.diff(sem) > 1) + 1)
            longas = [c for c in corridas if len(c) >= PAUSA and c[-1] < JANELA_ENCP - 1 and fala[c[-1] + 1:].any()]
            if longas:
                v0 = int(longas[-1][-1]) + 1 - MARGEM
        elif not fala.any():
            v0 = JANELA_ENCP - self.QMIN
        v0 = int(np.clip(v0, 0, JANELA_ENCP - self.QMIN))
        if v0:
            idx = (self.IDX - JANELA_ENCP) % (JANELA_ENCP - v0) + v0
            m_p, logs_p = self.s_encp.run(None, {"phone": np.ascontiguousarray(self.fe[:, idx]),
                                                 "pitch": grosso_de(self.f0[idx])[None]})
        else:
            m_p, logs_p = self.s_encp.run(None, {"phone": self.fe, "pitch": grosso_de(self.f0)[None]})

        # o ruido do instante depende so do numero do bloco
        novo = np.random.default_rng([SEMENTE, self.nb])
        self.nb += 1
        self.rz[:, :, :-self.P] = self.rz[:, :, self.P:].copy()
        self.rz[:, :, -self.P:] = novo.standard_normal((1, 192, self.P)).astype(f32)
        self.rf[:-self.AF] = self.rf[self.AF:].copy()
        self.rf[-self.AF:] = novo.standard_normal(self.AF).astype(f32)
        kz = self.FUT + self.P  # o latente so muda ate congelar, a EMENDA do futuro
        self.z[:, :, :-self.P] = self.z[:, :, self.P:].copy()
        self.z[:, :, -kz:] = (m_p + np.exp(logs_p) * self.rz * f32(0.66666))[:, :, -kz:]
        i0, dl = self.I0, self.DL
        som = self.s_dec.run(None, {self.ENT_DEC: np.ascontiguousarray(self.z[:, ::-1, i0:i0 + dl]),
                                    "nsff0": np.ascontiguousarray(self.f0[None, i0:i0 + dl]),
                                    "ruido_fonte": np.ascontiguousarray(self.rf[None, :dl * self.POR_QUADRO, None]),
                                    "fase0": np.full((1, 1, 1), self.fase % 1.0, f32)})[0].reshape(-1).astype(f32)
        # na proxima passada a janela do decodificador comeca um bloco adiante: a fase anda o que ele anda
        self.fase = (self.fase + float(self.f0[i0:i0 + self.P].astype(np.float64).sum()) * self.POR_QUADRO / self.SRM) % 1.0

        # 2 quadros a mais de cada lado para o reamostrador nao comecar nem acabar no vazio; a passagem do bloco anterior
        seg = np.clip(som[(DEC_ESQ - 2) * self.POR_QUADRO:(DEC_ESQ + self.P + 2) * self.POR_QUADRO], -1.0, 1.0)
        al = self.re_out(seg)[2 * 480:2 * 480 + N + MISTURA].copy()
        al[:MISTURA] = self.guarda * _SOME + al[:MISTURA] * _ENTRA
        self.guarda[:] = al[N:N + MISTURA]
        y = al[:N]
        return np.ascontiguousarray(y * self._segue(y), f32)


_ENTRA = (np.sin(0.5 * np.pi * np.linspace(0.0, 1.0, MISTURA, dtype=f32)) ** 2).astype(f32)
_SOME = (1 - _ENTRA).astype(f32)
