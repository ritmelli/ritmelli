"""Testa a busca de musica do YouTube Music (yt_fora.musica, a rota /api/musica) sem a internet: um YouTube Music de
mentira devolve a busca e a pagina do artista. Cobre o pedido que e so o nome do artista (a mais tocada dele, com a
escrita errando um pouco e as iniciais com ponto), o pedido com o nome da musica junto (a musica, sem abrir a pagina do
artista), o video entrando e o que nao e musica nem video ficando de fora; e a busca junto da sugestao no pedido longo
(o tempo, a sugestao que acerta, o erro, o processo que sai sem esperar a busca jogada fora, a segunda conexao). Sai 1
se algo falhar.

    python dev/testa_musica.py
"""
import json
import subprocess
import sys
import threading
import time
import types
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import yt_fora  # noqa: E402


class YtmFalso:
    def __init__(self, busca, artistas=None, sugestoes=None):
        self.busca, self.artistas, self.pediu = busca, artistas or {}, []
        self.sugestoes = sugestoes or {}

    def _send_request(self, endpoint, corpo):
        self.pediu.append(("sugestao", corpo["input"]))
        itens = []
        for x in self.sugestoes.get(corpo["input"], []):
            if isinstance(x, dict):  # ja no formato da resposta (sug_musica, sug_artista)
                itens.append(x)
                continue
            yid, titulo, segunda = x
            itens.append({"musicResponsiveListItemRenderer": {
                "playlistItemData": {"videoId": yid},
                "flexColumns": [{"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": t}]}}}
                                for t in (titulo, segunda)]}})
        return {"contents": [{"searchSuggestionsSectionRenderer": {"contents": itens}}]}

    def search(self, q, limit=10):
        self.pediu.append(("search", q))
        return self.busca.get(q, [])

    def get_artist(self, bid):
        self.pediu.append(("artist", bid))
        return self.artistas[bid]


def _canal(bid, tipo="MUSIC_PAGE_TYPE_ARTIST"):
    return {"browseEndpoint": {"browseId": bid, "browseEndpointContextSupportedConfigs": {
        "browseEndpointContextMusicConfig": {"pageType": tipo}}}}


def _col(runs):
    return {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": runs}}}


def sug_musica(yid, titulo, nome, bid, tipo="Song"):
    """Uma musica sugerida como a resposta de verdade (09/11): o artista leva o id do canal; o album tambem e link."""
    return {"musicResponsiveListItemRenderer": {
        "playlistItemData": {"videoId": yid},
        "flexColumns": [_col([{"text": titulo}]),
                        _col([{"text": tipo}, {"text": " • "}, {"text": nome, "navigationEndpoint": _canal(bid)},
                              {"text": " • "}, {"text": "12M plays"}]),
                        _col([{"text": titulo, "navigationEndpoint": _canal("MPREb_1", "MUSIC_PAGE_TYPE_ALBUM")}])]}}


def sug_artista(nome, bid):
    return {"musicResponsiveListItemRenderer": {
        "navigationEndpoint": _canal(bid),
        "flexColumns": [_col([{"text": nome}]), _col([{"text": "4.74M monthly audience"}])]}}


def artista(nome, bid):
    return {"category": "Top result", "resultType": "artist", "artists": [{"name": nome, "id": bid}]}


def musica(yid, titulo, nome=None, tipo="song"):
    return {"resultType": tipo, "videoId": yid, "title": titulo, "artists": [{"name": nome}] if nome else []}


class Musica(unittest.TestCase):
    def test_so_artista(self):
        for ped, art in (("Raul", "Raul Seixas"), ("the weekend", "The Weeknd"), ("rei da cimbinha", "Rei da Cacimbinha"),
                         ("Pedro Joilson", "Pedro E Joilson"), ("M.C. Gorila", "Mc Gorila"), ("Kevin", "MC Kevin"),
                         ("Racionais MC's", "Racionais MC's")):
            self.assertTrue(yt_fora.so_artista(ped, art), (ped, art))
        for ped, art in (("Luan Santana Chuva de Arroz", "Luan Santana"), ("Te dei o sol te dei o mar", "Luan Santana"),
                         ("Gaiola funk", "MC Livinho"), ("uma música boa", "Emilly Vick")):
            self.assertFalse(yt_fora.so_artista(ped, art), (ped, art))

    def test_artista_toca_a_mais_tocada(self):
        y = YtmFalso({"Raul": [artista("Raul Seixas", "UC1"), musica("p1", "As profecias")]},
                     {"UC1": {"name": "Raul Seixas", "songs": {"results": [musica("m1", "Metamorfose Ambulante"),
                                                                           musica("g1", "Gita")]}}})
        achou = yt_fora.musica("Raul", 3, y)
        self.assertEqual([x["youtube_id"] for x in achou], ["m1", "g1"])
        self.assertEqual(achou[0]["channel"], "Raul Seixas", "sem o artista no resultado, vale o da página")

    def test_artista_com_a_musica_toca_a_musica(self):
        y = YtmFalso({"Luan Santana Chuva de Arroz": [artista("Luan Santana", "UC2"),
                                                       musica("c1", "Chuva de Arroz (Ao Vivo)", "Luan Santana")]})
        self.assertEqual(yt_fora.musica("Luan Santana Chuva de Arroz", 3, y)[0]["youtube_id"], "c1")
        self.assertNotIn("artist", [k for k, _ in y.pediu], "com o nome da música junto, a página do artista não abre")

    def test_video_entra_e_album_nao(self):
        y = YtmFalso({"balaco balaco bico": [{"resultType": "album", "browseId": "MPRE1", "title": "Funk"},
                                             musica("v1", "BALACO BALACO BICO", "mc lipzl", tipo="video")]})
        self.assertEqual(yt_fora.musica("balaco balaco bico", 3, y)[0]["youtube_id"], "v1")
        self.assertEqual(yt_fora.musica("nada", 3, YtmFalso({"nada": [{"resultType": "album"}]})), [])


class Sugestao(unittest.TestCase):
    def busca(self):
        return {"cheia de manias": [musica("v1", "Raça Negra - Cheia de Manias (Deezer Sessions)", "Raça Negra")],
                "alors on danse": [musica("v2", "Alors on danse", "Stromae")],
                "uma rapariga e bom demais": [musica("v3", "UMA RAPARIGA É BOM DEMAIS", "Filho do Piseiro")]}

    def test_song_que_bate(self):
        y = YtmFalso(self.busca(), sugestoes={"cheia de manias": [
            ("s1", "Cheia de Manias", "Song • Raça Negra • 168M plays")]})
        r = yt_fora.musica("cheia de manias", 3, y)
        self.assertEqual((r[0]["youtube_id"], r[0]["channel"]), ("s1", "Raça Negra"))
        self.assertNotIn("search", [k for k, _ in y.pediu], "pela sugestao, sem a busca")

    def test_song_depois_do_video(self):
        y = YtmFalso(self.busca(), sugestoes={"alors on danse": [
            ("s2", "Stromae - Alors On Dance (Dubdogz Remix)", "Video • 3.8M views"),
            ("s3", "Alors on danse", "Song • Stromae • 900M plays")]})
        with unittest.mock.patch.object(yt_fora, "PARALELO_PALAVRAS", 0):  # sem a busca junto (classe Paralelo)
            self.assertEqual(yt_fora.musica("alors on danse", 3, y)[0]["youtube_id"], "s3",
                             "o remix (video) fica de fora")
        self.assertNotIn("search", [k for k, _ in y.pediu])

    def test_so_video_vai_a_busca(self):
        y = YtmFalso(self.busca(), sugestoes={"alors on danse": [
            ("s2", "Stromae - Alors On Dance (Dubdogz Remix)", "Video • 3.8M views")]})
        self.assertEqual(yt_fora.musica("alors on danse", 3, y)[0]["youtube_id"], "v2")

    def test_outra_pelo_artista_da_musica_sugerida(self):
        """ "toca outra do Rei da Cacimbinha" (n 8): as sugestoes so trazem musicas dele; o artista delas (com o id do
        canal) e o pedido, e a lista sai da pagina dele, sem a busca."""
        pagina = {"name": "O Rei da Cacimbinha", "songs": {"results": [musica("m1", "Meu Pai É Foda"),
                                                                        musica("m2", "Bicicletinha")]}}
        y = YtmFalso({}, {"UC9": pagina}, sugestoes={"Rei da Cacimbinha": [
            sug_musica("p1", "Pop 100", "O Rei da Cacimbinha", "UC9"),
            sug_musica("p2", "Muriçoca", "O Rei da Cacimbinha", "UC9")]})
        r = yt_fora.musica("Rei da Cacimbinha", 8, y)
        self.assertEqual([x["youtube_id"] for x in r], ["m1", "m2"])
        self.assertEqual(y.pediu, [("sugestao", "Rei da Cacimbinha"), ("artist", "UC9")], "uma pagina, sem a busca")

    def test_item_do_artista(self):
        pagina = {"name": "Raul Seixas", "songs": {"results": [musica("m1", "Metamorfose Ambulante")]}}
        y = YtmFalso({}, {"UC1": pagina}, sugestoes={"Raul": [
            sug_artista("Raul Seixas", "UC1"), sug_musica("t1", "Tente Outra Vez", "Raul Seixas", "UC1")]})
        self.assertEqual(yt_fora.musica("Raul", 3, y)[0]["youtube_id"], "t1", "ate 3: a musica sugerida, sem pagina")
        self.assertEqual(yt_fora.musica("Raul", 8, y)[0]["youtube_id"], "m1", "o outra: a pagina")

    def test_artista_que_nao_e_so_o_pedido_vai_a_busca(self):
        busca = {"Luan Santana Chuva de Arroz": [musica("c1", "Chuva de Arroz (Ao Vivo)", "Luan Santana")]}
        y = YtmFalso(busca, {}, sugestoes={"Luan Santana Chuva de Arroz": [sug_artista("Luan Santana", "UC2")]})
        self.assertEqual(yt_fora.musica("Luan Santana Chuva de Arroz", 8, y)[0]["youtube_id"], "c1")
        self.assertNotIn("artist", [k for k, _ in y.pediu])

    def test_pagina_de_outro_nome_vai_a_busca(self):
        """O nome na sugestao bate, mas a pagina e de outro (o da pagina vale, como na busca): a busca de sempre."""
        busca = {"Kevin": [musica("k1", "Cavalo de Tróia", "Mc Kevin")]}
        y = YtmFalso(busca, {"UC3": {"name": "Os Garotos de Liverpool", "songs": {"results": [musica("x", "x")]}}},
                     sugestoes={"Kevin": [sug_artista("Kevin", "UC3")]})
        self.assertEqual(yt_fora.musica("Kevin", 8, y)[0]["youtube_id"], "k1")

    def test_versao_que_o_pedido_nao_falou(self):
        y = YtmFalso({"Chuva de Arroz Luan Santana": [musica("e1", "Chuva de Arroz", "Luan Santana")]}, sugestoes={
            "Chuva de Arroz Luan Santana": [("v1", "Chuva de Arroz (Ao Vivo)", "Song • Luan Santana • 90M plays")],
            "Chuva de Arroz ao vivo": [("v1", "Chuva de Arroz (Ao Vivo)", "Song • Luan Santana • 90M plays")]})
        self.assertEqual(yt_fora.musica("Chuva de Arroz Luan Santana", 3, y)[0]["youtube_id"], "e1", "a de estudio")
        self.assertEqual(yt_fora.musica("Chuva de Arroz ao vivo", 3, y)[0]["youtube_id"], "v1", "pediu ao vivo")
        self.assertTrue(yt_fora.versao_a_mais("x", "Dilatação Hipnótica 5.0 (Slowed)"))
        self.assertFalse(yt_fora.versao_a_mais("x", "Living on a Prayer"), "palavra inteira: 'live' nao casa 'living'")

    def test_album_nao_e_artista(self):
        artistas, musicas = yt_fora.sugestoes("x", YtmFalso({}, sugestoes={"x": [
            sug_musica("p1", "Pop 100", "O Rei da Cacimbinha", "UC9")]}))
        self.assertEqual(artistas, [("O Rei da Cacimbinha", "UC9")], "o link do album (MPREb) fica de fora")
        self.assertEqual(musicas, [{"youtube_id": "p1", "title": "Pop 100", "channel": "O Rei da Cacimbinha"}])

    def test_song_que_nao_bate_vai_a_busca(self):
        y = YtmFalso(self.busca(), sugestoes={"uma rapariga e bom demais": [
            ("s4", "Raparigas", "Song • Filho do Piseiro • 19M plays")]})
        self.assertEqual(yt_fora.musica("uma rapariga e bom demais", 3, y)[0]["youtube_id"], "v3")

    def test_sem_sugestao_vai_a_busca(self):
        y = YtmFalso(self.busca())
        self.assertEqual(yt_fora.musica("cheia de manias", 3, y)[0]["youtube_id"], "v1")

    def test_outra_e_desligado_nao_usam(self):
        sug = {"cheia de manias": [("s1", "Cheia de Manias", "Song • Raça Negra • 168M plays")]}
        y = YtmFalso(self.busca(), sugestoes=sug)
        self.assertEqual(yt_fora.musica("cheia de manias", 8, y)[0]["youtube_id"], "v1", "o outra quer a lista")
        with unittest.mock.patch.object(yt_fora, "SUGESTAO", False):
            self.assertEqual(yt_fora.musica("cheia de manias", 3, YtmFalso(self.busca(), sugestoes=sug))[0]
                             ["youtube_id"], "v1")


class YtmLento(YtmFalso):
    """O falso com o tempo da rede: a sugestao e a busca demoram; a busca pode falhar."""

    def __init__(self, *a, t_sug=0.3, t_busca=0.3, busca_falha=False, **kw):
        super().__init__(*a, **kw)
        self.t_sug, self.t_busca, self.busca_falha = t_sug, t_busca, busca_falha

    def _send_request(self, endpoint, corpo):
        time.sleep(self.t_sug)
        return super()._send_request(endpoint, corpo)

    def search(self, q, limit=10):
        self.pediu.append(("search", q))
        time.sleep(self.t_busca)
        if self.busca_falha:
            raise RuntimeError("a busca caiu")
        return self.busca.get(q, [])


LONGO = "Pedro e Joilson Ai Ui"  # 4 palavras
ACHADA = [musica("p1", "Aí Ui Aí Ui", "Pedro E Joilson")]
SUGERIDA = ("s1", "Ai Ui", "Song • Pedro E Joilson • 1M plays")


class Paralelo(unittest.TestCase):
    """A busca junto da sugestao no pedido longo (PARALELO_PALAVRAS, r13)."""

    def test_a_busca_sai_junto_no_pedido_longo(self):
        y = YtmLento({LONGO: ACHADA})
        t0 = time.monotonic()
        r = yt_fora.musica(LONGO, 3, y)
        self.assertEqual(r[0]["youtube_id"], "p1")
        self.assertLess(time.monotonic() - t0, 0.5, "0,3 s de sugestao e 0,3 de busca, ao mesmo tempo")

    def test_a_sugestao_que_acerta_vale_e_nao_espera_a_busca(self):
        y = YtmLento({LONGO: ACHADA}, sugestoes={LONGO: [SUGERIDA]}, t_sug=0.05, t_busca=1.0)
        t0 = time.monotonic()
        self.assertEqual(yt_fora.musica(LONGO, 3, y)[0]["youtube_id"], "s1")
        self.assertLess(time.monotonic() - t0, 0.5)

    def test_o_pedido_curto_busca_depois(self):
        y = YtmLento({"Ai Ui": ACHADA}, sugestoes={"Ai Ui": [SUGERIDA]}, t_sug=0.05)
        self.assertEqual(yt_fora.musica("Ai Ui", 3, y)[0]["youtube_id"], "s1")
        self.assertEqual(y.pediu, [("sugestao", "Ai Ui")], "2 palavras: a sugestao acertou, sem busca")

    def test_o_erro_da_busca_so_conta_quando_ela_vale(self):
        y = YtmLento({}, sugestoes={LONGO: [SUGERIDA]}, t_sug=0.05, t_busca=0.05, busca_falha=True)
        self.assertEqual(yt_fora.musica(LONGO, 3, y)[0]["youtube_id"], "s1")
        with self.assertRaisesRegex(RuntimeError, "a busca caiu"):
            yt_fora.musica(LONGO, 3, YtmLento({}, t_sug=0.05, t_busca=0.05, busca_falha=True))

    def test_desligado_a_busca_depois_da_sugestao(self):
        y = YtmLento({LONGO: ACHADA}, t_sug=0.05, t_busca=0.05)
        with unittest.mock.patch.object(yt_fora, "PARALELO_PALAVRAS", 0):
            self.assertEqual(yt_fora.musica(LONGO, 3, y)[0]["youtube_id"], "p1")
        self.assertEqual(y.pediu, [("sugestao", LONGO), ("search", LONGO)])

    def test_o_processo_sai_sem_esperar_a_busca_jogada_fora(self):
        """O servidor le a saida da reserva ate o processo fechar: a busca que ficou para tras nao segura a saida."""
        filho = f'''
import sys, time
sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})
sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
import yt_fora, testa_musica as t
yt_fora.aquece_ytm = lambda: None
y = t.YtmLento({{}}, sugestoes={{t.LONGO: [t.SUGERIDA]}}, t_sug=0.05, t_busca=5.0)
yt_fora.ytm = lambda: y
yt_fora.main()
'''
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, "-c", filho], input=json.dumps({"op": "musica", "q": LONGO, "n": 3}) + "\n",
                           capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(json.loads(r.stdout.splitlines()[0])["r"][0]["youtube_id"], "s1", r.stderr)
        self.assertLess(time.monotonic() - t0, 3.5, "a busca de 5 s ficou para tras sem segurar o processo")

    def test_pre_conecta(self):
        solta = threading.Event()

        class Conexao:
            def __init__(self, ligada):
                self.is_connected = ligada

            def connect(self):
                solta.wait(5)
                self.is_connected = True

            def close(self):
                pass

        class Pool:
            proxy = None

            def __init__(self):
                self.fila = [Conexao(True)]  # a do visitor id

            def _get_conn(self):
                return (self.fila.pop() if self.fila else None) or Conexao(False)

            def _put_conn(self, c):
                self.fila.append(c)
        pool = Pool()
        adaptador = types.SimpleNamespace(get_connection_with_tls_context=lambda req, verify, proxies, cert: pool)
        sessao = types.SimpleNamespace(verify=True, cert=None, get_adapter=lambda url: adaptador,
                                       merge_environment_settings=lambda url, p, s, v, c: {
                                           "verify": v, "proxies": p, "cert": c})
        th = threading.Thread(target=yt_fora.pre_conecta, args=(types.SimpleNamespace(_session=sessao, proxies=None),))
        th.start()
        time.sleep(0.2)  # a nova no meio do aperto de mao
        self.assertEqual([c.is_connected for c in pool.fila], [True], "a quente ja voltou ao pool (revisao da r13)")
        solta.set()
        th.join()
        self.assertEqual([c.is_connected for c in pool.fila], [True, True], "duas abertas, as duas de volta ao pool")
        yt_fora.pre_conecta(types.SimpleNamespace(_session=None, proxies=None))  # falhou: so o log, sem erro

    def test_liga_que_falha_nao_estraga_o_pool(self):
        """Pool de verdade do urllib3 contra um servidor local que fecha no meio do aperto de mao: o pedido seguinte
        pega um lugar vazio e abre a dele, sem o "file descriptor cannot be a negative integer" (revisao da r13)."""
        import socket
        import urllib3
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)

        def fecha():
            for _ in range(2):
                try:
                    c, _ = srv.accept()
                    c.close()
                except OSError:
                    return
        threading.Thread(target=fecha, daemon=True).start()
        pool = urllib3.HTTPSConnectionPool("127.0.0.1", srv.getsockname()[1], maxsize=2)
        try:
            with self.assertRaises(Exception):
                yt_fora.liga(pool, 2)
            for _ in range(2):
                c = pool._get_conn()  # antes quebrava aqui
                self.assertFalse(c.is_connected)
        finally:
            srv.close()

    def test_liga_com_proxy_nao_conecta(self):
        """Com proxy o connect cru pulava o CONNECT do tunel: nada se abre (revisao da r13)."""
        import urllib3
        pool = urllib3.ProxyManager("http://127.0.0.1:9").connection_from_url("https://music.youtube.com/")
        yt_fora.liga(pool, 2)
        self.assertEqual(pool.num_connections, 0)


class Aquece(unittest.TestCase):
    """O "aquece" do processo (yt_fora.aquece e responde, r14): no vivo, o YoutubeDL do endereco com a mesma chave do
    faz e um HEAD no www.youtube.com; na reserva, as conexoes do YouTube Music trocadas por novas; nao responde nada."""

    def test_no_vivo_o_youtubedl_do_endereco_e_o_head(self):
        pedidos, chaves = [], []
        ydl = types.SimpleNamespace(urlopen=lambda req: pedidos.append((req.method, req.url)) or
                                    types.SimpleNamespace(read=lambda: pedidos.append("leu") or b"",
                                                          close=lambda: pedidos.append("fechou")))
        with unittest.mock.patch.object(yt_fora, "_ydl", lambda o: chaves.append(o) or ydl), \
                unittest.mock.patch.object(yt_fora, "opts_rapido", lambda o: {**o, "rapido": 1}), \
                unittest.mock.patch.object(yt_fora, "_rapido_falhas", 0):
            yt_fora.aquece({"opts": {"format": "bestaudio"}, "rapido": True})
        self.assertEqual(pedidos, [("HEAD", "https://www.youtube.com/robots.txt"), "leu", "fechou"],
                         "lida antes de fechar: a conexao volta ao pool")
        self.assertEqual(chaves, [{"format": "bestaudio", "logtostderr": True, "rapido": 1}],
                         "as mesmas opts que o faz monta para o stream rapido")

    def test_no_vivo_com_o_rapido_desligado(self):
        chaves = []
        ydl = types.SimpleNamespace(urlopen=lambda req: types.SimpleNamespace(read=lambda: b"", close=lambda: None))
        with unittest.mock.patch.object(yt_fora, "_ydl", lambda o: chaves.append(o) or ydl), \
                unittest.mock.patch.object(yt_fora, "_rapido_falhas", yt_fora.RAPIDO_FALHAS_MAX):
            yt_fora.aquece({"opts": {"format": "bestaudio"}, "rapido": True})
        self.assertEqual(chaves, [{"format": "bestaudio", "logtostderr": True}])

    def test_na_reserva_as_conexoes_novas(self):
        chamou = []
        cli = object()
        with unittest.mock.patch.object(yt_fora, "ytm", lambda: cli), \
                unittest.mock.patch.object(yt_fora, "pre_conecta", lambda yt, n=2, fresca=False:
                                           chamou.append((yt, n, fresca))):
            yt_fora.aquece({})
        self.assertEqual(chamou, [(cli, 2, True)])

    def test_liga_fresca_troca_as_paradas(self):
        class Conexao:
            def __init__(self):
                self.is_connected, self.ligou, self.fechou = True, 0, 0

            def close(self):
                self.is_connected, self.fechou = False, self.fechou + 1

            def connect(self):
                self.is_connected, self.ligou = True, self.ligou + 1
        velhas = [Conexao(), Conexao()]
        pool = types.SimpleNamespace(proxy=None, fila=list(velhas))
        pool._get_conn = lambda: pool.fila.pop()
        pool._put_conn = pool.fila.append
        yt_fora.liga(pool, 2, fresca=True)
        self.assertEqual([(c.fechou, c.ligou, c.is_connected) for c in velhas], [(1, 1, True)] * 2)

    def test_responde_nao_escreve_nada(self):
        saida = []
        with unittest.mock.patch.object(yt_fora, "aquece", lambda p: saida.append("aqueceu")), \
                unittest.mock.patch("builtins.print", lambda *a, **kw: saida.append(a)):
            self.assertFalse(yt_fora.responde(json.dumps({"op": "aquece"})))
        self.assertEqual(saida, ["aqueceu"])

        def falha(p):
            raise RuntimeError("sem rede")
        saida.clear()
        with unittest.mock.patch.object(yt_fora, "aquece", falha), \
                unittest.mock.patch("builtins.print", lambda *a, **kw: saida.append(kw.get("file"))):
            self.assertFalse(yt_fora.responde(json.dumps({"op": "aquece"})))
        self.assertEqual(saida, [sys.stderr], "a falha vai so para o log, nada na saida que o servidor le")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
