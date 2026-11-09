"""Testa o stream aberto antes (engine.Preaberto, Engine.preabre e _pre_pega) com o ffmpeg de verdade, sem o YouTube: o
aberto antes guarda o comeco e o resto continua do mesmo ffmpeg, igual ao ffmpeg novo (um wav local: o servidor http
do Python no Windows corta o stream no meio e, sem Range, o reconecta do comeco); uma vez so; vence em PRE_VALE_S;
PRE_MAX fecha o mais velho; PREABRE = False nao abre; endereco que nao e http nao abre (esses pelo servidor http local,
onde o conteudo nao importa). Sai 1 se algo falhar.

    python dev/testa_preabre.py
"""
import functools
import http.server
import io
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as eng  # noqa: E402


def _servidor(pasta):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=pasta)
    h.log_message = lambda *a: None
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def _decodifica(url):
    r = subprocess.run([eng.FFMPEG, "-v", "error", "-ss", "0.0", "-i", str(url), "-f", "f32le", "-ac", "2",
                        "-ar", str(eng.SR), "-"], capture_output=True, creationflags=eng.NO_WINDOW)
    return r.stdout


class Preabre(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        x = (np.sin(np.arange(eng.SR * 5) * 2 * np.pi * 440 / eng.SR) * 8000).astype(np.int16)  # 5 s
        for nome in ("a.wav", "b.wav", "c.wav"):
            with wave.open(str(Path(cls.dir.name) / nome), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(eng.SR)
                w.writeframes(x.tobytes())
        cls.srv = _servidor(cls.dir.name)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}/"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.dir.cleanup()

    def setUp(self):
        self.e = eng.Engine.__new__(eng.Engine)
        self.e._preabertos, self.e._pre_lock = {}, threading.Lock()

    def tearDown(self):
        for p in list(self.e._preabertos.values()):
            p.fecha()

    def _espera_cheio(self, url):
        p = self.e._preabertos[url]
        for _ in range(100):
            if not p._th.is_alive():
                return p
            time.sleep(0.05)
        self.fail("o aberto antes nao encheu")

    def test_o_comeco_e_o_resto_igual_ao_ffmpeg_novo(self):
        arq = Path(self.dir.name) / "a.wav"
        p = eng.Preaberto(str(arq), [])
        for _ in range(100):
            if not p._th.is_alive():
                break
            time.sleep(0.05)
        self.assertGreaterEqual(sum(map(len, p.blocos)), int(eng.PRE_S * eng.SR) * 8, "guardou PRE_S")
        blocos, ff = p.pega()
        resto = ff.stdout.read()
        ff.wait(timeout=5)
        self.assertEqual(b"".join(blocos) + resto, _decodifica(arq))
        self.assertIsNone(p.pega(), "uma vez so")

    def test_pega_no_meio_da_leitura(self):
        arq = Path(self.dir.name) / "b.wav"
        with mock.patch.object(eng, "PRE_S", 60.0):  # nao para de ler: o pega para a thread no meio
            p = eng.Preaberto(str(arq), [])
            time.sleep(0.05)
            blocos, ff = p.pega()
        resto = ff.stdout.read()
        ff.wait(timeout=5)
        self.assertEqual(b"".join(blocos) + resto, _decodifica(arq))

    def test_pelo_registro(self):
        url = self.base + "a.wav"
        self.assertTrue(self.e.preabre(url))
        self.assertFalse(self.e.preabre(url), "o mesmo endereco abre uma vez")
        x = self.e._pre_pega(url)
        self.assertIsNotNone(x)
        x[1].kill()
        x[1].wait(timeout=5)
        self.assertIsNone(self.e._pre_pega(url), "uma vez so")

    def test_vence(self):
        url = self.base + "a.wav"
        with mock.patch.object(eng, "PRE_VALE_S", 0.3):
            self.e.preabre(url)
        p = self.e._preabertos[url]
        time.sleep(0.8)
        self.assertTrue(p.morto)
        self.assertIsNotNone(p.ff.poll(), "o ffmpeg fechou")
        self.assertIsNone(self.e._pre_pega(url))

    def test_pre_max_fecha_o_mais_velho(self):
        a, b, c = (self.base + n for n in ("a.wav", "b.wav", "c.wav"))
        self.e.preabre(a)
        pa = self.e._preabertos[a]
        self.e.preabre(b)
        self.e.preabre(c)
        self.assertEqual(list(self.e._preabertos), [b, c])
        self.assertTrue(pa.morto)

    def test_desligado_e_nao_http(self):
        with mock.patch.object(eng, "PREABRE", False):
            self.assertFalse(self.e.preabre(self.base + "a.wav"))
        self.assertFalse(self.e.preabre(str(Path(self.dir.name) / "a.wav")))
        self.assertEqual(self.e._preabertos, {})


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
