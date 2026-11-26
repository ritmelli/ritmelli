r"""Checks the Automatico on the real App: server.App(..., mock=True, vigias=False, relogio=False), in the same process
and a temporary folder with a known andamentos.json, without the watcher threads or the MockEngine's clock. The App's
mix_do (the network search for similar tracks, which already comes back empty with --mock) becomes a fake with six
similar tracks of known tempo, and the platter gets a track with a youtube_id and no path (without a path the engine
opens no reader): that is the seed. The test plays the watcher: it turns the Automatico on (ligar_auto), calls the
first round (A.automatico.auto_round), which asks for the seed's search, runs that search itself
(A.automatico.fetch_mix, with no thread and no wait) and calls the second round, which builds the queue in tempo
order. Then a new measure with the head of the queue held (the passage to it already being prepared) and without it,
and the Automatico turned off. Nothing goes to the network or opens a device, and the user's shelf and folder are not
read.

    python dev/testa_automatico.py

Exits 1 if something fails."""
import contextlib
import io
import json
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

with contextlib.redirect_stderr(io.StringIO()):  # o aviso das vozes do pedal, que nao sao deste teste
    import automatico as auto_mod
    import engine as eng
    import pastas
    import server

falhas = []

SEMENTE = {"id": None, "youtube_id": "sssssssssss", "title": "Semente Primeira", "channel": "Quem Semeia",
           "duration": 600.0, "lufs": -14.0}
# as parecidas na ordem do Mix (a mais parecida com a semente primeiro), cada uma de um artista
PARECIDAS = [("aaaaaaaaaa1", "Musica Um"), ("aaaaaaaaaa2", "Musica Dois"), ("aaaaaaaaaa3", "Musica Tres"),
             ("aaaaaaaaaa4", "Musica Quatro"), ("aaaaaaaaaa5", "Musica Cinco"), ("aaaaaaaaaa6", "Musica Seis")]
# o comeco e o fim de cada uma (a 4 sem medida). Do fim da semente (120), a ordem sobe no circulo das oitavas: a 3
# (comeca em 120, termina em 130), a 6 (131), a 2 (138), a 4 (sem andamento, o salto) e a 1 (90, a volta do circulo);
# a 5 (125, abaixo de 131 e de 138) fica no Mix, que so cabe cinco na fila
ANDAMENTOS = {"sssssssssss": {"ini": 120.0, "fim": 120.0}, "aaaaaaaaaa1": {"ini": 90.0, "fim": 90.0},
              "aaaaaaaaaa2": {"ini": 138.0, "fim": 138.0}, "aaaaaaaaaa3": {"ini": 120.0, "fim": 130.0},
              "aaaaaaaaaa5": {"ini": 125.0, "fim": 125.0}, "aaaaaaaaaa6": {"ini": 131.0, "fim": 131.0}}


def confere(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        falhas.append(msg)


def monta(tmp):
    """O App de verdade, sem vigias e sem relogio, com a prateleira vazia e o andamentos.json conhecido."""
    (tmp / "library.json").write_text("[]", encoding="utf-8")
    (tmp / "andamentos.json").write_text(json.dumps(ANDAMENTOS), encoding="utf-8")
    with (contextlib.redirect_stderr(io.StringIO()),
          mock.patch.object(eng.MockEngine, "_real_names", return_value={"mic": "", "monitor": ""})):
        A = server.App(0, tmp, mock=True, vigias=False, relogio=False)
    A.engine.volume_auto = False
    return A, A.engine


def automatico(A, E):
    pedidos = []

    def mix_falso(yid):
        """The seed's similar tracks, new on every search (fetch_mix numbers each one in Mix order)."""
        pedidos.append(yid)
        return [{"youtube_id": v, "title": t, "duration": 200.0, "channel": f"Artista {t.split()[-1]}",
                 "thumb": server.thumb(v)} for v, t in PARECIDAS]
    A.mix_do = mix_falso

    def auto():
        return [x["youtube_id"] for x in A.fila if x.get("auto")]

    E.load(dict(SEMENTE))
    A.ligar_auto(True)
    confere(A.automatico.auto and A.automatico.semente is None and A.automatico.mix is None, "o Automatico ligado, antes da primeira volta")

    # a primeira volta: o disco do prato vira a semente e a busca do Mix dela e pedida (a thread dela fica so pedida:
    # quem busca e o teste, com a semente que a volta passou a ela)
    with mock.patch.object(threading, "Thread") as thread:
        visto, sinal = A.automatico.auto_round(None, None)
    pedida = [(getattr(c.kwargs.get("target"), "__name__", None), c.kwargs.get("args")) for c in thread.call_args_list]
    base = pedida[0][1][0] if pedida and pedida[0][1] else None
    confere(visto == "sssssssssss" and A.automatico.semente == {"youtube_id": "sssssssssss", "title": "Semente Primeira"}
            and pedida == [("fetch_mix", ("sssssssssss",))] and thread.return_value.start.call_count == 1
            and A.automatico.mix_base == base and A.automatico.mix is None and A.automatico.mix_buscando and "sssssssssss" in A.automatico.fora and auto() == [],
            f"a primeira volta: a semente e o disco do prato, e a busca do Mix dela fica pedida ({A.automatico.semente}, {pedida})")

    # a busca, pelo mix_do do App (o falso)
    A.automatico.fetch_mix(base)
    confere(pedidos == ["sssssssssss"] and not A.automatico.mix_buscando
            and [m["youtube_id"] for m in A.automatico.mix] == [v for v, _ in PARECIDAS]
            and [m["ordem"] for m in A.automatico.mix] == [1, 2, 3, 4, 5, 6],
            f"a busca: as parecidas da semente, pelo mix_do do App, numeradas na ordem do Mix ({pedidos})")

    # a segunda volta monta a fila na ordem por andamento
    visto, sinal = A.automatico.auto_round(visto, sinal)
    esperado = ["aaaaaaaaaa3", "aaaaaaaaaa6", "aaaaaaaaaa2", "aaaaaaaaaa4", "aaaaaaaaaa1"]
    confere(auto() == esperado and len(A.fila) == auto_mod.AUTO_FILA,
            f"a segunda volta: cinco parecidas na fila, na ordem por andamento ({auto()})")
    confere(all(x.get("auto_de") == "Semente Primeira" and x.get("qid") and x.get("id") is None for x in A.fila),
            "cada parecida da fila diz de que semente veio e ganhou o seu qid")
    confere([m["youtube_id"] for m in A.automatico.mix] == ["aaaaaaaaaa5"], f"a que nao entrou fica no Mix ({A.automatico.mix})")
    antes = [x["qid"] for x in A.fila]
    visto, sinal = A.automatico.auto_round(visto, sinal)
    confere([x["qid"] for x in A.fila] == antes and pedidos == ["sssssssssss"],
            "a volta seguinte, sem nada mudar, deixa a fila como esta e nao busca de novo")

    # a medida nova poria a 1 na frente (comeca em 120, como a 3, e vem antes no Mix), mas a primeira da fila esta presa:
    # a passagem para ela ja esta sendo preparada
    with A.fila_lock:
        A.automatico.andamentos["aaaaaaaaaa1"] = {"ini": 120.0, "fim": 131.0}
        A.automatico.andamentos_versao += 1
    A.preparando = (E.track, A.fila[0]["qid"])
    visto, sinal = A.automatico.auto_round(visto, sinal)
    confere(auto() == esperado and A.fila[0]["qid"] == antes[0],
            f"com a primeira presa, a medida nova nao a troca ({auto()})")

    # sem a presa, a medida nova vale
    A.preparando = None
    visto, sinal = A.automatico.auto_round(visto, sinal)
    confere(auto() == ["aaaaaaaaaa1", "aaaaaaaaaa6", "aaaaaaaaaa2", "aaaaaaaaaa4", "aaaaaaaaaa3"],
            f"sem a presa, a medida nova reordena a fila ({auto()})")
    confere([m["youtube_id"] for m in A.automatico.mix] == ["aaaaaaaaaa5"] and pedidos == ["sssssssssss"],
            "o Mix e o mesmo, sem busca nova")

    removed = next(x for x in A.fila if x["youtube_id"] == "aaaaaaaaaa6")
    A.tirar_da_fila(removed["qid"], recusar=True)
    visto, sinal = A.automatico.auto_round(visto, sinal)
    confere("aaaaaaaaaa6" not in auto() and "aaaaaaaaaa5" in auto() and "aaaaaaaaaa6" in A.automatico.fora,
            f"a similar track the user takes out stays out, and the next one from the Mix takes its place ({auto()})")

    # desligar tira as parecidas da fila
    A.ligar_auto(False)
    confere(not A.automatico.auto and A.fila == [], f"desligado, as parecidas saem da fila ({auto()})")
    visto, sinal = A.automatico.auto_round(visto, sinal)
    confere(A.fila == [] and pedidos == ["sssssssssss"], "e a volta com o Automatico desligado nao poe nada")


def saved_choice(tmp, A):
    print("--- the Automatico's choice, saved in config.json")
    confere(A.automatico.auto is True, "a fresh install has the Automatico on")
    A.ligar_auto(False)
    A.save_cfg()
    B, E = monta(tmp)
    try:
        confere(B.automatico.auto is False, "the next start keeps the choice the user saved")
    finally:
        E.close()
    A.ligar_auto(True)
    A.save_cfg()


def main():
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio"  # a pasta dos arquivos de audio tambem e a temporaria: o Library cria a dele
        with mock.patch.object(server, "LIB", audio), mock.patch.object(pastas, "LIB", audio):
            A, E = monta(Path(tmp))
            try:
                saved_choice(Path(tmp), A)
                automatico(A, E)
            finally:
                E.close()
    if falhas:
        print(f"\n{len(falhas)} falha(s)")
        sys.exit(1)
    print("\ntudo certo")


if __name__ == "__main__":
    main()
