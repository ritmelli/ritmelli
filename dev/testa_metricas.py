"""Confere os dados de uso e os erros (metricas.py, o PRIVACIDADE.md): so sai o que esta no EVENTOS, nada sai sem a
escolha de quem usa, desligar joga fora o que nao saiu, o uso soma o que o motor faz, o "ativo" sai uma vez por dia, e
o erro vai sem caminho de pasta, sem o que esta entre aspas e sem variavel. Nao usa a rede: o envio e trocado por uma
lista.

    python dev/testa_metricas.py                 os testes
    python dev/testa_metricas.py --de-verdade    tambem manda um evento "teste_de_envio" ao PostHog e um erro de
                                                 teste ao Sentry (environment "teste"), para ver que as chaves valem

Sai 1 se algo falha."""
import json
import re
import sys
import tempfile
import traceback
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import metricas as met  # noqa: E402

falhas = []


def confere(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        falhas.append(msg)


class Motor:
    """O pedaco do motor que o metricas.py olha, com um disco de nome que nunca pode sair."""
    def __init__(self):
        self.effect, self.mic_mute, self._st = "nenhum", False, "idle"
        self.track = {"title": "Nome Secreto Da Musica", "path": r"C:\Users\fulano\Music\x.m4a"}

    def status(self):
        return self._st


def nova(cfg=None, instalador=None, tmp=None):
    met.escolha_do_instalador = lambda: instalador
    m = met.Metricas(cfg if cfg is not None else {}, lambda: None, estado=Path(tmp) / "metricas.json")
    m.fora = False  # pelo codigo ficaria "fora": o teste liga
    enviados = []
    m.envia = lambda url, dados, cab: enviados.append((url, dados, cab)) or 200
    return m, enviados


with tempfile.TemporaryDirectory() as tmp:
    # quem decide
    m, _ = nova(tmp=tmp)
    confere(m.situacao() == "decidir", "sem escolha no app nem no instalador: decidir (o aviso), e nada sai")
    m, _ = nova(instalador=True, tmp=tmp)
    confere(m.situacao() == "ligada", "o instalador marcou: ligada")
    m, _ = nova(cfg={"metricas": False}, instalador=True, tmp=tmp)
    confere(m.situacao() == "desligada", "a escolha feita na Vitrola vale sobre a do instalador")
    m2 = met.Metricas({}, lambda: None, mock=True, estado=Path(tmp) / "x.json")
    confere(m2.situacao() == "fora", "no --mock: fora, nunca envia")

    # desligada ou sem escolha: nada sai
    for cfg, inst, nome in (({}, None, "decidir"), ({"metricas": False}, None, "desligada")):
        m, env = nova(cfg=cfg, instalador=inst, tmp=tmp)
        m.evento("ativo", primeira_vez=True)
        m.erro(ValueError, ValueError("x"), None, "teste")
        m._manda_fila()
        confere(m.fila.empty() and not env, f"{nome}: nem evento nem erro")

    # a lista do que pode ir
    m, env = nova(instalador=True, tmp=tmp)
    try:
        m.evento("ativo", titulo="x")
        confere(False, "propriedade fora da lista e recusada")
    except ValueError:
        confere(True, "propriedade fora da lista e recusada")
    try:
        m.evento("busca")
        confere(False, "evento fora da lista e recusado")
    except ValueError:
        confere(True, "evento fora da lista e recusado")

    # o uso: musica tocando, voz com efeito, o efeito que liga
    m, env = nova(instalador=True, tmp=tmp)
    m.base["id"] = m._id()["id"]
    e = Motor()
    m.engine = e
    e._st = "playing"
    m._olha(5)
    e.effect = "eco"
    m._olha(5)
    e.mic_mute = True
    m._olha(5)  # microfone cortado: a voz nao conta
    e.mic_mute, e._st = False, "paused"
    e.effect = "robo"
    m._olha(5)
    m._fecha_uso()
    evs = [m.fila.get_nowait() for _ in range(m.fila.qsize())]
    nomes = [x["event"] for x in evs]
    confere(nomes == ["efeito", "efeito", "uso"], f"um 'efeito' por efeito ligado e o 'uso' no fim ({nomes})")
    uso = evs[-1]["properties"]
    confere(uso["musica_s"] == 15 and uso["voz_s"] == 10 and uso["efeitos"] == {"eco": 5, "robo": 5},
            f"o uso soma o que o motor fez ({uso['musica_s']}, {uso['voz_s']}, {uso['efeitos']})")
    permitidas = met.COMUNS | {"$process_person_profile", "$geoip_disable", "$lib"}
    fora = [(x["event"], k) for x in evs for k in x["properties"] if k not in met.EVENTOS[x["event"]] | permitidas]
    confere(not fora, f"so as propriedades da lista ({fora})")
    confere(all(x["properties"]["$process_person_profile"] is False and x["properties"]["$geoip_disable"] is True
                for x in evs), "sem perfil de pessoa e sem localizar pelo IP")

    # o que sai de verdade no envio: nada do disco, nem caminho
    for x in evs:
        m.fila.put(x)
    m._manda_fila()
    corpo = env[-1][1].decode("utf-8")
    confere(env[-1][0] == met.POSTHOG and "Nome Secreto" not in corpo and "fulano" not in corpo,
            "o envio vai ao PostHog sem o nome da musica e sem caminho")

    # o ativo do dia e o atualizou
    m, env = nova(instalador=True, tmp=tmp)
    Path(m.estado_path).unlink(missing_ok=True)
    m._dia_novo()
    m._dia = None
    m._dia_novo()
    evs = [m.fila.get_nowait() for _ in range(m.fila.qsize())]
    confere([x["event"] for x in evs] == ["ativo"] and evs[0]["properties"]["primeira_vez"] is True,
            "um 'ativo' por dia, com primeira_vez na primeira")
    est = json.loads(Path(m.estado_path).read_text(encoding="utf-8"))
    est.update(dia="2000-01-01", versao="0.0.1")
    Path(m.estado_path).write_text(json.dumps(est), encoding="utf-8")
    m._dia = None
    m._dia_novo()
    evs = [m.fila.get_nowait() for _ in range(m.fila.qsize())]
    confere([x["event"] for x in evs] == ["ativo", "atualizou"] and evs[1]["properties"]["de"] == "0.0.1",
            "a versao nova manda o 'atualizou' com a de antes")
    confere(re.fullmatch(r"[0-9a-f]{32}", evs[0]["distinct_id"] or "") is not None, "o id e aleatorio, de 32 hex")

    # desligar joga fora o que nao saiu
    m, env = nova(instalador=True, tmp=tmp)
    m.evento("ativo", primeira_vez=False)
    m.escolhe(False)
    m._manda_fila()
    confere(m.fila.empty() and not env and m.cfg["metricas"] is False, "desligar descarta a fila e nada sai")

    # a mensagem do erro, limpa
    casos = {
        "[Errno 2] No such file or directory: 'C:\\Users\\fulano\\Music\\Nome Secreto.m4a'": "fulano",
        'HTTP Error 403 for url https://youtube.com/watch?v=abc123': "abc123",
        "falhou em C:\\Users\\fulano\\AppData\\x.json": "fulano",
        "KeyError: 'Nome Secreto'": "Secreto",
        "mande para alguem@exemplo.com": "exemplo",
    }
    for txt, proibido in casos.items():
        confere(proibido not in met.limpa(txt), f"limpa: {met.limpa(txt)}")

    # o evento do erro: caminhos relativos, sem variavel, sem nome do PC
    m, env = nova(instalador=True, tmp=tmp)

    def explode(titulo):
        raise FileNotFoundError(f"no file: '{titulo}' in C:\\Users\\fulano\\x")

    try:
        try:
            explode("Nome Secreto")
        except FileNotFoundError as ex:
            raise RuntimeError("download failed") from ex
    except RuntimeError as ex:
        tipo, valor, tb = type(ex), ex, ex.__traceback__
    m.erro(tipo, valor, tb, "teste")
    m.erro(tipo, valor, tb, "teste")  # o mesmo erro: uma vez so
    import time as _t
    for _ in range(50):
        if env:
            break
        _t.sleep(0.05)
    confere(len(env) == 1, f"o mesmo erro sai uma vez por sessao ({len(env)})")
    url, corpo, cab = env[0]
    linhas = corpo.decode("utf-8").splitlines()
    ev = json.loads(linhas[2])
    confere(url.startswith("https://o4512454104907776.ingest.de.sentry.io/api/") and "sentry_key=" in cab["X-Sentry-Auth"],
            "o erro vai ao Sentry da Europa, com a chave de envio")
    texto = linhas[2]
    confere("Nome Secreto" not in texto and "fulano" not in texto and str(RAIZ).replace("\\", "\\\\") not in texto,
            "o erro vai sem o titulo, sem a pasta de quem usa e sem a pasta do app")
    confere(not ({"server_name", "request", "extra", "breadcrumbs"} & set(ev)), "sem nome do PC, pedido ou variaveis")
    tipos = [v["type"] for v in ev["exception"]["values"]]
    confere(tipos == ["FileNotFoundError", "RuntimeError"], f"a cadeia de erros, do mais velho ao mais novo ({tipos})")
    q = ev["exception"]["values"][0]["stacktrace"]["frames"][-1]
    confere(q["filename"] == "dev/testa_metricas.py" and q["function"] == "explode" and "vars" not in q,
            f"a linha da pilha relativa ao app, sem variaveis ({q})")
    confere(met._arquivo("C:/Program Files/Vitrola/_internal/aiohttp/web_protocol.py")[0] == "aiohttp/web_protocol.py"
            and met._arquivo("server.py") == ("server.py", True)
            and met._arquivo(r"C:\Python312\Lib\asyncio\events.py") == ("asyncio/events.py", False),
            "os caminhos da pilha: do app, de biblioteca e do Python")

if "--de-verdade" in sys.argv:
    import time
    import uuid
    from versao import VERSAO
    lote = {"api_key": met.POSTHOG_CHAVE, "batch": [{
        "event": "teste_de_envio", "distinct_id": "teste-" + uuid.uuid4().hex[:8],
        "properties": {"versao": VERSAO, "$process_person_profile": False, "$geoip_disable": True, "$lib": "vitrola"}}]}
    st = met._posta(met.POSTHOG, json.dumps(lote).encode(), {"Content-Type": "application/json"})
    confere(st == 200, f"o PostHog recebeu o evento de teste ({st})")
    ev = met.evento_de_erro(RuntimeError, RuntimeError("teste de envio"), None, "teste",
                            {"id": "teste", "windows": "teste", "lingua": "teste"})
    ev["environment"] = "teste"
    m, env = nova(instalador=True, tmp=tempfile.gettempdir())
    m.envia = met._posta
    m._manda_erro(ev)
    print(f"     o erro de teste {ev['event_id']} foi para o Sentry (environment teste)")
    time.sleep(1)

print("\ntudo certo" if not falhas else f"\n{len(falhas)} falha(s)")
sys.exit(1 if falhas else 0)
