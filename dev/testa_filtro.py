"""Testa o filtro de microfone inteiro (o micfx.cpp de verdade, pela banca_filtro.dll) com o efeito de voz no filtro
(issue #63), sem o audiodg e sem som: a banca cria o anel num nome so do teste e roda o APOProcess bloco a bloco; o
lado do app escreve no anel pelo microfone/injeta.py, como o motor.

Confere: sem efeito a voz passa igual; com o preset, a voz sai com efeito no MESMO bloco em que entrou, igual a cadeia
do voz.dll amostra a amostra, em todos os canais, e volta ao app em voz_fx; o efeito so vale com o app vivo; tirar o
preset devolve a voz crua; preset estragado ou de outra taxa e recusado (preset_erro) e a voz segue crua; a voz
cortada com efeito leva so a musica, e o efeito continua em voz_fx (ouvir a propria voz); a musica soma em cima da voz
com efeito; outro microfone (alvo de outro) fica intocado; a 44,1 kHz em estereo o preset da taxa monta e bate.

    microfone\\apo\\compila.bat teste
    python dev/testa_filtro.py

Sai 1 se algo falhar.
"""
import ctypes
import os
import sys
import unittest
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
os.environ["MICFX_MAPA"] = f"Local\\RitmelliTestaFiltro-{os.getpid()}"
sys.path.insert(0, str(AQUI.parent))
import fx  # noqa: E402
from microfone import injeta, preset, voz  # noqa: E402

_P = ctypes.POINTER(ctypes.c_float)
_dll = ctypes.CDLL(str(AQUI.parent / "microfone" / "apo" / "saida" / "banca_filtro.dll"))
_dll.banca_cria.restype = ctypes.c_void_p
_dll.banca_cria.argtypes = (ctypes.c_wchar_p, ctypes.c_float, ctypes.c_uint, ctypes.c_uint)
_dll.banca_bloco.argtypes = (ctypes.c_void_p, _P, _P, ctypes.c_uint, ctypes.c_int)
_dll.banca_bloco.restype = ctypes.c_int  # 1 = a saida marcada BUFFER_SILENT
_dll.banca_destroi.argtypes = (ctypes.c_void_p,)


class Banca:
    """O filtro numa taxa e num numero de canais, com o anel aberto pelo lado do app (self.m)."""

    conta = 0

    def __init__(self, taxa=48000, canais=1):
        Banca.conta += 1
        self.mapa = f"{os.environ['MICFX_MAPA']}-{Banca.conta}"
        injeta.MAPA = self.mapa
        self.taxa, self.canais, self.bloco = taxa, canais, taxa // 100
        self.h = _dll.banca_cria(self.mapa, float(taxa), canais, 4 * self.bloco)
        assert self.h, "a banca nao criou o filtro"
        self.m = injeta.Microfone()
        self.m.alvo(123)  # o filtro da banca nao sabe o microfone: age como o alvo de qualquer um

    def passa(self, x):
        """x mono (repete em todos os canais) em blocos de 10 ms; devolve a saida (quadros x canais)."""
        n = len(x) - len(x) % self.bloco
        ent = np.ascontiguousarray(np.repeat(x[:n, None], self.canais, axis=1), np.float32)
        sai = np.zeros_like(ent)
        for i in range(0, n, self.bloco):
            e, s = ent[i:i + self.bloco], sai[i:i + self.bloco]
            _dll.banca_bloco(self.h, e.ctypes.data_as(_P), s.ctypes.data_as(_P), self.bloco, 0)
        return sai

    def um_bloco(self, x, silencio=False):
        """Um bloco so (x mono, do tamanho do bloco); devolve (saida do canal 0, a saida marcada como silencio)."""
        ent = np.ascontiguousarray(np.repeat(np.asarray(x, np.float32)[:, None], self.canais, axis=1))
        sai = np.zeros_like(ent)
        mudo = _dll.banca_bloco(self.h, ent.ctypes.data_as(_P), sai.ctypes.data_as(_P), len(x), 1 if silencio else 0)
        return sai[:, 0], bool(mudo)

    def fecha(self):
        self.m.fecha()
        _dll.banca_destroi(self.h)


def fala(n_s=2.0, taxa=48000, semente=3):
    rng = np.random.default_rng(semente)
    t = np.arange(int(n_s * taxa)) / taxa
    x = 0.3 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 3 * t) > 0) + rng.standard_normal(len(t)) * 0.01
    return x.astype(np.float32)


def em_blocos(c, x, b):
    n = len(x) - len(x) % b
    return np.concatenate([c(x[i:i + b]) for i in range(0, n, b)])


class TestaFiltro(unittest.TestCase):
    def setUp(self):
        self.b = Banca()
        self.b.m.pulso(False)

    def tearDown(self):
        self.b.fecha()

    def test_sem_efeito_a_voz_passa(self):
        x = fala()
        y = self.b.passa(x)
        np.testing.assert_array_equal(y[:, 0], x[:len(y)])

    def test_efeito_no_mesmo_bloco_igual_ao_voz_dll(self):
        p = preset.compila(fx.criar("eco"), 48000)
        seq = self.b.m.preset(p)
        x = fala()
        y1 = self.b.passa(x[:-14400])
        self.b.m.voz_fx()  # a volta guarda ~0,34 s: o app le dali pra frente, como no motor
        y = np.concatenate([y1, self.b.passa(x[-14400:])])
        self.assertEqual(self.b.m.preset_estado(), (seq, 0), "o filtro nao montou o preset")
        esperado = em_blocos(voz.Cadeia(p, 48000), x, 480)
        np.testing.assert_array_equal(y[:, 0], esperado, "a voz com efeito nao e a da cadeia, ou chegou atrasada")
        devolvida, taxa = self.b.m.voz_fx()
        self.assertEqual(taxa, 48000)
        np.testing.assert_array_equal(devolvida, esperado[-14400:], "a voz com efeito nao voltou ao app")

    def test_app_morto_a_voz_volta_crua(self):
        self.b.m.preset(preset.compila(fx.criar("robo"), 48000))
        self.b.m.a.batida_app = injeta.k32.GetTickCount64() - 5000
        x = fala()
        np.testing.assert_array_equal(self.b.passa(x)[:, 0], x[:len(x) // 480 * 480])

    def test_tirar_o_preset_devolve_a_crua(self):
        self.b.m.preset(preset.compila(fx.criar("robo"), 48000))
        x = fala(0.5)
        self.assertFalse(np.array_equal(self.b.passa(x)[:, 0], x[:len(x) // 480 * 480]))
        seq = self.b.m.preset(b"")
        np.testing.assert_array_equal(self.b.passa(x)[:, 0], x[:len(x) // 480 * 480])
        self.assertEqual(self.b.m.preset_estado(), (seq, 0))

    def test_preset_estragado_ou_de_outra_taxa(self):
        x = fala(0.5)
        bom = preset.compila(fx.criar("locutor"), 48000)
        for p, erro in ((bom[:-8], 1), (b"lixo" * 30, 1), (preset.compila(fx.criar("locutor"), 44100), 3)):
            seq = self.b.m.preset(p)
            y = self.b.passa(x)
            self.assertEqual(self.b.m.preset_estado(), (seq, erro))
            np.testing.assert_array_equal(y[:, 0], x[:len(y)], "preset recusado e a voz nao passou crua")

    def test_voz_cortada_com_efeito(self):
        p = preset.compila(fx.criar("demonio"), 48000)
        self.b.m.preset(p)
        self.b.m.pulso(True)  # a voz cortada: so o que o app escreve (nada)
        self.b.m.voz_fx()
        x = fala(0.3)
        y = self.b.passa(x)
        self.assertEqual(float(np.max(np.abs(y))), 0.0, "a voz cortada deixou passar voz")
        devolvida, _ = self.b.m.voz_fx()
        np.testing.assert_array_equal(devolvida[-len(y):], em_blocos(voz.Cadeia(p, 48000), x, 480),
                                      "com a voz cortada o efeito tem que seguir para o fone")

    def test_musica_soma_na_voz_com_efeito(self):
        p = preset.compila(fx.criar("esquilo"), 48000)
        self.b.m.preset(p)
        x = fala(1.0)
        self.b.passa(x[:480])  # o primeiro bloco pega a vaga de leitor
        musica = (0.1 * np.sin(2 * np.pi * 440 * np.arange(24000) / 48000)).astype(np.float32)
        self.assertEqual(self.b.m.escreve(np.repeat(musica[:, None], 2, axis=1)), 24000)
        x = x[:24480]
        y = self.b.passa(x[480:])
        c = voz.Cadeia(p, 48000)
        c(x[:480])
        esperado = em_blocos(c, x[480:], 480) + musica[:len(y)]
        np.testing.assert_allclose(y[:, 0], np.clip(esperado, -0.9, 0.9), atol=1e-6)

    def test_cauda_do_efeito_com_a_entrada_em_silencio(self):
        """Microfone que marca o bloco como silencio (BUFFER_SILENT) e o anel sem musica: sem efeito a saida segue
        silencio; com efeito ela sai marcada como som, senao quem vem depois joga fora a cauda (o eco do Eco)."""
        zero = np.zeros(480, np.float32)
        self.assertTrue(self.b.um_bloco(zero, silencio=True)[1], "sem efeito, silencio continua silencio")
        self.b.m.preset(preset.compila(fx.criar("eco"), 48000))
        estalo = zero.copy()
        estalo[0] = 0.5
        self.b.um_bloco(estalo)
        saidas = [self.b.um_bloco(zero, silencio=True) for _ in range(40)]  # 400 ms: o eco sai aos 280
        self.assertFalse(any(mudo for _, mudo in saidas), "com o efeito, a saida veio marcada como silencio")
        self.assertGreater(float(np.max(np.abs(np.concatenate([y for y, _ in saidas])))), 0.05, "a cauda do Eco sumiu")

    def test_outro_microfone_intocado(self):
        b2 = Banca()  # outro anel, outro filtro: alvo 0 = nenhum
        try:
            b2.m.alvo(0)
            b2.m.pulso(False)
            b2.m.preset(preset.compila(fx.criar("robo"), 48000))
            x = fala(0.5)
            np.testing.assert_array_equal(b2.passa(x)[:, 0], x[:len(x) // 480 * 480])
        finally:
            b2.fecha()

    def test_441_estereo(self):
        b = Banca(44100, 2)
        try:
            b.m.pulso(False)
            p = preset.compila(fx.criar("radio-policia"), 44100, extra=False)
            seq = b.m.preset(p)
            x = fala(1.0, 44100)
            y = b.passa(x)
            self.assertEqual(b.m.preset_estado(), (seq, 0))
            esperado = em_blocos(voz.Cadeia(p, 44100), x, 441)
            np.testing.assert_array_equal(y[:, 0], esperado)
            np.testing.assert_array_equal(y[:, 1], esperado, "os dois canais levam a voz com efeito")
        finally:
            b.fecha()


if __name__ == "__main__":
    unittest.main(verbosity=2)
