"""Testa a troca de voz do pedal (#129) sem o filtro de verdade e sem som: um anel falso, com o layout do
microfone/apo/anel.h e um nome so do teste (MICFX_MAPA), faz o papel do filtro: a cada 10 ms entrega 10 ms de voz crua
e, com a pista ligada, le 480 quadros dela a partir de onde o escritor marcou.

Confere o pista.py com um conversor de mentira (o bloco sai como entrou): a pista so liga com a primeira voz
convertida, o colchao de silencio sai inteiro na frente dela, a voz chega em ordem e sem buraco, o microfone a 44,1 kHz
vira 48 kHz, o erro do conversor desliga a pista, e sair desliga a pista na hora. Confere o pistavoz.py: a voz escolhida
e o tom ficam no pedal_voz.json da pasta que o servidor passa (no --mock, a temporaria), voz desconhecida e recusada, e
sem as vozes baixadas o pedal nao sobe processo nenhum.

Com RITMELLI_VOZES_TESTE=1 (os modelos do python dev/vozes.py baixa) ou apontando para outra pasta com as releases do
ritmelli-voices, tambem roda o processo inteiro (ritmelli.py --pistavoz) com os modelos de verdade, na placa de video.

    python dev/testa_pista.py

Sai 1 se algo falhar."""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from ctypes import wintypes
from pathlib import Path

import numpy as np

os.environ["MICFX_MAPA"] = f"Local\\RitmelliTestePista-{os.getpid()}"  # nunca o anel do filtro de verdade
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import pista  # noqa: E402
import pistavoz  # noqa: E402
from microfone import injeta  # noqa: E402

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileMappingW.restype = wintypes.HANDLE
k32.CreateFileMappingW.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.LPCWSTR)
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)
ALVO = injeta.hash_microfone("{11111111-2222-3333-4444-555555555555}")
N = 3840  # o bloco do conversor (conversor.N), sem carregar o onnxruntime aqui


class FiltroFalso:
    """Cria o anel (como o micfx.dll) e, ligado, a cada 10 ms poe 10 ms de voz crua (uma rampa que conta as amostras, ou
    um seno a 44,1 kHz) e, com a pista ligada, le dela 480 quadros, do pista_inicio em diante, como o filtro do alvo."""

    conta = 0

    def __init__(self, taxa=48000):
        FiltroFalso.conta += 1
        injeta.MAPA = os.environ["MICFX_MAPA"] = f"Local\\RitmelliTestePista-{os.getpid()}-{FiltroFalso.conta}"
        n = ctypes.sizeof(injeta.Anel)
        self.h = k32.CreateFileMappingW(wintypes.HANDLE(-1), None, 0x04, 0, n, injeta.MAPA)
        assert self.h, ctypes.get_last_error()
        self.p = k32.MapViewOfFile(self.h, 0x000F001F, 0, 0, n)
        a = self.a = injeta.Anel.from_address(self.p)
        a.versao, a.taxa, a.canais, a.quadros, a.leitores = injeta.VERSAO, injeta.TAXA, 2, injeta.QUADROS, 8
        a.ganho, a.magia, a.alvo = 1.0, injeta.MAGIA, ALVO
        for i in range(injeta.LEITORES):
            a.pista_lido[i] = -1
        self.voz = np.ctypeslib.as_array(a.voz)
        self.pista = np.ctypeslib.as_array(a.pista).reshape(injeta.PISTA_QUADROS, 2)
        self.taxa, self.enviado, self.lido, self.secas, self.vai = taxa, 0, [], 0, True
        self.th = threading.Thread(target=self._roda, daemon=True)
        self.th.start()

    def _roda(self):
        a, eu, prox = self.a, self.a.leitor[0], time.perf_counter()
        eu.ep, eu.dono = ALVO, 7
        while self.vai:
            eu.batida = k32.GetTickCount64()
            k = self.taxa // 100
            n = np.arange(self.enviado, self.enviado + k)
            x = (n % 100000) / 100000 if self.taxa == 48000 else 0.5 * np.sin(2 * np.pi * 200 * n / self.taxa)
            fim = a.voz_escrito
            self.voz[np.arange(fim, fim + k) % injeta.VOZ_QUADROS] = x
            a.voz_taxa = self.taxa
            a.voz_escrito = fim + k
            self.enviado += k
            if a.pista_ligada and k32.GetTickCount64() - a.pista_batida < injeta.PISTA_MS:
                if a.pista_lido[0] < 0:
                    a.pista_lido[0] = a.pista_inicio
                ini = a.pista_lido[0]
                if a.pista_escrito - ini >= 480:
                    self.lido.append(self.pista[np.arange(ini, ini + 480) % injeta.PISTA_QUADROS, 0].copy())
                    a.pista_lido[0] = ini + 480
                else:
                    self.secas += 1
            else:
                a.pista_lido[0] = -1
            prox += 0.01
            time.sleep(max(0.0, prox - time.perf_counter()))

    def fecha(self):
        self.vai = False
        self.th.join()
        k32.UnmapViewOfFile(ctypes.c_void_p(self.p))
        k32.CloseHandle(self.h)


class ConversorFalso:
    """O bloco sai como entrou, depois de uma conta de 20 ms; com falha, o terceiro bloco levanta."""

    def __init__(self, falha=False):
        self.falha, self.n = falha, 0

    def bloco(self, x):
        self.n += 1
        if self.falha and self.n == 3:
            raise RuntimeError("placa sumiu")
        time.sleep(0.02)
        return x.copy()


def roda_pista(filtro, conv, segundos):
    m = injeta.Microfone()
    p = pista.Pista(m, conv)
    t = threading.Thread(target=p.laco, daemon=True)
    t.start()
    t0 = time.perf_counter()
    while p.vai and time.perf_counter() - t0 < segundos:
        time.sleep(0.05)
    ligada_antes = bool(filtro.a.pista_ligada)
    p.vai = False
    t.join(timeout=2)
    m.fecha()
    return p, ligada_antes


class TestaPista(unittest.TestCase):
    def test_colchao_e_voz_em_ordem(self):
        """A pista liga com a primeira voz convertida; o filtro le o colchao de silencio e depois a voz crua do
        conversor de mentira, em ordem e sem buraco; sair desliga a pista."""
        f = FiltroFalso()
        try:
            p, ligada = roda_pista(f, ConversorFalso(), 2.0)
            self.assertTrue(ligada, "a pista ligou")
            self.assertFalse(f.a.pista_ligada, "sair desliga a pista na hora")
            self.assertIsNone(p.erro)
            lido = np.concatenate(f.lido)
            self.assertGreater(len(lido), pista.COLCHAO + N, "o filtro leu o colchao e a voz")
            np.testing.assert_array_equal(lido[:pista.COLCHAO], 0, "o colchao sai inteiro na frente da voz")
            voz = lido[pista.COLCHAO:]
            self.assertTrue(np.all(np.diff(voz) > 0) or np.all(np.diff(voz[voz > 0]) > 0),
                            "a voz (uma rampa) chega em ordem")
            passo = np.round(np.diff(voz) * 100000).astype(int)
            self.assertTrue(np.all((passo == 1) | (passo == -99999)), "sem buraco nem repeticao")
            self.assertEqual(f.secas, 0, "a pista nao secou com a conta de 20 ms")
        finally:
            f.fecha()

    def test_microfone_a_44k(self):
        """Microfone a 44,1 kHz: a voz vira 48 kHz antes do conversor (um segundo de voz, um segundo de pista)."""
        f = FiltroFalso(taxa=44100)
        try:
            conv = ConversorFalso()
            p, _ = roda_pista(f, conv, 2.0)
            self.assertIsNone(p.erro)
            self.assertEqual(p.est["voz_taxa"], 44100)
            enviados_48k = f.enviado * 48000 / 44100
            self.assertAlmostEqual(conv.n * N / enviados_48k, 1.0, delta=0.12)
        finally:
            f.fecha()

    def test_erro_do_conversor_desliga(self):
        f = FiltroFalso()
        try:
            p, _ = roda_pista(f, ConversorFalso(falha=True), 3.0)
            self.assertIn("placa sumiu", p.erro or "")
            self.assertFalse(p.vai)
            self.assertFalse(f.a.pista_ligada, "a voz do microfone volta")
        finally:
            f.fecha()


class TestaModulo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.modelos = pistavoz.MODELOS
        pistavoz.MODELOS = Path(self.tmp.name) / "modelos"  # nenhum modelo baixado
        pistavoz.dados(self.tmp.name)

    def tearDown(self):
        pistavoz.liga(False)
        pistavoz.MODELOS = self.modelos
        self.tmp.cleanup()

    def test_escolhe_grava_na_pasta_do_servidor(self):
        self.assertEqual(pistavoz.estado()["voz"], "mina")
        pistavoz.escolhe("lira")
        self.assertEqual(pistavoz.estado(), {"voz": "lira", "visor": None, "progresso": None})
        with open(Path(self.tmp.name) / "pedal_voz.json", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["voz"], "lira")
        pistavoz.dados(self.tmp.name)  # o servidor subindo de novo: a voz escolhida volta
        self.assertEqual(pistavoz.estado()["voz"], "lira")
        with self.assertRaises(ValueError):
            pistavoz.escolhe("alien")

    def test_sem_vozes_nao_sobe(self):
        pistavoz.liga(True)
        self.assertIsNone(pistavoz._proc, "sem as vozes baixadas, nenhum processo")


@unittest.skipUnless(os.environ.get("RITMELLI_VOZES_TESTE"), "sem RITMELLI_VOZES_TESTE (os modelos do ritmelli-voices)")
class TestaProcesso(unittest.TestCase):
    def test_processo_inteiro(self):
        """ritmelli.py --pistavoz com os modelos de verdade, contra o anel falso: diz "pronto", liga a pista, a voz
        convertida chega ao filtro sem secar depois da partida, e "sair" desliga a pista e sai com 0."""
        v = Path(os.environ["RITMELLI_VOZES_TESTE"])
        v = v if v.is_dir() else pistavoz.MODELOS  # RITMELLI_VOZES_TESTE=1: os do python dev/vozes.py baixa
        f = FiltroFalso(taxa=48000)
        try:
            arg = json.dumps({"engine": str(v / pistavoz.ENGINE), "voz": str(v / pistavoz.RELEASES["mina"]), "tom": 9})
            env = dict(os.environ, MICFX_MAPA=injeta.MAPA)
            p = subprocess.Popen([sys.executable, str(RAIZ / "ritmelli.py"), "--pistavoz", arg], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            self.assertEqual(p.stdout.readline().strip(), "pronto")
            time.sleep(3)
            self.assertTrue(f.a.pista_ligada)
            secas = f.secas
            time.sleep(3)
            self.assertEqual(f.secas, secas, "a pista nao secou depois da partida")
            p.stdin.write("sair\n")
            p.stdin.flush()
            p.stdin.close()
            self.assertEqual(p.wait(timeout=15), 0)
            p.stdout.close()
            p.stderr.close()
            self.assertFalse(f.a.pista_ligada)
            lido = np.concatenate(f.lido)[pista.COLCHAO:]
            self.assertGreater(float(np.sqrt((lido ** 2).mean())), 1e-4, "a voz convertida nao e silencio")
        finally:
            f.fecha()


if __name__ == "__main__":
    unittest.main(verbosity=2)
