"""Confere o protocolo da sessao remota v1 (docs/protocolo-remoto.md): os esquemas, o mapa de cada comando para a rota
local e as fixtures dos dois sentidos, em docs/protocolo-remoto/v1/.

- Os esquemas sao JSON Schema validos, toda fixture valida passa e toda invalida e recusada.
- O mapa de comandos bate com a tabela do permissao.py: toda rota do mapa e do papel remoto, e toda rota do papel
  remoto esta no mapa; cada comando traduzido vira o pedido que a fixture diz.
- A posicao: cada cenario roda o motor de verdade sem som e sem aparelho (o Engine sem o __init__, como os outros
  testes do motor): o _plano_dois e o _plano_batida montam a passagem (so a medida das batidas trocada por numeros
  fixos), o _mede a aplica nas filas, o _vira vira o prato, o _cancela_passagem cancela, e o _tira consome a fila de
  10 em 10 ms, como o callback. Os rotulos dos blocos consumidos sao o mapa de amostras do motor. Cada foto da
  fixture reconstroi a posicao so com ela (a ancora e os segmentos) e bate com cada rotulo, a menos de uma amostra,
  da hora dela ate a proxima descontinuidade.
- O produtor de referencia (o que o PC publica) roda junto, a cada bloco: o rev so sobe quando a projecao ou a
  ancora mudam, e a sequencia de eventos tem de ser a da fixture.
- O relay de referencia guarda a foto da sessao e descarta o rev antigo e a sessao anterior; quem recebe acha o
  relogio do PC pelo menor atraso visto.

    python dev/testa_protocolo.py           confere
    python dev/testa_protocolo.py --gera    escreve as fixtures de novo (depois de mudar o motor ou o protocolo)

Precisa do jsonschema e das bibliotecas do motor (requirements-dev.txt). Sai 1 se algo falha."""
import argparse
import bisect
import contextlib
import copy
import io
import json
import math
import re
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import jsonschema  # noqa: E402
import numpy as np  # noqa: E402
from referencing import Registry, Resource  # noqa: E402

with contextlib.redirect_stderr(io.StringIO()):  # o fx avisa das vozes do pedal que faltam: nada disso importa aqui
    import engine as eng  # noqa: E402
import permissao as perm  # noqa: E402
import transicao  # noqa: E402

V1 = RAIZ / "docs" / "protocolo-remoto" / "v1"
FIX = V1 / "fixtures"
SR, BLOCO = eng.SR, eng.BLOCK
POR_MS = SR / 1000          # amostras de saida por ms
T0_MS = 1_000_000.0         # o relogio do PC (ms) na amostra 0 de cada cenario
SESSAO = "sessao-de-teste-01"
TOL_S = 1 / SR              # a posicao reconstruida bate com o rotulo do bloco a menos de uma amostra
MUDA_S = 0.5 / SR           # o produtor: a posicao que muda mais que meia amostra muda a ancora
VOL = 0.6


# ---------------------------------------------------------------------------------------------- esquemas e mapa

def esquemas():
    docs = {n: json.loads((V1 / f"{n}.schema.json").read_text("utf-8"))
            for n in ("estado", "comando", "argumentos", "resultado")}
    reg = Registry().with_resources([(d["$id"], Resource.from_contents(d)) for d in docs.values()])
    return docs, {n: jsonschema.Draft202012Validator(d, registry=reg) for n, d in docs.items()}


MAPA = json.loads((V1 / "comandos.json").read_text("utf-8"))


def capacidades(rotas=None):
    """Os comandos que o papel remoto alcanca: os que tem todas as rotas dele no caps (o do permissao.py, sem rotas)."""
    rotas = set(perm.caps("remoto")["rotas"] if rotas is None else rotas)
    return [c for c, rs in MAPA["comandos"].items() if all(f"{r['metodo']} {r['rota']}" in rotas for r in rs)]


def traduz(cmd):
    """O pedido local de um comando: (metodo, caminho, corpo). O argumento com o nome de um {campo} da rota vai no
    caminho; os outros, no corpo; com mais de uma rota, vale a do argumento do quando."""
    args = dict(cmd["args"])
    rotas = MAPA["comandos"][cmd["comando"]]
    r = rotas[0] if len(rotas) == 1 else next(r for r in rotas if r["quando"] in args)
    caminho = r["rota"]
    for campo in [c for c in args if "{" + c + "}" in caminho]:
        caminho = caminho.replace("{" + campo + "}", str(args.pop(campo)))
    return r["metodo"], caminho, args


# -------------------------------------------------------------------------------------- quem recebe (o cliente)

def avanco(v, d):
    """Quanto o disco anda, em amostras dele, em d amostras de saida na velocidade v (um numero, ou o meio cosseno
    v(i) = ate + (de - ate) * (1 + cos(pi * i / total)) / 2 a partir da fase): a soma de v(i), em forma fechada."""
    if not isinstance(v, dict):
        return v * d
    a, n = v["fase"], v["total"]
    b = a + d
    soma_cos = (math.sin(math.pi * (b - 0.5) / n) - math.sin(math.pi * (a - 0.5) / n)) / (2 * math.sin(math.pi / (2 * n)))
    return v["ate"] * d + (v["de"] - v["ate"]) / 2 * (d + soma_cos)


def posicao(anc, t_ms):
    """A posicao do disco no instante t_ms do relogio do PC, so pela ancora. Cada segmento vale de [comeco, comeco + n)
    (o pos do seguinte entra exatamente na fronteira); depois do ultimo segmento finito, a posicao fica parada."""
    p = anc["pos"]
    if not anc["anda"]:
        return p
    m = round((t_ms - anc["t"]) * anc["taxa"] / 1000, 6)
    if m <= 0:
        return p
    for i, s in enumerate(anc["segmentos"]):
        if i and "pos" in s:
            p = s["pos"]
        if s["n"] is None or m < s["n"]:
            return p + avanco(s["v"], m) / anc["taxa"]
        p += avanco(s["v"], s["n"]) / anc["taxa"]
        m -= s["n"]
    return p


def corta(segs, c):
    """Os segmentos depois de c amostras de saida: o que acabou sai, o do meio encurta (e o cosseno anda a fase)."""
    out = []
    for s in segs:
        s = dict(s)
        if s["n"] is not None and c >= s["n"]:
            c -= s["n"]
            continue
        if c:
            if s["n"] is not None:
                s["n"] -= c
            if isinstance(s["v"], dict):
                s["v"] = dict(s["v"], fase=s["v"]["fase"] + c)
            c = 0
        if not out:
            s.pop("pos", None)  # o primeiro comeca na posicao da ancora
        out.append(s)
    return out


def avanca(anc, m):
    """A mesma ancora m amostras de saida depois."""
    t = anc["t"] + m / POR_MS
    if not anc["anda"]:
        return dict(anc, t=t)
    return dict(anc, pos=posicao(anc, t), t=t, segmentos=corta(anc["segmentos"], m))


def equivalentes(a, b):
    """As duas ancoras dizem o mesmo daqui em diante."""
    if a["faixa"] != b["faixa"] or a["anda"] != b["anda"] or abs(a["pos"] - b["pos"]) > MUDA_S:
        return False
    if len(a["segmentos"]) != len(b["segmentos"]):
        return False
    for x, y in zip(a["segmentos"], b["segmentos"]):
        if x["n"] != y["n"] or x.get("preenchimento") != y.get("preenchimento") or ("pos" in x) != ("pos" in y):
            return False
        if "pos" in x and abs(x["pos"] - y["pos"]) > 1e-9:
            return False
        vx, vy = x["v"], y["v"]
        if isinstance(vx, dict) != isinstance(vy, dict):
            return False
        if isinstance(vx, dict):
            if (vx["total"], vx["fase"]) != (vy["total"], vy["fase"]) or abs(vx["de"] - vy["de"]) > 1e-12 \
                    or abs(vx["ate"] - vy["ate"]) > 1e-12:
                return False
        elif abs(vx - vy) > 1e-12:
            return False
    return True


class Relogio:
    """O relogio do PC visto por quem recebe: o desvio e o menor (chegada - agora - retido_ms) desde que a conexao
    abriu ou a sessao mudou. Com a foto atrasada, o erro e o atraso dela, ate chegar uma mensagem mais rapida."""

    def __init__(self):
        self.desvio = self.sessao = None

    def recebe(self, msg, chegada_ms):
        a = chegada_ms - msg["agora"] - msg.get("retido_ms", 0)
        if msg["sessao"] != self.sessao:
            self.sessao, self.desvio = msg["sessao"], a
        else:
            self.desvio = min(self.desvio, a)

    def pc(self, local_ms):
        return local_ms - self.desvio


class Cliente:
    """Quem recebe: so a sessao dele, e o estado com rev maior que o ultimo. A posicao sai da ancora mais nova cujo t
    ja chegou (a foto adiantada espera o t dela); antes de qualquer uma, o pos da primeira; com o prato vazio, nada."""

    def __init__(self, sessao):
        self.sessao, self.rev, self.estado, self.ancoras = sessao, 0, None, []

    def recebe(self, msg):
        if msg["sessao"] != self.sessao or msg["tipo"] != "estado" or msg["rev"] <= self.rev:
            return False
        self.rev, self.estado = msg["rev"], msg["estado"]
        if msg["estado"]["ancora"] is None:
            self.ancoras.clear()  # o prato vazio: nada mais anda
        else:
            self.ancoras.append(msg["estado"]["ancora"])
        return True

    def posicao(self, t_pc):
        """(faixa, posicao) no instante t_pc do relogio do PC, ou None com o prato vazio."""
        if not self.ancoras:
            return None
        valem = [a for a in self.ancoras if a["t"] <= t_pc]
        a = valem[-1] if valem else self.ancoras[0]
        return a["faixa"], posicao(a, t_pc) if valem else a["pos"]


def valida_estado(val, msg):
    """O esquema e o que ele nao diz: a ancora da faixa da projecao, so o ultimo segmento aberto, e o cosseno dentro do
    total. Devolve a lista de problemas."""
    erros = [e.message for e in val.iter_errors(msg)]
    if erros or msg["tipo"] != "estado" or msg["estado"]["ancora"] is None:
        return erros
    anc = msg["estado"]["ancora"]
    if anc["faixa"] != msg["estado"]["faixa"]["id"]:
        erros.append("a ancora e de outra faixa")
    if any(s["n"] is None for s in anc["segmentos"][:-1]):
        erros.append("segmento aberto antes do ultimo")
    if any(isinstance(s["v"], dict) and s["v"]["fase"] + s["n"] > s["v"]["total"] for s in anc["segmentos"]):
        erros.append("cosseno alem do total")
    return erros


# ------------------------------------------------------------------------------------------- o relay

class Relay:
    """O relay de referencia: guarda a ultima foto da sessao ativa e a entrega a quem conecta, com o retido_ms."""

    def __init__(self):
        self.sessao = self.foto = None
        self.guardada_em = 0.0

    def aceita(self, sessao):
        """Uma sessao nova (o convite aceito): a foto da anterior deixa de valer."""
        self.sessao, self.foto = sessao, None

    def do_pc(self, msg, agora_relay):
        """guarda (e repassa), repassa (o pulso) ou descarta."""
        if msg["sessao"] != self.sessao:
            return "descarta"
        if msg["tipo"] == "pulso":
            return "repassa"
        if self.foto is not None and msg["rev"] <= self.foto["rev"]:
            return "descarta"
        self.foto, self.guardada_em = msg, agora_relay
        return "guarda"

    def conecta(self, agora_relay):
        if self.foto is None:
            return None
        return dict(self.foto, retido_ms=agora_relay - self.guardada_em)


def resultado_repetido(guardados, cmd):
    """A repeticao pelo id: o mesmo comando com os mesmos argumentos recebe o resultado guardado; outro, id_repetido."""
    g = guardados.get(cmd["id"])
    if g is None:
        return None
    if (g["comando"], g["args"]) == (cmd["comando"], cmd["args"]):
        return g["resultado"]
    return {"protocolo": 1, "tipo": "resultado", "sessao": cmd["sessao"], "id": cmd["id"], "ok": False,
            "erro": "id_repetido"}


# ------------------------------------------------------------------------------------------ o PC (o produtor)

CAMPOS_FAIXA = ("id", "title", "channel", "duration", "youtube_id", "thumb")
CAMPOS_FILA = ("qid", "id", "title", "channel", "duration", "youtube_id", "thumb")
EVENTO_DO_STATUS = {"playing": "retomada", "paused": "pausa", "buffering": "buffering", "ended": "fim",
                    "idle": "parada"}
TEXTO_MAX, CAPA_MAX, FILA_MAX, DURACAO_MAX = 400, 500, 500, 86400
YT_ID = re.compile(r"[A-Za-z0-9_-]{11}")  # com fullmatch: o $ casa antes de um \n no fim
TICK_BLOCOS = 7   # o tick do servidor (o TICK de 1/15 s do server.py) em blocos de 10 ms
JANELA = SR       # quanto da fila o PC olha adiante: 1 s
SEGMENTOS_MAX = 8  # o maxItems dos segmentos no estado.schema.json


def _https(v):
    return v if isinstance(v, str) and v.startswith("https://") and len(v) <= CAPA_MAX else None


def _texto(v):
    """O texto cortado; o link (o titulo que o servidor poe quando so tem o endereco) nao sai do PC."""
    if not isinstance(v, str) or v.startswith(("http://", "https://")):
        return None
    return v[:TEXTO_MAX]


def _duracao(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= DURACAO_MAX else None


def _item(x, campos):
    d = {k: x.get(k) for k in campos}
    d.update(title=_texto(x.get("title")), channel=_texto(x.get("channel")), duration=_duracao(x.get("duration")),
             thumb=_https(x.get("thumb")),
             youtube_id=x["youtube_id"] if isinstance(x.get("youtube_id"), str) and YT_ID.fullmatch(x["youtube_id"])
             else None)
    return d


def projeta(local):
    """A projecao do estado local (o mesmo do GET /api/state) para fora do PC, sem a ancora: so os campos da lista, e
    sempre dentro do esquema (texto cortado, link, duracao, capa e id de video fora do formato em null, a fila nas
    primeiras FILA_MAX)."""
    tr = local.get("track")
    faixa = None
    if tr is not None and local["status"] != "idle":
        faixa = {**_item(tr, CAMPOS_FAIXA), "stream": bool(tr.get("stream"))}
    return {"status": local["status"], "faixa": faixa,
            "fila": [{**_item(x, CAMPOS_FILA), "auto": bool(x.get("auto"))} for x in (local.get("queue") or [])[:FILA_MAX]],
            "vol": local["vol"], "abaixa": local.get("abaixa"),
            "capacidades": capacidades((local.get("caps") or {}).get("rotas", []))}


def _continua(t_ant, n_ant, t):
    return abs(t_ant + n_ant / SR - t) <= 1e-7


def cauda(q, pula, eof, orcamento):
    """Os segmentos em 1 da fila q depois de pula amostras (blocos inteiros): um por trecho de rotulos continuos, com
    o pos dele, olhando JANELA amostras adiante e no maximo orcamento trechos. O ultimo fica aberto, salvo quando a
    fila acaba dentro da janela (ou bem no fim dela) com o fim do disco ja lido: ai a posicao para no fim."""
    if orcamento <= 0:
        return []
    segs, visto, ant, ultimo = [], 0, None, len(q) - 1
    for i, (t, a) in enumerate(q):
        n = len(a)
        if pula > 0:
            assert pula >= n, "a curva acaba no meio de um bloco"
            pula -= n
            continue
        if ant is not None and _continua(ant[0], ant[1], t):
            segs[-1]["n"] += n
        elif len(segs) == orcamento:
            segs[-1]["n"] = None  # sem lugar para o trecho seguinte: o de agora segue a 1 ate a ancora nova
            return segs
        else:
            segs.append({"n": n, "v": 1.0, "pos": float(t)})
        ant = (t, n)
        visto += n
        if visto >= JANELA:
            if not (i == ultimo and eof):
                segs[-1]["n"] = None
            return segs
    if segs and not eof:
        segs[-1]["n"] = None
    return segs


def _sem_pos_no_primeiro(segs):
    if segs:
        segs[0] = {k: v for k, v in segs[0].items() if k != "pos"}
    return segs


def _total(curva):
    return sum(s["n"] for s in curva["segmentos"])


def registra_curva(curvas, deck, nova):
    """A curva de um plano aplicado no deck: a que ja estava nele fica so com o trecho antes da nova (o _mede troca a
    cauda da fila a partir dali)."""
    lista = []
    for cv in curvas.get(id(deck), []):
        fica = nova["inicio"] - cv["inicio"]
        if fica <= 0:
            continue
        if fica < _total(cv):
            segs, n = [], fica
            for s in cv["segmentos"]:
                if n <= 0:
                    break
                s = dict(s)
                if s["n"] > n:
                    s["n"] = n
                n -= s["n"]
                segs.append(s)
            cv = dict(cv, segmentos=segs)
        lista.append(cv)
    curvas[id(deck)] = lista + [nova]


def segmentos(q, curvas, c, eof, recua=0):
    """Os segmentos de velocidade do prato a partir da amostra consumida c - recua do deck (recua > 0: a ancora de uma
    descontinuidade que ja tocou), com c as amostras consumidas do deck agora e q a fila dele. Cada curva de plano
    aplicado ocupa as amostras consumidas de inicio a inicio + total: entre elas e antes delas, o disco anda a 1; nelas,
    os segmentos delas; depois da ultima, a cauda da fila."""
    cur = c - recua
    segs = []
    for cv in sorted(curvas, key=lambda x: x["inicio"]):
        ini, fim = cv["inicio"], cv["inicio"] + _total(cv)
        if fim <= cur:
            continue
        if cur < ini:
            segs.append({"n": ini - cur, "v": 1.0})
            cur = ini
        segs += corta(cv["segmentos"], cur - ini)
        cur = fim
    if len(segs) >= SEGMENTOS_MAX:
        return _sem_pos_no_primeiro(segs[:SEGMENTOS_MAX])
    orcamento = SEGMENTOS_MAX - len(segs)
    if cur >= c:
        rabo = cauda(q, cur - c, eof, orcamento)
    else:  # a curva acabou depois da marca: o comeco da cauda ja tocou e segue na mesma velocidade (sem salto)
        k = c - cur
        rabo = cauda(q, 0, eof, orcamento)
        if rabo:
            rabo[0]["pos"] = max(0.0, rabo[0]["pos"] - k / SR)
            if rabo[0]["n"] is not None:
                rabo[0]["n"] += k
        else:
            rabo = [{"n": k, "v": 1.0}]
    return _sem_pos_no_primeiro((segs + rabo)[:SEGMENTOS_MAX])


class Produtor:
    """O que o PC publica. O tick (TICK_BLOCOS) olha o prato entre dois blocos: o rotulo do proximo bloco e a amostra
    de saida em que ele toca. Publica um estado novo (rev + 1) quando a projecao muda, quando a ancora de antes,
    adiantada em amostras, deixa de bater com a que sairia agora (o mapa mudou), e em cada fronteira de segmento que o
    prato cruzou, em ordem. A descontinuidade que ja tocou (a marca do callback: a virada, a retomada, o salto de
    rotulo) sai com o instante e o rotulo dela; a fronteira, com o instante dela; o prato que parou e voltou entre dois
    ticks, com as duas transicoes. A reconexao manda a foto completa na hora. O pulso so repete o rev."""

    def __init__(self, e, sim, curvas, fila):
        self.e, self.sim, self.curvas, self.fila = e, sim, curvas, fila
        self.rev, self.pub, self.msgs, self.lidas = 0, None, [], 0
        self.pub_c = 0  # a amostra consumida do prato no instante da ancora publicada
        self.pub_deck = None  # o deck dela
        self.pendente = None  # a foto de inicio ou de reconexao que espera a virada do callback

    def curvas_do_prato(self):
        return self.curvas.get(id(self.e._deck), [])

    def vira_pendente(self):
        """A fila do prato acabou com o fim lido e o callback seguinte vira (a proxima com blocos, ou o _virar_em ja
        alcancado, como no _mixa): o prato nao parou, e o que ele toca agora so o callback decide."""
        e = self.e
        return (not e._q and e._eof_gen == e._gen and e._pronto is not None and not e.paused
                and (bool(e._pronto.q) or (e._virar_em is not None and e.pos >= e._virar_em)))

    def status(self):
        """O do motor, com a fila vazia e o fim do disco lido ja como o fim: o motor so diz ended no callback
        seguinte, mas o prato parou ali (salvo com a virada pendente)."""
        e = self.e
        st = e.status()
        return "ended" if st == "playing" and not e._q and e._eof_gen == e._gen and not self.vira_pendente() else st

    def ancora(self, u, pos=None, recua=0, anda=None):
        e = self.e
        tr, q, st = e.track, e._q, self.status()
        if tr is None:
            return None
        if pos is None:
            pos = q[0][0] if q and not e.ended else e.pos
        anda = st == "playing" if anda is None else anda
        eof, c, cvs = e._eof_gen == e._gen, self.sim.c(), self.curvas_do_prato()
        if not anda:
            segs = []
        elif recua and not any(cv["inicio"] + _total(cv) > c - recua for cv in cvs):
            segs = self._ja_tocou(float(pos), c - recua, c, q, eof)
        else:
            segs = segmentos(q, cvs, c, eof, recua)
        return {"faixa": tr["id"], "pos": float(pos), "t": ms(u), "taxa": SR, "anda": anda, "segmentos": segs}

    def _ja_tocou(self, pos, c_m, c, q, eof):
        """Sem curva, a ancora de uma marca que ja tocou: um trecho a 1 da marca ate cada salto que tocou depois dela
        (com o pos dele) e ate agora; depois, a cauda da fila, que so emenda no ultimo trecho quando o rotulo continua
        (a volta do Repetir logo adiante tem o pos dela)."""
        pontos = [(c_m, pos)]
        for m in self.sim.marcas:  # so onde o rotulo salta: a retomada que continua nao abre trecho
            if (m["tipo"] == "anda" and m["deck"] == id(self.e._deck) and c_m < m["c"] <= c
                    and not _continua(pontos[-1][1], m["c"] - pontos[-1][0], m["rotulo"])):
                pontos.append((m["c"], m["rotulo"]))
        pre = [{"n": b[0] - a[0], "v": 1.0, "pos": a[1]} for a, b in zip(pontos, pontos[1:] + [(c, None)]) if b[0] > a[0]]
        rabo = cauda(q, 0, eof, SEGMENTOS_MAX - len(pre) + 1)
        if pre and rabo and _continua(pre[-1]["pos"], pre[-1]["n"], rabo[0]["pos"]):
            ult = pre.pop()
            rabo[0]["pos"] = ult["pos"]
            if rabo[0]["n"] is not None:
                rabo[0]["n"] += ult["n"]
        segs = pre + rabo
        if len(segs) > SEGMENTOS_MAX:
            segs = segs[:SEGMENTOS_MAX]
            segs[-1]["n"] = None
        return _sem_pos_no_primeiro(segs)

    def projecao(self, u):
        e = self.e
        p = projeta({"status": self.status(), "track": e.track, "queue": self.fila(e), "vol": VOL, "abaixa": None,
                     "caps": perm.caps("remoto")})
        p["ancora"] = self.ancora(u)
        return p

    def _publica(self, ev, p, u, c=None, deck=None):
        self.rev += 1
        self.pub, self.pub_c = p, self.sim.c() if c is None else c
        self.pub_deck = deck if deck is not None else id(self.e._deck) if p["faixa"] is not None else None
        self.msgs.append({"evento": ev, "msg": {"protocolo": 1, "tipo": "estado", "sessao": SESSAO, "rev": self.rev,
                                                "origem": ev if ev in ("inicio", "reconexao") else "mudanca",
                                                "agora": ms(u), "estado": p}})

    def _fronteiras(self, u, base, ate=None):
        """Cada fronteira que o prato cruzou desde a ancora publicada ate a amostra ate (por padrao, agora), em ordem: a
        ancora no instante dela. Com o prato seguindo igual, a janela da fila e refeita dali; antes de uma quebra (outro
        deck, parada, salto que ela nao previa), so a de antes adiantada ate la, porque a fila ja e a de depois."""
        ate = u if ate is None else ate
        refaz = (ate == u and self.e.track is not None and self.status() == "playing"
                 and id(self.e._deck) == self.pub_deck and self.e.track["id"] == (self.pub["faixa"] or {}).get("id"))
        while self.cruzou(ate):
            a = self.pub["ancora"]
            m = a["segmentos"][0]["n"]
            u_f, c_f = self._u(a) + m, self.pub_c + m
            anc = (self.ancora(u_f, posicao(a, ms(u_f)), self.sim.c() - c_f, anda=True) if refaz
                   else dict(avanca(a, m), t=ms(u_f)))
            self._publica("fronteira", dict(base, ancora=anc), u, c_f, None if refaz else self.pub_deck)

    def olha(self, u, reconexao=False):
        if self.vira_pendente():  # a foto de agora espera o callback que vira (ate um bloco); o tick nao publica
            if self.pub is None or reconexao:
                self.pendente = "reconexao" if reconexao else "inicio"
            return
        p = self.projecao(u)
        if self.pub is None or reconexao:  # a ancora de agora: as marcas de antes ja estao nela
            self.lidas = len(self.sim.marcas)
            return self._publica("reconexao" if reconexao else "inicio", p, u)
        # as marcas desde o tick de antes, na ordem em que o callback anotou (a do bloco do tick vem depois dele)
        self._transicoes(u, p, self.sim.marcas[self.lidas:])
        velha = self.pub["ancora"]
        quebrou = velha is not None and velha["anda"] and (
            p["status"] != "playing" or id(self.e._deck) != self.pub_deck
            or (p["faixa"] or {}).get("id") != velha["faixa"]
            or abs(posicao(velha, ms(u)) - p["ancora"]["pos"]) > MUDA_S)
        # o prato quebrou bem no tick (a marca do bloco dele so vem depois deste tick): so as fronteiras estritamente
        # antes, porque a bem no instante dela nao tocou
        self._fronteiras(u, self.pub, ate=u - 1 if quebrou else u)
        ev = self.diferenca(p, u)
        c_ancora = None
        if ev == "fronteira":
            self._fronteiras(u, p)
            ev = None
        elif ev == "projecao":  # so a projecao mudou: as fronteiras cruzadas antes, e a ancora publicada segue
            self._fronteiras(u, self.pub)
            p["ancora"], c_ancora = self.pub["ancora"], self.pub_c
        self.lidas = len(self.sim.marcas)
        if ev is not None:
            self._publica(ev, p, u, c_ancora)
            self._fronteiras(u, p)  # a ancora no instante da marca: as fronteiras dela que ja tocaram, em ordem

    def _transicoes(self, u, p, marcas):
        """O que mudou desde o tick de antes, em ordem, cada coisa no instante dela: as fronteiras que o prato cruzou
        antes, a parada (a pausa, o buffering) e o bloco que a ancora publicada nao previa (a retomada, a troca, o
        salto). A ancora de uma marca do disco e do deck de agora sai da fila de agora, como a do tick; a do disco que
        ja saiu do deck, so do que a marca diz: o rotulo e a velocidade 1 ate a marca seguinte."""
        for m in marcas:
            if m["tipo"] == "para":
                if self.pub["status"] != "playing":  # ja parado (a parada que o tick viu antes da marca dela)
                    continue
                self._fronteiras(u, self.pub, ate=m["u"] - 1)
                if m["status"] == "idle":  # o stop: o prato vazio
                    self._publica("parada", dict(p, status="idle", faixa=None, ancora=None), u, 0)
                    continue
                base = self._base(p, m)
                if base is None:
                    continue
                self._publica("troca" if (self.pub["faixa"] or {}).get("id") != m["faixa"]
                              else EVENTO_DO_STATUS[m["status"]],
                              dict(base, status=m["status"], ancora={"faixa": m["faixa"], "pos": m["pos"],
                                                                     "t": ms(m["u"]), "taxa": SR, "anda": False,
                                                                     "segmentos": []}), u, deck=m["deck"])
                continue
            base = self._base(p, m)
            if base is None or not self._nova(m):
                continue
            self._fronteiras(u, self.pub, ate=m["u"] - 1)
            if m["faixa"] == (self.e.track or {}).get("id") and m["deck"] == id(self.e._deck):
                anc = self.ancora(m["u"], m["rotulo"], self.sim.c() - m["c"], anda=True)
            else:
                anc = {"faixa": m["faixa"], "pos": m["rotulo"], "t": ms(m["u"]), "taxa": SR, "anda": True,
                       "segmentos": self._so_da_marca(m)}
            ev = ("troca" if (self.pub["faixa"] or {}).get("id") != m["faixa"]
                  else "retomada" if self.pub["status"] != "playing" else "mapa")
            self._publica(ev, dict(base, status="playing", ancora=anc), u, m["c"], m["deck"])

    def _so_da_marca(self, m):
        """Os segmentos da marca de um disco que ja saiu do deck: a curva do deck dela, se ainda vale ali (a virada na
        rampa de saida), e depois a velocidade 1, aberta (a marca seguinte corta)."""
        segs = segmentos([], self.curvas.get(m["deck"], []), m["c"], False)
        if len(segs) < SEGMENTOS_MAX:  # cheia, so promete ate o comeco do ultimo, e a curva fica fechada
            segs.append({"n": None, "v": 1.0})
        return segs

    def _base(self, p, m):
        """A projecao da faixa da marca: a de agora ou a publicada (o disco que saiu entre dois ticks), com a faixa como
        ela estava na marca, pela mesma lista de campos (a que entrou e saiu entre os dois, a que trocou de fonte
        depois); a mudanca dos campos dela sai depois, como projecao."""
        base = next((x for x in (p, self.pub) if (x["faixa"] or {}).get("id") == m["faixa"]), None)
        if m.get("track") is None:
            return base
        return dict(base or p, faixa=projeta({"status": "playing", "track": m["track"], "vol": VOL})["faixa"])

    def _nova(self, m):
        """A marca que a ancora publicada nao previa: estrutural, ou o rotulo fora do que ela dizia ali. A de antes do
        instante dela ja esta contada nela."""
        velha = self.pub["ancora"]
        if velha is not None and m["u"] < self._u(velha):
            return False
        if velha is None or not velha["anda"] or velha["faixa"] != m["faixa"]:
            return True
        # a estrutural bem no instante da ancora ja esta nela (a foto do tick que viu o disco antes do bloco dele)
        if m["estrutural"] and m["u"] > self._u(velha):
            return True
        return abs(posicao(velha, ms(m["u"])) - m["rotulo"]) > MUDA_S

    def callback(self, u):
        """Depois de cada callback: a foto que esperava a virada sai agora, com o que mudou antes dela."""
        if self.pendente is not None and not self.vira_pendente():
            reconexao, self.pendente = self.pendente == "reconexao", None
            if reconexao:
                self.olha(u)
            self.olha(u, reconexao=reconexao)

    def pulso(self, u):
        self.msgs.append({"evento": "pulso", "msg": {"protocolo": 1, "tipo": "pulso", "sessao": SESSAO,
                                                     "rev": self.rev, "agora": ms(u)}})

    @staticmethod
    def _u(anc):
        return round((anc["t"] - T0_MS) * POR_MS)

    def cruzou(self, u):
        """O prato passou do fim do primeiro segmento da ancora publicada (e ainda ha outro: o fim do mapa so espera o
        fim do disco)."""
        a = self.pub["ancora"]
        if a is None or not a["anda"] or len(a["segmentos"]) < 2:
            return False
        n = a["segmentos"][0]["n"]
        return n is not None and u - self._u(a) >= n

    def diferenca(self, p, u):
        velho = self.pub
        if p["status"] == "idle" and velho["status"] != "idle":  # o stop bem no tick: o prato vazio, nao a troca
            return "parada"
        if (velho["faixa"] or {}).get("id") != (p["faixa"] or {}).get("id"):
            return "troca"
        if velho["status"] != p["status"]:
            return EVENTO_DO_STATUS[p["status"]]
        a = velho["ancora"]
        if a is not None:
            adiante = avanca(a, u - self._u(a))
            if not equivalentes(adiante, p["ancora"]):
                return "mapa"
        if {k: v for k, v in velho.items() if k != "ancora"} != {k: v for k, v in p.items() if k != "ancora"}:
            return "projecao"
        return "fronteira" if self.cruzou(u) else None


def ms(u):
    return T0_MS + u / POR_MS


# ----------------------------------------------------------------------------------- o motor sem som (o cenario)

def _deck(tid, de, ate, mudo=0.0, fim=True, rng=None):
    """Um Deck com o disco tid decodificado de de a ate (s), em blocos de 10 ms, e o nivel de cada um."""
    rng = rng or np.random.default_rng(7)
    d = eng.Deck({"id": tid, "title": f"Disco {tid}", "channel": None, "duration": float(ate) if fim else None,
                  "youtube_id": None, "thumb": None})
    for k in range(int(round((ate - de) * SR)) // BLOCO):
        t = de + k * BLOCO / SR
        a = (np.zeros((BLOCO, 2), np.float32) if t < mudo
             else (rng.standard_normal((BLOCO, 2)) * 0.1).astype(np.float32))
        d.q.append((t, a))
        d.niveis.append((t, BLOCO, float(np.sqrt(np.mean(a * a)))))
    if fim:
        d.eof_gen = d.gen
    return d


def _motor(atual, pronto=None, pos=0.0):
    """O Engine so com o que a passagem, a virada e o status usam."""
    e = object.__new__(eng.Engine)
    e._qlock = threading.Lock()
    e._deck, e._pronto, e.track, e.pronto_tag = atual, pronto, atual.track, "proxima" if pronto else None
    e.pos, e.paused, e.ended, e.loop = pos, False, False, False
    e._virar_em = e._eco_plano = e._visor_pas = e._visor_feita = None
    e._saindo = e._entrando = e._eco = None
    e._pronto_falhou = None
    e._bloco = e._pausa = None  # o bloco em curso e a pausa pendente (o _captura_atual e o _restart os leem)
    e._registra_fim = lambda *a, **k: None  # o registro do fim grava em logs/: fora daqui
    return e


class Sim:
    """O callback de saida sem som: as linhas do _mixa que viram o prato e consomem a fila (o _tira de verdade), de
    BLOCO em BLOCO. Conta as amostras de saida (u) e as consumidas de cada deck no prato (c), e anota as marcas: o
    pedaco que nao continua o anterior (estrutural: outro deck ou outro disco, ou o primeiro depois de um bloco sem
    disco; ou so o rotulo que salta) e a amostra em que o prato parou (a pausa, o buffering, o fim, o stop; no meio do
    bloco, quando a fila seca antes do fim dele). O mapa de amostras: (amostra
    de saida, faixa, rotulo) de cada pedaco consumido."""

    def __init__(self, e):
        self.e, self.u, self.mapa, self.marcas, self.ant, self.andando = e, 0, [], [], None, False
        self.consumido = {}

    def c(self):
        return self.consumido.get(id(self.e._deck), 0)

    def vira(self):
        e = self.e
        if e._pronto is not None and e.track is not None and not e.paused:
            fim_deste = not e._q and e._eof_gen == e._gen
            if (e._virar_em is not None and e.pos >= e._virar_em) or (fim_deste and e._pronto.q):
                e._vira()

    def consome(self):
        e, item, deck = self.e, None, self.e._deck
        if e.track is not None and not e.paused:
            with e._qlock:
                item = e._tira(e._q, BLOCO)
            if not item and e._eof_gen == e._gen:
                e.ended = True
        u = self.u
        if not item:
            if self.andando and self.ant is not None:  # o prato parou: a pausa, o buffering, o fim ou o stop
                # a faixa e o deck do prato agora: o load (ou a virada) que ainda nao encheu a fila e o disco novo
                novo = e.track is not None
                self.marcas.append({"u": u, "tipo": "para", "faixa": e.track["id"] if novo else self.ant[2],
                                    "deck": id(e._deck) if novo else id(self.ant[3]),
                                    "pos": float(e._q[0][0]) if e._q and not e.ended else float(e.pos),
                                    "status": e.status(), "track": dict(e.track) if novo else self.ant[4]})
            self.andando, self.ant = False, None
        for t0, s in item or ():
            tid = e.track["id"]
            # outro deck (a virada, mesmo com o mesmo disco) ou outro disco no mesmo deck (o load que enche a fila
            # antes do callback seguinte)
            estrutural = self.ant is None or self.ant[3] is not deck or self.ant[2] != tid
            if estrutural or not _continua(self.ant[0], self.ant[1], t0):
                self.marcas.append({"u": u, "tipo": "anda", "rotulo": float(t0), "faixa": tid, "deck": id(deck),
                                    "c": self.c(), "estrutural": estrutural, "track": dict(e.track)})
            self.mapa.append((u, tid, float(t0)))
            self.ant = (t0, len(s), tid, deck, dict(e.track))  # a faixa como estava: o servidor muda a dele
            u += len(s)
            self.consumido[id(deck)] = self.consumido.get(id(deck), 0) + len(s)
        if item:
            e.pos = item[-1][0] + len(item[-1][1]) / SR
            self.andando = True
            if u - self.u < BLOCO:  # a fila secou no meio do bloco: o prato parou ali, nao no bloco seguinte
                fim = e._eof_gen == e._gen
                self.marcas.append({"u": u, "tipo": "para", "faixa": e.track["id"], "deck": id(deck),
                                    "pos": float(e.pos), "status": "ended" if fim else e.status(), "track": dict(e.track)})
                self.andando, self.ant = False, None
        self.u += BLOCO


def _roda(e, sim, prod, ate_s, eventos=(), reconexoes=(), pulsos=False):
    """Roda o cenario ate ate_s de saida: em cada bloco, os eventos (fn(u) que devolvem True quando agiram), a virada
    do callback, o tick do produtor (de TICK_BLOCOS em TICK_BLOCOS), a reconexao quando o gatilho manda (o produtor
    publica antes o que mudou) e o callback consome."""
    eventos, reconexoes = list(eventos), list(reconexoes)
    while sim.u < ate_s * SR:
        for ev in list(eventos):
            if ev(sim.u):
                eventos.remove(ev)
        sim.vira()
        tick = (sim.u // BLOCO) % TICK_BLOCOS == 0
        if tick:
            prod.olha(sim.u)
        for r in list(reconexoes):
            if r(sim.u):
                reconexoes.remove(r)
                if not tick:
                    prod.olha(sim.u)
                prod.olha(sim.u, reconexao=True)
        if pulsos and sim.u % SR == 0 and sim.u:
            prod.pulso(sim.u)
        sim.consome()
        prod.callback(sim.u)
    return prod.msgs


def _fila_de(*decks):
    """A fila do servidor: a proxima fica nela ate entrar no prato."""
    def fila(e):
        return [{"qid": f"{i:08x}", "id": d.track["id"], "title": d.track["title"], "channel": None,
                 "duration": d.track["duration"], "youtube_id": None, "thumb": None}
                for i, d in enumerate(decks, 1) if d is not e._deck and e._pronto is d]
    return fila


def _cos(de, ate, total):
    return {"de": float(de), "ate": float(ate), "total": int(total), "fase": 0}


def _preenchimento(cabeca, pad, ini, esticado):
    """Os segmentos do pad pelos rotulos do cabeca do plano: o bloco unico do final seco sem esticar anda a 1 (o _tira
    rotula o resto partido com t0 + n / SR), e o bloco de 10 ms do esticado que o motor prendeu em zero fica em 0."""
    segs, u = [], 0
    for t, a in cabeca:
        if u >= pad:
            break
        n = min(len(a), pad - u)
        v = 0.0 if esticado and t == 0.0 and ini + (u - pad) / SR < 0 else 1.0
        ult = segs[-1] if segs else None
        if ult is not None and ult["v"] == v and abs(ult["pos"] + v * ult["n"] / SR - t) <= 1e-9:
            ult["n"] += n
        else:
            segs.append({"n": n, "v": v, "pos": float(t), "preenchimento": True})
        u += len(a)
    return segs


def curva_entrada(plano, inicio=0):
    """A curva da faixa que entra, do plano aplicado: o preenchimento, sb por n_sob e a volta a 1 em meio cosseno (sem
    esticar, so o preenchimento). Os numeros do visor do plano, sem o arredondamento do _visor_publico. Ocupa as
    amostras consumidas do deck desde a virada (inicio 0)."""
    vis, cabeca = plano["visor"], plano["cabeca"]
    ini, total = float(vis["ini"]), sum(len(a) for _, a in cabeca)
    n_sob, n_rampa = int(round(vis["sob"] * SR)), int(round(vis["rampa"] * SR))
    pad = total - n_sob - n_rampa
    segs = _preenchimento(cabeca, pad, ini, bool(n_sob or n_rampa))
    if n_sob or n_rampa:
        segs += [{"n": n_sob, "v": float(vis["vb"]), "pos": ini},
                 {"n": n_rampa, "v": _cos(1 + float(vis["k"]), 1, n_rampa)}]
    return {"inicio": inicio, "segmentos": segs}, pad, ini


def curva_saida(plano, inicio):
    """A rampa de saida do plano aplicado: n_ra amostras de 1 a sa e sa ate o fim dos blocos esticados, a partir da
    amostra consumida inicio (a do rotulo t_r). O ultimo bloco, o do fim do arquivo, anda a 1 desde o rotulo dele, como
    o pos do _mixa. O n_ra e o do transicao.rampa_saida, que o _plano_dois usa (o plano ainda nao o devolve)."""
    _, novos = plano["sai_q"]
    sa = float(plano["visor"]["va"])
    n_ra = transicao.rampa_saida(sa, 0.0)[0]
    n_za = sum(len(x) for _, x in novos)
    t_ult, ult = novos[-1]
    return {"inicio": inicio, "segmentos": [{"n": n_ra, "v": _cos(1, sa, n_ra)}, {"n": n_za - n_ra - len(ult), "v": sa},
                                            {"n": len(ult), "v": 1.0, "pos": float(t_ult)}]}


def _inicio_da_saida(sim, deck, plano):
    """A amostra consumida do deck em que a rampa de saida comeca: as consumidas ate agora mais as da fila antes de t_r."""
    t_r = plano["sai_q"][0]
    return sim.consumido.get(id(deck), 0) + sum(len(a) for t, a in deck.q if t < t_r - 1e-7)


_PLANO = {}


def _plano_dois():
    """A passagem com os andamentos longe: a que sai vai devagar a sa antes da sobreposicao e a proxima entra
    esticada em sb, com o pad da virada. O _plano_dois de verdade (com a Rubber Band), com a fase das batidas fixa."""
    if "dois" not in _PLANO:
        a, b = _deck("A", 0.0, 40.0), _deck("B", 0.0, 45.0)
        e = _motor(a, b, pos=1.0)
        ga = types.SimpleNamespace(periodo=0.5, fase=0.2, bpm=120.0, firme=True)
        gb = types.SimpleNamespace(periodo=0.51, fase=0.1, bpm=117.6, firme=True)
        plano, motivo = e._plano_dois(list(a.q), list(b.q), ga, gb, 1.02, 1.012, 0.2, 0.1, 30.0, 6.0, 33.0, 0.0,
                                      lambda *x, **k: (0.137, None))
        assert plano is not None, motivo
        _PLANO["dois"] = plano
    return _PLANO["dois"]


def _aplica(e, a, b, em_s, plano_pronto=None, patches=(), depois=None):
    """O evento que aplica a passagem pelo _mede de verdade em em_s: com plano_pronto, o _plano_batida devolve esse;
    sem ele, o _plano_batida de verdade (com os patches). depois(plano) recebe o plano aplicado."""
    def ev(u):
        if u < em_s * SR:
            return False
        feito = {}
        real = e._plano_batida

        def plano_batida(*x, **k):
            r = (plano_pronto, None) if plano_pronto is not None else real(*x, **k)
            feito["plano"] = r[0]
            return r
        e._plano_batida = plano_batida
        with contextlib.ExitStack() as pilha:
            for p in patches:
                pilha.enter_context(p)
            pilha.enter_context(contextlib.redirect_stderr(io.StringIO()))
            e._mede(a, b, a.track)
        assert e._virar_em is not None and feito.get("plano") is not None, "o _mede nao aplicou o plano"
        if depois is not None:
            depois(feito["plano"])
        return True
    return ev


def _na_curva(sim, e, deck, curvas, fracao):
    """O gatilho de reconexao: o prato e o deck e ja consumiu a fracao do meio cosseno da curva dele."""
    def ev(u):
        lista = curvas.get(id(deck), [])
        if e._deck is not deck or not lista:
            return False
        segs = segmentos(e._q, lista, sim.c(), deck.eof_gen == deck.gen)
        return bool(segs) and isinstance(segs[0]["v"], dict) and segs[0]["v"]["fase"] >= fracao * segs[0]["v"]["total"]
    return ev


def cenario_passagem_dois(mesmo=False):
    a, b = _deck("A", 0.0, 40.0), _deck("A" if mesmo else "B", 0.0, 45.0)
    e = _motor(a, b)
    sim = Sim(e)
    curvas, info = {}, {}

    def depois(plano):
        registra_curva(curvas, a, curva_saida(plano, _inicio_da_saida(sim, a, plano)))
        entrada, info["pad"], info["ini"] = curva_entrada(plano)
        registra_curva(curvas, b, entrada)

    rampa_b = _na_curva(sim, e, b, curvas, 0.3)
    info["mesmo_disco"] = mesmo

    def troca_fonte(u):  # o download chega no meio da rampa de entrada: o trocar_fonte sobe o gen e deixa a fila
        if not rampa_b(u):
            return False
        with e._qlock:
            e._gen += 1
            e._eof_gen = -1
        return True
    prod = Produtor(e, sim, curvas, _fila_de(b))
    msgs = _roda(e, sim, prod, 74.0, eventos=[_aplica(e, a, b, 1.0, plano_pronto=_plano_dois(), depois=depois),
                                              troca_fonte],
                 reconexoes=[_na_curva(sim, e, a, curvas, 0.5), _na_curva(sim, e, b, curvas, 0.5)])
    return {"descricao": "A passagem com a rampa de saida (a que sai vai a sa antes da sobreposicao) e a entrada "
                         "esticada (sb, a volta a 1 em meio cosseno), com pad > 0 na virada e a origem dele presa em "
                         "zero; reconexao no meio das duas rampas, a de entrada depois de o download trocar a fonte "
                         "(o gen sobe e a fila fica).", **info}, msgs, sim.mapa


def _cancelada(repetir):
    a, b = _deck("A", 0.0, 40.0), _deck("B", 0.0, 45.0)
    e = _motor(a, b)
    sim = Sim(e)
    curvas, fila = {}, {"ok": True}
    plano = _plano_dois()

    def lista(e_):
        return _fila_de(b)(e_) if fila["ok"] else []

    def depois(p):
        registra_curva(curvas, a, curva_saida(p, _inicio_da_saida(sim, a, p)))

    rampa = _na_curva(sim, e, a, curvas, 1 / 3)

    def cancela(u):
        if not rampa(u):
            return False
        with e._qlock:  # a fila mudou: o servidor cancela a proxima, e os blocos esticados ficam na fila do prato
            e._cancela_passagem()
            if repetir is True:  # e o Repetir ligado: o leitor emenda a volta na mesma fila, depois dos blocos esticados
                e.loop = True
                a.q.extend(_deck("A", 0.0, 3.0).q)
                a.eof_gen = -1
        fila["ok"] = False
        return True

    def no_fim_esticado(u):  # reconexao no trecho em sa, antes de acabarem os blocos esticados
        lista = curvas.get(id(a), [])
        segs = segmentos(e._q, lista, sim.c(), a.eof_gen == a.gen) if lista and e._q else []
        return bool(segs) and not isinstance(segs[0]["v"], dict) and segs[0]["v"] > 1 and segs[0]["n"] < 2 * SR

    def na_volta(u):  # reconexao logo depois da volta (depois do cancelamento: o rotulo voltou ao comeco)
        return not fila["ok"] and bool(e._q) and e._q[0][0] < 0.5 and sim.mapa[-1][2] < 0.5

    def emenda_tarde(u):  # o Repetir ligado tarde: a volta entra na fila com 2 blocos esticados por tocar, fora do tick
        if fila["ok"] or len(e._q) > 2 or (u // BLOCO) % TICK_BLOCOS == 0:
            return False
        with e._qlock:
            e.loop = True
            a.q.extend(_deck("A", 0.0, 3.0).q)
            a.eof_gen = -1
        return True

    prod = Produtor(e, sim, curvas, lista)
    msgs = _roda(e, sim, prod, 43.0 if repetir else 42.0,
                 eventos=[_aplica(e, a, b, 1.0, plano_pronto=plano, depois=depois), cancela]
                 + ([emenda_tarde] if repetir == "tarde" else []),
                 reconexoes=[_na_curva(sim, e, a, curvas, 0.6), no_fim_esticado] + ([na_volta] if repetir else []))
    return msgs, sim.mapa


def cenario_passagem_cancelada():
    msgs, mapa = _cancelada(False)
    return {"descricao": "A passagem cancelada durante a rampa de saida, com a faixa no mesmo deck: os blocos "
                         "esticados ficam na fila e a ancora segue valendo; reconexao no meio da rampa e antes do fim "
                         "dos blocos esticados, e o fim natural congela a posicao onde a ancora parou."}, msgs, mapa


def cenario_cancelada_repetir():
    msgs, mapa = _cancelada(True)
    return {"descricao": "A mesma passagem cancelada, com o Repetir ligado: acabados os blocos esticados, a volta na "
                         "mesma fila segue a 1 (a curva nao vale mais), com reconexao logo depois da volta."}, msgs, mapa


def cenario_volta_tarde():
    msgs, mapa = _cancelada("tarde")
    return {"descricao": "A mesma passagem cancelada, com o Repetir ligado tarde: o leitor so poe a volta na fila quando "
                         "os blocos esticados estao acabando, e ela toca antes do tick seguinte; a ancora sai no "
                         "instante dela."}, msgs, mapa


def cenario_seek_na_rampa():
    a, b = _deck("A", 0.0, 40.0), _deck("B", 0.0, 45.0)
    e = _motor(a, b)
    sim = Sim(e)
    curvas = {}
    plano = _plano_dois()
    rampa = _na_curva(sim, e, a, curvas, 0.4)

    def seek(u):  # o _restart de verdade (o disco sem path: sem o leitor), e a fila que o leitor refaria de 30 s
        if not rampa(u):
            return False
        e._restart(30.0)
        curvas.pop(id(a), None)  # a fila foi limpa: as curvas dela saem junto
        with e._qlock:
            a.q.extend(_deck("A", 30.0, 40.0).q)
            a.eof_gen = a.gen
        return True

    prod = Produtor(e, sim, curvas, lambda e_: [])
    msgs = _roda(e, sim, prod, 21.0, eventos=[_aplica(e, a, b, 1.0, plano_pronto=plano, depois=lambda p: registra_curva(
        curvas, a, curva_saida(p, _inicio_da_saida(sim, a, p)))), seek])
    return {"descricao": "O seek no meio da rampa de saida: o _restart limpa a fila, os blocos esticados saem e a curva "
                         "sai junto; vale a cauda."}, msgs, sim.mapa


def cenario_troca_no_load():
    a = _deck("A", 10.0, 20.0)
    e = _motor(a, pos=10.0)
    sim = Sim(e)

    def toca_outro(u):  # o tocar de outro disco fora do tick: o load no mesmo deck, com a fila cheia antes do
        # callback seguinte (o stream aberto antes), sem bloco vazio no meio
        if u < 1.03 * SR:
            return False
        b = _deck("B", 0.0, 3.0)
        e.track = a.track = b.track
        e._restart(0.0)
        with e._qlock:
            a.q.extend(b.q)
            a.eof_gen = a.gen
        return True

    prod = Produtor(e, sim, {}, lambda e_: [])
    msgs = _roda(e, sim, prod, 2.0, eventos=[toca_outro])
    return {"descricao": "Outro disco pelo load, no mesmo deck, com a fila cheia antes do callback seguinte: a troca "
                         "sai no instante do primeiro bloco dele, com o rotulo dele."}, msgs, sim.mapa


def cenario_mesmo_disco():
    info, msgs, mapa = cenario_passagem_dois(mesmo=True)
    info["descricao"] = ("A mesma passagem com o mesmo disco nos dois decks (a fila pos de novo o que tocava): a virada e "
                         "uma descontinuidade do deck, e a ancora sai no instante dela mesmo com a faixa igual.")
    return info, msgs, mapa


def _patches_seco(golpe, esticar):
    """O _plano_batida de verdade no final seco com o corte no golpe: a proxima sem batida firme (sem esticar) ou com
    ela, a 2% (esticada no andamento deste). So a medida das batidas fica fixa."""
    g = [types.SimpleNamespace(periodo=0.5, fase=0.1, bpm=120.0, firme=True, motivo=""),
         types.SimpleNamespace(periodo=0.51, fase=0.1, bpm=117.6, firme=esticar, motivo="fixo no teste")]
    return [mock.patch.object(eng.batida, "medir", side_effect=g), mock.patch.object(eng, "grade_rede", return_value=None),
            mock.patch.object(eng.batida, "fase", return_value=(0.0, 10.0)),
            mock.patch.object(eng, "_golpe_final", return_value=golpe),
            mock.patch.object(eng, "_batida_tocada", return_value=0.5),
            mock.patch.object(eng, "_eco_corte", return_value=None)]


def _cenario_seco(mudo, esticar=False):
    a, b = _deck("A", 18.0, 32.0), _deck("B", 0.0, 30.0, mudo=mudo)
    e = _motor(a, b, pos=18.0)
    sim = Sim(e)
    curvas, info = {}, {}

    def depois(plano):
        entrada, info["pad"], info["ini"] = curva_entrada(plano)
        registra_curva(curvas, b, entrada)
        info["origem"] = float(plano["cabeca"][0][0])

    def no_preenchimento(u):  # reconexao entre a virada e o inicio efetivo da faixa de entrada
        return e._deck is b and BLOCO < sim.c() < info["pad"]

    prod = Produtor(e, sim, curvas, _fila_de(b))
    msgs = _roda(e, sim, prod, 16.0, eventos=[_aplica(e, a, b, 0.5, patches=_patches_seco(31.6037, esticar),
                                                      depois=depois)],
                 reconexoes=[no_preenchimento])
    return info, msgs, sim.mapa


def cenario_final_seco():
    info, msgs, mapa = _cenario_seco(0.0)
    info["descricao"] = ("O final seco no tempo sem estiramento, com o corte no golpe: a proxima entra depois de um pad "
                         "maior que um bloco, num bloco so, com a origem dele (ini - pad) presa em zero; reconexao entre "
                         "a virada e o inicio efetivo.")
    return info, msgs, mapa


def cenario_final_seco_sem_limite():
    info, msgs, mapa = _cenario_seco(1.0)
    info["descricao"] = ("O mesmo final seco, com a proxima comecando em 1 s (o silencio do comeco dela): a origem do "
                         "pad fica acima de zero.")
    return info, msgs, mapa


def cenario_final_seco_esticado():
    info, msgs, mapa = _cenario_seco(0.0, esticar=True)
    info["descricao"] = ("O final seco no tempo com o corte no golpe e a proxima esticada no andamento deste: o pad "
                         "maior que um bloco vem em blocos de 10 ms, cada um com o rotulo preso em zero; reconexao "
                         "dentro do preenchimento.")
    return info, msgs, mapa


def cenario_buffering():
    a = _deck("A", 10.0, 11.0, fim=False)
    a.q.append((11.0, np.zeros((BLOCO // 2, 2), np.float32)))  # o stream seca no meio de um bloco
    e = _motor(a, pos=10.0)
    sim = Sim(e)

    def chega(de, ate, s):  # o stream entrega de ate ate
        def ev(u):
            if u < s * SR:
                return False
            with e._qlock:
                a.q.extend(_deck("A", de, ate, fim=False).q)
            return True
        return ev

    def pausa_em(s, on):
        def ev(u):
            if u < s * SR:
                return False
            e.paused = on
            return True
        return ev

    prod = Produtor(e, sim, {}, lambda e_: [])
    msgs = _roda(e, sim, prod, 5.0, eventos=[chega(11.005, 11.025, 1.41), chega(11.025, 16.025, 2.0),
                                             pausa_em(3.0, True), pausa_em(3.37, False), pausa_em(3.39, True),
                                             pausa_em(3.5, False),
                                             pausa_em(4.21, True), pausa_em(4.24, False),
                                             pausa_em(4.63, True), pausa_em(4.64, False),
                                             pausa_em(4.66, True), pausa_em(4.67, False),
                                             pausa_em(4.71, True), pausa_em(4.72, False), pausa_em(4.76, True),
                                             pausa_em(4.8, False)])
    return {"descricao": "O stream que para no meio de um bloco (buffering congela a posicao ali), solta 20 ms e trava "
                         "de novo com o buffering publicado, a retomada depois do buffering, a pausa e a "
                         "retomada (e a retomada e a pausa logo depois de uma pausa publicada), cada transicao no instante "
                         "em que o prato parou ou voltou a andar, uma pausa de "
                         "30 ms entre dois ticks, publicada com as duas transicoes, e duas pausas de 10 ms entre os "
                         "mesmos dois ticks, com as quatro, e a pausa curta seguida de outra bem no bloco do tick seguinte (o de "
                         "4,76 s), que sai no instante dele."}, msgs, sim.mapa


def cenario_paradas_e_load():
    a = _deck("A", 0.0, 3.0)
    e = _motor(a)
    sim = Sim(e)

    def load_b(u):  # o load de B no mesmo deck, com a fila cheia antes do callback seguinte
        if u < 32 * BLOCO:
            return False
        b = _deck("B", 0.0, 3.0)
        e.track = a.track = b.track
        e._restart(0.0)
        with e._qlock:
            a.q.extend(b.q)
            a.eof_gen = a.gen
        return True

    c = _deck("C", 0.0, 3.0)

    def load_c(u):  # o load de C com o leitor ainda sem bloco: o callback seguinte acha a fila vazia
        if u < 40 * BLOCO:
            return False
        e.track = a.track = c.track
        e._restart(0.0)
        return True

    def chega_c(u):  # 30 ms depois, o leitor de C enche a fila
        if u < 43 * BLOCO:
            return False
        with e._qlock:
            a.q.extend(c.q)
            a.eof_gen = a.gen
        return True

    prod = Produtor(e, sim, {}, lambda e_: [])
    msgs = _roda(e, sim, prod, 0.6, eventos=_pausa_nos_blocos(e, 5, 8) + _pausa_nos_blocos(e, 9, 16)
                 + _pausa_nos_blocos(e, 29, 30) + [load_b] + _pausa_nos_blocos(e, 35, 37) + [load_c, chega_c])
    return {"descricao": "Paradas entre dois ticks com o prato ja parado na foto de antes (a retomada de um bloco so e a "
                         "pausa de novo), e a pausa curta, a retomada e o load de outro disco no mesmo deck antes do "
                         "tick que ve a pausa seguinte, e o load de outro disco com o leitor ainda sem bloco (o disco novo em "
                         "buffering desde o instante em que o prato calou): cada transicao no instante dela, com a faixa "
                         "dela."}, \
        msgs, sim.mapa


def _curto(tid):
    """Um disco de 105 ms, com o fim do arquivo no meio de um bloco."""
    d = _deck(tid, 0.0, 0.1)
    d.q.append((0.1, np.zeros((BLOCO // 2, 2), np.float32)))
    d.track["duration"] = 0.105
    return d


def cenario_fim_e_trocas():
    a = _curto("A")
    e = _motor(a)
    sim = Sim(e)

    def load(tid, bloco, curto=False):  # o load de outro disco no mesmo deck, com a fila cheia antes do callback
        def ev(u):
            if u < bloco * BLOCO:
                return False
            d = _curto(tid) if curto is True else curto() if curto else _deck(tid, 0.0, 3.0)
            e.track = a.track = d.track
            e._restart(0.0)
            with e._qlock:
                a.q.extend(d.q)
                a.eof_gen = a.gen
            return True
        return ev

    def voltas():  # D: um som de 20 ms com o Repetir, uma volta a cada 2 blocos
        d = _deck("D", 0.0, 0.02)
        um = list(d.q)
        for _ in range(9):
            d.q.extend(um)
        return d

    prod = Produtor(e, sim, {}, lambda e_: [])
    msgs = _roda(e, sim, prod, 0.5, eventos=[load("B", 15), load("C", 19, curto=True), load("D", 30, curto=voltas)]
                 + _pausa_nos_blocos(e, 35, 37), reconexoes=[lambda u: u == 11 * BLOCO])
    return {"descricao": "O fim natural no meio de um bloco, a reconexao antes de o motor dizer ended (a fila vazia com "
                         "o fim lido ja e o fim), outro disco que entra e sai entre dois ticks (a troca para B com a "
                         "projecao dele e a troca para C), e o fim de C, o comeco de D e as voltas de D entre os mesmos "
                         "dois ticks, antes do tick que ve a pausa, cada um no instante dele."}, msgs, sim.mapa


def cenario_repetir():
    a = _deck("A", 7.0, 9.99)
    a.q.append((9.99, np.zeros((BLOCO // 2, 2), np.float32)))  # o ultimo bloco do arquivo, curto
    a.q.extend(_deck("A", 0.0, 3.0).q)  # o leitor com o Repetir: depois do fim, a volta do comeco no mesmo deck
    a.track["duration"] = 9.995
    a.eof_gen = -1  # com o Repetir, o leitor nao chega ao fim
    e = _motor(a, pos=7.0)
    e.loop = True
    sim = Sim(e)
    prod = Produtor(e, sim, {}, lambda e_: [])
    msgs = _roda(e, sim, prod, 5.0)
    return {"descricao": "A volta do Repetir, no meio de um callback (o ultimo bloco do arquivo e curto): a volta entra "
                         "na ancora quando chega a fila, e a ancora nova sai no instante do primeiro bloco dela, com a "
                         "faixa e o deck iguais."}, msgs, sim.mapa


def cenario_repetir_curto():
    a = _deck("A", 0.0, 0.1)
    um = list(a.q)
    for _ in range(14):  # um som de 100 ms no Repetir: a fila tem uma volta a cada 100 ms
        a.q.extend(um)
    a.track["duration"] = 0.1
    a.eof_gen = -1
    e = _motor(a)
    e.loop = True
    sim = Sim(e)
    prod = Produtor(e, sim, {}, lambda e_: [])
    msgs = _roda(e, sim, prod, 1.2)
    return {"descricao": "Um som de 100 ms no Repetir: a janela de 1 s tem mais voltas do que cabem nos 8 segmentos; o "
                         "ultimo fica aberto e a ancora nova sai a cada volta."}, msgs, sim.mapa


def _repetir(dur_s, voltas, ate_s, eventos_de=None):
    a = _deck("A", 0.0, dur_s)
    um = list(a.q)
    for _ in range(voltas - 1):
        a.q.extend(um)
    a.track["duration"] = dur_s
    a.eof_gen = -1
    e = _motor(a)
    e.loop = True
    sim = Sim(e)
    prod = Produtor(e, sim, {}, lambda e_: [])
    return _roda(e, sim, prod, ate_s, eventos=eventos_de(e) if eventos_de else ()), sim.mapa


def _pausa_nos_blocos(e, de, ate):
    """A pausa do bloco de ate o bloco ate."""
    def para(u):
        if u < de * BLOCO:
            return False
        e.paused = True
        return True

    def volta(u):
        if u < ate * BLOCO:
            return False
        e.paused = False
        return True
    return [para, volta]


def cenario_retomada_na_volta():
    msgs, mapa = _repetir(0.1, 23, 2.3, lambda e: _pausa_nos_blocos(e, 28, 30) + _pausa_nos_blocos(e, 98, 103)
                          + _pausa_nos_blocos(e, 157, 160) + _pausa_nos_blocos(e, 210, 212))
    return {"descricao": "Um som de 100 ms no Repetir pausado perto do fim de uma volta: na primeira pausa, a volta toca "
                         "antes do tick que ve a retomada; na segunda, a volta e o proximo bloco no tick; na terceira, a "
                         "pausa cai bem no comeco da volta, que so toca depois da retomada; na quarta, tambem, e no bloco "
                         "do tick (o 210), que ve a pausa antes da marca dela. A ancora da retomada leva a volta."}, msgs, mapa


def cenario_volta_e_virada():
    a = _deck("A", 0.0, 0.1)
    um = list(a.q)
    for _ in range(4):
        a.q.extend(um)
    a.track["duration"], a.eof_gen = 0.1, -1
    b = _deck("B", 0.0, 3.0)
    e = _motor(a, b)
    e.loop = True
    e._sobrepor = e._segura = e._entrar = e._cheia = 0
    e._grave, e._nivel_entra = None, 1.0
    sim = Sim(e)

    def vira_logo(u):  # a virada marcada para 20 ms depois da volta de 100 ms: as duas entre os ticks de 70 e 140 ms
        if u < 105 * POR_MS:
            return False
        e._virar_em = 0.015
        return True

    prod = Produtor(e, sim, {}, _fila_de(b))
    msgs = _roda(e, sim, prod, 0.5, eventos=[vira_logo])
    return {"descricao": "A volta do Repetir e a virada para outro disco no mesmo intervalo entre dois ticks: a ancora da "
                         "volta sai com o disco que saiu, e a da virada com o que entrou, cada uma no instante dela."}, \
        msgs, sim.mapa


def cenario_repetir_curtissimo():
    msgs, mapa = _repetir(0.01, 40, 0.3)
    return {"descricao": "Um som de 10 ms no Repetir: varias voltas entre dois ticks, cada uma com a ancora dela, em "
                         "ordem, no instante do primeiro bloco."}, msgs, mapa


def cenario_fim_natural():
    a = _deck("A", 8.0, 10.0)
    e = _motor(a, pos=8.0)
    sim = Sim(e)
    prod = Produtor(e, sim, {}, lambda e_: [])
    msgs = _roda(e, sim, prod, 5.0, pulsos=True)
    return {"descricao": "O fim natural: com o fim do disco na janela, a ancora para na posicao final; depois ela "
                         "congela ali, os ticks seguem e o rev fica, com o pulso repetindo o rev de 1 em 1 s."}, \
        msgs, sim.mapa


CENARIOS = {"passagem-dois": cenario_passagem_dois, "passagem-cancelada": cenario_passagem_cancelada,
            "cancelada-repetir": cenario_cancelada_repetir, "volta-tarde": cenario_volta_tarde,
            "seek-na-rampa": cenario_seek_na_rampa, "mesmo-disco": cenario_mesmo_disco,
            "troca-no-load": cenario_troca_no_load,
            "volta-e-virada": cenario_volta_e_virada,
            "final-seco": cenario_final_seco, "final-seco-sem-limite": cenario_final_seco_sem_limite,
            "final-seco-esticado": cenario_final_seco_esticado, "buffering": cenario_buffering,
            "repetir": cenario_repetir, "repetir-curto": cenario_repetir_curto,
            "retomada-na-volta": cenario_retomada_na_volta, "repetir-curtissimo": cenario_repetir_curtissimo,
            "fim-natural": cenario_fim_natural, "paradas-e-load": cenario_paradas_e_load,
            "fim-e-trocas": cenario_fim_e_trocas}


def _limpa(x):
    """Os numeros do numpy em float do JSON."""
    if isinstance(x, dict):
        return {k: _limpa(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_limpa(v) for v in x]
    if isinstance(x, np.floating):
        return float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


# ---------------------------------------------------------------------------- as fixtures feitas a mao (os dados)

def _anc(pos, t, anda=True, segs=None, faixa="w6kKVs-h9Ns"):
    return {"faixa": faixa, "pos": pos, "t": t, "taxa": SR, "anda": anda,
            "segmentos": [{"n": None, "v": 1.0}] if segs is None and anda else (segs or [])}


FAIXA = {"id": "w6kKVs-h9Ns", "title": "Um disco", "channel": "Um canal", "duration": 236.0, "youtube_id": "w6kKVs-h9Ns",
         "thumb": "https://i.ytimg.com/vi/w6kKVs-h9Ns/mqdefault.jpg", "stream": False}


def _proj(status="playing", anc=None, **kw):
    p = {"status": status, "faixa": None if status == "idle" else FAIXA, "fila": [], "vol": VOL, "abaixa": None,
         "capacidades": capacidades(), "ancora": anc}
    p.update(kw)
    return p


def _estado(rev, agora, proj, origem="mudanca", sessao=SESSAO):
    return {"protocolo": 1, "tipo": "estado", "sessao": sessao, "rev": rev, "origem": origem, "agora": agora,
            "estado": proj}


def _pulso(rev, agora, sessao=SESSAO):
    return {"protocolo": 1, "tipo": "pulso", "sessao": sessao, "rev": rev, "agora": agora}


def _cmd(i, comando, args, sessao=SESSAO):
    return {"protocolo": 1, "tipo": "comando", "sessao": sessao, "id": i, "comando": comando, "args": args}


def fixture_relogio():
    """A foto atrasada: guardada no relay e entregue depois (o retido_ms), e atrasada na rede (o erro do relogio e o
    atraso, ate um pulso mais rapido)."""
    desvio = 5000.0  # o relogio de quem recebe = o do PC + 5 s
    anc = _anc(10.0, T0_MS)
    passos = []
    for msg, retido, transito, nota in (
            (_estado(3, T0_MS, _proj(anc=anc)), 4000.0, 400.0, "a foto guardada no relay, entregue 4 s depois a quem "
                                                                "conectou, e atrasada 400 ms na rede"),
            (_pulso(3, T0_MS + 4500.0), 0.0, 25.0, "o pulso, mais rapido: o erro cai de 400 para 25 ms"),
            (_estado(4, T0_MS + 6000.0, _proj(anc=_anc(16.0, T0_MS + 6000.0))), 0.0, 400.0, "a foto atrasada na rede: o "
                                                                                           "relogio nao piora"),
            (_pulso(4, T0_MS + 7000.0), 0.0, 20.0, "o pulso seguinte corrige")):
        if retido:
            msg = dict(msg, retido_ms=retido)
        chegada = msg["agora"] + desvio + retido + transito
        passos.append({"chega_ms": chegada, "transito_ms": transito, "nota": nota, "msg": msg})
    outra = dict(FAIXA, id="dQw4w9WgXcQ", youtube_id="dQw4w9WgXcQ")
    adiantada = [_estado(7, T0_MS, _proj(anc=_anc(30.0, T0_MS))),
                 _estado(8, T0_MS + 970.0, _proj(faixa=outra, anc=_anc(0.0, T0_MS + 1000.0, faixa=outra["id"])))]
    leituras = [{"pc_ms": T0_MS + 990.0, "faixa": FAIXA["id"], "pos": 30.99},
                {"pc_ms": T0_MS + 1000.0, "faixa": outra["id"], "pos": 0.0},
                {"pc_ms": T0_MS + 1500.0, "faixa": outra["id"], "pos": 0.5}]
    return {"descricao": "O relogio do PC visto por quem recebe: o desvio e o menor (chegada - agora - retido_ms). E a "
                         "foto adiantada (a virada com o t 30 ms depois do agora): a ancora de antes vale ate o t dela.",
            "desvio_real_ms": desvio, "entregas": passos, "adiantada": adiantada, "leituras": leituras}


def fixture_relay():
    s2 = "sessao-de-teste-02"
    p = _proj(anc=_anc(1.0, T0_MS))
    passos = [
        {"relay": "aceita", "sessao": SESSAO},
        {"cliente": "conecta", "agora_relay": 0.0, "espera": None},
        {"de": "pc", "agora_relay": 10.0, "msg": _estado(1, T0_MS, p, "inicio"), "espera": "guarda"},
        {"de": "pc", "agora_relay": 20.0, "msg": _estado(3, T0_MS + 10, p), "espera": "guarda"},
        {"de": "pc", "agora_relay": 25.0, "msg": _estado(2, T0_MS + 5, p), "espera": "descarta",
         "nota": "rev antigo da sessao atual, chegando depois do 3"},
        {"de": "pc", "agora_relay": 30.0, "msg": _pulso(3, T0_MS + 20), "espera": "repassa"},
        {"cliente": "conecta", "agora_relay": 530.0, "espera": {"rev": 3, "retido_ms": 510.0}},
        {"de": "pc", "agora_relay": 600.0, "msg": _estado(4, T0_MS + 590, p, "reconexao"), "espera": "guarda"},
        {"de": "pc", "agora_relay": 610.0, "msg": _estado(4, T0_MS + 590, p, "reconexao"), "espera": "descarta",
         "nota": "a mesma foto de novo"},
        {"relay": "aceita", "sessao": s2},
        {"cliente": "conecta", "agora_relay": 700.0, "espera": None, "nota": "a foto da sessao anterior nao vai"},
        {"de": "pc", "agora_relay": 710.0, "msg": _estado(5, T0_MS + 700, p), "espera": "descarta",
         "nota": "da sessao anterior, atrasada"},
        {"de": "pc", "agora_relay": 720.0, "msg": _estado(1, T0_MS + 710, p, "inicio", sessao=s2), "espera": "guarda"},
        {"de": "pc", "agora_relay": 725.0, "msg": _pulso(5, T0_MS + 715), "espera": "descarta"},
        {"cliente": "conecta", "agora_relay": 730.0, "espera": {"rev": 1, "retido_ms": 10.0, "sessao": s2}},
    ]
    return {"descricao": "O relay guarda a ultima foto da sessao ativa: troca a da sessao anterior, descarta o rev antigo "
                         "e a sessao que acabou, e entrega a guardada a quem conecta, com o retido_ms.", "passos": passos}


def fixture_comandos():
    validos = [
        (_cmd("c1", "tocar", {"id": "w6kKVs-h9Ns"}), ("POST", "/api/play", {"id": "w6kKVs-h9Ns"})),
        (_cmd("c2", "tocar", {"qid": "4f1c2a9b"}), ("POST", "/api/queue/play", {"qid": "4f1c2a9b"})),
        (_cmd("c3", "enfileirar", {"id": "w6kKVs-h9Ns", "next": True}),
         ("POST", "/api/queue", {"id": "w6kKVs-h9Ns", "next": True})),
        (_cmd("c4", "enfileirar", {"youtube_id": "dQw4w9WgXcQ", "title": "Outro", "channel": None, "duration": 213}),
         ("POST", "/api/queue", {"youtube_id": "dQw4w9WgXcQ", "title": "Outro", "channel": None, "duration": 213})),
        (_cmd("c5", "pular", {}), ("POST", "/api/next", {})),
        (_cmd("c6", "pausar", {}), ("POST", "/api/pause", {})),
        (_cmd("c7", "retomar", {}), ("POST", "/api/resume", {})),
        (_cmd("c8", "tirar_da_fila", {"qid": "4f1c2a9b"}), ("DELETE", "/api/queue/4f1c2a9b", {})),
        (_cmd("c9", "mover_na_fila", {"qid": "4f1c2a9b", "to": 0}), ("POST", "/api/queue/move", {"qid": "4f1c2a9b", "to": 0})),
        (_cmd("c10", "volume", {"vol": 0.35}), ("POST", "/api/volume", {"vol": 0.35})),
        (_cmd("c11", "abaixar", {"db": 12, "ms": 3000}), ("POST", "/api/abaixa", {"db": 12, "ms": 3000})),
        (_cmd("c12", "abaixar", {"db": 0, "ms": 0}), ("POST", "/api/abaixa", {"db": 0, "ms": 0})),
        (_cmd("c13", "sinal", {}), ("POST", "/api/sinal", {})),
    ]
    invalidos = [
        (_cmd("x1", "parar", {}), "fora do vocabulario"),
        (_cmd("x2", "tocar", {"id": "a", "start": 30}), "argumento a mais (o remoto nao escolhe de onde toca)"),
        (_cmd("x3", "tocar", {"id": "a", "qid": "4f1c2a9b"}), "o disco e a entrada juntos"),
        (_cmd("x4", "tocar", {}), "sem o que tocar"),
        (_cmd("x5", "enfileirar", {"url": "https://example.com/a.mp3"}), "link de fora do YouTube"),
        (_cmd("x6", "enfileirar", {"youtube_id": "curto"}), "id de video invalido"),
        (_cmd("x7", "enfileirar", {"youtube_id": "dQw4w9WgXcQ", "duration": 90000}), "duracao de mais de um dia"),
        (_cmd("x8", "enfileirar", {"youtube_id": "dQw4w9WgXcQ", "thumb": "https://example.com/x.jpg"}),
         "capa de outro endereco"),
        (_cmd("x9", "enfileirar", {"youtube_id": "dQw4w9WgXcQ", "title": 5}), "titulo que nao e texto"),
        (_cmd("x10", "pular", {"qid": "4f1c2a9b"}), "argumento num comando sem argumentos"),
        (_cmd("x11", "volume", {"vol": 1.5}), "volume fora de 0 a 1"),
        (_cmd("x12", "volume", {"vol": True}), "volume que nao e numero"),
        (_cmd("x13", "abaixar", {"db": 41, "ms": 1000}), "abaixar mais que 40 dB"),
        (_cmd("x14", "abaixar", {"db": 6, "ms": 1.5}), "prazo que nao e inteiro"),
        (_cmd("x15", "mover_na_fila", {"qid": "4F1C2A9B", "to": 0}), "qid fora do formato"),
        (_cmd("x16", "mover_na_fila", {"qid": "4f1c2a9b", "to": -1}), "lugar negativo"),
        (dict(_cmd("x17", "pular", {}), protocolo=2), "outra versao do protocolo"),
        (dict(_cmd("x18", "pular", {}), sessao="curta"), "id de sessao fora do formato"),
        (dict(_cmd("x19", "pular", {}), token="abc"), "campo a mais (o token nunca entra no protocolo)"),
        (_cmd("id com espaco", "pular", {}), "id do comando fora do formato"),
        (_cmd("x19\n", "pular", {}), "id do comando com a quebra de linha no fim"),
        (dict(_cmd("x20", "pular", {}), sessao="s3ss40-d0-pc\n"), "id de sessao com a quebra de linha no fim"),
        (_cmd("x21", "tirar_da_fila", {"qid": "4f1c2a9b\n"}), "entrada da fila com a quebra de linha no fim"),
        (_cmd("x22", "enfileirar", {"youtube_id": "dQw4w9WgXcQ\n"}), "id de video com a quebra de linha no fim"),
    ]
    ok = {"protocolo": 1, "tipo": "resultado", "sessao": SESSAO, "ok": True}
    erro = {"protocolo": 1, "tipo": "resultado", "sessao": SESSAO, "ok": False}
    resultados = [
        dict(ok, id="c3", rev=12, dados={"qid": "9a8b7c6d", "tocando": False}),
        dict(ok, id="c10", rev=13, dados={"vol": 0.35}),
        dict(ok, id="c11", rev=14, dados={"abaixa": {"db": 12, "ms": 3000}}),
        dict(ok, id="c12", rev=15, dados={"abaixa": None}),
        dict(ok, id="c5", rev=16, dados={}),
        dict(erro, id="c5", erro="conflito"),
        dict(erro, id="x1", erro="fora_do_vocabulario"),
        dict(erro, id="c6", erro="sem_pc", retido_ms=0),
    ]
    resultados_invalidos = [
        (dict(erro, id="c5", erro="conflito", mensagem="The queue is empty"), "a mensagem local nao sai do PC"),
        (dict(erro, id="c5", erro="api_409"), "codigo fora da lista"),
        (dict(ok, id="c5", dados={}), "ok sem o rev"),
        (dict(ok, id="c10", rev=13, dados={"vol": 0.35, "config": "x"}), "dado fora da lista"),
        (dict(ok, id="c3", rev=12, dados={"qid": "9a8b7c6d"}), "o enfileirar sem o tocando"),
        (dict(ok, id="c10", rev=13, dados={"vol": 0.35, "abaixa": None}), "dados de dois comandos juntos"),
    ]
    pular = _cmd("r1", "pular", {})
    feito = dict(ok, id="r1", rev=20, dados={})
    repeticao = [
        {"msg": pular, "espera": "executa", "resultado": feito},
        {"msg": pular, "espera": feito, "nota": "o mesmo id, comando e argumentos: o resultado guardado, sem pular de novo"},
        {"msg": _cmd("r1", "pausar", {}), "espera": dict(erro, id="r1", erro="id_repetido"),
         "nota": "o mesmo id com outro comando: recusado sem mexer na reproducao"},
    ]
    return {"validos": [{"msg": m, "pedido": {"metodo": p[0], "caminho": p[1], "corpo": p[2]}} for m, p in validos],
            "invalidos": [{"msg": m, "por_que": n} for m, n in invalidos],
            "resultados": resultados, "resultados_invalidos": [{"msg": m, "por_que": n} for m, n in resultados_invalidos],
            "repeticao": repeticao}


LOCAL = {  # o GET /api/state de verdade traz tudo isto; para fora do PC vai so o que a projecao lista
    "status": "playing", "duration": 236.0, "vol": 0.6, "mon_vol": 0.6, "mic_vol": 1.0, "mic_mute": False,
    "volume_auto": True, "ganho_db": -2.1, "monitor_on": True, "loop": False, "effect": "nenhum", "voice_monitor": False,
    "voice_mon_vol": 0.8, "por_cima": [], "abaixa": {"db": 12, "ms": 3000},
    "track": {"id": "w6kKVs-h9Ns", "title": "Um disco", "file": "w6kKVs-h9Ns.webm", "duration": 236.0,
              "youtube_id": "w6kKVs-h9Ns", "thumb": "https://i.ytimg.com/vi/w6kKVs-h9Ns/mqdefault.jpg",
              "channel": "Um canal", "added": "2026-10-17T13:34:56", "last_pos": 807, "plays": 3, "lufs": -14.1, "bpm": 96.0},
    "devices": {"mic": "default", "monitor": "default"},
    "active_devices": {"mic": "Microfone (Aparelho)", "monitor": "Fone (Aparelho)"},
    "microfone": {"anel": True, "leitores": 1, "folga_min_ms": 40.0, "secas": 0, "volta_max_ms": 4.5,
                  "preparando": None, "efeito_no_filtro": False},
    "error": {"key": "server.player.readFailed", "params": {"title": "x"}, "text": "Couldn't read the audio"},
    "queue": [{"qid": "4f1c2a9b", "id": None, "youtube_id": "dQw4w9WgXcQ", "url": None, "title": "Outro",
               "channel": None, "thumb": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg", "duration": 213,
               "job": "ce14abe3", "bpm": 98.0},
              {"qid": "0a1b2c3d", "id": "x1", "youtube_id": None, "url": None, "title": "Parecida", "channel": "c",
               "thumb": "http://sem-tls.example/x.jpg", "duration": 180, "job": None, "auto": True, "auto_de": "Um disco"}],
    "shuffle": False, "auto": True, "history": 3, "versao": "0.9.0",
    "visor": {"ondas": 3, "passagens": []},
    "atualizacao": {"nova": "1.0.0", "estado": "pronta", "progresso": 1.0, "erro": None},
    "caps": perm.caps("remoto"), "mock": True}
LOCAL["queue"].append({"qid": "0b1c2d3e", "id": "x2", "youtube_id": None, "url": None, "title": "t" * 401,
                       "channel": None, "thumb": "https://i.ytimg.com/" + "x" * 500, "duration": 90000, "job": None})
LOCAL["queue"].append({"qid": "1c2d3e4f", "id": None, "youtube_id": "audio-file", "title": "https://x.example/a.mp3?k=1",
                       "url": "https://x.example/a.mp3?k=1", "channel": None, "thumb": None, "duration": 60, "job": "j1"})


def fixture_estados():
    """O que a projecao leva do estado local, e estados invalidos que o esquema recusa."""
    remota = projeta(LOCAL)
    remota["ancora"] = _anc(12.5, T0_MS)
    validos = [
        _estado(1, T0_MS, remota, "inicio"),
        _estado(2, T0_MS + 1, _proj("idle", None)),
        _estado(3, T0_MS + 2, _proj("paused", _anc(40.0, T0_MS + 2, anda=False))),
        _estado(4, T0_MS + 3, _proj("buffering", _anc(41.0, T0_MS + 3, anda=False), fila=remota["fila"])),
        _pulso(4, T0_MS + 1000),
        _estado(5, T0_MS + 4, _proj(anc=_anc(0.0, T0_MS + 4, segs=[
            {"n": 1138, "v": 0.0, "preenchimento": True}, {"n": 284000, "v": 1.02, "pos": 0.0},
            {"n": 960000, "v": {"de": 1.0204, "ate": 1.0, "total": 960000, "fase": 0}}, {"n": None, "v": 1.0}]))),
    ]
    base = _estado(9, T0_MS, _proj(anc=_anc(1.0, T0_MS)))
    invalidos = []
    for campo, valor, nota in (("microfone", LOCAL["microfone"], "o microfone nunca sai do PC"),
                               ("devices", LOCAL["devices"], "os aparelhos nunca saem do PC"),
                               ("active_devices", LOCAL["active_devices"], "os aparelhos nunca saem do PC"),
                               ("atualizacao", LOCAL["atualizacao"], "a atualizacao nunca sai do PC"),
                               ("error", LOCAL["error"], "o erro local nunca sai do PC"),
                               ("mic_mute", False, "o microfone nunca sai do PC")):
        m = copy.deepcopy(base)
        m["estado"][campo] = valor
        invalidos.append({"msg": m, "por_que": nota})
    for nota, mexe in (
            ("campo da faixa fora da lista (o arquivo local)", lambda m: m["estado"]["faixa"].update(file="x.webm")),
            ("campo da fila fora da lista (o download local)", lambda m: m["estado"].update(
                fila=[dict(remota["fila"][0], job="ce14abe3")])),
            ("parado com faixa", lambda m: m["estado"].update(status="idle")),
            ("tocando com a ancora parada", lambda m: m["estado"]["ancora"].update(anda=False)),
            ("tocando sem segmentos", lambda m: m["estado"]["ancora"].update(segmentos=[])),
            ("id de video com a quebra de linha no fim", lambda m: m["estado"]["faixa"].update(youtube_id="dQw4w9WgXcQ\n")),
            ("pausado com a ancora andando", lambda m: m["estado"].update(status="paused")),
            ("outra taxa", lambda m: m["estado"]["ancora"].update(taxa=44100)),
            ("velocidade zero", lambda m: m["estado"]["ancora"].update(segmentos=[{"n": None, "v": 0}])),
            ("segmento de zero amostras", lambda m: m["estado"]["ancora"].update(segmentos=[{"n": 0, "v": 1.0}])),
            ("cosseno aberto", lambda m: m["estado"]["ancora"].update(
                segmentos=[{"n": None, "v": {"de": 1.0, "ate": 1.01, "total": 10, "fase": 0}}])),
            ("preenchimento aberto", lambda m: m["estado"]["ancora"].update(
                segmentos=[{"n": None, "v": 1.0, "preenchimento": True}])),
            ("preenchimento em cosseno", lambda m: m["estado"]["ancora"].update(
                segmentos=[{"n": 10, "v": {"de": 1.0, "ate": 1.01, "total": 10, "fase": 0}, "preenchimento": True}])),
            ("cosseno sem a fase", lambda m: m["estado"]["ancora"].update(
                segmentos=[{"n": 10, "v": {"de": 1.0, "ate": 1.01, "total": 10}}])),
            ("posicao negativa", lambda m: m["estado"]["ancora"].update(pos=-0.01)),
            ("rev zero", lambda m: m.update(rev=0)),
            ("origem fora da lista", lambda m: m.update(origem="tick")),
            ("capacidade fora do vocabulario", lambda m: m["estado"].update(capacidades=["parar"])),
            ("volume fora de 0 a 1", lambda m: m["estado"].update(vol=1.2)),
            ("capa sem https", lambda m: m["estado"]["faixa"].update(thumb="http://x/y.jpg")),
            ("pos no primeiro segmento", lambda m: m["estado"]["ancora"]["segmentos"][0].update(pos=3.0)),
            ("segmento aberto antes do ultimo", lambda m: m["estado"]["ancora"].update(
                segmentos=[{"n": None, "v": 1.0}, {"n": 10, "v": 1.0, "pos": 5.0}])),
            ("cosseno alem do total", lambda m: m["estado"]["ancora"].update(
                segmentos=[{"n": 20, "v": {"de": 1.0, "ate": 1.01, "total": 10, "fase": 0}}])),
            ("a ancora de outra faixa", lambda m: m["estado"]["ancora"].update(faixa="outra"))):
        m = copy.deepcopy(base)
        mexe(m)
        invalidos.append({"msg": m, "por_que": nota})
    return {"local": LOCAL, "remota": dict(remota, ancora=None), "validos": validos, "invalidos": invalidos}


def gera():
    FIX.mkdir(parents=True, exist_ok=True)
    escritos = []
    for nome, fn in CENARIOS.items():
        info, msgs, _ = fn()
        dados = {"cenario": nome, **info, "relogio": {"t0_ms": T0_MS, "taxa": SR}, "mensagens": msgs}
        escritos.append(_escreve(f"posicao-{nome}.json", _limpa(dados)))
    for nome, fn in (("relogio", fixture_relogio), ("relay", fixture_relay), ("comandos", fixture_comandos),
                     ("estados", fixture_estados)):
        escritos.append(_escreve(f"{nome}.json", _limpa(fn())))
    for p in escritos:
        print(f"escreveu {p.relative_to(RAIZ)}")


def _escreve(nome, dados):
    p = FIX / nome
    p.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def _le(nome):
    return json.loads((FIX / nome).read_text("utf-8"))


# ------------------------------------------------------------------------------------------------------- testes

class Esquemas(unittest.TestCase):
    def setUp(self):
        self.docs, self.val = esquemas()

    def test_esquemas_validos(self):
        for d in self.docs.values():
            jsonschema.Draft202012Validator.check_schema(d)

    def _valido(self, nome, msg):
        erros = valida_estado(self.val[nome], msg) if nome == "estado" else [e.message for e in self.val[nome].iter_errors(msg)]
        self.assertEqual(erros, [], f"{nome}: {json.dumps(msg, ensure_ascii=False)[:300]}")

    def _invalido(self, nome, msg, por_que):
        ok = not valida_estado(self.val[nome], msg) if nome == "estado" else self.val[nome].is_valid(msg)
        self.assertFalse(ok, f"{nome} aceitou: {por_que}")

    def test_comandos(self):
        f = _le("comandos.json")
        for c in f["validos"]:
            self._valido("comando", c["msg"])
        for c in f["invalidos"]:
            self._invalido("comando", c["msg"], c["por_que"])
        for r in f["resultados"]:
            self._valido("resultado", r)
        for r in f["resultados_invalidos"]:
            self._invalido("resultado", r["msg"], r["por_que"])
        for p in f["repeticao"]:
            self._valido("comando", p["msg"])
            for k in ("resultado", "espera"):
                if isinstance(p.get(k), dict):
                    self._valido("resultado", p[k])

    def test_estados(self):
        f = _le("estados.json")
        for m in f["validos"]:
            self._valido("estado", m)
        for m in f["invalidos"]:
            self._invalido("estado", m["msg"], m["por_que"])
        for nome in ("relogio.json", "relay.json"):
            g = _le(nome)
            for p in g.get("entregas", g.get("passos")):
                if "msg" in p:
                    self._valido("estado", p["msg"])
        for m in _le("relogio.json")["adiantada"]:
            self._valido("estado", m)
        for nome in CENARIOS:
            for m in _le(f"posicao-{nome}.json")["mensagens"]:
                self._valido("estado", m["msg"])

    def test_vocabulario_igual_nos_esquemas_e_no_mapa(self):
        nomes = self.docs["argumentos"]["$defs"]["nome"]["enum"]
        self.assertEqual(sorted(nomes), sorted(MAPA["comandos"]))
        por_comando = {r["if"]["properties"]["comando"]["const"] for r in self.docs["comando"]["allOf"]}
        self.assertEqual(por_comando, set(nomes), "todo comando tem os argumentos dele no comando.schema.json")
        for n in nomes:
            self.assertIn(n, self.docs["argumentos"]["$defs"], f"{n} sem argumentos")


class Mapa(unittest.TestCase):
    def test_bate_com_a_tabela_do_permissao(self):
        do_mapa = {(r["metodo"], r["rota"]) for rs in MAPA["comandos"].values() for r in rs}
        leitura = {(r["metodo"], r["rota"]) for r in MAPA["leitura"]}
        for m, r in do_mapa | leitura:
            self.assertIn("remoto", perm.papeis(m, r), f"{m} {r} do mapa nao e do papel remoto no permissao.py")
        do_remoto = {(m, r) for (m, r), p in perm.TABELA.items() if "remoto" in p}
        self.assertEqual(do_remoto, do_mapa | leitura, "o mapa e a tabela do permissao.py tem de ter as mesmas rotas")
        self.assertFalse(do_mapa & leitura)

    def test_capacidades_sao_o_vocabulario_inteiro(self):
        self.assertEqual(capacidades(), list(MAPA["comandos"]))

    def test_rota_com_campo_e_campo_obrigatorio(self):
        docs, _ = esquemas()
        for nome, rs in MAPA["comandos"].items():
            for r in rs:
                for campo in [p[1:-1] for p in r["rota"].split("/") if p.startswith("{")]:
                    self.assertIn(campo, docs["argumentos"]["$defs"][nome].get("required", []), f"{nome}: {campo}")
            if len(rs) > 1:  # com mais de uma rota, cada uma tem o argumento dela, e cada ramo dos argumentos uma rota
                ramos = docs["argumentos"]["$defs"][nome]["oneOf"]
                self.assertEqual(sorted(r["quando"] for r in rs), sorted(x["required"][0] for x in ramos))

    def test_traducao_das_fixtures(self):
        for c in _le("comandos.json")["validos"]:
            m, caminho, corpo = traduz(c["msg"])
            self.assertEqual({"metodo": m, "caminho": caminho, "corpo": corpo}, c["pedido"], c["msg"]["comando"])

    def test_erros_da_api_local(self):
        docs, _ = esquemas()
        codigos = set(docs["resultado"]["$defs"]["codigo"]["enum"])
        self.assertTrue(set(MAPA["erros"].values()) <= codigos)
        self.assertTrue(set(MAPA["dados"]) <= set(MAPA["comandos"]))
        formas = [set(f.get("required", [])) for f in docs["resultado"]["$defs"]["dados"]["oneOf"]]
        for d in MAPA["dados"].values():  # cada comando com dados devolve uma das formas do esquema
            self.assertIn(set(d), formas)

    def test_repeticao_pelo_id(self):
        guardados = {}
        for p in _le("comandos.json")["repeticao"]:
            r = resultado_repetido(guardados, p["msg"])
            if p["espera"] == "executa":
                self.assertIsNone(r)
                guardados[p["msg"]["id"]] = {"comando": p["msg"]["comando"], "args": p["msg"]["args"],
                                             "resultado": p["resultado"]}
            else:
                self.assertEqual(r, p["espera"], p.get("nota"))


class Projecao(unittest.TestCase):
    def test_so_os_campos_da_lista(self):
        f = _le("estados.json")
        self.assertEqual(projeta(f["local"]), {k: v for k, v in f["remota"].items() if k != "ancora"})
        link = f["remota"]["fila"][-1]  # o link direto: sem o endereco e sem o id que nao e de video
        self.assertEqual((link["title"], link["youtube_id"]), (None, None))
        cortada = f["remota"]["fila"][-2]
        self.assertEqual((len(cortada["title"]), cortada["thumb"], cortada["duration"]), (TEXTO_MAX, None, None))
        self.assertEqual(f["remota"]["capacidades"], list(MAPA["comandos"]))
        self.assertTrue(esquemas()[1]["estado"].is_valid(_estado(1, T0_MS, dict(f["remota"], ancora=_anc(1.0, T0_MS)))))
        texto = json.dumps(f["remota"])
        for fora in ('"microfone"', '"devices"', '"active_devices"', '"atualizacao"', '"mic_mute"', '"error"', '"caps"',
                     '"file"', '"job"', '"url"', '"last_pos"', "Aparelho", "sem-tls", "x.example"):
            self.assertNotIn(fora, texto)


class RelayECliente(unittest.TestCase):
    def test_relay(self):
        relay = Relay()
        for p in _le("relay.json")["passos"]:
            if p.get("relay") == "aceita":
                relay.aceita(p["sessao"])
            elif p.get("cliente") == "conecta":
                foto = relay.conecta(p["agora_relay"])
                if p["espera"] is None:
                    self.assertIsNone(foto, p.get("nota"))
                else:
                    self.assertEqual(foto["rev"], p["espera"]["rev"])
                    self.assertEqual(foto["retido_ms"], p["espera"]["retido_ms"])
                    self.assertEqual(foto["sessao"], p["espera"].get("sessao", SESSAO))
            else:
                self.assertEqual(relay.do_pc(p["msg"], p["agora_relay"]), p["espera"], p.get("nota"))

    def test_cliente_descarta_rev_antigo(self):
        c = Cliente(SESSAO)
        p = _proj(anc=_anc(1.0, T0_MS))
        self.assertTrue(c.recebe(_estado(2, T0_MS, p)))
        self.assertFalse(c.recebe(_estado(1, T0_MS, p)))
        self.assertFalse(c.recebe(_estado(2, T0_MS, p)))
        self.assertFalse(c.recebe(_estado(3, T0_MS, p, sessao="sessao-de-teste-02")))
        self.assertTrue(c.recebe(_estado(3, T0_MS, p)))

    def test_foto_adiantada(self):
        f = _le("relogio.json")
        c = Cliente(SESSAO)
        for m in f["adiantada"]:
            self.assertTrue(c.recebe(m))  # o rev novo entra na hora
        for x in f["leituras"]:
            faixa, pos = c.posicao(x["pc_ms"])
            self.assertEqual(faixa, x["faixa"])
            self.assertAlmostEqual(pos, x["pos"], places=9)

    def test_prato_vazio(self):
        c = Cliente(SESSAO)
        self.assertTrue(c.recebe(_estado(1, T0_MS, _proj("idle", None))))
        self.assertIsNone(c.posicao(T0_MS))  # a primeira foto e do prato vazio
        c.recebe(_estado(2, T0_MS + 10, _proj(anc=_anc(5.0, T0_MS + 10))))
        self.assertEqual(c.posicao(T0_MS + 1010), (FAIXA["id"], 6.0))
        c.recebe(_estado(3, T0_MS + 2000, _proj("idle", None)))
        self.assertIsNone(c.posicao(T0_MS + 3000))  # parou: a faixa de antes nao anda mais

    def test_curva_nova_corta_a_anterior(self):
        curvas, deck = {}, types.SimpleNamespace()
        registra_curva(curvas, deck, {"inicio": 0, "segmentos": [{"n": 100, "v": 1.02}, {"n": 300, "v": _cos(1.02, 1, 300)}]})
        registra_curva(curvas, deck, {"inicio": 250, "segmentos": [{"n": 50, "v": _cos(1, 1.01, 50)}]})
        primeira, segunda = curvas[id(deck)]
        self.assertEqual([s["n"] for s in primeira["segmentos"]], [100, 150])
        self.assertEqual(segunda["inicio"], 250)
        self.assertEqual(segmentos([], curvas[id(deck)], 240, True)[0]["n"], 10)

    def test_marca_do_disco_que_saiu(self):
        """A marca de um disco que ja saiu do deck entre dois ticks (a virada na rampa de saida): a curva do deck dela
        ainda vale ali, e depois a velocidade 1, aberta."""
        curvas, deck = {}, types.SimpleNamespace()
        registra_curva(curvas, deck, {"inicio": 100, "segmentos": [{"n": 300, "v": _cos(1, 1.02, 300)},
                                                                   {"n": 200, "v": 1.02}]})
        prod = Produtor(None, None, curvas, None)
        segs = prod._so_da_marca({"deck": id(deck), "c": 250})
        self.assertEqual(segs, [{"n": 150, "v": dict(_cos(1, 1.02, 300), fase=150)}, {"n": 200, "v": 1.02},
                                {"n": None, "v": 1.0}])
        self.assertEqual(prod._so_da_marca({"deck": id(deck), "c": 700}), [{"n": None, "v": 1.0}])  # a curva acabou

    def test_relogio_e_foto_atrasada(self):
        f = _le("relogio.json")
        r, menor = Relogio(), math.inf
        for p in f["entregas"]:
            r.recebe(p["msg"], p["chega_ms"])
            menor = min(menor, p["transito_ms"])
            real = p["chega_ms"] - f["desvio_real_ms"]  # o relogio do PC quando a mensagem chegou
            self.assertAlmostEqual(real - r.pc(p["chega_ms"]), menor, places=6, msg=p["nota"])
            if p["msg"]["tipo"] == "estado":
                anc = p["msg"]["estado"]["ancora"]
                # a posicao mostrada fica atras da real so o tanto do menor atraso visto (a velocidade e 1)
                self.assertAlmostEqual(posicao(anc, real) - posicao(anc, r.pc(p["chega_ms"])), menor / 1000, places=6)


CONTINUA = ("fronteira", "reconexao", "projecao")  # o estado que nao muda o mapa: a ancora de antes segue valendo


def _iguais(a, b, caminho=""):
    """As mensagens de agora e as da fixture iguais, com os numeros a menos de 1e-9 (o ultimo bit do numpy pode mudar
    de uma maquina para outra). Devolve onde diferem, ou None."""
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str):
        return None if a == b else caminho
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return None if math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9) else caminho
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return caminho + "{chaves}"
        return next((d for k in a if (d := _iguais(a[k], b[k], f"{caminho}.{k}"))), None)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return caminho + "[tamanho]"
        return next((d for i, (x, y) in enumerate(zip(a, b)) if (d := _iguais(x, y, f"{caminho}[{i}]"))), None)
    return caminho


def _u(t_ms):
    return round((t_ms - T0_MS) * POR_MS)


class Posicao(unittest.TestCase):
    """Cada cenario: o motor de verdade sem som, e cada foto da fixture contra o mapa de amostras dele."""

    corridas = {}

    @classmethod
    def corre(cls, nome):
        if nome not in cls.corridas:
            cls.corridas[nome] = CENARIOS[nome]()
        return cls.corridas[nome]

    def confere(self, nome):
        info, msgs_agora, mapa = self.corre(nome)
        fixture = _le(f"posicao-{nome}.json")
        # o produtor de agora publica o mesmo que a fixture (rode --gera se mudou o motor ou o produtor)
        self.assertEqual(len(msgs_agora), len(fixture["mensagens"]), f"{nome}: rode python dev/testa_protocolo.py --gera")
        for x, y in zip(_limpa(msgs_agora), fixture["mensagens"]):
            self.assertIsNone(_iguais(x, y), f"{nome}: rev {y['msg']['rev']} mudou; rode python dev/testa_protocolo.py --gera")
        msgs = [m for m in fixture["mensagens"] if m["msg"]["tipo"] == "estado"]
        us = [u for u, _, _ in mapa]
        conferidos = set()
        for i, m in enumerate(msgs):
            est = m["msg"]["estado"]
            anc = est["ancora"]
            if anc is None:
                continue
            self.assertEqual(anc["faixa"], est["faixa"]["id"])
            for s in anc["segmentos"]:
                if isinstance(s["v"], dict):
                    self.assertLessEqual(s["v"]["fase"] + s["n"], s["v"]["total"])
            for s in anc["segmentos"][:-1]:
                self.assertIsNotNone(s["n"], "so o ultimo segmento pode ser aberto")
            # vale do instante dela ate o da proxima foto que muda o mapa (a fronteira, a reconexao e a projecao seguem
            # com a mesma ancora): cada rotulo, por toda foto que ainda vale nele
            u_fim = min((_u((x["msg"]["estado"]["ancora"] or {}).get("t", x["msg"]["agora"]))
                         for x in msgs[i + 1:] if x["evento"] not in CONTINUA), default=math.inf)
            self.assertLessEqual(_u(anc["t"]), u_fim, f"{nome}: rev {m['msg']['rev']} voltou no tempo")
            if len(anc["segmentos"]) == SEGMENTOS_MAX:  # cheia: so promete ate o comeco do ultimo segmento
                u_fim = min(u_fim, _u(anc["t"]) + sum(x["n"] for x in anc["segmentos"][:-1]))
            if i:
                ant = msgs[i - 1]["msg"]["estado"]["ancora"]
                self.assertLessEqual(_u(ant["t"]) if ant else 0, _u(anc["t"]), f"{nome}: rev {m['msg']['rev']} antes")
            for u, faixa, rotulo in mapa[bisect.bisect_left(us, _u(anc["t"])):]:
                if u >= u_fim:
                    break
                self.assertEqual(faixa, anc["faixa"], f"{nome}: rev {m['msg']['rev']} na amostra {u}")
                p = posicao(anc, ms(u))
                self.assertLessEqual(abs(p - rotulo), TOL_S,
                                     f"{nome}: rev {m['msg']['rev']} ({m['evento']}) na amostra {u}: {p} e o motor "
                                     f"{rotulo}")
                conferidos.add(u)
        # todo rotulo ate o ultimo tick foi conferido por alguma foto
        ultimo = max(_u(m["msg"]["agora"]) for m in msgs)
        primeiro = _u(msgs[0]["msg"]["estado"]["ancora"]["t"])
        faltam = [u for u in us if primeiro <= u <= ultimo and u not in conferidos]
        self.assertEqual(faltam[:5], [], f"{nome}: rotulos sem foto que valha")
        return info, fixture["mensagens"], mapa

    @staticmethod
    def primeiro(m):
        anc = m["msg"]["estado"]["ancora"] if m["msg"]["tipo"] == "estado" else None
        return anc["segmentos"][0] if anc and anc["segmentos"] else None

    def test_passagem_dois(self):
        info, msgs, _ = self.confere("passagem-dois")
        self.assertTrue(0 < info["pad"] < BLOCO)
        cos = [(m["evento"], m["msg"]["estado"]["ancora"]["faixa"], s["v"]["fase"], s["v"]["total"])
               for m in msgs if (s := self.primeiro(m)) and isinstance(s["v"], dict)]
        for faixa in ("A", "B"):  # o comeco (a fronteira, no instante dele), o meio (a reconexao) e o fim
            self.assertIn(("fronteira", faixa, 0), [(e, f, fase) for e, f, fase, _ in cos], faixa)
            self.assertTrue(any(e == "reconexao" and f == faixa and 0.4 < fase / n < 0.9 for e, f, fase, n in cos), faixa)
        fins = [m for m in msgs if m["evento"] == "fronteira" and (s := self.primeiro(m)) and not isinstance(s["v"], dict)]
        self.assertTrue(any(m["msg"]["estado"]["ancora"]["faixa"] == "A" and self.primeiro(m)["v"] > 1 for m in fins))
        self.assertTrue(any(m["msg"]["estado"]["ancora"]["faixa"] == "B" and self.primeiro(m)["v"] == 1.0 for m in fins))
        troca = next(m for m in msgs if m["evento"] == "troca")
        self.assertTrue(self.primeiro(troca).get("preenchimento"))  # a ancora da virada, no instante dela

    def test_passagem_cancelada(self):
        _, msgs, _ = self.confere("passagem-cancelada")
        self.assertEqual([m["evento"] for m in msgs],
                         ["inicio", "mapa", "fronteira", "projecao", "reconexao", "fronteira", "reconexao", "fronteira",
                          "fim"])
        cancelou = msgs[3]["msg"]["estado"]["ancora"]
        self.assertEqual(cancelou, msgs[2]["msg"]["estado"]["ancora"])  # so a fila mudou: a mesma ancora
        rec = [self.primeiro(m) for m in msgs if m["evento"] == "reconexao"]
        self.assertTrue(isinstance(rec[0]["v"], dict) and rec[0]["v"]["fase"] > 0)   # no meio da rampa
        self.assertTrue(not isinstance(rec[1]["v"], dict) and rec[1]["v"] > 1)       # no trecho em sa
        # a ultima ancora andando para exatamente onde o motor congela no fim
        andando, fim = msgs[-2]["msg"]["estado"]["ancora"], msgs[-1]["msg"]["estado"]["ancora"]
        self.assertEqual(andando["segmentos"][0]["v"], 1.0)  # o ultimo bloco esticado, a 1 como o _mixa
        self.assertAlmostEqual(posicao(andando, andando["t"] + 60_000), fim["pos"], places=9)
        # e na hora em que ele para: no meio do bloco em que a fila acabou, nao no tick que ve o ended depois
        self.assertEqual(_u(fim["t"]), _u(andando["t"]) + sum(x["n"] for x in andando["segmentos"]))

    def test_cancelada_repetir(self):
        _, msgs, mapa = self.confere("cancelada-repetir")
        ev = [m["evento"] for m in msgs]
        self.assertNotIn("fim", ev)
        volta = max(u for u, _, r in mapa if r == 0.0)  # o rotulo 0 da volta (o primeiro e o comeco do disco)
        depois = [m for m in msgs if m["evento"] == "reconexao" and _u(m["msg"]["estado"]["ancora"]["t"]) > volta]
        self.assertEqual(len(depois), 1)  # a reconexao logo depois da volta: a 1, sem a curva de antes
        self.assertEqual(depois[0]["msg"]["estado"]["ancora"]["segmentos"][0]["v"], 1.0)

    def test_mesmo_disco(self):
        _, msgs, mapa = self.confere("mesmo-disco")
        virada = next(u for (u, _, r), (_, _, r0) in zip(mapa[1:], mapa) if r == 0.0 and r0 > 1.0)
        self.assertIn(virada, [_u(m["msg"]["estado"]["ancora"]["t"]) for m in msgs])  # a ancora no instante da virada

    def test_troca_no_load(self):
        _, msgs, mapa = self.confere("troca-no-load")
        troca = next(m for m in msgs if m["evento"] == "troca")["msg"]["estado"]["ancora"]
        self.assertEqual((_u(troca["t"]), troca["pos"]), (next(u for u, f, _ in mapa if f == "B"), 0.0))

    def test_volta_tarde(self):
        self._voltas("volta-tarde")

    def test_volta_e_virada(self):
        msgs = self._voltas("volta-e-virada")
        ev = [(m["evento"], m["msg"]["estado"]["ancora"]["faixa"]) for m in msgs]
        i = ev.index(("troca", "B"))
        self.assertEqual(ev[i - 1], ("fronteira", "A"))  # a volta de A antes da virada, no mesmo tick
        self.assertEqual(msgs[i - 1]["msg"]["agora"], msgs[i]["msg"]["agora"])

    def test_seek_na_rampa(self):
        _, msgs, _ = self.confere("seek-na-rampa")
        self.assertEqual([m["evento"] for m in msgs], ["inicio", "mapa", "fronteira", "mapa"])
        depois = [m for m in msgs if m["msg"]["estado"]["ancora"]["pos"] >= 30.0]
        self.assertEqual(len(depois), 1)  # um estado so depois do seek, com a cauda (a curva saiu com o gen)
        self.assertTrue(all(not isinstance(s["v"], dict) and s["v"] == 1.0  # a curva saiu com a fila limpa
                            for s in depois[0]["msg"]["estado"]["ancora"]["segmentos"]))

    def test_repetir_curto(self):
        _, msgs, _ = self.confere("repetir-curto")
        cheias = [m["msg"]["estado"]["ancora"]["segmentos"] for m in msgs
                  if len(m["msg"]["estado"]["ancora"]["segmentos"]) == SEGMENTOS_MAX]
        self.assertTrue(cheias)  # o orcamento chegou ao limite: o ultimo fica aberto
        self.assertTrue(all(segs[-1]["n"] is None for segs in cheias))

    def _seco(self, nome):
        info, msgs, mapa = self.confere(nome)
        self.assertGreater(info["pad"], BLOCO)
        rec = [m for m in msgs if m["evento"] == "reconexao"]
        self.assertEqual(len(rec), 1)
        self.assertTrue(self.primeiro(rec[0]).get("preenchimento"))  # entre a virada e o inicio efetivo
        virada = next(u for u, f, _ in mapa if f == "B")
        anc = rec[0]["msg"]["estado"]["ancora"]  # so com ela: antes, na fronteira e depois do inicio efetivo
        perto = [(u, r) for u, f, r in mapa if f == "B" and _u(anc["t"]) <= u <= virada + info["pad"] + 2 * BLOCO]
        self.assertGreaterEqual(len(perto), 3)
        for u, r in perto:
            self.assertLessEqual(abs(posicao(anc, ms(u)) - r), TOL_S, f"{nome}: a reconexao na amostra {u}")
        return info, msgs, mapa, virada

    def test_final_seco(self):
        info, _, mapa, virada = self._seco("final-seco")
        self.assertEqual(info["origem"], 0.0)  # ini - pad abaixo de zero: preso em zero, como o rotulo do motor
        # o mapa do motor: o bloco unico partido pelo _tira anda a 1 desde o zero, e na fronteira volta ao ini
        self.assertEqual([r for u, f, r in mapa if f == "B" and u == virada + info["pad"]], [info["ini"]])
        self.assertGreater(next(r for u, f, r in mapa if f == "B" and u > virada), 0.0)

    def test_final_seco_sem_limite(self):
        info, _, mapa, virada = self._seco("final-seco-sem-limite")
        self.assertAlmostEqual(info["origem"], info["ini"] - info["pad"] / SR, places=9)
        self.assertEqual([r for u, f, r in mapa if f == "B" and u == virada + info["pad"]], [info["ini"]])

    def test_final_seco_esticado(self):
        info, msgs, mapa, virada = self._seco("final-seco-esticado")
        self.assertEqual(info["origem"], 0.0)
        # o mapa do motor: os blocos de 10 ms do preenchimento ficam todos em zero
        presos = [r for u, f, r in mapa if f == "B" and virada <= u < virada + info["pad"]]
        self.assertGreater(len(presos), 1)
        self.assertEqual(set(presos), {0.0})
        troca = next(m for m in msgs if m["evento"] == "troca")
        s = self.primeiro(troca)
        self.assertEqual((s["v"], s.get("preenchimento")), (0.0, True))

    def test_buffering(self):
        _, msgs, mapa = self.confere("buffering")
        self.assertEqual([m["evento"] for m in msgs],
                         ["inicio", "buffering", "retomada", "buffering", "retomada", "pausa", "retomada", "pausa",
                          "retomada"] + ["pausa", "retomada"] * 5)
        # sem salto de rotulo no buffering: a retomada que continua nao abre trecho com pos
        self.assertEqual([s for m in msgs for s in m["msg"]["estado"]["ancora"]["segmentos"] if "pos" in s], [])
        volta = [m["msg"] for m in msgs[2:4]]  # o stream que solta 20 ms com o buffering publicado: as duas, em ordem
        self.assertEqual(volta[0]["agora"], volta[1]["agora"])
        self.assertEqual(_u(volta[1]["estado"]["ancora"]["t"]) - _u(volta[0]["estado"]["ancora"]["t"]), 2 * BLOCO)
        logo = [m["msg"] for m in msgs[6:8]]  # a retomada e a pausa logo depois da pausa publicada
        self.assertEqual(logo[0]["agora"], logo[1]["agora"])
        self.assertEqual(_u(logo[1]["estado"]["ancora"]["t"]) - _u(logo[0]["estado"]["ancora"]["t"]), 2 * BLOCO)
        curta = [m["msg"] for m in msgs[9:11]]  # a pausa de 30 ms entre dois ticks: as duas no mesmo tick, em ordem
        self.assertEqual(curta[0]["agora"], curta[1]["agora"])
        self.assertEqual(_u(curta[1]["estado"]["ancora"]["t"]) - _u(curta[0]["estado"]["ancora"]["t"]), 3 * BLOCO)
        duas = [m["msg"] for m in msgs[11:15]]  # as duas pausas de 10 ms entre os mesmos dois ticks: as quatro, em ordem
        self.assertEqual(len({m["agora"] for m in duas}), 1)
        self.assertEqual([_u(m["estado"]["ancora"]["t"]) - _u(duas[0]["estado"]["ancora"]["t"]) for m in duas],
                         [0, BLOCO, 3 * BLOCO, 4 * BLOCO])
        # a pausa curta e outra no bloco do tick, antes da marca dela: a segunda no instante do tick, nao no da primeira
        no_tick = msgs[17]["msg"]
        self.assertEqual((msgs[17]["evento"], no_tick["estado"]["ancora"]["t"]), ("pausa", no_tick["agora"]))
        b = msgs[1]["msg"]["estado"]["ancora"]  # parado no meio do bloco, onde a fila secou
        self.assertEqual((b["anda"], b["pos"]), (False, 11.005))
        self.assertEqual(_u(b["t"]), next(u for u, _, rot in mapa if rot == 11.0) + BLOCO // 2)
        r = msgs[2]["msg"]["estado"]["ancora"]
        self.assertEqual(r["pos"], 11.005)
        self.assertEqual(_u(r["t"]), next(u for u, _, rot in mapa if rot == 11.005))  # no instante em que voltou

    def test_paradas_e_load(self):
        _, msgs, mapa = self.confere("paradas-e-load")
        vistos = [(m["evento"], m["msg"]["estado"]["ancora"]["faixa"], _u(m["msg"]["estado"]["ancora"]["t"]) // BLOCO)
                  for m in msgs if m["evento"] not in ("inicio", "fronteira")]
        self.assertEqual(vistos, [("pausa", "A", 5), ("retomada", "A", 8), ("pausa", "A", 9), ("retomada", "A", 16),
                                  ("pausa", "A", 29), ("retomada", "A", 30), ("troca", "B", 32), ("pausa", "B", 35),
                                  ("retomada", "B", 37), ("troca", "C", 40), ("retomada", "C", 43)])
        val = esquemas()[1]["estado"]
        for m in msgs:
            self.assertEqual(valida_estado(val, m["msg"]), [], m["evento"])

    def test_fim_e_trocas(self):
        _, msgs, mapa = self.confere("fim-e-trocas")
        vistos = [(m["evento"], m["msg"]["estado"]["status"], m["msg"]["estado"]["faixa"]["id"],
                   _u(m["msg"]["estado"]["ancora"]["t"])) for m in msgs if m["evento"] not in ("inicio", "mapa")]
        primeiro = {f: next(u for u, x, _ in mapa if x == f) for f in "BCD"}
        self.assertEqual(vistos[:7], [("fim", "ended", "A", 10 * BLOCO + BLOCO // 2),
                                      ("reconexao", "ended", "A", 11 * BLOCO),
                                      ("troca", "playing", "B", primeiro["B"]), ("troca", "playing", "C", primeiro["C"]),
                                      ("fim", "ended", "C", primeiro["C"] + 10 * BLOCO + BLOCO // 2),
                                      ("troca", "playing", "D", primeiro["D"]),
                                      ("fronteira", "playing", "D", primeiro["D"] + 2 * BLOCO)])
        # as voltas de D antes da pausa no tick: a parada de C, antes da ancora de D, nao segura as fronteiras dela
        self.assertEqual(vistos[7:9], [("fronteira", "playing", "D", primeiro["D"] + 4 * BLOCO),
                                       ("pausa", "paused", "D", 35 * BLOCO)])
        val = esquemas()[1]["estado"]
        for m in msgs:
            self.assertEqual(valida_estado(val, m["msg"]), [], m["evento"])

    def test_seek_pausado(self):
        """O seek com o prato pausado e a retomada sem audio (buffering): a parada de antes do seek nao volta o t."""
        a = _deck("A", 0.0, 3.0)
        e = _motor(a)
        sim = Sim(e)

        def seek(u):
            if u < 8 * BLOCO:
                return False
            e._restart(1.0)  # o leitor ainda nao pos nada
            return True

        def chega(u):
            if u < 25 * BLOCO:
                return False
            with e._qlock:
                a.q.extend(_deck("A", 1.0, 3.0).q)
                a.eof_gen = a.gen
            return True

        msgs = _roda(e, sim, Produtor(e, sim, {}, lambda e_: []), 0.4,
                     eventos=_pausa_nos_blocos(e, 5, 16) + [seek, chega])
        vistos = [(m["evento"], _u(m["msg"]["estado"]["ancora"]["t"]) // BLOCO) for m in msgs
                  if m["msg"]["tipo"] == "estado"]
        self.assertEqual(vistos, [("inicio", 0), ("pausa", 5), ("mapa", 14), ("buffering", 21), ("retomada", 25)])

    def test_stop_e_load(self):
        """O stop e o load de outro disco entre dois ticks: o prato vazio no instante do stop, sem as voltas que o
        disco de antes nao tocou, e a troca no primeiro bloco do novo."""
        a = _deck("A", 0.0, 0.02)
        um = list(a.q)
        for _ in range(9):  # um som de 20 ms com o Repetir: uma volta a cada 2 blocos
            a.q.extend(um)
        a.eof_gen = -1
        e = _motor(a)
        sim = Sim(e)
        b = _deck("B", 0.0, 3.0)

        def stop(u):  # o stop do motor: a fila limpa e o prato sem disco
            if u < 9 * BLOCO:
                return False
            with e._qlock:
                e._q.clear()
            e.track = None
            return True

        def load_b(u):
            if u < 12 * BLOCO:
                return False
            e.track = a.track = b.track
            e._restart(0.0)
            with e._qlock:
                a.q.extend(b.q)
                a.eof_gen = a.gen
            return True

        msgs = _roda(e, sim, Produtor(e, sim, {}, lambda e_: []), 0.2, eventos=[stop, load_b])
        vistos = [(m["evento"], m["msg"]["estado"]["status"], _u((m["msg"]["estado"]["ancora"] or {}).get(
            "t", m["msg"]["agora"])) // BLOCO) for m in msgs if m["msg"]["tipo"] == "estado"]
        # a volta de A no bloco 10 nao tocou: o stop no 9 vem antes
        self.assertEqual(vistos, [("inicio", "playing", 0), ("fronteira", "playing", 2), ("fronteira", "playing", 4),
                                  ("fronteira", "playing", 6), ("fronteira", "playing", 8), ("parada", "idle", 14),
                                  ("troca", "playing", 12)])

    def test_fim_com_a_virada_no_callback_seguinte(self):
        """O tick entre o ultimo bloco de A e o callback que vira para B: o prato nao parou, e nao sai fim."""
        a, b = _deck("A", 0.0, 0.1), _deck("B", 0.0, 1.0)
        e = _motor(a, pronto=b)
        sim = Sim(e)
        prod = Produtor(e, sim, {}, lambda e_: [])
        prod.olha(0)
        for _ in range(10):
            sim.vira()
            sim.consome()
        prod.olha(sim.u)  # o tick do servidor, fora da thread do som, pode cair aqui
        prod.olha(sim.u, reconexao=True)  # e a reconexao tambem: espera o callback que vira
        self.assertEqual([m["evento"] for m in prod.msgs], ["inicio"])
        sim.vira()
        sim.consome()
        prod.callback(sim.u)
        self.assertEqual([m["evento"] for m in prod.msgs], ["inicio", "troca", "reconexao"])
        rec = prod.msgs[-1]["msg"]
        self.assertEqual((rec["origem"], rec["estado"]["faixa"]["id"], rec["estado"]["status"]),
                         ("reconexao", "B", "playing"))
        val = esquemas()[1]["estado"]
        for m in prod.msgs:
            self.assertEqual(valida_estado(val, m["msg"]), [], m["evento"])

    def test_ultimo_bloco_curto_antes_da_virada(self):
        """O ultimo bloco de A e curto (o prato calou no meio dele) e o tick cai antes do callback que vira: nada sai
        nesse tick, e depois o fim de A no meio do bloco e a troca para B, sem retomada de A."""
        a, b = _curto("A"), _deck("B", 0.0, 1.0)
        e = _motor(a, pronto=b)
        sim = Sim(e)
        prod = Produtor(e, sim, {}, lambda e_: [])
        prod.olha(0)
        for _ in range(11):
            sim.vira()
            sim.consome()
        prod.olha(sim.u)
        self.assertEqual([m["evento"] for m in prod.msgs], ["inicio"])
        sim.vira()
        sim.consome()
        prod.olha(sim.u)
        self.assertEqual([(m["evento"], _u(m["msg"]["estado"]["ancora"]["t"])) for m in prod.msgs],
                         [("inicio", 0), ("fim", 10 * BLOCO + BLOCO // 2), ("troca", 11 * BLOCO)])
        val = esquemas()[1]["estado"]
        for m in prod.msgs:
            self.assertEqual(valida_estado(val, m["msg"]), [], m["evento"])

    def test_stop_no_tick(self):
        """O stop bem no tick (antes da marca do bloco): sai a parada, com o prato vazio."""
        a = _deck("A", 0.0, 3.0)
        e = _motor(a)
        sim = Sim(e)

        def stop(u):
            if u < 7 * BLOCO:
                return False
            with e._qlock:
                e._q.clear()
            e.track = None
            return True

        msgs = _roda(e, sim, Produtor(e, sim, {}, lambda e_: []), 0.2, eventos=[stop])
        estados = [m for m in msgs if m["msg"]["tipo"] == "estado"]
        self.assertEqual([(m["evento"], m["msg"]["estado"]["status"]) for m in estados][-1], ("parada", "idle"))
        self.assertNotIn("troca", [m["evento"] for m in estados])

    def test_fonte_que_vira_arquivo(self):
        """B entra pelo stream e vira o arquivo antes do tick seguinte: a foto da entrada leva a faixa como ela estava
        ali, e a mudanca sai depois como projecao, com a mesma ancora."""
        a = _deck("A", 0.0, 3.0)
        e = _motor(a)
        sim = Sim(e)
        b = _deck("B", 0.0, 3.0)
        b.track["stream"] = True

        def load_b(u):
            if u < 9 * BLOCO:
                return False
            e.track = a.track = b.track
            e._restart(0.0)
            with e._qlock:
                a.q.extend(b.q)
                a.eof_gen = a.gen
            return True

        def canal(u):  # o canal que chega depois, escrito no mesmo dicionario da faixa (o canal_depois)
            if u < 10 * BLOCO:
                return False
            b.track["channel"] = "Canal B"
            return True

        def arquivo(u):  # o trocar_fonte: o disco no prato passa a ser o do arquivo, com a fila igual
            if u < 11 * BLOCO:
                return False
            e.track = a.track = dict(b.track, stream=False, title="Disco B (arquivo)")
            return True

        msgs = _roda(e, sim, Produtor(e, sim, {}, lambda e_: []), 0.2, eventos=[load_b, canal, arquivo])
        vistos = [(m["evento"], m["msg"]["estado"]["faixa"]["stream"], m["msg"]["estado"]["faixa"]["title"],
                   m["msg"]["estado"]["faixa"]["channel"], _u(m["msg"]["estado"]["ancora"]["t"]) // BLOCO)
                  for m in msgs if m["msg"]["tipo"] == "estado" and m["evento"] != "inicio"]
        self.assertEqual(vistos[:2], [("troca", True, "Disco B", None, 9),
                                      ("projecao", False, "Disco B (arquivo)", "Canal B", 9)])

    def test_repetir(self):
        _, msgs, mapa = self.confere("repetir")
        self.assertEqual([m["evento"] for m in msgs], ["inicio", "mapa", "fronteira"])
        u_volta = next(u for u, _, r in mapa if r == 0.0)
        self.assertNotEqual(u_volta % BLOCO, 0)  # a volta comeca no meio de um callback
        chegou, volta = msgs[1]["msg"]["estado"]["ancora"], msgs[2]["msg"]["estado"]["ancora"]
        self.assertEqual(chegou["segmentos"][1].get("pos"), 0.0)  # a volta na ancora antes de tocar
        self.assertEqual((_u(volta["t"]), volta["pos"], volta["faixa"]), (u_volta, 0.0, "A"))  # e no primeiro bloco

    def test_fim_natural_e_rev_estavel(self):
        _, msgs, _ = self.confere("fim-natural")
        estados = [m for m in msgs if m["msg"]["tipo"] == "estado"]
        self.assertEqual([m["evento"] for m in estados], ["inicio", "mapa", "fim"])
        perto = estados[1]["msg"]["estado"]["ancora"]  # o fim do disco na janela: a ancora para em 10 s
        self.assertIsNotNone(perto["segmentos"][-1]["n"])
        self.assertAlmostEqual(posicao(perto, perto["t"] + 60_000), 10.0, places=9)
        fim = estados[2]["msg"]["estado"]
        self.assertEqual(fim["ancora"]["anda"], False)
        self.assertAlmostEqual(fim["ancora"]["pos"], 10.0, places=9)
        pulsos = [m["msg"] for m in msgs if m["msg"]["tipo"] == "pulso"]
        self.assertGreaterEqual(len(pulsos), 4)
        self.assertEqual({p["rev"] for p in pulsos if p["agora"] > estados[2]["msg"]["agora"]}, {3})

    def _voltas(self, nome):
        """Cada volta do Repetir tem a ancora dela, no instante do primeiro bloco e com o rotulo 0."""
        _, msgs, mapa = self.confere(nome)
        voltas = [u for (u, _, r), (u0, _, r0) in zip(mapa[1:], mapa)  # o rotulo 0 que nao continua o anterior
                  if r == 0.0 and abs(r0 + (u - u0) / SR) > 1e-9]
        ancoras = {(_u(m["msg"]["estado"]["ancora"]["t"]), m["msg"]["estado"]["ancora"]["pos"]) for m in msgs
                   if m["msg"]["estado"]["ancora"]}
        ultimo = max(_u(m["msg"]["agora"]) for m in msgs)  # a volta depois do ultimo tick ainda nao foi vista
        voltas = [v for v in voltas if v <= ultimo]
        self.assertTrue(voltas)
        self.assertEqual([v for v in voltas if (v, 0.0) not in ancoras], [], nome)
        return msgs

    def test_retomada_na_volta(self):
        msgs = self._voltas("retomada-na-volta")
        self.assertEqual([m["evento"] for m in msgs].count("pausa"), 4)
        # a fronteira bem no instante da pausa nao tocou: nenhuma sai com o t de uma parada
        t_de = {ev: {m["msg"]["estado"]["ancora"]["t"] for m in msgs if m["evento"] == ev} for ev in ("pausa", "fronteira")}
        self.assertEqual(t_de["pausa"] & t_de["fronteira"], set())

    def test_salto_curto_no_instante_dele(self):
        """O seek de 0,75 amostra fora do tick: a ancora nova sai no instante do salto, nao no do tick que o ve."""
        a = _deck("A", 0.0, 3.0)
        e = _motor(a)
        sim = Sim(e)
        para = {}

        def seek(u):
            if u < 10 * BLOCO:  # depois do primeiro tick, entre o de 7 e o de 14 blocos
                return False
            para["pos"] = x = float(e._q[0][0]) + 0.75 / SR
            e._restart(x)
            with e._qlock:
                a.q.extend(_deck("A", x, 3.0).q)
                a.eof_gen = a.gen
            return True

        msgs = _roda(e, sim, Produtor(e, sim, {}, lambda e_: []), 0.5, eventos=[seek])
        ancoras = [m["msg"]["estado"]["ancora"] for m in msgs if m["msg"]["tipo"] == "estado"]
        self.assertIn((_u(ms(10 * BLOCO)), para["pos"]), [(_u(x["t"]), x["pos"]) for x in ancoras])

    def test_repetir_curtissimo(self):
        self._voltas("repetir-curtissimo")

    def test_rev_estavel_entre_ticks(self):
        for nome in CENARIOS:
            _, msgs, _ = self.corre(nome)
            estados = [m for m in msgs if m["msg"]["tipo"] == "estado"]
            self.assertEqual([m["msg"]["rev"] for m in estados], list(range(1, len(estados) + 1)))
            # o produtor olhou o prato a cada tick e so publicou nas mudancas (o Repetir curto publica uma por volta)
            self.assertLess(len(estados), 60, nome)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gera", action="store_true", help="escreve as fixtures de novo")
    a, resto = ap.parse_known_args()
    if a.gera:
        gera()
        return 0
    r = unittest.main(argv=[sys.argv[0], *resto], exit=False, verbosity=2).result
    return 0 if r.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
