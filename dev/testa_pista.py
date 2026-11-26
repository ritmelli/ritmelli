"""Testa a troca de voz do pedal (#129) sem o filtro de verdade e sem som: um anel falso, com o layout do
microfone/apo/anel.h e um nome so do teste (MICFX_MAPA), faz o papel do filtro: a cada 10 ms entrega 10 ms de voz crua
e, com a pista ligada, le 480 quadros dela a partir de onde o escritor marcou.

Confere o pista.py com um conversor de mentira (o bloco sai como entrou): a pista so liga com a primeira voz
convertida, o colchao de silencio sai inteiro na frente dela, a voz chega em ordem e sem buraco, o microfone a 44,1 kHz
vira 48 kHz, o erro do conversor desliga a pista, e sair desliga a pista na hora. O ajuste do tom: a pista sai muda
enquanto mede, diz o "ouvindo" em passos e o "medido" com o deslocamento, e so entao converte; sem voz, segue muda.

Confere o pistavoz.py (com um processo de mentira): a voz escolhida e o tom de quem fala ficam no pedal_voz.json da
pasta que o servidor passa (no --mock, a temporaria), voz desconhecida e recusada, sem as vozes baixadas o pedal nao
sobe processo nenhum, sem o tom medido o processo sobe no ajuste e o visor passa por FALE ALGO, OUVINDO e PRONTO, com o
tom medido converte direto (o deslocamento pelo voz.json de cada voz), clicar na voz escolhida mede de novo e desligar
no meio do ajuste nao guarda nada.

Com RITMELLI_VOZES_TESTE=1 (os modelos do python dev/vozes.py baixa) ou apontando para outra pasta com as releases do
ritmelli-voices, tambem roda o processo inteiro (ritmelli.py --pistavoz) com os modelos de verdade, na placa de video:
com o tom dado, e medindo o tom de uma vogal sintetica.

    python dev/testa_pista.py

Sai 1 se algo falhar."""
import contextlib
import ctypes
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from ctypes import wintypes
from pathlib import Path
from unittest import mock

import numpy as np

os.environ["MICFX_MAPA"] = f"Local\\RitmelliTestePista-{os.getpid()}"  # nunca o anel do filtro de verdade
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import pista
import pistavoz
from microfone import injeta

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

    def __init__(self, taxa=48000, vogal_hz=0):
        FiltroFalso.conta += 1
        self.vogal_hz = vogal_hz  # > 0: no lugar da rampa, uma vogal sintetica (harmonicos) nesse tom
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
            if self.vogal_hz:
                fase = 2 * np.pi * self.vogal_hz * n / self.taxa
                x = 0.2 * sum(np.sin(h * fase) / h * np.exp(-h / 12) for h in range(1, 30)) / 1.6
            else:
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
    """O bloco sai como entrou, depois de uma conta de 20 ms; com falha, o terceiro bloco levanta. O tom de quem fala
    (tom_congelado) e hz em todo quadro, e o ajuste_tom() fica guardado em tons."""

    def __init__(self, falha=False, hz=0.0):
        self.falha, self.n, self.hz, self.tons = falha, 0, hz, []
        self.tom_congelado = np.zeros(0, np.float32)

    def bloco(self, x):
        self.n += 1
        if self.falha and self.n == 3:
            raise RuntimeError("placa sumiu")
        time.sleep(0.02)
        self.tom_congelado = np.full(8, self.hz, np.float32)
        return x.copy()

    def ajusta_tom(self, tom):
        self.tons.append(tom)


def roda_pista(filtro, conv, segundos, ajuste=None):
    m = injeta.Microfone()
    p = pista.Pista(m, conv, ajuste)
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

    def test_ajuste_do_tom(self):
        """Medindo: a pista sai muda (o colchao e os blocos do ajuste em silencio), o "ouvindo" sobe em passos ate 1, o
        "medido" traz o tom de quem fala e o deslocamento ate o alvo, e a voz so sai depois, em ordem."""
        f = FiltroFalso()
        ditos = []
        try:
            with mock.patch.object(pista, "AJUSTE_S", 0.4), mock.patch.object(pista, "diz", ditos.append):
                conv = ConversorFalso(hz=123.4)
                p, _ = roda_pista(f, conv, 2.0, pista.Ajuste(208.0))
            self.assertIsNone(p.erro)
            ouvindo = [float(d.split()[1]) for d in ditos if d.startswith("ouvindo")]
            self.assertTrue(ouvindo and ouvindo == sorted(ouvindo) and ouvindo[-1] == 1.0, ditos)
            medido = [d for d in ditos if d.startswith("medido")]
            self.assertEqual(len(medido), 1, ditos)
            hz, tom = map(float, medido[0].split()[1:])
            self.assertAlmostEqual(hz, 123.4, places=1)
            self.assertAlmostEqual(tom, 12 * np.log2(208 / 123.4), places=2)
            self.assertEqual(conv.tons, [aprox(tom)], "o conversor passa ao deslocamento medido")
            lido = np.concatenate(f.lido)
            mudos = 5 * N  # 0,4 s de fala = 40 quadros = 5 blocos de 8
            np.testing.assert_array_equal(lido[:pista.COLCHAO + mudos], 0, "mudo enquanto mede")
            voz = lido[pista.COLCHAO + mudos:]
            self.assertGreater(len(voz), N, "depois do ajuste a voz sai")
            passo = np.round(np.diff(voz) * 100000).astype(int)
            self.assertTrue(np.all((passo == 1) | (passo == -99999)), "em ordem, sem buraco")
        finally:
            f.fecha()

    def test_ajuste_sem_voz_segue_mudo(self):
        """Ninguem fala (nenhum quadro com tom): nada de "ouvindo" nem "medido", e a pista segue muda."""
        f = FiltroFalso()
        ditos = []
        try:
            with mock.patch.object(pista, "diz", ditos.append):
                p, ligada = roda_pista(f, ConversorFalso(hz=0.0), 1.5, pista.Ajuste(208.0))
            self.assertTrue(ligada, "a pista liga muda: a voz de verdade nao vaza")
            self.assertEqual([d for d in ditos if d != "pronto"], [])
            np.testing.assert_array_equal(np.concatenate(f.lido), 0)
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


def aprox(v):
    """Igual a v ate o centesimo (o deslocamento vai pelo texto com duas casas)."""
    class Aprox(float):
        def __eq__(self, o):
            return abs(float(o) - v) < 0.006
        __hash__ = float.__hash__
    return Aprox(v)


class Entrada(io.StringIO):
    """A entrada do processo de mentira: o que recebeu fica em recebido, tambem depois de fechada."""
    recebido = ""

    def close(self):
        self.recebido = self.getvalue()
        super().close()


class ProcFalso:
    """O processo da troca de voz de mentira: guarda o json que recebeu e diz o que o teste mandar."""
    todos = []

    def __init__(self, args, **_):
        self.cfg = json.loads(args[-1])
        self.linhas = queue.Queue()
        self.stdout = iter(self.linhas.get, None)
        self.stdin = Entrada()
        ProcFalso.todos.append(self)

    def diz(self, linha):
        self.linhas.put(linha + "\n")

    def wait(self, timeout=None):
        self.linhas.put(None)
        return 0

    def kill(self):
        self.linhas.put(None)


class TestaModulo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.modelos = pistavoz.MODELOS
        pistavoz.MODELOS = Path(self.tmp.name) / "modelos"  # nenhum modelo baixado
        pistavoz._refaz = False
        ProcFalso.todos = []
        self.pilha = contextlib.ExitStack()
        # o log do processo e o processo: nunca os de verdade (a pasta de logs e a de quem usa)
        self.pilha.enter_context(mock.patch.object(pistavoz.pastas, "LOGS", Path(self.tmp.name) / "logs"))
        self.pilha.enter_context(mock.patch.object(pistavoz.subprocess, "Popen", ProcFalso))
        self.pilha.enter_context(mock.patch.object(pistavoz, "PRONTO_S", 0.05))
        self.pilha.enter_context(contextlib.redirect_stderr(io.StringIO()))
        pistavoz.dados(self.tmp.name)

    def tearDown(self):
        pistavoz.liga(False)
        self.pilha.close()
        pistavoz.MODELOS = self.modelos
        self.tmp.cleanup()

    def baixa(self, **alvos):
        """As pastas das vozes, com o voz.json de cada uma (o tom_hz)."""
        (pistavoz.MODELOS / pistavoz.ENGINE).mkdir(parents=True)
        for voz, tag in pistavoz.RELEASES.items():
            (pistavoz.MODELOS / tag).mkdir(parents=True)
            (pistavoz.MODELOS / tag / "voz.json").write_text(json.dumps({"tom_hz": alvos.get(voz, 208)}))

    def espera(self, cond, s=2.0):
        fim = time.monotonic() + s
        while not cond() and time.monotonic() < fim:
            time.sleep(0.01)
        return cond()

    def guardado(self):
        with open(Path(self.tmp.name) / "pedal_voz.json", encoding="utf-8") as f:
            return json.load(f)

    def test_ajuste_na_primeira_vez(self):
        self.baixa()
        pistavoz.liga(True)
        p = ProcFalso.todos[-1]
        self.assertEqual((p.cfg["tom"], p.cfg["alvo_hz"]), (None, 208.0), "sem o tom medido, o processo mede")
        self.assertEqual(pistavoz.estado()["visor"], "fale")
        p.diz("pronto")
        p.diz("ouvindo 0.250")
        self.assertTrue(self.espera(lambda: pistavoz.estado()["visor"] == "ouvindo"))
        self.assertEqual(pistavoz.estado()["progresso"], 0.25)
        p.diz("medido 123.4 9.02")
        self.assertTrue(self.espera(lambda: pistavoz.estado()["visor"] == "pronto"))
        self.assertEqual(self.guardado()["falante_hz"], 123.4)
        self.assertTrue(self.espera(lambda: pistavoz.estado()["visor"] is None), "o PRONTO volta para a voz")

    def test_com_o_tom_medido_converte_direto(self):
        self.baixa(lira=250)
        (Path(self.tmp.name) / "pedal_voz.json").write_text(json.dumps({"voz": "mina", "falante_hz": 123.4}))
        pistavoz.dados(self.tmp.name)
        pistavoz.liga(True)
        self.assertAlmostEqual(ProcFalso.todos[-1].cfg["tom"], 12 * np.log2(208 / 123.4), places=2)
        self.assertIsNone(pistavoz.estado()["visor"])
        pistavoz.escolhe("lira")  # a mesma medida serve para a outra voz, com o tom_hz dela
        self.assertAlmostEqual(ProcFalso.todos[-1].cfg["tom"], 12 * np.log2(250 / 123.4), places=2)
        self.assertEqual(len(ProcFalso.todos), 2)

    def test_clicar_na_escolhida_mede_de_novo(self):
        self.baixa()
        (Path(self.tmp.name) / "pedal_voz.json").write_text(json.dumps({"voz": "mina", "falante_hz": 123.4}))
        pistavoz.dados(self.tmp.name)
        pistavoz.liga(True)
        antes = ProcFalso.todos[-1]
        pistavoz.escolhe("mina")
        self.assertIn("sair", antes.stdin.recebido)
        p = ProcFalso.todos[-1]
        self.assertIsNone(p.cfg["tom"], "a escolhida de novo mede o tom de novo")
        self.assertEqual(pistavoz.estado()["visor"], "fale")
        p.diz("medido 150.0 5.66")
        self.assertTrue(self.espera(lambda: self.guardado()["falante_hz"] == 150.0))
        pistavoz.liga(False)
        pistavoz.liga(True)
        self.assertAlmostEqual(ProcFalso.todos[-1].cfg["tom"], 12 * np.log2(208 / 150), places=2, msg="medido, nao mede mais")

    def test_desligar_no_meio_do_ajuste(self):
        self.baixa()
        pistavoz.liga(True)
        ProcFalso.todos[-1].diz("ouvindo 0.500")
        self.assertTrue(self.espera(lambda: pistavoz.estado()["visor"] == "ouvindo"))
        pistavoz.liga(False)
        self.assertEqual(pistavoz.estado(), {"voz": "mina", "visor": None, "progresso": None})
        self.assertFalse((Path(self.tmp.name) / "pedal_voz.json").exists(), "nada medido, nada guardado")
        pistavoz.liga(True)
        self.assertIsNone(ProcFalso.todos[-1].cfg["tom"], "o ajuste fica para a proxima vez")

    def test_voz_json_ruim_nao_sobe(self):
        self.baixa(mina="alto")
        pistavoz.liga(True)
        self.assertEqual(ProcFalso.todos, [])

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
        self.assertEqual(ProcFalso.todos, [])


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

    def test_processo_mede_o_tom(self):
        """O processo inteiro no ajuste, com uma vogal sintetica a 150 Hz: diz "ouvindo" ate 1 e "medido" com uns 150
        Hz e o deslocamento ate o alvo, e a voz convertida so sai depois (antes, a pista sai muda)."""
        v = Path(os.environ["RITMELLI_VOZES_TESTE"])
        v = v if v.is_dir() else pistavoz.MODELOS
        f = FiltroFalso(taxa=48000, vogal_hz=150)
        try:
            arg = json.dumps({"engine": str(v / pistavoz.ENGINE), "voz": str(v / pistavoz.RELEASES["mina"]),
                              "tom": None, "alvo_hz": 208.0})
            env = dict(os.environ, MICFX_MAPA=injeta.MAPA)
            p = subprocess.Popen([sys.executable, str(RAIZ / "ritmelli.py"), "--pistavoz", arg], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            linhas = []
            for linha in p.stdout:
                linhas.append(linha.strip())
                if linha.startswith(("medido", "erro")):
                    break
            self.assertEqual(linhas[0], "pronto")
            self.assertTrue(linhas[-1].startswith("medido"), linhas)
            hz, tom = map(float, linhas[-1].split()[1:])
            self.assertAlmostEqual(hz, 150, delta=3)
            self.assertAlmostEqual(tom, 12 * np.log2(208 / hz), places=1)
            self.assertEqual(float(linhas[-2].split()[1]), 1.0)
            mudo = len(np.concatenate(f.lido))
            time.sleep(3)
            p.stdin.write("sair\n")
            p.stdin.flush()
            p.stdin.close()
            self.assertEqual(p.wait(timeout=15), 0)
            p.stdout.close()
            p.stderr.close()
            lido = np.concatenate(f.lido)
            np.testing.assert_array_equal(lido[:mudo - 2 * N], 0, "mudo enquanto media")
            self.assertGreater(float(np.sqrt((lido[mudo:] ** 2).mean())), 1e-4, "depois, a voz convertida")
        finally:
            f.fecha()


if __name__ == "__main__":
    unittest.main(verbosity=2)
