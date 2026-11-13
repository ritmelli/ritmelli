"""Testa a saida direto no microfone (engine.Injetor) sem o filtro de verdade e sem som: um anel falso, com o mesmo
layout do microfone/apo/anel.h, faz o papel do micfx.dll (um leitor que tira 10 ms a cada 10 ms, como o audiodg). O
motor escreve nele pelo microfone/injeta.py, num nome so do teste (MICFX_MAPA), entao nada chega no microfone do PC.

Confere: o que o leitor tirou e a sequencia que o misturador deu, amostra por amostra, sem buraco nem repeticao; a voz
cortada (mic_mute) chega no anel com o pulso do app, e o fechamento devolve a voz; sem leitor o motor anda pelo relogio
(a musica segue no fone); e o misturador do motor direto no microfone nao leva a voz nem aceita efeito de voz.

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


class AnelFalso:
    """O lado do filtro: cria a memoria (como o micfx.dll no AbreAnel) e, ligado, le 480 quadros a cada 10 ms numa vaga,
    guardando o que leu e quantas vezes faltou."""

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
        self.lido, self.faltou, self._vai = [], 0, False

    def liga(self):
        self._vai = True
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
            prox += 0.01
            time.sleep(max(0.0, prox - time.perf_counter()))


class MotorFalso:
    """O misturador do motor: cada bloco e a continuacao de uma rampa, para o leitor conferir a ordem."""

    def __init__(self):
        self.n, self.mic_mute, self.error = 0, False, None

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
            self.assertGreaterEqual(inj.estado()["leitores"], 1)
            motor.mic_mute = True
            time.sleep(0.1)
            self.assertEqual(anel.a.sem_voz, 1, "a voz cortada nao chegou no anel")
            self.assertLess(k32.GetTickCount64() - anel.a.batida_app, 500, "o pulso do app nao anda")
            faltou_antes = anel.faltou
            time.sleep(1.0)
            self.assertLessEqual(anel.faltou - faltou_antes, 1, "o leitor ficou sem som com o motor escrevendo")
        finally:
            inj.para()
            anel.desliga()
        self.assertEqual(anel.a.sem_voz, 0, "o fechamento nao devolveu a voz")
        lido = np.concatenate(anel.lido)
        esperado = (np.arange(len(lido)) + round(lido[0] * 100000)) % 100000 / 100000
        np.testing.assert_allclose(lido, esperado.astype(np.float32), atol=0,
                                   err_msg="o que o filtro leu nao e a sequencia do misturador")

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

    def test_misturador_direto_sem_voz(self):
        e = eng.Engine(mic="x", out=eng.MICROFONE, monitor="")
        voz = np.full(eng.BLOCK, 0.25, np.float32)
        e._mic.append(voz)
        self.assertTrue(np.any(e._mixa(eng.BLOCK)), "pelo cabo a voz vai no bloco")
        e._direto = True
        e._mic.append(voz)
        self.assertFalse(np.any(e._mixa(eng.BLOCK)), "direto no microfone a voz ja esta nele")
        with self.assertRaises(ValueError):
            e.set_effect("robo")
        e.set_effect("nenhum")


if __name__ == "__main__":
    unittest.main(verbosity=2)
