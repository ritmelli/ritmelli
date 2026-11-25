r"""Confere o Automatico no App de verdade: o server.App(..., mock=True, vigias=False, relogio=False), no mesmo processo e
numa pasta temporaria com um andamentos.json conhecido, sem as threads dos vigias nem o relogio do MockEngine. O
mix_do do App (a busca de parecidas na rede, que no --mock ja volta vazia) vira um falso com seis parecidas de
andamento conhecido, e o prato recebe uma faixa com youtube_id e sem path (sem path, o motor nao abre leitor): ela e a
semente. O teste faz o papel do vigia, sempre pelo App: liga o Automatico (ligar_auto), chama a primeira volta
(_volta_auto), que pede a busca da semente, faz a busca ele mesmo (_busca_mix, sem thread e sem esperar) e chama a
segunda volta, que monta a fila na ordem por andamento. Depois, uma medida nova com a primeira da fila presa (a
passagem para ela ja sendo preparada) e sem ela, e o Automatico desligado. Nada vai a rede nem abre aparelho, e a
prateleira e a pasta de quem usa nao sao lidas.

    python dev/testa_automatico.py

Sai 1 se algo falha."""
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
    import automatico as auto_mod  # noqa: E402
    import engine as eng  # noqa: E402
    import pastas  # noqa: E402
    import server  # noqa: E402

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
        """As parecidas da semente, novas a cada busca (o _busca_mix numera cada uma na ordem do Mix)."""
        pedidos.append(yid)
        return [{"youtube_id": v, "title": t, "duration": 200.0, "channel": f"Artista {t.split()[-1]}",
                 "thumb": server.thumb(v)} for v, t in PARECIDAS]
    A.mix_do = mix_falso

    def auto():
        return [x["youtube_id"] for x in A.fila if x.get("auto")]

    E.load(dict(SEMENTE))
    A.ligar_auto(True)
    confere(A.auto and A.semente is None and A.mix is None, "o Automatico ligado, antes da primeira volta")

    # a primeira volta: o disco do prato vira a semente e a busca do Mix dela e pedida (a thread dela fica so pedida:
    # quem busca e o teste, com a semente que a volta passou a ela)
    with mock.patch.object(threading, "Thread") as thread:
        visto, sinal = A._volta_auto(None, None)
    pedida = [(getattr(c.kwargs.get("target"), "__name__", None), c.kwargs.get("args")) for c in thread.call_args_list]
    base = pedida[0][1][0] if pedida and pedida[0][1] else None
    confere(visto == "sssssssssss" and A.semente == {"youtube_id": "sssssssssss", "title": "Semente Primeira"}
            and pedida == [("_busca_mix", ("sssssssssss",))] and thread.return_value.start.call_count == 1
            and A.mix_base == base and A.mix is None and A.mix_buscando and "sssssssssss" in A.fora and auto() == [],
            f"a primeira volta: a semente e o disco do prato, e a busca do Mix dela fica pedida ({A.semente}, {pedida})")

    # a busca, pelo mix_do do App (o falso)
    A._busca_mix(base)
    confere(pedidos == ["sssssssssss"] and not A.mix_buscando
            and [m["youtube_id"] for m in A.mix] == [v for v, _ in PARECIDAS]
            and [m["ordem"] for m in A.mix] == [1, 2, 3, 4, 5, 6],
            f"a busca: as parecidas da semente, pelo mix_do do App, numeradas na ordem do Mix ({pedidos})")

    # a segunda volta monta a fila na ordem por andamento
    visto, sinal = A._volta_auto(visto, sinal)
    esperado = ["aaaaaaaaaa3", "aaaaaaaaaa6", "aaaaaaaaaa2", "aaaaaaaaaa4", "aaaaaaaaaa1"]
    confere(auto() == esperado and len(A.fila) == auto_mod.AUTO_FILA,
            f"a segunda volta: cinco parecidas na fila, na ordem por andamento ({auto()})")
    confere(all(x.get("auto_de") == "Semente Primeira" and x.get("qid") and x.get("id") is None for x in A.fila),
            "cada parecida da fila diz de que semente veio e ganhou o seu qid")
    confere([m["youtube_id"] for m in A.mix] == ["aaaaaaaaaa5"], f"a que nao entrou fica no Mix ({A.mix})")
    antes = [x["qid"] for x in A.fila]
    visto, sinal = A._volta_auto(visto, sinal)
    confere([x["qid"] for x in A.fila] == antes and pedidos == ["sssssssssss"],
            "a volta seguinte, sem nada mudar, deixa a fila como esta e nao busca de novo")

    # a medida nova poria a 1 na frente (comeca em 120, como a 3, e vem antes no Mix), mas a primeira da fila esta presa:
    # a passagem para ela ja esta sendo preparada
    with A.fila_lock:
        A.andamentos["aaaaaaaaaa1"] = {"ini": 120.0, "fim": 131.0}
        A.andamentos_versao += 1
    A.preparando = (E.track, A.fila[0]["qid"])
    visto, sinal = A._volta_auto(visto, sinal)
    confere(auto() == esperado and A.fila[0]["qid"] == antes[0],
            f"com a primeira presa, a medida nova nao a troca ({auto()})")

    # sem a presa, a medida nova vale
    A.preparando = None
    visto, sinal = A._volta_auto(visto, sinal)
    confere(auto() == ["aaaaaaaaaa1", "aaaaaaaaaa6", "aaaaaaaaaa2", "aaaaaaaaaa4", "aaaaaaaaaa3"],
            f"sem a presa, a medida nova reordena a fila ({auto()})")
    confere([m["youtube_id"] for m in A.mix] == ["aaaaaaaaaa5"] and pedidos == ["sssssssssss"],
            "o Mix e o mesmo, sem busca nova")

    # desligar tira as parecidas da fila
    A.ligar_auto(False)
    confere(not A.auto and A.fila == [], f"desligado, as parecidas saem da fila ({auto()})")
    visto, sinal = A._volta_auto(visto, sinal)
    confere(A.fila == [] and pedidos == ["sssssssssss"], "e a volta com o Automatico desligado nao poe nada")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio"  # a pasta dos arquivos de audio tambem e a temporaria: o Library cria a dele
        with mock.patch.object(server, "LIB", audio), mock.patch.object(pastas, "LIB", audio):
            A, E = monta(Path(tmp))
            try:
                automatico(A, E)
            finally:
                E.close()
    if falhas:
        print(f"\n{len(falhas)} falha(s)")
        sys.exit(1)
    print("\ntudo certo")


if __name__ == "__main__":
    main()
