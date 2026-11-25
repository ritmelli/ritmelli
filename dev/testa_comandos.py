r"""Confere os comandos de musica (comandos.py) e o avanco da fila no App de verdade: o server.App(..., mock=True,
vigias=False, relogio=False), no mesmo processo e numa pasta temporaria, sem as threads dos vigias nem o relogio do
MockEngine. Quem anda o audio e o teste, chamando o engine._mixa(BLOCK); quem faz o papel de cada vigia e o teste,
chamando a volta dele (_volta_fila, _volta_passagem e _volta_auto). O leitor do motor e um de mentira (blocos de
silencio, sem ffmpeg), o som por cima so e anotado e o endereco do stream e recusado: nada vai a rede nem abre
aparelho, e a prateleira e a pasta de quem usa nao sao lidas.

    python dev/testa_comandos.py

Sai 1 se algo falha."""
import contextlib
import io
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402

with contextlib.redirect_stderr(io.StringIO()):  # o aviso das vozes do pedal, que nao sao deste teste
    import comandos as cmd  # noqa: E402
    import engine as eng  # noqa: E402
    import pastas  # noqa: E402
    import server  # noqa: E402

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

    # a parecida que chega com o prato parado toca na hora (_volta_auto)
    A.auto, A.semente, A.mix_base = True, {"youtube_id": "bbbbbbbbbbb", "title": "semente"}, "bbbbbbbbbbb"
    A.mix = [{"youtube_id": "aaaaaaaaaaa", "title": "Disco d3", "duration": 120.0, "ordem": 1}]
    visto, sinal = A._volta_auto(None, None)
    confere(no_prato(E) == "d3" and E.track.get("auto") and A.parado_sem_fila is None and fila(A) == [],
            f"o _volta_auto: a parecida que chegou com o prato parado toca na hora ({no_prato(E)})")
    visto, sinal = A._volta_auto(visto, sinal)
    confere(visto == "aaaaaaaaaaa" and A.ponte == "aaaaaaaaaaa",
            "a volta seguinte ve a parecida no prato: o Automatico segue do Mix dela quando o da semente acabar")
    A.auto = False

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
    A._volta_passagem()
    ate(lambda: A.preparando is None)  # a volta ja prepara a seguinte (a d2): o teste so segue com ela pronta
    confere(E.virou is None and fila(A) == ["d2"] and historico(A)[-1:] == ["d3"] and no_prato(E) == "d1",
            f"o _volta_passagem tira da fila a que entrou e guarda a que saiu ({fila(A)}, {historico(A)[-1:]})")

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
        confere(ate(lambda: no_prato(E) == "d2"), f"o stream dela recusado: a seguinte da fila toca ({no_prato(E)})")
    confere(historico(A) == hist + ["d1"] and fila(A) == [],
            f"e a parecida que nao tocou nao vai para o Anterior ({historico(A)[len(hist):]})")

    # a entrada quebrada no fim do disco: o erro vai para a tela (na_tela), e a volta segue sem travar a fila
    ate(lambda: E.status() == "playing")
    with A.fila_lock:
        A.fila.append({"id": None, "youtube_id": None, "url": None, "title": "quebrada", "qid": "q0", "job": None})
    toca_ate_o_fim(E)
    tr, E.error = E.track, None
    confere(A._volta_fila(None) is tr and fila(A) == [] and A.parado_sem_fila is not tr
            and (E.error or {}).get("key") == "server.queue.playFailed",
            f"o fim do disco com uma entrada quebrada: o erro vai para a tela, e ela sai da fila ({E.error})")
    try:
        with A.fila_lock:
            A.fila.append({"id": None, "youtube_id": None, "url": None, "title": "quebrada", "qid": "q1", "job": None})
        cmd.pular(A)
        confere(False, "o pular com a entrada quebrada levanta o erro (a rota responde 500, como antes)")
    except ValueError:
        confere(fila(A) == [], "o pular com a entrada quebrada levanta o erro (a rota responde 500, como antes)")
    try:
        cmd.enfileirar(A, {})
        confere(False, "o enfileirar sem disco nem video e a recusa do corpo (400)")
    except cmd.CorpoRecusado:
        confere(True, "o enfileirar sem disco nem video e a recusa do corpo (400)")

    # o erro de tocar a entrada na hora nao e a recusa do corpo: segue para o guard (500), como antes
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
    """O _vigia_andamento de verdade, uma volta por caso: a versao de audio e o andamento medidos sao gravados fora da
    fila_lock; a medida fica na memoria mesmo se a gravacao falha, mas so vale na fila depois de gravada."""
    print("--- o _vigia_andamento: a gravacao fora da fila_lock")

    class Fim(Exception):
        pass
    E.cancelar_pronto()
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

        def grava(caminho, dados):
            travado.append(A.fila_lock.locked())
            if falha:
                raise OSError("disco cheio")
        travado, trocas, versao = [], [], A.andamentos_versao
        v = {"youtube_id": "fffffffffff", "duration": 200, "title": "parecida", "channel": "c"}
        with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(server, "ANDAMENTO_APOS_S", -1),
              mock.patch.object(server, "save_json", grava), mock.patch.object(A, "_a_medir", a_medir),
              mock.patch.object(A, "versao_audio", return_value=v),
              mock.patch.object(A, "_mede_andamento", return_value={"ini": 100.0, "fim": 101.0}),
              mock.patch.object(A, "_troca_audio", side_effect=lambda *a: trocas.append(a)),
              mock.patch.object(threading, "excepthook", lambda a: None)):
            A.auto = True
            t = threading.Thread(target=A._vigia_andamento)
            t.start()
            t.join(10)
            A.auto = False
        return travado, trocas, A.andamentos_versao - versao, v

    travado, trocas, subiu, v = roda("audio", "aaaaaaaaaa1", falha=False)
    confere(travado == [False] and trocas == [("aaaaaaaaaa1", v)] and subiu == 1 and A.versoes["aaaaaaaaaa1"] == v,
            f"a versao de audio: gravada fora da fila_lock e so entao vale na fila ({travado}, {len(trocas)}, {subiu})")
    travado, trocas, subiu, v = roda("audio", "aaaaaaaaaa2", falha=True)
    confere(travado == [False] and trocas == [] and subiu == 0 and A.versoes.get("aaaaaaaaaa2") == v,
            f"a gravacao da versao falha: ela fica na memoria, mas nao vale na fila "
            f"({travado}, {len(trocas)}, {subiu})")
    travado, _, subiu, _ = roda("medir", "aaaaaaaaaa3", falha=False)
    confere(travado == [False] and subiu == 1 and A.andamentos.get("aaaaaaaaaa3") == {"ini": 100.0, "fim": 101.0},
            f"o andamento: gravado fora da fila_lock e so entao reordena o Automatico ({travado}, {subiu})")
    travado, _, subiu, _ = roda("medir", "aaaaaaaaaa4", falha=True)
    confere(travado == [False] and subiu == 0 and A.andamentos.get("aaaaaaaaaa4") == {"ini": 100.0, "fim": 101.0},
            f"a gravacao do andamento falha: ele fica na memoria, mas nao reordena ({travado}, {subiu})")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio"  # a pasta dos arquivos de audio tambem e a temporaria: o Library cria a dele
        with mock.patch.object(server, "LIB", audio), mock.patch.object(pastas, "LIB", audio):
            A, E = monta(Path(tmp))
            try:
                comandos(A, E)
                voltas(A, E)
                andamento(A, E)
            finally:
                E.close()
    if falhas:
        print(f"\n{len(falhas)} falha(s)")
        sys.exit(1)
    print("\ntudo certo")


if __name__ == "__main__":
    main()
