"""Testa o endereco rapido (yt_fora.opts_rapido e o op "stream" com rapido; server.stream_info) sem o YouTube: o
stream_yt e um falso que anota as opts e falha quando mandado. Cobre: as opts rapidas levam so o visionos, os skips e
o visitor id do YouTube Music; o rapido que falha cai no de sempre no mesmo processo; sem visitor id, o de sempre; sem
rapido, so o de sempre; o servidor pede rapido so no formato padrao e com ENDERECO_RAPIDO. Sai 1 se algo falhar.

    python dev/testa_rapido.py
"""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import yt_fora  # noqa: E402

OPTS = {"quiet": True, "format": "bestaudio[protocol^=http]/bestaudio/best"}


class Rapido(unittest.TestCase):
    def setUp(self):
        self.chamadas = []
        self.falha_rapido = False
        yt_fora._rapido_falhas = 0

        def stream_yt(alvo, opts):
            yt = (opts.get("extractor_args") or {}).get("youtube") or {}
            self.chamadas.append(yt)
            if yt and self.falha_rapido:
                raise RuntimeError("o YouTube recusou o cliente")
            return {"url": "https://audio/x", "id": "x", "title": "t"}, "h"
        self.p1 = mock.patch.object(yt_fora, "stream_yt", stream_yt)
        self.p2 = mock.patch.object(yt_fora, "ytm", lambda: types.SimpleNamespace(headers={"X-Goog-Visitor-Id": "Cgt"}))
        self.p1.start()
        self.p2.start()

    def tearDown(self):
        self.p1.stop()
        self.p2.stop()

    def test_opts_rapidas(self):
        o = yt_fora.opts_rapido({**OPTS, "extractor_args": {"youtube": {"lang": ["pt"]}}})
        yt = o["extractor_args"]["youtube"]
        self.assertEqual(yt["player_client"], ["visionos"])
        self.assertEqual(set(yt["player_skip"]), {"webpage", "configs", "initial_data", "js"})
        self.assertEqual((yt["visitor_data"], yt["skip"], yt["lang"]), (["Cgt"], ["hls"], ["pt"]))
        self.assertEqual(o["format"], OPTS["format"])

    def test_rapido(self):
        r = yt_fora.faz({"op": "stream", "alvo": "a", "opts": OPTS, "rapido": True})
        self.assertEqual(r["info"]["url"], "https://audio/x")
        self.assertEqual(len(self.chamadas), 1)
        self.assertEqual(self.chamadas[0]["player_client"], ["visionos"])

    def test_rapido_que_falha_vai_pelo_de_sempre(self):
        self.falha_rapido = True
        r = yt_fora.faz({"op": "stream", "alvo": "a", "opts": OPTS, "rapido": True})
        self.assertEqual(r["info"]["url"], "https://audio/x")
        self.assertEqual(len(self.chamadas), 2)
        self.assertEqual(self.chamadas[1], {}, "o segundo e o de sempre, sem as opts rapidas")

    def test_sem_visitor_id(self):
        with mock.patch.object(yt_fora, "ytm", lambda: types.SimpleNamespace(headers={})):
            yt_fora.faz({"op": "stream", "alvo": "a", "opts": OPTS, "rapido": True})
        self.assertEqual(self.chamadas, [{}])

    def test_sem_rapido(self):
        yt_fora.faz({"op": "stream", "alvo": "a", "opts": OPTS})
        self.assertEqual(self.chamadas, [{}])

    def test_disjuntor(self):
        self.falha_rapido = True
        for _ in range(3):
            yt_fora.faz({"op": "stream", "alvo": "a", "opts": OPTS, "rapido": True})
        self.assertEqual(len(self.chamadas), 5, "duas falhas do rapido, depois so o de sempre")
        yt_fora._rapido_falhas = 0

    def test_not_a_bot_desliga_na_hora(self):
        def stream_yt(alvo, opts):
            yt = (opts.get("extractor_args") or {}).get("youtube") or {}
            self.chamadas.append(yt)
            if yt:
                raise RuntimeError("Sign in to confirm you're not a bot")
            return {"url": "u", "id": "x"}, "h"
        with mock.patch.object(yt_fora, "stream_yt", stream_yt):
            yt_fora.faz({"op": "stream", "alvo": "a", "opts": OPTS, "rapido": True})
            yt_fora.faz({"op": "stream", "alvo": "a", "opts": OPTS, "rapido": True})
        self.assertEqual(len(self.chamadas), 3)
        yt_fora._rapido_falhas = 0

    def test_canal_quando_falta(self):
        song = types.SimpleNamespace(headers={"X-Goog-Visitor-Id": "Cgt"},
                                     get_song=lambda yid: {"videoDetails": {"author": "Raul Seixas"}})
        with mock.patch.object(yt_fora, "ytm", lambda: song):
            r = yt_fora.faz({"op": "stream", "alvo": "a", "opts": OPTS, "rapido": True, "canal": True})
            s = yt_fora.faz({"op": "stream", "alvo": "a", "opts": OPTS, "rapido": True})
        self.assertEqual(r["info"]["channel"], "Raul Seixas")
        self.assertIsNone(s["info"]["channel"], "sem o pedido do canal, nada a mais")

    def test_ytm_guarda_o_cliente_novo(self):
        criados = []

        class YTM:
            def __init__(self):
                criados.append(self)
                self.headers = {"X-Goog-Visitor-Id": "Cgt"}
        self.p2.stop()
        try:
            with mock.patch.object(yt_fora, "_AQUECE", None), mock.patch.object(yt_fora, "_YTM", None), \
                    mock.patch.object(yt_fora, "_AQUECE_ERRO", "sem rede"), \
                    mock.patch.dict(sys.modules, {"ytmusicapi": types.SimpleNamespace(YTMusic=YTM)}):
                a, b = yt_fora.ytm(), yt_fora.ytm()
        finally:
            self.p2.start()
        self.assertIs(a, b)
        self.assertEqual(len(criados), 1, "o cliente novo que conseguiu o visitor id fica")

    def test_servidor_pede_rapido(self):
        pedidos = []

        def pede(op, **kw):
            pedidos.append(kw.get("rapido"))
            self.assertIn("canal", kw)
            return {"info": {}, "hdr": ""}
        app = types.SimpleNamespace(alvo_yt=server.App.alvo_yt, opts_stream=server.App.opts_stream)
        with mock.patch.object(server.fora, "pede", pede):
            server.App.stream_info(app, "CmB4sfoZkwo")
            server.App.stream_info(app, "CmB4sfoZkwo", "bestaudio/best")
            with mock.patch.object(server, "ENDERECO_RAPIDO", False):
                server.App.stream_info(app, "CmB4sfoZkwo")
        self.assertEqual(pedidos, [True, False, False])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
