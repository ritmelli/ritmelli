"""Testa as vozes do pedal de troca de voz (#129) sem rede e sem placa de video: o vozes.json (as releases do
ritmelli-voices que esta versao usa: cada voz com os dois modelos, o voz.json e a licenca; a engine com os modelos dela;
nome e sha256 no formato), o vozes.iss que o instalador/vozes_iss.py gera (uma copia por arquivo, com o Check de cada
um, e a lista que o [Code] baixa) e o texto da licenca da pagina de aceite, o python dev/vozes.py baixa (o arquivo com
o sha256 certo fica e nao baixa de novo, o que chega com outro hash nao vira arquivo) e o impedimento() do pistavoz.py
(sem placa de video, ou sem os modelos inteiros, o motivo; com os dois, None).

    python dev/testa_vozes.py

So a biblioteca padrao. Sai 1 se algo falhar."""
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "dev"))
sys.path.insert(0, str(RAIZ / "instalador"))
import pistavoz
import vozes
import vozes_iss

M = json.loads((RAIZ / "vozes.json").read_text(encoding="utf-8"))


class Manifesto(unittest.TestCase):
    def test_formato(self):
        self.assertEqual(M["repo"], "ritmelli/ritmelli-voices")
        rels = [M["engine"], *M["vozes"]]
        self.assertEqual(len({r["tag"] for r in rels}), len(rels))
        for r in rels:
            for a in r["arquivos"]:
                self.assertRegex(a["sha256"], r"^[0-9a-f]{64}$", a["nome"])
                self.assertGreater(a["tamanho"], 0, a["nome"])
        nomes = {a["nome"] for a in M["engine"]["arquivos"]}
        for n in ("fcpe_fp16.onnx", "ref.npz", "meta.json"):
            self.assertIn(n, nomes)
        self.assertTrue(any(re.fullmatch(r"contentvec_n\d+_fp16\.onnx", n) for n in nomes))

    def test_cada_voz(self):
        self.assertEqual(pistavoz.VOZES, [v["id"] for v in M["vozes"]])
        self.assertGreaterEqual(len(pistavoz.VOZES), 2, "o pedal mostra duas vozes")
        for v in M["vozes"]:
            nomes = {a["nome"] for a in v["arquivos"]}
            self.assertIn("LICENSE.md", nomes, v["tag"])
            self.assertIn("voz.json", nomes, v["tag"])
            self.assertTrue(any(n.endswith("_encp_q334_fp16.onnx") for n in nomes), v["tag"])
            self.assertTrue(any(re.search(r"_dec_q\d+_fp16\.onnx$", n) for n in nomes), v["tag"])
            self.assertFalse(any(n.endswith(".pth") for n in nomes), "o modelo de treino nao vai para o app")


class Instalador(unittest.TestCase):
    def test_vozes_iss(self):
        t = vozes_iss.iss(M)
        rels = [M["engine"], *M["vozes"]]
        n = sum(len(r["arquivos"]) for r in rels)
        copias = [linha for linha in t.splitlines() if linha.startswith("Source: ")]
        self.assertEqual(len(copias), n)
        for linha in copias:
            self.assertRegex(linha, r'^Source: "\{tmp\}\\vozes-[^"]+"; DestName: "[^"]+"; DestDir: "\{app\}\\vozes\\[^"]+"; '
                                    r"ExternalSize: \d+; Flags: external ignoreversion; Check: FaltaVoz\('[^']+', '[0-9a-f]{64}'\)$")
        lista = re.search(r'#define VozesLista "([^"]+)"', t).group(1).split(";")
        self.assertEqual(lista, [f"{r['tag']}|{a['nome']}|{a['sha256']}" for r in rels for a in r["arquivos"]])
        self.assertIn(f'#define VozesTags "|{"|".join(r["tag"] for r in rels)}|"', t)
        self.assertIn(f'#define VozesRepo "{M["repo"]}"', t)

    def test_nome_estranho_recusado(self):
        ruim = json.loads(json.dumps(M))
        ruim["vozes"][0]["arquivos"][0]["nome"] = "x'; DelTree"
        with self.assertRaises(SystemExit):
            vozes_iss.iss(ruim)

    def test_texto_da_licenca(self):
        self.assertEqual(vozes_iss.texto("# Titulo\n\n## 1. Parte\n- **Voz:** a Mina\n"), "Titulo\n\n1. Parte\n- Voz: a Mina\n")


class Baixa(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dados = {"a.onnx": b"modelo" * 100, "voz.json": b'{"tom_hz": 239}\n'}
        self.m = {"repo": "x/y", "engine": {"tag": "engine-v0", "arquivos": [self._arq("a.onnx")]},
                  "vozes": [{"id": "v", "tag": "v-v0", "arquivos": [self._arq("voz.json")]}]}
        self.pedidos = []

    def tearDown(self):
        self.tmp.cleanup()

    def _arq(self, nome):
        b = self.dados[nome]
        return {"nome": nome, "tamanho": len(b), "sha256": hashlib.sha256(b).hexdigest()}

    def _abre(self, url):
        self.pedidos.append(url)
        return io.BytesIO(self.servido.get(url.rsplit("/", 1)[1], b""))

    def test_baixa_confere_e_nao_repete(self):
        self.servido = dict(self.dados)
        with mock.patch.object(vozes, "_abre", self._abre):
            self.assertEqual(vozes.baixa(self.tmp.name, self.m), 2)
            self.assertEqual((Path(self.tmp.name) / "v-v0" / "voz.json").read_bytes(), self.dados["voz.json"])
            self.assertIn("https://github.com/x/y/releases/download/engine-v0/a.onnx", self.pedidos)
            self.pedidos.clear()
            self.assertEqual(vozes.baixa(self.tmp.name, self.m), 0, "com o hash certo, fica")
            self.assertEqual(self.pedidos, [])

    def test_hash_errado_nao_vira_arquivo(self):
        self.servido = dict(self.dados, **{"voz.json": b'{"tom_hz": 999}\n'})
        with mock.patch.object(vozes, "_abre", self._abre), self.assertRaises(SystemExit):
            vozes.baixa(self.tmp.name, self.m)
        pasta = Path(self.tmp.name) / "v-v0"
        self.assertEqual(list(pasta.iterdir()), [], "nem o arquivo, nem o .parte")


class Impedimento(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = {"repo": "x/y", "engine": {"tag": "e", "arquivos": [{"nome": "c.onnx", "tamanho": 5, "sha256": "0" * 64}]},
                  "vozes": [{"id": "mina", "tag": "m", "arquivos": [{"nome": "d.onnx", "tamanho": 3, "sha256": "0" * 64}]}]}
        self.patches = [mock.patch.object(pistavoz, "MANIFESTO", self.m),
                        mock.patch.object(pistavoz, "MODELOS", Path(self.tmp.name))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _poe(self, tag, nome, n):
        (Path(self.tmp.name) / tag).mkdir(exist_ok=True)
        (Path(self.tmp.name) / tag / nome).write_bytes(b"x" * n)

    def test_sem_placa(self):
        with mock.patch.object(pistavoz, "placas", lambda: []):
            self.assertIn("no graphics card", pistavoz.impedimento())

    def test_sem_modelos_ou_pela_metade(self):
        with mock.patch.object(pistavoz, "placas", lambda: ["Placa"]):
            self.assertIn("2 voice files missing", pistavoz.impedimento())
            self._poe("e", "c.onnx", 5)
            self._poe("m", "d.onnx", 2)  # o download interrompido
            self.assertIn("1 voice files missing or incomplete", pistavoz.impedimento())
            self._poe("m", "d.onnx", 3)
            self.assertIsNone(pistavoz.impedimento())

    def test_adaptador_de_verdade(self):
        def a(fab, flags):
            return SimpleNamespace(VendorId=fab, Flags=flags)
        self.assertTrue(pistavoz.de_verdade(a(0x10DE, 0)))  # NVIDIA
        self.assertTrue(pistavoz.de_verdade(a(0x1002, 0)))  # AMD
        self.assertFalse(pistavoz.de_verdade(a(0x1414, 2)))  # o Basic Render Driver com a marca de software
        self.assertFalse(pistavoz.de_verdade(a(0x1414, 0)))  # e sem ela, como na maquina do GitHub
        self.assertFalse(pistavoz.de_verdade(a(0x8086, 2)))  # qualquer adaptador de software

    def test_placas_de_verdade(self):
        p = pistavoz.placas()  # sem placa (a maquina do GitHub), lista vazia; nunca um adaptador do Windows
        print(f"placas: {p}")
        self.assertIsInstance(p, list)
        self.assertFalse(any(n.startswith("Microsoft ") for n in p))


if __name__ == "__main__":
    unittest.main(verbosity=2)
