"""Testa o stream que congela no meio (13/11: a Toxic parou de chegar em 2:12 com a conexao aberta, o ffmpeg esperou
pra sempre e a vitrola ficou carregando): com o ffmpeg de verdade e o leitor do motor (Engine._reader), um servidor
http local manda o comeco do disco e para de mandar sem fechar a conexao, e para sempre naquele endereco (o pior caso:
o endereco morreu). O ffmpeg reconecta uma vez depois de STREAM_SEM_DADO_S sem nada, congela de novo e desiste; o
religar (o do servidor, imitado aqui com a espera de um endereco novo) troca a fonte, e um consumidor no ritmo do microfone
(10 ms por bloco, o mesmo que o _out_cb tira da fila) conta cada bloco que faltou. O som tocado tem que ser o disco
inteiro, amostra por amostra, sem buraco.

O teste rapido encolhe os tempos (2 s sem dado, 10 s de folga, 2 s pelo endereco novo) e tem o controle: com a folga
antiga de 2 s o mesmo congelamento faz buraco, entao o teste enxerga buraco quando ele existe.

    python dev/testa_congela.py          # o rapido (~1 min)
    python dev/testa_congela.py --real   # com os tempos de verdade e o endereco novo em 15 s, como no 13/11 (~75 s)

Sai 1 se algo falhar.
"""
import contextlib
import functools
import http.server
import re
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

CABECALHO = 44  # o wav PCM simples que o teste escreve


class _Servidor(http.server.SimpleHTTPRequestHandler):
    """/ok/<arq> serve com Range; /congela/<arq> serve ate o byte `corte` e dai para de mandar, sem fechar, ate o
    servidor desligar (toda conexao nesse endereco, tambem a que o ffmpeg reabrir)."""

    corte = 0
    parou_em = None  # perf_counter da primeira vez que congelou
    fim = threading.Event()

    def log_message(self, *a):
        pass

    def do_GET(self):
        m = re.match(r"^/(ok|congela)/(.+)$", self.path)
        if not m:
            self.send_error(404)
            return
        dados = (Path(self.directory) / m.group(2)).read_bytes()
        ini = 0
        r = re.match(r"bytes=(\d+)-", self.headers.get("Range") or "")
        if r:
            ini = int(r.group(1))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {ini}-{len(dados) - 1}/{len(dados)}")
        else:
            self.send_response(200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(dados) - ini))
        self.end_headers()
        ate = len(dados) if m.group(1) == "ok" else max(ini, type(self).corte)
        try:
            for i in range(ini, ate, 16384):
                self.wfile.write(dados[i:min(i + 16384, ate)])
            self.wfile.flush()
            if ate < len(dados):
                if type(self).parou_em is None:
                    type(self).parou_em = time.perf_counter()
                type(self).fim.wait(600)  # congelado: a conexao fica aberta e nada chega
        except OSError:
            pass


@contextlib.contextmanager
def _disco(dur_s, corte_s):
    """Um wav estereo de ruido (cada amostra unica) de dur_s no servidor local, que congela em corte_s no endereco
    /congela; volta (base do endereco, classe do servidor, o ruido em float como o ffmpeg entrega)."""
    pasta = tempfile.TemporaryDirectory()
    ruido = np.random.default_rng(13).integers(-8000, 8000, (int(dur_s * eng.SR), 2)).astype(np.int16)
    with wave.open(str(Path(pasta.name) / "d.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(eng.SR)
        w.writeframes(ruido.tobytes())
    srv_cls = type("S", (_Servidor,), {"corte": CABECALHO + int(corte_s * eng.SR) * 4, "parou_em": None,
                                       "fim": threading.Event()})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(srv_cls, directory=pasta.name))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", srv_cls, ruido.astype(np.float32) / 32768
    finally:
        srv_cls.fim.set()
        srv.shutdown()
        pasta.cleanup()


def _toca(dur_s, corte_s, folga, sem_dado_s, atraso_s):
    """Toca um disco de dur_s que congela em corte_s; volta (som tocado, faltas depois do comeco, religares, ruido)."""
    with _disco(dur_s, corte_s) as (base, _, ruido):
        e = eng.Engine("default", "")
        e._onda_pede = lambda *a: None
        e._onda_acumulador = lambda tr: None
        religou = []

        def religar(tr, pos, desistir):  # o do servidor: endereco novo depois de atraso_s, ate 2 vezes
            religou.append(pos)
            k = tr.get("religou", 0) + 1
            if k > 2:
                desistir()
                return
            time.sleep(atraso_s)
            e.trocar_fonte(tr, dict(tr, path=f"{base}/ok/d.wav", religou=k))

        e.religar_stream = religar
        tr = {"id": "d", "title": "congela", "path": f"{base}/congela/d.wav", "stream": True, "duration": dur_s}
        tocado, faltas = [], 0
        with mock.patch.object(eng, "STREAM_AHEAD", folga), mock.patch.object(eng, "STREAM_SEM_DADO_S", sem_dado_s):
            e.load(tr)
            prox = time.perf_counter()
            teto = prox + dur_s + 60
            while time.perf_counter() < teto:  # o microfone: um bloco de 10 ms a cada 10 ms
                prox += eng.BLOCK / eng.SR
                time.sleep(max(0.0, prox - time.perf_counter()))
                with e._qlock:
                    item = e._tira(e._q, eng.BLOCK)
                if item:
                    for _, s in item:
                        tocado.append(s.copy())
                    e.pos = item[-1][0] + len(item[-1][1]) / eng.SR
                elif e._eof_gen == e._gen:
                    break
                elif tocado:
                    faltas += 1
    som = np.concatenate(tocado) if tocado else np.zeros((0, 2), np.float32)
    return som, faltas, religou, ruido


class Congela(unittest.TestCase):
    sem_dado_s = 2.0

    def _confere(self, dur_s, corte_s, folga, atraso_s, buraco):
        som, faltas, religou, ruido = _toca(dur_s, corte_s, folga, self.sem_dado_s, atraso_s)
        print(f"\n  folga {folga * eng.BLOCK / eng.SR:.0f} s, {self.sem_dado_s:.0f} s sem dado, endereco novo em "
              f"{atraso_s:.0f} s: religou em {', '.join(f'{p:.2f} s' for p in religou)}; {faltas} blocos de 10 ms "
              f"faltaram; tocou {len(som) / eng.SR:.2f} de {dur_s} s", file=sys.stderr)
        self.assertEqual(len(religou), 1)
        self.assertAlmostEqual(religou[0], corte_s, delta=0.05)  # caiu onde congelou, nem antes nem depois
        if buraco:
            self.assertGreater(faltas, 0)
            return
        self.assertEqual(faltas, 0)
        self.assertEqual(len(som), len(ruido))
        self.assertTrue(np.array_equal(som, ruido), "o som tocado nao e o disco amostra por amostra")

    def test_o_ffmpeg_desiste_no_prazo(self):
        """Lendo sem freio: uma reconexao no endereco morto e o ffmpeg sai, sem as 4 tentativas de antes."""
        with _disco(30, 5) as (base, srv_cls, _), \
                mock.patch.object(eng, "STREAM_SEM_DADO_S", self.sem_dado_s):
            url = f"{base}/congela/d.wav"
            ff = subprocess.Popen([eng.FFMPEG, "-v", "error", *eng.Engine._entrada({"stream": True, "path": url}),
                                   "-i", url, "-f", "f32le", "-"], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, creationflags=eng.NO_WINDOW)
            try:
                ff.wait(timeout=4 * self.sem_dado_s + 20)
            finally:
                ff.kill()
            espera = time.perf_counter() - srv_cls.parou_em
        print(f"\n  o ffmpeg saiu {espera:.2f} s depois de congelar ({self.sem_dado_s:.0f} s sem dado)",
              file=sys.stderr)
        self.assertLess(espera, 2 * self.sem_dado_s + 1.5)

    def test_congela_sem_buraco(self):
        self._confere(24, 10, 1000, 2.0, buraco=False)

    def test_controle_a_folga_antiga_faz_buraco(self):
        self._confere(24, 10, eng.AHEAD, 2.0, buraco=True)


class CongelaReal(Congela):
    sem_dado_s = eng.STREAM_SEM_DADO_S

    def test_congela_sem_buraco(self):
        self._confere(70, 45, eng.STREAM_AHEAD, 15.0, buraco=False)

    test_controle_a_folga_antiga_faz_buraco = None


if __name__ == "__main__":
    caso = CongelaReal if "--real" in sys.argv else Congela
    r = unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromTestCase(caso))
    sys.exit(0 if r.wasSuccessful() else 1)
