r"""Confere a pasta de dados do servidor no --mock (#117, pastas.dados_do_mock): sem --data-dir, uma pasta temporaria
nova, que sai quando o processo fecha; a pasta de quem usa (a de hoje e a de antes da troca de nome), nem pedida; outra
pasta, ela mesma. O download de mentira do --mock copia o disco mais curto com outro nome, e na pasta de quem usa isso
virava disco falso na prateleira. A LOCALAPPDATA e temporaria: nada de verdade e tocado.

E que o --mock nao vai a rede sozinho (#128), pelo servidor de verdade: so com as bibliotecas dele (a esteira roda este
teste antes de instalar, e essa parte fica de fora). O servidor sobe pelo dev/so_mock.py, so da biblioteca padrao: a
porta nunca e a 8799 nem uma em que alguem ja responde, e cada pedido, o /api/shutdown inclusive, so vai enquanto o
filho esta vivo e responde como --mock; se nao, so ele sai, pelo handle.

E quem pode chamar cada rota (permissao.py): toda rota do server.py esta na tabela, e a tabela so tem rotas que existem
(pelo fonte, sem as bibliotecas; pelo roteador do aiohttp, com elas). Com as bibliotecas, o guard de verdade, pedido a
pedido: o PC, o celular antes e depois de parear, o remoto com o token e sem ele, a rota com parametro, o HEAD, a
desconexao no SSE e o caps de cada papel, e o SSE com dois PCs ligados: o snapshot montado uma vez por volta para os
dois, e o motor virando entre o state e o tick com o envio de um deles suspenso (cada posicao e da faixa entregue
naquela volta, e o outro segue recebendo). E, no mesmo --mock do teste sem rede, o PC com tudo (o /api/volume, o
/api/abaixa voltando sozinho no prazo, o /api/sinal, a recarga dos efeitos) e a rede de casa recusada onde deve, com os
pedidos saindo do 127.0.0.2: o --mock so escuta no 127.0.0.1, e o servidor olha o endereco de quem conecta.

    python dev/testa_mock.py

Sai 1 se algo falha."""
import asyncio
import contextlib
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.error
import wave
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import so_mock

sys.path.insert(0, str(RAIZ))
import permissao as perm

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


# o vocabulario do remoto, fechado: abrir um comando para ele e mudar aqui e na tabela
VOCABULARIO = {("GET", "/api/state"), ("GET", "/api/events"), ("POST", "/api/play"), ("POST", "/api/queue"),
               ("POST", "/api/queue/play"), ("POST", "/api/next"), ("POST", "/api/pause"), ("POST", "/api/resume"),
               ("DELETE", "/api/queue/{qid}"), ("POST", "/api/queue/move"), ("POST", "/api/volume"),
               ("POST", "/api/abaixa"), ("POST", "/api/sinal")}


def rotas_do_fonte():
    """As rotas do server.py pelo fonte (sem o aiohttp), pela arvore do ast: (metodo, rota canonica), e os registros que
    nao deu para ler. O {nome:regex} vira {nome}, como no canonical do aiohttp, e o static do /t/ vira o "/t" dele. Todo
    registro de rota conta: o @r.<metodo>(...), o @r.route(...), o router.add_<algo>(...) e o web.<metodo>(...) de uma
    lista de rotas; o que nao for um caminho literal (ou uma constante do modulo mais um literal) volta como ilegivel."""
    import ast
    arvore = ast.parse((RAIZ / "server.py").read_text(encoding="utf-8"))
    consts = {n.targets[0].id: n.value.value for n in arvore.body if isinstance(n, ast.Assign) and len(n.targets) == 1
              and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)
              and isinstance(n.value.value, str)}
    metodos = {"get", "post", "put", "patch", "delete", "head", "options", "view"}

    def caminho(no):
        if isinstance(no, ast.Constant) and isinstance(no.value, str):
            return no.value
        if isinstance(no, ast.Name) and no.id in consts:
            return consts[no.id]
        if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Add):
            a, b = caminho(no.left), caminho(no.right)
            return None if a is None or b is None else a + b
        return None

    # o r.<metodo>(...) so como decorador: fora dele, r e o nome de muito dicionario (r.get("title"))
    decoradores = {id(d) for f in ast.walk(arvore) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                   for d in f.decorator_list}
    out, ilegiveis = set(), []
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)):
            continue
        nome, dono = no.func.attr, no.func.value
        dono_nome = dono.id if isinstance(dono, ast.Name) else getattr(dono, "attr", None)
        estatico = nome == "add_static" or (nome == "static" and dono_nome in ("r", "web"))
        if estatico or (dono_nome == "router" and nome.startswith("add_") and nome != "add_routes"):
            c = caminho(no.args[0]) if no.args else None
            if estatico and c is not None:
                out.add(("GET", c.rstrip("/")))
            else:
                ilegiveis.append(f"linha {no.lineno}: {ast.unparse(no)[:80]}")
        elif ((dono_nome == "r" and id(no) in decoradores) or dono_nome == "web") and (nome in metodos
                                                                                       or nome == "route"):
            args = list(no.args)
            metodo = nome.upper()
            if nome == "route":
                m = caminho(args.pop(0)) if args else None
                metodo = m.upper() if m else None
            c = caminho(args[0]) if args else None
            if metodo is None or c is None or metodo == "VIEW":
                ilegiveis.append(f"linha {no.lineno}: {ast.unparse(no)[:80]}")
            else:
                out.add((metodo, re.sub(r"\{(\w+):[^}]*\}", r"{\1}", c)))
    return out, ilegiveis


TRACK_FIELDS = {"title", "channel", "thumb", "duration"}
BAD_TRACK_BODIES = ({"youtube_id": "dQw4w9WgXcQ", "title": "a\ud800b"},
                    {"youtube_id": "dQw4w9WgXcQ", "channel": "\udfff"},
                    {"youtube_id": "dQw4w9WgXcQ", "thumb": "https://i.ytimg.com/\ud800"},
                    {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&x=\ud800"},
                    {"youtube_id": "dQw4w9WgXcQ", "title": ["x"]}, {"youtube_id": "dQw4w9WgXcQ", "channel": 3},
                    {"youtube_id": "dQw4w9WgXcQ", "thumb": {"url": "x"}},
                    {"youtube_id": "dQw4w9WgXcQ", "duration": "x"}, {"youtube_id": "dQw4w9WgXcQ", "duration": True},
                    {"youtube_id": "dQw4w9WgXcQ", "duration": -1}, {"youtube_id": "dQw4w9WgXcQ", "duration": 10 ** 7},
                    {"youtube_id": "dQw4w9WgXcQ", "duration": 1e9}, {"youtube_id": "dQw4w9WgXcQ", "duration": 10 ** 400},
                    {"youtube_id": "dQw4w9WgXcQ", "duration": float("inf")},
                    {"youtube_id": "dQw4w9WgXcQ", "duration": float("nan")}, {"url": ["v=dQw4w9WgXcQ"]})
TRACK_ROUTES = ((("POST", "/api/queue"), {}, TRACK_FIELDS), (("POST", "/api/library"), {"play": True}, TRACK_FIELDS),
                (("POST", "/api/library"), {}, {"title"}))
RENAME_ROUTE = ("PATCH", "/api/library/{iid}")
EMPTY_TARGET_TEXT = {"/api/queue": "Send the id of a record on the shelf, a video id or a YouTube link.",
                     "/api/library": "Send a YouTube link, a video ID, or search text."}
BODY_READERS = {"read", "text", "json", "post", "multipart", "content"}
ROUTE_REGISTRARS = {"get", "post", "put", "patch", "delete", "head", "options", "view", "route"}


class PassedTheCheck(Exception):
    pass


def passed_the_check(*_):
    raise PassedTheCheck


def bad_bodies_for(extra, fields):
    return [{**c, **extra} for c in BAD_TRACK_BODIES if set(c) - {"youtube_id", "url"} <= set(fields)]


def route_handler_names():
    import ast
    tree = ast.parse((RAIZ / "server.py").read_text(encoding="utf-8"))
    return {fn.name for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name)
                    and d.func.value.id == "r" for d in fn.decorator_list)}


def track_field_routes(sources=None):
    import ast
    if sources is None:
        sources = {name: (RAIZ / f"{name}.py").read_text(encoding="utf-8") for name in ("server", "comandos")}
    defs = {}
    module_of = {}
    parent = {}
    decorated = []
    trees = [(name, ast.parse(source)) for name, source in sources.items()]

    def positional(fn):
        return [a.arg for a in fn.args.posonlyargs + fn.args.args]
    for name, tree in trees:
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent[id(child)] = node
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_method = positional(node)[:1] == ["self"]
                defs.setdefault((name, node.name, is_method), node)
                module_of[id(node)] = name
                if name == "server" and node.decorator_list:
                    decorated.append(node)

    def callee(module, call):
        f = call.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id == "cmd":
                return defs.get(("comandos", f.attr, False)), 0
            if f.value.id in ("A", "self"):
                return defs.get(("server", f.attr, True)), 1
            if f.value.id == "App":
                return defs.get(("server", f.attr, True)), 0
        if isinstance(f, ast.Name):
            return defs.get((module, f.id, False)), 0
        return None, 0

    def parameter_for(fn, call, node):
        target, before = callee(module_of[id(fn)], call)
        params = positional(target) if target else []
        pos = before + call.args.index(node) if node in call.args else \
            next((params.index(k.arg) for k in call.keywords if k.value is node and k.arg in params), None)
        if target is None or pos is None or pos >= len(params):
            return None, None
        return target, params[pos]

    def loop_keys(fn, node, name):
        a = parent.get(id(node))
        while a is not None and a is not fn:
            gens = (a.generators if isinstance(a, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
                    else [a] if isinstance(a, ast.For) else [])
            loop = next((g for g in gens if isinstance(g.target, ast.Name) and g.target.id == name), None)
            if loop is not None:
                elts = loop.iter.elts if isinstance(loop.iter, (ast.Tuple, ast.List)) else [None]
                ok = all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elts)
                return {e.value for e in elts} if ok else None
            a = parent.get(id(a))
        return None

    def loads_of(fn, var):
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and node.id == var and isinstance(node.ctx, ast.Load):
                p = parent[id(node)]
                yield node, p, f"{fn.name}:{node.lineno} {ast.unparse(parent.get(id(p), p))[:70]}"

    def passed_to(p, node):
        return isinstance(p, ast.Call) and (node in p.args or any(k.value is node for k in p.keywords))

    def prepares_a_stream_response(fn, call):
        f = call.func
        if not (isinstance(f, ast.Attribute) and f.attr == "prepare" and isinstance(f.value, ast.Name)):
            return False
        stores = [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == f.value.id
                  and not isinstance(n.ctx, ast.Load)]
        assign = parent.get(id(stores[0])) if len(stores) == 1 else None
        return (isinstance(assign, ast.Assign) and assign.targets == [stores[0]] and isinstance(assign.value, ast.Call)
                and ast.unparse(assign.value.func) == "web.StreamResponse")

    def follow_body(fn, var, path, read, lost):
        if (id(fn), var) in [(id(f), v) for f, v in path]:
            return
        path = path + [(fn, var)]
        names = {c.value for c in ast.walk(fn) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        for node, p, where in loads_of(fn, var):
            key = None
            if isinstance(p, ast.Attribute) and p.attr == "get" and isinstance(parent.get(id(p)), ast.Call) \
                    and parent[id(p)].func is p and parent[id(p)].args:
                key = parent[id(p)].args[0]
            elif isinstance(p, ast.Subscript) and p.value is node:
                key = p.slice
            elif (isinstance(p, ast.Compare) and len(p.ops) == 1 and isinstance(p.ops[0], (ast.In, ast.NotIn))
                  and p.comparators[0] is node):
                key = p.left
            if key is not None:
                known = ({key.value} if isinstance(key, ast.Constant)
                         else loop_keys(fn, node, key.id) if isinstance(key, ast.Name) else None)
                if known is not None:
                    if known & TRACK_FIELDS:
                        read.append([f.name for f, _ in path])
                elif names & TRACK_FIELDS:
                    read.append([f.name for f, _ in path])
                else:
                    lost.append(where)
            elif passed_to(p, node):
                target, param = parameter_for(fn, p, node)
                if target is None:
                    lost.append(where)
                else:
                    follow_body(target, param, path, read, lost)
            else:
                lost.append(where)

    def follow_request(fn, var, path, lost):
        if (id(fn), var) in [(id(f), v) for f, v in path]:
            return
        in_route = not path
        path = path + [(fn, var)]
        for node, p, where in loads_of(fn, var):
            if isinstance(p, ast.Attribute):
                if p.attr in BODY_READERS:
                    lost.append(where)
            elif isinstance(p, ast.Subscript) and p.value is node:
                continue
            elif passed_to(p, node):
                if isinstance(p.func, ast.Name) and p.func.id == "body" and module_of[id(fn)] == "server":
                    if not in_route:
                        lost.append(where)
                    continue
                target, param = parameter_for(fn, p, node)
                if target is not None:
                    follow_request(target, param, path, lost)
                elif not prepares_a_stream_response(fn, p):
                    lost.append(where)
            else:
                lost.append(where)

    found, lost_by_route = {}, {}
    for fn in decorated:
        routes = [(d.func.attr.upper(),
                   d.args[0].value if isinstance(d.args[0], ast.Constant) else ast.unparse(d.args[0]))
                  for d in fn.decorator_list
                  if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name)
                  and d.func.value.id == "r" and d.args]
        kept = [n for n in ast.walk(fn) if isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Await)
                and isinstance(n.value.value, ast.Call) and isinstance(n.value.value.func, ast.Name)
                and n.value.value.func.id == "body"]
        bodies = [n.targets[0].id for n in kept]
        lost_here = [f"{fn.name}:{n.lineno} {ast.unparse(n)[:70]}" for n in ast.walk(fn)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "body"
                     and not any(n is a.value.value for a in kept)]
        for route in routes:
            read, lost = [], list(lost_here)
            for var in bodies:
                follow_body(fn, var, [], read, lost)
            if positional(fn):
                follow_request(fn, positional(fn)[0], [], lost)
            if read:
                found[route] = read[0]
            if lost:
                lost_by_route[route] = lost
    for name, tree in trees:
        for node in ast.walk(tree):
            if name == "server" and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                owner_name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", None)
                if ((owner_name == "web" and node.func.attr in ROUTE_REGISTRARS)
                        or (owner_name == "router" and node.func.attr.startswith("add_")
                            and node.func.attr != "add_static")):
                    lost_by_route[("registered", ast.unparse(node)[:70])] = ["a route registered outside @r.<method>"]
    return found, lost_by_route


TRACKER_CASES = (('b = await body(request)\n    return b.get("title")', "found"),
                 ('b = await body(request)\n    return b["channel"]', "found"),
                 ('b = await body(request)\n    return "title" in b', "found"),
                 ('b = await body(request)\n    p = dict(b)\n    return p.get("title")', "lost"),
                 ('b = await body(request)\n    p = b\n    return p.get("title")', "lost"),
                 ('b = p = await body(request)\n    return b.get("title")', "lost"),
                 ('p, = [await body(request)]\n    return p.get("title")', "lost"),
                 ('b = await body(request)\n    return cmd.x(A, b)', "found"),
                 ('b = await body(request)\n    return A.keep(b)', "found"),
                 ('b = await body(request)\n    return cmd.y(A, b)', "lost"),
                 ('b = await body(request)\n    return other.f(b)', "lost"),
                 ('b = await body(request)\n    return [b[k] for k in ("vol", "title")]', "found"),
                 ('b = await body(request)\n    return [b[k] for k in KEYS]', "lost"),
                 ('b = await body(request)\n    return b.get("vol")', "none"),
                 ('return await request.json()', "lost"),
                 ('return await request.post()', "lost"),
                 ('return await request.text()', "lost"),
                 ('return await request.read()', "lost"),
                 ('return await request.multipart()', "lost"),
                 ('return await request.content.read()', "lost"),
                 ('return await reads(request)', "lost"),
                 ('return await via(request)', "lost"),
                 ('q = request\n    return await q.json()', "lost"),
                 ('return other.parse(request)', "lost"),
                 ('await other.prepare(request)', "lost"),
                 ('resp = make()\n    await resp.prepare(request)', "lost"),
                 ('resp = web.StreamResponse()\n    resp: object = make()\n    await resp.prepare(request)', "lost"),
                 ('resp = web.StreamResponse()\n    for resp in make():\n        pass\n    await resp.prepare(request)',
                  "lost"),
                 ('resp = web.StreamResponse()\n    await resp.prepare(request)\n    return request.match_info["iid"]',
                  "none"))
TRACKER_ROUTE_SHAPE_CASES = (('@r.post("/api/x")', "request, /", 'return await request.json()', "lost"),
                             ('@r.post("/api/x")', "request, /", 'b = await body(request)\n    return b.get("title")',
                              "found"),
                             ('@r.get(PREFIX + "{rest:(?:/.*)?}")', "request", 'return await request.json()', "lost"),
                             ("", "request", 'return await request.json()\nroutes = [web.post("/api/x", x)]', "lost"),
                             ("", "request", 'return await request.json()\napp.router.add_post("/api/x", x)', "lost"))


def check_track_field_routes():
    print("--- every route that takes title, channel, thumb or duration (by the source)")
    found, lost = track_field_routes()
    covered = {r for r, _, _ in TRACK_ROUTES} | {RENAME_ROUTE}
    confere(("POST", "/api/queue") in found and ("POST", "/api/library") in found,
            f"the source search finds the queue and the shelf ({sorted(found)})")
    confere(set(found) == covered, f"every route whose body reaches a track field is in TRACK_ROUTES, which this "
            f"test sends the bad bodies to (not covered: {sorted(set(found) - covered)}; covered but no longer "
            f"found: {sorted(covered - set(found))}; the way: {found})")
    confere(not lost, f"the search follows the body of every route to the end, so none reads a track field "
            f"behind its back; a route reads its body only through body() ({lost})")
    base = ("import comandos as cmd\nasync def body(r): return {}\nasync def reads(r): return await r.json()\n"
            "async def via(r):\n    b = await body(r)\n    return b['title']\n"
            "class App:\n    def keep(self, b):\n        return b['thumb']\n")
    helpers = "def x(A, b):\n    return b['duration']\ndef y(A, b):\n    return list(b.items())\n"
    for decorator, params, route_body, expected in ([('@r.post("/api/x")', "request", *c) for c in TRACKER_CASES]
                                                    + list(TRACKER_ROUTE_SHAPE_CASES)):
        source = base + f'{decorator}\nasync def x({params}):\n    {route_body}\n'
        found, lost = track_field_routes({"server": source, "comandos": helpers})
        got = "lost" if lost else "found" if found else "none"
        confere(got == expected, f"the search on the route {decorator} x({params}): "
                f"{route_body.replace(chr(10) + '    ', '; ').replace(chr(10), '; ')}: {expected} ({got})")


def tabela():
    print("--- a tabela de quem pode cada rota (permissao.py)")
    rotas, ilegiveis = rotas_do_fonte()
    confere(len(rotas) > 50, f"o fonte do server.py tem as rotas ({len(rotas)})")
    confere(not ilegiveis, f"todo registro de rota do server.py tem metodo e caminho legiveis ({ilegiveis})")
    fora = sorted(rotas - set(perm.TABELA))
    confere(not fora, f"toda rota do server.py esta na tabela (fora: {fora})")
    sobra = sorted(set(perm.TABELA) - rotas)
    confere(not sobra, f"a tabela so tem rotas que existem (sobra: {sobra})")
    confere(all(p <= set(perm.PAPEIS) and "pc" in p for p in perm.TABELA.values()),
            "cada linha usa so os quatro papeis, e o PC pode todas")
    remoto = {k for k, p in perm.TABELA.items() if "remoto" in p}
    confere(remoto == VOCABULARIO, f"o remoto alcanca so o vocabulario dele (a mais: {sorted(remoto - VOCABULARIO)}, "
            f"a menos: {sorted(VOCABULARIO - remoto)})")
    confere(not any("publico" in p and "remoto" in p for p in perm.TABELA.values()),
            "o remoto nao usa as rotas livres (o pareamento)")
    livre_api = {k for k, p in perm.TABELA.items() if "publico" in p and k[1].startswith("/api/")}
    confere(livre_api == {("GET", "/api/themes"), ("POST", "/api/parear")},
            f"antes de parear, da API so o /api/themes e o /api/parear ({sorted(livre_api)})")
    confere(perm.papeis("POST", "/api/nao-existe") == perm.PC and perm.papeis("GET", None) == perm.PC,
            "rota fora da tabela (ou nenhuma) e so do PC")
    confere(perm.papeis("HEAD", "/api/state") == perm.papeis("GET", "/api/state"), "o HEAD vale como o GET")
    confere(perm.papeis("POST", "/api/effects/reload") == perm.PC, "a recarga dos efeitos e so do PC")
    confere(perm.OUT_OF_REPO and all(perm.TABELA.get(k) == perm.PC for k in perm.OUT_OF_REPO),
            f"the routes only the module from outside the repo calls are PC only ({sorted(perm.OUT_OF_REPO)})")
    r = perm.Remotos()
    t = r.abre()
    confere(len(t) >= 40 and r.vale(t) and not r.vale(t[:-1]) and not r.vale("") and not r.vale(None),
            "o token da sessao remota e longo e so ele vale")
    r.fecha(t)
    confere(not r.vale(t), "a sessao fechada, o token deixa de valer")


async def papeis_no_guard():
    """O guard do server.build de verdade, num app com o resto de mentira: cada papel em cada tipo de rota, e o SSE e o
    /api/state de verdade."""
    from unittest import mock

    from aiohttp import streams, web
    from aiohttp.test_utils import make_mocked_request

    with contextlib.redirect_stderr(io.StringIO()):  # o aviso das vozes do pedal, que nao sao deste teste
        import pareamento as par
        import server
    lan, porta, cel, pc = "192.168.0.10", 8799, "192.168.0.50", "127.0.0.1"
    print("--- o guard, papel por papel")
    with tempfile.TemporaryDirectory() as tmp:
        E = types.SimpleNamespace(pos=0.0, levels={}, vol=0.5)
        A = types.SimpleNamespace(engine=E, port=porta, lan_ip=lan, mock=True, closing=False, papel_local="pc",
                                  celulares=par.Pareamento(Path(tmp) / "celulares.json"), remotos=perm.Remotos(),
                                  metricas=types.SimpleNamespace(erro=lambda *a, **k: None),
                                  atualizacao=types.SimpleNamespace(ao_abrir=lambda: None),
                                  leitura=lambda: ({"status": "idle"}, 0.0), public_jobs=lambda: [],
                                  lib=types.SimpleNamespace(version=1, public=lambda: [],
                                                            get=lambda i: {"id": i} if i == "12345678901" else None,
                                                            by_youtube=lambda _: None),
                                  grava_cfg=lambda **k: None)
        app = server.build(A)
        A.enfileirar = lambda b, remoto=False: server.App.enfileirar(A, b, remoto)  # o de verdade: so recusa aqui
        guard = app.middlewares[0]
        reais = {(r.method, r.resource.canonical) for r in app.router.routes() if r.resource is not None}
        sem_head = {("GET" if m == "HEAD" else m, c) for m, c in reais}
        confere(sem_head == set(perm.TABELA), f"o roteador do aiohttp e a tabela tem as mesmas rotas (so no roteador: "
                f"{sorted(sem_head - set(perm.TABELA))}, so na tabela: {sorted(set(perm.TABELA) - sem_head)})")
        confere(("HEAD", "/api/state") in reais, "o roteador responde HEAD nas rotas GET")
        rota = {(r.method, r.resource.canonical): r.handler for r in app.router.routes() if r.resource is not None}
        dynamic = {r.handler.__name__ for r in app.router.routes()
                   if r.resource is not None and not isinstance(r.resource, web.StaticResource)}
        confere(dynamic <= route_handler_names(), f"every route of the aiohttp router has a handler the route tracker "
                f"follows, an @r.<method> function of server.py (not followed: {sorted(dynamic - route_handler_names())})")

        async def segue(req):  # a rota de verdade nao importa aqui: so se o guard deixou chegar nela
            return web.json_response({"ok": True, "chegou": True})

        async def manda(metodo, caminho, de=cel, cookie=None, token=None, corpo=None, handler=None, host=None,
                        origin=None, cookie_name=par.COOKIE):
            t = mock.Mock()
            t.get_extra_info.side_effect = lambda nome, d=None: (de, 50000) if nome == "peername" else d
            cab = {"Host": host or (f"{pc}:{porta}" if de == pc else f"{lan}:{porta}")}
            if cookie:
                cab["Cookie"] = f"{cookie_name}={cookie}"
            if origin:
                cab["Origin"] = origin
            if token is not None:
                cab[perm.REMOTO] = token
            carga = streams.EMPTY_PAYLOAD
            if corpo is not None:
                cab["Content-Type"] = "application/json"
                carga = streams.StreamReader(mock.Mock(_reading_paused=False), 2 ** 16, loop=asyncio.get_running_loop())
                carga.feed_data(json.dumps(corpo).encode("utf-8"))
                carga.feed_eof()
            req = make_mocked_request(metodo, caminho, headers=cab, transport=t, payload=carga, app=app)
            req._match_info = await app.router.resolve(req)  # a rota casada, como no servidor
            resp = await guard(req, handler or segue)
            corpo = getattr(resp, "body", None) if resp.content_type == "application/json" else None
            return resp, (json.loads(corpo) if corpo else {}), req

        async def status(*a, **k):
            resp, j, _ = await manda(*a, **k)
            return 200 if j.get("chegou") else resp.status

        # o PC: tudo, inclusive o que so ele pode
        for m, c in (("POST", "/api/effects/reload"), ("GET", "/api/pareamento"), ("POST", "/api/atualizacao/instalar"),
                     ("DELETE", "/api/pareamento/abc"), ("POST", "/api/play"), ("HEAD", "/api/metricas")):
            confere(await status(m, c, de=pc) == 200, f"o PC: {m} {c} passa")

        # antes de parear: o tema e o pareamento; o resto da API pede o codigo, e o que e do PC e 403
        for m, c in (("GET", "/t/ritmelli/"), ("GET", "/t/ritmelli/index.html"), ("GET", "/"), ("GET", "/api/themes"),
                     ("HEAD", "/api/themes"), ("HEAD", "/t/ritmelli/"), ("GET", server.TEMA_DE_ANTES + "/")):
            confere(await status(m, c) == 200, f"antes de parear: {m} {c} passa")
        resp, j, _ = await manda("GET", "/api/state")
        confere(resp.status == 401 and j.get("parear") and j.get("caps") == perm.caps("publico")
                and j.get("mock") is True,
                f"antes de parear, o /api/state e o 401 do pareamento, com o caps do pre-pareamento ({resp.status})")
        confere(j.get("caps", {}).get("rotas") == ["GET /api/themes", "POST /api/parear"],
                f"o caps do pre-pareamento: so o /api/themes e o /api/parear ({j.get('caps')})")
        confere(await status("HEAD", "/api/state") == 401, "antes de parear, o HEAD do /api/state tambem pede o codigo")
        confere(await status("POST", "/api/effects/reload") == 403, "antes de parear, a recarga dos efeitos e 403")
        confere(await status("GET", "/api/nao-existe") == 403, "antes de parear, rota fora da tabela e 403")
        confere(await status("POST", "/api/pareamento/codigo") == 403, "before pairing, a new code is PC only (403)")
        A.mock = False
        resp, j, _ = await manda("GET", "/api/state")
        confere(resp.status == 401 and j.get("parear") and "mock" not in j,
                "outside --mock, the pairing 401 has no \"mock\" (dev/so_mock.py refuses that server)")
        A.mock = True
        confere(await status("POST", "/api/play", host=f"ritmelli.example:{porta}") == 403,
                "another Host (DNS rebinding), from the home network: 403")
        confere(await status("POST", "/api/parear", origin="http://outro.example", corpo={"codigo": "1"}) == 403,
                "another Origin on a write (CSRF), from the home network: 403")

        # o pareamento
        codigo, _ = A.celulares.codigo_atual()
        outro = f"{(int(codigo) + 1) % 10 ** 6:06d}"
        resp, j, _ = await manda("POST", "/api/parear", corpo={"codigo": outro}, handler=rota[("POST", "/api/parear")])
        confere(resp.status == 403 and par.COOKIE not in resp.cookies,
                f"the /api/parear with the wrong code pairs nothing ({resp.status})")
        com_espaco = codigo[:3] + " " + codigo[3:]
        resp, j, _ = await manda("POST", "/api/parear", corpo={"codigo": com_espaco},
                                 handler=rota[("POST", "/api/parear")])
        chave = resp.cookies.get(par.COOKIE)
        confere(resp.status == 200 and chave is not None and chave["httponly"] and chave["samesite"] == "Strict",
                f"the /api/parear with the right code ({com_espaco!r}, a space in the middle) puts the key in an "
                f"HttpOnly, SameSite=Strict cookie ({resp.status})")
        chave = chave.value if chave is not None else ""
        confere(await status("POST", "/api/play", cookie=chave, cookie_name=par.COOKIE_VELHO) == 200,
                "the key in the cookie from before the name change works too")

        # o celular pareado: o que o tema usa nele, com e sem parametro; o que e do PC, 403
        for m, c in (("POST", "/api/play"), ("DELETE", "/api/queue/q1"), ("DELETE", "/api/library/d1"),
                     ("GET", "/api/onda/d1"), ("PATCH", "/api/library/d1"), ("POST", "/api/settings"),
                     ("HEAD", "/api/state")):
            confere(await status(m, c, cookie=chave) == 200, f"o celular pareado: {m} {c} passa")
        for m, c in (("POST", "/api/effects/reload"), ("DELETE", "/api/pareamento/abc"), ("GET", "/api/pareamento"),
                     ("HEAD", "/api/pareamento"), ("GET", "/api/atualizacao"), ("POST", "/api/metricas"),
                     ("POST", "/api/boas-vindas"), ("POST", "/api/janela/foco"), ("POST", "/api/volume"),
                     ("POST", "/api/abaixa"), ("POST", "/api/sinal"), ("POST", "/api/shutdown"), ("GET", "/api/lan"),
                     *perm.OUT_OF_REPO):
            confere(await status(m, c, cookie=chave) == 403, f"o celular pareado: {m} {c} nao e dele (403)")
        for m, c in (("POST", "/api/boas-vindas"), ("POST", "/api/janela/foco")):  # the guard alone turns them away
            resp, j, _ = await manda(m, c, cookie=chave, handler=rota[(m, c)])
            confere(resp.status == 403, f"the paired phone: {m} {c} through its real handler is 403 ({resp.status})")
        resp, j, _ = await manda("GET", "/api/state", cookie=chave, handler=rota[("GET", "/api/state")])
        confere(resp.status == 200 and j.get("caps") == perm.caps("celular") and par.COOKIE in resp.cookies,
                "o /api/state do celular traz o caps dele e renova o cookie")
        rotas = j.get("caps", {}).get("rotas", [])
        confere("POST /api/effects/reload" not in rotas and "POST /api/play" in rotas,
                "o caps do celular: tocar sim, recarga dos efeitos nao")
        resp, j, _ = await manda("GET", "/api/state", de=pc, handler=rota[("GET", "/api/state")])
        confere(j.get("caps") == perm.caps("pc") and "POST /api/effects/reload" in j["caps"]["rotas"],
                "o /api/state do PC traz o caps do PC, com a recarga dos efeitos")

        async def eventos_ate_revogar(revoga, **k):
            """O /api/events de verdade: os eventos ate revogar, e se ele terminou sozinho depois."""
            tarefa = asyncio.ensure_future(manda("GET", "/api/events", handler=rota[("GET", "/api/events")], **k))
            await asyncio.sleep(0.3)
            revoga()
            try:
                _, _, req = await asyncio.wait_for(tarefa, 3)
            except asyncio.TimeoutError:
                return [], False
            escrito = b"".join(c.args[0] for c in req._payload_writer.write.call_args_list).decode("utf-8")
            return re.findall(r"^event: (\w+)\ndata: (.*)$", escrito, re.M), True

        renamed = []
        A.lib.update = lambda iid, **kw: renamed.append((iid, kw))
        for who, kw in (("the paired phone", {"cookie": chave}), ("the PC", {"de": pc})):
            A.job_rodando = passed_the_check
            for (m, c), extra, fields in TRACK_ROUTES:
                for bad in bad_bodies_for(extra, fields):
                    try:
                        resp, _, _ = await manda(m, c, corpo=bad, handler=rota[(m, c)], **kw)
                        st = resp.status
                    except PassedTheCheck:
                        st = "accepted"
                    confere(st == 400, f"{who}: {m} {c} refuses {str(bad)[:80]} ({st})")
            for m, c in (("POST", "/api/queue"), ("POST", "/api/library")):
                resp, j, _ = await manda(m, c, corpo={"youtube_id": "dQw4w9WgXcQ", "play": True, "duration": 90000},
                                         handler=rota[(m, c)], **kw)
                confere(resp.status == 400 and j["error"].get("key") == "server.queue.tooLong",
                        f"{who} cannot {m} {c} a search result longer than a day, and the theme can say so "
                        f"({j.get('error')})")
                resp, j, _ = await manda(m, c, corpo={"youtube_id": "dQw4w9WgXcQ", "play": True,
                                                      "duration": float("inf")}, handler=rota[(m, c)], **kw)
                confere(resp.status == 400 and "key" not in j["error"],
                        f"{who}: {m} {c} refuses an infinite duration as a bad body, not as a video longer than a day "
                        f"({j.get('error')})")
            del A.job_rodando
            lookups = []
            shelf_get, shelf_by_youtube = A.lib.get, A.lib.by_youtube
            A.lib.get = lambda iid: lookups.append(("get", iid))
            A.lib.by_youtube = lambda yid: lookups.append(("by_youtube", yid))
            try:
                for m, c, sent in (("POST", "/api/queue", {"youtube_id": "dQw4w9WgXcQ", "duration": -1}),
                                   ("POST", "/api/queue", {"id": "d1", "youtube_id": "dQw4w9WgXcQ", "duration": -1}),
                                   ("POST", "/api/library", {"youtube_id": "dQw4w9WgXcQ", "play": True,
                                                             "duration": -1})):
                    resp, _, _ = await manda(m, c, corpo=sent, handler=rota[(m, c)], **kw)
                    confere(resp.status == 400 and not lookups, f"{who}: {m} {c} refuses {sent} before it looks at "
                            f"the shelf ({resp.status}, {lookups})")
                    lookups.clear()
            finally:
                A.lib.get, A.lib.by_youtube = shelf_get, shelf_by_youtube
            labels, streamed = [], []
            A.job_rodando, A.run_download, A.job_update = (lambda _: None), (lambda *a: None), (lambda j, **k: None)
            A.new_job = lambda label, play, alvo: labels.append(label) or {"id": "j1"}
            A.tocar_remoto = lambda j, target, meta: streamed.append(target) or True
            played = {"youtube_id": "dQw4w9WgXcQ", "play": True, "title": "Live", "duration": 233}
            try:
                resp, j, _ = await manda("POST", "/api/library", handler=rota[("POST", "/api/library")], **kw,
                                         corpo={"youtube_id": "dQw4w9WgXcQ", "title": "Live", "duration": 90000})
                confere(resp.status == 200 and j.get("job") == {"id": "j1"} and labels == ["Live"],
                        f"{who} can still save a search result longer than a day, without play ({resp.status}, {j})")
                resp, j, _ = await manda("POST", "/api/library", corpo=played, handler=rota[("POST", "/api/library")],
                                         **kw)
            finally:
                del A.job_rodando, A.run_download, A.job_update, A.new_job, A.tocar_remoto
            confere(resp.status == 200 and j.get("streaming") is True and streamed == ["dQw4w9WgXcQ"],
                    f"{who} can play a video off the shelf right away (dev/testa_comandos.py checks the platter) "
                    f"({resp.status}, {j}, {streamed})")
            resp, j, _ = await manda("PATCH", "/api/library/d1", corpo={"title": "a\ud800b"},
                                     handler=rota[("PATCH", "/api/library/{iid}")], **kw)
            confere(resp.status == 400 and not renamed and j["error"].get("key") == "server.library.badTitle",
                    f"{who} cannot rename a record with a lone surrogate, and the theme can say so ({resp.status}, "
                    f"{renamed}, {j.get('error')})")
        del A.lib.update

        # the SSE round is built once for every connection: a state that carries such a text anyway still goes out
        # (as ASCII-only JSON), and the next state arrives whole
        states = [{"status": "idle", "track": {"title": "a\ud800b"}}, {"status": "idle", "track": {"title": "Ação"}}]
        leitura, A.leitura = A.leitura, lambda: (states.pop(0) if len(states) > 1 else states[0], 0.0)  # one per round
        try:
            ev, terminou = await eventos_ate_revogar(lambda: setattr(A, "closing", True), de=pc)
        except Exception as ex:  # the round that fails to build raises in every connection waiting for it
            ev, terminou = [("error", repr(ex))], False
        finally:
            A.leitura, A.closing = leitura, False
        titles = [json.loads(d)["track"]["title"] for e, d in ev if e == "state"]
        confere(terminou and titles == ["a\ud800b", "Ação"] and all(d.isascii() for _, d in ev),
                f"the SSE sends the state with a lone surrogate, and the next one arrives whole ({titles or ev[:1]})")

        ev, terminou = await eventos_ate_revogar(lambda: A.celulares.desconecta(A.celulares.publico()[0]["id"]),
                                                 cookie=chave)
        nomes = [e for e, _ in ev]
        confere(terminou and nomes[:1] == ["caps"] and json.loads(ev[0][1]) == perm.caps("celular")
                and nomes[-1:] == ["desconectado"], f"o SSE do celular: o caps primeiro, e desconectado no PC, avisa "
                f"e fecha ({nomes[:2]}...{nomes[-1:]})")
        resp, j, _ = await manda("POST", "/api/play", cookie=chave)
        confere(resp.status == 401 and j.get("desconectado"), "desconectado, a chave e recusada (401, desconectado)")
        torto = "ç" * 43  # fora do ASCII (o byte cru, que vira substituto, vai no --mock de verdade)
        confere(await status("GET", "/t/ritmelli/", cookie=torto) == 200, "o cookie que nao e ASCII: o tema abre")
        resp, j, _ = await manda("GET", "/api/state", cookie=torto)
        confere(resp.status == 401 and j.get("parear") and not j.get("desconectado"),
                f"o cookie que nao e ASCII: a API pede o codigo, sem dizer que o PC desconectou ({resp.status})")

        # o remoto: o token da sessao, so do 127.0.0.1, so o vocabulario
        token = A.remotos.abre()
        for m, c in (("POST", "/api/volume"), ("POST", "/api/abaixa"), ("POST", "/api/sinal"),
                     ("DELETE", "/api/queue/q1"), ("POST", "/api/queue/move"), ("HEAD", "/api/state")):
            confere(await status(m, c, de=pc, token=token) == 200, f"o remoto: {m} {c} passa")
        for m, c in (("POST", "/api/settings"), ("POST", "/api/effects/reload"), ("DELETE", "/api/library/d1"),
                     ("POST", "/api/shutdown"), ("GET", "/api/pareamento"), ("POST", "/api/parear"),
                     ("GET", "/api/themes"), ("POST", "/api/nao-existe"), ("GET", "/t/ritmelli/")):
            confere(await status(m, c, de=pc, token=token) == 403, f"o remoto: {m} {c} fora da lista (403)")
        # o corpo torto: o inteiro com digitos demais, o aninhamento fundo e o charset que nao existe sao 400, nao 500
        for dados, tipo in ((b'{"vol": 1' + b"0" * 5000 + b"}", "application/json"), (b"[" * 100000, "application/json"),
                            (b'{"vol": 0.9}', "application/json; charset=nope")):
            t = mock.Mock()
            t.get_extra_info.side_effect = lambda nome, d=None: (pc, 50000) if nome == "peername" else d
            carga = streams.StreamReader(mock.Mock(_reading_paused=False), 2 ** 20, loop=asyncio.get_running_loop())
            carga.feed_data(dados)
            carga.feed_eof()
            req = make_mocked_request("POST", "/api/volume", headers={"Host": f"{pc}:{porta}", "Content-Type": tipo},
                                      transport=t, payload=carga, app=app)
            req._match_info = await app.router.resolve(req)
            try:
                st = (await guard(req, rota[("POST", "/api/volume")])).status
            except web.HTTPException as ex:
                st = ex.status
            confere(st == 400 and E.vol == 0.5, f"o corpo torto ({dados[:12]!r}..., {tipo}): {st}")

        # a sessao acaba enquanto o corpo chega: o comando nao vale mais, nem com o corpo invalido (401, nao 400)
        for dados in (b'{"vol": 0.9}', b'[1, 2]', b'{quebrado'):
            t = mock.Mock()
            t.get_extra_info.side_effect = lambda nome, d=None: (pc, 50000) if nome == "peername" else d
            carga = streams.StreamReader(mock.Mock(_reading_paused=False), 2 ** 16, loop=asyncio.get_running_loop())
            req = make_mocked_request("POST", "/api/volume", headers={"Host": f"{pc}:{porta}", perm.REMOTO: token,
                                                                      "Content-Type": "application/json"},
                                      transport=t, payload=carga, app=app)
            req._match_info = await app.router.resolve(req)
            tarefa = asyncio.ensure_future(guard(req, rota[("POST", "/api/volume")]))
            await asyncio.sleep(0.05)
            A.remotos.fecha(token)
            carga.feed_data(dados)
            carga.feed_eof()
            try:
                st = (await tarefa).status
            except web.HTTPException as ex:
                st = ex.status
            confere(st == 401 and E.vol == 0.5, f"a sessao acabou com o corpo {dados!r} a caminho: {st}, e o volume "
                    "nao muda")
            token = A.remotos.abre()
        resp, j, _ = await manda("GET", "/api/state", de=pc, token=token, handler=rota[("GET", "/api/state")])
        confere(j.get("caps") == perm.caps("remoto")
                and {tuple(x.split(" ", 1)) for x in j["caps"]["rotas"]} == VOCABULARIO,
                "o /api/state do remoto traz o caps dele: o vocabulario e nada mais")
        confere(await status("POST", "/api/play", token=token) == 401, "o token vindo da rede de casa: 401")
        confere(await status("POST", "/api/play", de="::1", token=token) == 401, "o token vindo do ::1: 401")
        for corpo in ({"url": "http://192.168.0.1/admin"}, {"url": "file:///C:/x"}, {"youtube_id": "curto"},
                      {"query": "queen"}, {"id": 12345678901, "url": "http://192.168.0.1/admin"},
                      {"youtube_id": 12345678901}, *BAD_TRACK_BODIES):
            A.job_rodando = passed_the_check
            try:
                resp, _, _ = await manda("POST", "/api/queue", de=pc, token=token, corpo=corpo,
                                         handler=rota[("POST", "/api/queue")])
                st = resp.status
            except PassedTheCheck:
                st = "accepted"
            finally:
                del A.job_rodando
            confere(st == 400, f"o remoto so enfileira disco da prateleira ou video do YouTube: {str(corpo)[:90]} -> {st}")
        # o que passa: o video do YouTube, com a capa dele e nao a do corpo; o disco da prateleira pelo id
        fila = types.SimpleNamespace(
            lib=types.SimpleNamespace(get=lambda i: {"id": i, "title": "t"} if i == "d1" else None,
                                      by_youtube=lambda _: None),
            job_rodando=lambda _: None, new_job=lambda *a: {"id": "j1"}, run_download=lambda *a: None,
            fila_lock=threading.Lock(), _por_na_fila=lambda *a, **k: None)
        capa = "http://192.168.0.1/capa.png"
        x, _ = server.App.enfileirar(fila, {"youtube_id": "dQw4w9WgXcQ", "thumb": capa}, True)
        confere(x["youtube_id"] == "dQw4w9WgXcQ" and x["thumb"] == server.thumb("dQw4w9WgXcQ"),
                f"o remoto enfileira o video do YouTube com a capa dele, nao a do corpo ({x['thumb']})")
        x, _ = server.App.enfileirar(fila, {"youtube_id": "dQw4w9WgXcQ", "thumb": capa})
        confere(x["thumb"] == capa, "o PC e o celular seguem mandando a capa (o tema manda a da busca)")
        x, _ = server.App.enfileirar(fila, {"id": "d1"}, True)
        confere(x["id"] == "d1", "o remoto enfileira o disco da prateleira pelo id")
        # o erro de tocar na hora a entrada que acabou de entrar nao e a recusa do corpo: o guard relanca, e o aiohttp
        # responde 500, como antes da camada de comandos
        falha_ao_tocar = ValueError("quebrou")
        enfileirar, A.enfileirar = A.enfileirar, (lambda b, remoto=False: ({"qid": "q1"}, None))
        E.captura = lambda: server.eng.Captura(None, 0.0, "idle", None, 0)  # o prato parado: a entrada toca na hora
        msg = "o POST /api/queue com o erro de tocar na hora: o erro sobe pelo guard (500), e nao vira 400"
        try:
            with mock.patch.object(server.cmd, "avanca", side_effect=falha_ao_tocar):  # o avanco que toca quebra
                resp, _, _ = await manda("POST", "/api/queue", de=pc, corpo={"id": "d1"},
                                         handler=rota[("POST", "/api/queue")])
            confere(False, f"{msg} ({resp.status})")
        except ValueError as ex:
            confere(ex is falha_ao_tocar, msg)
        finally:
            A.enfileirar = enfileirar
            del E.captura
        confere(await status("POST", "/api/play", de=pc, token=token[:-2] + "xx") == 401,
                "o token errado, do 127.0.0.1: 401 (nao cai no papel do PC)")
        confere(await status("POST", "/api/play", de=pc, token="") == 401, "o cabecalho vazio, do 127.0.0.1: 401")
        ev, terminou = await eventos_ate_revogar(lambda: A.remotos.fecha(token), de=pc, token=token)
        nomes = [e for e, _ in ev]
        confere(terminou and nomes[:1] == ["caps"] and json.loads(ev[0][1]) == perm.caps("remoto")
                and nomes[-1:] == ["desconectado"], f"o SSE do remoto: o caps primeiro, e a sessao fechada, avisa e "
                f"fecha ({nomes[:2]}...{nomes[-1:]})")
        resp, j, _ = await manda("POST", "/api/play", de=pc, token=token)
        confere(resp.status == 401, f"o token vencido (a sessao acabou), do 127.0.0.1: 401 ({resp.status})")
        confere(await status("POST", "/api/play", de=pc) == 200, "sem o cabecalho, o 127.0.0.1 segue o PC")

        # o SSE: o state e o tick de uma volta saem da mesma captura (App.leitura), mesmo com o motor virando no meio
        # do envio, e o snapshot base e montado uma vez por volta para todas as conexoes (server.Voltas). Dois PCs
        # ligados: o envio do primeiro fica suspenso logo depois do state, e a virada acontece ali (a faixa nova, com a
        # posicao dela); o segundo segue livre e recebe a virada enquanto o primeiro esta parado
        capturas, lidas = [({"status": "playing", "track": {"id": "t1"}}, 100.0)], []

        def leitura():
            lidas.append(1)
            return capturas[-1]
        A.leitura, E.pos = leitura, 100.0
        no_state, solta = asyncio.Event(), asyncio.Event()

        def cliente(suspende):
            t = mock.Mock()
            t.get_extra_info.side_effect = lambda nome, d=None: (pc, 50000) if nome == "peername" else d
            req = make_mocked_request("GET", "/api/events", headers={"Host": f"{pc}:{porta}"}, transport=t, app=app)
            escrito = []

            async def escreve(dados):
                escrito.append(dados.decode("utf-8"))
                if suspende and dados.startswith(b"event: state") and not no_state.is_set():
                    no_state.set()
                    await solta.wait()
            req._payload_writer.write = escreve
            return req, escrito

        def eventos(escrito):
            return [(e, json.loads(d)) for e, d in re.findall(r"^event: (\w+)\ndata: (.*)$", "".join(escrito), re.M)]

        def pares(escrito):
            faixa, out = None, []
            for e, d in eventos(escrito):
                if e == "state":
                    faixa = d["track"]["id"]
                elif e == "tick":
                    out.append((faixa, d["pos"]))
            return out

        async def ate(cond):
            for _ in range(100):
                if cond():
                    return True
                await asyncio.sleep(0.05)
            return False

        def com_t2(escrito):  # a faixa nova chegou, e o tick dela depois
            ev = eventos(escrito)
            return any(e == "state" and d["track"]["id"] == "t2" for e, d in ev) and ev[-1][0] == "tick"

        tarefas = []
        try:
            (req1, escrito1), (req2, escrito2) = cliente(True), cliente(False)
            for req in (req1, req2):
                req._match_info = await app.router.resolve(req)
                tarefas.append(asyncio.ensure_future(guard(req, rota[("GET", "/api/events")])))
            await asyncio.wait_for(no_state.wait(), 3)
            capturas.append(({"status": "playing", "track": {"id": "t2"}}, 0.5))
            E.pos = 0.5
            livre = await ate(lambda: com_t2(escrito2))
            confere(livre and no_state.is_set() and not solta.is_set() and not com_t2(escrito1),
                    "com o envio de um PC suspenso, o outro segue recebendo as voltas, a virada inclusive")
            solta.set()
            await ate(lambda: com_t2(escrito1))
            await asyncio.sleep(5 * server.TICK)  # algumas voltas com os dois livres
        finally:
            solta.set()
            A.closing = True
            for tarefa in tarefas:
                await asyncio.wait_for(tarefa, 3)
            A.closing, E.pos = False, 0.0
        for nome, escrito in (("suspenso", escrito1), ("livre", escrito2)):
            p = pares(escrito)
            confere(p[:1] == [("t1", 100.0)] and ("t2", 0.5) in p and set(p) <= {("t1", 100.0), ("t2", 0.5)},
                    f"o SSE com a virada entre o state e o tick, no PC {nome}: cada posicao e da faixa entregue na "
                    f"volta dela ({p})")
        estados = [d for e, d in eventos(escrito1) + eventos(escrito2) if e == "state"]
        confere(estados and all(d.get("api") == server.API and d.get("mock") is True for d in estados),
                f"o state do SSE leva o \"api\": {server.API} e o \"mock\" ({[sorted(d) for d in estados[:1]]})")
        # o livre entrega toda volta: as leituras sao as voltas dele, e no maximo a que estava no ar no fechamento.
        # Com cada conexao montando a sua, as do suspenso viriam a mais
        n1, n2 = len(pares(escrito1)), len(pares(escrito2))
        confere(n1 >= 2 and n2 >= 5 and len(lidas) <= n2 + 1,
                f"com dois PCs ligados, o snapshot e montado uma vez por volta ({len(lidas)} leituras; {n2} voltas "
                f"entregues ao livre, {n1} ao suspenso)")
        antes = len(lidas)
        await asyncio.sleep(5 * server.TICK)
        confere(len(lidas) == antes, f"sem conexao aberta, nada e montado ({len(lidas) - antes} leituras a mais)")
        A.leitura = lambda: ({"status": "idle"}, 0.0)
        resp, j, _ = await manda("GET", "/api/state", de=pc, handler=rota[("GET", "/api/state")])
        confere(j.get("api") == server.API and j.get("mock") is True,
                f"o /api/state leva o \"api\" e o \"mock\" ({ {k: j.get(k) for k in ('api', 'mock')} })")

        # o erro de montar a volta sobe para a conexao que a espera (o guard o leva as metricas, como quando cada
        # conexao lia a sua), e a conexao seguinte monta de novo
        quebrou = ValueError("leitura quebrou")

        def leitura_quebrada():
            raise quebrou
        A.leitura = leitura_quebrada
        try:
            await asyncio.wait_for(manda("GET", "/api/events", de=pc, handler=rota[("GET", "/api/events")]), 3)
            confere(False, "o erro de montar a volta sobe para a conexao (ela terminou sem erro)")
        except ValueError as ex:
            confere(ex is quebrou, "o erro de montar a volta sobe para a conexao")
        finally:
            A.leitura = lambda: ({"status": "idle"}, 0.0)
        ev, terminou = await eventos_ate_revogar(lambda: setattr(A, "closing", True), de=pc)
        A.closing = False
        confere(terminou and [e for e, _ in ev][:3] == ["caps", "state", "library"],
                f"depois do erro, a conexao seguinte recebe a volta de novo ({[e for e, _ in ev][:3]})")


async def papel_local_celular():
    """O --papel-local celular (so no --mock), pelo guard e pelas rotas de verdade: do 127.0.0.1, o Host
    127.0.0.1:<porta> passa pelo pareamento como o celular da rede de casa (o 401 com o "mock" e o caps do
    pre-pareamento, o caps do celular depois do POST /api/parear, a revogacao fechando o SSE) e o Host
    localhost:<porta> segue o PC, que le o codigo (com o endereco do 127.0.0.1) e desconecta o aparelho."""
    from unittest import mock

    from aiohttp import streams
    from aiohttp.test_utils import make_mocked_request

    with contextlib.redirect_stderr(io.StringIO()):  # o aviso das vozes do pedal, que nao sao deste teste
        import pareamento as par
        import server
    porta = 8801
    cel, pc = f"127.0.0.1:{porta}", f"localhost:{porta}"
    print("--- o --papel-local celular: o 127.0.0.1 como o celular, o localhost como o PC")
    with tempfile.TemporaryDirectory() as tmp:
        E = types.SimpleNamespace(pos=0.0, levels={}, vol=0.5)
        A = types.SimpleNamespace(engine=E, port=porta, lan_ip=None, mock=True, closing=False, papel_local="celular",
                                  celulares=par.Pareamento(Path(tmp) / "celulares.json"), remotos=perm.Remotos(),
                                  metricas=types.SimpleNamespace(erro=lambda *a, **k: None),
                                  atualizacao=types.SimpleNamespace(ao_abrir=lambda: None),
                                  leitura=lambda: ({"status": "idle"}, 0.0), public_jobs=lambda: [],
                                  lib=types.SimpleNamespace(version=1, public=lambda: []),
                                  boas_vindas_pendentes=lambda: True, grava_cfg=lambda **k: None)
        app = guard = rota = None

        def monta():
            nonlocal app, guard, rota
            app = server.build(A)
            guard = app.middlewares[0]
            rota = {(r.method, r.resource.canonical): r.handler for r in app.router.routes() if r.resource is not None}
        monta()

        async def manda(metodo, caminho, host=cel, cookie=None, corpo=None):
            """O pedido do 127.0.0.1 (o adb reverse e o navegador do PC chegam dele) com o Host dito, pela rota de
            verdade."""
            t = mock.Mock()
            t.get_extra_info.side_effect = lambda nome, d=None: ("127.0.0.1", 50000) if nome == "peername" else d
            cab = {"Host": host}
            if cookie:
                cab["Cookie"] = f"{par.COOKIE}={cookie}"
            carga = streams.EMPTY_PAYLOAD
            if corpo is not None:
                cab["Content-Type"] = "application/json"
                carga = streams.StreamReader(mock.Mock(_reading_paused=False), 2 ** 16, loop=asyncio.get_running_loop())
                carga.feed_data(json.dumps(corpo).encode("utf-8"))
                carga.feed_eof()
            req = make_mocked_request(metodo, caminho, headers=cab, transport=t, payload=carga, app=app)
            req._match_info = await app.router.resolve(req)
            resp = await guard(req, rota[(metodo, req._match_info.route.resource.canonical)])
            return resp, (json.loads(resp.body) if getattr(resp, "body", None) else {}), req

        resp, j, _ = await manda("GET", "/api/state")
        confere(resp.status == 401 and j.get("parear") and j.get("mock") is True and not j.get("desconectado")
                and j.get("caps") == perm.caps("publico"),
                f"o 127.0.0.1 sem cookie: o 401 do pareamento, com o \"mock\" e o caps do pre-pareamento ({resp.status})")
        for m, c in (("GET", "/api/pareamento"), ("POST", "/api/boas-vindas"), ("POST", "/api/effects/reload")):
            resp, _, _ = await manda(m, c)
            confere(resp.status == 403, f"o 127.0.0.1 sem cookie: {m} {c} e do PC (403, {resp.status})")
        resp, j, _ = await manda("GET", "/api/state", host=pc)
        confere(resp.status == 200 and j.get("caps") == perm.caps("pc"), "o localhost segue o PC: o caps do PC")
        resp, j, _ = await manda("GET", "/api/pareamento?caminho=/t/ritmelli/", host=pc)
        confere(resp.status == 200 and j.get("url") == f"http://127.0.0.1:{porta}/t/ritmelli/" and j.get("codigo")
                and j.get("qr"), f"o PC le o codigo, com o endereco do 127.0.0.1 ({j.get('url')})")
        resp, _, _ = await manda("POST", "/api/parear", corpo={"codigo": j.get("codigo") or ""})
        chave = resp.cookies.get(par.COOKIE)
        confere(resp.status == 200 and chave is not None, f"o 127.0.0.1 pareia com o codigo do PC ({resp.status})")
        chave = chave.value if chave is not None else ""
        resp, j, _ = await manda("GET", "/api/state", cookie=chave)
        confere(resp.status == 200 and j.get("caps") == perm.caps("celular") and par.COOKIE in resp.cookies,
                "pareado, o 127.0.0.1 le o estado com o caps do celular e renova o cookie")
        resp, j, _ = await manda("GET", "/api/boas-vindas", cookie=chave)
        confere(resp.status == 200 and j.get("mostrar") is False, "as boas-vindas nao abrem no papel do celular")
        resp, j, _ = await manda("GET", "/api/boas-vindas", host=pc)
        confere(j.get("mostrar") is True, "e abrem no localhost, o PC")
        resp, _, _ = await manda("GET", "/api/pareamento", cookie=chave)
        confere(resp.status == 403, f"pareado, o 127.0.0.1 segue sem o codigo e a lista dos celulares ({resp.status})")

        tarefa = asyncio.ensure_future(manda("GET", "/api/events", cookie=chave))
        await asyncio.sleep(0.3)
        resp, j, _ = await manda("GET", "/api/pareamento", host=pc)
        aid = (j.get("celulares") or [{}])[0].get("id", "")
        resp, _, _ = await manda("DELETE", f"/api/pareamento/{aid}", host=pc)
        confere(resp.status == 200, f"o PC desconecta o aparelho do 127.0.0.1 ({resp.status})")
        try:
            _, _, req = await asyncio.wait_for(tarefa, 3)
            escrito = b"".join(c.args[0] for c in req._payload_writer.write.call_args_list).decode("utf-8")
            nomes = re.findall(r"^event: (\w+)$", escrito, re.M)
        except asyncio.TimeoutError:
            nomes = None
        confere(nomes is not None and nomes[:1] == ["caps"] and nomes[-1:] == ["desconectado"],
                f"o SSE do 127.0.0.1: o caps primeiro, e desconectado no PC, avisa e fecha ({nomes})")
        resp, j, _ = await manda("GET", "/api/state", cookie=chave)
        confere(resp.status == 401 and j.get("desconectado") and j.get("caps") == perm.caps("publico"),
                "revogado, o 127.0.0.1 volta ao pareamento: o 401 diz que o PC desconectou, com o caps de antes")

        A.papel_local = "pc"
        monta()
        resp, j, _ = await manda("GET", "/api/state")
        confere(resp.status == 200 and j.get("caps") == perm.caps("pc"), "sem o --papel-local celular, o 127.0.0.1 e o PC")
        resp, j, _ = await manda("GET", "/api/pareamento", host=pc)
        confere(j.get("url") is None and j.get("codigo") is None,
                "e o --mock, sem o IP da rede de casa, nao gera codigo (como antes)")

        A.mock, A.papel_local = False, "celular"  # o modo e so do --mock: fora dele, o build o ignora
        monta()
        resp, j, _ = await manda("GET", "/api/state")
        confere(resp.status == 200 and j.get("caps") == perm.caps("pc"), "fora do --mock, o 127.0.0.1 segue o PC")
        resp, j, _ = await manda("GET", "/api/pareamento", host=pc)
        confere(j.get("url") is None and j.get("codigo") is None, "e o codigo nao sai no 127.0.0.1")


def de_casa(srv, metodo, caminho, corpo=None, origem="127.0.0.2", cab=None):
    """Um pedido ao --mock saindo do endereco origem (o 127.0.0.2 faz as vezes de um aparelho da rede de casa: o
    servidor olha o endereco de quem conecta), so com o filho vivo e respondendo como --mock, como no Filho.api.
    Volta (status, o JSON ou o texto)."""
    srv.confere()
    c = http.client.HTTPConnection("127.0.0.1", srv.porta, timeout=10, source_address=(origem, 0))
    try:
        dados = None if corpo is None else json.dumps(corpo).encode("utf-8")
        c.request(metodo, caminho, body=dados, headers={"Content-Type": "application/json", **(cab or {})})
        r = c.getresponse()
        texto = r.read().decode("utf-8", "replace")
        try:
            return r.status, json.loads(texto)
        except ValueError:
            return r.status, texto
    finally:
        c.close()


def first_events(srv, names, timeout=10):
    """The first event of each name in names from the PC's real /api/events, parsed, and whether every data line was
    ASCII."""
    srv.confere()
    c = http.client.HTTPConnection("127.0.0.1", srv.porta, timeout=timeout)
    out, ascii_only, name = {}, True, None
    try:
        c.request("GET", "/api/events")
        r = c.getresponse()
        while set(names) - set(out):
            line = r.readline()
            if not line:
                break
            ascii_only = ascii_only and line.isascii()
            line = line.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: ") and name in names and name not in out:
                out[name] = json.loads(line[len("data: "):])
    finally:
        c.close()
    return out, ascii_only


def recusa_do(srv, metodo, rota, corpo):
    """O status do pedido do PC (o so_mock levanta o HTTPError na recusa); 200 se passou."""
    try:
        srv.api(metodo, rota, corpo)
        return 200
    except OSError as ex:
        return getattr(ex, "code", None)


def answer_of(srv, method, route, body):
    try:
        srv.api(method, route, body)
        return 200, None
    except urllib.error.HTTPError as ex:
        return ex.code, json.loads(ex.read()) if ex.headers.get_content_type() == "application/json" else None


def the_theme_page_build():
    import server
    import theme_page
    import theme_page_cases
    print("--- the theme page: every <script src> and stylesheet <link> inline, or no page")
    with tempfile.TemporaryDirectory(prefix="testa_mock_inline_") as t:
        folder = Path(t)
        page, script, sheet = folder / "index.html", folder / "first.js", folder / "a.css"
        source = '<head>\n<script src="first.js"></script>\n<link rel="stylesheet" href="a.css">\n<script src="/t/ritmelli/i18n.js"></script>'
        page.write_text(source, encoding="utf-8")
        script.write_text("const first = 1;\n", encoding="utf-8")
        sheet.write_text("a { b: c; }\n", encoding="utf-8")
        shared = (theme_page.THEMES / "ritmelli" / "i18n.js").read_text(encoding="utf-8")
        html = theme_page.inline_files(source, folder)
        confere(html == f"<head>\n<script>\nconst first = 1;\n</script>\n<style>\na {{ b: c; }}\n</style>\n<script>\n{shared}</script>",
                f"each tag becomes a <script> or a <style> with the text of its file, a /t/ path from the themes folder ({html[:120]!r})")
        sent, etag = theme_page.build(page, folder / "i18n", "en")
        stamp = script.stat().st_mtime_ns
        script.write_text("const first = 2;\n", encoding="utf-8")
        os.utime(script, ns=(stamp, stamp))
        sent_after, etag_after = theme_page.build(page, folder / "i18n", "en")
        confere(sent == html and etag != etag_after and "const first = 2;" in sent_after,
                "the ETag of the page follows the text it sends, even when the inlined file keeps its mtime")
        refused = theme_page_cases.REFUSED
        (folder / "sub").mkdir()
        for what, (tag, files, said) in refused.items():
            script.write_text("const first = 1;\n", encoding="utf-8")
            sheet.write_text("a { b: c; }\n", encoding="utf-8")
            for name, text in files.items():
                (folder / name).write_bytes(text) if isinstance(text, bytes) else (folder / name).write_text(
                    text, encoding="utf-8", newline="")
            try:
                theme_page.inline_files(f"<head>\n{tag}\n", folder)
                error = "no error"
            except theme_page.ThemePageError as ex:
                error = str(ex)
            confere(said in error, f"{what} stops the build of the page ({error})")
        (folder / "sub" / "c.css").write_text("a { b: url(data:image/png;base64,AA); c: url(#d); e: url( 'data:x' ); "
                                              "f: url(HTTPS://example.com/x.png); }\n", encoding="utf-8")
        (folder / "a&b.js").write_text("const ab = 1;\n", encoding="utf-8")
        (folder / "bom.css").write_text("\ufeffa { b: c; }\n", encoding="utf-8")
        sheet.write_text("a { b: url(fonts/x.woff2); c: image-set(url('y.webp') 2x, 'z.webp' 1x); d: '\\00B7'; }\n",
                         encoding="utf-8")
        kept = theme_page_cases.KEPT
        for what, (tag, expected) in kept.items():
            try:
                out = theme_page.inline_files(tag, folder)
            except theme_page.ThemePageError as ex:
                out = f"error: {ex}"
            confere(out == (expected or tag), f"{what} builds as it should ({out[:90]!r})")
        real = theme_page.THEMES / "ritmelli" / "index.html"
        refused_read, error = theme_page.strict("<head>\n  <table></table>")
        theme_read, no_error = theme_page.strict(real.read_text(encoding="utf-8"))
        confere(refused_read is None and error[:2] == (2, 3) and error[2].startswith("the <table> is not one of the elements")
                and no_error is None and len(theme_read.found) == 82,
                f"strict() gives the first refusal with its line and column, or the template it read ({error}, {no_error})")
        theme_page.build(real, real.parent / "i18n", "en")
        sheets = sum(tag == "style" for _, _, tag, _ in theme_page.file_tags(real.read_text(encoding="utf-8")))
        before = theme_page.sheet_problem.cache_info()
        theme_page.build(real, real.parent / "i18n", "en")
        after = theme_page.sheet_problem.cache_info()
        confere(sheets > 0 and after.misses == before.misses and after.hits - before.hits == sheets,
                f"a second build of the unchanged page reuses the check of each of its {sheets} sheets ({before} -> {after})")
        asyncio.run(a_missing_file_answers_500(server, folder))


async def a_missing_file_answers_500(server, folder):
    from unittest import mock

    import yarl
    from aiohttp.test_utils import TestClient, TestServer

    broken = folder / "themes" / "broken"
    broken.mkdir(parents=True)
    (broken / "index.html").write_text('<head>\n<script src="gone.js"></script>\n', encoding="utf-8")
    (broken / "assets").mkdir()
    os.link(broken / "index.html", broken / "assets" / "alias.html")
    (folder / "themes" / "latin").mkdir()
    (folder / "themes" / "latin" / "index.html").write_bytes(b"<head>\n<title>caf\xe9</title>\n")
    held = folder / "themes" / "held"
    held.mkdir()
    (held / "index.html").write_text('<head>\n<script src="held.js"></script>\n', encoding="utf-8")
    (held / "held.js").write_text("1;\n", encoding="utf-8")
    for slug, name in (("share", "//unreachable.invalid/share/x.js"), ("tshare", "/t///unreachable.invalid/share/x.js")):
        (folder / "themes" / slug).mkdir()
        (folder / "themes" / slug / "index.html").write_text(f'<head>\n<script src="{name}"></script>\n', encoding="utf-8")
    marked = folder / "themes" / "marked"
    (marked / "i18n").mkdir(parents=True)
    (marked / "index.html").write_text("<head>\n<style>/* <!-- i18n --> */</style>\n<!-- i18n -->\n", encoding="utf-8")
    for language in ("en", "pt_BR"):
        (marked / "i18n" / f"i18n_{language}.properties").write_text("a=b\n", encoding="utf-8")
    read_text = Path.read_text

    def locked(path, *args, **kwargs):
        if path.name == "held.js":
            raise PermissionError(13, "Permission denied")
        return read_text(path, *args, **kwargs)
    stat_of = os.stat

    def stat_locked(path, *args, **kwargs):
        if os.fspath(path).endswith("held.js"):
            raise PermissionError(13, "Permission denied")
        return stat_of(path, *args, **kwargs)
    import pareamento as par
    A = types.SimpleNamespace(engine=types.SimpleNamespace(pos=0.0, levels={}, vol=0.5), port=8801, lan_ip=None,
                              mock=True, closing=False, papel_local=None,
                              celulares=par.Pareamento(folder / "celulares.json"), remotos=perm.Remotos(),
                              metricas=types.SimpleNamespace(erro=lambda *a, **k: None),
                              atualizacao=types.SimpleNamespace(ao_abrir=lambda: None),
                              leitura=lambda: ({"status": "idle"}, 0.0), public_jobs=lambda: [],
                              lib=types.SimpleNamespace(version=1, public=lambda: []),
                              boas_vindas_pendentes=lambda: True, grava_cfg=lambda **k: None)
    log = io.StringIO()
    themes = (folder / "themes").resolve()
    with mock.patch.object(server.theme_page, "THEMES", themes), contextlib.redirect_stderr(log):
        A.port = so_mock.free_port()
        compared = []
        samefile = os.path.samefile

        def recorded(a, b):
            compared.append(threading.current_thread() is threading.main_thread())
            return samefile(a, b)
        network = []
        stat, realpath = os.stat, os.path.realpath

        def local_only(real):
            def read(path, *args, **kwargs):
                if os.fspath(path).startswith(("\\\\", "//")):
                    network.append(os.fspath(path))
                    raise FileNotFoundError(path)
                return real(path, *args, **kwargs)
            return read
        async with TestClient(TestServer(server.build(A), host="127.0.0.1", port=A.port)) as client:
            resp = await client.get("/t/broken/", headers={"Host": f"localhost:{A.port}"})
            status, said = resp.status, await resp.text()
            latin = await client.get("/t/latin/", headers={"Host": f"localhost:{A.port}"})
            latin = latin.status, await latin.text()
            unread = {}
            for what, patched in (("text", mock.patch.object(Path, "read_text", locked)),
                                  ("metadata", mock.patch.object(os, "stat", stat_locked))):
                with patched:
                    before = log.tell()
                    resp = await client.get("/t/held/", headers={"Host": f"localhost:{A.port}"})
                    unread[what] = resp.status, await resp.text(), log.getvalue()[before:]
            with mock.patch.object(server.theme_page.os.path, "samefile", recorded):
                sent = await client.get("/t/broken/index.html", headers={"Host": f"localhost:{A.port}"},
                                        allow_redirects=False)
            alias = await client.get("/t/broken/assets/alias.html?lang=pt_BR", allow_redirects=False,
                                     headers={"Host": f"localhost:{A.port}"})
            with mock.patch.object(os, "stat", local_only(stat)), \
                    mock.patch.object(os.path, "realpath", local_only(realpath)):
                shares = {name: (await client.get(yarl.URL(name, encoded=True), allow_redirects=False,
                                                  headers={"Host": f"localhost:{A.port}"})).status
                          for name in ("/t///unreachable.invalid/share/index.html",
                                       "/t/%5C%5Cunreachable.invalid%5Cshare/x.png",
                                       "/t/%5C%5Cunreachable.invalid%5Cshare/")}
                shares_read, network[:] = network[:], []
                files = {slug: (resp.status, await resp.text()) for slug in ("share", "tshare")
                         for resp in [await client.get(f"/t/{slug}/", headers={"Host": f"localhost:{A.port}"})]}
            resp = await client.get("/t/marked/", headers={"Host": f"localhost:{A.port}"})
            mark = resp.status, await resp.text()
    confere(status == 500 and "themes/broken/index.html:2:1 was not built: gone.js is missing from themes/broken" in said
            and said in log.getvalue() and str(folder) not in said and folder.name not in said,
            f"through the route, a missing theme file answers 500 with the template, the file and the rule, the log "
            f"says the same, and no folder of the PC goes out ({status}, {said!r})")
    confere(latin[0] == 500 and "themes/latin/index.html was not built: index.html is not UTF-8 text" in latin[1]
            and latin[1] in log.getvalue(),
            f"a template that is not UTF-8 answers 500 naming it, and the log says the same ({latin})")
    for what, (code, text, logged) in unread.items():
        confere(code == 500 and "themes/held/index.html:2:1 was not built: held.js could not be read (Permission denied)"
                in text and text in logged and str(folder) not in text,
                f"a theme file whose {what} cannot be read answers 500 naming it, and the log says the same "
                f"({code}, {text!r})")
    confere(sent.status == 302 and compared == [False],
            f"the index.html redirect compares the file off the server's loop ({sent.status}, on the loop: {compared})")
    confere(alias.status == 302 and alias.headers.get("Location") == "/t/broken/?lang=pt_BR",
            f"a hard link to the index.html in a subfolder of the theme redirects too ({alias.status}, "
            f"{alias.headers.get('Location')})")
    confere(not shares_read and all(code in (403, 404) for code in shares.values()),
            f"a theme address naming a network share is refused without the PC reading it ({shares}, read: {shares_read})")
    confere(not network and files["share"][0] == files["tshare"][0] == 500
            and "//unreachable.invalid/share/x.js is outside themes/share" in files["share"][1]
            and "/t///unreachable.invalid/share/x.js is outside themes" in files["tshare"][1],
            f"a file tag naming a network share stops the build without the PC reading it ({files}, read: {network})")
    confere(mark[0] == 500 and "themes/marked/index.html:2:11 was not built: the <!-- i18n --> mark is read only as a "
            "comment of its own" in mark[1],
            f"an i18n mark in a style before the real one stops the build, read before the texts go in ({mark})")


def index_names():
    names = ["/t/ritmelli/index.html", "/t/ritmelli/INDEX.HTML", "/t/ritmelli/index.html.", "/t/ritmelli/index.html%20",
             "/t/ritmelli//index.html", "/t/ritmelli/./index.html"]
    if sys.platform == "win32":
        import ctypes
        page = RAIZ / "themes" / "ritmelli" / "index.html"
        short = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(str(page), short, len(short)):
            names.append("/t/ritmelli/" + Path(short.value).name)
        names += ["/t/ritmelli/index.html::$DATA", "/t/other/..%5Critmelli%5Cindex.html"]
    return names


def ao_vivo(srv):
    """No --mock de verdade: o PC com tudo e a rede de casa recusada onde deve."""
    print("--- no --mock de verdade: o PC e a rede de casa (pelo 127.0.0.2)")
    with so_mock.abre(srv.base + "/t/ritmelli/") as r:
        page, page_cache, etag = r.read().decode("utf-8"), r.headers.get("Cache-Control"), r.headers.get("ETag")
    confere("<script src=" not in page and "function bindDeskButtons()" in page,
            "the theme page comes with the theme's scripts inside it")
    conn = http.client.HTTPConnection("127.0.0.1", srv.porta, timeout=10)
    try:
        conn.request("GET", "/t/ritmelli/", headers={"If-None-Match": etag or ""})
        again = conn.getresponse()
        again.read()
        files = {}
        for name in ("shared.js", "base.css", "fonts/Archivo-latin.woff2", "texturas/veio.webp"):
            conn.request("GET", f"/t/ritmelli/{name}")
            answer = conn.getresponse()
            answer.read()
            files[name] = (answer.status, answer.getheader("Cache-Control"))
        index = []
        for path in index_names():
            conn.request("GET", f"{path}?lang=pt_BR&parear=123456")
            answer = conn.getresponse()
            answer.read()
            index.append((answer.status, answer.getheader("Location")))
    finally:
        conn.close()
    confere((page_cache, again.status, again.getheader("Cache-Control")) == ("no-cache", 304, "no-cache")
            and all(x == (200, "no-cache") for x in files.values()),
            f"/t/ answers with Cache-Control: no-cache: the page ({page_cache}), its 304 ({again.status}, "
            f"{again.getheader('Cache-Control')}) and a .js, a .css, a font and an image ({files})")
    confere(index == [(302, "/t/ritmelli/?lang=pt_BR&parear=123456")] * len(index_names()),
            f"every name of the theme's index.html takes to the built page with its query ({index_names()}: {index})")
    confere(srv.api("GET", "/api/state").get("caps") == perm.caps("pc"), "o PC: o /api/state traz o caps do PC")
    confere(srv.api("POST", "/api/volume", {"vol": 0.42}).get("vol") == 0.42
            and srv.api("GET", "/api/state").get("vol") == 0.42, "o PC: o /api/volume muda o volume da musica")
    confere(srv.api("POST", "/api/volume", {"vol": 5}).get("vol") == 1.0
            and srv.api("POST", "/api/volume", {"vol": -1}).get("vol") == 0.0,
            "o /api/volume fora de 0 a 1 fica no limite")
    srv.api("POST", "/api/volume", {"vol": 0.42})
    for corpo in ({"vol": "alto"}, {"vol": True}, {}):
        confere(recusa_do(srv, "POST", "/api/volume", corpo) == 400, f"o /api/volume recusa {corpo}")
    confere(recusa_do(srv, "POST", "/api/volume", {"vol": 10 ** 400}) == 400, "o /api/volume recusa o inteiro enorme")
    confere(recusa_do(srv, "POST", "/api/settings", {"vol": "alto"}) == 400, "o /api/settings recusa o vol \"alto\"")
    confere(recusa_do(srv, "POST", "/api/settings", {"vol": 0.1, "mon_vol": "x"}) == 400
            and srv.api("GET", "/api/state").get("vol") == 0.42, "o /api/settings recusado nao muda nada (nem o vol)")
    confere(srv.api("POST", "/api/effects/reload").get("ok") is True, "o PC: a recarga dos efeitos passa")
    confere(srv.api("POST", "/api/sinal").get("ok") is True, "o PC: o sinal de teste toca")
    srv.api("POST", "/api/settings", {"mic_mute": True})
    confere(recusa_do(srv, "POST", "/api/sinal", {}) == 409, "com a voz cortada, o sinal de teste nao toca (409)")
    srv.api("POST", "/api/settings", {"mic_mute": False})
    srv.confere()
    t0 = time.monotonic()
    ab = srv.api("POST", "/api/abaixa", {"db": 12, "ms": 800})
    confere(ab.get("abaixa") == {"db": 12.0, "ms": 800} and srv.api("GET", "/api/state").get("abaixa")
            == {"db": 12.0, "ms": 800}, f"o PC: o /api/abaixa abaixa a musica e o estado mostra ({ab})")
    while srv.api("GET", "/api/state").get("abaixa") is not None and time.monotonic() - t0 < 5:
        time.sleep(0.05)
    dt = time.monotonic() - t0
    confere(srv.api("GET", "/api/state").get("abaixa") is None and 0.7 < dt < 2.5,
            f"o /api/abaixa volta sozinho no prazo (800 ms; voltou em {dt * 1000:.0f} ms)")
    srv.api("POST", "/api/abaixa", {"db": 12, "ms": 20000})
    srv.api("POST", "/api/abaixa", {"db": 0, "ms": 0})
    confere(srv.api("GET", "/api/state").get("abaixa") is None, "o /api/abaixa com zero tira o abaixamento na hora")
    for corpo in ({"db": 12}, {"db": 99, "ms": 100}, {"db": 6, "ms": -1}, {"db": "x", "ms": 100},
                  {"db": 6, "ms": 10 ** 9}, {"db": True, "ms": 100}, {"db": 12, "ms": 0.5},
                  {"db": 6, "ms": 10 ** 400}):
        confere(recusa_do(srv, "POST", "/api/abaixa", corpo) == 400, f"o /api/abaixa recusa {corpo}")

    # the PC is held to the same queue rules as the remote session, and a rename with a lone surrogate is refused: the
    # SSE stays up and carries the next change whole
    for (m, c), extra, campos in TRACK_ROUTES:
        for corpo in bad_bodies_for(extra, campos):
            confere(recusa_do(srv, m, c, corpo) == 400, f"the PC: {m} {c} refuses {str(corpo)[:80]}")
    jobs = srv.api("GET", "/api/jobs")
    confere(not jobs, f"no refused body started a download ({jobs})")
    r = srv.api("POST", "/api/library", {"youtube_id": "djV11Xbc914", "play": True, "title": "a-ha", "channel": None,
                                         "thumb": "https://i.ytimg.com/vi/djV11Xbc914/mqdefault.jpg", "duration": 30})
    tocando = (srv.api("GET", "/api/state").get("track") or {}).get("id")
    confere((r.get("item") or {}).get("id") == "d2" and tocando == "d2",
            f"a body with every field right still plays the record from the shelf ({r}, playing {tocando})")
    for bad in (*BAD_TRACK_BODIES, {"url": [], "duration": -1}):
        on_shelf = ({**bad, "youtube_id": "djV11Xbc914"} if "youtube_id" in bad
                    else {**bad, "url": bad["url"].replace("dQw4w9WgXcQ", "djV11Xbc914")}
                    if isinstance(bad.get("url"), str) else bad)
        for sent in (on_shelf, {**on_shelf, "id": "d2"}):
            queue = answer_of(srv, "POST", "/api/queue", sent)
            library = answer_of(srv, "POST", "/api/library", {**sent, "play": True})
            target = sent.get("youtube_id") or sent.get("url")
            if isinstance(target, str) and target.strip():
                envelope = isinstance(queue[1], dict) and queue[1].get("ok") is False \
                    and isinstance(queue[1].get("error"), dict)
                confere(queue == library and queue[0] == 400 and envelope, f"the queue and the shelf with play refuse "
                        f"{str(sent)[:90]} with the same answer (queue {queue}, shelf {library})")
            else:
                confere((queue, library) == tuple((400, {"ok": False, "error": {"text": EMPTY_TARGET_TEXT[route]}})
                                                  for route in ("/api/queue", "/api/library")),
                        f"the queue and the shelf with play refuse {str(sent)[:90]} for its missing target, each "
                        f"with its own text (queue {queue}, shelf {library})")
    queue = answer_of(srv, "POST", "/api/queue", {"youtube_id": "djV11Xbc914", "title": "a-ha", "duration": 30})
    srv.api("DELETE", "/api/queue")
    confere(queue[0] == 200, f"the queue takes the same record with every field right ({queue})")
    confere(recusa_do(srv, "PATCH", "/api/library/d2", {"title": "a\ud800b"}) == 400,
            "the PC cannot rename a record with a lone surrogate")
    title = "a-ha – Take On Me (versão)"
    srv.api("PATCH", "/api/library/d2", {"title": title})
    ev, ascii_only = first_events(srv, ("state", "library"))
    shelf = {x.get("id"): x.get("title") for x in ev.get("library") or []}
    confere("state" in ev and shelf.get("d2") == title and ascii_only and not srv.api("GET", "/api/state")["queue"],
            f"the SSE stays up: the state and the renamed shelf arrive whole, as ASCII, and the queue is empty "
            f"({shelf.get('d2')!r}, ascii {ascii_only})")

    try:
        de_casa(srv, "GET", "/api/themes")
    except OSError as ex:
        print(f"--   a rede de casa pelo 127.0.0.2 ficou de fora: o sistema nao conecta dele ({ex})")
        return
    s, j = de_casa(srv, "GET", "/api/state")
    confere(s == 401 and isinstance(j, dict) and j.get("parear") and j.get("caps") == perm.caps("publico"),
            f"a rede de casa sem parear: o /api/state pede o codigo, com o caps do pre-pareamento ({s})")
    for m, c, esperado in (("GET", "/api/themes", 200), ("GET", "/t/ritmelli/", 200), ("POST", "/api/play", 401),
                           ("POST", "/api/volume", 403), ("POST", "/api/abaixa", 403), ("POST", "/api/sinal", 403),
                           ("POST", "/api/effects/reload", 403), ("GET", "/api/pareamento", 403),
                           ("POST", "/api/atualizacao/instalar", 403), ("HEAD", "/api/state", 401),
                           ("DELETE", "/api/pareamento/abc", 403), ("POST", "/api/shutdown", 403)):
        s, _ = de_casa(srv, m, c, corpo={} if m == "POST" else None)
        confere(s == esperado, f"a rede de casa sem parear: {m} {c} -> {s} (esperado {esperado})")
    # o cookie com bytes que nao sao UTF-8 (o aiohttp os passa como substitutos): o tema abre, a API pede o codigo
    biscoito = {"Cookie": 'ritmelli_celular="' + "\xff\xfe" * 20 + '"'}  # entre aspas, o valor passa inteiro
    s, _ = de_casa(srv, "GET", "/t/ritmelli/", cab=biscoito)
    confere(s == 200, f"a rede de casa com o cookie de bytes tortos: o tema abre ({s})")
    s, j = de_casa(srv, "GET", "/api/state", cab=biscoito)
    confere(s == 401 and isinstance(j, dict) and j.get("parear") and not j.get("desconectado"),
            f"e o /api/state pede o codigo, sem dizer que o PC desconectou ({s})")
    s, _ = de_casa(srv, "POST", "/api/play", {}, origem="127.0.0.1", cab={"Host": "ritmelli.example"})
    confere(s == 403, f"outro Host (DNS rebinding), mesmo do 127.0.0.1: 403 ({s})")
    s, _ = de_casa(srv, "POST", "/api/play", {}, origem="127.0.0.1", cab={"Origin": "http://outro.example"})
    confere(s == 403, f"outra Origin na escrita (CSRF), mesmo do 127.0.0.1: 403 ({s})")
    s, _ = de_casa(srv, "POST", "/api/play", {}, origem="127.0.0.1", cab={perm.REMOTO: "x" * 43})
    confere(s == 401, f"um token remoto que nao vale, do 127.0.0.1: 401 ({s})")
    s, _ = de_casa(srv, "GET", "/api/state", cab={perm.REMOTO: "x" * 43})
    confere(s == 401, f"um token remoto vindo de fora do 127.0.0.1: 401 ({s})")
    srv.confere()


def sem_rede():
    """(#128) O --mock nao vai a rede sozinho. O servidor de verdade sobe com a rede apontada para uma armadilha: o
    HTTP_PROXY e o HTTPS_PROXY numa porta daqui, que o yt-dlp, a ytmusicapi e o urllib seguem e os processos filhos
    herdam. Cada conexao para fora vira uma tentativa contada, e nenhuma chega a internet. Com uma prateleira de
    titulos e videos de verdade e um disco tocando, as capas, as parecidas do Automatico e o aquecimento do processo
    do YouTube iriam na hora. Depois, uma busca (o que a pessoa pede vai ao YouTube) tem que cair na armadilha: e ela
    que mostra que a armadilha pega."""
    try:
        import aiohttp
        import numpy
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
    porta = so_mock.free_port()  # o so_mock fala com o servidor sem proxy: sem a armadilha
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
            try:
                srv = so_mock.sobe([sys.executable, str(RAIZ / "server.py"), "--mock", "--no-browser", "--port",
                                    str(porta), "--data-dir", str(dados)], porta, limite=60, cwd=RAIZ, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
            except so_mock.Recusa as ex:   # a porta tomada, o servidor caiu ou nao respondeu: o fim do log diz por que
                arm.close()
                print((t / "servidor.log").read_text(encoding="utf-8", errors="replace")[-1500:])
                confere(False, f"o servidor --mock subiu para o teste sem rede: {ex} (o log dele esta acima)")
                return
            api = srv.api
            try:
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
                ao_vivo(srv)
            except so_mock.Recusa as ex:   # o filho caiu, ou a porta deixou de responder como --mock
                confere(False, f"o teste sem rede parou: {ex}")
            finally:
                srv.encerra(15)
                arm.close()
    finally:
        shutil.rmtree(t, ignore_errors=True)
        confere(not t.exists(), f"the test folder is removed at the first try, right after the server stops ({t})")


sys.stdout.reconfigure(encoding="utf-8")
tabela()
check_track_field_routes()
try:
    import aiohttp
    import numpy
except ImportError as ex:
    print(f"--   o guard papel por papel ficou de fora: sem as bibliotecas do app ({ex.name})")
else:
    asyncio.run(papeis_no_guard())
    asyncio.run(papel_local_celular())
    the_theme_page_build()
sem_rede()

print("\nFALHOU: " + "; ".join(falhas) if falhas else "\ntudo ok")
sys.exit(1 if falhas else 0)
