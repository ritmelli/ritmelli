r"""Checks the music commands (comandos.py) and the queue advance on the real App: server.App(..., mock=True,
vigias=False, relogio=False), in the same process and a temporary folder, without the watcher threads or the
MockEngine's clock. The test moves the audio, calling engine._mixa(BLOCK), and plays each watcher, calling its round
(_volta_fila, _volta_passagem and Automatico.auto_round). The engine's reader is a fake one (silent blocks, no
ffmpeg), the sound on top is only recorded and the stream address is refused: nothing goes to the network or opens a
device, and the user's shelf and folder are not read. Also the state read (App.leitura) with the engine's switch not
yet reconciled with the queue, with the watcher suspended in the middle of reconciling and with the preparation
blocked. And the _mixa block stopped between taking and publishing (Suspenso), with a seek, a load, a resume from the
end, a deck swap, the stream replaced by the file or a pause request in the middle. And the engine's public seams
(engine_seams).

    python dev/testa_comandos.py

Exits 1 if something fails."""
import asyncio
import contextlib
import io
import json
import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np
from aiohttp.test_utils import make_mocked_request

with contextlib.redirect_stderr(io.StringIO()):  # o aviso das vozes do pedal, que nao sao deste teste
    import automatico
    import comandos as cmd
    import engine as eng
    import i18n
    import pastas
    import server

falhas = []
BLOCOS = 30  # cada disco de mentira tem 0,3 s de audio


def confere(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        falhas.append(msg)


def ate(cond, limite=5.0):
    """Espera cond() ficar verdadeira (as threads do leitor e do stream); volta se ficou."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def disco(iid, dur=120.0, yid=None):
    # o lufs ja medido: o motor nao abre o ffmpeg para medir o arquivo (que nem existe)
    return {"id": iid, "title": f"Disco {iid}", "file": f"{iid}.m4a", "duration": dur, "youtube_id": yid,
            "lufs": -14.0, "last_pos": 0}


def monta(tmp):
    """O App de verdade, sem vigias e sem relogio, com tres discos longos e um curto na prateleira."""
    (tmp / "library.json").write_text(json.dumps([disco("d1"), disco("d2"), disco("d3", yid="aaaaaaaaaaa"),
                                                  disco("buzina", dur=3.0)]), encoding="utf-8")
    # o App nao abre porta (quem abre e o servir), e os aparelhos do Windows nao sao lidos: o motor liga sem eles.
    # Cada Thread.start fica anotado, mesmo o da thread que acaba logo (o vigia das metricas, no --mock)
    with (contextlib.redirect_stderr(io.StringIO()),
          mock.patch.object(eng.MockEngine, "_real_names", return_value={"mic": "", "monitor": ""}),
          mock.patch.object(threading.Thread, "start", autospec=True) as iniciar):
        A = server.App(0, tmp, mock=True, vigias=False, relogio=False)
    novas = [getattr(c.args[0], "name", "?") for c in iniciar.call_args_list]
    confere(not novas, f"o App sem vigias e sem relogio nao sobe thread nenhuma ({novas})")
    E = A.engine
    confere(getattr(E, "_run", False) and E.error is None, f"o motor ligou, sem o relogio ({E.error})")
    E.volume_auto = False

    def leitor(gen, track, start, deck):
        """O _reader sem ffmpeg: BLOCOS blocos de silencio a partir de start, e o fim."""
        with E._qlock:
            if gen != deck.gen:
                return
            for i in range(BLOCOS):
                t = start + i * eng.BLOCK / eng.SR
                deck.q.append((t, np.zeros((eng.BLOCK, 2), np.float32)))
                deck.niveis.append((t, eng.BLOCK, 0.0))
            deck.eof_gen = gen

    E._reader = leitor
    A.sobre = []
    E.por_cima = A.sobre.append  # o som por cima decodificaria o arquivo inteiro: so anota

    def recusa(target, formato=None):
        raise RuntimeError("Video unavailable")  # o erro do proprio video: o _abre_stream nao tenta de novo
    A.stream_info = recusa
    return A, E


def no_prato(E):
    return E.track and E.track.get("id")


def toca_ate_o_fim(E):
    """O _mixa ate o disco do prato acabar (o leitor de mentira ja pos tudo na fila)."""
    for _ in range(BLOCOS + 5):
        E._mixa(eng.BLOCK)
        if E.status() == "ended":
            return True
    return False


def fila(A):
    return [x["id"] for x in A.fila]


def historico(A):
    return [x["chave"] for x in A.historico]


def comandos(A, E):
    print("--- os comandos")
    confere(cmd.tocar(A, "nao-existe") is None, "tocar o que nao esta na prateleira: None (a rota responde 404)")
    confere(cmd.tocar(A, "d1") == "prato" and no_prato(E) == "d1", "tocar um disco: ele vai para o prato")
    confere(ate(lambda: E.status() == "playing"), f"e toca ({E.status()})")
    confere(cmd.tocar(A, "buzina") == "por_cima" and no_prato(E) == "d1" and A.sobre[-1]["id"] == "buzina",
            "o som curto toca por cima, sem trocar o disco do prato")
    confere(cmd.tocar(A, "buzina", por_cima=False) == "prato" and no_prato(E) == "buzina",
            "o som curto com por_cima false vai para o prato")
    cmd.tocar(A, "d1")
    confere(cmd.tocar(A, "buzina", por_cima=None) == "prato" and no_prato(E) == "buzina",
            "o som curto com o por_cima null no corpo vai para o prato, como o false")
    confere(cmd.tocar(A, "d1", por_cima=True) == "por_cima" and no_prato(E) == "buzina",
            "o disco longo com por_cima true toca por cima")
    A.lib.update("d1", last_pos=42.0)
    cmd.tocar(A, "d1", retomar=True)
    confere(ate(lambda: E.status() == "playing") and abs(E.pos - 42.0) < 0.01,
            f"retomar continua de onde parou ({E.pos})")

    x2, _, tocou = cmd.enfileirar(A, {"id": "d2"})
    x3, _, tocou3 = cmd.enfileirar(A, {"id": "d3"})
    confere(not tocou and not tocou3 and fila(A) == ["d2", "d3"], "com disco no prato, enfileirar so guarda")
    confere(cmd.mover_na_fila(A, x3["qid"], 0) and fila(A) == ["d3", "d2"], "mover na fila")
    confere(not cmd.mover_na_fila(A, "sumiu", 0), "mover o que ja saiu da fila: False (404)")
    confere(cmd.tirar_da_fila(A, x3["qid"]) is x3 and fila(A) == ["d2"], "tirar da fila")
    confere(cmd.tirar_da_fila(A, x3["qid"]) is None, "tirar o que ja saiu: None (404)")

    A.lib.update("d1", last_pos=0.0)  # o retomar acima deixou 42: a posicao conferida tem de vir do pausar
    cmd.pausar(A)
    confere(E.status() == "paused" and A.lib.get("d1")["last_pos"] == round(E.pos, 1),
            "pausar pausa e grava a posicao do disco")
    xq, _, tocou = cmd.enfileirar(A, {"id": "d3"})
    confere(not tocou and E.status() == "paused" and fila(A) == ["d2", "d3"],
            "com o disco pausado, enfileirar so guarda (pausado ainda e disco no prato)")
    cmd.alternar(A)
    confere(E.status() == "playing", f"o alternar com o disco pausado retoma ({E.status()})")
    cmd.alternar(A)
    confere(E.status() == "paused", f"o alternar com o disco tocando pausa ({E.status()})")
    cmd.retomar(A)
    confere(E.status() == "playing", "retomar")
    cmd.ir_para(A, 10.0)
    confere(ate(lambda: E.status() == "playing") and abs(E.pos - 10.0) < 0.01, f"ir para um ponto ({E.pos})")
    confere(cmd.tocar_da_fila(A, None) is None and cmd.tocar_da_fila(A, "sumiu") is None and no_prato(E) == "d1",
            "tocar da fila o que nao esta nela: None (404), e nada muda")
    confere(cmd.tocar_da_fila(A, xq["qid"]) is xq and no_prato(E) == "d3" and fila(A) == ["d2"]
            and historico(A)[-1:] == ["d1"], "tocar da fila: a entrada sai da fila e toca agora")

    x = cmd.pular(A)
    confere(x is x2 and no_prato(E) == "d2" and fila(A) == [] and historico(A)[-1:] == ["d3"],
            f"pular: a primeira da fila toca, e o que saiu vai para o Anterior ({historico(A)})")
    confere(cmd.pular(A) is None and no_prato(E) == "d2", "pular com a fila vazia: None (409), e nada muda")

    cmd.parar(A)
    confere(E.track is None and historico(A)[-1:] == ["d2"], "parar tira o disco do prato e guarda no Anterior")
    x, _, tocou = cmd.enfileirar(A, {"id": "d3"})
    confere(tocou and no_prato(E) == "d3" and fila(A) == [], "com o prato parado, o que entra na fila toca na hora")
    confere(cmd.voltar(A) == "anterior" and no_prato(E) == "d2" and fila(A) == ["d3"],
            "voltar: o de antes toca, e o do prato vai para o topo da fila")
    cmd.limpar_fila(A)
    confere(fila(A) == [], "limpar a fila")

    confere(cmd.volume(A, 0.3) == 0.3 and E.vol == 0.3
            and json.loads(A.cfg_path.read_text(encoding="utf-8")).get("vol") == 0.3,
            "o volume da musica muda no motor e e gravado")
    confere(cmd.volume(A, 1.5) == 1.0 and cmd.volume(A, -1) == 0.0, "o volume fora de 0 a 1 fica no limite")
    cmd.volume(A, 0.3)


def voltas(A, E):
    print("--- as voltas dos vigias")
    cmd.tocar(A, "d1")
    ate(lambda: E.status() == "playing")
    confere(A._volta_fila(None) is None, "o _volta_fila com o disco tocando nao faz nada")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    confere(toca_ate_o_fim(E), "o _mixa leva o disco ao fim")
    tr = E.track
    visto = A._volta_fila(None)
    confere(visto is tr and no_prato(E) == "d2" and fila(A) == [] and historico(A)[-1:] == ["d1"],
            "o fim do disco: o _volta_fila avanca a fila (o que saiu vai para o Anterior)")
    ate(lambda: E.status() == "playing")
    toca_ate_o_fim(E)
    tr = E.track
    confere(A._volta_fila(None) is tr and A.parado_sem_fila is tr and no_prato(E) == "d2",
            "o fim do disco com a fila vazia: o prato fica parado, marcado para a parecida que chegar")
    x, _ = A.enfileirar({"id": "d1"})  # so na fila, sem tocar: a volta seguinte nao pode avancar para ela
    confere(A._volta_fila(tr) is tr and no_prato(E) == "d2" and fila(A) == ["d1"],
            "a volta seguinte, com o mesmo disco visto, nao avanca de novo")
    A.tirar_da_fila(x["qid"])

    # the similar track that arrives with the platter stopped plays right away (auto_round)
    A.automatico._auto, A.automatico._semente, A.automatico._mix_base = True, {"youtube_id": "bbbbbbbbbbb", "title": "semente"}, "bbbbbbbbbbb"
    A.automatico._mix = [{"youtube_id": "aaaaaaaaaaa", "title": "Disco d3", "duration": 120.0, "ordem": 1}]
    visto, sinal = A.automatico.auto_round(None, None)
    confere(no_prato(E) == "d3" and E.track.get("auto") and A.parado_sem_fila is None and fila(A) == [],
            f"auto_round: the similar track that arrived with the platter stopped plays right away ({no_prato(E)})")
    visto, sinal = A.automatico.auto_round(visto, sinal)
    confere(visto == "aaaaaaaaaaa" and A.automatico._ponte == "aaaaaaaaaaa",
            "a volta seguinte ve a parecida no prato: o Automatico segue do Mix dela quando o da semente acabar")
    A.automatico._auto = False

    # a virada da passagem: o motor vira sozinho, e o _volta_passagem so acompanha a fila e o historico
    ate(lambda: E.status() == "playing")
    x, _, _ = cmd.enfileirar(A, {"id": "d1"})
    y, _, _ = cmd.enfileirar(A, {"id": "d2"})
    with contextlib.redirect_stderr(io.StringIO()):
        confere(E.preparar(dict(A.lib.get("d1"), path=str(server.LIB / "d1.m4a")), x["qid"]),
                "o motor prepara a primeira da fila no segundo deck")
        ate(lambda: E._pronto is not None and E._pronto.q)
        for _ in range(BLOCOS + 5):
            E._mixa(eng.BLOCK)
            if E.virou is not None:
                break
    confere(E.virou is not None and no_prato(E) == "d1", "o _mixa vira para a preparada no fim do disco")

    # a leitura do estado com a virada confirmada no motor e ainda nao conciliada na fila
    est, pos = A.leitura()
    confere(fila(A) == ["d1", "d2"], "a virada ainda nao conciliada: a entrada que entrou segue na fila do App")
    confere(est["track"]["id"] == "d1" and pos == E.pos and [q["qid"] for q in est["queue"]] == [y["qid"]],
            f"e a leitura ja e da virada: a faixa nova, a posicao dela e a fila sem a entrada que entrou "
            f"({est['track']['id']}, {[q['id'] for q in est['queue']]})")
    z, _, _ = cmd.enfileirar(A, {"id": "d3"})
    confere(not cmd.mover_na_fila(A, x["qid"], 1), "a entrada da virada ainda nao conciliada nao se move")
    confere(cmd.mover_na_fila(A, y["qid"], 1) and [q["id"] for q in A.leitura()[0]["queue"]] == ["d3", "d2"],
            f"mover na fila conta o lugar na fila que a tela ve, sem a entrada da virada ({fila(A)})")
    cmd.tirar_da_fila(A, z["qid"])

    # o Proximo com a virada pendente: a virada e o avanco dele (o Anterior guarda o que saiu nela), e ele volta a
    # entrada que acabou de entrar, sem pular de novo. Depois de cada caso, a virada volta a ficar pendente
    v, f0, h0 = E.virou, list(A.fila), list(A.historico)

    def pendente(f=f0):
        with A.fila_lock:
            A.fila[:], A.historico[:] = list(f), list(h0)
        E.virou, E.ended, A.parado_sem_fila = v, False, None

    vistos = []
    with mock.patch.object(A, "tocar_entrada", side_effect=lambda q, **_: vistos.append(
            (q, E.virou, historico(A)[-1:], fila(A)))):
        confere(cmd.pular(A) is x and vistos == [] and E.virou is None and fila(A) == ["d2"]
                and historico(A)[-1:] == ["d3"] and no_prato(E) == "d1",
                f"o Proxima logo depois da virada: fecha a virada (o Anterior guarda a d3) e volta a entrada que "
                f"acabou de entrar, sem tocar a seguinte ({[q['id'] for q, *_ in vistos]}, {fila(A)})")
    pendente([x])
    confere(cmd.pular(A) is x and E.virou is None and fila(A) == [] and historico(A)[-1:] == ["d3"],
            "so com a da virada na fila, o mesmo: o Proxima e a virada")
    pendente([x])
    tr, E.ended = E.track, True  # o disco que entrou na virada ja acabou, antes de o vigia conciliar
    confere(A._volta_fila(None) is tr and A.parado_sem_fila is tr and E.virou is None,
            "o fim do disco com a virada pendente e a fila vazia: o prato fica marcado como parado")
    confere(cmd.avanca(A, virada=v) is None and A.parado_sem_fila is tr and historico(A)[-1:] == ["d3"],
            "o vigia que ja tinha lido a virada nao concilia de novo nem apaga a marca do prato parado")
    A._volta_passagem()
    confere(A.parado_sem_fila is tr, "e a volta do vigia depois nao apaga essa marca (a virada ja foi fechada)")
    pendente()

    # a virada publicada pelo motor no instante em que o Proxima pega o _qlock (o vigia ainda nao a viu): o Proxima
    # a fecha, e ela e o avanco dele
    qlock, vistos, virou = E._qlock, [], [v]

    class Vira:
        """O mesmo _qlock; na primeira vez que alguem o pega, o motor acaba de virar."""

        def __enter__(self):
            if virou:
                E.virou = virou.pop()
            return qlock.__enter__()

        def __exit__(self, *a):
            return qlock.__exit__(*a)
    pendente()
    E.virou, E._qlock = None, Vira()
    try:
        with mock.patch.object(A, "tocar_entrada", side_effect=lambda q, **_: vistos.append((q, historico(A)[-1:]))):
            veio = cmd.pular(A)
    finally:
        E._qlock = qlock
    confere(veio is x and vistos == [] and E.virou is None and fila(A) == ["d2"] and historico(A)[-1:] == ["d3"],
            f"a virada que chega no meio do Proxima: ele a fecha e volta a entrada dela, sem tocar a seguinte "
            f"({[(q['id'], h) for q, h in vistos]})")
    pendente()

    # o vigia ganha a virada e fica suspenso no meio da conciliacao, logo antes de guardar no Anterior o que saiu; o
    # Proxima que chega nesse meio espera, e o Anterior guarda o que saiu na virada antes do disco da virada
    guardar = A.save_history
    dentro, solta, vistos = threading.Event(), threading.Event(), []

    def devagar(guarda):
        def f(novo_id=None, tr=None):
            if tr is v[0]:
                dentro.set()
                solta.wait(5)
            return guarda(novo_id, tr)
        return f
    A.save_history = devagar(guardar)
    try:
        with mock.patch.object(A, "tocar_entrada", side_effect=lambda q, **_: vistos.append(historico(A)[-1:])):
            vigia = threading.Thread(target=cmd.avanca, args=(A,), kwargs={"virada": v})
            vigia.start()
            confere(dentro.wait(5), "o vigia concilia a virada e para no meio, com a fila_lock na mao")
            proxima = threading.Thread(target=cmd.pular, args=(A,))
            proxima.start()
            proxima.join(0.2)
            confere(proxima.is_alive() and not vistos, "o Proxima que chega nesse meio espera a conciliacao")
            solta.set()
            vigia.join(5)
            proxima.join(5)
        confere(vistos == [["d3"]], f"e so toca depois de o Anterior guardar o que saiu na virada ({vistos})")
    finally:
        solta.set()
        del A.save_history  # volta o do App
    pendente()

    # a leitura pega o _qlock do motor: com ele na mao de outro (o _mixa no meio do bloco), ela espera
    class Avisa:
        """O mesmo _qlock, avisando quando alguem tenta pegar."""

        def __init__(self, trava, chegou):
            self.trava, self.chegou = trava, chegou

        def __enter__(self):
            self.chegou.set()
            return self.trava.__enter__()

        def __exit__(self, *a):
            return self.trava.__exit__(*a)

    qlock, chegou, lidas = E._qlock, threading.Event(), []
    leitor = threading.Thread(target=lambda: lidas.append(A.leitura()))
    qlock.acquire()
    try:
        E._qlock = Avisa(qlock, chegou)
        leitor.start()
        confere(chegou.wait(2), "a leitura chega ao _qlock do motor")
        leitor.join(0.2)
        confere(leitor.is_alive() and not lidas, "com o _qlock na mao de outro, a leitura espera")
    finally:
        qlock.release()
        leitor.join(5)
        E._qlock = qlock
    confere(lidas and lidas[0][0]["track"]["id"] == "d1" and lidas[0][1] == E.pos
            and [q["qid"] for q in lidas[0][0]["queue"]] == [y["qid"]],
            "solto o _qlock, a leitura volta com a faixa, a posicao e a fila da virada")

    # o vigia suspenso no meio da conciliacao, com a fila_lock na mao: a leitura espera e nunca ve a virada sem a fila
    tirar, dentro, solta = A.remove_from_queue, threading.Event(), threading.Event()

    def tirar_devagar(q):
        dentro.set()
        solta.wait(5)
        tirar(q)
    A.remove_from_queue = tirar_devagar
    vigia = threading.Thread(target=A._volta_passagem)
    vigia.start()
    dentro.wait(5)
    lidas = []
    leitor = threading.Thread(target=lambda: lidas.append(A.leitura()))
    leitor.start()
    leitor.join(0.3)
    confere(not lidas and E.virou is None, "com o vigia no meio da conciliacao, a leitura espera a fila_lock")
    solta.set()
    vigia.join(5)
    leitor.join(5)
    ate(lambda: A.preparando is None)  # a volta ja prepara a seguinte (a d2): o teste so segue com ela pronta
    A.remove_from_queue = tirar
    confere(lidas and lidas[0][0]["track"]["id"] == "d1" and [q["qid"] for q in lidas[0][0]["queue"]] == [y["qid"]],
            "e depois le a virada conciliada: a mesma faixa e a mesma fila")
    confere(E.virou is None and fila(A) == ["d2"] and historico(A)[-1:] == ["d3"] and no_prato(E) == "d1",
            f"o _volta_passagem tira da fila a que entrou e guarda a que saiu ({fila(A)}, {historico(A)[-1:]})")

    # a preparacao da proxima bloqueada, no endereco do stream (fonte_de, fora das travas) e depois no E.preparar, e o
    # E._lock na mao de outra thread: o GET /api/state de verdade, pelo guard, segue respondendo
    app = server.build(A)
    rota_state = next(r.handler for r in app.router.routes()
                      if r.method == "GET" and r.resource is not None and r.resource.canonical == "/api/state")

    async def pede_state():
        t = mock.Mock()
        t.get_extra_info.side_effect = lambda nome, d=None: ("127.0.0.1", 50000) if nome == "peername" else d
        req = make_mocked_request("GET", "/api/state", headers={"Host": f"127.0.0.1:{A.port}"}, transport=t, app=app)
        req._match_info = await app.router.resolve(req)
        resp = await app.middlewares[0](req, rota_state)
        return resp.status, json.loads(resp.body)

    def state_responde(quando):
        t0 = time.monotonic()
        st, corpo = asyncio.run(asyncio.wait_for(pede_state(), 2))
        dt = time.monotonic() - t0
        confere(st == 200 and dt < 0.5 and corpo["track"]["id"] == "d1" and "pos" in corpo,
                f"com a preparacao bloqueada {quando}, o /api/state responde ({st}, {dt:.3f} s)")

    fonte, preso, libera = A.fonte_de, threading.Event(), threading.Event()
    onda, na_onda, libera_onda = E._onda_pede, threading.Event(), threading.Event()

    def fonte_presa(q, shelf=None):
        preso.set()
        libera.wait(5)
        return fonte(q, shelf)

    def onda_presa(tr):
        na_onda.set()
        libera_onda.wait(5)
        return onda(tr)

    with E.state_section():
        E.drop_prepared()
    A.fonte_de, E._onda_pede = fonte_presa, onda_presa
    try:
        A._volta_passagem()
        confere(preso.wait(5), "o _volta_passagem comeca a preparar a primeira da fila")
        state_responde("no endereco do stream")
        libera.set()
        confere(na_onda.wait(5), "liberado o endereco, a preparacao entra no E.preparar")
        state_responde("no E.preparar")
    finally:
        libera.set()
        libera_onda.set()
        confere(ate(lambda: A.preparando is None), "liberada, a preparacao termina")
        A.fonte_de, E._onda_pede = fonte, onda

    # o E._lock na mao de outra thread (um load, um preparar): o /api/state, que so usa a fila_lock e o _qlock, responde
    com_lock, solta_lock = threading.Event(), threading.Event()

    def segura_lock():
        with E._lock:
            com_lock.set()
            solta_lock.wait(5)
    segura = threading.Thread(target=segura_lock, daemon=True)
    segura.start()
    try:
        confere(com_lock.wait(5), "outra thread segura o E._lock")
        state_responde("com o E._lock na mao de outra thread")
    finally:
        solta_lock.set()
        segura.join(5)

    # o pos do /api/state e o da mesma captura do estado: o motor que anda depois da leitura nao entra na resposta
    leitura, pos0 = A.leitura, E.pos

    def leitura_e_anda():
        r = leitura()
        E.pos = 0.5  # o motor andou depois da captura
        return r
    E.pos = 12.34
    try:
        with mock.patch.object(A, "leitura", leitura_e_anda):
            st, corpo = asyncio.run(asyncio.wait_for(pede_state(), 2))
    finally:
        E.pos = pos0
    confere(st == 200 and corpo["track"]["id"] == "d1" and corpo["pos"] == 12.34,
            f"o pos do /api/state e o da captura, nao o do motor depois dela ({corpo.get('pos')})")

    # o stream da parecida que nao abriu: a fila avanca sem guardar a parecida no Anterior
    cmd.limpar_fila(A)
    parecida = {"id": None, "youtube_id": "ccccccccccc", "url": None, "title": "parecida", "channel": None,
                "thumb": None, "duration": 120.0, "job": None, "qid": "p1", "auto": True, "auto_de": "semente"}
    cmd.enfileirar(A, {"id": "d2"})
    with A.fila_lock:
        A.fila.insert(0, parecida)  # na frente: o enfileirar poria o d2 antes dela
    hist = list(historico(A))
    with contextlib.redirect_stderr(io.StringIO()):
        confere(cmd.pular(A) is parecida, "pular para a parecida do stream")
        # a troca tira a entrada da fila sob a fila_lock, logo depois de o motor carregar: espera as duas
        confere(ate(lambda: no_prato(E) == "d2" and fila(A) == []),
                f"o stream dela recusado: a seguinte da fila toca ({no_prato(E)})")
    confere(historico(A) == hist + ["d1"] and fila(A) == [],
            f"e a parecida que nao tocou nao vai para o Anterior ({historico(A)[len(hist):]})")

    # a entrada quebrada no fim do disco: o erro vai para a tela (na_tela), e a volta segue sem travar a fila
    ate(lambda: E.status() == "playing")
    with A.fila_lock:
        A.fila.append({"id": None, "youtube_id": None, "url": None, "title": "quebrada", "qid": "q0", "job": None})
    toca_ate_o_fim(E)
    tr = E.track
    E.set_error(None)
    confere(A._volta_fila(None) is tr and fila(A) == [] and A.parado_sem_fila is not tr
            and (E.error or {}).get("key") == "server.queue.playFailed",
            f"o fim do disco com uma entrada quebrada: o erro vai para a tela, e ela sai da fila ({E.error})")
    try:
        with A.fila_lock:
            A.fila.append({"id": None, "youtube_id": None, "url": None, "title": "quebrada", "qid": "q1", "job": None})
        cmd.pular(A)
        confere(False, "a Next to a broken entry raises the queue's play failure (the route answers it as a 500)")
    except cmd.QueuePlayFailed as ex:
        confere(fila(A) == [] and isinstance(ex.__cause__, ValueError) and ex.message["key"] == "server.queue.playFailed",
                f"a Next to a broken entry raises the queue's play failure (the route answers it as a 500) ({ex!r})")
    try:
        cmd.enfileirar(A, {})
        confere(False, "o enfileirar sem disco nem video e a recusa do corpo (400)")
    except cmd.CorpoRecusado:
        confere(True, "o enfileirar sem disco nem video e a recusa do corpo (400)")

    # o erro de tocar a entrada na hora nao e a recusa do corpo: segue para o guard (500)
    cmd.parar(A)
    erro = "o erro de tocar na hora nao e a recusa do corpo (a rota responde 500, como antes)"
    with mock.patch.object(A, "tocar_entrada", side_effect=ValueError("quebrou")):
        try:
            cmd.enfileirar(A, {"id": "d1"})
            confere(False, erro)
        except cmd.CorpoRecusado:
            confere(False, erro)
        except ValueError:
            confere(fila(A) == [], erro)


def andamento(A, E):
    """The real run_tempo_watcher (App.automatico's), one round per case: the measured audio version and tempo are
    written outside the fila_lock; the measure enters memory even if the write fails, and the queue swap and
    andamentos_versao only come once the write is done. While it writes, nothing of the measure shows yet."""
    print("--- run_tempo_watcher: the write outside the fila_lock")

    class Fim(Exception):
        pass
    with E.state_section():
        E.drop_prepared()
    if E.track is None:
        cmd.tocar(A, "d1")
    ate(lambda: E.status() == "playing")

    def roda(o_que, yid, falha):
        pedidos = iter([(o_que, {"id": None, "youtube_id": yid, "title": "parecida"})])

        def a_medir():
            try:
                return next(pedidos)
            except StopIteration:
                raise Fim from None  # a segunda volta: o vigia sai

        def grava(caminho, dados):  # o que ja aparecia enquanto o disco grava: o dicionario, o contador e as trocas
            gravados.append((caminho, dict(dados), A.fila_lock.locked(), dict(ativo()), A.automatico._andamentos_versao,
                             list(trocas)))
            if falha:
                raise disco_cheio
        gravados, trocas, saiu, versao = [], [], [], A.automatico._andamentos_versao
        disco_cheio = OSError("disco cheio")
        v = {"youtube_id": "fffffffffff", "duration": 200, "title": "parecida", "channel": "c"}
        caminho, ativo = ((A.automatico._versoes_path, lambda: A.automatico._versoes) if o_que == "audio"
                          else (A.automatico._andamentos_path, lambda: A.automatico._andamentos))
        antes = dict(ativo())
        medida = v if o_que == "audio" else {"ini": 100.0, "fim": 101.0}
        with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(automatico, "ANDAMENTO_APOS_S", -1),
              mock.patch.object(automatico, "save_json", grava), mock.patch.object(A.automatico, "_a_medir", a_medir),
              mock.patch.object(A.automatico, "versao_audio", return_value=v),
              mock.patch.object(A.automatico, "_mede_andamento", return_value={"ini": 100.0, "fim": 101.0}),
              mock.patch.object(A.automatico, "_troca_audio", side_effect=lambda *a: trocas.append(a)),
              mock.patch.object(threading, "excepthook", lambda a: saiu.append(a.exc_value))):
            A.automatico._auto = True
            t = threading.Thread(target=A.automatico.run_tempo_watcher, daemon=True)
            t.start()
            t.join(10)
            A.automatico._auto = False
        confere(not t.is_alive() and len(saiu) == 1 and (saiu[0] is disco_cheio if falha else isinstance(saiu[0], Fim)),
                f"run_tempo_watcher left on its own, through {'the failed write' if falha else 'the next round'} "
                f"({o_que}, {saiu})")
        confere(gravados == [(caminho, {**antes, yid: medida}, False, antes, versao, [])],
                f"uma gravacao so, no arquivo certo, com o que havia mais a medida, sem a fila_lock, e com nada da "
                f"medida aparecendo ainda ({o_que})")
        return [g[2] for g in gravados], trocas, A.automatico._andamentos_versao - versao, v

    travado, trocas, subiu, v = roda("audio", "aaaaaaaaaa1", falha=False)
    confere(travado == [False] and trocas == [("aaaaaaaaaa1", v)] and subiu == 1 and A.automatico._versoes["aaaaaaaaaa1"] == v,
            f"a versao de audio: gravada fora da fila_lock e so entao vale na fila ({travado}, {len(trocas)}, {subiu})")
    travado, trocas, subiu, v = roda("audio", "aaaaaaaaaa2", falha=True)
    confere(travado == [False] and trocas == [] and subiu == 0 and A.automatico._versoes.get("aaaaaaaaaa2") == v,
            f"a gravacao da versao falha: ela fica na memoria, mas nao vale na fila "
            f"({travado}, {len(trocas)}, {subiu})")
    travado, _, subiu, _ = roda("medir", "aaaaaaaaaa3", falha=False)
    confere(travado == [False] and subiu == 1 and A.automatico._andamentos.get("aaaaaaaaaa3") == {"ini": 100.0, "fim": 101.0},
            f"o andamento: gravado fora da fila_lock e so entao reordena o Automatico ({travado}, {subiu})")
    travado, _, subiu, _ = roda("medir", "aaaaaaaaaa4", falha=True)
    confere(travado == [False] and subiu == 0 and A.automatico._andamentos.get("aaaaaaaaaa4") == {"ini": 100.0, "fim": 101.0},
            f"a gravacao do andamento falha: ele fica na memoria, mas nao reordena ({travado}, {subiu})")


class Suspenso:
    """O _mixa de um bloco numa thread, parado entre o _captura (o bloco ja retirado sob o _qlock) e o _renderiza, ate
    o solta(), que devolve o que ele mandou para o jogo."""

    def __init__(self, E):
        self.E, self.dentro, self.libera, self.saida = E, threading.Event(), threading.Event(), []
        renderiza = E._renderiza

        def preso(b, frames):
            self.bloco = b
            self.dentro.set()
            self.libera.wait(5)
            return renderiza(b, frames)
        E._renderiza = preso
        self.t = threading.Thread(target=lambda: self.saida.append(E._mixa(eng.BLOCK)))
        self.t.start()
        self.parou = self.dentro.wait(5)

    def solta(self):
        self.libera.set()
        self.t.join(5)
        del self.E._renderiza  # volta o do motor
        return self.saida[0] if self.saida else None


def enche(E, nivel):
    """Os blocos na fila do prato passam a ter o nivel constante nivel (o leitor de mentira poe silencio)."""
    with E._qlock:
        q = E._deck.q
        for i, (t, s) in enumerate(q):
            q[i] = (t, np.full_like(s, nivel))


def arquivo(A, iid):
    return dict(A.lib.get(iid), path=str(server.LIB / f"{iid}.m4a"))


async def pede_corpo(app, A, metodo, caminho, corpo):
    """A rota de verdade com um corpo JSON, pelo guard, como o PC pede: (status, corpo)."""
    from aiohttp import streams
    t = mock.Mock()
    t.get_extra_info.side_effect = lambda nome, d=None: ("127.0.0.1", 50000) if nome == "peername" else d
    carga = streams.StreamReader(mock.Mock(_reading_paused=False), 2 ** 16, loop=asyncio.get_running_loop())
    carga.feed_data(json.dumps(corpo).encode("utf-8"))
    carga.feed_eof()
    req = make_mocked_request(metodo, caminho, headers={"Host": f"127.0.0.1:{A.port}", "Content-Type": "application/json"},
                              transport=t, payload=carga, app=app)
    req._match_info = await app.router.resolve(req)
    resp = await app.middlewares[0](req, req._match_info.handler)
    return resp.status, json.loads(resp.body)


async def pede(app, A, metodo, caminho):
    """A rota de verdade, pelo guard, como o PC pede: (status, corpo)."""
    t = mock.Mock()
    t.get_extra_info.side_effect = lambda nome, d=None: ("127.0.0.1", 50000) if nome == "peername" else d
    req = make_mocked_request(metodo, caminho, headers={"Host": f"127.0.0.1:{A.port}"}, transport=t, app=app)
    req._match_info = await app.router.resolve(req)
    resp = await app.middlewares[0](req, req._match_info.handler)
    return resp.status, json.loads(resp.body)


def off_shelf_play(A, E):
    print("--- POST /api/library with play, for a video off the shelf: the platter and the state")
    cmd.limpar_fila(A)
    app = server.build(A)
    played = {"youtube_id": "dQw4w9WgXcQ", "play": True, "title": "Live", "channel": "Band",
              "thumb": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg", "duration": 233}
    fields = ("title", "channel", "thumb", "duration")
    opened = []
    with (mock.patch.object(A, "run_download", lambda j, target: None),
          mock.patch.object(A, "_abre_stream", lambda tr, target, titled: opened.append((tr["id"], target, titled)))):
        status, answer = asyncio.run(pede_corpo(app, A, "POST", "/api/library", played))
        ate(lambda: opened)
        state_status, state = asyncio.run(pede(app, A, "GET", "/api/state"))
    track = state.get("track") or {}
    confere(status == 200 and answer.get("streaming") is True and state_status == 200
            and {k: track.get(k) for k in fields} == {k: played[k] for k in fields} and track.get("stream") is True
            and opened == [("dQw4w9WgXcQ", "dQw4w9WgXcQ", True)],
            f"the video plays right away over its stream, and the state shows the body's title, channel, thumb and "
            f"duration on the platter ({status}, {answer}, {track}, {opened})")


def bloco(A, E):
    """O bloco do _mixa: retirado sob o _qlock, renderizado fora dele e publicado so se o deck e a linha ainda sao os
    do prato. Cada caso para o _mixa depois de retirar o bloco (Suspenso), faz a outra operacao e solta."""
    print("--- o bloco do motor: a linha de reproducao")
    with E.state_section():
        E.drop_prepared()
    E.virou = None
    cmd.limpar_fila(A)
    app = server.build(A)
    tiras, tira = [], E._tira

    def tira_anota(q, n):  # o comeco de cada bloco que sai do prato, para conferir que eles sao contiguos
        r = tira(q, n)
        if r and q is E._deck.q:
            tiras.append(r[0][0])
        return r
    E._tira = tira_anota

    def toca(iid, start=0.0):
        cmd.tocar(A, iid, start=start)
        ate(lambda: E.status() == "playing")
        enche(E, 0.25)

    # um seek depois de retirar o bloco: ele nao publica posicao nem fim, e a musica dele sai
    toca("d1")
    s = Suspenso(E)
    E.seek(10.0)
    out = s.solta()
    confere(s.parou and abs(E.pos - 10.0) < 1e-9 and not E.ended and out is not None and not np.any(out),
            f"o bloco retirado antes de um seek nao publica posicao nem fim, e a musica dele sai ({E.pos})")
    ate(lambda: E.status() == "playing")
    E._mixa(eng.BLOCK)
    confere(abs(E.pos - 10.01) < 1e-9, f"o primeiro bloco depois do seek e o do ponto novo ({E.pos})")
    E.seek(500.0)
    confere(abs(E.pos - (120.0 - 0.05)) < 1e-9, f"a seek past the end starts at the end of the record ({E.pos})")
    E.seek(-3.0)
    confere(E.pos == 0.0, f"a seek before the start starts at 0 ({E.pos})")

    # o mesmo com um load durante uma passagem, com o eco soando e o limitador segurando o fim do bloco de antes: o
    # bloco velho nao mexe na rampa, no ganho, no primeiro som nem no limitador da faixa nova
    toca("d1")
    velho = eng.Deck(arquivo(A, "d3"))
    velho.q.extend((i * eng.BLOCK / eng.SR, np.full((eng.BLOCK, 2), 0.25, np.float32)) for i in range(10))
    with E._qlock:
        E._entrando = [4800, 0, 1.0, 0]
        E._saindo = [velho, 4800, 0, None, 0]
        E._eco = [np.full((4800, 2), 0.25, np.float32), 0, velho]
        E._limitador.hist = np.full_like(E._limitador.hist, 0.5)
        E._deck.ganho, E._deck.ganho_alvo = 1.0, 2.0
    E.volume_auto = True
    E.tira_soou()  # o primeiro som de antes (o do seek), que o vigia ja teria levado
    s = Suspenso(E)
    E.load(arquivo(A, "d2"))
    ganho, prato = E._deck.ganho, E._prato
    out = s.solta()
    E.volume_auto = False
    confere(s.parou and not np.any(out) and E.pos == 0.0 and E._deck.ganho == ganho and E._prato is prato
            and E.tira_soou() is None,
            "o bloco retirado antes de um load: nada dele toca, e ele nao mexe no ganho, na posicao nem no primeiro "
            "som da faixa nova")
    confere(E._entrando is None and E._saindo is None and E._eco is None and E._limitador_zera
            and E._limitador is not s.bloco.lim,
            "nem na passagem, no eco ou no limitador: o pedido de zerar o limitador da linha nova fica para ela")
    ate(lambda: E.status() == "playing")
    out = E._mixa(eng.BLOCK)
    confere(not np.any(out) and E._prato is None and E.tira_soou() is not None and abs(E.pos - 0.01) < 1e-9,
            "o primeiro bloco da faixa nova nao tem nada da anterior (o eco, o que saia, os 2 ms do limitador)")

    # a troca de deck com o mesmo valor de linha e de gen: o deck do bloco e outro objeto, e o bloco nao publica
    toca("d1")
    s = Suspenso(E)
    with E._qlock:
        d = E._deck
        outro = eng.Deck(d.track)
        outro.linha, outro.gen, outro.eof_gen = d.linha, d.gen, d.eof_gen
        E._deck, E.pos = outro, 50.0
    out = s.solta()
    confere(s.parou and E.pos == 50.0 and not E.ended and not np.any(out),
            "a troca de deck com a mesma linha e o mesmo gen no meio do bloco: o bloco do deck de antes nao publica")

    # o motor confere a proxima preparada e a condicao da virada no mesmo trecho do _qlock em que vira: a preparada
    # que troca logo antes de o _mixa pegar a trava (ainda sem a virada medida) nao entra no prato
    def prepara(iid, tag):
        with contextlib.redirect_stderr(io.StringIO()):
            E.preparar(arquivo(A, iid), tag)
            ate(lambda: E._virar_em is not None)
        with E._qlock:
            E._virar_em = E.pos  # a hora da virada medida ja chegou

    class AntesDaTrava:
        """O mesmo _qlock; na primeira vez que alguem o pega, faz antes o que foi pedido (com a trava de verdade)."""

        def __init__(self, trava, faz):
            self.trava, self.faz = trava, [faz]

        def __enter__(self):
            if self.faz:
                self.faz.pop()()
            return self.trava.__enter__()

        def __exit__(self, *a):
            return self.trava.__exit__(*a)

    toca("d1")
    prepara("d2", "t2")
    qlock, outra = E._qlock, eng.Deck(arquivo(A, "d3"))
    outra.gen = 1
    outra.q.append((0.0, np.zeros((eng.BLOCK, 2), np.float32)))

    def reprepara():
        with qlock:
            E._cancela_passagem()
            E._pronto, E.pronto_tag = outra, "t3"
    E._qlock = AntesDaTrava(qlock, reprepara)
    try:
        E._mixa(eng.BLOCK)
    finally:
        E._qlock = qlock
    confere(E.virou is None and no_prato(E) == "d1" and E._pronto is outra,
            f"a preparada trocada logo antes do bloco, sem a virada medida, nao vira ({no_prato(E)})")
    with E.state_section():
        E.drop_prepared()

    prepara("d2", "t2")
    E._qlock = AntesDaTrava(qlock, lambda: E.load(arquivo(A, "d3")))
    try:
        E._mixa(eng.BLOCK)
    finally:
        E._qlock = qlock
    confere(E.virou is None and no_prato(E) == "d3" and E._pronto is None,
            f"o load logo antes do bloco da virada: ela nao acontece, e o disco do load fica ({no_prato(E)})")

    # o load concorrendo com o _vira: o bloco ja retirado do deck que acabou de entrar nao publica
    toca("d1")
    prepara("d2", "t2")
    s = Suspenso(E)
    virou = E.virou is not None and no_prato(E) == "d2"
    E.load(arquivo(A, "d3"))
    out = s.solta()
    confere(s.parou and virou and no_prato(E) == "d3" and E.pos == 0.0 and not np.any(out)
            and E._saindo is None and E._entrando is None,
            "o load logo depois da virada, com o bloco dela retirado: o bloco nao publica, e a passagem sai")
    E.virou = None

    # a troca do stream para o arquivo com o bloco retirado: ele sai uma vez, e o seguinte e contiguo
    def no_stream():
        tr = {"id": "s1", "title": "stream", "duration": 120.0, "path": None, "stream": True, "job": None,
              "lufs": -14.0}
        E.espera(tr)
        st = dict(tr, path="http://stream.invalid/s1")
        E.trocar_fonte(tr, st)
        ate(lambda: E.status() == "playing")
        with E._qlock:
            E._deck.eof_gen = -1  # o leitor do stream ainda le
        return st
    # o religar do stream (o mesmo audio por outro endereco) mantem a passagem preparada; a troca para o arquivo, com
    # leitor novo, a desfaz
    st = no_stream()
    with contextlib.redirect_stderr(io.StringIO()):
        E.preparar(arquivo(A, "d2"), "t2")
    preparada = E._pronto is not None
    st2 = dict(st, path="http://stream.invalid/s1-novo", religou=1)
    E.trocar_fonte(st, st2)
    confere(preparada and E._pronto is not None and E.pronto_tag == "t2",
            "o religar do stream mantem a passagem preparada")
    ate(lambda: E._deck.eof_gen == E._deck.gen)
    with E._qlock:
        E._deck.eof_gen = -1  # o leitor do stream ainda le
    E.trocar_fonte(st2, dict(st2, path=str(server.LIB / "s1.m4a")))
    confere(E._pronto is None and E.pronto_tag is None,
            "a troca do stream para o arquivo, com leitor novo, desfaz a passagem preparada na fonte de antes")

    for vazia in (False, True):
        st = no_stream()
        if vazia:
            with E._qlock:
                while len(E._q) > 1:
                    E._q.pop()
        s = Suspenso(E)
        fim = s.bloco.item[-1][0] + eng.BLOCK / eng.SR
        E.trocar_fonte(st, dict(st, path=str(server.LIB / "s1.m4a")))
        ate(lambda: len(E._q) > 0)
        out = s.solta()
        del tiras[:]
        E._mixa(eng.BLOCK)
        confere(s.parou and abs(E.pos - fim - 0.01) < 1e-9 and tiras and abs(tiras[0] - fim) < 1e-9,
                f"a troca para o arquivo com o bloco do stream retirado{' e a fila vazia' if vazia else ''}: ele "
                f"publica uma vez e o seguinte comeca onde ele acabou ({tiras[:1]}, {fim})")

    # a cauda do limitador depois do fim, um resume do zero no meio e a liberacao: o bloco velho nao publica fim, nao
    # entrega a cauda antiga e nao consome o pedido de zerar o limitador da linha nova
    toca("d1")
    toca_ate_o_fim(E)
    with E._qlock:
        E._limitador.hist = np.full_like(E._limitador.hist, 0.5)
    s = Suspenso(E)
    E.resume()
    out = s.solta()
    confere(s.parou and not E.ended and E.pos == 0.0 and E._limitador_zera and not np.any(out),
            "a cauda do limitador suspensa e o resume do zero: o bloco velho nao publica o fim nem entrega a cauda")
    ate(lambda: E.status() == "playing")
    out = E._mixa(eng.BLOCK)
    confere(abs(E.pos - 0.01) < 1e-9 and not np.any(out), "e a linha nova comeca do zero, sem a cauda de antes")

    # o bloco que retirou o fim e o Repetir ligado no meio: a volta seguinte ja comecou, e o fim nao publica
    toca("d1")
    toca_ate_o_fim(E)
    with E._qlock:
        E.ended = False  # o fim ainda nao publicado
    s = Suspenso(E)
    E.set_loop(True)
    ate(lambda: len(E._q) > 0)
    s.solta()
    confere(s.parou and s.bloco.fim and not E.ended and E.status() == "playing",
            f"o Repetir ligado com o bloco do fim retirado: o fim nao publica, e a volta seguinte toca ({E.status()})")
    E.set_loop(False)

    # tocar com o Repetir pedido, com o disco de antes ja acabado: ele nao recomeca, e a posicao dele nao vira 0
    toca("d1", start=20.045)
    toca_ate_o_fim(E)
    A.lib.update("d1", last_pos=7.0)
    comeca, visto = E._comeca, []
    E._comeca = lambda leitor: (visto.append(E.loop), comeca(leitor))
    try:
        cmd.tocar(A, "d2", loop=True)
    finally:
        del E._comeca
    confere(no_prato(E) == "d2" and E.loop and A.lib.get("d1")["last_pos"] == 7.0,
            f"tocar com o Repetir depois do fim: o de antes nao recomeca nem grava 0 ({A.lib.get('d1')['last_pos']})")
    confere(visto == [True], f"e o Repetir ja esta ligado quando o leitor da faixa nova comeca ({visto})")
    E.load(arquivo(A, "d2"))
    confere(E.loop, "o mesmo disco de novo, sem o Repetir pedido: ele segue ligado")
    visto.clear()
    E._comeca = lambda leitor: (visto.append(E.loop), comeca(leitor))
    try:
        E.load(arquivo(A, "d1"))
    finally:
        del E._comeca
    confere(not E.loop and visto == [False],
            f"outro disco entrando, sem o Repetir pedido: ele desliga, na mesma publicacao da faixa ({visto})")
    E.set_loop(False)

    # a pausa pedida com o bloco do fim retirado: o fim a substitui, sem gravar posicao
    toca("d1")
    toca_ate_o_fim(E)
    A.lib.update("d1", last_pos=7.0)
    with E._qlock:
        E.ended = False
    s = Suspenso(E)
    res = []
    t = threading.Thread(target=lambda: res.append(cmd.pausar(A)))
    t.start()
    t.join(0.3)
    esperou = t.is_alive()
    s.solta()
    t.join(5)
    confere(s.parou and esperou and res == [False] and E.ended and A.lib.get("d1")["last_pos"] == 7.0,
            f"a pausa com o bloco do fim retirado espera ele, e o fim a substitui sem gravar a posicao ({res})")
    p = E.pause()
    confere(p.feita.is_set() and not p.ok and E.paused, "pausar o disco que ja acabou: nada para confirmar nem gravar")

    # o leitor que chega ao fim decide repetir no mesmo trecho em que o set_loop liga o Repetir
    toca("d1")
    with E._qlock:
        d, gen = E._deck, E._deck.gen
        d.eof_gen = -1
    E.set_loop(True)
    repete = E._repete(d, gen) and d.eof_gen == -1
    E.set_loop(False)
    confere(repete and not E._repete(d, gen) and d.eof_gen == gen and not E._repete(d, gen - 1),
            "o leitor no fim: com o Repetir, a volta seguinte; sem, o fim; o de um gen velho, nada")

    # a pausa com o prato sem bloco na fila, mas com a passagem soando (o que sai): ela espera esse bloco
    toca("d1")
    velho = eng.Deck(arquivo(A, "d3"))
    velho.q.extend((i * eng.BLOCK / eng.SR, np.full((eng.BLOCK, 2), 0.25, np.float32)) for i in range(10))
    with E._qlock:
        E._q.clear()
        E._deck.eof_gen = -1  # o leitor ainda le: o prato carregando
        E._saindo = [velho, 4800, 0, None, 0]
    s = Suspenso(E)
    p = E.pause()
    pendente = not p.feita.is_set() and not E.paused
    s.solta()
    confere(s.parou and pendente and p.ok and E.paused,
            "a pausa com so o que sai soando no bloco espera a publicacao dele, e so entao pausa")
    with E._qlock:
        E._saindo = None
    cmd.retomar(A)

    # a pausa confirmada guarda a faixa daquele instante
    toca("d1")
    p = E.pause()
    with E._qlock:
        E.track["title"] = "outro nome"  # o prato muda o dicionario dele depois
    confere(p.ok and p.track["title"] == "Disco d1", f"a pausa guarda a faixa do instante dela ({p.track['title']})")
    with E._qlock:
        E.track["title"] = "Disco d1"
    cmd.retomar(A)

    # o nome novo da prateleira entra na faixa do prato sob o _qlock, so se ela ainda e a mesma
    toca("d1")
    st, corpo = asyncio.run(asyncio.wait_for(pede_corpo(app, A, "PATCH", "/api/library/d1", {"title": "Novo d1"}), 5))
    confere(st == 200 and E.track["title"] == "Novo d1" and E._deck.track is E.track,
            f"o PATCH da prateleira poe o nome novo na faixa do prato ({st}, {E.track.get('title')})")
    A.lib.update("d1", title="Disco d1")

    # the routes that used to reach past the commands: the POST /api/library with play of a record already on the
    # shelf goes to the platter from the start (cmd.play_shelf_record: a short sound too, not on top, and not from
    # its last_pos), and the /api/settings music volume takes the command's rule
    toca("d1")
    A.lib.update("buzina", youtube_id="bbbbbbbbbb1", last_pos=1.5)
    sobre0 = len(A.sobre)
    st, corpo = asyncio.run(asyncio.wait_for(pede_corpo(app, A, "POST", "/api/library",
                                                         {"youtube_id": "bbbbbbbbbb1", "play": True}), 5))
    confere(st == 200 and (corpo.get("item") or {}).get("id") == "buzina" and no_prato(E) == "buzina"
            and E.pos < 0.5 and len(A.sobre) == sobre0,
            f"the POST /api/library with play of a short shelf sound puts it on the platter from the start ({st}, "
            f"{no_prato(E)}, {E.pos}, on top: {len(A.sobre) - sobre0})")
    # the record the route found is the one that plays, and the one it answers: a download that replaces the shelf
    # record right after the route found it doesn't put the replacement on the platter
    toca("d1")
    real_by_youtube, replaced = A.lib.by_youtube, []

    def found_then_replaced(yid):
        it = real_by_youtube(yid)
        if it is not None and not replaced:
            replaced.append(it)
            A.lib.add(dict(it, title="Replacement"))
        return it
    with mock.patch.object(A.lib, "by_youtube", found_then_replaced):
        st, corpo = asyncio.run(asyncio.wait_for(pede_corpo(app, A, "POST", "/api/library",
                                                             {"youtube_id": "bbbbbbbbbb1", "play": True}), 5))
    confere(st == 200 and replaced and (corpo.get("item") or {}).get("title") == "Disco buzina"
            and (E.track or {}).get("title") == "Disco buzina",
            f"the POST /api/library with play plays and answers the record it found, not a replacement "
            f"({st}, {(corpo.get('item') or {}).get('title')}, {(E.track or {}).get('title')})")
    A.lib.update("buzina", title="Disco buzina", youtube_id=None, last_pos=0)
    vol0 = E.vol
    st, _ = asyncio.run(asyncio.wait_for(pede_corpo(app, A, "POST", "/api/settings", {"vol": 0.25}), 5))
    confere(st == 200 and E.vol == 0.25 and A.cfg.get("vol") == 0.25,
            f"the /api/settings music volume goes through the command and is saved ({st}, {E.vol}, {A.cfg.get('vol')})")
    cmd.volume(A, vol0)

    # the download that fails stops the platter only while it still holds that job's record, with no stream and no
    # file, checked under the engine's lock (stop's pode)
    j = A.new_job("failing", True, "bbbbbbbbbbb")
    E.espera({"id": "job-falha", "title": "loading", "job": j["id"], "path": None, "stream": True,
              "youtube_id": None, "duration": None, "lufs": -14.0})
    with (mock.patch.object(A, "download", side_effect=RuntimeError("boom")),
          contextlib.redirect_stderr(io.StringIO())):
        A.run_download(j, "bbbbbbbbbbb")
    confere(E.track is None and j["status"] == "error",
            f"the failed download stops the platter that waited for it ({no_prato(E)}, {j['status']})")
    toca("d1")
    j = A.new_job("failing", True, "ccccccccccc")
    with (mock.patch.object(A, "download", side_effect=RuntimeError("boom")),
          contextlib.redirect_stderr(io.StringIO())):
        A.run_download(j, "ccccccccccc")
    confere(no_prato(E) == "d1" and E.status() == "playing",
            f"with another record on the platter, the failed download leaves it playing ({no_prato(E)}, {E.status()})")
    # the platter swaps before stop takes the engine's lock: stop's pode sees the new record
    j = A.new_job("failing", True, "ddddddddddd")
    E.espera({"id": "job-falha2", "title": "loading", "job": j["id"], "path": None, "stream": True,
              "youtube_id": None, "duration": None, "lufs": -14.0})
    real_stop = E.stop

    def stop_after_swap(*a, **kw):
        toca("d1")
        return real_stop(*a, **kw)
    with (mock.patch.object(A, "download", side_effect=RuntimeError("boom")),
          mock.patch.object(E, "stop", side_effect=stop_after_swap),
          contextlib.redirect_stderr(io.StringIO())):
        A.run_download(j, "ddddddddddd")
    confere(no_prato(E) == "d1" and E.status() == "playing" and j["status"] == "error",
            f"the platter swapped right before the stop: the failed download leaves the new record playing "
            f"({no_prato(E)}, {E.status()}, {j['status']})")
    # the other way round: a swap holds the engine's lock and is about to put this job's record on the platter when
    # the download fails; the stop waits for the lock and then sees the job's record, so it doesn't stay loading
    toca("d1")
    j = A.new_job("failing", True, "eeeeeeeeeee")
    job_track = {"id": "job-falha3", "title": "loading", "job": j["id"], "path": None, "stream": True,
                 "youtube_id": None, "duration": None, "lufs": -14.0}
    real_stop, calling = E.stop, threading.Event()

    def stop_called(*a, **kw):
        calling.set()
        return real_stop(*a, **kw)

    def failing_download():
        with (mock.patch.object(A, "download", side_effect=RuntimeError("boom")),
              contextlib.redirect_stderr(io.StringIO())):
            A.run_download(j, "eeeeeeeeeee")
    with mock.patch.object(E, "stop", side_effect=stop_called):
        with E._lock:  # the swap in the middle (espera takes the same RLock again)
            td, _ = em_thread(failing_download)
            if not calling.wait(5):
                confere(False, "the failed download never called stop before the swap published")
            E.espera(job_track)
        td.join(5)
    confere(not td.is_alive() and E.track is None and j["status"] == "error",
            f"a swap that publishes the job's record while the download fails: the stop sees it and the platter "
            f"doesn't stay loading ({no_prato(E)}, {E.status()}, {j['status']})")

    # o leitor de uma linha que ja acabou nao marca o fim nem o erro da linha nova
    toca("d1")
    with E._qlock:
        d, gen = E._deck, E._deck.gen
        d.eof_gen = -1
        E.set_error(None)
    E._fim_do_leitor(d, gen - 1, erro=(E.track, 0.0))
    confere(d.eof_gen == -1 and E.error is None, "o leitor de um gen velho nao marca o fim nem o erro")

    # a troca de disco com o bloco do prato em curso e a fila vazia: a posicao dele e gravada (ele estava tocando)
    toca("d1", start=20.045)
    with E._qlock:
        while len(E._q) > 1:
            E._q.pop()
        E._deck.eof_gen = -1  # o leitor ainda le
    A.lib.update("d1", last_pos=7.0)
    s = Suspenso(E)
    cmd.tocar(A, "d2")
    s.solta()
    confere(s.parou and A.lib.get("d1")["last_pos"] == 20.0,
            f"a troca com o bloco em curso e a fila vazia grava a posicao do que saiu ({A.lib.get('d1')['last_pos']})")

    # a pausa pelo /api/pause e pelo /api/toggle com o bloco retirado: ela espera a publicacao dele, sem prender o
    # laco, e a posicao publicada e a gravada sao a do fim dele
    def rota(caminho, res):
        res.append(asyncio.run(asyncio.wait_for(pede(app, A, "POST", caminho), 5)))

    for caminho in ("/api/pause", "/api/toggle"):
        toca("d1", start=20.045)
        s = Suspenso(E)

        async def corre(caminho=caminho, s=s):
            """O POST esperando a confirmacao e um GET /api/state no mesmo laco: ele responde com o POST pendente."""
            pausa = asyncio.ensure_future(pede(app, A, "POST", caminho))
            fim = time.monotonic() + 2
            while not (E._pausa is not None and not E._pausa.feita.is_set()) and time.monotonic() < fim:
                await asyncio.sleep(0.01)
            st, _ = await asyncio.wait_for(pede(app, A, "GET", "/api/state"), 2)
            livre = st == 200 and not pausa.done() and not E.paused  # pendente: o prato so pausa na confirmacao
            out = s.solta()
            return livre, out, await asyncio.wait_for(pausa, 5)
        esperou, out, res = asyncio.run(corre())
        pos = E.pos
        confere(s.parou and esperou and res[0] == 200 and abs(pos - 20.055) < 1e-9
                and A.lib.get("d1")["last_pos"] == round(pos, 1) == 20.1 and np.any(out),
                f"o {caminho} com o bloco retirado espera a publicacao dele sem prender o laco (o /api/state responde), "
                f"e a posicao gravada e a publicada ({pos}, {A.lib.get('d1')['last_pos']})")
        for _ in range(3):
            E._mixa(eng.BLOCK)
        confere(E.pos == pos and A.lib.get("d1")["last_pos"] == 20.1, "e as duas ficam paradas na pausa")
        del tiras[:]
        cmd.retomar(A)
        E._mixa(eng.BLOCK)
        confere(tiras and abs(tiras[0] - pos) < 1e-9, f"e a retomada comeca onde a pausa parou ({tiras[:1]})")

    # a mesma pausa com um load ou um resume antes de soltar o bloco: a espera termina, a linha nova segue e nenhuma
    # posicao antiga e gravada
    for nome, faz in (("load", lambda: E.load(arquivo(A, "d2"))), ("resume", E.resume),
                      ("seek", lambda: E.seek(5.0)), ("toggle", lambda: cmd.alternar(A))):
        toca("d1", start=20.045)
        A.lib.update("d1", last_pos=7.0)
        s = Suspenso(E)
        res = []
        t = threading.Thread(target=rota, args=("/api/pause", res))
        t.start()
        t.join(0.3)
        faz()
        t.join(2)
        terminou = not t.is_alive() and res and res[0][0] == 200
        out = s.solta()
        mesma = nome in ("resume", "toggle")  # retomar (o segundo toggle tambem) preserva a linha
        confere(s.parou and terminou and not E.paused and A.lib.get("d1")["last_pos"] == 7.0
                and no_prato(E) == ("d2" if nome == "load" else "d1"),
                f"o {nome} com a pausa esperando o bloco: a espera termina sem gravar a posicao, e o disco segue "
                f"sem pausar")
        confere(np.any(out) == mesma and not E.paused,
                f"e o bloco retirado {'publica (a mesma linha)' if mesma else 'sai (a linha mudou)'} sem pausar nada")

    # a troca de faixa entre a confirmacao da pausa e a gravacao: a posicao antiga nao e gravada
    toca("d1", start=20.045)
    A.lib.update("d1", last_pos=7.0)
    trava = A.lib.lock
    A.lib.lock = AntesDaTrava(trava, lambda: E.load(arquivo(A, "d2")))
    try:
        cmd.pausar(A)
    finally:
        A.lib.lock = trava
    confere(A.lib.get("d1")["last_pos"] == 7.0 and no_prato(E) == "d2" and not E.paused,
            "a troca de faixa entre a confirmacao da pausa e a gravacao: nada e gravado, e a faixa nova toca")
    del E._tira


class Segura:
    """O A.tocar_entrada do primeiro avanco parado (com a reserva ja feita) ate o solta(); quebra=True: depois de
    soltar, ele levanta o erro da entrada quebrada."""

    def __init__(self, A, quebra=False):
        self.A, self.dentro, self.libera, self.vez = A, threading.Event(), threading.Event(), [1]
        real = A.tocar_entrada

        def preso(x, **kw):
            if self.vez:
                self.vez.pop()
                self.dentro.set()
                self.libera.wait(5)
                if isinstance(quebra, Exception):
                    raise quebra
                if quebra:
                    raise ValueError("the queue entry has no video and no link")
            return real(x, **kw)
        A.tocar_entrada = preso

    def solta(self):
        self.libera.set()

    def fim(self):
        self.libera.set()
        del self.A.tocar_entrada  # volta o do App


def em_thread(f, *a, **kw):
    """f numa thread; volta (thread, lista com o resultado ou o erro)."""
    res = []

    def roda():
        try:
            res.append(f(*a, **kw))
        except Exception as ex:  # o erro vira o resultado
            res.append(ex)
    t = threading.Thread(target=roda)
    t.start()
    return t, res


def avanco(A, E):
    """A reserva de avanco por deck e linha: uma so em curso; o vigia cede, o Proximo e o enfileirar esperam o
    resultado dela sem prender o laco; a troca confere de novo a reserva, o deck, a linha e a entrada; a preparacao
    da passagem confere a reserva e a cabeca da fila ao publicar; e quem mexe no historico fecha antes a virada."""
    print("--- a reserva de avanco")
    app = server.build(A)

    def limpa():
        with E.state_section():
            E.drop_prepared()
        E.set_loop(False)
        E.virou = None
        cmd.limpar_fila(A)
        A.parado_sem_fila = None

    def toca(iid, start=0.0):
        cmd.tocar(A, iid, start=start)
        ate(lambda: E.status() == "playing")

    # o fim do disco e o enfileirar com o prato parado: quem reserva primeiro toca, e o outro cede ou espera
    limpa()
    toca("d1")
    toca_ate_o_fim(E)
    h0 = historico(A)
    s = Segura(A)
    try:
        t, res = em_thread(cmd.enfileirar, A, {"id": "d2"})
        s.dentro.wait(5)
        visto = A._volta_fila(None)
        cedeu = visto is None and A.parado_sem_fila is None and fila(A) == ["d2"]
        s.solta()
        t.join(5)
    finally:
        s.fim()
    confere(cedeu, "o enfileirar reservou o avanco do prato parado: o fim do disco (o vigia) cede a vez")
    confere(res and res[0][2] is True and no_prato(E) == "d2" and fila(A) == []
            and historico(A) == h0 + ["d1"][:int(h0[-1:] != ["d1"])],
            f"e a entrada nova toca uma vez, com o Anterior em ordem ({res and res[0][2]}, {no_prato(E)}, {fila(A)})")

    toca_ate_o_fim(E)
    x, _ = A.enfileirar({"id": "d3"})  # so na fila: o vigia e quem avanca para ela
    s = Segura(A)
    try:
        tv, rv = em_thread(A._volta_fila, None)
        s.dentro.wait(5)
        tq, rq = em_thread(cmd.enfileirar, A, {"id": "d1"})
        tq.join(0.3)
        esperou = tq.is_alive()
        s.solta()
        tv.join(5)
        tq.join(5)
    finally:
        s.fim()
    confere(esperou and rq and rq[0][2] is False and no_prato(E) == "d3" and fila(A) == ["d1"],
            f"o fim do disco reservou antes: o enfileirar espera o resultado, nao toca e so guarda "
            f"({rq and rq[0][2]}, {no_prato(E)}, {fila(A)})")

    # a entrada removida entre a preparacao e a virada: a passagem preparada para ela sai na hora
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    with contextlib.redirect_stderr(io.StringIO()):
        E.preparar(arquivo(A, "d2"), x["qid"])
        ate(lambda: E._virar_em is not None)
    cmd.tirar_da_fila(A, x["qid"])
    confere(E._pronto is None and E.pronto_tag is None, "tirar da fila a entrada preparada tira a passagem dela")
    toca_ate_o_fim(E)
    A._volta_fila(None)
    confere(E.virou is None and no_prato(E) == "d3" and fila(A) == [],
            f"e o fim do disco toca a seguinte, sem a removida ({no_prato(E)}, {fila(A)})")
    for nome, mexe in (("move a seguinte para a frente", lambda x, y: cmd.mover_na_fila(A, y["qid"], 0)),
                       ("limpa a fila", lambda x, y: cmd.limpar_fila(A))):
        limpa()
        toca("d1")
        x, _, _ = cmd.enfileirar(A, {"id": "d2"})
        y, _, _ = cmd.enfileirar(A, {"id": "d3"})
        with contextlib.redirect_stderr(io.StringIO()):
            E.preparar(arquivo(A, "d2"), x["qid"])
        mexe(x, y)
        confere(E._pronto is None, f"quem {nome} tambem tira a passagem preparada para a primeira de antes")

    # a publicacao tardia do _prepara: a fonte sai fora das travas, e a fila (ou o prato) muda nesse meio
    fonte = A.fonte_de

    def tardia(nome, mexe, publica=False, no_motor=False):
        """no_motor: a fila muda ja dentro do E.preparar, depois de conferir a primeira da fila e antes do _qlock."""
        limpa()
        toca("d1", start=100.0)
        x, _, _ = cmd.enfileirar(A, {"id": "d2"})
        y, _, _ = cmd.enfileirar(A, {"id": "d3"})
        preso, libera = threading.Event(), threading.Event()
        prepara = E.preparar

        def fonte_presa(q, shelf=None):
            preso.set()
            libera.wait(5)
            return fonte(q, shelf)

        def preparar_preso(*a, **kw):
            preso.set()
            libera.wait(5)
            return prepara(*a, **kw)
        if no_motor:
            E.preparar = preparar_preso
        else:
            A.fonte_de = fonte_presa
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                A._volta_passagem()
                preso.wait(5)
                tm, _ = em_thread(mexe, x, y)  # com a fila_lock na mao da preparacao, quem mexe na fila espera
                tm.join(0.3)
                libera.set()
                tm.join(5)
                ate(lambda: A.preparando is None)
        finally:
            libera.set()
            A.fonte_de = fonte
            if no_motor:
                del E.preparar
        ok = (E.pronto_tag == x["qid"]) if publica else (E.pronto_tag is None)
        confere(ok, f"a preparacao que termina depois que {nome}: {'publica' if publica else 'nao publica'} "
                    f"({E.pronto_tag}, {x['qid']})")
    tardia("nada mudou", lambda x, y: None, publica=True)
    tardia("a entrada saiu da fila", lambda x, y: cmd.tirar_da_fila(A, x["qid"]))
    tardia("outra passou para a frente", lambda x, y: cmd.mover_na_fila(A, y["qid"], 0))
    tardia("o Proximo tocou a entrada", lambda x, y: cmd.pular(A))
    tardia("o prato trocou de disco", lambda x, y: cmd.tocar(A, "d1"))
    tardia("o Repetir ligou", lambda x, y: E.set_loop(True))
    tardia("a entrada saiu da fila com a preparacao ja no motor", lambda x, y: cmd.tirar_da_fila(A, x["qid"]),
           no_motor=True)
    tardia("outra passou para a frente com a preparacao ja no motor", lambda x, y: cmd.mover_na_fila(A, y["qid"], 0),
           no_motor=True)

    # o Proximo concorrente: espera o resultado da mesma reserva sem prender o laco (o /api/state responde), e so uma
    # entrada sai da fila
    def dois_proximos(quebra=False, invalida=None):
        limpa()
        toca("d1")
        x, _, _ = cmd.enfileirar(A, {"id": "d2"})
        y, _, _ = cmd.enfileirar(A, {"id": "d3"})
        s, joined, wait = Segura(A, quebra=quebra), threading.Event(), cmd.Proximo.espera

        def joins(self, prazo=None):
            joined.set()
            return wait(self, prazo)
        try:
            async def corre():
                off = asyncio.get_running_loop().run_in_executor
                primeiro = asyncio.ensure_future(pede(app, A, "POST", "/api/next"))
                await off(None, s.dentro.wait, 5)
                with mock.patch.object(cmd.Proximo, "espera", joins):
                    segundo = asyncio.ensure_future(pede(app, A, "POST", "/api/next"))
                    await off(None, joined.wait, 5)
                    t0 = time.monotonic()
                    st, corpo = await asyncio.wait_for(pede(app, A, "GET", "/api/state"), 2)
                    livre = (st == 200 and time.monotonic() - t0 < 0.5, segundo.done())
                    if invalida is not None:
                        invalida()
                    s.solta()
                    return livre, await asyncio.wait_for(primeiro, 5), await asyncio.wait_for(segundo, 5)
            livre, primeiro, segundo = asyncio.run(corre())
        finally:
            s.fim()
        return x, y, livre, segundo, primeiro
    x, y, livre, segundo, res = dois_proximos()
    confere(livre == (True, False), f"com o Proximo esperando a reserva de outro, o /api/state responde ({livre})")
    confere(segundo[0] == res[0] == 200 and segundo[1]["entry"]["qid"] == res[1]["entry"]["qid"] == x["qid"]
            and no_prato(E) == "d2" and fila(A) == ["d3"],
            f"e os dois Proximos devolvem a mesma entrada: so uma sai da fila ({segundo[0]}, {fila(A)})")
    x, y, livre, segundo, res = dois_proximos(quebra=True)
    confere(segundo[0] == res[0] == 500 and segundo[1] == res[1] and res[1]["error"]["key"] == "server.queue.playFailed"
            and fila(A) == ["d3"],
            f"the broken entry: the Next that waited answers the same 500 and message as the first, and it leaves the "
            f"queue ({segundo}, {res}, {fila(A)})")
    refused = i18n.Recusa("server.queue.empty", "The queue is empty: there's no next record.")
    x, y, livre, segundo, res = dois_proximos(quebra=refused)
    confere(segundo[0] == res[0] == 500 and segundo[1] == res[1]
            and res[1]["error"]["params"]["reason"] == refused.msg and fila(A) == ["d3"],
            f"an entry refused with a message for the screen: both Nexts answer the failure, with its message as the "
            f"reason ({segundo}, {res}, {fila(A)})")
    x, y, livre, segundo, res = dois_proximos(invalida=lambda: E.load(arquivo(A, "d3")))
    confere(segundo[0] == res[0] == 409 and no_prato(E) == "d3" and fila(A) == ["d2", "d3"],
            f"o prato trocou no meio: a reserva invalidada nao toca nem tira a entrada, e libera quem esperava "
            f"({segundo[0]}, {no_prato(E)}, {fila(A)})")

    # o segundo Proximo chega com o primeiro ja trocando o disco (preso no E.load, com a fila_lock na mao): os dois
    # dividem o mesmo avanco, e so uma entrada sai da fila
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    carrega, no_load, libera = E.load, threading.Event(), threading.Event()

    def load_preso(*a, **kw):
        no_load.set()
        libera.wait(5)
        return carrega(*a, **kw)
    E.load = load_preso
    try:
        t1, r1 = em_thread(cmd.pular, A)
        no_load.wait(5)
        t2, r2 = em_thread(cmd.pular, A)
        t2.join(0.3)
        libera.set()
        t1.join(5)
        t2.join(5)
    finally:
        libera.set()
        del E.load
    confere(r1 and r2 and r1[0] is x and r2[0] is x and no_prato(E) == "d2" and fila(A) == ["d3"],
            f"o segundo Proximo com o primeiro no meio da troca: os dois devolvem a mesma entrada, e so ela sai da "
            f"fila ({no_prato(E)}, {fila(A)})")

    group, late = cmd.Proximo(None, 0), RuntimeError("the entry would not play")

    class TimesOut(threading.Event):
        def wait(self, timeout=None):
            group.resolve(None, late)
            return False
    group.feita = TimesOut()
    try:
        timed_out = group.espera(0.01)
    except cmd.QueuePlayFailed as ex:
        timed_out = ex
    confere(timed_out is None, f"a Next whose wait ran out answers no entry (the 409), even with the failure published "
                               f"right after the wait ({timed_out!r})")

    def joined_next_and_a_play_that_raises(stops, after=()):
        limpa()
        toca("d1")
        E.set_error(None)
        cmd.enfileirar(A, {"id": "d2"})
        cmd.enfileirar(A, {"id": "d3"})
        playing, joined, refused = threading.Event(), threading.Event(), RuntimeError("the entry would not play")
        group_waits = cmd.Proximo.espera

        def joins(group, prazo=None):
            joined.set()
            return group_waits(group, prazo)

        def raises(*a, **kw):
            playing.set()
            joined.wait(5)
            if stops:
                cmd.parar(A)
            for step in after:
                step()
            raise refused
        with mock.patch.object(cmd.Proximo, "espera", joins), mock.patch.object(A, "tocar_entrada", raises):
            t1, r1 = em_thread(cmd.pular, A)
            playing.wait(5)
            t2, r2 = em_thread(cmd.pular, A)
            t1.join(5)
            t2.join(5)
        same = (r1 == r2 == [None] and (E.error is None) == bool(after)) if stops else (
            len(r1) == len(r2) == 1 and all(type(r[0]) is cmd.QueuePlayFailed and r[0].__cause__ is refused
                                            for r in (r1, r2)) and r1[0].message == r2[0].message)
        return joined.is_set() and same, (r1, r2, no_prato(E), fila(A), E.error)
    same, seen = joined_next_and_a_play_that_raises(stops=False)
    confere(same and seen[2:4] == ("d1", ["d3"]),
            f"a Next joins one whose play raises: both get the same error, and only the entry that failed leaves the "
            f"queue {seen}")
    same, seen = joined_next_and_a_play_that_raises(stops=True)
    confere(same and seen[2] is None and seen[3] == ["d3"],
            f"a Next joins one whose play raises after a Stop resolved the advance: both get the Stop's result, and "
            f"the error goes to the screen {seen}")
    with contextlib.redirect_stderr(io.StringIO()):
        same, seen = joined_next_and_a_play_that_raises(stops=True, after=(lambda: cmd.tocar(A, "d1"),))
    confere(same and seen[2] == "d1" and seen[3] == ["d3"],
            f"a Next joins one whose play raises after a Stop and another record: both get the Stop's result, and the "
            f"error stays off the record playing now {seen}")
    with contextlib.redirect_stderr(io.StringIO()):
        same, seen = joined_next_and_a_play_that_raises(stops=True, after=(lambda: cmd.tocar(A, "d1"),
                                                                           lambda: cmd.parar(A)))
    confere(same and seen[2] is None and seen[3] == ["d3"],
            f"a Next joins one whose play raises after a Stop, another record and a second Stop: both get the first "
            f"Stop's result, and the error stays off the platter the second Stop left {seen}")

    # a fila muda no mesmo trecho do _qlock em que a passagem preparada sai: o motor, no bloco que chega bem nessa hora,
    # nao vira para a entrada que acabou de sair
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    with contextlib.redirect_stderr(io.StringIO()):
        E.preparar(arquivo(A, "d2"), x["qid"])
        ate(lambda: E._virar_em is not None)
    with E._qlock:
        E._virar_em = E.pos  # o proximo bloco vira
    blocos = []

    class Fila(list):
        def remove(self, v):  # o bloco do motor chega enquanto a entrada sai
            t = threading.Thread(target=E._mixa, args=(eng.BLOCK,))
            t.start()
            t.join(0.2)
            blocos.append(t)
            super().remove(v)
    with A.fila_lock:
        A.fila = Fila(A.fila)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            cmd.tirar_da_fila(A, x["qid"])
            for t in blocos:
                t.join(5)
    finally:
        with A.fila_lock:
            A.fila = list(A.fila)
    confere(blocos and E.virou is None and no_prato(E) == "d1" and E._pronto is None and fila(A) == ["d3"],
            f"tirar da fila a preparada bem quando o motor ia virar: ele nao vira para ela ({no_prato(E)}, "
            f"{E.virou is not None})")

    # a preparacao da proxima publica sob a fila_lock: com o Parar no meio (a virada fechada, o stop ainda por vir),
    # ela espera, e depois o prato ja nao e o que ela viu
    limpa()
    toca("d1", start=100.0)
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    para, no_stop, libera = E.stop, threading.Event(), threading.Event()

    def stop_preso(*a, **kw):
        no_stop.set()
        libera.wait(5)
        return para(*a, **kw)
    E.stop = stop_preso
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            tp, _ = em_thread(cmd.parar, A)
            no_stop.wait(5)
            cap = E.captura()
            tq, res_q = em_thread(A._prepara, cap.track, x, dict(x), cap)
            tq.join(0.3)
            publicou = E._pronto is not None
            libera.set()
            tp.join(5)
            tq.join(5)
    finally:
        libera.set()
        del E.stop
    confere(res_q == [None] and not publicou and E._pronto is None and E.pronto_tag is None and E.track is None,
            f"a preparacao que chega com o Parar no meio nao publica, nem antes nem depois do stop ({publicou}, {res_q})")

    # o Proximo esperando o _lock do motor (na mao de outra thread, como na troca de aparelho) nao segura a fila_lock:
    # o /api/state responde, e o Proximo toca quando o _lock sai
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    segura, solta = threading.Event(), threading.Event()

    def dono():
        with E._lock:
            segura.set()
            solta.wait(5)
    th = threading.Thread(target=dono)
    th.start()
    segura.wait(5)
    try:
        t, res = em_thread(cmd.pular, A)
        t.join(0.2)
        t0 = time.monotonic()
        try:
            st, _ = asyncio.run(asyncio.wait_for(pede(app, A, "GET", "/api/state"), 2))
        except asyncio.TimeoutError:
            st = None
        livre = st == 200 and time.monotonic() - t0 < 0.5 and not res
    finally:
        solta.set()
        th.join(5)
        t.join(5)
    confere(livre and res and res[0] is x and no_prato(E) == "d2" and fila(A) == ["d3"],
            f"com o Proximo esperando o _lock do motor, o /api/state responde, e o Proximo toca depois "
            f"({livre}, {no_prato(E)}, {fila(A)})")

    # a reserva velha que falha nao tira a entrada da reserva nova (o prato mudou de linha no meio: um seek)
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    real = A.tocar_entrada
    dentro, portas, vez = [threading.Event(), threading.Event()], [threading.Event(), threading.Event()], [0]

    def preso(xx, **kw):
        i = vez[0]
        vez[0] += 1
        dentro[i].set()
        portas[i].wait(5)
        if i == 0:
            raise ValueError("the queue entry has no video and no link")
        return real(xx, **kw)
    A.tocar_entrada = preso
    try:
        t1, r1 = em_thread(cmd.pular, A)
        dentro[0].wait(5)
        E.seek(10.0)
        t2, r2 = em_thread(cmd.avanca, A)
        dentro[1].wait(5)
        portas[0].set()
        t1.join(5)
        ficou = fila(A) == ["d2", "d3"]
        portas[1].set()
        t2.join(5)
    finally:
        for porta in portas:
            porta.set()
        del A.tocar_entrada
    confere(ficou and r1 and isinstance(r1[0], cmd.QueuePlayFailed) and isinstance(r1[0].__cause__, ValueError) and r2 and r2[0] is x and no_prato(E) == "d2"
            and fila(A) == ["d3"],
            f"a reserva velha que falha deixa na fila a entrada da reserva nova, que toca ({ficou}, {no_prato(E)}, "
            f"{fila(A)})")

    # a gravacao da posicao que falha depois de tocar: o avanco tocou, e volta a entrada
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})

    def grava_falha(*a, **kw):
        raise OSError("disk full")
    A.remember_pos = grava_falha
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            r = cmd.pular(A)
    except OSError as ex:
        r = ex
    finally:
        del A.remember_pos
    confere(r is x and no_prato(E) == "d2" and fila(A) == [] and A.reserva is None,
            f"a gravacao da posicao que falha depois da troca nao desfaz o avanco ({r!r})")

    # a parecida sem stream, com o avanco de outro em curso nesta linha: espera o resultado dele, e se ele falha (com a
    # fila ainda com entradas), avanca ela mesma, em vez de deixar o prato carregando
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    tr = {"id": "ccccccccccc", "title": "parecida", "channel": None, "thumb": None, "duration": 120.0,
          "youtube_id": "ccccccccccc", "alvo": None, "path": None, "stream": True, "job": None, "auto": True}
    E.espera(tr)
    with A.fila_lock, E._qlock:
        r = A.reserva = cmd.Reserva(E._deck, E._deck.linha, x)
    with contextlib.redirect_stderr(io.StringIO()):
        t, _ = em_thread(A._abre_stream, tr, "ccccccccccc", True)
        t.join(0.3)
        esperou = t.is_alive() and E.track is tr
        with A.fila_lock:
            A.release_reservation(r, None)
        t.join(5)
    confere(esperou and no_prato(E) == "d2" and fila(A) == [],
            f"a parecida sem stream espera o avanco de outro, e com ele falhando toca a seguinte ({esperou}, "
            f"{no_prato(E)}, {fila(A)})")

    # o POST /api/queue poe na fila no laco do servidor, como o tocar e a prateleira (a procura do download do mesmo
    # video e a criacao de um novo nao correm com outro pedido), e so o tocar na hora vai ao executor
    limpa()
    toca("d1")
    onde, poe = [], cmd.poe_na_fila

    def poe_visto(*a, **kw):
        onde.append(threading.current_thread() is threading.main_thread())
        return poe(*a, **kw)
    with mock.patch.object(server.cmd, "poe_na_fila", side_effect=poe_visto), mock.patch.object(server.pool, "submit"):
        st, _ = asyncio.run(asyncio.wait_for(pede_corpo(app, A, "POST", "/api/queue", {"youtube_id": "eeeeeeeeeee"}),
                                             5))
    for k in [k for k, j in A.jobs.items() if j.get("alvo") == "eeeeeeeeeee"]:
        del A.jobs[k]
    confere(st == 200 and onde == [True], f"o POST /api/queue poe na fila no laco do servidor ({st}, {onde})")

    # o enfileirar com o prato parado que esperou a reserva do vigia, e ela quebrou: a vez e dele, e a entrada toca
    limpa()
    toca("d1")
    toca_ate_o_fim(E)
    with A.fila_lock:
        A.fila.append({"id": None, "youtube_id": None, "url": None, "title": "quebrada", "qid": "q9", "job": None})
    s = Segura(A, quebra=True)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            tv, _ = em_thread(A._volta_fila, None)
            s.dentro.wait(5)
            tq, rq = em_thread(cmd.enfileirar, A, {"id": "d2"})
            tq.join(0.3)
            s.solta()
            tv.join(5)
            tq.join(5)
    finally:
        s.fim()
    E.set_error(None)
    confere(rq and rq[0][2] is True and no_prato(E) == "d2" and fila(A) == [],
            f"o enfileirar que esperou a reserva do vigia, e ela quebrou: a entrada nova toca ({rq and rq[0][2]}, "
            f"{no_prato(E)}, {fila(A)})")

    # o Automatico nao reordena a primeira da fila que um avanco reservado vai tocar
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    with mock.patch.object(eng, "TRANS_PREP_S", 10):
        with A.fila_lock:
            antes = A.automatico.head_held()
            with E._qlock:
                r = A.reserva = cmd.Reserva(E._deck, E._deck.linha, x)
            reservada = A.automatico.head_held()
            A.release_reservation(r, None)
            depois = A.automatico.head_held()
    confere(not antes and reservada and not depois,
            f"a primeira da fila com um avanco reservado nao troca no Automatico ({antes}, {reservada}, {depois})")

    # a troca sem reserva (o tocar da prateleira) e o Parar soltam a reserva em curso: quem espera nao espera mais
    for nome, faz in (("o tocar da prateleira", lambda: cmd.tocar(A, "d3")), ("o Parar", lambda: cmd.parar(A))):
        limpa()
        toca("d1")
        x, _, _ = cmd.enfileirar(A, {"id": "d2"})
        with A.fila_lock, E._qlock:
            r = A.reserva = cmd.Reserva(E._deck, E._deck.linha, x)
        faz()
        confere(r.feita.is_set() and r.entrada is None and A.reserva is None,
                f"{nome} solta a reserva de avanco em curso ({r.feita.is_set()})")

    # o Proximo que chega com o fim do disco (o vigia) ja trocando o disco: espera o resultado dele, sem pular a
    # seguinte
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    toca_ate_o_fim(E)
    carrega, no_load, libera = E.load, threading.Event(), threading.Event()

    def load_preso(*a, **kw):
        no_load.set()
        libera.wait(5)
        return carrega(*a, **kw)
    E.load = load_preso
    try:
        tv, _ = em_thread(A._volta_fila, None)
        no_load.wait(5)
        tp, rp = em_thread(cmd.pular, A)
        tp.join(0.3)
        libera.set()
        tv.join(5)
        tp.join(5)
    finally:
        libera.set()
        del E.load
    confere(rp and rp[0] is x and no_prato(E) == "d2" and fila(A) == ["d3"],
            f"o Proximo com o fim do disco no meio da troca: devolve a entrada dele, sem pular a seguinte "
            f"({no_prato(E)}, {fila(A)})")

    # a parecida sem stream nao para o prato com um avanco de outro ainda em curso nesta linha (a fila ja vazia)
    limpa()
    toca("d1")
    x = {"id": "d2", "qid": "zz"}
    tr = {"id": "ccccccccccc", "title": "parecida", "channel": None, "thumb": None, "duration": 120.0,
          "youtube_id": "ccccccccccc", "alvo": None, "path": None, "stream": True, "job": None, "auto": True}
    E.espera(tr)
    with A.fila_lock, E._qlock:
        r = A.reserva = cmd.Reserva(E._deck, E._deck.linha, x)
    with mock.patch.object(cmd, "AVANCO_ESPERA_S", 0.05), contextlib.redirect_stderr(io.StringIO()):
        A._abre_stream(tr, "ccccccccccc", True)
    ficou = E.track is tr
    with A.fila_lock:
        A.release_reservation(r, None)
    confere(ficou, "a parecida sem stream que esperou o avanco de outro ate o prazo nao para o prato com ele em curso")

    # nem com uma entrada que chegou na fila depois do avanco vazio: o stop confere a fila no trecho do _qlock dele
    limpa()
    toca("d1")
    E.espera(tr)
    para, vez = E.stop, []

    def stop_com_entrada(*a, **kw):
        if not vez:
            vez.append(cmd.poe_na_fila(A, {"id": "d2"}))  # o POST /api/queue bem antes do stop
        return para(*a, **kw)
    E.stop = stop_com_entrada
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            A._abre_stream(tr, "ccccccccccc", True)
    finally:
        del E.stop
    confere(vez and no_prato(E) == "d2" and fila(A) == [],
            f"a parecida sem stream com uma entrada chegando antes do stop: ela toca ({no_prato(E)}, {fila(A)})")

    # o Anterior decide com o prato que viu sem virada: a passagem sai ali, e o motor nao vira entre a escolha e a troca
    limpa()
    toca("d1", start=50.0)
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    with contextlib.redirect_stderr(io.StringIO()):
        E.preparar(arquivo(A, "d2"), x["qid"])
        ate(lambda: E._virar_em is not None)
    seek, antes_do_seek = E.seek, []

    def seek_depois_do_bloco(t, pode=None):  # o bloco que viraria chega entre a escolha do Anterior e o seek
        antes_do_seek.append(E._pronto is not None)
        with E._qlock:
            E._virar_em = E.pos
        E._mixa(eng.BLOCK)
        return seek(t, pode=pode)
    E.seek = seek_depois_do_bloco
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            feito = cmd.voltar(A)
    finally:
        del E.seek
    confere(antes_do_seek == [False] and feito == "inicio" and no_prato(E) == "d1" and E.virou is None
            and fila(A) == ["d2"],
            f"o Anterior com a passagem preparada decide com o prato que viu: volta ao comeco dele ({feito}, "
            f"{no_prato(E)}, {fila(A)})")

    # o Automatico com o prato parado e a fila ja com uma parecida, sem parecida nova nesta volta: ela toca
    limpa()
    toca("d1")
    toca_ate_o_fim(E)
    A._volta_fila(None)
    marcado = A.parado_sem_fila is E.track
    with A.fila_lock:
        A.fila.append({"id": "d3", "youtube_id": None, "url": None, "title": "Disco d3", "duration": 120.0,
                       "job": None, "qid": "pz", "auto": True, "fixa": True, "auto_de": "semente"})
    A.automatico._auto, A.automatico._semente, A.automatico._mix, A.automatico._ponte = True, {"youtube_id": "bbbbbbbbbbb", "title": "semente"}, [], None
    try:
        A.automatico.auto_round((E.track or {}).get("youtube_id"), None)
    finally:
        A.automatico._auto = False
    confere(marcado and no_prato(E) == "d3" and fila(A) == [] and A.parado_sem_fila is None,
            f"o Automatico com o prato parado e a parecida ja na fila: ela toca ({no_prato(E)}, {fila(A)})")

    # a reserva que ja nao vale (o prato mudou de linha) nao tira a passagem preparada da linha nova ao ser recusada
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    s = Segura(A)
    try:
        t, res = em_thread(cmd.pular, A)
        s.dentro.wait(5)
        E.seek(10.0)
        with contextlib.redirect_stderr(io.StringIO()):
            E.preparar(arquivo(A, "d2"), x["qid"])
        s.solta()
        t.join(5)
    finally:
        s.fim()
    confere(res and res[0] is None and E.pronto_tag == x["qid"] and no_prato(E) == "d1" and fila(A) == ["d2", "d3"],
            f"a reserva recusada por outra linha deixa a passagem preparada nela ({E.pronto_tag}, {no_prato(E)})")

    # o enfileirar que esperava o vigia, com o Parar no meio: o prato fica parado, e a entrada so entra na fila
    limpa()
    toca("d1")
    A.enfileirar({"id": "d2"})
    toca_ate_o_fim(E)
    s = Segura(A)
    try:
        tv, _ = em_thread(A._volta_fila, None)
        s.dentro.wait(5)
        tq, rq = em_thread(cmd.enfileirar, A, {"id": "d3"})
        tq.join(0.3)
        cmd.parar(A)
        tq.join(5)
        s.solta()
        tv.join(5)
    finally:
        s.fim()
    confere(rq and rq[0][2] is False and E.track is None and fila(A) == ["d2", "d3"],
            f"o enfileirar com o Parar no meio da reserva do vigia nao toca por cima do Parar ({rq and rq[0][2]}, "
            f"{no_prato(E)}, {fila(A)})")

    # o Proximo que chega com o load do vigia ja publicado e a troca ainda por confirmar: espera por ela, sem pular a
    # entrada que o vigia acabou de pôr no prato
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    toca_ate_o_fim(E)
    carrega, publicou, libera = E.load, threading.Event(), threading.Event()

    def load_publicado(*a, **kw):
        cap = carrega(*a, **kw)
        publicou.set()
        libera.wait(5)
        return cap
    E.load = load_publicado
    try:
        tv, _ = em_thread(A._volta_fila, None)
        publicou.wait(5)
        tp, rp = em_thread(cmd.pular, A)
        tp.join(0.3)
        libera.set()
        tv.join(5)
        tp.join(5)
    finally:
        libera.set()
        del E.load
    confere(rp and rp[0] is x and no_prato(E) == "d2" and fila(A) == ["d3"],
            f"o Proximo com a troca do vigia publicada e por confirmar: devolve a entrada dele ({no_prato(E)}, "
            f"{fila(A)})")

    # o Proximo depois de um Parar nao herda o avanco de um Proximo de antes dele, que ja nao vale
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    s = Segura(A)
    try:
        t1, r1 = em_thread(cmd.pular, A)
        s.dentro.wait(5)
        cmd.parar(A)
        t2, r2 = em_thread(cmd.pular, A)
        t2.join(5)
        s.solta()
        t1.join(5)
    finally:
        s.fim()
    confere(r2 and r2[0] is x and r1 and r1[0] is None and no_prato(E) == "d2" and fila(A) == [],
            f"o Proximo depois de um Parar toca a primeira, sem esperar o Proximo de antes ({no_prato(E)}, {fila(A)})")

    # o enfileirar decide com o prato visto logo depois de a entrada entrar: o Parar que chega antes da thread nao vira
    # um tocar (e a rota passa a captura do laco)
    limpa()
    toca("d1")
    x, _ = cmd.poe_na_fila(A, {"id": "d2"})
    cap = E.captura()
    cmd.parar(A)
    tocou = cmd.toca_se_parado(A, x, cap)
    confere(not tocou and E.track is None and fila(A) == ["d2"],
            f"o enfileirar com o prato tocando e o Parar logo depois so guarda a entrada ({tocou}, {fila(A)})")
    visto = []
    with mock.patch.object(server.cmd, "toca_se_parado", side_effect=lambda A_, x_, c: visto.append(c) or False):
        st, _ = asyncio.run(asyncio.wait_for(pede_corpo(app, A, "POST", "/api/queue", {"id": "d3"}), 5))
    confere(st == 200 and len(visto) == 1 and isinstance(visto[0], eng.Captura),
            f"o POST /api/queue passa ao executor o prato visto no laco ({st}, {visto})")

    # o Proximo que ainda termina (gravando a posicao) depois de um Parar: o Proximo novo nao se junta a ele
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    grava, gravando, libera = A.remember_pos, threading.Event(), threading.Event()

    def grava_presa(*a, **kw):
        gravando.set()
        libera.wait(5)
        return grava(*a, **kw)
    A.remember_pos = grava_presa
    try:
        t1, r1 = em_thread(cmd.pular, A)
        gravando.wait(5)
        del A.remember_pos
        cmd.parar(A)
        t2, r2 = em_thread(cmd.pular, A)
        t2.join(5)
        libera.set()
        t1.join(5)
    finally:
        libera.set()
        if "remember_pos" in vars(A):
            del A.remember_pos
    confere(r1 and r1[0] is x and r2 and r2[0] is y and no_prato(E) == "d3" and fila(A) == [],
            f"o Proximo depois de um Parar, com o de antes ainda gravando: toca a seguinte ({no_prato(E)}, {fila(A)})")

    # o Proximo e o Parar no meio, entre o Proximo ver o prato e reservar: o prato fica parado
    avanca, no_avanco, libera, so_se = cmd.avanca, threading.Event(), threading.Event(), [lambda kw: True]

    def avanca_preso(*a, **kw):  # o primeiro cmd.avanca que so_se aceita para ali
        if not no_avanco.is_set() and so_se[0](kw):
            no_avanco.set()
            libera.wait(5)
        return avanca(*a, **kw)
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    with mock.patch.object(cmd, "avanca", side_effect=avanca_preso):
        t, res = em_thread(cmd.pular, A)
        no_avanco.wait(5)
        cmd.parar(A)
        libera.set()
        t.join(5)
    confere(res and res[0] is None and E.track is None and fila(A) == ["d2"],
            f"o Proximo com o Parar entre ver o prato e reservar: o prato fica parado ({no_prato(E)}, {fila(A)})")
    no_avanco.clear()
    libera.clear()
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    with mock.patch.object(cmd, "avanca", side_effect=avanca_preso):
        t, res = em_thread(cmd.pular, A)
        no_avanco.wait(5)
        E.seek(1.0)  # o mesmo disco numa linha nova: nao e um Parar
        libera.set()
        t.join(5)
    confere(res and res[0] is x and no_prato(E) == "d2" and fila(A) == [],
            f"o Proximo com um seek entre ver o prato e reservar: segue para a primeira ({no_prato(E)}, {fila(A)})")

    # o Proximo que encontra o fim do disco (o vigia) no meio da troca e o vigia terminando antes de ele reservar: o
    # avanco do vigia e o dele
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    toca_ate_o_fim(E)
    carrega, no_load, solta_load = E.load, threading.Event(), threading.Event()
    no_avanco.clear()
    libera.clear()
    so_se[0] = lambda kw: kw.get("pular")  # so o do Proximo para

    def load_preso(*a, **kw):
        no_load.set()
        solta_load.wait(5)
        return carrega(*a, **kw)
    E.load = load_preso
    try:
        with mock.patch.object(cmd, "avanca", side_effect=avanca_preso):
            tv, _ = em_thread(A._volta_fila, None)
            no_load.wait(5)
            tp, rp = em_thread(cmd.pular, A)
            tp.join(0.2)
            solta_load.set()  # o vigia termina a troca antes de o Proximo reservar
            tv.join(5)
            libera.set()
            tp.join(5)
    finally:
        solta_load.set()
        del E.load
    confere(rp and rp[0] is x and no_prato(E) == "d2" and fila(A) == ["d3"],
            f"o Proximo com o fim do disco no meio da troca e terminando antes dele: devolve a entrada do fim do "
            f"disco ({no_prato(E)}, {fila(A)})")

    # o Proximo que viu a virada pendente, com o vigia conciliando antes dele: devolve a entrada que entrou nela
    no_avanco.clear()
    libera.clear()
    so_se[0] = lambda kw: True
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    with contextlib.redirect_stderr(io.StringIO()):
        E.preparar(arquivo(A, "d2"), x["qid"])
        ate(lambda: E._virar_em is not None)
        with E._qlock:
            E._virar_em = E.pos
        E._mixa(eng.BLOCK)
    pend = E.virou is not None
    with mock.patch.object(cmd, "avanca", side_effect=avanca_preso):
        t, res = em_thread(cmd.pular, A)
        no_avanco.wait(5)
        avanca(A, virada=E.virou)  # o vigia concilia a virada primeiro
        libera.set()
        t.join(5)
    confere(pend and res and res[0] is x and no_prato(E) == "d2" and fila(A) == ["d3"],
            f"o Proximo que viu a virada pendente, com o vigia conciliando antes: devolve a entrada dela "
            f"({no_prato(E)}, {fila(A)})")

    # o Proximo que chega antes de o fim do disco (o vigia) reservar, e o vigia reservando e tocando antes de ele pegar a
    # fila_lock: o avanco do vigia e o dele (nem 409, nem pular a seguinte)
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    toca_ate_o_fim(E)
    no_avanco.clear()
    libera.clear()
    so_se[0] = lambda kw: kw.get("pular")
    with mock.patch.object(cmd, "avanca", side_effect=avanca_preso):
        tp, rp = em_thread(cmd.pular, A)
        no_avanco.wait(5)
        A._volta_fila(None)
        libera.set()
        tp.join(5)
    confere(rp and rp[0] is x and no_prato(E) == "d2" and fila(A) == ["d3"],
            f"o Proximo com o fim do disco reservando e tocando antes dele: devolve a entrada do fim do disco "
            f"({no_prato(E)}, {fila(A)})")

    # o segundo Proximo que chega com o primeiro gravando a posicao (sem Parar no meio) divide o mesmo avanco: volta
    # na hora com a mesma entrada, sem pular a seguinte
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    grava, gravando, libera_grava = A.remember_pos, threading.Event(), threading.Event()

    def grava_presa3(*a, **kw):
        gravando.set()
        libera_grava.wait(5)
        return grava(*a, **kw)
    A.remember_pos = grava_presa3
    try:
        t1, r1 = em_thread(cmd.pular, A)
        gravando.wait(5)
        t2, r2 = em_thread(cmd.pular, A)
        t2.join(0.5)
        antes = list(r2)
        libera_grava.set()
        t1.join(5)
        t2.join(5)
    finally:
        libera_grava.set()
        del A.remember_pos
    confere(antes and antes[0] is x and r1 and r1[0] is x and no_prato(E) == "d2" and fila(A) == ["d3"],
            f"o segundo Proximo com o primeiro gravando a posicao: a mesma entrada, na hora "
            f"({antes and (antes[0] or {}).get('id')}, {no_prato(E)}, {fila(A)})")

    # o segundo Proximo do mesmo avanco (juntou-se com o primeiro ainda no load) volta quando a reserva resolve, sem
    # esperar o primeiro gravar a posicao
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    grava, gravando, libera_grava = A.remember_pos, threading.Event(), threading.Event()
    carrega, no_load, solta_load = E.load, threading.Event(), threading.Event()

    def grava_presa2(*a, **kw):
        gravando.set()
        libera_grava.wait(5)
        return grava(*a, **kw)

    def load_preso2(*a, **kw):
        no_load.set()
        solta_load.wait(5)
        return carrega(*a, **kw)
    A.remember_pos, E.load = grava_presa2, load_preso2
    try:
        t1, r1 = em_thread(cmd.pular, A)
        no_load.wait(5)
        t2, r2 = em_thread(cmd.pular, A)
        t2.join(0.2)
        solta_load.set()
        gravando.wait(5)
        t2.join(0.5)
        antes = list(r2)
        libera_grava.set()
        t1.join(5)
        t2.join(5)
    finally:
        solta_load.set()
        libera_grava.set()
        del A.remember_pos, E.load
    confere(antes and antes[0] is x and r1 and r1[0] is x and no_prato(E) == "d2" and fila(A) == [],
            f"o segundo Proximo volta com a reserva resolvida, antes de o primeiro gravar a posicao "
            f"({antes and (antes[0] or {}).get('id')}, {r1 and (r1[0] or {}).get('id')}, {no_prato(E)}, {fila(A)})")

    # o Proximo que outro avanco ja ligou nao troca de avanco: o do fim do disco falhou (a entrada saiu), e o seguinte
    # do vigia nao vira o dele (o grupo responde o mesmo para todos)
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    toca_ate_o_fim(E)
    no_avanco.clear()
    libera.clear()
    so_se[0] = lambda kw: kw.get("pular")
    with mock.patch.object(cmd, "avanca", side_effect=avanca_preso):
        tp, rp = em_thread(cmd.pular, A)
        no_avanco.wait(5)
        s1 = Segura(A)
        try:
            tv, _ = em_thread(A._volta_fila, None)
            s1.dentro.wait(5)
            cmd.tirar_da_fila(A, x["qid"])
            s1.solta()
            tv.join(5)
        finally:
            s1.fim()
        s2 = Segura(A)
        try:
            tv, _ = em_thread(A._volta_fila, None)
            s2.dentro.wait(5)
            libera.set()
            tp.join(1)
            cedo = list(rp)
            s2.solta()
            tv.join(5)
            tp.join(5)
        finally:
            s2.fim()
    confere(cedo and cedo[0] is None and no_prato(E) == "d3" and fila(A) == [],
            f"o Proximo ligado ao avanco que falhou responde o resultado dele, sem trocar pelo seguinte "
            f"({cedo and (cedo[0] or {}).get('id')}, {no_prato(E)}, {fila(A)})")

    # o grupo que escolheu a virada pendente nao e ligado por uma reserva que outro cria na linha dele: o seguidor
    # responde a entrada da virada, como o primeiro
    no_avanco.clear()
    libera.clear()
    so_se[0] = lambda kw: "virada" in kw
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    with contextlib.redirect_stderr(io.StringIO()):
        E.preparar(arquivo(A, "d2"), x["qid"])
        ate(lambda: E._virar_em is not None)
        with E._qlock:
            E._virar_em = E.pos
        E._mixa(eng.BLOCK)
    with mock.patch.object(cmd, "avanca", side_effect=avanca_preso):
        t1, r1 = em_thread(cmd.pular, A)
        no_avanco.wait(5)
        t2, r2 = em_thread(cmd.pular, A)
        t2.join(0.2)
        avanca(A)  # outro avanco nesta linha (como o do fim do disco): concilia a virada e reserva a seguinte
        libera.set()
        t1.join(5)
        t2.join(5)
    confere(r1 and r1[0] is x and r2 and r2[0] is x,
            f"o grupo da virada pendente responde a entrada dela para todos ({r1 and (r1[0] or {}).get('id')}, "
            f"{r2 and (r2[0] or {}).get('id')})")

    # dois Proximos com a virada no meio: o primeiro (que viu o prato antes dela) concilia a virada, e o segundo, que
    # chega enquanto ele concilia, se junta a ele (os dois devolvem a entrada da virada)
    no_avanco.clear()
    libera.clear()
    so_se[0] = lambda kw: kw.get("pular")
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    fecha, fechando, solta_fecha = cmd.fecha_virada, threading.Event(), threading.Event()

    def fecha_presa(*a, **kw):
        fechando.set()
        solta_fecha.wait(5)
        return fecha(*a, **kw)
    with contextlib.redirect_stderr(io.StringIO()):
        E.preparar(arquivo(A, "d2"), x["qid"])
        ate(lambda: E._virar_em is not None)
    with mock.patch.object(cmd, "avanca", side_effect=avanca_preso):
        t1, r1 = em_thread(cmd.pular, A)
        no_avanco.wait(5)
        with E._qlock:
            E._virar_em = E.pos
        with contextlib.redirect_stderr(io.StringIO()):
            E._mixa(eng.BLOCK)  # a virada chega depois de o primeiro ver o prato
        with mock.patch.object(cmd, "fecha_virada", side_effect=fecha_presa):
            libera.set()
            fechando.wait(5)
            t2, r2 = em_thread(cmd.pular, A)
            t2.join(0.3)
            solta_fecha.set()
            t1.join(5)
            t2.join(5)
    confere(r1 and r1[0] is x and r2 and r2[0] is x and no_prato(E) == "d2" and fila(A) == ["d3"],
            f"dois Proximos com a virada no meio: os dois devolvem a entrada dela ({r2 and (r2[0] or {}).get('id')}, "
            f"{no_prato(E)}, {fila(A)})")

    # o grupo ja ligado ao avanco do fim do disco nao troca por uma virada que aparece depois
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    toca_ate_o_fim(E)
    no_avanco.clear()
    libera.clear()
    so_se[0] = lambda kw: kw.get("pular")
    with mock.patch.object(cmd, "avanca", side_effect=avanca_preso):
        tp, rp = em_thread(cmd.pular, A)
        no_avanco.wait(5)
        A._volta_fila(None)  # o fim do disco toca a d2 e liga o grupo do Proximo
        with E._qlock:
            E.virou = (dict(E.track), dict(arquivo(A, "d3")), y["qid"])  # e uma virada aparece antes de ele seguir
        libera.set()
        tp.join(5)
    E.virou = None
    confere(rp and rp[0] is x and fila(A) == ["d3"],
            f"o grupo ligado ao fim do disco devolve a entrada dele, sem trocar por uma virada que veio depois "
            f"({rp and (rp[0] or {}).get('id')}, {fila(A)})")

    # o Proximo que viu a virada sem a entrada dela na fila e o fim do disco tocando a primeira antes dele: o avanco do
    # fim do disco e o dele (nem 409)
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    y, _, _ = cmd.enfileirar(A, {"id": "d3"})
    with contextlib.redirect_stderr(io.StringIO()):
        E.preparar(arquivo(A, "d2"), x["qid"])
        ate(lambda: E._virar_em is not None)
        with E._qlock:
            E._virar_em = E.pos
        E._mixa(eng.BLOCK)
    with A.fila_lock:
        A.remove_from_queue(x)  # a entrada da virada saiu da fila antes de conciliar
    no_avanco.clear()
    libera.clear()
    so_se[0] = lambda kw: kw.get("pular")
    with mock.patch.object(cmd, "avanca", side_effect=avanca_preso):
        tp, rp = em_thread(cmd.pular, A)
        no_avanco.wait(5)
        avanca(A, na_tela=True, cede=True)  # o fim do disco: concilia a virada e toca a primeira
        libera.set()
        tp.join(5)
    confere(rp and rp[0] is y and no_prato(E) == "d3" and fila(A) == [],
            f"o Proximo com a virada sem entrada e o fim do disco tocando antes: devolve a entrada dele "
            f"({rp and (rp[0] or {}).get('id')}, {no_prato(E)}, {fila(A)})")

    # a parecida sem stream com um seek entre a captura e a reserva: tenta de novo, e a seguinte toca
    limpa()
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    tr = {"id": "ccccccccccc", "title": "parecida", "channel": None, "thumb": None, "duration": 120.0,
          "youtube_id": "ccccccccccc", "alvo": None, "path": None, "stream": True, "job": None, "auto": True}
    E.espera(tr)
    no_avanco.clear()
    libera.clear()
    so_se[0] = lambda kw: True
    with mock.patch.object(cmd, "avanca", side_effect=avanca_preso), contextlib.redirect_stderr(io.StringIO()):
        t, _ = em_thread(A._abre_stream, tr, "ccccccccccc", True)
        no_avanco.wait(5)
        E.seek(5.0)
        libera.set()
        t.join(5)
    confere(no_prato(E) == "d2" and fila(A) == [],
            f"a parecida sem stream com um seek no meio: a seguinte toca ({no_prato(E)}, {fila(A)})")

    # o Automatico com o prato parado cuja fila esvaziou antes de reservar: a marca do prato parado fica, e a parecida
    # que chegar depois ainda toca
    limpa()
    toca("d1")
    toca_ate_o_fim(E)
    A._volta_fila(None)
    marcado = E.track
    with A.fila_lock:
        A.fila.append({"id": "d3", "youtube_id": None, "url": None, "title": "Disco d3", "duration": 120.0,
                       "job": None, "qid": "pw", "auto": True, "fixa": True, "auto_de": "semente"})
    A.automatico._auto, A.automatico._semente, A.automatico._mix, A.automatico._ponte = True, {"youtube_id": "bbbbbbbbbbb", "title": "semente"}, [], None
    real_av = cmd.avanca

    def esvazia_e_avanca(*a, **kw):
        cmd.limpar_fila(A)  # a fila esvazia antes de o Automatico reservar
        return real_av(*a, **kw)
    try:
        with mock.patch.object(cmd, "avanca", side_effect=esvazia_e_avanca):
            A.automatico.auto_round((E.track or {}).get("youtube_id"), None)
    finally:
        A.automatico._auto = False
    confere(A.parado_sem_fila is marcado and marcado is not None,
            "o Automatico que nao tocou nada (a fila esvaziou) deixa a marca do prato parado")

    # o Proximo que encontra a fila vazia resolve o grupo ali mesmo: outra reserva que vier antes do fim dele nao o liga
    limpa()
    toca("d1")
    with E._qlock:
        g = cmd.Proximo(E._deck, E._deck.linha)
    r_vazia = avanca(A, pular=True, grupo=g, visto=g)
    confere(r_vazia is None and g.feita.is_set() and g.entrada is None,
            f"o Proximo com a fila vazia resolve o grupo antes de voltar ({r_vazia}, {g.feita.is_set()})")

    # o Anterior e um Proximo no meio, entre a escolha do Anterior e a troca: o Anterior escolhe de novo, com o prato
    # e o historico de agora
    limpa()
    toca("d3")
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    real, vez = A.tocar_entrada, []

    def tocar_com_proximo(xx, **kw):
        if not vez and kw.get("anterior"):
            vez.append(1)
            cmd.pular(A)  # o Proximo passa entre a escolha do Anterior e a troca dele
        return real(xx, **kw)
    A.tocar_entrada = tocar_com_proximo
    try:
        feito = cmd.voltar(A)
    finally:
        del A.tocar_entrada
    confere(vez and feito == "anterior" and no_prato(E) == "d1" and fila(A) == ["d2"],
            f"o Anterior com um Proximo entre a escolha e a troca: volta ao que o Proximo tirou ({feito}, "
            f"{no_prato(E)}, {fila(A)})")
    for nome, mexe, espera in (("um seek (so a linha muda)", lambda: E.seek(50.0), ("inicio", "d1")),
                               ("o esquecer do disco (so o historico muda)", lambda: A.esquecer("d3", None),
                                ("anterior", "d2"))):
        limpa()
        toca("d2")
        toca("d3")
        toca("d1")
        real, vez = A.tocar_entrada, []

        def tocar_com(xx, mexe=mexe, vez=vez, real=real, **kw):
            if not vez and kw.get("anterior"):
                vez.append(1)
                mexe()
            return real(xx, **kw)
        A.tocar_entrada = tocar_com
        try:
            feito = cmd.voltar(A)
        finally:
            del A.tocar_entrada
        confere(vez and (feito, no_prato(E)) == espera,
                f"o Anterior com {nome} entre a escolha e a troca: escolhe de novo ({feito}, {no_prato(E)})")
    # a troca recusada do Anterior (o prato mudou depois da escolha) nao tira a passagem preparada da linha nova
    limpa()
    toca("d3")
    toca("d1")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    real, vez, depois_da_recusa = A.tocar_entrada, [], []

    def tocar_recusado(xx, **kw):
        if not vez and kw.get("anterior"):
            vez.append(1)
            cmd.tocar(A, "d3", start=100.0)  # outro disco no meio, e a passagem dele ja preparada
            with contextlib.redirect_stderr(io.StringIO()):
                E.preparar(arquivo(A, "d2"), x["qid"])
            ok = real(xx, **kw)
            depois_da_recusa.append((ok, E.pronto_tag))
            return ok
        return real(xx, **kw)
    A.tocar_entrada = tocar_recusado
    try:
        cmd.voltar(A)
    finally:
        del A.tocar_entrada
    confere(depois_da_recusa == [(False, x["qid"])],
            f"a troca recusada do Anterior deixa a passagem preparada da linha nova ({depois_da_recusa})")
    toca("d1", start=50.0)
    sk, vez = E.seek, []

    def seek_com_troca(t, pode=None):
        if not vez:
            vez.append(1)
            cmd.tocar(A, "d3")  # outro disco entre a escolha do recomeco e o seek
        return sk(t, pode=pode)
    E.seek = seek_com_troca
    try:
        feito = cmd.voltar(A)
    finally:
        del E.seek
    confere(vez and feito == "anterior" and no_prato(E) == "d1" and E.pos < 1.0,
            f"o Anterior que ia recomecar, com outro disco no meio: escolhe de novo ({feito}, {no_prato(E)})")

    # o Anterior, o Parar e o tocar da prateleira com a virada pendente: ela fecha antes de mexer no historico
    def vira_pendente():
        limpa()
        toca("d1")
        x, _, _ = cmd.enfileirar(A, {"id": "d2"})
        y, _, _ = cmd.enfileirar(A, {"id": "d3"})
        with contextlib.redirect_stderr(io.StringIO()):
            E.preparar(arquivo(A, "d2"), x["qid"])
            ate(lambda: E._virar_em is not None)
            with E._qlock:
                E._virar_em = E.pos
            E._mixa(eng.BLOCK)
        return E.virou is not None and no_prato(E) == "d2"
    pend = vira_pendente()
    cmd.parar(A)
    confere(pend and E.virou is None and historico(A)[-2:] == ["d1", "d2"] and fila(A) == ["d3"],
            f"o Parar com a virada pendente: o Anterior guarda o que saiu nela e depois o que parou "
            f"({historico(A)[-2:]})")
    pend = vira_pendente()
    cmd.tocar(A, "d3")
    confere(pend and E.virou is None and historico(A)[-2:] == ["d1", "d2"] and no_prato(E) == "d3"
            and fila(A) == ["d3"],
            f"o tocar da prateleira com a virada pendente: o mesmo ({historico(A)[-2:]}, {fila(A)})")
    pend = vira_pendente()
    A.esquecer("d2", None)  # a entrada da virada sai da fila antes de o vigia conciliar
    r = cmd.pular(A)
    confere(pend and r is not None and r["id"] == "d3" and no_prato(E) == "d3" and fila(A) == [],
            f"o Proximo com a virada pendente cuja entrada ja saiu da fila: segue para a primeira ({no_prato(E)}, "
            f"{fila(A)})")
    pend = vira_pendente()
    feito = cmd.voltar(A)
    confere(pend and feito == "anterior" and E.virou is None and no_prato(E) == "d1" and fila(A) == ["d2", "d3"],
            f"o Anterior com a virada pendente: fecha ela, toca o que saiu nela e poe a da virada no topo da fila "
            f"({no_prato(E)}, {fila(A)})")
    limpa()


def two_nexts_table(A, E):
    """The rule of two Proximos together (API.md, "Dois Próximos juntos") as a table: the moment the second one
    arrives, against what happens to the platter between the two, and what each one returns."""
    print("--- two Proximos together, as a table")

    def fresh():
        with E.state_section():
            E.drop_prepared()
        E.set_loop(False)
        E.virou = None
        cmd.limpar_fila(A)
        A.parado_sem_fila = None
        cmd.tocar(A, "d1")
        ate(lambda: E.status() == "playing")
        x, _, _ = cmd.enfileirar(A, {"id": "d2"})
        y, _, _ = cmd.enfileirar(A, {"id": "d3"})
        return x, y

    junta, judged = cmd.Proximo.junta, threading.Event()

    def judging(p, E_):
        """Proximo.junta, telling the test the second Proximo already decided whether it shares the first's advance."""
        try:
            return junta(p, E_)
        finally:
            judged.set()

    def arrive_second():
        """The second Proximo, back once it decided (or once it returned); fails the row if it never does."""
        judged.clear()
        with mock.patch.object(cmd.Proximo, "junta", judging):
            t2, r2 = em_thread(cmd.pular, A)
            if not judged.wait(5):
                confere(False, "the second Proximo never decided whether to share the first's advance")
        return t2, r2

    def before_reserving(change):
        """The first holds its Proximo and waits for the fila_lock the test holds: it has not reserved yet."""
        with A.fila_lock:
            t1, r1 = em_thread(cmd.pular, A)
            if not ate(lambda: A.proximo is not None):
                confere(False, "the first Proximo never started")
            t1.join(0.2)  # on its way to the fila_lock; whether it got there or not, it has not reserved
            change()
            t2, r2 = arrive_second()
        t1.join(5)
        t2.join(5)
        return r1, r2, None

    def while_swapping(change):
        """The first is inside the engine's load, with the fila_lock and the engine's _lock held."""
        carrega, inside, release = E.load, threading.Event(), threading.Event()

        def stuck_load(*a, **kw):
            inside.set()
            release.wait(30)  # only the test releases it (the finally too)
            return carrega(*a, **kw)
        E.load = stuck_load
        try:
            t1, r1 = em_thread(cmd.pular, A)
            if not inside.wait(5):
                confere(False, "the first Proximo never got into the engine's load")
            change()
            t2, r2 = arrive_second()
            release.set()
            t1.join(5)
            t2.join(5)
        finally:
            release.set()
            del E.load
        return r1, r2, None

    def while_saving(change):
        """The first already swapped and is saving the position of the record that left (only its own call waits)."""
        grava, saving, release = A.remember_pos, threading.Event(), threading.Event()

        def stuck_save(*a, **kw):
            if not saving.is_set():
                saving.set()
                release.wait(30)  # only the test releases it (the finally too)
            return grava(*a, **kw)
        A.remember_pos = stuck_save
        try:
            t1, r1 = em_thread(cmd.pular, A)
            if not saving.wait(5):
                confere(False, "the first Proximo never got to saving the position")
            change()
            t2, r2 = em_thread(cmd.pular, A)
            t2.join(5)  # in every row the second no longer depends on the first, which is still saving
            early = list(r2)  # before the first returns
            release.set()
            t1.join(5)
            t2.join(5)
        finally:
            release.set()
            del A.remember_pos
        return r1, r2, early

    def after_returning(change):
        r1 = [cmd.pular(A)]
        change()
        return r1, [cmd.pular(A)], None

    def nothing():
        pass

    def stop_engine():  # the platter stops on a new line (the test holds the fila_lock: the engine's stop, not /api/stop)
        E.stop()

    # (when the second arrives, what happens to the platter in between, what the first returns, what the second
    # returns, the platter and the queue at the end); "x" is the first of the queue, "y" the next one
    table = [
        ("before the first reserves", before_reserving, "nothing", nothing, "x", "x", "d2", ["d3"]),
        ("before the first reserves", before_reserving, "stopped", stop_engine, None, "x", "d2", ["d3"]),
        ("while the first swaps", while_swapping, "nothing", nothing, "x", "x", "d2", ["d3"]),
        ("while the first saves the position", while_saving, "nothing", nothing, "x", "x", "d2", ["d3"]),
        ("while the first saves the position", while_saving, "stopped", lambda: cmd.parar(A), "x", "y", "d3", []),
        ("while the first saves the position", while_saving, "seek", lambda: cmd.ir_para(A, 5.0), "x", "y", "d3", []),
        ("while the first saves the position", while_saving, "another record", lambda: cmd.tocar(A, "d1"), "x", "y",
         "d3", []),
        ("after the first returns", after_returning, "nothing", nothing, "x", "y", "d3", []),
    ]
    # a group that already resolved with nothing to play takes no one: the first found the queue empty and is still
    # finishing its command; an entry comes in, and the second plays it on its own (the last row of the table)
    with E.state_section():
        E.drop_prepared()
    E.set_loop(False)
    E.virou = None
    cmd.limpar_fila(A)
    A.parado_sem_fila = None
    cmd.tocar(A, "d1")
    ate(lambda: E.status() == "playing")
    real_avanca, held, release = cmd.avanca, threading.Event(), threading.Event()

    def advance_then_hold(*a, **kw):
        r = real_avanca(*a, **kw)
        if not held.is_set():  # only the first Proximo's advance holds
            held.set()
            release.wait(30)  # only the test releases it (the finally too)
        return r
    try:
        with mock.patch.object(cmd, "avanca", side_effect=advance_then_hold):
            t1, r1 = em_thread(cmd.pular, A)
            if not held.wait(5):
                confere(False, "the first Proximo never got past its advance")
            x, _, _ = cmd.enfileirar(A, {"id": "d2"})
            t2, r2 = em_thread(cmd.pular, A)
            t2.join(5)
            early = list(r2)
            release.set()
            t1.join(5)
    finally:
        release.set()
    confere(r1 == [None] and early and early[0] is x and no_prato(E) == "d2" and fila(A) == [],
            f"second Proximo after the first found the queue empty, before it finishes: first None (409), second the "
            f"entry that came in, on its own (got {r1!r}, {early!r}, {no_prato(E)}, "
            f"{fila(A)})")

    for when, moment, between, change, first, second, platter, queue in table:
        x, y = fresh()
        with contextlib.redirect_stderr(io.StringIO()):
            r1, r2, early = moment(change)

        def name(r):
            if not r:
                return "nothing returned"
            return "x" if r[0] is x else "y" if r[0] is y else None if r[0] is None else repr(r[0])[:60]
        got = (name(r1), name(r2), no_prato(E), fila(A))
        ok = got == (first, second, platter, queue)
        if early is not None:
            ok = ok and name(early) == second  # sharing the advance, the second returns before the first
        confere(ok, f"second Proximo {when}, platter {between}: first {first}, second {second}, platter {platter}, "
                    f"queue {queue} (got {got}{'' if early is None else f', before the first: {name(early)}'})")

    x, y = fresh()
    held, waiting, waiters = Segura(A, quebra=True), cmd.Proximo.espera, threading.Semaphore(0)

    def waits(p, prazo=None):
        waiters.release()
        return waiting(p, prazo)
    try:
        with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(cmd.Proximo, "espera", waits):
            tw, rw = em_thread(cmd.avanca, A, na_tela=True, cede=True)
            held.dentro.wait(5)
            E.set_error(None)
            t1, r1 = em_thread(cmd.pular, A)
            t2, r2 = em_thread(cmd.pular, A)
            joined = waiters.acquire(timeout=5) and waiters.acquire(timeout=5)
            held.solta()
            for t in (tw, t1, t2):
                t.join(5)
    finally:
        held.fim()
    confere(joined and rw and rw[0] is x and r1 == [None] and r2 == [None] and no_prato(E) == "d1"
            and fila(A) == ["d3"] and (E.error or {}).get("key") == "server.queue.playFailed",
            f"two Proximos waiting on the end of the record's advance, whose entry does not play: both None (409), and "
            f"the error goes to the state's error ({joined}, {rw!r}, {r1!r}, {r2!r}, {no_prato(E)}, {fila(A)}, "
            f"{E.error})")
    cmd.limpar_fila(A)
    E.set_error(None)


def mixa():
    """The MockEngine's own _mixa, block by block with the clock in hand: the music ducked by POST /api/abaixa leaves
    for the game about 12 dB lower while the headphones stay the same, and comes back by the deadline; the test beep
    of POST /api/sinal goes only to the game, outside the music volume, and only with the voice on."""
    print("--- the _mixa: the ducking and the test beep")
    agora = [1000.0]
    with contextlib.redirect_stderr(io.StringIO()):
        E = eng.MockEngine("", "")
    E.vol, E.mon_vol = 0.5, 0.5
    E.monitor_on, E.active = True, {"mic": "", "monitor": "headphones"}
    t = np.arange(eng.BLOCK * 400, dtype=np.float32) / eng.SR
    tom = 0.2 * np.sin(2 * np.pi * 400 * t)  # whole cycles in each block: every block has the same RMS
    E._sobre = [[{"id": "tone"}, np.stack([tom, tom], axis=1).astype(np.float32), 0]]  # music the whole test long

    def db(x):
        return 20 * np.log10(max(float(np.sqrt(np.mean(x * x))), 1e-9))

    def bloco():
        """(game dB, headphones dB, game peak) of the next block."""
        jogo = E._mixa(eng.BLOCK).copy()
        fone = E._mon.pop() if E._mon else np.zeros((eng.BLOCK, 2), np.float32)
        E._mon.clear()
        return db(jogo), db(fone), float(np.abs(jogo).max())

    with mock.patch.object(eng, "time", types.SimpleNamespace(monotonic=lambda: agora[0])):
        jogo0, fone0, _ = bloco()
        tom_db = 20 * np.log10(0.2 / np.sqrt(2) * 0.5)  # the tone's RMS at the 0.5 volumes
        confere(abs(jogo0 - tom_db) < 0.1 and abs(fone0 - tom_db) < 0.1,
                f"before the ducking, the tone reaches the game and the headphones ({jogo0:.1f}, {fone0:.1f} dB)")
        E.abaixa(12, 500)
        bloco()  # the ramp from the gain before, with no click
        jogo, fone, _ = bloco()
        confere(abs(jogo - jogo0 + 12) < 0.2 and abs(fone - fone0) < 0.01
                and E.abaixamento() == {"db": 12.0, "ms": 500},
                f"ducked by 12 dB: the game {jogo - jogo0:+.2f} dB, the headphones {fone - fone0:+.2f} dB")
        agora[0] += 0.45
        jogo, _, _ = bloco()
        confere(abs(jogo - jogo0 + 12) < 0.2, f"before the deadline it stays ducked ({jogo - jogo0:+.2f} dB)")
        agora[0] += 0.1
        confere(E.abaixamento() is None, "past the deadline, the state has no ducking")
        bloco()  # the ramp back
        jogo, fone, _ = bloco()
        confere(abs(jogo - jogo0) < 0.01 and abs(fone - fone0) < 0.01,
                f"past the deadline the music is back by itself (the game {jogo - jogo0:+.2f} dB)")

        E._sobre, E.vol = [], 0.0  # no music, and its volume at zero: the beep doesn't go through it
        bloco()
        E.mic_mute = True
        confere(E.sinal() is False and bloco()[2] == 0.0, "with the voice cut, the beep doesn't play")
        E.mic_mute = False
        confere(E.sinal() is True, "with the voice on, the beep is accepted")
        blocos = [bloco() for _ in range(int(eng.SINAL_S * eng.SR / eng.BLOCK) + 2)]
        pico = max(b[2] for b in blocos)
        confere(abs(20 * np.log10(pico) - eng.SINAL_DB) < 0.5 and blocos[-1][2] == 0.0,
                f"the beep plays at {20 * np.log10(pico):.1f} dBFS (expected {eng.SINAL_DB:g}) and ends by itself")
        confere(all(b[1] < -150 for b in blocos), "the beep goes only to the game, not to the headphones")
        E.sinal()
        primeiro = bloco()[2]
        E.mic_mute = True
        cortado = bloco()[2]
        E.mic_mute = False
        confere(primeiro > 0 and cortado == 0.0 and bloco()[2] == 0.0,
                "the voice cut in the middle of the beep: the rest doesn't play, not even with the voice back")
        E.sinal()
        agora[0] += eng.SINAL_S + 0.1
        confere(bloco()[2] == 0.0, "a beep that didn't start by its deadline doesn't play")


def engine_seams(A, E):
    print("--- the engine's public seams: state_section, take_prepare_failure and with_lock")
    with E.state_section() as handle:
        held = E._qlock.locked()
    confere(handle is None and held and not E._qlock.locked(),
            f"state_section holds the _qlock in its body, hands out no lock and releases it ({handle})")
    with contextlib.suppress(KeyError), E.state_section():
        raise KeyError("body")
    confere(not E._qlock.locked(), "and releases it when the body raises")

    cmd.tocar(A, "d1")
    confere(ate(lambda: E.status() == "playing"), f"the record plays ({E.status()})")
    x, _, _ = cmd.enfileirar(A, {"id": "d2"})
    A.failed_passages.clear()
    engine_class, uses, reads, drops = type(E), [], [], []

    class Counted:
        def __init__(self, lock):
            self.lock, self.taken = lock, 0

        def __enter__(self):
            self.lock.acquire()
            self.taken += 1
            return self

        def __exit__(self, *exc):
            self.lock.release()

        def locked(self):
            return self.lock.locked()

    class Watched(engine_class):
        @property
        def _prepare_failure(self):
            uses.append(self._qlock.locked())
            reads.append(("failure", self._qlock.taken, self._qlock.locked()))
            return self.__dict__["_prepare_failure"]

        @_prepare_failure.setter
        def _prepare_failure(self, value):
            uses.append(self._qlock.locked())
            self.__dict__["_prepare_failure"] = value

        @property
        def pronto_tag(self):
            reads.append(("pronto", self._qlock.taken, self._qlock.locked()))
            return self.__dict__["pronto_tag"]

        @pronto_tag.setter
        def pronto_tag(self, value):
            self.__dict__["pronto_tag"] = value

        def drop_prepared(self):
            drops.append((self._qlock.taken, self._qlock.locked()))
            return super().drop_prepared()
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6), mock.patch.object(A, "_prepara") as prepara:
        A._volta_passagem()
        confere(ate(lambda: prepara.called) and prepara.call_args.args[1] is x,
                "inside the preparation window, the head of the queue is prepared")
        A.preparando = None
        prepara.reset_mock()
        failed_key = (cmd.Identity(E.track), x["qid"], A.passage_source(x))
        with E.state_section():
            E._prepare_failure, E.pronto_tag = failed_key, "a deck prepared for another entry"
        qlock, E.__class__ = E._qlock, Watched
        E._qlock = Counted(qlock)
        try:
            A._volta_passagem()
            again, _ = E.take_prepare_failure(x["qid"])
        finally:
            E.__class__, E._qlock = engine_class, qlock
        A._volta_passagem()
    pairs = [(a, b) for a, b in zip(reads, reads[1:]) if a[0] == "failure"]
    confere(failed_key in A.failed_passages and again is None,
            f"the passage watcher takes the prepare failure out of the engine, once ({A.failed_passages})")
    confere(uses and all(uses), f"and reads and clears it under the engine's _qlock ({uses})")
    confere(drops == [reads[0][1:]] and reads[0][0] == "failure",
            f"and drops a deck prepared for another entry in the same hold of the _qlock as the failure ({drops}, "
            f"{reads[:1]})")
    confere(len(pairs) == 2 and all(b[0] == "pronto" and a[1:] == b[1:] == (a[1], True) for a, b in pairs),
            f"and reads the prepared deck's tag in the same hold of the _qlock as the failure ({pairs})")
    confere(not prepara.called and A.preparando is None,
            f"and the head that failed is not prepared again ({prepara.call_count}, {A.preparando})")
    carried, taken = (cmd.Identity(E.track), x["qid"], ("the source the prepare picked", None)), []

    def decodes_nothing(gen, track, start, deck):
        with E._qlock:
            deck.eof_gen = gen
    with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", decodes_nothing):
        started = E.preparar(arquivo(A, "d2"), x["qid"], key=carried)
        failed = ate(lambda: taken.append(E.take_prepare_failure(x["qid"])[0]) or taken[-1] is not None, limite=15.0)
    confere(started and failed and taken[-1] == carried,
            f"a prepared deck that does not decode hands back the key its prepare carried ({taken[-1:]})")
    with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", decodes_nothing), \
            mock.patch.object(E, "_mede", lambda *a: None):
        started = E.preparar(arquivo(A, "d2"), x["qid"], key=carried)
        with E.state_section():
            atual, prox, playing = E._deck, E._pronto, E.track
    eng.Engine._mede(E, atual, prox, playing)
    real_failure, _ = E.take_prepare_failure(x["qid"])
    confere(started and real_failure == carried,
            f"and so does the engine's own measure of the passage, Engine._mede ({real_failure})")
    cmd.tirar_da_fila(A, x["qid"])

    real, holding, release, waiting = E._lock, threading.Event(), threading.Event(), threading.Event()

    class Spy:
        def acquire(self, blocking=True):
            return real.acquire(blocking)

        def release(self):
            real.release()

        def __enter__(self):
            waiting.set()
            return real.__enter__()

        def __exit__(self, *a):
            return real.__exit__(*a)

    def engine_lock_free():
        free = []

        def probe():
            free.append(real.acquire(blocking=False))
            if free[-1]:
                real.release()
        em_thread(probe)[0].join(5)
        return free == [True]

    seen, after_seen, result = [], [], []

    def f(after):
        seen.append((A.fila_lock.locked(), engine_lock_free()))
        after.append(lambda: after_seen.append((A.fila_lock.locked(), engine_lock_free())))
        return "ran"

    def hold():
        with real:
            holding.set()
            release.wait(5)
    holder, _ = em_thread(hold)
    confere(holding.wait(5), "another thread holds the engine's _lock")
    E._lock = Spy()
    try:
        waiter, _ = em_thread(lambda: result.append(A.with_engine(f)))
        confere(waiting.wait(5), "with_engine waits for the engine's _lock")
        free = A.fila_lock.acquire(timeout=1)
        if free:
            A.fila_lock.release()
        confere(free and not seen, "while it waits for the engine's _lock, with_engine does not hold the fila_lock")
        release.set()
        waiter.join(5)
    finally:
        release.set()
        holder.join(5)
        E._lock = real
    confere(result == ["ran"] and seen == [(True, False)],
            f"then f runs once, with the fila_lock and the engine's _lock held ({result}, {seen})")
    confere(after_seen == [(False, True)], f"and what f leaves for after runs with both released ({after_seen})")


def main():
    mixa()
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio"  # a pasta dos arquivos de audio tambem e a temporaria: o Library cria a dele
        with mock.patch.object(server, "LIB", audio), mock.patch.object(pastas, "LIB", audio):
            A, E = monta(Path(tmp))
            try:
                comandos(A, E)
                voltas(A, E)
                andamento(A, E)
                bloco(A, E)
                avanco(A, E)
                two_nexts_table(A, E)
                engine_seams(A, E)
                off_shelf_play(A, E)
            finally:
                E.close()
    if falhas:
        print(f"\n{len(falhas)} falha(s)")
        sys.exit(1)
    print("\ntudo certo")


if __name__ == "__main__":
    main()
