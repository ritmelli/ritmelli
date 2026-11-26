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


class TestVoicePedalStart(unittest.TestCase):
    def test_pedal_off_while_a_dry_out_is_told(self):
        pedal = dryouts.VoicePedalStart(clock=lambda: 5.0)
        pedal.pedal(True)
        calls = []

        def clock():
            if not calls:
                calls.append(1)
                pedal.pedal(False)
            return 6.0

        pedal.clock = clock
        self.assertIn("turned on 1.00 s ago", pedal.starting()[1])

    def test_a_full_log_drops_lines_and_does_not_wait(self):
        release, written = threading.Event(), io.StringIO()

        writing = threading.Event()

        class Slow:
            def write(self, text):
                writing.set()
                release.wait()
                return written.write(text)

            def flush(self):
                pass

        log = dryouts.Log(size=2)
        self.addCleanup(release.set)
        with mock.patch("sys.stderr", Slow()):
            first = threading.Thread(target=log.tell, args=("first",), daemon=True)
            first.start()
            first.join(3.0)
            self.assertFalse(first.is_alive(), "telling a line made its caller wait for the log")
            self.assertTrue(writing.wait(3.0), "the writer never took the first line")
            teller = threading.Thread(target=lambda: [log.tell(line) for line in ("second", "third", "fourth")],
                                      daemon=True)
            teller.start()
            teller.join(3.0)
            self.assertFalse(teller.is_alive(), "a full log made its caller wait")
            self.assertEqual(log.dropped, 1)
            release.set()
            log.written()
        self.assertEqual(written.getvalue().splitlines(),
                         ["first", "second (1 line(s) of the dry-out log dropped before this one)", "third"])

    def away(self, pedal_on_at, up_at):
        now = [0.0]
        pedal = dryouts.VoicePedalStart(clock=lambda: now[0])
        if pedal_on_at is not None:
            now[0] = pedal_on_at
            pedal.pedal(True)
        dry = dryouts.RingDryOuts(pedal, 0.03)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            now[0] = 0.1
            dry.read_ring(lambda: 1)
            now[0] = 0.756
            pedal.track(True, 7_000, now[0] - up_at)
            dry.ran_dry(0.656, 1)
            dryouts.LOG.written()
        return dry.while_pedal_starting, log.getvalue()

    def test_a_track_up_after_the_ring_ran_dry(self):
        counted, log = self.away(0.0, 0.4)
        self.assertEqual(counted, 1)
        self.assertIn("came up 0.36 s ago, after the ring ran dry", log)

    def test_a_track_up_as_the_ring_ran_dry_has_no_order(self):
        counted, log = self.away(0.0, 0.12)
        self.assertEqual(counted, 1)
        self.assertIn("which came first is not known", log)

    def test_a_pedal_on_after_the_ring_ran_dry_does_not_count(self):
        counted, log = self.away(0.45, 0.5)
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

    def test_without_stderr_nothing_is_written(self):
        log = dryouts.Log()
        with mock.patch("sys.stderr", None), mock.patch("sys.stdout", io.StringIO()) as out:
            log.tell("a line")
            log.written()
        self.assertEqual(out.getvalue(), "")

    def test_telling_starts_no_thread(self):
        log = dryouts.Log()
        with mock.patch("sys.stderr", io.StringIO()):
            with mock.patch.object(threading.Thread, "start", side_effect=AssertionError("tell() started a thread")):
                log.tell("a line")
            log.written()

    def test_a_failed_write_is_dropped_and_the_log_goes_on(self):
        written = io.StringIO()

        class Failing:
            left = 2

            def write(self, text):
                if Failing.left:
                    Failing.left -= 1
                    raise OSError("disk full")
                return written.write(text)

            def flush(self):
                pass

        log = dryouts.Log()
        with mock.patch("sys.stderr", Failing()):
            for line in ("first", "second", "third"):
                log.tell(line)
            done = threading.Thread(target=log.written, daemon=True)
            done.start()
            done.join(3.0)
        self.assertFalse(done.is_alive(), "the log stopped after a failed write")
        self.assertEqual((log.dropped, written.getvalue().splitlines()),
                         (2, ["third (2 line(s) of the dry-out log dropped before this one)"]))

    def test_the_track_is_up_only_once_its_line_is_queued(self):
        pedal = dryouts.VoicePedalStart(clock=lambda: 5.0)
        pedal.pedal(True)
        seen = []
        with mock.patch.object(dryouts.LOG, "tell", side_effect=lambda line: seen.append(pedal.track_up_at)):
            pedal.track(True, 7_000, 0.0)
        self.assertEqual((seen, pedal.track_up_at), ([None], 5.0))

    def test_one_stamp_is_one_start(self):
        pedal = dryouts.VoicePedalStart(clock=lambda: 5.0)
        pedal.pedal(True)
        with mock.patch("sys.stderr", io.StringIO()) as log:
            pedal.clock = lambda: 6.0
            pedal.track(False, 7_000, 0.2)
            pedal.clock = lambda: 6.5
            pedal.track(True, 7_000, 0.7)
            pedal.track(False, 7_000, 0.7)
            pedal.track(True, 7_000, 0.7)
            dryouts.LOG.written()
        self.assertEqual(log.getvalue().count("its voice track came up"), 1,
                         "the stamp seen before the track was live, and the track flapping, are the same start")


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
        self.log = io.StringIO()
        full = eng.INJ_FOLGA * eng.BLOCK

        self.wrote = self.drain_next = False

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
            self.wrote = True
            return len(x)

        pista_ligou = injeta.Microfone.pista_ligou

        def read_track(m):
            if not self.read_gate.is_set():
                self.read_held.set()
                self.read_gate.wait()
            return pista_ligou(m)

        patches = [mock.patch.object(injeta, "k32", self.k), mock.patch.object(injeta.Microfone, "na_fila", na_fila),
                   mock.patch.object(injeta.Microfone, "escreve", escreve),
                   mock.patch.object(injeta.Microfone, "pista_ligou", read_track),
                   mock.patch.object(eng.preset, "pede", return_value=None), mock.patch("sys.stderr", self.log)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.producer = injeta.Microfone()
        self.addCleanup(dryouts.LOG.written)
        self.inj = eng.Injetor(self.motor)
        self.addCleanup(self.inj.para)
        self.addCleanup(self.gate.set)
        self.addCleanup(self.read_gate.set)
        self.assertTrue(espera(lambda: self.inj.folga_min is not None), "the injector never served the reader")
        self.dry_done = threading.Event()
        ran_dry = self.inj.dry_outs.ran_dry

        def told(back_s, count):
            ran_dry(back_s, count)
            self.dry_done.set()

        self.inj.dry_outs.ran_dry = told

    def advance(self, seconds):
        self.now += seconds
        self.tick += round(seconds * 1000)
        self.a.leitor[0].batida = self.tick

    def wait_filled(self):
        self.assertTrue(espera(lambda: self.inj.dry_outs.filled_at == (self.now, self.now)),
                        "the ring thread never saw the ring full at the test's time")

    def dry_out(self):
        self.wait_filled()
        self.dry_done.clear()
        self.drain.set()
        self.assertTrue(self.dry_done.wait(3.0), "the ring never ran dry")

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

    def logged(self):
        dryouts.LOG.written()
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
        self.now -= seconds_ago
        self.motor.voice_pedal.pedal(True)
        self.now += seconds_ago

    def pedal_lines(self):
        return [ln for ln in self.logged().splitlines() if "while the voice pedal was starting" in ln]

    def offset(self, line, what):
        return float(re.search(what + r" (\d+\.\d+) s ago", line).group(1))

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
        self.assertIn("its voice track came up 1.00 s after the pedal turned on", self.logged())

    def test_a_track_up_within_what_the_ring_held_has_no_order(self):
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

    def test_a_slow_log_does_not_hold_the_ring(self):
        release = threading.Event()
        log = self.log

        class Slow:
            def write(self, text):
                release.wait()
                return log.write(text)

            def flush(self):
                pass

        self.addCleanup(release.set)
        self.pedal_on(1.0)
        with mock.patch("sys.stderr", Slow()):
            self.dry_out()
            self.dry_out()
            self.assertEqual(self.inj.dry_outs.while_pedal_starting, 2, "the ring went on while its log was stuck")
            release.set()
            dryouts.LOG.written()
        self.assertEqual(len(self.pedal_lines()), 2)

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
        self.assertIn("came up 0.00 s ago, after the ring was last filled, so which came first is not known",
                      self.pedal_lines()[-1])
        self.assertEqual(self.logged().count("after the pedal turned on"), 1, "one line for the track coming up")

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
