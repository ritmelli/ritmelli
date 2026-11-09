"""Testa o processo vivo dos enderecos (server.Fora._pede_vivo e o laco do yt_fora.main) sem o YouTube: o auxiliar
e o yt_fora de verdade com o faz trocado por um falso que devolve o pid e quantos pedidos aquele processo ja atendeu.
Cobre: dois enderecos no mesmo processo; os outros pedidos por fora dele; o vivo saindo no erro, no estouro do limite,
depois de VIVO_MAX pedidos e de VIVO_MAX_S; o vivo ocupado (o pedido vai ao segundo vivo; os VIVOS ocupados, por um
processo novo); e desligado (VIVO_MAX = 0). Sai 1 se algo falhar.

    python dev/testa_vivo.py
"""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import server  # noqa: E402

FALSO = f'''
import os, sys, time
sys.path.insert(0, {str(RAIZ)!r})
import yt_fora
def faz(p):
    if p.get("alvo") == "erro":
        raise RuntimeError("o YouTube recusou")
    if p.get("alvo") == "indisponivel":
        raise RuntimeError("ERROR: [youtube] xyz: Video unavailable. This video is not available")
    if p.get("alvo") == "dorme":
        time.sleep(float(p.get("s", 3)))
    yt_fora._N = getattr(yt_fora, "_N", 0) + 1
    return {{"pid": os.getpid(), "n": yt_fora._N, "vivo": yt_fora.VIVO}}
yt_fora.faz = faz
yt_fora.aquece_ytm = lambda: None  # sem o GET do YouTube Music: o teste nao sai para a rede
yt_fora.main()
'''


class Vivo(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(server, "auxiliar", lambda modo: [sys.executable, "-c", FALSO])
        self.p.start()
        self.f = server.Fora()

    def tearDown(self):
        for v in self.f.vivos:
            with v.lock:
                self.f._solta_vivo(v)
        with self.f.lock:
            rs, self.f.reservas = self.f.reservas, []
        for r in rs:
            r.stdin.close()
        self.p.stop()

    def stream(self, alvo="a", **kw):
        return self.f.pede("stream", alvo=alvo, **kw)

    def test_mesmo_processo(self):
        a, b = self.stream(), self.stream()
        self.assertEqual((a["pid"], a["n"], a["vivo"]), (b["pid"], 1, True))
        self.assertEqual(b["n"], 2, "o segundo endereco no mesmo processo")

    def test_outros_pedidos_por_fora(self):
        a = self.stream()
        i = self.f.pede("info", alvo="x")
        self.assertNotEqual(i["pid"], a["pid"])
        self.assertFalse(i["vivo"])
        self.assertEqual(self.stream()["pid"], a["pid"], "o info nao mexe no vivo")

    def test_duas_reservas(self):
        self.f.aquece()
        self.assertEqual(len(self.f.reservas), server.RESERVAS)
        a, b = self.f._tira_reserva(), self.f._tira_reserva()
        self.assertNotEqual(a.pid, b.pid, "dois pedidos juntos, dois processos ja abertos")
        a.stdin.close()
        b.stdin.close()
        n = 0
        for _ in range(100):
            with self.f.lock:
                n = len(self.f.reservas)
            if n == server.RESERVAS:
                break
            time.sleep(0.1)
        self.assertEqual(n, server.RESERVAS, "as reservas voltam a ser duas")

    def test_erro_troca_o_vivo(self):
        a = self.stream()
        with self.assertRaisesRegex(RuntimeError, "recusou"):
            self.stream("erro")
        self.assertNotEqual(self.stream()["pid"], a["pid"])

    def test_erro_do_video_nao_troca_o_vivo(self):
        a = self.stream()
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            self.stream("indisponivel")
        b = self.stream()
        self.assertEqual(b["pid"], a["pid"], "o video indisponivel nao e defeito do processo: o vivo fica quente")
        self.assertEqual(b["n"], a["n"] + 1, "o mesmo processo (o falso so conta o que deu certo)")

    def test_limite_mata_e_o_seguinte_abre_outro(self):
        a = self.stream()
        t = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "não respondeu a tempo"):
            self.stream("dorme", s=5, limite=1)
        self.assertLess(time.monotonic() - t, 3)
        b = self.stream()
        self.assertNotEqual(b["pid"], a["pid"])
        self.assertTrue(b["vivo"])

    def test_vivo_max(self):
        with mock.patch.object(server, "VIVO_MAX", 2):
            a, b, c = self.stream(), self.stream(), self.stream()
        self.assertEqual(a["pid"], b["pid"])
        self.assertNotEqual(c["pid"], a["pid"])
        self.assertEqual(c["n"], 1)

    def test_vivo_max_s(self):
        with mock.patch.object(server, "VIVO_MAX_S", 0.0):
            a, b = self.stream(), self.stream()
        self.assertNotEqual(a["pid"], b["pid"])

    def test_ocupado_vai_ao_segundo_e_depois_por_um_novo(self):
        a = self.stream()
        lentos = {}
        ths = [threading.Thread(target=lambda k=k: lentos.update({k: self.stream("dorme", s=3)})) for k in (1, 2)]
        ths[0].start()
        time.sleep(0.5)  # o primeiro vivo (o de a) ocupado
        ths[1].start()
        time.sleep(0.5)  # o segundo vivo ocupado
        c = self.stream()  # os dois ocupados
        for t in ths:
            t.join()
        self.assertEqual(lentos[1]["pid"], a["pid"])
        self.assertTrue(lentos[2]["vivo"], "o segundo pedido ao mesmo tempo vai ao segundo vivo")
        self.assertNotEqual(lentos[2]["pid"], a["pid"])
        self.assertFalse(c["vivo"], "os dois vivos ocupados: processo novo")
        self.assertEqual(self.stream()["pid"], a["pid"], "o primeiro vivo segue o mesmo")

    def test_um_vivo_so(self):
        with mock.patch.object(server, "VIVOS", 1):
            f = server.Fora()
        try:
            a = f.pede("stream", alvo="a")
            lento = {}
            th = threading.Thread(target=lambda: lento.update(f.pede("stream", alvo="dorme", s=2)))
            th.start()
            time.sleep(0.5)
            b = f.pede("stream", alvo="a")
            th.join()
            self.assertEqual(lento["pid"], a["pid"])
            self.assertFalse(b["vivo"])
        finally:
            for v in f.vivos:
                with v.lock:
                    f._solta_vivo(v)

    def test_desligado(self):
        with mock.patch.object(server, "VIVO_MAX", 0):
            a, b = self.stream(), self.stream()
        self.assertNotEqual(a["pid"], b["pid"])
        self.assertFalse(a["vivo"] or b["vivo"])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
