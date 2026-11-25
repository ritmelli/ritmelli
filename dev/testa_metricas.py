"""Confere os dados de uso e os erros (metricas.py, o PRIVACIDADE.md): so sai o que esta no EVENTOS, nada sai sem a
escolha de quem usa, desligar joga fora o que nao saiu, o uso soma o que o motor faz, o "ativo" sai uma vez por dia, e
o erro vai sem caminho de pasta, sem o que esta entre aspas e sem variavel. E o "audio": a janela da saude da saida
para o jogo (a Rubber Band que atravessa duas janelas, o desligar no meio de uma), so com a escolha no texto de agora,
a versao do texto pela escolha do app ou do instalador (texto 1 ou 2, e o aviso de novo) e o --metricas-teste. Nao usa
a rede: o envio e trocado por uma lista.

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


def nova(cfg=None, instalador=None, tmp=None, texto_inst=None):
    # a escolha do instalador (o Metricas do HKLM) e a versao do texto dele (o MetricasVersao), trocadas por falsas
    met.escolha_do_instalador = lambda: instalador
    met.texto_do_instalador = lambda: texto_inst
    cfg = cfg if cfg is not None else {}
    # o gravar e o da App (grava_cfg): muda o cfg (e la grava o config.json, sob a trava do cfg)
    m = met.Metricas(cfg, lambda **mud: cfg.update(mud), estado=Path(tmp) / "metricas.json")
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
    confere(m.situacao() == "desligada", "a escolha feita no Ritmelli vale sobre a do instalador")
    m2 = met.Metricas({}, lambda **mud: None, mock=True, estado=Path(tmp) / "x.json")
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
    confere(nomes == ["efeito", "efeito", "uso", "efeito_tempo", "efeito_tempo"],
            f"um 'efeito' por efeito ligado, e o 'uso' e o tempo de cada efeito no fim ({nomes})")
    uso = evs[2]["properties"]
    tempos = {x["properties"]["efeito"]: x["properties"]["segundos"] for x in evs[3:]}
    confere(uso["musica_s"] == 15 and uso["voz_s"] == 10 and tempos == {"eco": 5, "robo": 5},
            f"o uso soma o que o motor fez ({uso['musica_s']}, {uso['voz_s']}, {tempos})")
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

    # a versao do texto: a escolha do app ou a do instalador, com texto 1 (sem versao) ou 2, e o aviso de novo
    def aviso(pub):
        """A mesma regra do metricasSePrecisar do tema."""
        return pub["situacao"] == "decidir" or (pub["situacao"] == "ligada" and pub["texto"] < pub["texto_atual"])

    casos = [
        # (cfg, instalador, MetricasVersao, situacao, texto, aviso)
        ({}, None, None, "decidir", 0, True),
        ({}, True, None, "ligada", 1, True),
        ({}, True, 2, "ligada", 2, False),
        ({}, False, None, "desligada", 1, False),
        ({}, False, 2, "desligada", 2, False),
        ({"metricas": True}, None, None, "ligada", 1, True),
        ({"metricas": True, "metricas_texto": 2}, None, None, "ligada", 2, False),
        ({"metricas": False}, True, 2, "desligada", 1, False),
        ({"metricas": False, "metricas_texto": 2}, None, None, "desligada", 2, False),
        ({"metricas": True}, False, 2, "ligada", 1, True),  # a escolha e do app: a versao e a dele, nao a do HKLM
        ({"metricas": True, "metricas_texto": 2}, False, None, "ligada", 2, False),
        ({"metricas": True, "metricas_texto": "2"}, None, None, "ligada", 1, True),  # versao torta: a de antes
    ]
    for cfg, inst, vers, sit, txt, av in casos:
        m, _ = nova(cfg=dict(cfg), instalador=inst, texto_inst=vers, tmp=tmp)
        pub = m.publico()
        confere(pub["situacao"] == sit and pub["texto"] == txt and pub["texto_atual"] == met.TEXTO == 2
                and aviso(pub) == av and m.texto() == txt,
                f"app {cfg}, instalador {inst} com a versao {vers}: {sit}, texto {txt}, "
                f"{'com' if av else 'sem'} aviso ({pub})")
    m2 = met.Metricas({}, lambda **mud: None, mock=True, estado=Path(tmp) / "x.json")
    confere(m2.publico()["texto"] == 0 and m2.texto() == 0, "fora (o --mock): texto 0, sem ler o instalador")
    for ligar in (True, False):
        m, _ = nova(cfg={"metricas": True}, instalador=True, texto_inst=None, tmp=tmp)
        m.escolhe(ligar)
        pub = m.publico()
        confere(m.cfg == {"metricas": ligar, "metricas_texto": 2} and pub["texto"] == 2 and not aviso(pub),
                f"escolher {'Enviar' if ligar else 'Nao enviar'} grava o metricas e o metricas_texto 2 juntos, e o "
                f"aviso nao volta ({m.cfg})")

    # o --metricas-teste: liga sem ler o instalador, guarda na memoria e o erro nem sai
    met.escolha_do_instalador, met.texto_do_instalador = (lambda: True), (lambda: 2)
    mt = met.Metricas({}, lambda **mud: None, mock=True, estado=Path(tmp) / "t.json", teste=True)
    confere(mt.situacao() == "decidir" and mt.texto() == 0,
            f"--metricas-teste: sem ler o instalador (que diria ligada), decidir ({mt.situacao()})")
    mt.cfg["metricas"] = True
    mt.evento("ativo", primeira_vez=True)
    mt._manda_fila()
    mt.erro(ValueError, ValueError("x"), None, "teste")
    confere([e["event"] for e in mt.guardados] == ["ativo"] and not mt.erros,
            "--metricas-teste: o lote fica na memoria, e o erro nao vai")

    # o "audio": a janela da saude da saida para o jogo, com um relogio de mentira
    class Relogio:
        t = 100.0

        def __call__(self):
            return self.t

    rel = Relogio()
    rb = met.EmCurso(rel)

    class MotorComAudio(Motor):
        def __init__(self):
            super().__init__()
            self.preparos, self.reserva_s = 0, 0.0
            self.janela = met.SaudeAudio(48000)

        def saude_audio(self):
            return self.janela

    def volta(e, s=0.01, **kw):
        """Uma volta do Injetor: s segundos no relogio, com o estado dado (o resto, o de um microfone normal)."""
        rel.t += s
        est = {"anel": True, "leitores": 1, "fx_no_filtro": False, "voz_taxa": 48000}
        est.update(kw)
        e.janela.volta(s, totais=(e.preparos, e.reserva_s, *rb.total()), **est)

    def audios(m):
        evs = [m.fila.get_nowait() for _ in range(m.fila.qsize())]
        return [x["properties"] for x in evs if x["event"] == "audio"], evs

    def fecha_janela(m):
        """O fim de uma janela, como no vigia: o "uso" e o "audio"."""
        m._fecha_uso()
        m._manda_audio()

    m, env = nova(cfg={"metricas": True, "metricas_texto": 2}, tmp=tmp)
    e = MotorComAudio()
    m.engine = e
    volta(e)
    e.janela.fila(4800)
    m._confere_audio()  # a escolha no texto de agora passa a valer: a janela comeca aqui, o de antes some
    volta(e)
    e.janela.fila(960)  # 20 ms
    e.preparos += 1  # uma passagem preparada
    volta(e)
    e.janela.fila(0, passagem=True)  # seca no meio dela
    rb_ctx = rb.roda()
    rb_ctx.__enter__()  # a Rubber Band comeca nesta janela...
    volta(e, 2.0)
    volta(e, 0.05, leitores=0)  # o leitor sumiu com o anel aberto
    volta(e, 3.0, leitores=0)
    volta(e, 0.01, leitores=2)
    fecha_janela(m)  # ...e a janela fecha com ela em curso
    a1, evs = audios(m)
    confere(len(a1) == 1 and set(a1[0]) - permitidas == met.EVENTOS["audio"],
            f"o 'audio' sai com exatamente as propriedades do EVENTOS, alem das comuns "
            f"({sorted(set(a1[0]) - permitidas) if a1 else a1})")
    fora = [(x["event"], k) for x in evs for k in x["properties"] if k not in met.EVENTOS[x["event"]] | permitidas]
    confere(not fora, f"o 'audio' so com as propriedades da lista, alem das comuns ({fora})")
    a1 = a1[0] if a1 else {}
    confere(a1.get("secas") == 1 and a1.get("secas_passagem") == 1 and a1.get("secas_esticamento") == 0
            and a1.get("folga_min_ms") == 0.0 and a1.get("passagens") == 1 and a1.get("esticamentos") == 1
            and a1.get("volta_max_ms") == 3000.0 and a1.get("leitor_perdido") == 1
            and a1.get("leitor_perdido_s") == 3 and a1.get("voz_taxa") == 48000,
            f"a primeira janela conta o que passou nela, e so depois do comeco ({a1})")
    confere(a1.get("esticamento_ms") == 5060, f"a Rubber Band em curso no fim da janela: o tempo ate ali ({a1})")
    volta(e, 1.0, fx_no_filtro=True)
    e.reserva_s += 2.0  # 2 s de voz pelo microfone de reserva (os quadros do _mic_cb)
    e.janela.fila(0, esticando=True)  # seca na janela seguinte, com a mesma chamada em curso
    volta(e, 2.0)
    rel.t += 0.5
    rb_ctx.__exit__(None, None, None)  # a chamada acaba na seguinte
    volta(e, 1.0)
    fecha_janela(m)
    a2, _ = audios(m)
    a2 = a2[0] if a2 else {}
    confere(a2.get("esticamento_ms") == 3500 and a2.get("esticamentos") == 0 and a2.get("secas_esticamento") == 1
            and a2.get("secas") == 1 and a2.get("passagens") == 0 and a2.get("leitor_perdido") == 0,
            f"a Rubber Band que comecou na janela de antes entra no esticamento_ms das duas, e a seca dela e desta ({a2})")
    confere(a2.get("fx_no_filtro_s") == 2 and a2.get("mic_reserva_s") == 2,
            f"o tempo com o efeito no filtro e com a voz pelo microfone de reserva ({a2})")

    # a janela em que a thread da saida nao andou (o audio fechado, o Injetor parado): nenhum "audio"
    fecha_janela(m)
    confere(not audios(m)[0], "sem nenhuma volta do Injetor na janela: o 'audio' nao sai (nem zerado)")
    e.janela.fila(0)
    volta(e, 0.01, fx_no_filtro=True)  # o efeito rodando no filtro...
    e.janela.anel_caiu()  # ...e o anel fecha por erro: a pausa de 3 s ate a volta seguinte nao conta nele
    volta(e, 3.0, anel=False, leitores=0)
    fecha_janela(m)
    a5, _ = audios(m)
    confere(len(a5) == 1 and a5[0]["fx_no_filtro_s"] == 0 and a5[0]["leitor_perdido"] == 0,
            f"o anel que caiu: a pausa ate o proximo nao conta como efeito nem como leitor perdido ({a5})")
    volta(e)
    fecha_janela(m)
    audios(m)
    e.janela.fila(0)  # a seca logo depois do fim da janela, antes da volta seguinte do Injetor
    fecha_janela(m)
    a7, _ = audios(m)
    confere(len(a7) == 1 and a7[0]["secas"] == 1, f"a seca entre o fim da janela e a volta seguinte conta ({a7})")

    # o desligar no meio da janela: o que ela contou some, e a de depois comeca na hora de ligar de novo
    volta(e)
    e.janela.fila(0)
    m.escolhe(False)
    fecha_janela(m)
    confere(not audios(m)[0], "desligada no meio da janela: o 'audio' nao sai")
    volta(e)
    e.janela.fila(0)
    e.janela.fila(0)
    m.escolhe(True)  # sem esperar o vigia
    volta(e)
    e.janela.fila(0)
    fecha_janela(m)
    a3, _ = audios(m)
    confere(len(a3) == 1 and a3[0]["secas"] == 1, f"ligada de novo: a janela comeca ali, sem o que veio antes ({a3})")

    # ligada num texto de antes: os outros eventos saem, o "audio" nao, ate o Enviar do aviso de novo
    m, env = nova(cfg={"metricas": True}, tmp=tmp)
    e = MotorComAudio()
    m.engine = e
    m._confere_audio()
    volta(e)
    e._st = "playing"
    m._olha(5)
    fecha_janela(m)
    a4, evs = audios(m)
    confere(not a4 and [x["event"] for x in evs] == ["uso"], f"ligada no texto 1: o 'uso' sai, o 'audio' nao ({evs})")
    m.escolhe(True)  # o Enviar do aviso de novo
    volta(e)
    fecha_janela(m)
    confere(len(audios(m)[0]) == 1, "o Enviar do aviso, no texto 2: o 'audio' passa a sair")
    m, env = nova(cfg={"metricas": True, "metricas_texto": 2}, tmp=tmp)
    m.engine = Motor()  # o --mock, ou o audio fechado: sem a janela
    m._confere_audio()
    fecha_janela(m)
    confere(not audios(m)[0], "sem Injetor (o --mock, o audio fechado): nenhum 'audio'")

    # a escolha no texto de agora que ja valia ao abrir: o vigia nao joga fora o comeco da janela do Injetor
    import threading
    import time as _t
    m, env = nova(cfg={"metricas": True, "metricas_texto": 2}, tmp=tmp)
    e = MotorComAudio()
    volta(e)
    e.janela.fila(0)  # a seca logo na abertura do audio
    th = threading.Thread(target=m.vigia, args=(e,), daemon=True)
    th.start()
    for _ in range(100):
        if m._audio_vale:
            break
        _t.sleep(0.01)
    volta(e)
    m.fecha()  # fechado antes da primeira volta do vigia
    th.join(5)
    a6 = [x for _, corpo, _ in env for x in json.loads(corpo).get("batch", []) if x["event"] == "audio"]
    confere(not th.is_alive() and len(a6) == 1 and a6[0]["properties"]["secas"] == 1
            and re.fullmatch(r"[0-9a-f]{32}", a6[0]["distinct_id"] or "") is not None,
            f"aberto com a escolha no texto 2 e fechado logo: a janela conta desde a abertura do audio, sai com o id, "
            f"e o vigia para ({a6})")

    # o lote que falha enquanto a pessoa desliga (e liga de novo) nao volta para a fila
    m, env = nova(cfg={"metricas": True, "metricas_texto": 2}, tmp=tmp)
    m.evento("ativo", primeira_vez=False)

    def falha_desligando(url, dados, cab):
        m.escolhe(False)  # desligou durante o envio...
        m.escolhe(True)  # ...e ligou de novo
        raise OSError("sem rede")
    m.envia = falha_desligando
    m._manda_fila()
    confere(m.fila.empty(), "desligada durante o envio que falhou: o lote nao volta para a fila, nem ligando de novo")
    m.evento("ativo", primeira_vez=False)
    m.envia = lambda url, dados, cab: (_ for _ in ()).throw(OSError("sem rede"))
    m._manda_fila()
    confere(m.fila.qsize() == 1, "sem rede, com o envio ligado: o lote volta para a fila")

    # o instalador grava a versao do texto de agora, e a politica lista cada campo do "audio"
    iss = (RAIZ / "instalador" / "ritmelli.iss").read_text(encoding="utf-8-sig")
    reg = re.search(r'ValueName: "MetricasVersao"; ValueData: "(\d+)"; Flags: ([^;]+); Check: (\w+)', iss)
    confere(reg is not None and int(reg.group(1)) == met.TEXTO and reg.group(2).split() ==
            ["uninsdeletevalue", "uninsdeletekeyifempty"] and reg.group(3) == "GravaMetricas",
            f"o instalador grava o MetricasVersao {met.TEXTO}, sob o GravaMetricas ({reg and reg.groups()})")
    pol = (RAIZ / "PRIVACIDADE.md").read_text(encoding="utf-8")
    sem = sorted(c for c in met.EVENTOS["audio"] if pol.count(f"`{c}`") < 2)
    confere(not sem, f"o PRIVACIDADE.md lista cada campo do 'audio', nas duas linguas (faltam: {sem})")

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
    confere(met._arquivo("C:/Program Files/Ritmelli/_internal/aiohttp/web_protocol.py")[0] == "aiohttp/web_protocol.py"
            and met._arquivo("server.py") == ("server.py", True)
            and met._arquivo(r"C:\Python312\Lib\asyncio\events.py") == ("asyncio/events.py", False),
            "os caminhos da pilha: do app, de biblioteca e do Python")

    # todo modulo do app e "nosso": o filtro da conexao fechada (abaixo) deixaria passar o erro de um modulo esquecido
    modulos = {p.stem for p in RAIZ.glob("*.py")} | {
        p.name for p in RAIZ.iterdir() if p.is_dir() and p.name not in ("dev", "instalador") and any(p.glob("*.py"))}
    confere(modulos <= met.NOSSOS, f"todo modulo do app esta no NOSSOS (faltam: {sorted(modulos - met.NOSSOS)})")

    # a conexao fechada pelo outro lado (#116), pelo tratador de verdade de um loop do asyncio: o erro de conexao com a
    # pilha so do asyncio (o _call_connection_lost do loop Proactor, como o que chegou ao Sentry) nao vai; com linha do
    # app vai, e os outros erros tambem. O tratador de antes (o log) recebe todos
    import asyncio
    import gc
    import time

    def de(arquivo, codigo, nome):
        """Uma funcao cujo codigo mora em arquivo: a linha dela na pilha e desse arquivo, como a de verdade."""
        ns = {}
        exec(compile(codigo, arquivo, "exec"), ns)
        return ns[nome]

    def envios(enviados, n):
        """Quantos erros sairam: espera ate 3 s pelo n-esimo (o envio e numa thread), e um pouco mais por um a mais."""
        for _ in range(60):
            if len(enviados) >= n:
                break
            time.sleep(0.05)
        time.sleep(0.1)
        return len(enviados)

    do_asyncio, do_app = str(Path(asyncio.__file__).parent / "proactor_events.py"), str(RAIZ / "server.py")
    m, env = nova(instalador=True, tmp=tmp)
    loop = asyncio.new_event_loop()
    log = []
    loop.set_exception_handler(lambda lp, ctx: log.append(type(ctx.get("exception")).__name__))
    m.no_loop(loop)

    def no_loop_roda(cb):
        loop.call_soon(cb)
        loop.run_until_complete(asyncio.sleep(0.01))

    fechadas = ["ConnectionResetError", "ConnectionAbortedError", "BrokenPipeError"]
    for tipo in fechadas:
        no_loop_roda(de(do_asyncio, f"def _call_connection_lost():\n    raise {tipo}(10054, 'fechada')\n",
                        "_call_connection_lost"))
    confere(envios(env, 1) == 0 and not m.erros and log == fechadas,
            f"a conexao fechada pelo outro lado, so com o asyncio na pilha: nada vai ao Sentry, o log registra ({log})")
    no_loop_roda(de(do_app, "def responde():\n    raise ConnectionResetError(10054, 'no codigo do app')\n", "responde"))
    confere(envios(env, 1) == 1 and log[-1] == "ConnectionResetError",
            "o mesmo erro com linha do app na pilha: vai ao Sentry")
    no_loop_roda(de(do_asyncio, "def _loop_reading():\n    raise ValueError('outro erro')\n", "_loop_reading"))
    confere(envios(env, 2) == 2 and log[-1] == "ValueError",
            "outro erro, mesmo so com o asyncio na pilha: vai ao Sentry")
    tarefa = loop.create_task(de(do_app, "async def toca():\n    raise RuntimeError('falha de verdade')\n", "toca")())
    loop.run_until_complete(asyncio.sleep(0.01))
    del tarefa
    gc.collect()  # a tarefa que ninguem esperou chega ao tratador ao sair da memoria
    confere(envios(env, 3) == 3 and log[-1] == "RuntimeError",
            "o erro de verdade numa tarefa do asyncio, com linha do app: vai ao Sentry, e o log registra")
    confere(all(u.startswith("https://o4512454104907776.ingest.de.sentry.io/") for u, _, _ in env),
            "os tres foram ao Sentry")
    loop.close()

if "--de-verdade" in sys.argv:
    import time
    import uuid
    from versao import VERSAO
    lote = {"api_key": met.POSTHOG_CHAVE, "batch": [{
        "event": "teste_de_envio", "distinct_id": "teste-" + uuid.uuid4().hex[:8],
        "properties": {"versao": VERSAO, "$process_person_profile": False, "$geoip_disable": True, "$lib": "ritmelli"}}]}
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
