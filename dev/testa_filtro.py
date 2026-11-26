"""Testa o filtro de microfone inteiro (o micfx.cpp de verdade, pela banca_filtro.dll) com o efeito de voz no filtro
(issue #63), sem o audiodg e sem som: a banca cria o anel num nome so do teste e roda o APOProcess bloco a bloco; o
lado do app escreve no anel pelo microfone/injeta.py, como o motor.

Confere: sem efeito a voz passa igual; com o preset, a voz sai com efeito no MESMO bloco em que entrou, igual a cadeia
do voz.dll amostra a amostra, em todos os canais, e volta ao app em voz_fx; o efeito so vale com o app vivo; tirar o
preset devolve a voz crua; preset estragado ou de outra taxa e recusado (preset_erro) e a voz segue crua; a voz
cortada com efeito leva so a musica, e o efeito continua em voz_fx (ouvir a propria voz); a musica soma em cima da voz
com efeito; outro microfone (alvo de outro) fica intocado; a 44,1 kHz em estereo o preset da taxa monta e bate.

Duas cadeias no mesmo microfone (#70, o microfone aberto por dois programas): so a dona da voz escreve a voz crua e a
voz com efeito do app, e as duas poem o efeito no proprio som; a dona que fecha, sai do alvo ou para de bater passa a
voz pra outra.

O hospedeiro do MFX (#49), com um fabricante falso por dentro (cancelamento de eco, corta a voz pela metade): o
fabricante recebe o Initialize com o CLSID dele, o registro sai com o do hospedeiro, so as interfaces que o fabricante
tem aparecem; a musica entra inteira DEPOIS do fabricante (e no lugar da voz cortada); fora do alvo so o fabricante
age; a 44,1 kHz em estereo os dois canais passam; desmontado, o hospedeiro solta todas as referencias do fabricante.

A cadeia inteira de um microfone com o hospedeiro (#78: o EFX so com a voz, o fabricante falso e o hospedeiro): o
efeito entra depois do fabricante, que nao apaga mais o efeito; a voz crua do app e a de antes do fabricante e a com
efeito e a do hospedeiro; com a voz cortada e o efeito montado, a voz passa pelo fabricante, o hospedeiro corta depois
do efeito e a voz com efeito segue voltando ao app; sem efeito, o EFX corta.

A pista da voz (a voz convertida fora do filtro, por um processo do app): desligada, nada muda; ligada, a voz da pista
entra bit a bit no lugar da do microfone e a crua segue indo ao app; sem dado o bloco e silencio (a voz do microfone nao
vaza); escritor parado ou pista desligada devolvem a voz; o que foi escrito antes de ligar nao toca; a musica soma por
cima e a voz cortada corta as duas; a 44,1 kHz em estereo ela passa pelo reamostrador; duas cadeias poem a mesma voz; no
microfone com o hospedeiro ela entra depois do fabricante.

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
import fx
from microfone import injeta, preset, voz

_P = ctypes.POINTER(ctypes.c_float)
_dll = ctypes.CDLL(str(AQUI.parent / "microfone" / "apo" / "saida" / "banca_filtro.dll"))
_dll.banca_cria.restype = ctypes.c_void_p
_dll.banca_cria.argtypes = (ctypes.c_wchar_p, ctypes.c_float, ctypes.c_uint, ctypes.c_uint)
_dll.banca_bloco.argtypes = (ctypes.c_void_p, _P, _P, ctypes.c_uint, ctypes.c_int)
_dll.banca_bloco.restype = ctypes.c_int  # 1 = a saida marcada BUFFER_SILENT
_dll.banca_destroi.argtypes = (ctypes.c_void_p,)
_dll.banca_so_voz.argtypes = (ctypes.c_void_p, ctypes.c_int)


class Banca:
    """O filtro numa taxa e num numero de canais, com o anel aberto pelo lado do app (self.m)."""

    conta = 0

    def __init__(self, taxa=48000, canais=1, mapa=None):
        """mapa: o anel de outra banca (uma segunda cadeia no mesmo microfone, sem o lado do app: self.m None)."""
        Banca.conta += 1
        self.mapa = mapa or f"{os.environ['MICFX_MAPA']}-{Banca.conta}"
        self.taxa, self.canais, self.bloco = taxa, canais, taxa // 100
        self.h = _dll.banca_cria(self.mapa, float(taxa), canais, 4 * self.bloco)
        assert self.h, "a banca nao criou o filtro"
        self.m = None
        if mapa is None:
            injeta.MAPA = self.mapa
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

    def fecha_filtro(self):
        """Desmonta so o filtro (a cadeia fechou: UnlockForProcess e o fim da instancia); o lado do app segue aberto."""
        if self.h:
            _dll.banca_destroi(self.h)
            self.h = None

    def fecha(self):
        if self.m:
            self.m.fecha()
        self.fecha_filtro()


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


class TestaDuasCadeias(unittest.TestCase):
    """O microfone aberto por dois programas: o Windows pode montar duas cadeias, cada uma com a sua instancia do filtro
    no mesmo anel (#70)."""

    def setUp(self):
        self.a = Banca()
        self.a.m.pulso(False)
        self.b = Banca(mapa=self.a.mapa)
        self.m = self.a.m

    def tearDown(self):
        self.b.fecha()
        self.a.fecha()

    def blocos(self, xa, xb):
        """As duas cadeias bloco a bloco, a primeira na frente (a que abriu antes); devolve as duas saidas."""
        ya, yb = [], []
        for i in range(0, len(xa) - len(xa) % 480, 480):
            ya.append(self.a.um_bloco(xa[i:i + 480])[0])
            yb.append(self.b.um_bloco(xb[i:i + 480])[0])
        return np.concatenate(ya), np.concatenate(yb)

    def test_uma_voz_pro_app_e_o_efeito_nas_duas(self):
        p = preset.compila(fx.criar("eco"), 48000)
        seq = self.m.preset(p)
        self.m.voz()
        self.m.voz_fx()
        xa, xb = fala(0.3), fala(0.3, semente=9)[::-1].copy()
        ya, yb = self.blocos(xa, xb)
        self.assertEqual(self.m.preset_estado(), (seq, 0), "o preset nao montou")
        self.assertNotEqual(self.m.a.voz_dono, 0)
        np.testing.assert_array_equal(self.m.voz()[0], xa[:len(ya)],
                                      "a voz do app nao e so a da dona (ou andou em dobro)")
        esperado_a = em_blocos(voz.Cadeia(p, 48000), xa, 480)
        np.testing.assert_array_equal(self.m.voz_fx()[0], esperado_a, "a voz com efeito do app nao e so a da dona")
        np.testing.assert_array_equal(ya, esperado_a)
        np.testing.assert_array_equal(yb, em_blocos(voz.Cadeia(p, 48000), xb, 480), "a outra cadeia perdeu o efeito")

    def test_a_dona_fecha_e_a_outra_assume_na_hora(self):
        x1, x2 = fala(0.1), fala(0.1, semente=5)
        self.blocos(x1, x2)
        dona = self.m.a.voz_dono
        self.assertNotEqual(dona, 0)
        self.m.voz()
        self.a.fecha_filtro()
        self.assertEqual(self.m.a.voz_dono, 0, "a cadeia que fecha nao soltou a voz")
        y = self.b.passa(x2)
        self.assertNotIn(self.m.a.voz_dono, (0, dona))
        np.testing.assert_array_equal(self.m.voz()[0], x2[:len(y)], "a outra cadeia nao assumiu a voz na hora")

    def test_a_dona_parada_passa_a_voz_depois_da_batida(self):
        x = fala(0.2)
        self.a.um_bloco(x[:480])
        dona = self.m.a.voz_dono
        self.m.voz()
        self.b.passa(x)
        self.assertEqual(self.m.a.voz_dono, dona, "a outra tomou a voz com a dona batendo")
        self.assertEqual(len(self.m.voz()[0]), 0, "a outra escreveu a voz com a dona viva")
        self.m.a.voz_batida = injeta.k32.GetTickCount64() - 600  # a dona parou (cadeia travada, ou sumiu sem soltar)
        y = self.b.passa(x)
        self.assertNotIn(self.m.a.voz_dono, (0, dona))
        np.testing.assert_array_equal(self.m.voz()[0], x[:len(y)], "a outra nao assumiu a voz da dona parada")
        self.a.passa(x)
        self.assertEqual(len(self.m.voz()[0]), 0, "a dona velha voltou a escrever por cima da nova")

    def test_fora_do_alvo_solta_a_voz(self):
        x = fala(0.01)
        self.a.um_bloco(x)
        dona = self.m.a.voz_dono
        self.assertNotEqual(dona, 0)
        self.m.alvo(0)
        self.a.um_bloco(x)
        self.assertEqual(self.m.a.voz_dono, 0, "o microfone que deixou de ser o alvo nao soltou a voz")
        self.m.alvo(123)
        self.m.voz()
        self.b.um_bloco(x)
        self.assertNotIn(self.m.a.voz_dono, (0, dona))
        np.testing.assert_array_equal(self.m.voz()[0], x)


_dll.banca_hospede_cria.restype = ctypes.c_void_p
_dll.banca_hospede_cria.argtypes = (ctypes.c_wchar_p, ctypes.c_float, ctypes.c_uint, ctypes.c_uint)
_dll.banca_hospede_bloco.argtypes = (ctypes.c_void_p, _P, _P, ctypes.c_uint, ctypes.c_int)
_dll.banca_hospede_info.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
_dll.banca_hospede_destroi.restype = ctypes.c_int
_dll.banca_hospede_destroi.argtypes = (ctypes.c_void_p,)


class BancaHospede(Banca):
    """O hospedeiro do MFX (#49) pela fabrica de verdade, com um fabricante falso por dentro: um APO com
    cancelamento de eco que devolve a entrada pela metade (o "redutor")."""

    def __init__(self, taxa=48000, canais=1):  # mesmo molde da Banca, com as funcoes do hospedeiro
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

    def um_bloco(self, x, silencio=False):
        """Um bloco so pelo hospedeiro (x mono); devolve (saida do canal 0, None: a marca da saida nao volta)."""
        ent = np.ascontiguousarray(np.repeat(np.asarray(x, np.float32)[:, None], self.canais, axis=1))
        sai = np.zeros_like(ent)
        _dll.banca_hospede_bloco(self.h, ent.ctypes.data_as(_P), sai.ctypes.data_as(_P), len(x), 1 if silencio else 0)
        return sai[:, 0], None

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



class TestaEfeitoNoHospedeiro(unittest.TestCase):
    """O microfone com o hospedeiro do MFX inteiro: o EFX (so a voz crua), o fabricante falso (o "redutor", que passa a
    metade) e o hospedeiro, no mesmo anel (#78)."""

    def setUp(self):
        self.h = BancaHospede()
        self.h.m.pulso(False)
        self.m = self.h.m
        self.e = Banca(mapa=self.h.mapa)
        _dll.banca_so_voz(self.e.h, 1)

    def tearDown(self):
        self.e.fecha()
        self.h.fecha()

    def cadeia(self, x):
        """x pela cadeia, bloco a bloco: devolve (o que o EFX passou ao fabricante, o que saiu do hospedeiro)."""
        meio, fim = [], []
        for i in range(0, len(x) - len(x) % 480, 480):
            y, mudo = self.e.um_bloco(x[i:i + 480])
            meio.append(y)
            fim.append(self.h.um_bloco(y, mudo)[0])
        return np.concatenate(meio), np.concatenate(fim)

    def test_efeito_depois_do_fabricante(self):
        p = preset.compila(fx.criar("eco"), 48000)
        seq = self.m.preset(p)
        self.m.voz()
        self.m.voz_fx()
        x = fala(0.3)
        meio, y = self.cadeia(x)
        self.assertEqual(self.m.preset_estado(), (seq, 0), "o hospedeiro nao montou o preset")
        np.testing.assert_array_equal(meio, x[:len(meio)], "o EFX pos o efeito antes do fabricante")
        esperado = em_blocos(voz.Cadeia(p, 48000), 0.5 * x, 480)
        np.testing.assert_array_equal(y, esperado, "o efeito nao entrou depois do fabricante")
        np.testing.assert_array_equal(self.m.voz()[0], x[:len(y)], "a voz crua do app e a de antes do fabricante")
        np.testing.assert_array_equal(self.m.voz_fx()[0], esperado, "a voz com efeito do app e a do hospedeiro")
        self.assertNotIn(self.m.a.voz_dono, (0, self.m.a.fx_dono), "o EFX tem a voz e o hospedeiro o efeito")
        self.assertNotEqual(self.m.a.fx_dono, 0)

    def test_voz_cortada_com_efeito_corta_depois_dele(self):
        p = preset.compila(fx.criar("eco"), 48000)
        seq = self.m.preset(p)
        x = fala(0.3)
        self.cadeia(x[:480])
        self.assertEqual(self.m.preset_estado(), (seq, 0))
        self.m.pulso(True)
        self.m.voz_fx()
        meio, y = self.cadeia(x[480:])
        np.testing.assert_array_equal(meio, x[480:480 + len(meio)], "com o efeito montado a voz segue pro hospedeiro")
        self.assertEqual(float(np.max(np.abs(y))), 0.0, "a voz cortada vazou")
        esperado = em_blocos(voz.Cadeia(p, 48000), 0.5 * x, 480)[480:]
        np.testing.assert_array_equal(self.m.voz_fx()[0], esperado,
                                      "com a voz cortada, a voz com efeito tem que seguir voltando ao app")

    def test_voz_cortada_sem_efeito_o_efx_corta(self):
        self.m.pulso(True)
        self.m.voz()
        x = fala(0.1)
        meio, y = self.cadeia(x)
        self.assertEqual(float(np.max(np.abs(meio))), 0.0, "sem efeito no filtro, a voz cortada sai ja no EFX")
        self.assertEqual(float(np.max(np.abs(y))), 0.0)
        np.testing.assert_array_equal(self.m.voz()[0], x[:len(meio)], "a voz crua segue indo ao app")

    def test_musica_e_efeito_no_hospedeiro(self):
        p = preset.compila(fx.criar("robo"), 48000)
        self.m.preset(p)
        x = fala(0.5)
        self.cadeia(x[:480])  # o primeiro bloco pega a vaga de leitor e monta o preset
        musica = (0.1 * np.sin(2 * np.pi * 440 * np.arange(9600) / 48000)).astype(np.float32)
        self.m.escreve(np.repeat(musica[:, None], 2, axis=1))
        _, y = self.cadeia(x[480:480 + 9600])
        com_efeito = em_blocos(voz.Cadeia(p, 48000), 0.5 * x, 480)[480:480 + 9600]
        np.testing.assert_allclose(y, np.clip(com_efeito + musica, -0.9, 0.9), atol=1e-6,
                                   err_msg="a musica entra depois do efeito, sem passar por ele")


def convertida(n, f=330.0, taxa=48000):
    """A "voz convertida" que o processo do app escreveria na pista: um tom, facil de reconhecer na saida."""
    return (0.2 * np.sin(2 * np.pi * f * np.arange(n) / taxa)).astype(np.float32)


class TestaPistaDaVoz(unittest.TestCase):
    """A pista da voz do anel: a voz convertida fora do filtro entra no lugar da voz do microfone."""

    def setUp(self):
        self.b = Banca()
        self.m = self.b.m
        self.m.pulso(False)

    def tearDown(self):
        self.b.fecha()

    def test_desligada_a_voz_do_microfone_passa(self):
        x = fala(0.5)
        self.m.pista_escreve(convertida(4800))  # escrever sem ligar nao muda nada
        np.testing.assert_array_equal(self.b.passa(x)[:, 0], x[:len(x) // 480 * 480])

    def test_ligada_a_voz_da_pista_no_lugar(self):
        x = fala(1.0)
        self.m.pista_liga()
        self.b.passa(x[:480])
        v = convertida(14400)
        self.assertEqual(self.m.pista_escreve(v), 14400)
        self.m.voz()
        y = self.b.passa(x[480:480 + 14400])
        np.testing.assert_array_equal(y[:, 0], v, "a voz da pista nao entrou bit a bit no lugar da do microfone")
        np.testing.assert_array_equal(self.m.voz()[0], x[480:480 + 14400],
                                      "a voz crua tem que seguir indo ao app: e dela que a convertida sai")

    def test_sem_dado_e_silencio_e_nao_a_voz(self):
        self.m.pista_liga()
        y = self.b.passa(fala(0.3))
        self.assertEqual(float(np.max(np.abs(y))), 0.0, "a pista sem dado deixou a voz do microfone vazar")
        v = convertida(240)
        self.m.pista_escreve(v)  # meio bloco: sai o que tem, e o resto e silencio
        y, _ = self.b.um_bloco(fala(0.01)[:480])
        np.testing.assert_array_equal(y[:240], v)
        self.assertEqual(float(np.max(np.abs(y[240:]))), 0.0)

    def test_bloco_marcado_silencio_sai_com_a_voz_da_pista(self):
        self.m.pista_liga()
        self.b.um_bloco(np.zeros(480, np.float32), silencio=True)
        v = convertida(480)
        self.m.pista_escreve(v)
        y, mudo = self.b.um_bloco(np.zeros(480, np.float32), silencio=True)
        np.testing.assert_array_equal(y, v)
        self.assertFalse(mudo, "com a pista no comando, a saida nao pode sair marcada como silencio")

    def test_escritor_parado_a_voz_volta(self):
        self.m.pista_liga()
        x = fala(0.3)
        self.assertEqual(float(np.max(np.abs(self.b.passa(x)))), 0.0)
        self.m.a.pista_batida = injeta.k32.GetTickCount64() - injeta.PISTA_MS - 100
        np.testing.assert_array_equal(self.b.passa(x)[:, 0], x[:len(x) // 480 * 480],
                                      "o escritor da pista caiu e o microfone ficou mudo")

    def test_desligar_devolve_a_voz_na_hora(self):
        self.m.pista_liga()
        x = fala(0.3)
        self.assertEqual(float(np.max(np.abs(self.b.passa(x)))), 0.0)
        self.m.pista_liga(False)
        np.testing.assert_array_equal(self.b.passa(x)[:, 0], x[:len(x) // 480 * 480])

    def test_o_escrito_antes_de_ligar_nao_toca(self):
        self.m.pista_escreve(convertida(4800, 990.0))
        self.m.pista_liga()
        y, _ = self.b.um_bloco(fala(0.01)[:480])
        self.assertEqual(float(np.max(np.abs(y))), 0.0, "a pista tocou voz velha ao ligar")
        v = convertida(1440)
        self.m.pista_escreve(v)
        np.testing.assert_array_equal(self.b.passa(fala(0.03))[:, 0], v)

    def test_a_folga_escrita_logo_depois_de_ligar_toca_inteira(self):
        """O escritor liga e ja escreve (o silencio da folga e a voz), antes de o filtro rodar o bloco seguinte: nada
        disso pode ser pulado, senao a pista fica sem folga e engasga a cada atraso do escritor."""
        self.m.pista_liga()
        v = convertida(1440)
        self.m.pista_escreve(np.zeros(480, np.float32))
        self.m.pista_escreve(v)
        y = self.b.passa(fala(0.04))
        self.assertEqual(float(np.max(np.abs(y[:480]))), 0.0)
        np.testing.assert_array_equal(y[480:, 0], v, "o que foi escrito logo depois de ligar foi pulado")

    def test_musica_soma_na_voz_da_pista(self):
        x = fala(0.5)
        self.m.pista_liga()
        self.b.passa(x[:480])  # o primeiro bloco pega a vaga de leitor
        v = convertida(9600)
        musica = (0.1 * np.sin(2 * np.pi * 440 * np.arange(9600) / 48000)).astype(np.float32)
        self.m.pista_escreve(v)
        self.m.escreve(np.repeat(musica[:, None], 2, axis=1))
        y = self.b.passa(x[480:480 + 9600])
        np.testing.assert_allclose(y[:, 0], v + musica, atol=1e-6, err_msg="a musica nao somou por cima da voz da pista")

    def test_voz_cortada_corta_a_pista_tambem(self):
        x = fala(0.5)
        self.m.pista_liga()
        self.m.pulso(True)
        self.b.passa(x[:480])
        musica = (0.1 * np.sin(2 * np.pi * 440 * np.arange(4800) / 48000)).astype(np.float32)
        self.m.pista_escreve(convertida(9600))
        self.m.escreve(np.repeat(musica[:, None], 2, axis=1))
        y = self.b.passa(x[480:480 + 9600])
        np.testing.assert_allclose(y[:4800, 0], musica, atol=1e-6)
        self.assertEqual(float(np.max(np.abs(y[4800:]))), 0.0, "com a voz cortada pelo app, a da pista tambem nao sai")

    def test_folga_que_o_escritor_mede(self):
        self.m.pista_liga()
        self.b.passa(fala(0.02))  # dois blocos: a vaga de leitor e a posicao dele na pista
        self.assertEqual(self.m.pista_na_fila(), 0)
        self.m.pista_escreve(convertida(1440))
        self.assertEqual(self.m.pista_na_fila(), 1440)
        self.b.um_bloco(np.zeros(480, np.float32))
        self.assertEqual(self.m.pista_na_fila(), 960)

    def test_441_estereo(self):
        b = Banca(44100, 2)
        try:
            b.m.pulso(False)
            b.m.pista_liga()
            v = convertida(48000)
            x = fala(1.0, 44100)
            partes = []
            for k in range(100):  # 10 ms de cada lado por volta: o escritor a 48 kHz, o microfone a 44,1
                b.m.pista_escreve(v[k * 480:(k + 1) * 480])
                partes.append(b.passa(x[k * 441:(k + 1) * 441]))
            y = np.concatenate(partes)[4410:-441]  # depois que o reamostrador encheu
            for c in (0, 1):
                esp = np.abs(np.fft.rfft(y[:, c] * np.hanning(len(y))))
                self.assertAlmostEqual(float(np.argmax(esp)) * 44100 / len(y), 330.0, delta=2.0,
                                       msg="o tom da pista nao saiu em 330 Hz na taxa do microfone")
                self.assertAlmostEqual(float(np.sqrt(np.mean(y[:, c] ** 2))), 0.2 / np.sqrt(2), delta=0.003,
                                       msg="o nivel da voz da pista mudou no reamostrador (ou a voz do microfone vazou)")
        finally:
            b.fecha()

    def test_duas_cadeias_poem_a_mesma_voz(self):
        outra = Banca(mapa=self.b.mapa)
        try:
            x = fala(0.5)
            self.m.pista_liga()
            self.b.um_bloco(x[:480])
            outra.um_bloco(x[:480])
            v = convertida(4800)
            self.m.pista_escreve(v)
            ya, yb = [], []
            for i in range(480, 480 + 4800, 480):
                ya.append(self.b.um_bloco(x[i:i + 480])[0])
                yb.append(outra.um_bloco(x[i:i + 480])[0])
            np.testing.assert_array_equal(np.concatenate(ya), v)
            np.testing.assert_array_equal(np.concatenate(yb), v, "a segunda cadeia do microfone ficou sem a voz da pista")
        finally:
            outra.fecha()


class TestaPistaCadeiaQueChegaDepois(unittest.TestCase):
    """O microfone aberto por um segundo programa com a pista ja tocando (#70): a cadeia nova comeca junto da que ja
    le, com a mesma folga, e nao do comeco da pista nem sem folga nenhuma."""

    def test_comeca_junto_da_que_ja_le(self):
        a = Banca()
        b = None
        try:
            a.m.pulso(False)
            x = fala(0.5)
            a.m.pista_liga()
            a.um_bloco(x[:480])
            v = convertida(4800)
            a.m.pista_escreve(v)
            a.um_bloco(x[:480])
            a.um_bloco(x[:480])  # a primeira ja leu 20 ms e tem 80 ms de folga
            b = Banca(mapa=a.mapa)
            ya = a.um_bloco(x[:480])[0]
            yb = b.um_bloco(x[:480])[0]
            np.testing.assert_array_equal(ya, v[960:1440])
            np.testing.assert_array_equal(yb, v[1440:1920], "a cadeia nova nao comecou junto da que ja le a pista")
        finally:
            if b:
                b.fecha()
            a.fecha()


class TestaPistaNoHospedeiro(unittest.TestCase):
    """A pista da voz no microfone com o hospedeiro do MFX: o EFX nao mexe, e ela entra depois do fabricante."""

    def setUp(self):
        self.h = BancaHospede()
        self.h.m.pulso(False)
        self.m = self.h.m
        self.e = Banca(mapa=self.h.mapa)
        _dll.banca_so_voz(self.e.h, 1)

    def tearDown(self):
        self.e.fecha()
        self.h.fecha()

    def cadeia(self, x):
        meio, fim = [], []
        for i in range(0, len(x) - len(x) % 480, 480):
            y, mudo = self.e.um_bloco(x[i:i + 480])
            meio.append(y)
            fim.append(self.h.um_bloco(y, mudo)[0])
        return np.concatenate(meio), np.concatenate(fim)

    def test_pista_depois_do_fabricante(self):
        x = fala(0.5)
        self.m.pista_liga()
        self.cadeia(x[:480])
        v = convertida(9600)
        self.m.pista_escreve(v)
        self.m.voz()
        meio, y = self.cadeia(x[480:480 + 9600])
        np.testing.assert_array_equal(meio, x[480:480 + 9600], "o EFX mexeu na voz: ela tem que seguir ao fabricante")
        np.testing.assert_array_equal(y, v, "a voz da pista tem que entrar inteira, depois do fabricante")
        np.testing.assert_array_equal(self.m.voz()[0], x[480:480 + 9600], "a voz crua do app e a de antes do fabricante")

    def test_musica_e_pista_no_hospedeiro(self):
        x = fala(0.5)
        self.m.pista_liga()
        self.cadeia(x[:480])
        v = convertida(4800)
        musica = (0.1 * np.sin(2 * np.pi * 440 * np.arange(4800) / 48000)).astype(np.float32)
        self.m.pista_escreve(v)
        self.m.escreve(np.repeat(musica[:, None], 2, axis=1))
        _, y = self.cadeia(x[480:480 + 4800])
        np.testing.assert_allclose(y, v + musica, atol=1e-6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
