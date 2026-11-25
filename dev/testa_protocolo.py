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

V1 = RAIZ / "docs" / "protocolo-remoto" / "v1"
FIX = V1 / "fixtures"
SR, BLOCO = eng.SR, eng.BLOCK
POR_MS = SR / 1000          # amostras de saida por ms
T0_MS = 1_000_000.0         # o relogio do PC (ms) na amostra 0 de cada cenario
SESSAO = "sessao-de-teste-01"
TOL_S = 1 / SR              # a posicao reconstruida bate com o rotulo do bloco a menos de uma amostra
VOL = 0.6
CONTINUA = ("fronteira", "reconexao", "projecao")  # o estado que nao muda o mapa: a ancora de antes segue valendo


# ---------------------------------------------------------------------------------------------- esquemas e mapa

def esquemas():
    docs = {n: json.loads((V1 / f"{n}.schema.json").read_text("utf-8"))
            for n in ("estado", "comando", "argumentos", "resultado")}
    reg = Registry().with_resources([(d["$id"], Resource.from_contents(d)) for d in docs.values()])
    return docs, {n: jsonschema.Draft202012Validator(d, registry=reg) for n, d in docs.items()}


MAPA = json.loads((V1 / "comandos.json").read_text("utf-8"))


def capacidades():
    """Os comandos que o papel remoto alcanca: os que tem todas as rotas dele no caps do permissao.py."""
    rotas = set(perm.caps("remoto")["rotas"])
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
    if a["faixa"] != b["faixa"] or a["anda"] != b["anda"] or abs(a["pos"] - b["pos"]) > 0.5 / SR:
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
    """Quem recebe: so a sessao dele, e o estado com rev maior que o ultimo."""

    def __init__(self, sessao):
        self.sessao, self.rev, self.estado = sessao, 0, None

    def recebe(self, msg):
        if msg["sessao"] != self.sessao or msg["tipo"] != "estado" or msg["rev"] <= self.rev:
            return False
        self.rev, self.estado = msg["rev"], msg["estado"]
        return True


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


def _https(v):
    return v if isinstance(v, str) and v.startswith("https://") else None


def projeta(local):
    """A projecao do estado local (o do GET /api/state) para fora do PC, sem a ancora: so os campos da lista."""
    tr = local.get("track")
    faixa = None
    if tr is not None and local["status"] != "idle":
        faixa = {**{k: tr.get(k) for k in CAMPOS_FAIXA}, "thumb": _https(tr.get("thumb")), "stream": bool(tr.get("stream"))}
    return {"status": local["status"], "faixa": faixa,
            "fila": [{**{k: x.get(k) for k in CAMPOS_FILA}, "thumb": _https(x.get("thumb")), "auto": bool(x.get("auto"))}
                     for x in local.get("queue") or []],
            "vol": local["vol"], "abaixa": local.get("abaixa"), "capacidades": capacidades()}


def segmentos(q, curva, desde_virada):
    """Os segmentos de velocidade do prato a partir do proximo bloco da fila q: v = 1 sem curva; na rampa de saida,
    pela fila (o que falta dos blocos esticados, a partir do rotulo t_r); na faixa que entrou, pelas amostras do prato
    desde a virada."""
    if curva is None:
        return [{"n": None, "v": 1.0}]
    if curva["tipo"] == "saida":
        t_r = curva["t_r"]
        resta = sum(len(a) for t, a in q if t >= t_r - 1e-7)
        c = curva["n"] - resta
        if c == 0:
            antes = sum(len(a) for t, a in q if t < t_r - 1e-7)
            return ([{"n": antes, "v": 1.0}] if antes else []) + corta(curva["segmentos"], 0)
        return corta(curva["segmentos"], c)
    return corta(curva["segmentos"], desde_virada)


class Produtor:
    """O que o PC publica: a cada bloco olha o prato; publica um estado novo (rev + 1) quando a projecao muda, quando
    a ancora de antes deixa de prever a posicao (o mapa mudou) e em cada fronteira de segmento, e a foto completa
    quando o conector religa. O pulso so repete o rev."""

    def __init__(self, e, sim, curvas, fila):
        self.e, self.sim, self.curvas, self.fila = e, sim, curvas, fila
        self.rev, self.pub, self.msgs, self.olhadas = 0, None, [], 0

    def projecao(self, u):
        e = self.e
        p = projeta({"status": e.status(), "track": e.track, "queue": self.fila(e), "vol": VOL, "abaixa": None})
        tr = e.track
        if tr is None:
            p["ancora"] = None
            return p
        q, st = e._q, e.status()
        pos = q[0][0] if q and not e.ended else e.pos
        segs = segmentos(q, self.curvas.get(id(e._deck)), self.sim.desde) if st == "playing" else []
        p["ancora"] = {"faixa": tr["id"], "pos": float(pos), "t": ms(u), "taxa": SR, "anda": st == "playing",
                       "segmentos": segs}
        return p

    def olha(self, u, reconexao=False):
        self.olhadas += 1
        p = self.projecao(u)
        ev = "inicio" if self.pub is None else "reconexao" if reconexao else self.diferenca(p, u)
        if ev is None:
            return
        self.rev += 1
        origem = ev if ev in ("inicio", "reconexao") else "mudanca"
        self.pub = (p, u)
        self.msgs.append({"evento": ev, "msg": {"protocolo": 1, "tipo": "estado", "sessao": SESSAO, "rev": self.rev,
                                                "origem": origem, "agora": ms(u), "estado": p}})

    def pulso(self, u):
        self.msgs.append({"evento": "pulso", "msg": {"protocolo": 1, "tipo": "pulso", "sessao": SESSAO,
                                                     "rev": self.rev, "agora": ms(u)}})

    def diferenca(self, p, u):
        velho, u0 = self.pub
        if (velho["faixa"] or {}).get("id") != (p["faixa"] or {}).get("id"):
            return "troca"
        if velho["status"] != p["status"]:
            return EVENTO_DO_STATUS[p["status"]]
        if {k: v for k, v in velho.items() if k != "ancora"} != {k: v for k, v in p.items() if k != "ancora"}:
            return "projecao"
        a = velho["ancora"]
        if a is None:
            return None
        adiante = avanca(a, u - u0)
        if not equivalentes(adiante, p["ancora"]):
            return "mapa"
        if len(adiante["segmentos"]) < len(a["segmentos"]):
            return "fronteira"
        return None


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
    e.pronto_falhou = None
    e._registra_fim = lambda *a, **k: None  # o registro do fim grava em logs/: fora daqui
    return e


class Sim:
    """O callback de saida sem som: as linhas do _mixa que viram o prato e consomem a fila (o _tira de verdade), de
    BLOCO em BLOCO. Guarda o mapa de amostras: (amostra de saida, faixa, rotulo) de cada pedaco consumido."""

    def __init__(self, e):
        self.e, self.u, self.mapa, self.desde, self.virada = e, 0, [], 0, None

    def vira(self):
        e = self.e
        if e._pronto is not None and e.track is not None and not e.paused:
            fim_deste = not e._q and e._eof_gen == e._gen
            if (e._virar_em is not None and e.pos >= e._virar_em) or (fim_deste and e._pronto.q):
                e._vira()
                self.desde, self.virada = 0, self.u

    def consome(self):
        e, item = self.e, None
        if e.track is not None and not e.paused:
            with e._qlock:
                item = e._tira(e._q, BLOCO)
            if not item and e._eof_gen == e._gen:
                e.ended = True
        u = self.u
        for t0, s in item or ():
            self.mapa.append((u, e.track["id"], float(t0)))
            u += len(s)
            self.desde += len(s)
        if item:
            e.pos = item[-1][0] + len(item[-1][1]) / SR
        self.u += BLOCO


def _roda(e, sim, prod, ate_s, eventos=(), reconexoes=(), pulsos=False):
    """Roda o cenario ate ate_s de saida: em cada bloco, os eventos (fn(u) que devolvem True quando agiram), a virada
    do callback, o produtor olha o prato (e a reconexao, quando o gatilho manda) e o callback consome."""
    eventos, reconexoes = list(eventos), list(reconexoes)
    while sim.u < ate_s * SR:
        for ev in list(eventos):
            if ev(sim.u):
                eventos.remove(ev)
        sim.vira()
        prod.olha(sim.u)
        for r in list(reconexoes):
            if r(sim.u):
                reconexoes.remove(r)
                prod.olha(sim.u, reconexao=True)
        if pulsos and sim.u % SR == 0 and sim.u:
            prod.pulso(sim.u)
        sim.consome()
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


def _curvas_dois(a, b, plano):
    """As curvas do plano aplicado: a rampa de saida (do t_r, n_ra amostras de 1 a sa, e sa ate o fim dos blocos
    esticados) e a entrada (o preenchimento, sb por n_sob, a volta a 1 em n_rampa, e 1)."""
    t_r, novos = plano["sai_q"]
    vis = plano["visor"]
    sa = float(vis["va"])
    n_ra = int(min(max(abs(sa - 1) / eng.RAMPA_TAXA, eng.RAMPA_MIN_S), eng.RAMPA_MAX_S) * SR)  # o do _plano_dois
    n_za = sum(len(x) for _, x in novos)
    n_sob, n_rampa = int(round(vis["sob"] * SR)), int(round(vis["rampa"] * SR))
    pad = sum(len(x) for _, x in plano["cabeca"]) - n_sob - n_rampa
    sb, k, ini = float(vis["vb"]), float(vis["k"]), float(vis["ini"])
    entrada = ([{"n": pad, "v": 1.0, "preenchimento": True}] if pad else []) + [
        {"n": n_sob, "v": sb, "pos": ini}, {"n": n_rampa, "v": _cos(1 + k, 1, n_rampa)}, {"n": None, "v": 1.0}]
    return {id(a): {"tipo": "saida", "t_r": float(t_r), "n": n_za,
                    "segmentos": [{"n": n_ra, "v": _cos(1, sa, n_ra)}, {"n": n_za - n_ra, "v": sa}]},
            id(b): {"tipo": "entrada", "segmentos": entrada}}, pad


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


def _aplica(e, a, b, em_s, plano_batida=None, patches=(), depois=None):
    """O evento que aplica a passagem pelo _mede de verdade em em_s: com plano_batida, o plano ja feito; depois, o que
    o PC guarda do plano aplicado (as curvas)."""
    def ev(u):
        if u < em_s * SR:
            return False
        if plano_batida is not None:
            e._plano_batida = lambda *x, **k: (plano_batida, None)
        with contextlib.ExitStack() as pilha:
            for p in patches:
                pilha.enter_context(p)
            pilha.enter_context(contextlib.redirect_stderr(io.StringIO()))
            e._mede(a, b, a.track)
        assert e._virar_em is not None, "o _mede nao aplicou o plano"
        if depois is not None:
            depois()
        return True
    return ev


def _na_curva(sim, e, deck, curva, fracao):
    """O gatilho de reconexao: o prato e o deck e ja consumiu a fracao do meio cosseno da curva."""
    def ev(u):
        if e._deck is not deck:
            return False
        segs = segmentos(e._q, curva, sim.desde)
        return bool(segs) and isinstance(segs[0]["v"], dict) and segs[0]["v"]["fase"] >= fracao * segs[0]["v"]["total"]
    return ev


def cenario_passagem_dois():
    a, b = _deck("A", 0.0, 40.0), _deck("B", 0.0, 45.0)
    e = _motor(a, b)
    sim = Sim(e)
    plano = _plano_dois()
    novas, pad = _curvas_dois(a, b, plano)
    curvas = {}
    prod = Produtor(e, sim, curvas, _fila_de(b))
    msgs = _roda(e, sim, prod, 74.0, eventos=[_aplica(e, a, b, 1.0, plano_batida=plano,
                                                      depois=lambda: curvas.update(novas))],
                 reconexoes=[_na_curva(sim, e, a, novas[id(a)], 0.5), _na_curva(sim, e, b, novas[id(b)], 0.5)])
    return {"descricao": "A passagem com a rampa de saida (a que sai vai a sa antes da sobreposicao) e a entrada "
                         "esticada (sb, a volta a 1 em meio cosseno), com pad > 0 na virada e a origem dele presa em "
                         "zero; reconexao no meio das duas rampas.", "pad": pad}, msgs, sim.mapa


def cenario_passagem_cancelada():
    a, b = _deck("A", 0.0, 40.0), _deck("B", 0.0, 45.0)
    e = _motor(a, b)
    sim = Sim(e)
    plano = _plano_dois()
    novas, _ = _curvas_dois(a, b, plano)
    curvas = {}
    fila = {"ok": True}

    def lista(e_):
        return _fila_de(b)(e_) if fila["ok"] else []

    def cancela(u):
        if id(a) not in curvas:
            return False
        segs = segmentos(e._q, curvas[id(a)], sim.desde)
        if not (segs and isinstance(segs[0]["v"], dict) and segs[0]["v"]["fase"] >= segs[0]["v"]["total"] // 3):
            return False
        with e._qlock:  # a fila mudou: o servidor cancela a proxima, e os blocos esticados ficam na fila do prato
            e._cancela_passagem()
        fila["ok"] = False
        return True

    def no_fim_esticado(u):  # reconexao no trecho em sa, antes de acabarem os blocos esticados
        segs = segmentos(e._q, curvas[id(a)], sim.desde) if id(a) in curvas and e._q else []
        return len(segs) == 1 and not isinstance(segs[0]["v"], dict) and segs[0]["n"] < 2 * SR

    prod = Produtor(e, sim, curvas, lista)
    msgs = _roda(e, sim, prod, 42.0, eventos=[_aplica(e, a, b, 1.0, plano_batida=plano,
                                                      depois=lambda: curvas.update(novas)), cancela],
                 reconexoes=[_na_curva(sim, e, a, novas[id(a)], 0.6), no_fim_esticado])
    return {"descricao": "A passagem cancelada durante a rampa de saida, com a faixa no mesmo deck: os blocos "
                         "esticados ficam na fila e a ancora segue valendo; reconexao no meio da rampa e antes do fim "
                         "dos blocos esticados, e o fim natural congela a posicao."}, msgs, sim.mapa


def _patches_seco(golpe):
    """O _plano_batida de verdade no final seco com o corte no golpe e sem esticar (a proxima sem batida firme)."""
    g = [types.SimpleNamespace(periodo=0.5, fase=0.1, bpm=120.0, firme=True, motivo=""),
         types.SimpleNamespace(periodo=0.52, fase=0.1, bpm=115.4, firme=False, motivo="fixo no teste")]
    return [mock.patch.object(eng.batida, "medir", side_effect=g), mock.patch.object(eng, "_grade_rede", return_value=None),
            mock.patch.object(eng.batida, "fase", return_value=(0.0, 10.0)),
            mock.patch.object(eng, "_golpe_final", return_value=golpe),
            mock.patch.object(eng, "_batida_tocada", return_value=0.5),
            mock.patch.object(eng, "_eco_corte", return_value=None)]


def _cenario_seco(mudo):
    a, b = _deck("A", 18.0, 32.0), _deck("B", 0.0, 20.0, mudo=mudo)
    e = _motor(a, b, pos=18.0)
    sim = Sim(e)
    curvas = {}
    info = {}

    def aplica(u):
        if u < 0.5 * SR or not _aplica(e, a, b, 0.5, patches=_patches_seco(31.6037))(u):
            return False
        cab = b.q[0]  # o preenchimento: um bloco so, com o rotulo preso em zero
        pad = len(cab[1])
        ini = b.q[1][0]
        curvas[id(b)] = {"tipo": "entrada", "segmentos": [{"n": pad, "v": 1.0, "preenchimento": True},
                                                          {"n": None, "v": 1.0, "pos": float(ini)}]}
        info.update(pad=pad, ini=float(ini), origem=float(cab[0]))
        return True

    def no_preenchimento(u):  # reconexao entre a virada e o inicio efetivo da faixa de entrada
        return e._deck is b and BLOCO < sim.desde < info["pad"]

    prod = Produtor(e, sim, curvas, _fila_de(b))
    msgs = _roda(e, sim, prod, 16.0, eventos=[aplica], reconexoes=[no_preenchimento])
    return info, msgs, sim.mapa


def cenario_final_seco():
    info, msgs, mapa = _cenario_seco(0.0)
    info["descricao"] = ("O final seco no tempo sem estiramento, com o corte no golpe: a proxima entra depois de um pad "
                         "maior que um bloco, com a origem dele (ini - pad) presa em zero; reconexao entre a virada e o "
                         "inicio efetivo.")
    return info, msgs, mapa


def cenario_final_seco_sem_limite():
    info, msgs, mapa = _cenario_seco(1.0)
    info["descricao"] = ("O mesmo final seco, com a proxima comecando em 1 s (o silencio do comeco dela): a origem do "
                         "pad fica acima de zero.")
    return info, msgs, mapa


def cenario_buffering():
    a = _deck("A", 10.0, 11.0, fim=False)
    e = _motor(a, pos=10.0)
    sim = Sim(e)

    def chega(u):  # o stream volta: os blocos de 11 s em diante
        if u < 2.0 * SR:
            return False
        with e._qlock:
            a.q.extend(_deck("A", 11.0, 16.0, fim=False).q)
        return True

    def pausa(u):
        if u < 3.0 * SR:
            return False
        e.paused = True
        return True

    def retoma(u):
        if u < 3.5 * SR:
            return False
        e.paused = False
        return True

    prod = Produtor(e, sim, {}, lambda e_: [])
    msgs = _roda(e, sim, prod, 5.0, eventos=[chega, pausa, retoma])
    return {"descricao": "O stream que para (buffering congela a posicao), a retomada depois do buffering, a pausa e a "
                         "retomada."}, msgs, sim.mapa


def cenario_repetir():
    a = _deck("A", 7.0, 10.0)
    a.q.extend(_deck("A", 0.0, 3.0).q)  # o leitor com o Repetir: depois do fim, a volta do comeco no mesmo deck
    a.track["duration"] = 10.0
    e = _motor(a, pos=7.0)
    e.loop = True
    sim = Sim(e)
    prod = Produtor(e, sim, {}, lambda e_: [])
    msgs = _roda(e, sim, prod, 5.0)
    return {"descricao": "A volta do Repetir: a ancora nova no primeiro bloco da volta, com a faixa e o deck iguais."}, \
        msgs, sim.mapa


def cenario_fim_natural():
    a = _deck("A", 8.0, 10.0)
    e = _motor(a, pos=8.0)
    sim = Sim(e)
    prod = Produtor(e, sim, {}, lambda e_: [])
    msgs = _roda(e, sim, prod, 5.0, pulsos=True)
    return {"descricao": "O fim natural: a ancora congela na posicao final; os ticks seguem e o rev fica, com o pulso "
                         "repetindo o rev de 1 em 1 s."}, msgs, sim.mapa


CENARIOS = {"passagem-dois": cenario_passagem_dois, "passagem-cancelada": cenario_passagem_cancelada,
            "final-seco": cenario_final_seco, "final-seco-sem-limite": cenario_final_seco_sem_limite,
            "buffering": cenario_buffering, "repetir": cenario_repetir, "fim-natural": cenario_fim_natural}


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
            (_estado(3, T0_MS, _proj(anc=anc)), 4000.0, 30.0, "a foto guardada no relay, entregue 4 s depois a quem "
                                                               "conectou"),
            (_pulso(3, T0_MS + 4500.0), 0.0, 25.0, "o pulso, mais rapido: o relogio melhora"),
            (_estado(4, T0_MS + 6000.0, _proj(anc=_anc(16.0, T0_MS + 6000.0))), 0.0, 400.0, "a foto atrasada na rede: o "
                                                                                           "relogio fica com o atraso do pulso"),
            (_pulso(4, T0_MS + 7000.0), 0.0, 20.0, "o pulso seguinte corrige")):
        if retido:
            msg = dict(msg, retido_ms=retido)
        chegada = msg["agora"] + desvio + retido + transito
        passos.append({"chega_ms": chegada, "transito_ms": transito, "nota": nota, "msg": msg})
    return {"descricao": "O relogio do PC visto por quem recebe: o desvio e o menor (chegada - agora - retido_ms).",
            "desvio_real_ms": desvio, "entregas": passos}


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
    "caps": {"papel": "remoto", "rotas": ["POST /api/play"]}, "mock": True}


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
            ("pausado com a ancora andando", lambda m: m["estado"].update(status="paused")),
            ("outra taxa", lambda m: m["estado"]["ancora"].update(taxa=44100)),
            ("velocidade zero", lambda m: m["estado"]["ancora"].update(segmentos=[{"n": None, "v": 0}])),
            ("segmento de zero amostras", lambda m: m["estado"]["ancora"].update(segmentos=[{"n": 0, "v": 1.0}])),
            ("cosseno sem a fase", lambda m: m["estado"]["ancora"].update(
                segmentos=[{"n": 10, "v": {"de": 1.0, "ate": 1.01, "total": 10}}])),
            ("posicao negativa", lambda m: m["estado"]["ancora"].update(pos=-0.01)),
            ("rev zero", lambda m: m.update(rev=0)),
            ("origem fora da lista", lambda m: m.update(origem="tick")),
            ("capacidade fora do vocabulario", lambda m: m["estado"].update(capacidades=["parar"])),
            ("volume fora de 0 a 1", lambda m: m["estado"].update(vol=1.2)),
            ("capa sem https", lambda m: m["estado"]["faixa"].update(thumb="http://x/y.jpg"))):
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
        erros = [e.message for e in self.val[nome].iter_errors(msg)]
        self.assertEqual(erros, [], f"{nome}: {json.dumps(msg, ensure_ascii=False)[:300]}")

    def _invalido(self, nome, msg, por_que):
        self.assertFalse(self.val[nome].is_valid(msg), f"{nome} aceitou: {por_que}")

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
        campos = set(docs["resultado"]["$defs"]["dados"]["properties"])
        for d in MAPA["dados"].values():
            self.assertTrue(set(d) <= campos)

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
        texto = json.dumps(f["remota"])
        for fora in ('"microfone"', '"devices"', '"active_devices"', '"atualizacao"', '"mic_mute"', '"error"', '"caps"',
                     '"file"', '"job"', '"url"', '"last_pos"', "Aparelho", "sem-tls"):
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
        # o produtor de agora publica os mesmos estados, pelos mesmos motivos, que a fixture (rode --gera se mudou)
        self.assertEqual([(m["evento"], m["msg"]["tipo"], m["msg"]["rev"]) for m in msgs_agora],
                         [(m["evento"], m["msg"]["tipo"], m["msg"]["rev"]) for m in fixture["mensagens"]],
                         f"{nome}: os estados mudaram; rode python dev/testa_protocolo.py --gera")
        msgs = [m for m in fixture["mensagens"] if m["msg"]["tipo"] == "estado"]
        us = [u for u, _, _ in mapa]
        conferidos = 0
        for i, m in enumerate(msgs):
            est = m["msg"]["estado"]
            anc = est["ancora"]
            if anc is None:
                continue
            self.assertEqual(anc["faixa"], est["faixa"]["id"])
            fim = next((x["msg"]["agora"] for x in msgs[i + 1:] if x["evento"] not in CONTINUA), math.inf)
            u_ini = round((m["msg"]["agora"] - T0_MS) * POR_MS)
            u_fim = math.inf if fim == math.inf else round((fim - T0_MS) * POR_MS)
            for u, faixa, rotulo in mapa[bisect.bisect_left(us, u_ini):]:
                if u >= u_fim:
                    break
                if faixa != anc["faixa"]:
                    continue
                p = posicao(anc, ms(u))
                self.assertLessEqual(abs(p - rotulo), TOL_S,
                                     f"{nome}: rev {m['msg']['rev']} ({m['evento']}) na amostra {u}: {p} e o motor "
                                     f"{rotulo}")
                conferidos += 1
        self.assertGreater(conferidos, 100)
        return info, fixture["mensagens"], mapa

    @staticmethod
    def primeiro(m):
        segs = m["msg"]["estado"]["ancora"]["segmentos"] if m["msg"]["tipo"] == "estado" and \
            m["msg"]["estado"]["ancora"] else []
        return segs[0] if segs else None

    def test_passagem_dois(self):
        info, msgs, _ = self.confere("passagem-dois")
        self.assertTrue(0 < info["pad"] < BLOCO)
        cos = [(m["evento"], m["msg"]["estado"]["ancora"]["faixa"], s["v"]["fase"], s["v"]["total"])
               for m in msgs if (s := self.primeiro(m)) and isinstance(s["v"], dict)]
        for faixa in ("A", "B"):  # o comeco (a fronteira no primeiro bloco dele), o meio (a reconexao) e o fim
            self.assertIn(("fronteira", faixa), [(e, f) for e, f, fase, _ in cos if fase < BLOCO], faixa)
            self.assertTrue(any(e == "reconexao" and f == faixa and 0.4 < fase / n < 0.9 for e, f, fase, n in cos), faixa)
        fins = [m for m in msgs if m["evento"] == "fronteira" and (s := self.primeiro(m)) and not isinstance(s["v"], dict)]
        self.assertTrue(any(m["msg"]["estado"]["ancora"]["faixa"] == "A" and self.primeiro(m)["v"] > 1 for m in fins))
        self.assertTrue(any(m["msg"]["estado"]["ancora"]["faixa"] == "B" and self.primeiro(m)["v"] == 1.0
                            and self.primeiro(m)["n"] is None for m in fins))
        self.assertIn("troca", [m["evento"] for m in msgs])

    def test_passagem_cancelada(self):
        _, msgs, _ = self.confere("passagem-cancelada")
        ev = [m["evento"] for m in msgs]
        self.assertIn("projecao", ev)  # o cancelamento tirou a proxima da fila, e a ancora seguiu
        rec = [self.primeiro(m) for m in msgs if m["evento"] == "reconexao"]
        self.assertTrue(isinstance(rec[0]["v"], dict) and rec[0]["v"]["fase"] > 0)   # no meio da rampa
        self.assertTrue(not isinstance(rec[1]["v"], dict) and rec[1]["v"] > 1)       # no trecho em sa
        self.assertEqual(ev[-1], "fim")
        self.assertNotIn("troca", ev)

    def _seco(self, nome):
        info, msgs, mapa = self.confere(nome)
        self.assertGreater(info["pad"], BLOCO)
        rec = [m for m in msgs if m["evento"] == "reconexao"]
        self.assertEqual(len(rec), 1)
        s = self.primeiro(rec[0])
        self.assertTrue(s.get("preenchimento"))
        # o mapa do motor na fronteira do inicio efetivo: o rotulo do primeiro bloco depois do preenchimento e o ini
        virada = next(u for u, f, _ in mapa if f == "B")
        na_fronteira = [r for u, f, r in mapa if f == "B" and u == virada + info["pad"]]
        self.assertEqual(na_fronteira, [info["ini"]])
        return info

    def test_final_seco(self):
        info = self._seco("final-seco")
        self.assertEqual(info["origem"], 0.0)  # ini - pad abaixo de zero: preso em zero, como o rotulo do motor

    def test_final_seco_sem_limite(self):
        info = self._seco("final-seco-sem-limite")
        self.assertAlmostEqual(info["origem"], info["ini"] - info["pad"] / SR, places=9)

    def test_buffering(self):
        _, msgs, _ = self.confere("buffering")
        self.assertEqual([m["evento"] for m in msgs], ["inicio", "buffering", "retomada", "pausa", "retomada"])
        b = msgs[1]["msg"]["estado"]["ancora"]
        self.assertEqual((b["anda"], b["pos"]), (False, 11.0))
        self.assertEqual(msgs[2]["msg"]["estado"]["ancora"]["pos"], 11.0)

    def test_repetir(self):
        _, msgs, mapa = self.confere("repetir")
        self.assertEqual([m["evento"] for m in msgs], ["inicio", "mapa"])
        volta = msgs[1]["msg"]
        u_volta = next(u for u, _, r in mapa if r == 0.0)
        self.assertEqual(round((volta["agora"] - T0_MS) * POR_MS), u_volta)  # no primeiro bloco da volta
        self.assertEqual((volta["estado"]["ancora"]["pos"], volta["estado"]["faixa"]["id"]), (0.0, "A"))

    def test_fim_natural_e_rev_estavel(self):
        _, msgs, _ = self.confere("fim-natural")
        estados = [m for m in msgs if m["msg"]["tipo"] == "estado"]
        self.assertEqual([m["evento"] for m in estados], ["inicio", "fim"])
        fim = estados[1]["msg"]["estado"]
        self.assertEqual(fim["ancora"]["anda"], False)
        self.assertAlmostEqual(fim["ancora"]["pos"], 10.0, places=9)
        pulsos = [m["msg"] for m in msgs if m["msg"]["tipo"] == "pulso"]
        self.assertGreaterEqual(len(pulsos), 4)
        self.assertEqual({p["rev"] for p in pulsos if p["agora"] > estados[1]["msg"]["agora"]}, {2})

    def test_rev_estavel_entre_ticks(self):
        for nome in CENARIOS:
            info, msgs, mapa = self.corre(nome)
            estados = [m for m in msgs if m["msg"]["tipo"] == "estado"]
            self.assertEqual([m["msg"]["rev"] for m in estados], list(range(1, len(estados) + 1)))
            # o produtor olhou o prato a cada bloco e so publicou nas mudancas
            self.assertLess(len(estados), 30, nome)


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
