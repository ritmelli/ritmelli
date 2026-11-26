"""Testa a saida para o jogo (engine.Injetor) sem o filtro de verdade e sem som: um anel falso, com o mesmo layout do
microfone/apo/anel.h, faz o papel do micfx.dll (um leitor que tira 10 ms a cada 10 ms, como o audiodg, e devolve a
voz crua do microfone). O motor escreve nele pelo microfone/injeta.py, num nome so do teste (MICFX_MAPA), entao nada
chega no microfone do PC.

Confere: o alvo do anel e o do motor, e so o filtro do alvo conta como leitor; o que o leitor tirou e a sequencia que
o misturador deu, amostra por amostra, sem buraco nem repeticao; a voz pelo app (cortada ou com efeito) chega no anel
com o pulso, e o fechamento devolve a voz e solta o alvo; sem leitor do alvo o motor anda pelo relogio (a musica segue
no fone); a voz crua que o filtro devolve chega ao motor em blocos, inclusive de microfone a 44,1 kHz; e o misturador
so leva a voz quando o app a poe no lugar da crua (com efeito, sem a voz cortada). A voz com efeito que sai do app (o
filtro recusou o efeito, ou o microfone sem o filtro e a voz so no fone) passa pelo voz.dll, o mesmo motor do filtro,
e nunca pelo fx.py; sem o voz.dll o motor sobe igual, a voz segue crua e o aviso sai uma vez. O fx.py recarregado
com o mesmo efeito ligado reenvia o preset ao filtro.

O vigia com o leitor perdido (o motor de verdade, com a partida trocada por uma que so sobe o Injetor no anel falso, e
a lista de aparelhos parada): o filtro que para de ler com o motor ainda no mesmo microfone faz o vigia reabrir, com
intervalo e ate o limite de tentativas, e o leitor que volta zera a conta; o leitor que volta sozinho antes do prazo,
o fim da captura (o motor fechado) e a troca manual de microfone (para um que nunca teve leitor) nao reabrem nada.

    microfone\\apo\\compila.bat teste
    python dev/testa_microfone.py

Sai 1 se algo falhar.
"""
import contextlib
import ctypes
import os
import sys
import threading
import time
import unittest
from ctypes import wintypes
from pathlib import Path
from unittest import mock

import numpy as np

os.environ["MICFX_MAPA"] = f"Local\\RitmelliTesteMicFx-{os.getpid()}"  # nunca o anel do filtro de verdade
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as eng
import fx
from microfone import injeta, preset, voz
from testa_voz import fala_sintetica

# a voz pelo fx.py (numpy e pedalboard) quebra o teste: no app ela so passa pelo voz.dll
SEM_FX_PY = mock.patch.object(fx.Efeito, "__call__", side_effect=AssertionError("a voz passou pelo fx.py"))

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileMappingW.restype = wintypes.HANDLE
k32.CreateFileMappingW.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.LPCWSTR)
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)

ALVO = injeta.hash_microfone("{11111111-2222-3333-4444-555555555555}")
OUTRO = injeta.hash_microfone("{00000000-0000-0000-0000-000000000001}")


class AnelFalso:
    """O lado do filtro: cria a memoria (como o micfx.dll no AbreAnel) e, ligado, le 480 quadros a cada 10 ms numa vaga
    (a do microfone ep), guardando o que leu e quantas vezes faltou; com voz_taxa, devolve a cada 10 ms 10 ms de voz
    crua nessa taxa, como o filtro do alvo."""

    conta = 0

    def __init__(self):
        AnelFalso.conta += 1  # um nome por anel: o do teste anterior pode seguir aberto
        injeta.MAPA = f"Local\\RitmelliTesteMicFx-{os.getpid()}-{AnelFalso.conta}"
        n = ctypes.sizeof(injeta.Anel)
        self.h = k32.CreateFileMappingW(wintypes.HANDLE(-1), None, 0x04, 0, n, injeta.MAPA)
        assert self.h, ctypes.get_last_error()
        self.p = k32.MapViewOfFile(self.h, 0x000F001F, 0, 0, n)
        self.a = injeta.Anel.from_address(self.p)
        a = self.a
        a.versao, a.taxa, a.canais, a.quadros, a.leitores = injeta.VERSAO, injeta.TAXA, 2, injeta.QUADROS, 8
        a.ganho, a.magia = 1.0, injeta.MAGIA
        self.dados = np.ctypeslib.as_array(a.dados).reshape(injeta.QUADROS, 2)
        self.voz = np.ctypeslib.as_array(a.voz)
        self.voz_fx = np.ctypeslib.as_array(a.voz_fx)
        self.lido, self.faltou, self.voz_n, self._vai = [], 0, 0, False

    def liga(self, ep=ALVO, voz_taxa=0):
        self._vai, self.voz_taxa = True, voz_taxa
        self.a.leitor[0].ep = ep
        self.a.leitor[0].dono = 7
        self.a.leitor[0].lido = self.a.escrito
        self._th = threading.Thread(target=self._le, daemon=True)
        self._th.start()

    def desliga(self):
        self._vai = False
        self._th.join()
        self.a.leitor[0].dono = 0

    def _le(self):
        eu, prox = self.a.leitor[0], time.perf_counter()
        while self._vai:
            eu.batida = k32.GetTickCount64()
            ini = eu.lido
            if self.a.escrito - ini >= 480:
                self.lido.append(self.dados[np.arange(ini, ini + 480) % injeta.QUADROS, 0])  # passa a volta do anel
                eu.lido = ini + 480
            else:
                self.faltou += 1
            if self.voz_taxa:
                k = self.voz_taxa // 100
                fim = self.a.voz_escrito
                n = np.arange(self.voz_n, self.voz_n + k)
                # a 48 kHz uma rampa (passa sem reamostrar, conferida amostra a amostra); fora, um seno de 100 Hz
                self.voz[np.arange(fim, fim + k) % injeta.VOZ_QUADROS] = \
                    (n % 1000) / 1000 if self.voz_taxa == 48000 else np.sin(2 * np.pi * 100 * n / self.voz_taxa)
                self.voz_n += k
                self.a.voz_taxa = self.voz_taxa
                self.a.voz_escrito = fim + k  # depois das amostras, como o filtro
                # a voz "com efeito" que o filtro devolve: a mesma, no anel dela
                w = self.a.fx_escrito
                self.voz_fx[np.arange(w, w + k) % injeta.VOZ_QUADROS] = self.voz[np.arange(fim, fim + k) % injeta.VOZ_QUADROS]
                self.a.fx_escrito = w + k
            prox += 0.01
            time.sleep(max(0.0, prox - time.perf_counter()))


class MotorFalso:
    """O que o Injetor usa do motor: cada bloco do misturador e a continuacao de uma rampa, para o leitor conferir a
    ordem; a voz crua que volta fica guardada."""

    def __init__(self, alvo=ALVO):
        self.n, self.mic_mute, self.error, self._fx, self.effect = 0, False, None, None, "nenhum"
        self._fx_id = None
        self._fx_filtro = self._fx_pendente = False
        self._pista_viva = False
        self._alvo, self._voz_anel_em, self.voz, self.voz_fx = alvo, -1e9, [], []

    def set_error(self, message):
        self.error = message

    def totais_saude(self):  # a janela do evento "audio" (metricas.SaudeAudio)
        return 0, 0.0

    def em_passagem(self):
        return False

    def voz_pelo_app(self):
        return eng.Engine.voz_pelo_app(self)

    def _push_mic(self, x):
        self.voz.append(x.copy())

    def _push_voz_fx(self, x):
        self.voz_fx.append(x.copy())

    def _mixa(self, frames):
        x = (np.arange(self.n, self.n + frames) % 100000).astype(np.float32) / 100000
        self.n += frames
        return np.repeat(x[:, None], 2, axis=1)


# o vigia em tempo de teste: a lista lida a cada 50 ms, o leitor dado como perdido em 0,3 s e as reaberturas a cada
# 0,3 s, ate 3 (create: o motor de antes da recuperacao nao tem esses nomes, e o caso persistente falha nele)
VIGIA_RAPIDO = {"VIGIA_S": 0.05, "LEITOR_PERDIDO_S": 0.3, "LEITOR_INTERVALO_S": 0.3, "LEITOR_TENTATIVAS": 3}
LISTA = {"inputs": ["Mic", "Mic2"], "outputs": [], "default_input": "Mic", "default_output": None}
ALVOS = {"Mic": ALVO, "Mic2": OUTRO}  # o Mic e o que o AnelFalso le; o Mic2, ninguem


class VigiaNoAnel:
    """The real Engine with its watcher running, the device list frozen (LISTA) and start replaced by one that only
    brings the Injetor up on the fake ring, aimed at the chosen microphone (ALVOS). It records the microphone of each
    opening, and wait_for_reopenings waits for the openings themselves instead of a fixed time."""

    def __init__(self):
        self.e = e = eng.Engine(mic="Mic", monitor="")
        self.aberturas = []
        self._opened = threading.Condition()
        e.start = self._start
        self._patches = contextlib.ExitStack()
        self._patches.enter_context(mock.patch.multiple(eng, create=True, **VIGIA_RAPIDO))
        self._patches.enter_context(mock.patch.object(eng, "list_devices_live", return_value=LISTA))
        self._patches.enter_context(mock.patch.object(eng, "_rescan"))
        with e._lock:
            e.start()
        e._vigia = threading.Thread(target=e._vigia_loop, daemon=True)
        e._vigia.start()

    def _start(self, reserva=False, fixos=()):
        e = self.e
        e._fechado = False
        mic = e.devices["mic"]
        e.active = {"mic": mic, "monitor": ""}
        e._alvo = ALVOS[mic]
        st = contextlib.ExitStack()
        segue = e._saude_segue  # como o start: a reabertura do leitor perdido continua a janela, no mesmo microfone
        inj = eng.Injetor(e, segue[1] if segue and segue[0] == mic else None)
        st.callback(inj.para)
        e._stack, e._injetor = st, inj
        with self._opened:
            self.aberturas.append(mic)
            self._opened.notify_all()

    def reaberturas(self):
        return len(self.aberturas) - 1

    def wait_for_reopenings(self, count, timeout_s=10.0):
        with self._opened:
            return self._opened.wait_for(lambda: self.reaberturas() >= count, timeout_s)

    def fecha(self):
        self.e.close()  # o vigia segue vivo, mas parado: o motor esta fechado
        self._patches.close()


class TestaMicrofone(unittest.TestCase):
    def _espera_leitor(self, v):
        prazo = time.monotonic() + 2.0
        while not v.e._injetor.leitores and time.monotonic() < prazo:
            time.sleep(0.01)
        self.assertTrue(v.e._injetor.leitores, "o Injetor nao viu o leitor do anel")

    def test_vigia_reabre_o_leitor_perdido(self):
        """The filter of the microphone in use stops reading and doesn't come back, with the engine still capturing the
        same microphone and the device list frozen: the watcher reopens the audio on the same microphone, at most
        LEITOR_TENTATIVAS times, keeping the audio event window; a reader that comes back resets the count, and the
        next loss reopens again. The delay and the interval are proven on the controlled clock of
        test_recupera_leitor_conta."""
        anel = AnelFalso()
        anel.liga()
        v = VigiaNoAnel()
        try:
            self._espera_leitor(v)
            janela = v.e._injetor.saude
            time.sleep(0.3)
            self.assertEqual(v.reaberturas(), 0, "com o leitor vivo o vigia nao reabre")
            anel.desliga()  # o filtro parou de ler; o motor segue capturando o mesmo microfone
            self.assertTrue(v.wait_for_reopenings(3), "o leitor perdido tem que reabrir ate o limite de tentativas")
            # a janela do evento "audio" segue nas reaberturas, com a perda que as pediu
            self.assertIs(v.e._injetor.saude, janela, "a reabertura do leitor perdido trocou a janela do audio")
            self.assertEqual(janela.leitor_perdido, 1, "a perda que pediu a reabertura sumiu da janela do audio")
            self.assertTrue(all(m == "Mic" for m in v.aberturas), "a reabertura trocou de microfone")
            time.sleep(0.6)
            self.assertEqual(v.reaberturas(), 3, "passou do limite de tentativas")
            anel.liga()  # o filtro voltou a ler: a conta zera
            self._espera_leitor(v)
            time.sleep(0.2)
            anel.desliga()
            self.assertTrue(v.wait_for_reopenings(4), "depois de o leitor voltar, a perda nova nao reabriu")
        finally:
            v.fecha()
            if anel._vai:
                anel.desliga()

    def test_recupera_leitor_conta(self):
        """A conta do _recupera_leitor num relogio controlado, sem threads: o leitor que volta e some de novo entre
        duas voltas do vigia recomeca a conta (e o prazo) da perda nova; a reabertura que falha (sem stream nenhum)
        segue na conta, no intervalo e ate o limite."""
        e = eng.Engine(mic="Mic", monitor="")
        e.active = {"mic": "Mic", "monitor": ""}
        agora = [100.0]
        reaberturas = []

        def injetor(perdeu_em=None):
            return mock.Mock(leitores=0, perdeu_em=perdeu_em)

        def reabre(falha=False):
            reaberturas.append(agora[0])
            e._stack = None if falha else contextlib.ExitStack()
            if falha:
                e._caiu_no_vigia = True
            else:
                e._injetor, e._caiu_no_vigia = injetor(), False

        def volta(dt):
            agora[0] += dt
            e._recupera_leitor()

        e._stack, e._injetor = contextlib.ExitStack(), mock.Mock(leitores=1, perdeu_em=50.0)
        with mock.patch.multiple(eng, create=True, LEITOR_PERDIDO_S=10.0, LEITOR_INTERVALO_S=30.0,
                                 LEITOR_TENTATIVAS=3), \
                mock.patch.object(eng.time, "monotonic", side_effect=lambda: agora[0]), \
                mock.patch.object(e, "_reabre", side_effect=reabre):
            volta(0.0)  # o leitor vivo com um perdeu_em lido antes de ele voltar: nao reabre
            self.assertEqual(reaberturas, [], "reabriu com o leitor vivo")
            e._injetor = injetor(perdeu_em=100.0)
            volta(9.0)
            self.assertEqual(reaberturas, [], "reabriu antes do prazo")
            volta(1.0)
            self.assertEqual(reaberturas, [110.0])
            # o Injetor novo viu o leitor voltar e sumir de novo entre duas voltas do vigia
            volta(2.0)
            e._injetor.perdeu_em = 113.0
            volta(2.0)
            self.assertIsNone(e._recupera, "o leitor que voltou nao zerou a conta")
            volta(7.0)
            self.assertEqual(reaberturas, [110.0], "reabriu antes do prazo da perda nova")
            volta(2.0)  # 123: 10 s da perda nova
            self.assertEqual(reaberturas, [110.0, 123.0])
            self.assertEqual(e._recupera[1], 1, "a perda nova nao comecou a conta do zero")
            # as duas proximas falham (sem stream nenhum): seguem no intervalo, ate o limite
            e._reabre.side_effect = lambda: reabre(falha=True)
            volta(29.0)
            self.assertEqual(reaberturas, [110.0, 123.0], "reopened before the interval")
            volta(1.0)
            self.assertEqual(reaberturas, [110.0, 123.0, 153.0])
            volta(29.0)
            self.assertEqual(reaberturas, [110.0, 123.0, 153.0], "reopened before the interval after a failed reopen")
            volta(1.0)
            for _ in range(3):
                volta(30.0)
            self.assertEqual(reaberturas, [110.0, 123.0, 153.0, 183.0], "a reabertura que falhou parou a conta")
            self.assertIsNone(e._stack)
            e.close()
            self.assertIsNone(e._recupera, "o motor fechado nao zerou a conta")

    def test_vigia_nao_reabre_o_leitor_que_volta_sozinho(self):
        """O leitor que some e volta antes de LEITOR_PERDIDO_S (o filtro que o Windows remonta sozinho) nao reabre: o
        Injetor viu a perda, e o leitor volta logo depois, bem antes do prazo (1 s neste teste)."""
        anel = AnelFalso()
        anel.liga()
        v = VigiaNoAnel()
        try:
            with mock.patch.object(eng, "LEITOR_PERDIDO_S", 1.0):
                self._espera_leitor(v)
                anel.desliga()
                prazo = time.monotonic() + 2.0
                while v.e._injetor.leitores and time.monotonic() < prazo:
                    time.sleep(0.005)
                self.assertEqual(v.e._injetor.leitores, 0, "o Injetor nao viu a perda")
                anel.liga()
                self._espera_leitor(v)
                time.sleep(1.5)
                self.assertEqual(v.reaberturas(), 0, "o leitor voltou sozinho e o vigia reabriu")
        finally:
            v.fecha()
            anel.desliga()

    def test_vigia_nao_reabre_no_fim_da_captura(self):
        """O motor fechado (a captura acabou, e o filtro para de ler por isso): o vigia nao reabre nada."""
        anel = AnelFalso()
        anel.liga()
        v = VigiaNoAnel()
        try:
            self._espera_leitor(v)
            v.e.close()
            anel.desliga()
            time.sleep(1.0)
            self.assertEqual(v.reaberturas(), 0, "o motor fechado de proposito foi reaberto")
        finally:
            v.fecha()

    def test_vigia_nao_reabre_na_troca_manual(self):
        """A troca manual para um microfone que nunca teve leitor (sem o filtro): o leitor do de antes some com a
        troca, e o vigia nao reabre nem volta para o de antes."""
        anel = AnelFalso()
        anel.liga()
        v = VigiaNoAnel()
        try:
            self._espera_leitor(v)
            v.e.set_devices(mic="Mic2")
            anel.desliga()
            time.sleep(1.0)
            self.assertEqual(v.aberturas, ["Mic", "Mic2"], "o vigia mexeu na troca manual")
            self.assertEqual(v.e.active["mic"], "Mic2")
        finally:
            v.fecha()

    def test_reopens_after_the_mic_task_when_the_mic_changed_meanwhile(self):
        for result in ({"ok": True}, {"ok": False, "motivo": "nao_pronto", "reopen": True}):
            v = VigiaNoAnel()
            try:
                other_error = {"key": "server.test.otherError"}

                def task(mic, result=result, v=v):
                    v.e.set_devices(mic="Mic2")
                    v.e.set_error(other_error)
                    return result
                without_filter = {"filtro": False, "melhorias": True, "guid": "{a}"}
                with mock.patch.object(eng, "_do_microfone", lambda mic: without_filter), \
                        mock.patch("microfone.microfone.pede_tarefa", task), \
                        mock.patch.object(v.e, "_confere_mudos") as check_silent:
                    v.e._confere_filtro("Mic")
                self.assertEqual(v.aberturas, ["Mic", "Mic2", "Mic2"],
                                 f"the task restarted the Windows audio, so the streams of Mic2 died too ({result})")
                self.assertIs(v.e.error, other_error, f"the old microphone's task keeps another error ({result})")
                check_silent.assert_called_once_with()
            finally:
                v.fecha()

    def test_injetor_no_ritmo_do_leitor(self):
        anel = AnelFalso()
        anel.liga()
        motor = MotorFalso()
        inj = eng.Injetor(motor)
        try:
            time.sleep(1.5)
            self.assertEqual(anel.a.alvo, ALVO, "o alvo do anel nao e o microfone do motor")
            self.assertGreaterEqual(inj.estado()["leitores"], 1)
            self.assertEqual(anel.a.sem_voz, 0, "sem efeito e sem corte a voz e a crua")
            motor.mic_mute = True
            time.sleep(0.1)
            self.assertEqual(anel.a.sem_voz, 1, "a voz cortada nao chegou no anel")
            motor.mic_mute, motor._fx = False, object()
            time.sleep(0.1)
            self.assertEqual(anel.a.sem_voz, 1, "a voz com efeito nao foi pelo app")
            self.assertLess(k32.GetTickCount64() - anel.a.batida_app, 500, "o pulso do app nao anda")
            faltou_antes = anel.faltou
            time.sleep(1.0)
            self.assertLessEqual(anel.faltou - faltou_antes, 1, "o leitor ficou sem som com o motor escrevendo")
        finally:
            inj.para()
            anel.desliga()
        self.assertEqual(anel.a.sem_voz, 0, "o fechamento nao devolveu a voz")
        self.assertEqual(anel.a.alvo, 0, "o fechamento nao soltou o alvo")
        lido = np.concatenate(anel.lido)
        esperado = (np.arange(len(lido)) + round(lido[0] * 100000)) % 100000 / 100000
        np.testing.assert_allclose(lido, esperado.astype(np.float32), atol=0,
                                   err_msg="o que o filtro leu nao e a sequencia do misturador")

    def test_leitor_que_some_no_meio_do_preenchimento(self):
        """O leitor some entre o vivos() e o enchimento do anel (o na_fila ja nao o ve e da 0): o Injetor escreve no
        maximo INJ_FOLGA blocos nessa volta e, na seguinte, ve que ficou sem leitor (o vigia depende disso)."""
        anel = AnelFalso()
        anel.liga()
        motor = MotorFalso()
        inj = eng.Injetor(motor)
        try:
            prazo = time.monotonic() + 2.0
            while not inj.leitores and time.monotonic() < prazo:
                time.sleep(0.01)
            self.assertTrue(inj.leitores)
            with mock.patch.object(injeta.Microfone, "na_fila", return_value=0):
                time.sleep(0.05)
                anel.desliga()
                time.sleep(0.3)
                self.assertEqual(inj.leitores, 0, "o Injetor ficou preso enchendo o anel sem leitor")
                self.assertIsNotNone(inj.perdeu_em, "o Injetor nao marcou a perda do leitor")
        finally:
            inj.para()
            if anel._vai:
                anel.desliga()

    def test_leitor_de_outro_microfone_nao_conta(self):
        anel = AnelFalso()
        anel.liga(ep=OUTRO)  # o filtro de outro microfone, vivo: nao e por ele que a musica sai
        motor = MotorFalso()
        inj = eng.Injetor(motor)
        try:
            time.sleep(0.8)
            self.assertEqual(inj.estado()["leitores"], 0)
        finally:
            inj.para()
            anel.desliga()
        self.assertEqual(anel.a.escrito, 0, "a musica foi para o anel sem leitor do alvo")
        self.assertGreater(motor.n, eng.SR * 0.5, "sem leitor do alvo a musica tem que andar pelo relogio")

    def test_sem_leitor_anda_pelo_relogio(self):
        anel = AnelFalso()  # o anel existe, mas ninguem le (o jogo fechado)
        motor = MotorFalso()
        inj = eng.Injetor(motor)
        try:
            time.sleep(0.3)
            n0, t0 = motor.n, time.perf_counter()
            time.sleep(1.0)
            ritmo = (motor.n - n0) / (time.perf_counter() - t0)
        finally:
            inj.para()
        self.assertEqual(anel.a.escrito, 0, "sem leitor nada vai pro anel")
        self.assertAlmostEqual(ritmo, eng.SR, delta=eng.SR * 0.1)

    def _voz_volta(self, taxa):
        anel = AnelFalso()
        anel.liga(voz_taxa=taxa)
        motor = MotorFalso()
        inj = eng.Injetor(motor)
        try:
            time.sleep(1.2)
        finally:
            inj.para()
            anel.desliga()
        self.assertTrue(motor.voz, f"a voz crua a {taxa} Hz nao chegou ao motor")
        self.assertTrue(all(len(b) == eng.BLOCK for b in motor.voz), "a voz chega em blocos do motor")
        # >= 0: no Windows o monotonic anda em tiques de ~15,6 ms, e a ultima voz pode ser do mesmo tique
        self.assertGreaterEqual(time.monotonic() - motor._voz_anel_em, 0)
        self.assertLess(time.monotonic() - motor._voz_anel_em, 1.0, "o motor nao soube da voz do filtro")
        x = np.concatenate(motor.voz)
        return x

    def test_voz_crua_volta_ao_motor(self):
        x = self._voz_volta(48000)
        d = np.diff(x)
        # a rampa de 0,001 por amostra (volta a 0 a cada 1000), a 48 kHz passa sem reamostrar
        self.assertTrue(np.all(np.isclose(d, 0.001, atol=1e-6) | (d < -0.9)), "a voz crua a 48 kHz chegou mudada")
        self.assertGreater(len(x), eng.SR * 0.5)

    def test_voz_da_pista_vai_pro_fone(self):
        """Com a pista da voz no comando, o Injetor entrega ao motor a voz que o processo escreveu nela (o fone e o
        medidor levam o que o jogo ouve) e marca o motor; pista desligada, o motor volta para a crua."""
        anel = AnelFalso()
        anel.liga(voz_taxa=48000)
        motor = MotorFalso()
        inj = eng.Injetor(motor)
        escritor = None
        try:
            time.sleep(0.4)
            self.assertFalse(motor._pista_viva)
            escritor = injeta.Microfone()  # o processo da voz, no mesmo anel
            escritor.pista_liga()
            v = (np.arange(1920 * 5) % 777 / 777).astype(np.float32)
            for k in range(5):
                escritor.pista_escreve(v[k * 1920:(k + 1) * 1920])
                time.sleep(0.04)
            time.sleep(0.1)
            self.assertTrue(motor._pista_viva, "o Injetor nao viu a pista no comando")
            chegou = np.concatenate(motor.voz_fx)
            np.testing.assert_allclose(chegou[-len(v):] if len(chegou) >= len(v) else chegou, v[-len(chegou):], atol=0,
                                       err_msg="a voz da pista nao chegou ao motor como foi escrita")
            self.assertGreaterEqual(len(chegou), 1920 * 4)
            escritor.pista_liga(False)
            time.sleep(0.1)
            self.assertFalse(motor._pista_viva, "pista desligada e o motor seguiu nela")
        finally:
            if escritor:
                escritor.fecha()
            inj.para()
            anel.desliga()

    def test_voz_crua_a_44k_vira_48k(self):
        x = self._voz_volta(44100)
        # o seno de 100 Hz a 44,1 kHz, reamostrado: 100 Hz tambem a 48 kHz (2 cruzamentos do zero por ciclo) e sem degrau
        cruza = np.count_nonzero(np.signbit(x[1:]) != np.signbit(x[:-1]))
        self.assertAlmostEqual(cruza, 2 * 100 * len(x) / eng.SR, delta=3, msg="a voz a 44,1 kHz nao virou 48 kHz")
        self.assertLess(np.max(np.abs(np.diff(x))), 2 * np.pi * 100 / eng.SR * 1.05, "degrau na voz reamostrada")

    def test_misturador_so_leva_a_voz_pelo_app(self):
        e = eng.Engine(mic="x", monitor="")
        voz = np.full(eng.BLOCK, 0.25, np.float32)
        self.assertFalse(e.voz_pelo_app())
        e._mic.append(voz)
        self.assertFalse(np.any(e._mixa(eng.BLOCK)), "a voz crua ja esta no microfone: o app nao manda de novo")
        e.set_effect("robo")
        self.assertTrue(e.voz_pelo_app())
        e._mic.append(voz)
        self.assertTrue(np.any(e._mixa(eng.BLOCK)), "a voz com efeito sai pelo app")
        e.mic_mute = True
        e._mic.append(voz)
        self.assertFalse(np.any(e._mixa(eng.BLOCK)), "a voz cortada nao vai")
        e.mic_mute = False
        e.set_effect("nenhum")
        self.assertFalse(e.voz_pelo_app())

    def test_efeito_no_filtro_ou_pelo_app(self):
        """O efeito que o filtro roda vai como preset e a voz nao passa pelo app; enquanto o filtro nao responde, a voz
        crua segue; sem resposta em PRESET_ESPERA_S, ou com o filtro recusando, a voz vai pelo app."""
        anel = AnelFalso()
        anel.liga(voz_taxa=48000)
        motor = MotorFalso()
        inj = eng.Injetor(motor)
        a = anel.a
        try:
            time.sleep(0.2)
            motor.effect, motor._fx, motor._fx_id = "eco", object(), "eco"
            time.sleep(0.05)
            self.assertGreater(a.preset_n, 0, "o preset do eco nao foi pro anel")
            self.assertEqual(a.preset_seq % 2, 0, "o seqlock ficou aberto")
            self.assertEqual(a.sem_voz, 0, "esperando o filtro, a voz crua segue")
            time.sleep(eng.PRESET_ESPERA_S + 0.1)
            self.assertEqual(a.sem_voz, 1, "o filtro nao respondeu: a voz tinha que ir pelo app")
            self.assertFalse(inj.estado()["efeito_no_filtro"])
            a.preset_erro, a.preset_feito = 0, a.preset_seq  # o filtro montou
            time.sleep(0.05)
            self.assertTrue(inj.estado()["efeito_no_filtro"])
            self.assertEqual(a.sem_voz, 0, "com o efeito no filtro a voz nao passa pelo app")
            self.assertTrue(motor.voz_fx, "a voz com efeito que o filtro devolve nao chegou ao motor")
            motor.effect = motor._fx_id = "robo"  # outro efeito: preset novo, e o filtro recusa
            time.sleep(0.05)
            a.preset_erro, a.preset_feito = 1, a.preset_seq
            time.sleep(0.05)
            self.assertEqual(a.sem_voz, 1, "o filtro recusou: a voz vai pelo app")
            motor.effect, motor._fx, motor._fx_id = "nenhum", None, None
            time.sleep(0.05)
            self.assertEqual(a.preset_n, 0, "sem efeito o preset sai do anel")
            self.assertEqual(a.sem_voz, 0)
        finally:
            inj.para()
            anel.desliga()

    def test_projeto_do_preset_fora_da_thread(self):
        """O projeto do preset (ate ~70 ms no scipy) nunca roda na thread da saida para o jogo: com um projeto de 300 ms,
        a volta do Injetor segue curta, a voz crua segue enquanto ele projeta, e o preset chega quando fica pronto."""
        from microfone import preset
        anel = AnelFalso()
        anel.liga(voz_taxa=48000)
        motor = MotorFalso()
        original = preset._projeta
        preset._prontos.pop(("radio-policia", 48000), None)

        def lento(*a):
            time.sleep(0.3)
            return original(*a)

        preset._projeta = lento
        inj = eng.Injetor(motor)
        try:
            time.sleep(0.3)
            inj.volta_max = 0.0
            motor.effect, motor._fx, motor._fx_id = "radio-policia", object(), "radio-policia"
            time.sleep(0.1)
            self.assertEqual(anel.a.preset_n, 0, "o preset nao podia estar pronto ainda")
            self.assertEqual(anel.a.sem_voz, 0, "projetando, a voz crua segue")
            time.sleep(0.4)
            self.assertGreater(anel.a.preset_n, 0, "o preset projetado a parte nao chegou no anel")
            self.assertLess(inj.estado()["volta_max_ms"], 100, "a thread da saida esperou o projeto do preset")
        finally:
            preset._projeta = original
            inj.para()
            anel.desliga()

    def test_reload_reenvia_o_preset_ao_filtro(self):
        """O fx.py recarregado (/api/effects/reload: preset.esquece) com o mesmo efeito ligado: o anel recebe o preset
        novo sem ninguem trocar de efeito; sem reload, o preset nao se reescreve sozinho."""
        anel = AnelFalso()
        anel.liga(voz_taxa=48000)
        motor = MotorFalso()
        inj = eng.Injetor(motor)
        a = anel.a
        compensa = dict(fx.COMPENSA_DB)
        try:
            time.sleep(0.2)
            motor.effect, motor._fx, motor._fx_id = "eco", object(), "eco"
            time.sleep(0.1)
            velho, seq = bytes(a.preset[:a.preset_n]), a.preset_seq
            self.assertEqual(velho, preset.compila(fx.criar("eco"), 48000), "o preset do eco nao foi pro anel")
            time.sleep(0.1)
            self.assertEqual(a.preset_seq, seq, "sem reload o preset nao se reescreve")
            fx.COMPENSA_DB["eco"] += 3.0  # o fx.py mudou (o ganho do eco), e o reload joga fora o projetado
            preset.esquece()
            time.sleep(0.2)
            self.assertNotEqual(a.preset_seq, seq, "o reload nao reenviou o preset ao filtro")
            novo = bytes(a.preset[:a.preset_n])
            self.assertNotEqual(novo, velho, "o filtro recebeu de novo o preset velho")
            self.assertEqual(novo, preset.compila(fx.criar("eco"), 48000), "o preset reenviado nao e o do fx.py novo")
        finally:
            fx.COMPENSA_DB.clear()
            fx.COMPENSA_DB.update(compensa)
            preset.esquece()
            inj.para()
            anel.desliga()

    def test_projeto_de_antes_do_reload_nao_fica(self):
        """Um projeto que comecou antes do reload e terminou depois vale para quem pediu, mas nao fica guardado: o
        proximo pedido projeta com o fx.py novo."""
        chave = ("robo", 48000)
        original = preset._projeta
        comecou, solta = threading.Event(), threading.Event()

        def lento(*a):
            comecou.set()
            solta.wait(2.0)
            return b"velho"

        preset._prontos.pop(chave, None)
        preset._projeta = lento
        try:
            th = threading.Thread(target=preset.preset, args=chave)
            th.start()
            self.assertTrue(comecou.wait(2.0))
            preset.esquece()
            solta.set()
            th.join(2.0)
            self.assertNotIn(chave, preset._prontos, "o projeto de antes do reload ficou guardado")
        finally:
            preset._projeta = original
        self.assertEqual(preset.preset(*chave), preset.compila(fx.criar("robo"), 48000))

    def test_microfone_do_motor_cede_a_voz_do_filtro(self):
        e = eng.Engine(mic="x", monitor="")
        bloco = np.full((eng.BLOCK, 1), 0.5, np.float32)
        e._mic_cb(bloco, eng.BLOCK, None, None)
        self.assertEqual(len(e._mic), 1, "sem a voz do filtro, a do microfone aberto pelo motor vale")
        e._voz_anel_em = time.monotonic()
        e._mic_cb(bloco, eng.BLOCK, None, None)
        self.assertEqual(len(e._mic), 1, "com a voz do filtro viva, a do microfone (que ja leva a musica) fica fora")

    def test_reserva_pelo_voz_dll(self):
        """O filtro recusou o efeito (ou ele nao cabe na taxa do microfone): a voz crua que volta passa no app pelo
        voz.dll, com o preset de 48 kHz, e o misturador manda ela no lugar da crua, bloco a bloco igual a cadeia."""
        x = fala_sintetica(2.0)
        with SEM_FX_PY:
            e = eng.Engine(mic="x", monitor="")
            e.set_effect("eco")
            self.assertIsInstance(e._fx, voz.Cadeia, "o efeito no app nao e o motor do filtro")
            ref = voz.Cadeia(preset.compila(fx.criar("eco"), eng.SR), eng.SR)
            saida, esperado = [], []
            for k in range(0, len(x) - eng.BLOCK + 1, eng.BLOCK):
                b = x[k:k + eng.BLOCK]
                e._push_mic(b)  # a voz crua do filtro (o Injetor._voz), com o filtro sem o efeito
                self.assertTrue(e.voz_pelo_app())
                saida.append(e._mixa(eng.BLOCK)[:, 0])
                esperado.append(ref(b))
        y = np.concatenate(saida)
        np.testing.assert_array_equal(y, np.concatenate(esperado), err_msg="a voz no jogo nao e a do voz.dll")
        self.assertGreater(float(np.max(np.abs(y - x[:len(y)]))), 0.01, "o eco nao mudou a voz")

    def test_ouvir_a_propria_voz_sem_filtro_pelo_voz_dll(self):
        """Microfone sem o filtro: a voz que o motor abre passa pelo voz.dll e chega ao fone com o efeito."""
        x = fala_sintetica(2.0)
        with SEM_FX_PY:
            e = eng.Engine(mic="x", monitor="fone")
            e.active["monitor"] = "fone"
            e.voice_monitor, e.voice_mon_vol = True, 1.0
            e.set_effect("robo")
            ref = voz.Cadeia(preset.compila(fx.criar("robo"), eng.SR), eng.SR)
            fone, esperado = [], []
            for k in range(0, len(x) - eng.BLOCK + 1, eng.BLOCK):
                b = x[k:k + eng.BLOCK]
                e._mic_cb(b[:, None], eng.BLOCK, None, None)  # sem a voz do filtro, vale a do microfone aberto
                e._mixa(eng.BLOCK)
                fone.append(e._mon.popleft()[:, 0])
                esperado.append(np.clip(ref(b), -1, 1))
        np.testing.assert_array_equal(np.concatenate(fone), np.concatenate(esperado),
                                      err_msg="o fone nao ouve a voz do voz.dll")

    def test_sem_voz_dll_sobe_e_a_voz_segue_crua(self):
        """Sem o voz.dll o motor sobe e troca de efeito igual: o filtro ainda recebe o preset, a voz que sairia do app
        segue crua no microfone e o aviso sai uma vez por efeito escolhido."""
        with mock.patch.object(voz, "_dll", None), mock.patch.object(voz, "caminho", return_value="nao-existe/voz.dll"):
            self.assertFalse(voz.disponivel())
            e = eng.Engine(mic="x", monitor="")
            e.set_effect("robo")
            self.assertIsNone(e._fx)
            self.assertEqual(e._fx_id, "robo", "sem o voz.dll o filtro ainda roda o efeito")
            self.assertFalse(e.voz_pelo_app(), "sem a cadeia do app, a voz crua segue no microfone")
            b = np.full(eng.BLOCK, 0.25, np.float32)
            e._push_mic(b)
            np.testing.assert_array_equal(e._mic[-1], b)
            # o aviso e uma mensagem traduzida (i18n.msg, desde o #106): a chave dela, com o texto em ingles junto
            self.assertEqual((e.error or {}).get("key"), "server.effect.noVozDll")
            self.assertIn("voz.dll", e.error["text"])
            e.set_error(None)
            e._push_mic(b)
            self.assertIsNone(e.error, "o aviso sai uma vez por efeito")
            e.set_effect("eco")
            e._push_mic(b)
            self.assertEqual((e.error or {}).get("key"), "server.effect.noVozDll", "outro efeito avisa de novo")
            e.set_error(None)
            e._fx_filtro = True
            e._push_mic(b)
            self.assertIsNone(e.error)
            e._fx_filtro = False
            e.set_effect("nenhum")
            self.assertIsNone(e._fx_id)
            e._push_mic(b)
            self.assertIsNone(e.error, "sem efeito nao ha o que avisar")


if __name__ == "__main__":
    unittest.main(verbosity=2)
