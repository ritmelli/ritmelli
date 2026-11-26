"""Testa o volume automatico (sonoridade.py e o motor) sem som: arquivos wav de mentira, o ffmpeg de verdade, o leitor
e o misturador do motor (Engine._mixa chamado na mao, como no dev/testa_microfone.py) e um servidor http local no
papel do stream do YouTube.

Confere: a medida (LUFS integrado) bate com o caso de teste da EBU (seno de 1 kHz a -23 dBFS = -23 LUFS) e com o
ebur128 do ffmpeg, igual em qualquer tamanho de pedaco; o ganho leva ao alvo (a alta desce, a baixa sobe ate o teto); o
limitador nunca deixa o que o ganho acrescentou passar de 0 dBFS, e o disco sem ganho sai igual, so atrasado (mesmo o
que ja passa de 0 dBFS); no motor, a musica baixa sai com o ganho e o atraso do limitador, a alta desce, o desligar
desce em rampa, o arquivo sem medida e medido e guardado, o stream e estimado no comeco e medido inteiro no fim, e o eco
da passagem leva o ganho do disco que saiu.

    python dev/testa_ganho.py

Sai 1 se algo falhar.
"""
import contextlib
import functools
import http.server
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as eng  # noqa: E402
import sonoridade as so  # noqa: E402

SR, B, D = so.SR, eng.BLOCK, so.LIMITE_ANTES


def grava(p, x):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        q = np.round(np.clip(x, -1, 32767 / 32768) * 32768)
        w.writeframes(q.astype(np.int16).tobytes())
    return q.astype(np.float32) / 32768  # o que o ffmpeg devolve


def musica(seg, nivel_db, picos=0.0, semente=1):
    """Ruido rosado estereo no nivel (dBFS de RMS), com um estalo de pico `picos` a cada 0,7 s."""
    rng = np.random.default_rng(semente)
    n = int(seg * SR)
    f = np.fft.rfftfreq(n, 1 / SR)
    x = np.stack([np.fft.irfft(np.fft.rfft(rng.standard_normal(n)) / np.sqrt(np.maximum(f, 20)), n) for _ in (0, 1)], 1)
    x *= 10 ** (nivel_db / 20) / np.sqrt(np.mean(x ** 2))
    if picos:
        for i in range(int(0.3 * SR), n - 100, int(0.7 * SR)):
            x[i:i + 48] = picos * np.sign(x[i:i + 48] + 1e-9)
    return x


def lufs(x):
    m = so.Medidor()
    m(x)
    return m.lufs()


class TestaMedida(unittest.TestCase):
    def test_seno_da_ebu(self):
        t = np.arange(20 * SR) / SR
        s = 10 ** (-23 / 20) * np.sin(2 * np.pi * 1000 * t)
        self.assertAlmostEqual(lufs(np.stack([s, s], 1)), -23.0, delta=0.1)

    def test_pedacos(self):
        x = musica(12, -18)
        m = so.Medidor()
        i = 0
        for k in (7, 480, 4799, 12345, 1) * 1000:
            if i >= len(x):
                break
            m(x[i:i + k])
            i += k
        self.assertAlmostEqual(m.lufs(), lufs(x), places=9)

    def test_contra_o_ffmpeg(self):
        with tempfile.TemporaryDirectory() as d:
            for nivel in (-30, -18, -8):
                x = grava(Path(d) / "m.wav", musica(10, nivel))
                ff = so.mede_arquivo(Path(d) / "m.wav", eng.FFMPEG)
                self.assertIsNotNone(ff)
                self.assertAlmostEqual(lufs(x), ff, delta=0.1, msg=f"{nivel} dBFS")

    def test_silencio_e_arquivo_ruim(self):
        with tempfile.TemporaryDirectory() as d:
            grava(Path(d) / "s.wav", np.zeros((SR * 2, 2)))
            self.assertIsNone(so.mede_arquivo(Path(d) / "s.wav", eng.FFMPEG))
            (Path(d) / "ruim.wav").write_bytes(b"nao e audio")
            self.assertIsNone(so.mede_arquivo(Path(d) / "ruim.wav", eng.FFMPEG))
            self.assertIsNone(lufs(np.zeros((SR, 2))))

    def test_ganho(self):
        self.assertEqual(so.ganho_db(None), 0.0)
        self.assertAlmostEqual(so.ganho_db(so.ALVO + 3), -3.0)  # a alta desce ate o alvo, como no Spotify
        self.assertAlmostEqual(so.ganho_db(so.ALVO + 9.5), -9.5)  # sem limite para descer
        self.assertAlmostEqual(so.ganho_db(so.ALVO - 2.5), 2.5)
        self.assertEqual(so.ganho_db(so.ALVO - 20), so.TETO)


class TestaLimitador(unittest.TestCase):
    def roda(self, som, cru, blocos):
        lim, out, i = so.Limitador(), [], 0
        for k in blocos:
            if i >= len(som):
                break
            out.append(lim(som[i:i + k], None if cru is None else cru[i:i + k]))
            i += k
        return np.concatenate(out)

    def test_teto_e_atraso(self):
        cru = musica(6, -14, picos=0.95).astype(np.float32)
        cru[SR:SR + 10] = 1.3  # um pico acima de 0 dBFS ja no disco
        g = np.where(np.arange(len(cru)) < len(cru) // 2, 2.0, 1.0)[:, None].astype(np.float32)
        a = self.roda(cru * g, cru, [B] * 2000)
        teto = np.maximum(1.0, np.max(np.abs(cru), axis=1))
        sai = np.max(np.abs(a[D:]), axis=1)
        self.assertTrue(np.all(sai <= teto[:len(sai)] + 1e-6), "o ganho levou o pico acima de 0 dBFS")
        self.assertGreaterEqual(float(sai[SR:SR + 10].max()), 1.299, "o pico que o disco ja tinha ficou")
        meio = len(cru) // 2 + SR
        self.assertTrue(np.array_equal(a[meio:], cru[meio - D:len(a) - D]), "sem ganho, o disco sai igual e atrasado")
        b = self.roda(cru * g, cru, [7, 333, B, 1, 1000] * 3000)[:len(a)]
        self.assertLess(float(np.max(np.abs(a - b))), 1e-6, "o tamanho do bloco muda a saida")

    def test_sem_ganho_nada_muda(self):
        cru = (musica(3, -8, picos=1.4)).astype(np.float32)  # decodificado acima de 0 dBFS, como muita musica alta
        a = self.roda(cru, None, [B] * 1000)
        self.assertTrue(np.array_equal(a[D:], cru[:len(a) - D]))


@contextlib.contextmanager
def servidor(pasta):
    h = functools.partial(_Quieto, directory=str(pasta))
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{s.server_address[1]}"
    finally:
        s.shutdown()


class _Quieto(http.server.SimpleHTTPRequestHandler):
    """Serve com Range, como o YouTube: o leitor do motor abre com -ss e o ffmpeg pede o audio depois do cabecalho
    (sem Range ele recebia o arquivo do comeco e decodificava desalinhado)."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        dados = (Path(self.directory) / self.path.lstrip("/")).read_bytes()
        ini = 0
        r = (self.headers.get("Range") or "").removeprefix("bytes=").split("-")[0]
        if r.isdigit():
            ini = int(r)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {ini}-{len(dados) - 1}/{len(dados)}")
        else:
            self.send_response(200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(dados) - ini))
        self.end_headers()
        with contextlib.suppress(OSError):
            self.wfile.write(dados[ini:])


class TestaMotor(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.pasta = Path(self.dir.name)
        self.medidos = []
        self.e = eng.Engine(mic="x", monitor="")
        self.e.vol, self.e.monitor_on = 1.0, False
        self.e.sonoridade_de = lambda tr: None
        self.e.mediu = lambda tr, v: self.medidos.append((tr.get("id"), v))

    def tearDown(self):
        self.e.stop()
        time.sleep(0.2)
        self.dir.cleanup()

    def espera(self, cond, limite=15.0):
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def toca(self, blocos):
        """blocos chamadas do _mixa, cada uma so com o disco ja decodificado adiante (o leitor no ritmo dele)."""
        out = []
        for _ in range(blocos):
            self.espera(lambda: len(self.e._q) > 2 or self.e._eof_gen == self.e._gen, 5)
            out.append(self.e._mixa(B))
        return np.concatenate(out)

    def disco(self, x, **kw):
        p = self.pasta / f"{kw.get('id', 'd')}.wav"
        y = grava(p, x)
        return dict({"id": "d", "title": "disco", "path": str(p), "duration": len(x) / SR}, **kw), y

    def test_baixa_sobe_alta_desce(self):
        tr, y = self.disco(musica(4, -24, picos=0.7), id="baixa", lufs=-24.0)
        self.e.load(tr)
        a = self.toca(300)
        g = 10 ** (so.ganho_db(-24.0) / 20)
        self.assertAlmostEqual(self.e.snapshot()["ganho_db"], so.TETO, places=1)
        ref = y[:len(a) - D] * g
        livre = np.ones(len(ref), bool)  # longe dos estalos: o limitador so mexe ate 150 ms depois deles
        for i in range(int(0.3 * SR), len(ref), int(0.7 * SR)):
            livre[max(0, i - D):i + int(0.2 * SR)] = False
        self.assertLess(float(np.max(np.abs(a[D:][livre] - ref[livre]))), 1e-5, "a baixa nao saiu com o ganho")
        self.assertLessEqual(float(np.max(np.abs(a))), 1.0 + 1e-6)
        # em LUFS sobe quase o teto: o limitador segura os estalos (um forte a cada 0,7 s, o pior caso), e com o teto
        # de +9 dB eles custam ~1,1 dB; musica de verdade perde bem menos (a Vanessa da Mata, a +8,2, limita mais de
        # 1 dB em 1,8% do tempo)
        self.assertGreater(lufs(a[D:]) - lufs(y[:len(a) - D]), so.TETO - 1.5)
        self.e.stop()
        tr, y = self.disco(musica(4, -8, picos=0.99), id="alta", lufs=-8.0)
        self.e.load(tr)
        a = self.toca(300)
        g = 10 ** (so.ganho_db(-8.0) / 20)
        self.assertAlmostEqual(self.e.snapshot()["ganho_db"], so.ALVO + 8.0, places=1)
        # a alta desce o ganho exato, sem o limitador mexer (nada passa de onde o disco ja ia)
        self.assertLess(float(np.max(np.abs(a[D:] - y[:len(a) - D] * np.float32(g)))), 1e-6, "a alta nao desceu")

    def test_desligar_desce_em_rampa(self):
        tr, y = self.disco(musica(6, -24), id="baixa", lufs=-24.0)
        self.e.load(tr)
        a = self.toca(100)
        self.e.volume_auto = False
        b = self.toca(300)  # a rampa de 6 dB/s desce o teto todo em 1,5 s; o ultimo 1 s ja e o disco
        x = np.concatenate([a, b])
        k = (len(x) - D) // B * B
        rb = np.sqrt(np.mean(x[D:D + k].reshape(-1, B, 2) ** 2, axis=(1, 2)) /
                     np.mean(y[:k].reshape(-1, B, 2) ** 2, axis=(1, 2)))
        db = 20 * np.log10(rb)
        self.assertAlmostEqual(db[50], so.TETO, delta=0.1)
        self.assertLess(float(np.max(np.abs(np.diff(db)))), 0.1, "o desligar pulou de uma vez")
        fim = y[len(x) - 100 * B - D:len(x) - D]
        self.assertTrue(np.array_equal(x[-100 * B:], fim), "desligado, nao voltou ao disco")
        self.assertEqual(self.e.snapshot()["volume_auto"], False)

    def test_arquivo_sem_medida(self):
        tr, y = self.disco(musica(5, -20), id="nova")
        self.e.load(tr)
        self.assertTrue(self.espera(lambda: self.medidos), "o arquivo nao foi medido")
        self.assertEqual(self.medidos[0][0], "nova")
        self.assertAlmostEqual(self.medidos[0][1], lufs(y), delta=0.1)
        self.assertAlmostEqual(20 * np.log10(self.e._deck.ganho_alvo), so.ganho_db(self.medidos[0][1]), places=6)
        self.toca(150)  # 1,5 s: a rampa de 6 dB/s chega
        self.assertAlmostEqual(self.e.snapshot()["ganho_db"], so.ganho_db(self.medidos[0][1]), delta=0.05)

    def test_stream(self):
        x = musica(12, -19)
        with servidor(self.pasta) as url:
            _, y = self.disco(x, id="s")
            tr = {"id": "s", "youtube_id": "abcdefghijk", "title": "stream", "path": f"{url}/s.wav", "stream": True,
                  "duration": 12.0}
            vistas = []
            orig = self.e.sonoridade
            self.e.sonoridade = lambda t, v, inteira=True: (vistas.append((round(v, 2), inteira)), orig(t, v, inteira))
            self.e.load(tr)
            self.assertTrue(self.espera(lambda: self.medidos), "o stream inteiro nao foi medido")
        self.assertEqual([i for _, i in vistas], [False, True], "estimativa aos 8 s e a medida inteira no fim")
        self.assertAlmostEqual(self.medidos[0][1], lufs(y), delta=0.01)
        self.assertEqual(self.e._medidas["abcdefghijk"][1], True)
        self.assertAlmostEqual(20 * np.log10(self.e._deck.ganho_alvo), so.ganho_db(lufs(y)), places=6)

    def test_eco_leva_o_ganho_de_quem_saiu(self):
        velho = eng.Deck()
        velho.ganho = 2.0
        a = np.full((B * 3, 2), 0.1, np.float32)
        self.e._eco = [a, 0, velho]
        out = np.concatenate([self.e._mixa(B) for _ in range(4)])
        self.assertAlmostEqual(float(out[D + 10, 0]), 0.2, places=6)
        self.e.volume_auto = False
        self.e._eco = [a, 0, velho]
        out = np.concatenate([self.e._mixa(B) for _ in range(4)])
        self.assertAlmostEqual(float(out[D + 10, 0]), 0.1, places=6)

    def test_custo_do_misturador(self):
        tr, _ = self.disco(musica(8, -24, picos=0.9), id="baixa", lufs=-24.0)
        self.e.load(tr)
        self.toca(20)
        ts = []
        cpu = 0.0
        for _ in range(400):
            self.espera(lambda: len(self.e._q) > 2 or self.e._eof_gen == self.e._gen, 5)
            c0 = time.thread_time()
            t0 = time.perf_counter()
            self.e._mixa(B)
            ts.append(time.perf_counter() - t0)
            cpu += time.thread_time() - c0
        import json, os
        if os.environ.get("GANHO_DUMP"):
            Path(os.environ["GANHO_DUMP"]).write_text(json.dumps({"wall": ts, "cpu": cpu}))
        ms = np.array(ts) * 1000
        print(f"\n  _mixa com ganho e limitador: {ms.mean():.3f} ms em media, {np.percentile(ms, 99):.3f} no p99",
              file=sys.stderr)
        self.assertLess(float(ms.mean()), 0.3)  # a media: o p99 sobe com o PC ocupado (so se mostra)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(0 if unittest.main(exit=False, verbosity=2).result.wasSuccessful() else 1)
