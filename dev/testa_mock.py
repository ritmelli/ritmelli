r"""Confere a pasta de dados do servidor no --mock (#117, pastas.dados_do_mock): sem --data-dir, uma pasta temporaria
nova, que sai quando o processo fecha; a pasta de quem usa (a de hoje e a de antes da troca de nome), nem pedida; outra
pasta, ela mesma. O download de mentira do --mock copia o disco mais curto com outro nome, e na pasta de quem usa isso
virava disco falso na prateleira. A LOCALAPPDATA e temporaria: nada de verdade e tocado.

E que o --mock nao vai a rede sozinho (#128), pelo servidor de verdade: so com as bibliotecas dele (a esteira roda este
teste antes de instalar, e essa parte fica de fora).

    python dev/testa_mock.py

Sai 1 se algo falha."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
falhas = []


def confere(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        falhas.append(msg)


def pastas_com(local, codigo):
    """Roda o codigo num Python novo, com a LOCALAPPDATA trocada (o pastas.py calcula as pastas ao carregar)."""
    env = {**os.environ, "LOCALAPPDATA": str(local)}
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pastas\n" + codigo,
                        str(RAIZ)], env=env, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        print(r.stderr)
    return r.stdout.strip()


with tempfile.TemporaryDirectory(prefix="testa_mock_") as t:
    local = Path(t)
    for nome in ("Ritmelli", "Vitrola"):
        (local / nome / "library").mkdir(parents=True)

    # sem --data-dir: uma pasta nova a cada vez, fora das de quem usa, que sai quando o servidor fecha
    saida = pastas_com(local, "a = pastas.dados_do_mock(); b = pastas.dados_do_mock()\n"
                              "print(a.is_dir(), b.is_dir(), a != b); print(a); print(b)")
    linhas = saida.splitlines()
    confere(len(linhas) == 3 and linhas[0] == "True True True", "sem --data-dir: uma pasta temporaria nova a cada vez")
    if len(linhas) == 3:
        dentro = [p for p in linhas[1:] if Path(p).resolve().is_relative_to(local.resolve())]
        confere(not dentro, "sem --data-dir: a pasta nao fica na pasta de dados de quem usa")
        confere(not any(Path(p).exists() for p in linhas[1:]), "sem --data-dir: a pasta sai quando o processo fecha")

    # a pasta de quem usa: a de hoje, a de antes da troca de nome, com outra caixa, barra no fim ou caminho relativo
    pedidas = [local / "Ritmelli" / "library", local / "Vitrola" / "library",
               str(local / "RITMELLI" / "Library").upper(), str(local / "Ritmelli" / "library") + os.sep,
               local / "Ritmelli" / "x" / ".." / "library", os.path.realpath(local / "Ritmelli" / "library")]
    for p in pedidas:
        r = pastas_com(local, f"print(pastas.dados_do_mock({str(p)!r}))")
        confere(r == "None", f"a pasta de quem usa recusada: {p}")

    # outra pasta: ela mesma
    outra = local / "outra"
    r = pastas_com(local, f"print(pastas.dados_do_mock({str(outra)!r}))")
    confere(Path(r) == outra, "outra pasta pedida: a propria")


def sem_rede():
    """(#128) O --mock nao vai a rede sozinho. O servidor de verdade sobe com a rede apontada para uma armadilha: o
    HTTP_PROXY e o HTTPS_PROXY numa porta daqui, que o yt-dlp, a ytmusicapi e o urllib seguem e os processos filhos
    herdam. Cada conexao para fora vira uma tentativa contada, e nenhuma chega a internet. Com uma prateleira de
    titulos e videos de verdade e um disco tocando, as capas, as parecidas do Automatico e o aquecimento do processo
    do YouTube iriam na hora. Depois, uma busca (o que a pessoa pede vai ao YouTube) tem que cair na armadilha: e ela
    que mostra que a armadilha pega."""
    try:
        import aiohttp  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as ex:
        print(f"--   o --mock sem rede ficou de fora: sem as bibliotecas do servidor ({ex.name})")
        return
    tentativas = []
    arm = socket.create_server(("127.0.0.1", 0))

    def atende():
        while True:
            try:
                c, _ = arm.accept()
            except OSError:
                return
            with c:
                try:
                    c.settimeout(2)
                    tentativas.append(c.recv(300).split(b"\r\n", 1)[0].decode("latin-1"))  # CONNECT host:443 ...
                except OSError:
                    tentativas.append("?")
    threading.Thread(target=atende, daemon=True).start()
    proxy = f"http://127.0.0.1:{arm.getsockname()[1]}"
    direto = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # o teste fala com o servidor sem a armadilha
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]

    def api(metodo, rota, corpo=None, espera=10):
        req = urllib.request.Request(f"http://127.0.0.1:{porta}{rota}", method=metodo,
                                     data=None if corpo is None else json.dumps(corpo).encode(),
                                     headers={"Content-Type": "application/json"})
        with direto.open(req, timeout=espera) as r:
            return json.load(r)

    t = Path(tempfile.mkdtemp(prefix="testa_mock_rede_"))
    try:
        dados, lib = t / "dados", t / "local" / "Ritmelli" / "library"
        dados.mkdir()
        lib.mkdir(parents=True)
        discos = [("d1", "Queen - Bohemian Rhapsody", "fJ9rUzIMcZQ"), ("d2", "a-ha - Take On Me", "djV11Xbc914"),
                  ("d3", "Michael Jackson - Billie Jean", "Zi_XLOBDo_Y")]
        (dados / "library.json").write_text(json.dumps(
            [{"id": i, "title": tit, "youtube_id": y, "channel": tit.split(" - ")[0], "file": f"{i}.wav",
              "duration": 30, "thumb": None} for i, tit, y in discos]), encoding="utf-8")
        for i, _, _ in discos:
            with wave.open(str(lib / f"{i}.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(bytes(2 * 8000 * 30))
        env = {**os.environ, "LOCALAPPDATA": str(t / "local"), "HTTP_PROXY": proxy, "HTTPS_PROXY": proxy,
               "ALL_PROXY": proxy, "NO_PROXY": "127.0.0.1,localhost"}
        with open(t / "servidor.log", "w", encoding="utf-8") as log:
            srv = subprocess.Popen([sys.executable, str(RAIZ / "server.py"), "--mock", "--no-browser", "--port",
                                    str(porta), "--data-dir", str(dados)], cwd=RAIZ, env=env, stdout=log,
                                   stderr=subprocess.STDOUT)
            try:
                for _ in range(600):
                    try:
                        api("GET", "/api/state", espera=2)
                        break
                    except OSError:
                        if srv.poll() is not None:
                            break
                        time.sleep(0.1)
                api("POST", "/api/play", {"id": "d1"})
                api("POST", "/api/aquece", {})  # a mina avisando que alguem comecou a falar
                time.sleep(8)  # as capas a cada 2 s, o Automatico em 0,5 s, o aquecimento logo ao subir
                sozinho = list(tentativas)
                confere(not sozinho, f"o --mock com um disco tocando nao vai a rede sozinho ({sozinho[:4]})")
                try:
                    api("GET", "/api/search?q=queen&n=5", espera=20)
                except OSError:
                    pass  # a armadilha fecha a conexao: a busca falha, e o que conta e ter tentado
                for _ in range(100):
                    if len(tentativas) > len(sozinho):
                        break
                    time.sleep(0.1)
                confere(len(tentativas) > len(sozinho), f"a busca que a pessoa pede cai na armadilha: ela pega "
                        f"({tentativas[len(sozinho):][:2]})")
            finally:
                try:
                    api("POST", "/api/shutdown", espera=5)
                    srv.wait(15)
                except (OSError, subprocess.TimeoutExpired):
                    srv.kill()
                    srv.wait()
                arm.close()
    finally:
        # o servidor saiu, mas o ffmpeg que media a sonoridade de um disco ainda pode estar com o .wav aberto: a pasta
        # sai quando ele soltar
        for _ in range(60):
            shutil.rmtree(t, ignore_errors=True)
            if not t.exists():
                break
            time.sleep(0.25)
        confere(not t.exists(), f"a pasta do teste saiu ({t})")


sem_rede()

print("\nFALHOU: " + "; ".join(falhas) if falhas else "\ntudo ok")
sys.exit(1 if falhas else 0)
