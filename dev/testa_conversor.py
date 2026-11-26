"""Testa o conversor.py (o motor da troca de voz, #129) sem placa de video e sem as vozes de verdade: uma engine e uma
voz de mentira, montadas aqui em ONNX com as mesmas entradas e saidas das do ritmelli-voices, rodando no processador. O
FCPE de mentira diz 150 Hz em todo quadro com som (e nada no silencio), e o decodificador de mentira gera um seno no tom
que recebe, a partir da fase que recebe.

Confere o caminho de ponta a ponta: cada bloco de 80 ms sai com o mesmo tamanho, o tom chega deslocado (150 Hz com +9
sai a 252 Hz), a onda emenda de um bloco no outro sem degrau (a fase continuada e a passagem entre blocos: o seno sai
limpo), o tom_congelado traz o tom de quem fala sem o deslocamento, o ajusta_tom() muda o tom e o silencio sai em
silencio.

    python dev/testa_conversor.py

Precisa do numpy, do onnxruntime e do onnx (requirements-dev.txt). Sai 1 se algo falhar."""
import json
import sys
import tempfile
import unittest
from math import gcd
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto
from onnx import helper as h
from onnx import numpy_helper

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import conversor as C

TOM_HZ = 150.0  # o tom que o FCPE de mentira ouve em todo quadro com som
SRM, POR_QUADRO = 32000, 320
P = C.N // 3 // 160  # o passo, em quadros
CONV_N = C.N // 3 + int(C.EXTRA_S * 16000) + int(C.EMENDA_S * C.SR) // 3
DL = C.DEC_ESQ + P + C.DEC_DIR


def _ini(nome, valor, tipo=np.float32):
    return numpy_helper.from_array(np.asarray(valor, tipo), nome)


def _vi(nome, tipo, forma):
    return h.make_tensor_value_info(nome, tipo, forma)


def _salva(nos, entradas, saidas, inis, caminho):
    m = h.make_model(h.make_graph(nos, Path(caminho).stem, entradas, saidas, inis),
                     opset_imports=[h.make_opsetid("", 17)])
    m.ir_version = 8
    onnx.checker.check_model(m)
    onnx.save(m, str(caminho))


def _nucleo(de, para, largura, k):
    """Um reamostrador de seno cardinal com janela de Hann, no formato do ref.npz (para, 1, k)."""
    g = gcd(de, para)
    de, para = de // g, para // g
    corte = min(1.0, para / de)
    d = (np.arange(k)[None, :] - largura) - np.arange(para)[:, None] * de / para
    jan = np.where(np.abs(d) <= largura + 1, 0.5 * (1 + np.cos(np.pi * d / (largura + 1))), 0.0)
    return (corte * np.sinc(corte * d) * jan)[:, None, :].astype(np.float32)


def monta(pasta):
    """A engine-teste/ e a voz-teste/ de mentira, com os nomes de arquivo que o conversor procura."""
    engine, voz = pasta / "engine-teste", pasta / "voz-teste"
    engine.mkdir()
    voz.mkdir()
    meta = {"re_in": {"de": 48000, "para": 16000, "largura": 19}, "re_out": {"de": SRM, "para": 48000, "largura": 7},
            "mel": {"n_fft": 1024, "win": 1024, "salto": 160, "piso": 1e-05, "stft": False, "saidas": 360},
            "sr_modelo": SRM, "amostras_por_quadro": POR_QUADRO}
    (engine / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    bordas = np.linspace(0, 513, 129).astype(int)
    base = np.zeros((128, 513), np.float32)
    for i in range(128):
        base[i, bordas[i]:bordas[i + 1]] = 1.0 / (bordas[i + 1] - bordas[i])
    np.savez(engine / "ref.npz", mel_janela=np.hanning(1025)[:-1].astype(np.float32), mel_base=base,
             centavos=(1200 * np.log2(TOM_HZ / 10) + 20 * (np.arange(360) - 180)).astype(np.float32),
             re_in_nucleo=_nucleo(48000, 16000, 19, 41), re_out_nucleo=_nucleo(SRM, 48000, 7, 16))
    f = TensorProto.FLOAT

    # o ContentVec: um conteudo fixo
    q = CONV_N // POR_QUADRO - 1
    _salva([h.make_node("Identity", ["c"], ["feats"])], [_vi("audio", f, [1, CONV_N])], [_vi("feats", f, [1, q, 768])],
           [_ini("c", np.full((1, q, 768), 0.01))], engine / f"contentvec_n{CONV_N}_fp16.onnx")

    # o FCPE: o pico no bin do TOM_HZ, com a confianca pelo volume do quadro (o silencio fica abaixo do LIMIAR_TOM)
    linha = np.zeros(360, np.float32)
    linha[176:185] = [0.05, 0.1, 0.2, 0.6, 1.0, 0.6, 0.2, 0.1, 0.05]
    _salva([h.make_node("ReduceMax", ["mel"], ["e"], axes=[2], keepdims=1), h.make_node("Add", ["e", "sete"], ["e7"]),
            h.make_node("Sigmoid", ["e7"], ["conf"]), h.make_node("Mul", ["conf", "linha"], ["latente"])],
           [_vi("mel", f, [1, "T", 128])], [_vi("latente", f, [1, "T", 360])],
           [_ini("sete", [7.0]), _ini("linha", linha.reshape(1, 1, 360))], engine / "fcpe_fp16.onnx")

    # o enc_p: o latente e o conteudo, sem ruido (logs muito negativo)
    jan = C.JANELA_ENCP
    _salva([h.make_node("Slice", ["phone", "ini", "fim", "eixo"], ["p192"]),
            h.make_node("Transpose", ["p192"], ["m"], perm=[0, 2, 1]),
            h.make_node("Mul", ["m", "zero"], ["m0"]), h.make_node("Add", ["m0", "menos10"], ["logs"])],
           [_vi("phone", f, [1, jan, 768]), _vi("pitch", TensorProto.INT64, [1, jan])],
           [_vi("m", f, [1, 192, jan]), _vi("logs", f, [1, 192, jan])],
           [_ini("ini", [0], np.int64), _ini("fim", [192], np.int64), _ini("eixo", [2], np.int64), _ini("zero", [0.0]),
            _ini("menos10", [-10.0])], voz / f"teste_encp_q{jan}_fp16.onnx")

    # o decodificador: um seno no tom de cada quadro (nsff0), a partir da fase0 (em voltas), mudo onde nao ha tom; o
    # lote livre na entrada, como no exportado
    n = DL * POR_QUADRO
    _salva([h.make_node("Reshape", ["nsff0", "f_col"], ["f2"]), h.make_node("Tile", ["f2", "rep"], ["f3"]),
            h.make_node("Reshape", ["f3", "f_lin"], ["fq"]), h.make_node("Div", ["fq", "srm"], ["inc"]),
            h.make_node("CumSum", ["inc", "eixo0"], ["cs"]), h.make_node("Reshape", ["fase0", "um"], ["f0s"]),
            h.make_node("Add", ["cs", "f0s"], ["volta"]), h.make_node("Mul", ["volta", "dois_pi"], ["ang"]),
            h.make_node("Sin", ["ang"], ["s"]), h.make_node("Sign", ["fq"], ["tem"]),
            h.make_node("Mul", ["s", "tem"], ["s1"]), h.make_node("Mul", ["s1", "amp"], ["s2"]),
            h.make_node("Reshape", ["s2", "saida"], ["audio"])],
           [_vi("z", f, ["lote", 192, DL]), _vi("nsff0", f, [1, DL]), _vi("ruido_fonte", f, [1, n, 1]),
            _vi("fase0", f, [1, 1, 1])], [_vi("audio", f, [1, 1, n])],
           [_ini("f_col", [DL, 1], np.int64), _ini("rep", [1, POR_QUADRO], np.int64), _ini("f_lin", [n], np.int64),
            _ini("srm", [float(SRM)]), _ini("eixo0", 0, np.int64), _ini("um", [1], np.int64),
            _ini("dois_pi", [2 * np.pi]), _ini("amp", [0.3]), _ini("saida", [1, 1, n], np.int64)],
           voz / f"teste_dec_q{DL}_fp16.onnx")
    return engine, voz


def pico(x, sr=48000):
    """O tom de um trecho (Hz) e a parte da energia que fica a 8 Hz dele (1 = um seno limpo)."""
    jan = np.hanning(len(x))
    esp = np.abs(np.fft.rfft(x * jan, 8 * len(x))) ** 2
    hz = np.fft.rfftfreq(8 * len(x), 1 / sr)
    k = int(esp[1:].argmax()) + 1
    a, b, c = np.log(esp[k - 1:k + 2] + 1e-30)
    f = hz[k] + 0.5 * (a - c) / (a - 2 * b + c) * (hz[1] - hz[0])
    return f, float(esp[np.abs(hz - f) <= 8].sum() / esp.sum())


def voz(segundos):
    t = np.arange(int(segundos * 48000)) / 48000
    return (0.1 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)  # o FCPE de mentira so ouve o volume


class Motor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.engine, cls.voz = monta(Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def conversor(self, tom):
        return C.Conversor(str(self.engine), str(self.voz), tom=tom, provedor="cpu")

    def roda(self, c, x):
        saidas = []
        for i in range(0, len(x) - C.N + 1, C.N):
            y = c.bloco(x[i:i + C.N])
            self.assertEqual((y.shape, y.dtype), ((C.N,), np.float32))
            saidas.append(y)
        return np.concatenate(saidas)

    def test_tom_deslocado_e_onda_limpa(self):
        c = self.conversor(9)
        y = self.roda(c, voz(3.0))
        self.assertTrue(np.all(np.isfinite(y)))
        f, limpo = pico(y[-48000:])
        self.assertAlmostEqual(f, TOM_HZ * 2 ** (9 / 12), delta=1.0)
        self.assertGreater(limpo, 0.98, "um seno limpo: a onda emenda de um bloco no outro sem degrau")
        np.testing.assert_allclose(c.tom_congelado, TOM_HZ, atol=0.5, err_msg="o tom de quem fala, sem o deslocamento")
        self.assertEqual(len(c.tom_congelado), P)

    def test_ajusta_tom(self):
        c = self.conversor(9)
        self.roda(c, voz(1.5))
        c.ajusta_tom(0)
        y = self.roda(c, voz(2.0))
        f, limpo = pico(y[-48000:])
        self.assertAlmostEqual(f, TOM_HZ, delta=1.0)
        self.assertGreater(limpo, 0.98)

    def test_silencio_sai_em_silencio(self):
        c = self.conversor(9)
        self.roda(c, voz(1.0))
        y = self.roda(c, np.zeros(2 * 48000, np.float32))
        self.assertLess(float(np.sqrt((y[-24000:] ** 2).mean())), 1e-4)
        np.testing.assert_array_equal(c.tom_congelado, 0, "sem som, sem tom")


if __name__ == "__main__":
    unittest.main(verbosity=2)
