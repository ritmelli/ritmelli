"""Testa o filtro de microfone inteiro (o micfx.cpp de verdade, pela banca_filtro.dll) com o efeito de voz no filtro
(issue #63), sem o audiodg e sem som: a banca cria o anel num nome so do teste e roda o APOProcess bloco a bloco; o
lado do app escreve no anel pelo microfone/injeta.py, como o motor.

Confere: sem efeito a voz passa igual; com o preset, a voz sai com efeito no MESMO bloco em que entrou, igual a cadeia
do voz.dll amostra a amostra, em todos os canais, e volta ao app em voz_fx; o efeito so vale com o app vivo; tirar o
preset devolve a voz crua; preset estragado ou de outra taxa e recusado (preset_erro) e a voz segue crua; a voz
cortada com efeito leva so a musica, e o efeito continua em voz_fx (ouvir a propria voz); a musica soma em cima da voz
com efeito; outro microfone (alvo de outro) fica intocado; a 44,1 kHz em estereo o preset da taxa monta e bate.

O hospedeiro do MFX (#49), com um fabricante falso por dentro (cancelamento de eco, corta a voz pela metade): o
fabricante recebe o Initialize com o CLSID dele, o registro sai com o do hospedeiro, so as interfaces que o fabricante
tem aparecem; a musica entra inteira DEPOIS do fabricante (e no lugar da voz cortada); fora do alvo so o fabricante
age; a 44,1 kHz em estereo os dois canais passam; desmontado, o hospedeiro solta todas as referencias do fabricante.

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


_dll.banca_hospede_cria.restype = ctypes.c_void_p
_dll.banca_hospede_cria.argtypes = (ctypes.c_wchar_p, ctypes.c_float, ctypes.c_uint, ctypes.c_uint)
_dll.banca_hospede_bloco.argtypes = (ctypes.c_void_p, _P, _P, ctypes.c_uint, ctypes.c_int)
_dll.banca_hospede_info.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
_dll.banca_hospede_destroi.restype = ctypes.c_int
_dll.banca_hospede_destroi.argtypes = (ctypes.c_void_p,)


class BancaHospede(Banca):
    """O hospedeiro do MFX (#49) pela fabrica de verdade, com um fabricante falso por dentro: um APO com
    cancelamento de eco que devolve a entrada pela metade (o "redutor")."""

    def __init__(self, taxa=48000, canais=1):  # noqa: D107 - mesmo molde da Banca, com as funcoes do hospedeiro
        Banca.conta += 1
        self.mapa = f"{os.environ['MICFX_MAPA']}-h{Banca.conta}"
        injeta.MAPA = self.mapa
        self.taxa, self.canais, self.bloco = taxa, canais, taxa // 100
        self.h = _dll.banca_hospede_cria(self.mapa, float(taxa), canais, 4 * self.bloco)
        assert self.h, "a banca nao criou o hospedeiro"
        self.m = injeta.Microfone()
        self.m.alvo(123)

    def passa(self, x):
        n = len(x) - len(x) % self.bloco
        ent = np.ascontiguousarray(np.repeat(x[:n, None], self.canais, axis=1), np.float32)
        sai = np.zeros_like(ent)
        for i in range(0, n, self.bloco):
            e, s = ent[i:i + self.bloco], sai[i:i + self.bloco]
            _dll.banca_hospede_bloco(self.h, e.ctypes.data_as(_P), s.ctypes.data_as(_P), self.bloco, 0)
        return sai

    def info(self):
        r = (ctypes.c_int * 6)()
        _dll.banca_hospede_info(self.h, r)
        return list(r)

    def fecha(self):
        self.m.fecha()
        return _dll.banca_hospede_destroi(self.h)


class TestaHospede(unittest.TestCase):
    def setUp(self):
        self.b = BancaHospede()
        self.b.m.pulso(False)

    def tearDown(self):
        if self.b:
            self.b.fecha()

    def test_repasse_ao_fabricante(self):
        self.b.passa(fala(0.1))
        init_dele, registro_nosso, aec, fx3, travado, blocos = self.b.info()
        self.assertTrue(init_dele, "o Initialize do fabricante nao recebeu o CLSID dele")
        self.assertTrue(registro_nosso, "o registro tem que sair com o CLSID do hospedeiro")
        self.assertTrue(aec, "o fabricante tem cancelamento de eco e o hospedeiro escondeu")
        self.assertFalse(fx3, "o hospedeiro mostrou uma interface que o fabricante nao tem")
        self.assertEqual(travado, 1)
        self.assertEqual(blocos, 10)

    def test_musica_depois_do_redutor(self):
        x = fala(1.0)
        self.b.passa(x[:480])  # o primeiro bloco pega a vaga de leitor
        musica = (0.1 * np.sin(2 * np.pi * 440 * np.arange(24000) / 48000)).astype(np.float32)
        self.assertEqual(self.b.m.escreve(np.repeat(musica[:, None], 2, axis=1)), 24000)
        x = x[:24480]
        y = self.b.passa(x[480:])
        esperado = 0.5 * x[480:] + musica[:len(y)]  # o fabricante corta a voz, a musica entra inteira depois
        np.testing.assert_allclose(y[:, 0], np.clip(esperado, -0.9, 0.9), atol=1e-6)

    def test_voz_cortada_so_a_musica(self):
        self.b.m.pulso(True)
        x = fala(0.6)
        self.b.passa(x[:480])
        musica = (0.1 * np.sin(2 * np.pi * 440 * np.arange(9600) / 48000)).astype(np.float32)
        self.b.m.escreve(np.repeat(musica[:, None], 2, axis=1))
        y = self.b.passa(x[480:24480])
        np.testing.assert_allclose(y[:9600, 0], musica, atol=1e-6)
        self.assertEqual(float(np.max(np.abs(y[9600:]))), 0.0, "sem musica, a voz cortada e silencio")

    def test_outro_microfone_so_o_fabricante(self):
        self.b.m.alvo(0)
        x = fala(0.5)
        self.b.m.escreve(np.full((4800, 2), 0.1, np.float32))
        np.testing.assert_allclose(self.b.passa(x)[:, 0], 0.5 * x[:len(x) // 480 * 480], atol=1e-7)

    def test_estereo_441(self):
        b = BancaHospede(44100, 2)
        try:
            b.m.pulso(False)
            x = fala(0.5, 44100)
            y = b.passa(x)
            np.testing.assert_allclose(y[:, 1], 0.5 * x[:len(y)], atol=1e-7)
        finally:
            b.fecha()

    def test_solta_o_fabricante(self):
        self.b.passa(fala(0.1))
        sobra = self.b.fecha()
        self.b = None
        self.assertEqual(sobra, 1, "o hospedeiro nao soltou todas as referencias do fabricante")


if __name__ == "__main__":
    unittest.main(verbosity=2)
