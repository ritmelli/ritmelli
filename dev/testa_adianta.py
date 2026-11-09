"""Testa o endereco adiantado (server.App.adianta_endereco, endereco_adiantado e o _abre_stream que usa o adiantado)
sem o YouTube: o stream_info e um falso que conta os pedidos. Cobre: o tocar usa o adiantado sem pedir outro; sem
adiantado, pede; o adiantado que falhou cai no pedido normal; o vencido (ADIANTA_S) nao vale; ADIANTA = False nao
adianta; o mesmo video adiantado duas vezes e um pedido so; o adiantado que saiu abre o ffmpeg antes (preabre) e o que
falhou nao; o adiantado que nem comecou (executor cheio) e cancelado e o tocar pede na hora; o disco que entrou sem
canal pede o canal depois. Sai 1 se algo falhar.

    python dev/testa_adianta.py
"""
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

YID = "CmB4sfoZkwo"


class Adianta(unittest.TestCase):
    def setUp(self):
        self.pedidos = []
        self.falha = set()
        self.trocas = []
        self.tr = {"id": YID, "youtube_id": YID, "title": "Metamorfose Ambulante", "channel": None, "thumb": None,
                   "duration": None, "path": None, "stream": True, "job": None}
        app = types.SimpleNamespace(_adiantados={}, _adi_lock=threading.Lock())

        def stream_info(target, formato=None, canal=False):
            self.pedidos.append(target)
            time.sleep(0.05)
            if target in self.falha:
                self.falha.discard(target)
                raise RuntimeError("o YouTube recusou")
            return {"url": f"https://audio/{target}", "id": YID, "title": "x"}, "h"
        app.stream_info = stream_info
        self.preabertos, self.canais = [], []
        app.engine = types.SimpleNamespace(track=self.tr, trocar_fonte=lambda a, n: self.trocas.append(n) or True,
                                           preabre=lambda url, h=None: self.preabertos.append(url))
        app._preabre = lambda fut: server.App._preabre(app, fut)
        app.canal_depois = lambda tr, no_prato=False: self.canais.append(tr.get("youtube_id"))
        app.adianta_endereco = lambda yid: server.App.adianta_endereco(app, yid)
        app.endereco_adiantado = lambda yid: server.App.endereco_adiantado(app, yid)
        self.app = app

    def abre(self):
        with mock.patch.object(server.time, "sleep", lambda s: None):
            server.App._abre_stream(self.app, self.tr, YID, True)

    def test_tocar_usa_o_adiantado(self):
        self.app.adianta_endereco(YID)
        self.abre()
        self.assertEqual(self.pedidos, [YID], "um pedido so: o do adiantado")
        self.assertEqual(self.trocas[0]["path"], f"https://audio/{YID}")

    def test_sem_adiantado_pede(self):
        self.abre()
        self.assertEqual(self.pedidos, [YID])
        self.assertEqual(len(self.trocas), 1)

    def test_adiantado_que_falhou_pede_de_novo(self):
        self.falha.add(YID)
        self.app.adianta_endereco(YID)
        self.abre()
        self.assertEqual(self.pedidos, [YID, YID])
        self.assertEqual(self.trocas[0]["path"], f"https://audio/{YID}")

    def test_vencido_nao_vale(self):
        with mock.patch.object(server, "ADIANTA_S", 0.0):
            self.app.adianta_endereco(YID)
            time.sleep(0.1)
            self.abre()
        self.assertEqual(len(self.pedidos), 2, "o vencido nao conta: o tocar pede outro")

    def test_desligado(self):
        with mock.patch.object(server, "ADIANTA", False):
            self.app.adianta_endereco(YID)
        self.assertEqual(self.app._adiantados, {})

    def test_o_mesmo_duas_vezes(self):
        self.app.adianta_endereco(YID)
        self.app.adianta_endereco(YID)
        time.sleep(0.2)
        self.assertEqual(self.pedidos, [YID])

    def test_preabre_o_que_saiu(self):
        self.app.adianta_endereco(YID)
        time.sleep(0.2)
        self.assertEqual(self.preabertos, [f"https://audio/{YID}"])
        self.falha.add("abcdefghijk")
        self.app.adianta_endereco("abcdefghijk")
        time.sleep(0.2)
        self.assertEqual(len(self.preabertos), 1, "o que falhou nao abre ffmpeg")

    def test_adiantado_que_nem_comecou_e_cancelado(self):
        trava = threading.Event()
        lento = server.ThreadPoolExecutor(1)
        lento.submit(trava.wait)  # o executor ocupado: o adiantado fica na fila
        try:
            with mock.patch.object(server, "pool_rapido", lento):
                self.app.adianta_endereco(YID)
                self.abre()
        finally:
            trava.set()
            lento.shutdown()
        self.assertEqual(self.pedidos, [YID], "pediu na hora, o da fila nao rodou")
        self.assertEqual(self.trocas[0]["path"], f"https://audio/{YID}")

    def test_canal_depois(self):
        self.abre()
        self.assertEqual(self.canais, [YID], "entrou sem canal: pede depois")

    def test_canal_do_disco_que_saiu_nao_pede(self):
        pedidos = []
        tr = {"youtube_id": YID, "channel": None}
        app = types.SimpleNamespace(engine=types.SimpleNamespace(track=tr))
        with mock.patch.object(server.fora, "pede", lambda op, **kw: pedidos.append(op) or {"channel": "x"}), \
                mock.patch.object(server, "CANAL_DEPOIS_S", 0.1):
            server.App.canal_depois(app, tr, no_prato=True)
            app.engine.track = {"youtube_id": "outro"}  # "nao, toca Y" antes do timer
            time.sleep(0.4)
        self.assertEqual(pedidos, [])

    def test_da_busca(self):
        feitos = []
        app = types.SimpleNamespace(tocadas=["t1"], engine=types.SimpleNamespace(track={"youtube_id": "t2"}),
                                    fila=[{"youtube_id": "t3"}], adianta_endereco=feitos.append)
        res = [{"youtube_id": y, "in_library": y == "t5"} for y in ("t1", "t2", "t3", "t4", "t5")]
        server.App.adianta_da_busca(app, res, 3)
        server.App.adianta_da_busca(app, res, 8)
        server.App.adianta_da_busca(app, res[4:], 8)
        server.App.adianta_da_busca(app, [], 3)
        self.assertEqual(feitos, ["t1", "t4"], "ate 3 o primeiro; o outra o primeiro que nao tocou; prateleira nada")
        feitos.clear()
        app.engine.track = {"youtube_id": "t2", "title": "O REI DA CACIMBINHA - Meu Pai É Foda"}
        res = [{"youtube_id": "v1", "title": "Meu Pai É Foda (Ao Vivo)", "in_library": False},
               {"youtube_id": "v2", "title": "Bicicletinha", "in_library": False}]
        server.App.adianta_da_busca(app, res, 8)
        self.assertEqual(feitos, ["v2"], "outra versao da que toca a mina pula: o servidor tambem")

    def test_so_id_de_video(self):
        self.app.adianta_endereco("Raul Seixas")
        self.app.adianta_endereco(None)
        self.assertEqual(self.app._adiantados, {})


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
