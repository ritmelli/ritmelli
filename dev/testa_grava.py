r"""Confere a gravacao dos .json dos dados (pastas.save_json): duas threads gravando o mesmo arquivo 200 vezes cada
terminam sem excecao, com o JSON valido e sem temporario sobrando; o arquivo aberto por outro por menos de 1 s nao
derruba a gravacao (o Windows recusa a troca e ela tenta de novo); aberto por mais tempo, a gravacao desiste com o
PermissionError e o temporario sai. So a biblioteca padrao, numa pasta temporaria: nada de verdade e tocado. A
recusa do arquivo aberto e a do Windows: fora dele, essa parte fica de fora.

    python dev/testa_grava.py

Sai 1 se algo falha."""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import pastas  # noqa: E402

falhas = []


def confere(ok, msg):
    print(("ok    " if ok else "FALHA ") + msg)
    if not ok:
        falhas.append(msg)


def sobras(pasta):
    return sorted(p.name for p in pasta.iterdir() if p.name != "config.json")


with tempfile.TemporaryDirectory() as tmp:
    pasta = Path(tmp)
    alvo = pasta / "config.json"

    # duas threads, 200 gravacoes cada, no mesmo arquivo
    erros, comeca = [], threading.Barrier(2)

    def grava(quem):
        comeca.wait()
        for i in range(200):
            try:
                pastas.save_json(alvo, {"quem": quem, "i": i, "texto": "x" * 2000})
            except Exception as ex:  # noqa: BLE001 - o teste conta qualquer uma
                erros.append(f"{quem} {i}: {ex!r}")

    ts = [threading.Thread(target=grava, args=(q,)) for q in ("a", "b")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    confere(not erros, f"duas threads, 200 gravacoes cada: sem excecao {erros[:3]}")
    try:
        fim = json.loads(alvo.read_text(encoding="utf-8"))
        valido = fim.get("i") == 199 and fim.get("quem") in ("a", "b")
    except ValueError:
        valido = False
    confere(valido, "o arquivo no fim e um JSON valido, de uma das ultimas gravacoes")
    confere(not sobras(pasta), f"nenhum temporario sobrando {sobras(pasta)}")

    if sys.platform == "win32":
        # aberto por outro por um instante: a troca e recusada e a gravacao tenta de novo
        f = open(alvo, encoding="utf-8")  # noqa: SIM115 - fica aberto de proposito
        solta = threading.Timer(0.3, f.close)
        solta.start()
        t0 = time.monotonic()
        try:
            pastas.save_json(alvo, {"depois": "de esperar"})
            ok = True
        except PermissionError:
            ok = False
        solta.join()
        confere(ok and time.monotonic() - t0 >= 0.25
                and json.loads(alvo.read_text(encoding="utf-8")) == {"depois": "de esperar"},
                "aberto por 0,3 s: a gravacao espera e troca")
        confere(not sobras(pasta), f"nenhum temporario sobrando {sobras(pasta)}")

        # aberto o tempo todo: desiste com o PermissionError, o arquivo fica como estava e o temporario sai
        with open(alvo, encoding="utf-8"):
            t0 = time.monotonic()
            try:
                pastas.save_json(alvo, {"nunca": "troca"})
                desistiu = False
            except PermissionError:
                desistiu = True
            dt = time.monotonic() - t0
        confere(desistiu and 0.9 <= dt < 3, f"aberto o tempo todo: PermissionError depois de {dt:.2f} s")
        confere(json.loads(alvo.read_text(encoding="utf-8")) == {"depois": "de esperar"}, "o arquivo fica como estava")
        confere(not sobras(pasta), f"nenhum temporario sobrando {sobras(pasta)}")

    # o que nao vira JSON falha antes de criar o temporario
    try:
        pastas.save_json(alvo, {"x": object()})
        recusou = False
    except TypeError:
        recusou = True
    confere(recusou and not sobras(pasta), "o que nao vira JSON: TypeError e nenhum temporario")

sys.exit(1 if falhas else 0)
