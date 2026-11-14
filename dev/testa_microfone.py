"""Testa a saida para o jogo (engine.Injetor) sem o filtro de verdade e sem som: um anel falso, com o mesmo layout do
microfone/apo/anel.h, faz o papel do micfx.dll (um leitor que tira 10 ms a cada 10 ms, como o audiodg, e devolve a
voz crua do microfone). O motor escreve nele pelo microfone/injeta.py, num nome so do teste (MICFX_MAPA), entao nada
chega no microfone do PC.

Confere: o alvo do anel e o do motor, e so o filtro do alvo conta como leitor; o que o leitor tirou e a sequencia que
o misturador deu, amostra por amostra, sem buraco nem repeticao; a voz pelo app (cortada ou com efeito) chega no anel
com o pulso, e o fechamento devolve a voz e solta o alvo; sem leitor do alvo o motor anda pelo relogio (a musica segue
no fone); a voz crua que o filtro devolve chega ao motor em blocos, inclusive de microfone a 44,1 kHz; e o misturador
so leva a voz quando o app a poe no lugar da crua (com efeito, sem a voz cortada).

    python dev/testa_microfone.py

Sai 1 se algo falhar.
"""
import ctypes
import os
import sys
import threading
import time
import unittest
from ctypes import wintypes
from pathlib import Path

import numpy as np

os.environ["MICFX_MAPA"] = f"Local\\VitrolaTesteMicFx-{os.getpid()}"  # nunca o anel do filtro de verdade
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as eng  # noqa: E402
from microfone import injeta  # noqa: E402

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
        injeta.MAPA = f"Local\\VitrolaTesteMicFx-{os.getpid()}-{AnelFalso.conta}"
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
            prox += 0.01
            time.sleep(max(0.0, prox - time.perf_counter()))


class MotorFalso:
    """O que o Injetor usa do motor: cada bloco do misturador e a continuacao de uma rampa, para o leitor conferir a
    ordem; a voz crua que volta fica guardada."""

    def __init__(self, alvo=ALVO):
        self.n, self.mic_mute, self.error, self._fx = 0, False, None, None
        self._alvo, self._voz_anel_em, self.voz = alvo, -1e9, []

    def voz_pelo_app(self):
        return eng.Engine.voz_pelo_app(self)

    def _push_mic(self, x):
        self.voz.append(x.copy())

    def _mixa(self, frames):
        x = (np.arange(self.n, self.n + frames) % 100000).astype(np.float32) / 100000
        self.n += frames
        return np.repeat(x[:, None], 2, axis=1)


class TestaMicrofone(unittest.TestCase):
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
        self.assertGreater(time.monotonic() - motor._voz_anel_em, 0)
        self.assertLess(time.monotonic() - motor._voz_anel_em, 1.0, "o motor nao soube da voz do filtro")
        x = np.concatenate(motor.voz)
        return x

    def test_voz_crua_volta_ao_motor(self):
        x = self._voz_volta(48000)
        d = np.diff(x)
        # a rampa de 0,001 por amostra (volta a 0 a cada 1000), a 48 kHz passa sem reamostrar
        self.assertTrue(np.all(np.isclose(d, 0.001, atol=1e-6) | (d < -0.9)), "a voz crua a 48 kHz chegou mudada")
        self.assertGreater(len(x), eng.SR * 0.5)

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

    def test_microfone_do_motor_cede_a_voz_do_filtro(self):
        e = eng.Engine(mic="x", monitor="")
        bloco = np.full((eng.BLOCK, 1), 0.5, np.float32)
        e._mic_cb(bloco, eng.BLOCK, None, None)
        self.assertEqual(len(e._mic), 1, "sem a voz do filtro, a do microfone aberto pelo motor vale")
        e._voz_anel_em = time.monotonic()
        e._mic_cb(bloco, eng.BLOCK, None, None)
        self.assertEqual(len(e._mic), 1, "com a voz do filtro viva, a do microfone (que ja leva a musica) fica fora")


if __name__ == "__main__":
    unittest.main(verbosity=2)
