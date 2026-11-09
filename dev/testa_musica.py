"""Testa a busca de musica do YouTube Music (yt_fora.musica, a rota /api/musica) sem a internet: um YouTube Music de
mentira devolve a busca e a pagina do artista. Cobre o pedido que e so o nome do artista (a mais tocada dele, com a
escrita errando um pouco e as iniciais com ponto), o pedido com o nome da musica junto (a musica, sem abrir a pagina do
artista), o video entrando e o que nao e musica nem video ficando de fora. Sai 1 se algo falhar.

    python dev/testa_musica.py
"""
import sys
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
        for yid, titulo, segunda in self.sugestoes.get(corpo["input"], []):
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

    def test_video_na_frente_vai_a_busca(self):
        y = YtmFalso(self.busca(), sugestoes={"alors on danse": [
            ("s2", "Stromae - Alors On Dance (Dubdogz Remix)", "Video • 3.8M views"),
            ("s3", "Alors on danse", "Song • Stromae • 900M plays")]})
        self.assertEqual(yt_fora.musica("alors on danse", 3, y)[0]["youtube_id"], "v2")

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


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
