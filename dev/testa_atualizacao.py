"""Testa o atualizacao.py sem a internet nem o instalador de verdade: um servidor http local serve o manifesto, a
assinatura e um setup de mentira, com uma chave de teste gerada na hora. Cobre a assinatura (certa, de outra chave,
manifesto mexido), o formato, a versao (mais velha, igual, mais nova), o download (certo, hash errado, maior que o
manifesto, servidor fora), o caminho que sai da pasta do app, o setup trocado depois de conferido e o pedido de
permissao do Windows (aceito e recusado, sem abrir nada). Sai 1 se algo falhar.

    python dev/testa_atualizacao.py
"""
import base64
import functools
import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atualizacao as atu  # noqa: E402
from versao import VERSAO  # noqa: E402
from Cryptodome.PublicKey import ECC  # noqa: E402
from Cryptodome.Signature import eddsa  # noqa: E402

falhas = []


def caso(nome, ok, detalhe=""):
    print(f"[{'ok' if ok else 'FALHOU'}] {nome}" + (f": {detalhe}" if detalhe else ""))
    if not ok:
        falhas.append(nome)


def mais(v, n=1):
    a, b, c = atu.versao(v)
    return f"{a}.{b}.{c + n}"


tmp = Path(tempfile.mkdtemp(prefix="vitrola-atu-"))
www = tmp / "www"
www.mkdir()
atu.PASTA = tmp / "dados"
atu.SO_HTTPS = False

class Quieto(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quieto, directory=str(www)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
atu.MANIFESTO = f"{base}/manifest.json"

chave = ECC.generate(curve="Ed25519")
outra = ECC.generate(curve="Ed25519")
atu.CHAVES = {1: base64.b64encode(chave.public_key().export_key(format="raw")).decode()}

setup = os.urandom(3 << 20)
(www / "setup.exe").write_bytes(setup)
SHA = hashlib.sha256(setup).hexdigest()


def manifesto(**muda):
    m = {"formato": 1, "app": "vitrola", "versao": mais(VERSAO), "data": "2026-11-03", "notas": ["Uma coisa nova."],
         "instalador": {"url": f"{base}/setup.exe", "sha256": SHA, "tamanho": len(setup)},
         "arquivos": [{"caminho": "vitrola.exe", "sha256": SHA, "tamanho": 1}]}
    m.update(muda)
    return m


def assina(dados, k=chave, numero=1):
    return json.dumps({"chave": numero, "assinatura": base64.b64encode(eddsa.new(k, "rfc8032").sign(dados)).decode()}).encode()


def publica(m, k=chave, numero=1):
    dados = json.dumps(m, ensure_ascii=False).encode()
    (www / "manifest.json").write_bytes(dados)
    (www / "manifest.json.sig").write_bytes(assina(dados, k, numero))
    return dados


def recusa(nome, dados, sig):
    try:
        atu.confere(dados, sig)
    except atu.Recusado as e:
        caso(nome, True, str(e))
    else:
        caso(nome, False, "aceitou")


print("--- a assinatura e o formato")
d = json.dumps(manifesto()).encode()
caso("manifesto certo", atu.confere(d, assina(d))["versao"] == mais(VERSAO))
recusa("manifesto mexido depois de assinado", d.replace(b"Uma coisa", b"Outra coisa"), assina(d))
recusa("assinado por outra chave", d, assina(d, outra))
recusa("chave que o app nao conhece", d, assina(d, chave, 2))
recusa("assinatura que nao e base64", d, b'{"chave": 1, "assinatura": "@@@"}')
for nome, m in (("de outro app", manifesto(app="outro")), ("de outro formato", manifesto(formato=2)),
                ("versao fora do formato", manifesto(versao="1.0")),
                ("instalador sem hash", manifesto(instalador={"url": f"{base}/setup.exe", "tamanho": 1})),
                ("caminho que sai da pasta", manifesto(arquivos=[{"caminho": "../../x.exe", "sha256": SHA, "tamanho": 1}])),
                ("caminho absoluto", manifesto(arquivos=[{"caminho": "C:/Windows/x.exe", "sha256": SHA, "tamanho": 1}]))):
    dd = json.dumps(m).encode()
    recusa(f"manifesto {nome}", dd, assina(dd))
atu.SO_HTTPS = True
recusa("instalador por http, com o https exigido", d, assina(d))
atu.SO_HTTPS = False

print("--- a versao")
for nome, v, espera in (("mais velha", "0.0.1", False), ("igual", VERSAO, False), ("mais nova", mais(VERSAO), True)):
    publica(manifesto(versao=v))
    a = atu.Atualizacao(ativa=True)
    caso(f"versao {nome} ({v})", a.consultar() is espera and (a.publico()["nova"] is not None) is espera)
caso("sem endereco e chave, nao consulta", atu.Atualizacao().ativa is False and atu.Atualizacao().consultar() is False)


def espera(a, *estados):
    for _ in range(200):
        if a.estado in estados:
            return True
        threading.Event().wait(0.05)
    return False


print("--- o download")
publica(manifesto())
a = atu.Atualizacao(ativa=True)
a.consultar()
caso("baixar comeca", a.baixar())
caso("download certo fica pronto", espera(a, "pronta") and a.setup.exists() and a.setup.read_bytes() == setup)
caso("nada de .parcial sobrando", not list(atu.PASTA.glob("*.parcial")))

print("--- instalar, sem abrir nada")
chamadas = []
atu.abre_instalador = lambda s, p: chamadas.append((s, p)) or 42
ok, motivo = a.instalar()
caso("instala com a permissao aceita", ok and a.estado == "instalando" and chamadas and "/VERYSILENT" in chamadas[0][1]
     and "/reabrir=1" in chamadas[0][1] and Path(chamadas[0][0]) == a.setup, chamadas and chamadas[0][1])

for nome, inst in (("hash errado", {"sha256": "0" * 64}), ("maior que o manifesto", {"tamanho": len(setup) - 10})):
    for f in atu.PASTA.glob("*"):
        f.unlink()
    publica(manifesto(instalador={"url": f"{base}/setup.exe", "sha256": SHA, "tamanho": len(setup), **inst}))
    b = atu.Atualizacao(ativa=True)
    b.consultar()
    b.baixar()
    caso(f"download com {nome} e recusado", espera(b, "parado") and b.erro and b.setup is None and not list(atu.PASTA.glob("*.exe")),
         b.erro)

publica(manifesto())
c = atu.Atualizacao(ativa=True)
c.consultar()
c.baixar()
espera(c, "pronta")
atu.abre_instalador = lambda s, p: atu.SE_ERR_ACCESSDENIED
ok, motivo = c.instalar()
caso("permissao recusada no Windows", not ok and c.estado == "pronta" and "permissão" in motivo, motivo)
c.setup.write_bytes(b"trocado")
ok, motivo = c.instalar()
caso("setup trocado depois de conferido", not ok and c.estado == "parado", motivo)

print("--- servidor fora e a limpeza")
srv.shutdown()
srv.server_close()
d2 = atu.Atualizacao(ativa=True)
caso("servidor fora: sem versao nova e com o motivo", d2.consultar() is False and d2.estado == "parado" and d2.erro, d2.erro)
for f in atu.PASTA.glob("*"):
    f.unlink()
for nome in (f"Vitrola-{VERSAO}-setup.exe", "Vitrola-0.0.1-setup.exe", "x-setup.exe.parcial", f"Vitrola-{mais(VERSAO, 5)}-setup.exe"):
    (atu.PASTA / nome).write_bytes(b"x")
atu.Atualizacao(ativa=True)._limpa()
sobra = sorted(f.name for f in atu.PASTA.iterdir() if "setup" in f.name)
caso("a limpeza tira os setups velhos e os pela metade", sobra == [f"Vitrola-{mais(VERSAO, 5)}-setup.exe"], sobra)

print("tudo certo" if not falhas else f"FALHAS: {', '.join(falhas)}")
sys.exit(1 if falhas else 0)
