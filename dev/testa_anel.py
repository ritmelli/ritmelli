"""Testa que o anel do filtro de microfone (microfone/injeta.py) nunca fica aberto depois de uma falha, sem abrir
memoria nenhuma: o kernel32 do injeta.py e trocado por um falso, que da um handle de mentira, poe a "vista" numa
memoria do proprio teste e conta cada UnmapViewOfFile e CloseHandle.

Confere: o Microfone() que falha no MapViewOfFile fecha o handle; o de magia ou versao que nao bate solta a vista e
fecha o handle antes de levantar o SemFiltro; o fecha solta cada um uma vez (chamar de novo nao faz nada) e fecha o
handle mesmo se soltar a vista falhar, e a limpeza que falha nao troca o erro de abrir. Na saida para o jogo
(engine.Injetor): o escreve que levanta faz o anel fechar uma vez e o efeito no filtro zerar, o fecha que falha
tambem zera o efeito e solta o anel, e a troca de efeito (outra thread) nunca le a vista, que a thread pode fechar.

    python dev/testa_anel.py

Sai 1 se algo falhar.
"""
import ctypes
import io
import os
import re
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ["MICFX_MAPA"] = f"Local\\RitmelliTesteAnel-{os.getpid()}"  # o k32 e falso, mas nunca o nome de verdade
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dryouts
import engine as eng
from microfone import injeta

ALVO = injeta.hash_microfone("{11111111-2222-3333-4444-555555555555}")
HANDLE = 0x5A5A


class K32Falso:
    """O que o injeta.py chama do kernel32. A vista e uma memoria do teste com o layout do anel; abrir so da certo
    `aberturas` vezes (depois o anel "nao existe"), e cada soltura fica anotada."""

    def __init__(self, vista=True, versao=injeta.VERSAO, magia=injeta.MAGIA, aberturas=1, falha_unmap=False):
        self.mem = ctypes.create_string_buffer(ctypes.sizeof(injeta.Anel))
        self.p = ctypes.addressof(self.mem)
        a = injeta.Anel.from_address(self.p)
        a.magia, a.versao, a.voz_taxa = magia, versao, 48000
        self.vista, self.aberturas, self.falha_unmap = vista, aberturas, falha_unmap
        self.abertos, self.vistas, self.unmaps, self.closes = 0, 0, [], []

    def OpenFileMappingW(self, acesso, herda, nome):
        if self.abertos >= self.aberturas:
            return None
        self.abertos += 1
        return HANDLE

    def MapViewOfFile(self, h, acesso, alto, baixo, n):
        if not self.vista:
            return None
        self.vistas += 1
        return self.p

    def UnmapViewOfFile(self, p):
        self.unmaps.append(p)
        if self.falha_unmap:
            raise OSError("UnmapViewOfFile falso falhou")
        return 1

    def CloseHandle(self, h):
        self.closes.append(h)
        return 1

    def GetTickCount64(self):
        return 10_000


class MotorFalso:
    """O que o Injetor usa do motor, com um efeito escolhido (o filtro o roda: ver o _efeito)."""

    def __init__(self):
        self.error, self._fx, self.effect, self.mic_mute = None, None, "robo", False
        self._fx_id = "robo"
        self._fx_filtro = self._fx_pendente = False
        self._pista_viva = False
        self.voice_pedal = dryouts.VoicePedalStart()
        self._alvo, self._voz_anel_em = ALVO, -1e9

    def voz_pelo_app(self):
        return False

    def set_error(self, message):
        self.error = message

    def totais_saude(self):  # a janela do evento "audio" (metricas.SaudeAudio)
        return 0, 0.0

    def em_passagem(self):
        return False

    def _push_mic(self, x):
        pass

    def _push_voz_fx(self, x):
        pass

    def _mixa(self, frames):
        return eng.np.zeros((frames, 2), eng.np.float32)


def espera(cond, s=3.0):
    fim = time.monotonic() + s
    while time.monotonic() < fim and not cond():
        time.sleep(0.01)
    return cond()


class TestaConstrutor(unittest.TestCase):
    def test_falha_no_mapview_fecha_o_handle(self):
        k = K32Falso(vista=False)
        with mock.patch.object(injeta, "k32", k), self.assertRaises(injeta.SemFiltro):
            injeta.Microfone()
        self.assertEqual(k.closes, [HANDLE])
        self.assertEqual(k.unmaps, [])

    def test_versao_ou_magia_que_nao_bate_solta_tudo(self):
        for nome, kw in (("versao", {"versao": injeta.VERSAO - 1}), ("magia", {"magia": 0x1234})):
            with self.subTest(nome):
                k = K32Falso(**kw)
                with mock.patch.object(injeta, "k32", k), self.assertRaises(injeta.SemFiltro):
                    injeta.Microfone()
                self.assertEqual(k.unmaps, [k.p])
                self.assertEqual(k.closes, [HANDLE])

    def test_limpeza_que_falha_nao_troca_o_erro(self):
        """Soltar a vista falhou na limpeza: sobe o SemFiltro de antes (o Injetor tenta de novo) e o handle fecha."""
        k = K32Falso(versao=injeta.VERSAO - 1, falha_unmap=True)
        with mock.patch.object(injeta, "k32", k), self.assertRaises(injeta.SemFiltro):
            injeta.Microfone()
        self.assertEqual(k.unmaps, [k.p])
        self.assertEqual(k.closes, [HANDLE])

    def test_erro_inesperado_no_construtor_solta_tudo(self):
        k = K32Falso()
        with mock.patch.object(injeta, "k32", k), \
                mock.patch.object(injeta.np.ctypeslib, "as_array", side_effect=MemoryError("falso")), \
                self.assertRaises(MemoryError):
            injeta.Microfone()
        self.assertEqual(k.unmaps, [k.p])
        self.assertEqual(k.closes, [HANDLE])

    def test_fecha_solta_cada_um_uma_vez(self):
        k = K32Falso()
        with mock.patch.object(injeta, "k32", k):
            m = injeta.Microfone()
            m.fecha()
            m.fecha()
        self.assertEqual(k.unmaps, [k.p])
        self.assertEqual(k.closes, [HANDLE])

    def test_fecha_fecha_o_handle_mesmo_se_a_vista_falhar(self):
        k = K32Falso(falha_unmap=True)
        with mock.patch.object(injeta, "k32", k):
            m = injeta.Microfone()
            with self.assertRaises(OSError):
                m.fecha()
            m.fecha()
        self.assertEqual(k.unmaps, [k.p])
        self.assertEqual(k.closes, [HANDLE])


class TestaInjetor(unittest.TestCase):
    def _falha_no_escreve(self, falha_unmap):
        """O filtro do alvo le (um leitor vivo) e roda o efeito; o escreve levanta. Devolve o k32 falso, o motor e o
        Injetor depois de parar."""
        k = K32Falso(falha_unmap=falha_unmap)
        a = injeta.Anel.from_address(k.p)
        a.leitor[0].dono, a.leitor[0].batida, a.leitor[0].ep = 1, k.GetTickCount64(), ALVO
        a.preset_feito = 2  # o filtro ja leu o preset (o primeiro seq e 2) e montou: o efeito roda nele
        motor = MotorFalso()
        viu_efeito, na_pausa = [], []
        dorme = time.sleep

        def escreve(self, x):
            viu_efeito.append(motor._fx_filtro)
            raise RuntimeError("escreve falso falhou")

        def sleep(s):  # a pausa de 0,5 s depois da falha: o efeito ja zerou nela, e nao so na volta seguinte
            if s == 0.5 and threading.current_thread().name == "ritmelli-microfone" and not na_pausa:
                na_pausa.append((motor._fx_filtro, motor._fx_pendente, motor._pista_viva, len(k.closes)))
            dorme(s)

        with mock.patch.object(injeta, "k32", k), mock.patch.object(injeta.Microfone, "escreve", escreve), \
                mock.patch.object(eng.preset, "pede", return_value=b"\x01"), mock.patch.object(eng.time, "sleep", sleep):
            inj = eng.Injetor(motor)
            try:
                self.assertTrue(espera(lambda: k.closes), "o anel que falhou nao fechou")
                self.assertTrue(espera(lambda: inj.m is None and not inj.efeito_no_filtro))
            finally:
                inj.para()
        self.assertEqual(viu_efeito[:1], [True], "o teste nao chegou ao escreve com o efeito no filtro")
        self.assertEqual(na_pausa, [(False, False, False, 1)], "na pausa depois da falha o anel ja fechou e o efeito zerou")
        return k, motor, inj

    def _confere(self, k, motor, inj):
        self.assertEqual(k.abertos, 1)
        self.assertEqual(k.unmaps, [k.p], "a vista solta uma vez")
        self.assertEqual(k.closes, [HANDLE], "o handle fecha uma vez")
        self.assertIsNone(inj.m)
        self.assertFalse(inj.efeito_no_filtro)
        self.assertIsNone(inj._preset)
        self.assertEqual(inj.voz_taxa, 0, "a taxa do anel que falhou nao fica para o proximo")
        self.assertFalse(motor._fx_filtro or motor._fx_pendente or motor._pista_viva)
        self.assertEqual((motor.error or {}).get("key"), "server.mic.outputFailed")

    def test_falha_no_escreve_fecha_o_anel(self):
        self._confere(*self._falha_no_escreve(falha_unmap=False))

    def test_fecha_que_falha_ainda_zera_o_efeito(self):
        self._confere(*self._falha_no_escreve(falha_unmap=True))

    def test_troca_de_efeito_nao_le_a_vista(self):
        """A troca de efeito (outra thread) pega a taxa que o Injetor copiou, e nunca a vista do anel, que a thread
        dele pode fechar no meio."""

        class AnelFechado:
            @property
            def a(self):
                raise AssertionError("a troca de efeito leu a vista do anel")

        e = eng.Engine(mic="x", monitor="")
        e._injetor = mock.Mock(m=AnelFechado(), voz_taxa=44100)
        pedidos = []
        with mock.patch.object(e, "_cadeia", return_value=None),                 mock.patch.object(eng.preset, "preset", lambda eid, taxa: pedidos.append((eid, taxa))):
            e.set_effect("robo")
        self.assertEqual(pedidos, [("robo", 44100)], "o preset do filtro nao ficou pronto na taxa do Injetor")


class TestVoicePedalDryOut(unittest.TestCase):
    def setUp(self):
        self.k = K32Falso()
        a = self.a = injeta.Anel.from_address(self.k.p)
        a.leitor[0].dono, a.leitor[0].batida, a.leitor[0].ep = 1, self.k.GetTickCount64(), ALVO
        self.motor = MotorFalso()
        self.now = 1000.0
        self.motor.voice_pedal = dryouts.VoicePedalStart(clock=lambda: self.now)
        self.drain = threading.Event()
        self.log = io.StringIO()
        full = eng.INJ_FOLGA * eng.BLOCK

        def na_fila(m):
            if self.drain.is_set():
                self.drain.clear()
                return 0
            return full

        patches = [mock.patch.object(injeta, "k32", self.k), mock.patch.object(injeta.Microfone, "na_fila", na_fila),
                   mock.patch.object(injeta.Microfone, "escreve", lambda m, x: len(x)),
                   mock.patch.object(eng.preset, "pede", return_value=None), mock.patch("sys.stderr", self.log)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.inj = eng.Injetor(self.motor)
        self.addCleanup(self.inj.para)
        self.assertTrue(espera(lambda: self.inj.leitores == 1), "the injector never saw the reader")

    def dry_out(self):
        before = self.inj.secas
        self.drain.set()
        self.assertTrue(espera(lambda: self.inj.secas > before), "the ring never ran dry")

    def track_up(self):
        self.a.pista_batida, self.a.pista_ligada = self.k.GetTickCount64(), 1
        self.assertTrue(espera(lambda: self.motor.voice_pedal.track_up_at is not None), "the injector never saw the voice track")

    def pedal_on(self, seconds_ago):
        self.now -= seconds_ago
        self.motor.voice_pedal.pedal(True)
        self.now += seconds_ago

    def pedal_lines(self):
        return [ln for ln in self.log.getvalue().splitlines() if "while the voice pedal was starting" in ln]

    def offset(self, line, what):
        return float(re.search(what + r" (\d+\.\d+) s ago", line).group(1))

    def test_dry_out_before_the_track_is_up(self):
        self.pedal_on(2.0)
        self.dry_out()
        self.assertEqual((self.inj.dry_outs.while_pedal_starting, self.inj.estado()["secas_pedal"]), (1, 1))
        line = self.pedal_lines()[-1]
        self.assertIn("its voice track isn't up yet", line)
        self.assertEqual(self.offset(line, "turned on"), 2.0)

    def test_dry_out_after_the_track_came_up(self):
        self.pedal_on(1.0)
        self.track_up()
        self.now += 0.3
        self.dry_out()
        self.assertEqual(self.inj.dry_outs.while_pedal_starting, 1)
        line = self.pedal_lines()[-1]
        self.assertEqual((self.offset(line, "turned on"), self.offset(line, "came up")), (1.3, 0.3))

    def test_dry_out_long_after_the_track_came_up(self):
        self.pedal_on(0.0)
        self.track_up()
        self.now += dryouts.AFTER_TRACK_S + 0.1
        self.dry_out()
        self.assertEqual((self.inj.secas, self.inj.dry_outs.while_pedal_starting), (1, 0))
        self.assertEqual(self.pedal_lines(), [])

    def test_dry_out_with_the_pedal_off(self):
        self.track_up()
        self.dry_out()
        self.assertEqual((self.inj.secas, self.inj.dry_outs.while_pedal_starting), (1, 0))
        self.assertEqual(self.pedal_lines(), [])

    def test_track_of_an_earlier_pedal_does_not_count_as_up(self):
        self.track_up()
        self.now += 1.0
        self.pedal_on(0.0)
        self.dry_out()
        self.assertIn("its voice track isn't up yet", self.pedal_lines()[-1])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
