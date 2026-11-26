"""Confere o pareamento do celular (pareamento.py, #127): e a unica trava do controle pelo celular, e sem o codigo de 6
numeros um aparelho da rede de casa nao muda nada no Ritmelli. As regras da docstring do modulo, com o relogio na mao (o
time.monotonic dele trocado aqui) e o celulares.json numa pasta temporaria:

- o codigo vale CODIGO_S e uma vez so;
- o codigo morre com ERROS_MAX tentativas erradas, e ai so o PC gera outro;
- o aparelho pareado ganha uma chave no cookie, e o celulares.json guarda so o hash dela;
- desconectar tira o aparelho, e a chave dele deixa de valer;
- o outro_codigo invalida o anterior.

The server's guard, with requests from the home network, is tested in dev/testa_mock.py (papeis_no_guard).

    python dev/testa_pareamento.py

Sai 1 se algo falha."""
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
    import segno
except ImportError:
    sys.modules["segno"] = types.ModuleType("segno")
import pareamento as par

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


print("\nFALHOU: " + "; ".join(falhas) if falhas else "\ntudo certo")
sys.exit(1 if falhas else 0)
