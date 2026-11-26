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


def stamp(t):
    return 1 + round(t * 1000) % (2**32 - 1)


class TestVoicePedalStart(unittest.TestCase):
    def test_pedal_off_while_a_dry_out_is_told(self):
        pedal = dryouts.VoicePedalStart(clock=lambda: 5.0)
        pedal.sent(pedal.pedal(True))
        calls = []

        def clock():
            if not calls:
                calls.append(1)
                pedal.pedal(False)
            return 6.0

        pedal.clock = clock
        self.assertIn("turned on 1.00 s ago", pedal.starting()[1])

    def away(self, pedal_on_at, up_at, empty_at=0.756, seen_at=None):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        if pedal_on_at is not None:
            now[0] = pedal_on_at
            pedal.sent(pedal.pedal(True))
        dry = dryouts.RingDryOuts(pedal)
        steps = sorted([(0.1, lambda: dry.read_ring(lambda: 1)), (empty_at, lambda: dry.read_ring(lambda: 0)),
                        (up_at if seen_at is None else seen_at, lambda: pedal.track(stamp(up_at)))], key=lambda x: x[0])
        with mock.patch("sys.stderr", io.StringIO()) as log:
            for at, step in steps:
                now[0] = at
                step()
            now[0] = 0.756
            dry.ran_dry(0.656, 1, 0.0)
        return dry.while_pedal_starting, log.getvalue()

    def test_a_track_up_after_the_ring_was_seen_empty(self):
        counted, log = self.away(0.0, 0.6, empty_at=0.5)
        self.assertEqual(counted, 1)
        self.assertIn("came up 0.16 s ago, after the ring ran dry", log)

    def test_a_track_up_before_the_ring_was_seen_empty_has_no_order(self):
        for up_at, said in ((0.12, "which came first is not known"),
                            (0.4, "after the ring was last filled, so which came first is not known"),
                            (0.75, "after the ring was last filled, so which came first is not known")):
            with self.subTest(up_at=up_at):
                counted, log = self.away(0.0, up_at)
                self.assertEqual(counted, 1)
                self.assertIn(said, log, "a track up past a tick of the last fill came after it")

    def test_a_track_up_within_a_tick_of_the_read_has_no_order(self):
        for up_at, empty_at, said in ((0.09, 0.756, "within a tick of the ring's last fill, so which came first is not "
                                                    "known"),
                                      (0.51, 0.5, "which came first is not known")):
            with self.subTest(up_at=up_at, empty_at=empty_at):
                counted, log = self.away(0.0, up_at, empty_at=empty_at)
                self.assertEqual(counted, 1)
                self.assertIn(said, log, "a track up just before the last fill isn't after it")

    def test_a_track_up_past_a_tick_of_the_read_has_its_order(self):
        for up_at, empty_at, said in ((0.08, 0.756, "came up 0.68 s ago;"), (0.52, 0.5, "after the ring ran dry")):
            with self.subTest(up_at=up_at, empty_at=empty_at):
                counted, log = self.away(0.0, up_at, empty_at=empty_at)
                self.assertEqual(counted, 1)
                self.assertIn(said, log)

    def test_a_track_stamped_before_the_fill_but_seen_after_it_has_no_order(self):
        for seen_at, said in ((0.756, "came up between 0.68 and 0.00 s ago, across the ring's last fill, so which came "
                                      "first is not known"),
                              (0.1, "across the ring's last fill, so which came first is not known"),
                              (0.085, "came up between 0.68 and 0.67 s ago;")):
            with self.subTest(seen_at=seen_at):
                counted, log = self.away(0.0, 0.08, seen_at=seen_at)
                self.assertEqual(counted, 1)
                self.assertIn(said, log)

    def test_a_stamp_rounded_past_its_read_is_not_after_it(self):
        now = [99.0058]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        lines = []
        with mock.patch.object(dryouts, "tell", side_effect=lines.append):
            pedal.sent(pedal.pedal(True))
            now[0] = 100.0007
            pedal.track(stamp(100.0006))
        now[0] = 100.0008
        self.assertEqual(lines, ["voice pedal: its voice track came up 0.99 s after the pedal turned on"])
        self.assertIn("its voice track came up 0.00 s ago", pedal.starting(99.5, 100.0006)[1])

    def test_the_line_gives_when_the_ring_ran_dry(self):
        for empty_at, said in ((0.5, "it ran dry between 0.10 and 0.50 s after the pedal turned on;"),
                               (0.7, "it ran dry between 0.10 and 0.70 s after the pedal turned on;")):
            with self.subTest(empty_at=empty_at):
                counted, log = self.away(0.0, 0.12, empty_at=empty_at)
                self.assertEqual(counted, 1)
                self.assertIn(said, log)

    def test_the_line_without_a_fill_or_an_empty_read(self):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        pedal.sent(pedal.pedal(True))
        for reads, said in (([0], "came back after 500 ms; it ran dry by 0.50 s after the pedal turned on; "),
                            ([], "came back after 500 ms; the pedal turned on")):
            with self.subTest(reads=reads):
                dry = dryouts.RingDryOuts(pedal)
                with mock.patch("sys.stderr", io.StringIO()) as log:
                    now[0] = 0.5
                    for held in reads:
                        dry.read_ring(lambda: held)
                    dry.ran_dry(0.5, 1, 0.0)
                self.assertEqual(dry.while_pedal_starting, 1)
                self.assertIn(said, log.getvalue())

    def test_the_bounds_are_not_moved_by_float_error(self):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        pedal.sent(pedal.pedal(True))
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            now[0] = 0.29
            dry.read_ring(lambda: 1)
            now[0] = 0.56
            dry.read_ring(lambda: 0)
            dry.ran_dry(0.27, 1, 0.0)
        self.assertIn("it ran dry between 0.29 and 0.56 s after the pedal turned on;", log.getvalue())

    def test_the_bounds_of_the_line_never_narrow(self):
        counted, log = self.away(-0.006, 0.0, empty_at=0.108)
        self.assertEqual(counted, 1)
        self.assertIn("it ran dry between 0.10 and 0.12 s after the pedal turned on;", log)

    def test_a_pedal_on_after_the_ring_was_seen_empty_does_not_count(self):
        counted, log = self.away(0.6, 0.7, empty_at=0.5)
        self.assertEqual(counted, 0)
        self.assertNotIn("voice pedal was starting", log)
        self.assertIn("the microphone ring ran dry (", log)

    def test_a_pedal_on_as_the_thread_left_may_be_after_the_dry_out(self):
        counted, log = self.away(0.11, 0.5)
        self.assertEqual(counted, 1)
        self.assertIn("(after the ring was last filled, maybe after it ran dry)", log)
        counted, log = self.away(0.095, 0.5)
        self.assertEqual(counted, 1)
        self.assertNotIn("maybe after it ran dry", log)

    def test_an_ended_start_keeps_its_own_track(self):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.sent(pedal.pedal(True))
            now[0] = 0.1
            pedal.track(stamp(0.1))
            now[0] = 6.0
            dry.read_ring(lambda: 1)
            now[0] = 6.1
            pedal.pedal(False)
            now[0] = 6.3
            pedal.track(stamp(6.3))
            now[0] = 6.35
            dry.read_ring(lambda: 0)
            dry.ran_dry(0.35, 1, 0.0)
        self.assertEqual(dry.while_pedal_starting, 0, "the first start's track came up 5.9 s before the ring was seen")
        self.assertIn("the microphone ring ran dry (", log.getvalue())

    def test_an_ended_start_does_not_take_the_track_of_the_start_after_it(self):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.sent(pedal.pedal(True))
            now[0] = 0.1
            pedal.track(stamp(0.1))
            now[0] = 6.0
            dry.read_ring(lambda: 1)
            now[0] = 6.1
            pedal.pedal(False)
            now[0] = 6.101
            dry.read_ring(lambda: 0)
            now[0] = 6.102
            pedal.sent(pedal.pedal(True))
            now[0] = 6.2
            pedal.track(stamp(6.112))
            dry.ran_dry(0.1, 1, 0.0)
        self.assertEqual(dry.while_pedal_starting, 0,
                         "the track at 6.112 s is the second start's, and the first one's came up 5.9 s before the ring")
        self.assertIn("the microphone ring ran dry (", log.getvalue())

    def pedal_off_while_its_track_is_told(self, up_at, filled_at, read_at):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        tell, told = dryouts.tell, []

        def off_while_told(line):
            if not told:
                told.append(line)
                pedal.pedal(False)
            tell(line)

        with mock.patch("sys.stderr", io.StringIO()) as log, mock.patch.object(dryouts, "tell", off_while_told):
            pedal.sent(pedal.pedal(True))
            now[0] = filled_at
            dry.read_ring(lambda: 1)
            now[0] = read_at
            pedal.track(stamp(up_at))
            now[0] = read_at + 0.05
            dry.read_ring(lambda: 0)
            dry.ran_dry(0.05, 1, 0.0)
        self.assertEqual(told, [f"voice pedal: its voice track came up between {up_at:.2f} and {read_at:.2f} s after "
                                f"the pedal turned on"])
        return dry.while_pedal_starting, log.getvalue()

    def test_a_pedal_off_while_its_track_is_told_keeps_the_track(self):
        counted, log = self.pedal_off_while_its_track_is_told(1.5, 1.2, 1.6)
        self.assertEqual(counted, 1)
        self.assertIn("its voice track came up between 0.15 and 0.05 s ago", log)

    def test_a_pedal_off_while_its_track_is_told_keeps_its_window(self):
        counted, log = self.pedal_off_while_its_track_is_told(0.1, 6.1, 6.15)
        self.assertEqual(counted, 1, "the track was seen after the ring was last filled, so it may be in the window")
        self.assertIn("its voice track came up between 6.10 and 0.05 s ago (maybe more than 5 s before the ring was "
                      "last filled), across the ring's last fill", log)

    def test_a_dry_out_classified_while_the_pedal_turns_off_sees_a_whole_start(self):
        now, inside = [0.0], []

        def clock():
            if inside:
                inside.pop()()
            return now[0]

        pedal = dryouts.VoicePedalStart(clock=clock)
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.sent(pedal.pedal(True))
            now[0] = 0.5
            dry.read_ring(lambda: 1)
            now[0] = 0.6
            dry.read_ring(lambda: 0)
            now[0] = 0.7
            inside.append(lambda: dry.ran_dry(0.05, 1, 0.0))
            pedal.pedal(False)
        self.assertEqual(dry.while_pedal_starting, 1)
        self.assertIn("the pedal turned on 0.70 s ago, its voice track isn't up yet", log.getvalue())

    def pedal_turning_off(self, up_at, filled_at, off_at):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        pedal.sent(pedal.pedal(True))
        now[0] = up_at
        with mock.patch.object(dryouts, "tell"):
            pedal.track(stamp(up_at))
        now[0] = filled_at
        dry.read_ring(lambda: 1)
        now[0] = off_at
        pedal._on[1] = off_at
        return now, pedal, dry

    def test_a_track_up_after_the_off_of_a_start_turning_off_is_not_its(self):
        now, pedal, dry = self.pedal_turning_off(0.1, 6.1, 6.2)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            now[0] = 6.3
            pedal.track(stamp(6.22))
            pedal._ended, pedal._on = (pedal._on,), None
            dry.read_ring(lambda: 0)
            dry.ran_dry(0.05, 1, 0.0)
        self.assertEqual(dry.while_pedal_starting, 0, "the start's own track came up 6.0 s before the ring was filled")
        self.assertNotIn("voice pedal: its voice track came up", log.getvalue())

    def test_a_ring_filled_after_the_off_is_not_the_pedals_in_either_phase_of_turning_off(self):
        for done, filled in ((False, 2.0), (True, 2.0), (False, 2.2), (True, 2.2)):
            with self.subTest(turning_off_done=done, filled=filled):
                now = [0.0]
                pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
                dry = dryouts.RingDryOuts(pedal)
                with mock.patch("sys.stderr", io.StringIO()) as log:
                    pedal.sent(pedal.pedal(True))
                    now[0] = 1.0
                    pedal.track(stamp(1.0))
                    now[0] = 2.0
                    pedal._on[1] = now[0]
                    if done:
                        pedal._ended, pedal._on = (pedal._on,), None
                    now[0] = filled
                    dry.read_ring(lambda: 1)
                    now[0] = 2.8
                    dry.read_ring(lambda: 0)
                    dry.ran_dry(0.6, 1, 0.0)
                self.assertEqual(dry.while_pedal_starting, 0, "the ring had music 0.2 s after the pedal turned off")
                self.assertIn("the microphone ring ran dry (", log.getvalue())

    def test_a_track_up_before_the_off_of_a_start_turning_off_is_its(self):
        now, pedal, dry = self.pedal_turning_off(0.1, 6.1, 6.2)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            now[0] = 6.3
            pedal.track(stamp(6.21))
            pedal._ended, pedal._on = (pedal._on,), None
            dry.read_ring(lambda: 0)
            dry.ran_dry(0.05, 1, 0.0)
        self.assertEqual(dry.while_pedal_starting, 1, "the start's track came up 0.01 s after its off, inside TICK_S")
        self.assertIn("voice pedal: its voice track came up between 6.21 and 6.30 s after the pedal turned on",
                      log.getvalue())

    def test_a_start_turning_off_is_told_without_a_ring(self):
        now, pedal, _ = self.pedal_turning_off(1.0, 1.5, 2.0)
        now[0] = 2.5
        self.assertEqual(pedal.starting()[1],
                         "the pedal turned on 2.50 s ago and off 0.50 s ago, its voice track came up 1.50 s ago")

    def ended_start_with_a_track_read_late(self, up_s_ago):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.sent(pedal.pedal(True))
            now[0] = 1.0
            dry.read_ring(lambda: 1)
            now[0] = 1.4
            pedal.pedal(False)
            now[0] = 1.656
            dry.read_ring(lambda: 0)
            pedal.track(stamp(now[0] - up_s_ago))
            dry.ran_dry(0.656, 1, 0.0)
        return dry.while_pedal_starting, log.getvalue()

    def test_an_ended_start_takes_its_track_read_after_it_ended(self):
        counted, log = self.ended_start_with_a_track_read_late(0.456)
        self.assertEqual(counted, 1)
        self.assertIn("came up between 0.46 and 0.00 s ago, after the ring was last filled, so which came first is "
                      "not known", log)

    def test_an_ended_start_does_not_take_a_track_up_after_it_ended(self):
        counted, log = self.ended_start_with_a_track_read_late(0.056)
        self.assertEqual(counted, 1)
        self.assertIn("its voice track isn't up yet", log)
        self.assertNotIn("voice pedal: its voice track came up", log, "a track up after the pedal turned off")

    def test_an_ended_start_takes_a_track_within_a_tick_of_its_end(self):
        for up_s_ago, said in ((0.246, "came up between 0.25 and 0.00 s ago, after the ring was last filled, so which "
                                       "came first is not "
                                       "known"),
                               (0.236, "its voice track isn't up yet")):
            with self.subTest(up_s_ago=up_s_ago):
                counted, log = self.ended_start_with_a_track_read_late(up_s_ago)
                self.assertEqual(counted, 1)
                self.assertIn(said, log)

    def pedal_off_at(self, off_at):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.sent(pedal.pedal(True))
            now[0] = 1.05
            pedal.track(stamp(1.05))
            for at, step in sorted([(1.2, lambda: dry.read_ring(lambda: 1)), (1.6, lambda: dry.read_ring(lambda: 0)),
                                    (off_at, lambda: pedal.pedal(False))], key=lambda x: x[0]):
                now[0] = at
                step()
            now[0] = 1.7
            dry.ran_dry(0.5, 1, 0.0)
        return dry.while_pedal_starting, log.getvalue()

    def test_a_pedal_off_before_the_ring_was_seen_empty_may_be_before_the_dry_out(self):
        counted, log = self.pedal_off_at(1.21)
        self.assertEqual(counted, 1)
        self.assertIn("and off 0.49 s ago (before the ring was seen empty, maybe before it ran dry), its voice track came up "
                      "0.65 s ago", log)

    def test_a_pedal_off_after_the_ring_was_seen_empty_has_no_doubt(self):
        counted, log = self.pedal_off_at(1.65)
        self.assertEqual(counted, 1)
        self.assertIn("and off 0.05 s ago, its voice track came up 0.65 s ago", log)

    def test_the_track_is_up_only_once_its_line_is_told(self):
        now = [4.99]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        pedal.sent(pedal.pedal(True))
        now[0] = 5.0
        seen = []
        with mock.patch.object(dryouts, "tell",
                               side_effect=lambda line: seen.append((pedal.track_up_at, pedal.starting()[1]))):
            pedal.track(stamp(5.0))
        self.assertEqual((seen, pedal.track_up_at),
                         ([(None, "the pedal turned on 0.01 s ago, its voice track isn't up yet")], 5.0))

    def test_a_track_read_after_its_pedal_turned_on_again_is_told_for_its_start(self):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        lines = []
        with mock.patch.object(dryouts, "tell", side_effect=lines.append):
            pedal.sent(pedal.pedal(True))
            now[0] = 2.3
            pedal.pedal(False)
            now[0] = 2.5
            pedal.sent(pedal.pedal(True))
            now[0] = 2.7
            pedal.track(stamp(1.5))
            now[0] = 3.5
            pedal.track(stamp(3.2))
        self.assertEqual(lines, ["voice pedal: its voice track came up between 0.50 and 1.70 s after the pedal turned "
                                 "on (maybe after it turned off)",
                                 "voice pedal: its voice track came up between 0.70 and 1.00 s after the pedal turned "
                                 "on"],
                         "one line for each start, each against its own pedal")

    def test_a_track_up_just_after_the_pedal_turned_on_again_is_the_start_that_is_on(self):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        lines = []
        with mock.patch.object(dryouts, "tell", side_effect=lines.append):
            pedal.sent(pedal.pedal(True))
            now[0] = 2.3
            pedal.pedal(False)
            now[0] = 2.302
            pedal.sent(pedal.pedal(True))
            now[0] = 2.5
            pedal.track(stamp(2.312))
        self.assertEqual(lines, ["voice pedal: its voice track came up between 0.01 and 0.20 s after the pedal turned "
                                 "on"],
                         "a track up in the start that is on is told against its pedal")

    def test_a_late_track_of_an_ended_start_survives_the_next_track(self):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        with mock.patch.object(dryouts, "tell"):
            pedal.sent(pedal.pedal(True))
            now[0] = 2.3
            pedal.pedal(False)
            now[0] = 2.4
            pedal.track(stamp(1.5))
            now[0] = 3.2
            pedal.track(stamp(3.2))
            told = pedal.starting(2.0, 2.4)[1]
        self.assertIn("its voice track came up between 1.70 and 0.80 s ago, across the ring's last fill", told,
                      "the track read after the pedal turned off is still that start's once another one came up")

    def test_a_late_track_of_an_earlier_start_is_not_the_next_ones(self):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        with mock.patch.object(dryouts, "tell"):
            pedal.sent(pedal.pedal(True))
            now[0] = 2.3
            pedal.pedal(False)
            now[0] = 2.4
            pedal.track(stamp(1.5))
            now[0] = 3.0
            pedal.sent(pedal.pedal(True))
            now[0] = 3.5
            pedal.track(stamp(3.5))
            now[0] = 4.0
            pedal.pedal(False)
            now[0] = 4.5
            pedal.track(stamp(4.5))
            told = pedal.starting(3.8, 4.1)[1]
        self.assertIn("its voice track came up 1.00 s ago", told,
                      "the second start keeps its own track, and not the one read late for the first")

    def test_an_ended_start_does_not_take_the_next_starts_track_within_a_tick(self):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        with mock.patch.object(dryouts, "tell"):
            pedal.sent(pedal.pedal(True))
            now[0] = 2.3
            pedal.pedal(False)
            now[0] = 2.302
            pedal.sent(pedal.pedal(True))
            now[0] = 2.5
            pedal.track(stamp(2.312))
            told = pedal.starting(2.0, 2.301)[1]
        self.assertIn("its voice track isn't up yet", told,
                      "a track up in the start that is on isn't the ended start's, even within a tick of its end")

    def test_each_dry_out_count_has_its_own_injector_number(self):
        counts = [dryouts.RingDryOuts(dryouts.VoicePedalStart()) for _ in range(2)]
        self.assertEqual(counts[1].state()["injetor"], counts[0].state()["injetor"] + 1)

    def test_without_a_fill_the_window_ends_at_the_empty_read(self):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.sent(pedal.pedal(True))
            now[0] = 1.1
            pedal.track(stamp(1.1))
            now[0] = 6.0
            dry.read_ring(lambda: 0)
            now[0] = 6.2
            dry.ran_dry(0.2, 1, 0.0)
        self.assertEqual(dry.while_pedal_starting, 1, "the ring was seen empty 4.9 s after the track came up")
        self.assertIn("its voice track came up 5.10 s ago, with no fill seen, so which came first is not known",
                      log.getvalue())

    def test_without_a_fill_the_pedal_may_have_turned_on_after_the_ring_ran_dry(self):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.sent(pedal.pedal(True))
            now[0] = 6.0
            dry.read_ring(lambda: 0)
            now[0] = 6.2
            dry.ran_dry(0.2, 1, 0.0)
        self.assertIn("the pedal turned on 5.20 s ago (with no fill seen, maybe after it ran dry), its voice track "
                      "isn't up yet", log.getvalue())

    def test_without_a_fill_a_track_up_within_a_tick_of_the_empty_read_has_no_order(self):
        for up_at, wording in ((6.01, "with no fill seen, so which came first is not known"),
                               (6.02, "after the ring ran dry")):
            with self.subTest(up_at=up_at):
                now = [1.0]
                pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
                dry = dryouts.RingDryOuts(pedal)
                with mock.patch("sys.stderr", io.StringIO()) as log:
                    pedal.sent(pedal.pedal(True))
                    now[0] = 6.0
                    dry.read_ring(lambda: 0)
                    now[0] = up_at
                    pedal.track(stamp(up_at))
                    now[0] = 6.2
                    dry.ran_dry(0.2, 1, 0.0)
                self.assertIn(f"s ago, {wording}", log.getvalue())

    def test_without_a_ring_the_window_ends_now(self):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        with mock.patch("sys.stderr", io.StringIO()):
            pedal.sent(pedal.pedal(True))
            now[0] = 1.0
            pedal.track(stamp(1.0))
        now[0] = 5.9
        self.assertEqual(pedal.starting()[1], "the pedal turned on 5.90 s ago, its voice track came up 4.90 s ago")
        now[0] = 6.1
        self.assertEqual(pedal.starting(), (0.0, None), "5.1 s after the track came up, with no read of the ring")

    def test_without_a_fill_a_start_ended_after_the_empty_read_is_the_dry_outs(self):
        counted, log = self.run_starts([(1.0, "on"), (1.1, "track"), (1.2, "empty"), (1.25, "off")], 1.3)
        self.assertEqual(counted, 1, "the pedal was still on when the ring was seen empty")
        self.assertIn("its voice track came up 0.20 s ago", log)
        counted, _ = self.run_starts([(1.0, "on"), (1.1, "track"), (1.15, "off"), (1.2, "empty")], 1.3)
        self.assertEqual(counted, 0, "the pedal turned off before the ring was seen empty, maybe before it ran dry")
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()):
            pedal.sent(pedal.pedal(True))
            pedal._on[1] = 1.15
            now[0] = 1.2
            dry.read_ring(lambda: 0)
            now[0] = 1.3
            dry.ran_dry(0.1, 1, 0.0)
        self.assertEqual(dry.while_pedal_starting, 0, "a start turning off before the empty read is the same")

    def test_an_ended_start_is_not_taken_without_a_fill_seen(self):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        pedal.sent(pedal.pedal(True))
        now[0] = 1.0
        pedal.pedal(False)
        now[0] = 2.0
        self.assertEqual(pedal.starting(None, 1.5), (None, None),
                         "with no read that found something, the dry-out may have come before the start ended or not")

    def run_starts(self, steps, at):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            for t, step, *up in steps:
                now[0] = t
                {"on": lambda: pedal.sent(pedal.pedal(True)), "off": lambda: pedal.pedal(False),
                 "track": lambda: pedal.track(stamp((up or [t])[0])), "fill": lambda: dry.read_ring(lambda: 1),
                 "empty": lambda: dry.read_ring(lambda: 0)}[step]()
            now[0] = at
            dry.ran_dry(at - 1.3, 1, 0.0)
        return dry.while_pedal_starting, log.getvalue()

    def test_a_dry_out_seen_before_two_starts_ended_is_the_first_starts(self):
        counted, log = self.run_starts([(1.0, "on"), (1.2, "track"), (1.3, "fill"), (1.4, "empty"), (1.5, "off"),
                                        (1.6, "on"), (1.7, "off")], 1.75)
        self.assertEqual(counted, 1, "the first start was on when the ring was seen empty")
        self.assertIn("the pedal turned on 0.75 s ago and off 0.25 s ago, its voice track came up 0.55 s ago", log)

    def test_of_two_ended_starts_that_cross_the_dry_out_the_latest_is_told(self):
        counted, log = self.run_starts([(1.0, "on"), (1.05, "track"), (1.3, "fill"), (1.32, "off"), (1.34, "on"),
                                        (1.36, "track"), (1.4, "empty"), (1.45, "off")], 1.5)
        self.assertEqual(counted, 1)
        self.assertIn("the pedal turned on 0.16 s ago (after the ring was last filled, maybe after it ran dry) and "
                      "off 0.05 s ago", log)

    def test_a_track_read_after_two_starts_ended_is_the_latest_one_it_fits(self):
        _, log = self.run_starts([(1.0, "on"), (1.5, "off"), (1.502, "on"), (1.6, "off"), (1.7, "track", 1.512)], 1.8)
        self.assertIn("voice pedal: its voice track came up between 0.01 and 0.20 s after the pedal turned on", log)

    def test_a_track_read_after_two_starts_ended_still_finds_the_first(self):
        counted, log = self.run_starts([(1.0, "on"), (1.3, "fill"), (1.4, "empty"), (1.5, "off"),
                                        (1.6, "on"), (1.7, "off"), (1.75, "track", 1.2)], 1.75)
        self.assertEqual(counted, 1)
        self.assertIn("voice pedal: its voice track came up between 0.20 and 0.75 s after the pedal turned on", log)
        self.assertIn("the pedal turned on 0.75 s ago and off 0.25 s ago, its voice track came up between 0.55 and "
                      "0.00 s "
                      "ago, across the ring's last fill", log)

    def test_a_track_up_before_its_start_was_sent_is_not_its(self):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        with mock.patch("sys.stderr", io.StringIO()) as log:
            start = pedal.pedal(True)
            now[0] = 1.2
            pedal.track(stamp(1.05))
            now[0] = 1.3
            pedal.sent(start)
            now[0] = 1.4
            pedal.pedal(False)
            now[0] = 1.5
            pedal.track(stamp(1.1))
        self.assertNotIn("voice pedal:", log.getvalue(), "both tracks came up before the start's liga(True) was sent")

    def test_a_stamp_in_the_millisecond_its_start_was_sent_is_not_its(self):
        for sent_at, up_at, read_at, told in ((2.4999, 2.4996, 2.6, False), (2.4999, 2.501, 2.6, True),
                                              (2.5043, 2.505, 2.5075, True), (2.5054, 2.505, 2.5065, False),
                                              (2.5009, 2.5006, 2.6025, False), (2.4999, 2.501, 2.6015, True)):
            with self.subTest(sent_at=sent_at, up_at=up_at, read_at=read_at):
                now = [2.0]
                pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
                with mock.patch("sys.stderr", io.StringIO()) as log:
                    start = pedal.pedal(True)
                    now[0] = sent_at
                    pedal.sent(start)
                    now[0] = read_at
                    pedal.track(stamp(up_at))
                self.assertEqual("voice pedal:" in log.getvalue(), told)

    def test_a_fill_for_the_readers_before_a_change_does_not_bound_the_next_dry_out(self):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        dry = dryouts.RingDryOuts(pedal)
        with mock.patch("sys.stderr", io.StringIO()):
            pedal.sent(pedal.pedal(True))
            dry.served((1,))
            now[0] = 1.1
            pedal.track(stamp(1.1))
            dry.read_ring(lambda: 1)
            now[0] = 10.0
            dry.served((2,))
            dry.read_ring(lambda: 0)
            now[0] = 10.05
            dry.read_ring(lambda: 0)
            dry.ran_dry(0.05, 1, 0.0)
        self.assertEqual(dry.while_pedal_starting, 0, "the track came up 8.9 s before the ring was seen empty")

    def test_a_start_sent_again_keeps_when_it_was_first_sent(self):
        now = [1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.sent(pedal.pedal(True))
            now[0] = 2.0
            pedal.sent(pedal.pedal(True))
            now[0] = 2.1
            pedal.track(stamp(1.5))
        self.assertIn("voice pedal: its voice track came up between 0.50 and 1.10 s after the pedal turned on",
                      log.getvalue())

    def test_only_the_last_ended_starts_are_kept(self):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        for i in range(3 * dryouts.ENDED_STARTS):
            now[0] = float(i)
            pedal.sent(pedal.pedal(True))
            pedal.pedal(False)
        self.assertEqual([on for on, *_ in pedal._ended],
                         list(range(2 * dryouts.ENDED_STARTS, 3 * dryouts.ENDED_STARTS)))

    def test_a_stamp_from_before_the_wrap_read_after_it(self):
        wrap = 2**32 / 1000
        now = [wrap - 1.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.sent(pedal.pedal(True))
            now[0] = wrap + 0.5
            pedal.track(stamp(wrap - 0.5))
        self.assertAlmostEqual(pedal.track_up_at, wrap - 0.5, places=3)
        self.assertIn("its voice track came up between 0.50 and 1.50 s after the pedal turned on", log.getvalue())

    def test_one_stamp_is_one_start(self):
        pedal = dryouts.VoicePedalStart(clock=lambda: 5.0)
        pedal.sent(pedal.pedal(True))
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.clock = lambda: 6.0
            pedal.track(stamp(5.8))
            pedal.clock = lambda: 6.5
            pedal.track(stamp(5.8))
            pedal.track(stamp(5.8))
            pedal.track(stamp(5.8))
        self.assertEqual(log.getvalue().count("its voice track came up"), 1,
                         "the same stamp read again is the same start")


class TestVoicePedalDryOut(unittest.TestCase):
    def setUp(self):
        self.k = K32Falso(aberturas=3)
        self.tick = 10_000
        self.k.GetTickCount64 = lambda: self.tick
        a = self.a = injeta.Anel.from_address(self.k.p)
        a.leitor[0].dono, a.leitor[0].batida, a.leitor[0].ep = 1, self.tick, ALVO
        self.motor = MotorFalso()
        self.now = 1000.0
        self.motor.voice_pedal = dryouts.VoicePedalStart(clock=lambda: self.now)
        self.drain, self.gate, self.held = threading.Event(), threading.Event(), threading.Event()
        self.gate.set()
        self.read_gate, self.read_held = threading.Event(), threading.Event()
        self.read_gate.set()
        self.readers_gate, self.readers_held = threading.Event(), threading.Event()
        self.readers_gate.set()
        self.after_read_gate, self.after_read_held = threading.Event(), threading.Event()
        self.after_read_gate.set()
        self.write_gate, self.write_held = threading.Event(), threading.Event()
        self.write_gate.set()
        self.log = io.StringIO()
        full = eng.INJ_FOLGA * eng.BLOCK

        self.wrote = self.drain_next = self.fail_next = False

        def na_fila(m):
            if not self.gate.is_set():
                self.held.set()
                self.gate.wait()
                if self.drain_next:
                    self.drain_next = False
                    self.drain.set()
                    return full
            if self.wrote:
                self.wrote = False
                return full
            if self.drain.is_set():
                self.drain.clear()
                return 0
            return full

        def escreve(m, x):
            if self.fail_next:
                self.fail_next = False
                raise OSError("the ring failed")
            if not self.write_gate.is_set():
                self.write_held.set()
                self.write_gate.wait()
            self.wrote = True
            return len(x)

        pista_ligou, vivos = injeta.Microfone.pista_ligou, injeta.Microfone.vivos

        def readers(m):
            if not self.readers_gate.is_set():
                self.readers_held.set()
                self.readers_gate.wait()
            return vivos(m)

        def read_track(m):
            if not self.read_gate.is_set():
                self.read_held.set()
                self.read_gate.wait()
            stamp = pista_ligou(m)
            if m.a.pista_estado >> 32 and not self.after_read_gate.is_set():
                self.after_read_held.set()
                self.after_read_gate.wait()
            return stamp

        patches = [mock.patch.object(injeta, "k32", self.k), mock.patch.object(injeta.Microfone, "na_fila", na_fila),
                   mock.patch.object(injeta.Microfone, "escreve", escreve),
                   mock.patch.object(injeta.Microfone, "pista_ligou", read_track),
                   mock.patch.object(injeta.Microfone, "vivos", readers),
                   mock.patch.object(injeta, "clock", lambda: self.now),
                   mock.patch.object(eng.preset, "pede", return_value=None), mock.patch("sys.stderr", self.log)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.producer = injeta.Microfone()
        self.inj = eng.Injetor(self.motor)
        self.addCleanup(self.inj.para)
        self.addCleanup(self.gate.set)
        self.addCleanup(self.read_gate.set)
        self.addCleanup(self.readers_gate.set)
        self.addCleanup(self.after_read_gate.set)
        self.addCleanup(self.write_gate.set)
        self.assertTrue(espera(lambda: self.inj.folga_min is not None), "the injector never served the reader")
        self.dry_done = threading.Event()
        ran_dry = self.inj.dry_outs.ran_dry

        def told(back_s, count, longest):
            self.live_at_dry = self.motor._pista_viva
            ran_dry(back_s, count, longest)
            self.dry_done.set()

        self.inj.dry_outs.ran_dry = told

    def advance(self, seconds):
        self.now += seconds
        self.tick += round(seconds * 1000)
        self.a.leitor[0].batida = self.tick

    def wait_filled(self):
        self.assertTrue(espera(lambda: self.inj.dry_outs.filled_at == self.now),
                        "the ring thread never saw the ring full at the test's time")

    def published(self):
        self.assertTrue(espera(lambda: self.inj.estado()["secas"] == self.inj.secas),
                        "the pass that saw the dry ring never published its counts")

    def dry_out(self):
        self.wait_filled()
        self.dry_done.clear()
        self.drain.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")
        self.published()

    def dry_out_after_away(self, away_s):
        self.wait_filled()
        self.held.clear()
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        self.advance(away_s)
        self.dry_done.clear()
        self.drain.set()
        self.gate.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")
        self.published()

    def logged(self):
        return self.log.getvalue()

    def plain_lines(self):
        return self.logged().count("the microphone ring ran dry (")

    def seen_up(self):
        self.assertTrue(espera(lambda: self.motor.voice_pedal.track_up_at is not None),
                        "the injector never saw the voice track")

    def track_up(self):
        self.producer.pista_liga(True)
        self.seen_up()

    def pedal_on(self, seconds_ago):
        self.now -= seconds_ago + 0.001
        self.motor.voice_pedal.sent(self.motor.voice_pedal.pedal(True))
        self.now += seconds_ago + 0.001

    def pedal_lines(self):
        return [ln for ln in self.logged().splitlines() if "while the voice pedal was starting" in ln]

    def offset(self, line, what):
        return float(re.search(what + r" (?:between )?(\d+\.\d+)(?: and \d+\.\d+)? s ago", line).group(1))

    def test_dry_out_before_the_track_is_up(self):
        self.pedal_on(2.0)
        self.dry_out()
        self.assertEqual((self.inj.dry_outs.while_pedal_starting, self.inj.estado()["secas_pedal"]), (1, 1))
        line = self.pedal_lines()[-1]
        self.assertIn("its voice track isn't up yet", line)
        self.assertEqual(self.offset(line, "turned on"), 2.0)
        self.now += 1.0
        self.dry_out()
        self.assertEqual((self.inj.dry_outs.while_pedal_starting, len(self.pedal_lines()), self.plain_lines()),
                         (2, 2, 0), "each dry-out while the pedal starts is told, without the quiet window")
        self.advance(0.7)
        self.track_up()
        self.assertIn("its voice track came up 3.70 s after the pedal turned on", self.logged())

    def test_dry_out_after_the_track_came_up(self):
        self.pedal_on(1.0)
        self.track_up()
        self.advance(0.3)
        self.producer.pista_pulso()
        self.dry_out()
        self.assertEqual(self.inj.dry_outs.while_pedal_starting, 1)
        line = self.pedal_lines()[-1]
        self.assertEqual((self.offset(line, "turned on"), self.offset(line, "came up")), (1.3, 0.3))

    def test_track_that_came_up_while_the_injector_was_away(self):
        self.pedal_on(1.0)
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        self.producer.pista_liga(True)
        self.advance(0.5)
        self.producer.pista_pulso()
        self.gate.set()
        self.seen_up()
        self.dry_out()
        line = self.pedal_lines()[-1]
        self.assertEqual((self.offset(line, "turned on"), self.offset(line, "came up")), (1.5, 0.5))

    def test_track_off_and_on_while_the_injector_was_away(self):
        self.pedal_on(0.0)
        self.track_up()
        first = self.motor.voice_pedal.track_up_at
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        self.producer.pista_liga(False)
        self.motor.voice_pedal.pedal(False)
        self.advance(dryouts.AFTER_TRACK_S)
        self.pedal_on(0.0)
        self.producer.pista_liga(True)
        self.advance(0.2)
        self.producer.pista_pulso()
        self.gate.set()
        self.assertTrue(espera(lambda: self.motor.voice_pedal.track_up_at != first), "the new track was not seen")
        self.dry_out()
        self.assertEqual(self.offset(self.pedal_lines()[-1], "came up"), 0.2)

    def test_track_after_a_voice_process_that_was_killed(self):
        injeta.Microfone().pista_liga(True)
        self.seen_up()
        self.advance(30.0)
        self.assertTrue(espera(lambda: not self.motor._pista_viva), "the killed track never went quiet")
        self.pedal_on(1.0)
        old = self.motor.voice_pedal.track_up_at
        self.producer.pista_liga(True)
        self.assertTrue(espera(lambda: self.motor.voice_pedal.track_up_at != old), "the new track never came up")
        self.dry_out()
        self.assertIn("came up 0.00 s ago", self.pedal_lines()[-1])

    def test_track_on_and_off_while_the_injector_was_away(self):
        self.pedal_on(1.0)
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        self.producer.pista_liga(True)
        self.advance(0.3)
        self.producer.pista_liga(False)
        self.advance(0.2)
        self.gate.set()
        self.assertTrue(espera(lambda: self.motor.voice_pedal.track_up_at is not None), "the track was not seen")
        self.dry_out()
        self.assertEqual(self.offset(self.pedal_lines()[-1], "came up"), 0.5)
        self.assertIn("its voice track came up between 1.00 and 1.50 s after the pedal turned on", self.logged())

    def test_a_track_up_just_after_the_last_fill_has_no_order(self):
        self.pedal_on(1.0)
        self.wait_filled()
        self.read_gate.clear()
        self.assertTrue(self.read_held.wait(3), "the injector never got to the voice track")
        self.advance(0.03)
        self.producer.pista_liga(True)
        self.dry_done.clear()
        self.drain.set()
        self.read_gate.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")
        self.assertIn("came up 0.00 s ago, after the ring was last filled, so which came first is not known",
                      self.pedal_lines()[-1])

    def hold_producer(self, where):
        entered, release = threading.Event(), threading.Event()
        real = getattr(where[0], where[1])

        def held(*args):
            if threading.current_thread().name == "producer":
                entered.set()
                release.wait(5)
            return real(*args)
        self.enterContext(mock.patch.object(where[0], where[1], held))
        producer = threading.Thread(target=self.producer.pista_liga, name="producer", daemon=True)
        producer.start()
        self.addCleanup(producer.join, 5)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(3), "the producer never got to the hold")
        return release

    def test_a_track_turning_on_is_not_up_before_it_is_on(self):
        self.pedal_on(0.5)
        release = self.hold_producer((self.k, "GetTickCount64"))
        self.dry_out()
        release.set()
        self.assertIn("its voice track isn't up yet", self.pedal_lines()[-1])

    def test_frames_read_before_the_track_turns_off_in_the_pass_are_heard(self):
        self.track_up()
        pushed, armed = [], [True]
        self.motor._push_voz_fx = lambda x: pushed.append(len(x))
        track = self.motor.voice_pedal.track

        def turning_off(stamp):
            if armed[0] and self.inj.m.pista_pos == self.a.pista_escrito > 0:
                armed[0] = False
                self.producer.pista_liga(False)
            return track(stamp)
        self.motor.voice_pedal.track = turning_off
        self.producer.pista_escreve(eng.np.zeros(2 * eng.BLOCK, eng.np.float32))
        self.assertTrue(espera(lambda: not armed[0]), "the injector never read the frames")
        self.assertTrue(espera(lambda: sum(pushed) == 2 * eng.BLOCK), "the pass read the track live and must hear "
                        f"what it read, not {sum(pushed)} frames")

    def test_a_track_turns_on_with_its_stamp_in_one_write(self):
        self.pedal_on(0.5)
        release = self.hold_producer((injeta, "clock"))
        self.assertEqual(self.a.pista_estado, 0, "the track went on before its stamp")
        self.dry_out()
        self.assertIn("its voice track isn't up yet", self.pedal_lines()[-1])
        release.set()
        self.assertTrue(espera(lambda: 0 != self.a.pista_estado >> 32 == self.motor.voice_pedal._stamp),
                        "the injector never read the stamp")
        self.assertEqual((self.a.pista_estado & 1, self.logged().count("voice pedal: its voice track came up")), (1, 1))
        stamped = self.a.pista_estado >> 32
        self.producer.pista_liga(False)
        self.assertEqual(self.a.pista_estado, stamped << 32, "turning off keeps the stamp")

    def test_a_track_published_after_its_clock_has_no_order_across_the_fill(self):
        line = self.published_after_the_empty_read(0.1)
        self.assertIn("across the ring's last fill, so which came first is not known", line)
        self.assertNotIn("maybe more than", line)

    def test_a_track_published_more_than_the_window_after_its_clock_counts_with_the_note(self):
        line = self.published_after_the_empty_read(dryouts.AFTER_TRACK_S + 0.2)
        self.assertEqual((self.inj.secas, self.inj.dry_outs.while_pedal_starting), (1, 1),
                         "the track was published after the empty read, so it may be in the window")
        self.assertIn("(maybe more than 5 s before the ring was last filled), across the ring's last fill, so which "
                      "came first is not known", line)

    def published_after_the_empty_read(self, held_s):
        self.pedal_on(1.0)
        entered, release = threading.Event(), threading.Event()
        real = injeta.clock

        def held():
            sampled = real()
            if threading.current_thread().name == "producer":
                entered.set()
                release.wait(5)
            return sampled
        self.enterContext(mock.patch.object(injeta, "clock", held))
        producer = threading.Thread(target=self.producer.pista_liga, name="producer", daemon=True)
        producer.start()
        self.addCleanup(producer.join, 5)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(3), "the producer never read its clock")
        self.advance(held_s)
        self.wait_filled()
        read_ring = self.inj.dry_outs.read_ring

        def published_after_the_empty_read(read):
            held_now = read_ring(read)
            if held_now == 0 and not release.is_set():
                release.set()
                self.assertTrue(espera(lambda: self.a.pista_estado != 0), "the producer never published")
            return held_now
        self.inj.dry_outs.read_ring = published_after_the_empty_read
        self.dry_done.clear()
        self.drain.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")
        self.published()
        return self.pedal_lines()[-1]

    def test_dry_out_long_after_the_track_came_up(self):
        self.pedal_on(0.0)
        self.track_up()
        self.now += dryouts.AFTER_TRACK_S + 0.1
        self.dry_out()
        self.assertEqual((self.inj.secas, self.inj.dry_outs.while_pedal_starting), (1, 0))
        self.assertEqual(self.pedal_lines(), [])

    def test_dry_out_seen_past_the_window_of_a_track_up_within_it(self):
        self.pedal_on(1.0)
        self.track_up()
        self.advance(4.9)
        self.dry_out_after_away(0.656)
        self.assertEqual(self.inj.dry_outs.while_pedal_starting, 1, "the ring ran dry 4.9 s after the track came up")
        self.assertIn("came up 5.56 s ago", self.pedal_lines()[-1])

    def test_dry_out_of_a_ring_filled_past_the_window_of_a_track_up(self):
        self.pedal_on(1.0)
        self.track_up()
        self.advance(dryouts.AFTER_TRACK_S + 0.2)
        self.dry_out_after_away(0.656)
        self.assertEqual((self.inj.secas, self.inj.dry_outs.while_pedal_starting), (1, 0))

    def test_pedal_and_track_up_while_the_ring_was_being_filled(self):
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        self.advance(0.3)
        self.pedal_on(0.0)
        self.producer.pista_liga(True)
        self.dry_done.clear()
        self.drain_next = True
        self.gate.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")
        self.published()
        self.assertEqual(self.inj.estado()["secas_pedal"], 1, "the pedal turned on before the read that saw the ring")
        line = self.pedal_lines()[-1]
        self.assertIn("(after the ring was last filled, maybe after it ran dry)", line)
        self.assertIn("so which came first is not known", line)

    def test_track_up_while_the_read_that_saw_the_dry_ring_was_held(self):
        self.pedal_on(1.0)
        self.wait_filled()
        self.held.clear()
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        self.advance(0.01)
        self.producer.pista_liga(True)
        self.dry_done.clear()
        self.drain.set()
        self.gate.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")
        self.assertIn("came up 0.00 s ago, within a tick of the ring's last fill, so which came first is not known",
                      self.pedal_lines()[-1])
        self.assertEqual(self.logged().count("voice pedal: its voice track came up"), 1,
                         "one line for the track coming up")
        self.assertFalse(self.live_at_dry, "the second reading of the track left the pass's mix as _voz chose it")

    def test_track_up_while_the_reader_held_the_ring(self):
        self.pedal_on(1.0)
        self.wait_filled()
        self.held.clear()
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        self.advance(0.1)
        self.producer.pista_liga(True)
        self.advance(0.1)
        self.dry_done.clear()
        self.drain.set()
        self.gate.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")
        self.assertIn("came up between 0.10 and 0.00 s ago, after the ring was last filled, so which came first is "
                      "not known",
                      self.pedal_lines()[-1])

    def test_track_up_after_the_ring_was_seen_empty(self):
        self.pedal_on(1.0)
        self.wait_filled()
        self.held.clear()
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        self.read_held.clear()
        self.read_gate.clear()
        self.dry_done.clear()
        self.drain.set()
        self.gate.set()
        self.assertTrue(self.read_held.wait(3), "the injector never read the track again")
        self.advance(0.1)
        self.producer.pista_liga(True)
        self.read_gate.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")
        self.assertIn("came up 0.00 s ago, after the ring ran dry", self.pedal_lines()[-1])

    def test_pedal_off_after_the_ring_ran_dry(self):
        self.pedal_on(1.0)
        self.track_up()
        self.wait_filled()
        self.held.clear()
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        self.advance(0.3)
        self.motor.voice_pedal.pedal(False)
        self.dry_done.clear()
        self.drain.set()
        self.gate.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")
        self.assertEqual(self.inj.dry_outs.while_pedal_starting, 1, "the ring ran dry with the pedal on")
        self.assertIn("the pedal turned on 1.30 s ago and off 0.00 s ago", self.pedal_lines()[-1])

    def pedal_off_before_its_track_is_seen(self, stalled_s):
        self.pedal_on(1.0)
        self.wait_filled()
        self.readers_gate.clear()
        self.assertTrue(self.readers_held.wait(3), "the injector never got past the voice track")
        self.read_gate.clear()
        self.producer.pista_liga(True)
        self.advance(stalled_s)
        self.readers_gate.set()
        self.assertTrue(self.read_held.wait(3), "the injector never came back to the voice track")
        self.advance(0.01)
        self.motor.voice_pedal.pedal(False)
        self.dry_done.clear()
        self.drain.set()
        self.read_gate.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")

    def test_pedal_off_before_its_track_was_seen(self):
        self.pedal_off_before_its_track_is_seen(0.2)
        self.assertEqual(self.inj.dry_outs.while_pedal_starting, 1)
        up = "its voice track came up between 1.00 and 1.21 s after the pedal turned on"
        self.assertEqual(self.logged().count(up + "\n"), 1,
                         "the track was seen within a tick of the pedal turning off, so its line is written once, "
                         "with no note")
        self.assertIn("its voice track came up between 0.21 and 0.00 s ago", self.pedal_lines()[-1])

    def test_pedal_off_before_its_track_was_seen_past_its_window(self):
        self.pedal_off_before_its_track_is_seen(dryouts.AFTER_TRACK_S + 0.2)
        self.assertEqual((self.inj.secas, self.inj.dry_outs.while_pedal_starting), (1, 1),
                         "the track was seen after the ring was last filled, so it may be in the window")
        self.assertIn("(maybe more than 5 s before the ring was last filled), across the ring's last fill",
                      self.pedal_lines()[-1])

    def test_track_time_read_before_the_thread_stalled(self):
        self.pedal_on(1.0)
        self.after_read_held.clear()
        self.after_read_gate.clear()
        self.producer.pista_liga(True)
        up_at = self.now
        self.assertTrue(self.after_read_held.wait(3), "the injector never read the voice track")
        self.advance(0.656)
        self.after_read_gate.set()
        self.seen_up()
        self.assertEqual(self.motor.voice_pedal.track_up_at, up_at)
        self.assertIn("its voice track came up between 1.00 and 1.66 s after the pedal turned on", self.logged())

    def test_track_up_as_the_clock_wraps(self):
        self.advance(2**32 / 1000 - self.now)
        self.pedal_on(1.0)
        self.track_up()
        self.assertEqual(self.motor.voice_pedal.track_up_at, self.now)
        self.assertIn("its voice track came up 1.00 s after the pedal turned on", self.logged())

    def test_track_stamped_where_the_stamp_wraps_read_after_it(self):
        self.advance((2**32 - 1) / 1000 - self.now)
        self.pedal_on(1.0)
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        up_at = self.now
        self.producer.pista_liga(True)
        self.assertEqual(self.producer.a.pista_estado >> 32, 1)
        self.advance(0.5)
        self.producer.pista_pulso()
        self.gate.set()
        self.seen_up()
        self.assertEqual(self.motor.voice_pedal.track_up_at, up_at)
        self.assertIn("its voice track came up between 1.00 and 1.50 s after the pedal turned on", self.logged())

    def test_the_counts_are_published_together(self):
        self.pedal_on(1.0)
        hold, held = threading.Event(), threading.Event()
        starting = self.motor.voice_pedal.starting

        def held_starting(*a):
            held.set()
            hold.wait()
            return starting(*a)

        self.addCleanup(hold.set)
        self.motor.voice_pedal.starting = held_starting
        self.wait_filled()
        self.dry_done.clear()
        self.drain.set()
        self.assertTrue(held.wait(3), "the ring never ran dry")
        state = self.inj.estado()
        self.assertEqual((self.inj.secas, state["secas"], state["secas_pedal"]), (1, 0, 0))
        hold.set()
        self.assertTrue(self.dry_done.wait(3.0), "the dry-out was never told")
        self.published()
        state = self.inj.estado()
        self.assertEqual((state["secas"], state["secas_pedal"]), (1, 1))

    def test_a_dry_out_is_published_before_the_ring_is_filled_again(self):
        self.pedal_on(1.0)
        self.wait_filled()
        self.held.clear()
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        since = time.perf_counter()
        self.assertTrue(espera(lambda: time.perf_counter() - since > 0.3))
        self.write_held.clear()
        self.write_gate.clear()
        self.drain_next = True
        self.gate.set()
        self.assertTrue(self.write_held.wait(3), "the ring was never filled again after it ran dry")
        state = self.inj.estado()
        self.assertEqual((state["secas"], state["secas_pedal"]), (1, 1),
                         "a dry-out already classified waited for the ring to be filled again")
        self.assertGreater(state["volta_max_ms"], 300, "its return waited for the ring to be filled again")

    def test_a_dry_out_after_the_longest_return_was_zeroed_publishes_its_own(self):
        self.pedal_on(1.0)
        self.wait_filled()
        self.held.clear()
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        since = time.perf_counter()
        self.assertTrue(espera(lambda: time.perf_counter() - since > 0.3))
        self.drain_next = True
        self.gate.set()
        self.assertTrue(espera(lambda: self.inj.volta_max > 0.3 and self.inj.estado()["volta_max_ms"] > 300),
                        "the pass with the long return never ended")
        self.held.clear()
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got back to the ring")
        self.inj.volta_max = 0.0
        self.write_held.clear()
        self.write_gate.clear()
        self.drain.set()
        self.gate.set()
        self.assertTrue(self.write_held.wait(3), "the ring was never filled again after it ran dry")
        state = self.inj.estado()
        self.assertEqual(state["secas"], self.inj.secas, "the second dry-out was not published before the refill")
        self.assertLess(state["volta_max_ms"], 300, "the dry-out published the longest return from before it was zeroed")

    def test_each_change_of_the_readers_is_in_the_state(self):
        self.wait_filled()
        before = self.inj.estado()["leitores_trocados"]
        for n, (owner, what) in enumerate(((2, "another reader"), (0, "no reader"), (2, "the reader back")), 1):
            self.a.leitor[0].dono = owner
            self.assertTrue(espera(lambda n=n: self.inj.estado()["leitores_trocados"] == before + n), what)

    def test_a_new_reader_is_in_the_state_before_the_ring_is_filled_for_it(self):
        self.wait_filled()
        before = self.inj.estado()["leitores_trocados"]
        self.readers_held.clear()
        self.readers_gate.clear()
        self.assertTrue(self.readers_held.wait(3), "the injector never got to its readers")
        self.write_held.clear()
        self.write_gate.clear()
        self.a.leitor[0].dono = 2
        self.drain.set()
        self.readers_gate.set()
        self.assertTrue(self.write_held.wait(3), "the ring was never filled for the new reader")
        self.assertEqual((self.inj.secas, self.inj.estado()["leitores_trocados"]), (0, before + 1),
                         "the new reader waited for the ring to be filled for it")

    def test_the_readers_and_their_changes_are_published_together(self):
        self.a.leitor[0].dono = 0
        self.assertTrue(espera(lambda: self.inj.estado()["leitores"] == 0), "the reader never went")
        before = self.inj.estado()["leitores_trocados"]
        hold, held = threading.Event(), threading.Event()
        volta = self.inj.saude.volta

        def held_volta(*a, **kw):
            if kw.get("leitores") and not held.is_set():
                held.set()
                hold.wait()
            return volta(*a, **kw)

        self.addCleanup(hold.set)
        self.inj.saude.volta = held_volta
        self.a.leitor[0].dono = 1
        self.assertTrue(held.wait(3), "the reader never came back")
        state = self.inj.estado()
        self.assertEqual((state["leitores"], state["leitores_trocados"]), (0, before),
                         "the reader came back in the state before its change was counted")
        hold.set()
        self.assertTrue(espera(lambda: self.inj.estado()["leitores"] == 1), "the reader never showed")
        state = self.inj.estado()
        self.assertEqual((state["leitores"], state["leitores_trocados"]), (1, before + 1))

    def test_a_ring_that_failed_is_a_change_of_its_readers(self):
        self.wait_filled()
        before = self.inj.estado()["leitores_trocados"]
        self.inj._tentou = -1e9
        self.fail_next = True
        self.drain.set()
        self.assertTrue(espera(lambda: self.inj.estado()["leitores_trocados"] == before + 2),
                        "the ring that failed served no reader, and its reader came back")

    def test_the_longest_return_is_published_with_the_counts(self):
        self.pedal_on(1.0)
        hold, held = threading.Event(), threading.Event()
        starting = self.motor.voice_pedal.starting

        def held_starting(*a):
            held.set()
            hold.wait()
            return starting(*a)

        self.addCleanup(hold.set)
        self.motor.voice_pedal.starting = held_starting
        self.wait_filled()
        self.held.clear()
        self.gate.clear()
        self.assertTrue(self.held.wait(3), "the injector never got to the ring")
        since = time.perf_counter()
        self.assertTrue(espera(lambda: time.perf_counter() - since > 0.3))
        self.dry_done.clear()
        self.drain_next = True
        self.gate.set()
        self.assertTrue(held.wait(3), "the ring never ran dry")
        state = self.inj.estado()
        self.assertEqual((state["secas"], state["secas_pedal"]), (0, 0))
        self.assertLess(state["volta_max_ms"], 300, "the long pass came out before its dry-out was classified")
        hold.set()
        self.assertTrue(self.dry_done.wait(3.0), "the dry-out was never told")
        self.published()
        state = self.inj.estado()
        self.assertEqual((state["secas"], state["secas_pedal"]), (1, 1))
        self.assertGreater(state["volta_max_ms"], 300, "the long pass came out with its dry-out")

    def test_pedal_off_before_the_ring_was_last_filled(self):
        self.pedal_on(1.0)
        self.track_up()
        self.motor.voice_pedal.pedal(False)
        self.advance(0.1)
        self.dry_out()
        self.assertEqual((self.inj.secas, self.inj.dry_outs.while_pedal_starting), (1, 0))
        self.assertEqual(self.pedal_lines(), [])

    def test_dry_out_with_the_pedal_off(self):
        self.track_up()
        self.dry_out()
        self.assertEqual((self.inj.secas, self.inj.dry_outs.while_pedal_starting), (1, 0))
        self.assertEqual((self.pedal_lines(), self.plain_lines()), ([], 1))
        self.now += 1.0
        self.dry_out()
        self.assertEqual(self.plain_lines(), 1, "another dry-out within QUIET_S is not told")
        self.now += dryouts.QUIET_S + 0.1
        self.dry_out()
        self.assertEqual(self.plain_lines(), 2, "after QUIET_S it is told again")

    def test_track_of_an_earlier_pedal_does_not_count_as_up(self):
        self.track_up()
        self.now += 1.0
        self.pedal_on(0.0)
        self.dry_out()
        self.assertIn("its voice track isn't up yet", self.pedal_lines()[-1])

    def test_lines_of_one_start_stop_at_the_cap(self):
        self.pedal_on(0.0)
        for _ in range(dryouts.PEDAL_LINES + 5):
            self.dry_out()
        self.assertEqual((self.inj.dry_outs.while_pedal_starting, len(self.pedal_lines()), self.plain_lines()),
                         (dryouts.PEDAL_LINES + 5, dryouts.PEDAL_LINES, 1), "past the cap, the plain line")
        self.motor.voice_pedal.pedal(False)
        self.now += 1.0
        self.pedal_on(0.0)
        self.dry_out()
        self.assertEqual(len(self.pedal_lines()), dryouts.PEDAL_LINES + 1, "a new start tells again")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
