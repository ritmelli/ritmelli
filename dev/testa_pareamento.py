"""Confere o pareamento do celular (pareamento.py, #127): e a unica trava do controle pelo celular, e sem o codigo de 6
numeros um aparelho da rede de casa nao muda nada no Ritmelli. As regras da docstring do modulo, com o relogio na mao (o
time.monotonic dele trocado aqui) e o celulares.json numa pasta temporaria:

- o codigo vale CODIGO_S e uma vez so;
- o codigo morre com ERROS_MAX tentativas erradas, e ai so o PC gera outro;
- o aparelho pareado ganha uma chave no cookie, e o celulares.json guarda so o hash dela;
- desconectar tira o aparelho, e a chave dele deixa de valer;
- o outro_codigo invalida o anterior.

E o guard do servidor de verdade (server.build), com pedidos que chegam de um IP da rede de casa: sem a chave, uma rota
que muda alguma coisa e recusada; com ela, passa. Essa parte precisa das bibliotecas do app (o aiohttp): a esteira roda
este teste antes de instalar, e ela fica de fora.

    python dev/testa_pareamento.py

Sai 1 se algo falha."""
import asyncio
import contextlib
import hashlib
import io
import itertools
import json
import secrets
import sys
import tempfile
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
try:  # o QR (segno) nao entra aqui, e a esteira roda este teste antes de instalar as bibliotecas
    import segno  # noqa: F401
except ImportError:
    sys.modules["segno"] = types.ModuleType("segno")
import pareamento as par  # noqa: E402

falhas = []


def confere(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        falhas.append(msg)


# o relogio do pareamento.py na mao: os prazos so andam quando o teste manda
relogio = types.SimpleNamespace(t=1000.0)
par.time = types.SimpleNamespace(monotonic=lambda: relogio.t)
# os codigos em sequencia, cada um diferente do anterior: com o sorteio de verdade, um codigo novo igual ao velho (1 em
# 1 milhao) faria o "o anterior nao pareia" passar por acaso. As chaves e a comparacao seguem as de verdade
_seq = itertools.count(100000, 7919)
par.secrets = types.SimpleNamespace(randbelow=lambda n: next(_seq) % n, compare_digest=secrets.compare_digest,
                                    token_urlsafe=secrets.token_urlsafe, token_hex=secrets.token_hex)


def errado(codigo):
    """Um codigo de 6 numeros que nao e este."""
    return f"{(int(codigo) + 1) % 10 ** 6:06d}"


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)

    print(f"--- o codigo vale CODIGO_S ({par.CODIGO_S} s) e uma vez so")
    p = par.Pareamento(tmp / "a.json")
    codigo, vale_s = p.codigo_atual()
    confere(len(codigo) == 6 and codigo.isdigit() and vale_s == par.CODIGO_S, f"6 numeros, valendo {vale_s} s")
    relogio.t += 120
    confere(p.codigo_atual() == (codigo, par.CODIGO_S - 120), "o mesmo codigo enquanto vale, com o tempo que falta")
    relogio.t += par.CODIGO_S - 120 - 1
    chave, motivo = p.parear(codigo, "Android · Chrome")
    confere(bool(chave) and motivo is None, "1 s antes de vencer, ainda pareia")
    confere(p.parear(codigo, "x") == (None, "errado"), "usado uma vez, o mesmo codigo nao pareia de novo")
    outro, vale_s = p.codigo_atual()
    confere(outro != codigo and vale_s == par.CODIGO_S, "usado, a tela do PC ganha outro, com o prazo inteiro")
    relogio.t += par.CODIGO_S
    confere(p.parear(outro, "x") == (None, "errado"), "vencido (CODIGO_S depois), o codigo nao pareia")
    terceiro, vale_s = p.codigo_atual()
    confere(terceiro not in (codigo, outro) and vale_s == par.CODIGO_S, "vencido, a tela do PC ganha outro sozinha")

    print(f"--- o codigo morre com ERROS_MAX ({par.ERROS_MAX}) tentativas erradas, e so o PC gera outro")
    p = par.Pareamento(tmp / "b.json")
    codigo, _ = p.codigo_atual()
    formas = ("", "abcdef", "12345", errado(codigo))   # vazio, letras, curto e outro numero: todos contam
    quase = [p.parear(formas[i % len(formas)], "x") for i in range(par.ERROS_MAX - 1)]
    confere(all(r == (None, "errado") for r in quase) and bool(p.parear(codigo, "x")[0]),
            f"com {par.ERROS_MAX - 1} erradas (vazio, letras, curto e outro numero), o certo ainda pareia")
    p = par.Pareamento(tmp / "c.json")
    codigo, _ = p.codigo_atual()
    tentativas = [p.parear(errado(codigo), "x") for _ in range(par.ERROS_MAX)]
    confere(tentativas[-1] == (None, "queimado") and all(r == (None, "errado") for r in tentativas[:-1]),
            f"a {par.ERROS_MAX}a errada queima o codigo")
    confere(p.parear(codigo, "x") == (None, "queimado"), "queimado, nem o codigo certo pareia")
    relogio.t += 10 * par.CODIGO_S
    confere(p.codigo_atual() == (None, 0), "queimado, a tela do PC nao ganha outro sozinha, nem com o tempo")
    p.outro_codigo()
    novo, vale_s = p.codigo_atual()
    quase = [p.parear(errado(novo), "x") for _ in range(par.ERROS_MAX - 1)] if novo else []
    confere(novo is not None and vale_s == par.CODIGO_S and all(r == (None, "errado") for r in quase)
            and bool(p.parear(novo, "x")[0]), "o outro codigo do PC vale, com as tentativas zeradas")

    print("--- o pareado ganha uma chave, e o celulares.json guarda so o hash dela")
    arq = tmp / "d.json"
    p = par.Pareamento(arq)
    codigo, _ = p.codigo_atual()
    chave, _ = p.parear(codigo, "iPhone · Safari")
    texto = arq.read_text(encoding="utf-8")
    salvo = json.loads(texto)
    confere(len(chave) >= 40, f"a chave e longa ({len(chave)} caracteres)")
    confere(chave not in texto and salvo[0]["hash"] == hashlib.sha256(chave.encode("utf-8")).hexdigest(),
            "no disco, o hash da chave, e a chave nao")
    confere(set(salvo[0]) == set(par.CAMPOS), f"no disco, so os campos de sempre ({sorted(salvo[0])})")
    confere("hash" not in p.publico()[0], "a lista da tela do PC nao mostra o hash")
    torta = chave[:-1] + ("A" if chave[-1] != "A" else "B")
    confere(p.vale(chave) and not p.vale(torta) and not p.vale("") and not p.vale(None),
            "vale so a chave certa (nem a com um caractere trocado, nem a vazia)")
    confere(p.confere(chave) and not p.confere(torta) and not p.confere(None), "o confere aceita so a certa")
    confere(par.Pareamento(arq).vale(chave), "com o app aberto de novo, a chave segue valendo")
    confere(par.chave_do({par.COOKIE: chave}) == chave and par.chave_do({par.COOKIE_VELHO: chave}) == chave
            and par.chave_do({}) is None, "a chave vem do cookie (o novo, ou o de antes da troca de nome)")

    print("--- desconectar tira o aparelho, e a chave dele deixa de valer")
    aid = p.publico()[0]["id"]
    confere(p.desconecta(aid) and not p.vale(chave) and not p.confere(chave) and not p.publico(),
            "desconectado, a chave deixa de valer e o aparelho sai da lista")
    confere(not p.desconecta(aid), "desconectar de novo: nada a fazer")
    confere(not par.Pareamento(arq).vale(chave), "com o app aberto de novo, continua sem valer")

    print("--- o outro_codigo invalida o anterior")
    p = par.Pareamento(tmp / "e.json")
    antes, _ = p.codigo_atual()
    p.outro_codigo()
    depois, vale_s = p.codigo_atual()
    confere(depois != antes and vale_s == par.CODIGO_S and p.parear(antes, "x") == (None, "errado"),
            "o codigo anterior nao pareia mais")
    confere(bool(p.parear(depois, "x")[0]), "e o novo pareia")

    print("--- o celulares.json estragado")
    arq = tmp / "f.json"
    arq.write_text("{quebrado", encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()) as log:
        p = par.Pareamento(arq)
    confere(p.aparelhos == [] and "unreadable" in log.getvalue(), "o app abre com a lista vazia, e o log diz")


async def guard_do_servidor():
    """Os pedidos de um celular da rede de casa (o IP de quem conectou, que e o que o servidor olha) pelo guard do
    server.build de verdade, num app com o resto de mentira."""
    from unittest import mock

    from aiohttp import streams, web
    from aiohttp.test_utils import make_mocked_request

    with contextlib.redirect_stderr(io.StringIO()):  # o aviso das vozes do pedal, que nao sao deste teste
        import server
    lan, porta, celular, pc = "192.168.0.10", 8799, "192.168.0.50", "127.0.0.1"
    with tempfile.TemporaryDirectory() as tmp:
        A = types.SimpleNamespace(engine=None, port=porta, lan_ip=lan,
                                  celulares=par.Pareamento(Path(tmp) / "celulares.json"),
                                  metricas=types.SimpleNamespace(erro=lambda *a, **k: None))
        app = server.build(A)
        guard = app.middlewares[0]
        rota_parear = next(r.handler for r in app.router.routes()
                           if r.method == "POST" and r.resource and r.resource.canonical == "/api/parear")
        passou = []

        async def segue(req):  # a rota de verdade nao importa aqui: so se o guard deixou chegar nela
            passou.append((req.method, req.path))
            return web.json_response({"ok": True})

        def pedido(metodo, caminho, de=celular, host=None, cookie=None, origem=None, corpo=None):
            t = mock.Mock()
            t.get_extra_info.side_effect = lambda nome, d=None: (de, 50000) if nome == "peername" else d
            cab = {"Host": host or (f"{pc}:{porta}" if de == pc else f"{lan}:{porta}")}
            if cookie:
                cab["Cookie"] = cookie
            if origem:
                cab["Origin"] = origem
            carga = streams.EMPTY_PAYLOAD
            if corpo is not None:
                cab["Content-Type"] = "application/json"
                carga = streams.StreamReader(mock.Mock(_reading_paused=False), 2 ** 16, loop=asyncio.get_running_loop())
                carga.feed_data(json.dumps(corpo).encode("utf-8"))
                carga.feed_eof()
            return make_mocked_request(metodo, caminho, headers=cab, transport=t, payload=carga)

        async def manda(req, handler=segue):
            n = len(passou)
            resp = await guard(req, handler)
            return resp, len(passou) > n

        def corpo(resp):
            return json.loads(resp.body) if resp.body else {}

        print("--- o guard do servidor, com pedidos de um celular da rede de casa")
        resp, chegou = await manda(pedido("POST", "/api/play"))
        confere(resp.status == 401 and corpo(resp).get("parear") and not chegou,
                f"sem a chave, uma rota que muda o Ritmelli e recusada ({resp.status}), e pede o pareamento")
        resp, chegou = await manda(pedido("GET", "/api/state"))
        confere(resp.status == 401 and not chegou, "sem a chave, nem o estado ele le")
        for metodo, caminho in (("GET", "/api/pareamento"), ("POST", "/api/pareamento/codigo"),
                                ("DELETE", "/api/pareamento/abc")):
            resp, chegou = await manda(pedido(metodo, caminho))
            confere(resp.status == 403 and not chegou, f"{metodo} {caminho}: so no PC ({resp.status})")
        for caminho in ("/t/ritmelli/", server.TEMA_DE_ANTES + "/"):  # o de antes (#58) leva ao novo
            resp, chegou = await manda(pedido("GET", caminho))
            confere(chegou, f"{caminho}: a pagina do tema abre sem a chave, e nela que o celular digita o codigo")
        resp, chegou = await manda(pedido("POST", "/api/play", host="ritmelli.example:8799"))
        confere(resp.status == 403 and not chegou, "outro Host (DNS rebinding): recusado")
        resp, chegou = await manda(pedido("POST", "/api/parear", origem="http://outro.example", corpo={"codigo": "1"}))
        confere(resp.status == 403 and not chegou, "outra Origin na escrita (CSRF): recusado")

        codigo, _ = A.celulares.codigo_atual()
        resp, _ = await manda(pedido("POST", "/api/parear", corpo={"codigo": errado(codigo)}), rota_parear)
        confere(resp.status == 403 and par.COOKIE not in resp.cookies,
                f"o /api/parear com o codigo errado: {resp.status}")
        com_espaco = {"codigo": codigo[:3] + " " + codigo[3:]}
        resp, _ = await manda(pedido("POST", "/api/parear", corpo=com_espaco), rota_parear)
        biscoito = resp.cookies.get(par.COOKIE)
        confere(resp.status == 200 and biscoito is not None and biscoito["httponly"]
                and biscoito["samesite"] == "Strict",
                "o /api/parear com o codigo certo (\"482 913\" vale) poe a chave num cookie HttpOnly e SameSite=Strict")
        chave = biscoito.value if biscoito is not None else ""
        resp, chegou = await manda(pedido("POST", "/api/play", cookie=f"{par.COOKIE}={chave}"))
        confere(chegou, "com a chave, a mesma rota passa")
        resp, chegou = await manda(pedido("POST", "/api/play", cookie=f"{par.COOKIE_VELHO}={chave}"))
        confere(chegou, "com a chave no cookie de antes da troca de nome tambem")
        resp, chegou = await manda(pedido("GET", "/api/pareamento", cookie=f"{par.COOKIE}={chave}"))
        confere(resp.status == 403 and not chegou, "pareado, o codigo e a lista dos celulares seguem so no PC")
        A.celulares.desconecta(A.celulares.publico()[0]["id"])
        resp, chegou = await manda(pedido("POST", "/api/play", cookie=f"{par.COOKIE}={chave}"))
        confere(resp.status == 401 and corpo(resp).get("desconectado") and not chegou,
                "desconectado no PC, a chave dele e recusada, e o tema sabe que foi desconectado")
        resp, chegou = await manda(pedido("POST", "/api/play", de=pc))
        confere(chegou, "o PC (127.0.0.1) muda tudo sem chave")


try:
    import aiohttp  # noqa: F401
    import numpy  # noqa: F401
except ImportError as ex:
    print(f"--   o guard do servidor ficou de fora: sem as bibliotecas do app ({ex.name})")
else:
    asyncio.run(guard_do_servidor())

print("\nFALHOU: " + "; ".join(falhas) if falhas else "\ntudo certo")
sys.exit(1 if falhas else 0)
