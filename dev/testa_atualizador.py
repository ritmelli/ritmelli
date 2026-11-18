"""Testa o atualizador.py (a atualizacao automatica pela tarefa do Windows) sem a tarefa, sem SYSTEM e sem o instalador
de verdade: um servidor http local serve o manifesto, a assinatura e um setup de mentira, com uma chave de teste
gerada na hora, e quem roda o setup e quem olha os processos sao trocados por gravadores. Cobre a rodada sem versao
nova, a assinatura de outra chave, o download com o hash errado, a versao nova com a Vitrola aberta (fica baixada e
nao instala) e depois de fechar (instala sem baixar de novo, em silencio e sem /reabrir), o setup trocado depois de
conferido (nao roda), a rodada seguinte ao instalador (instalada, ou erro se a versao nao mudou), o lado da tela (o
estado da tarefa no formato do app, e o Instalar agora, que marca o reabrir) e o ao_sair (so dispara com a versao
pronta). Sai 1 se algo falhar.

    python dev/testa_atualizador.py
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
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atualizacao as atu  # noqa: E402
import atualizador  # noqa: E402
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


tmp = Path(tempfile.mkdtemp(prefix="vitrola-atualizador-"))
www = tmp / "www"
www.mkdir()
atualizador.PASTA = tmp / "app" / "atualizacao"
pedidos = []


class Conta(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        pedidos.append(self.path)
        super().do_GET()


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Conta, directory=str(www)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
chave = ECC.generate(curve="Ed25519")
outra = ECC.generate(curve="Ed25519")
CHAVES = {1: base64.b64encode(chave.public_key().export_key(format="raw")).decode()}
atualizador._config = lambda: (f"{base}/manifest.json", CHAVES, False)

setup = os.urandom(2 << 20)
(www / "setup.exe").write_bytes(setup)
SHA = hashlib.sha256(setup).hexdigest()
NOVA = mais(VERSAO)


def publica(versao=NOVA, k=chave, sha=SHA):
    m = {"formato": 1, "app": "vitrola", "versao": versao, "data": "2026-11-18", "notas": ["Uma coisa nova."],
         "notas_en": ["A new thing."], "instalador": {"url": f"{base}/setup.exe", "sha256": sha, "tamanho": len(setup)},
         "arquivos": [{"caminho": "vitrola.exe", "sha256": SHA, "tamanho": 1}]}
    dados = json.dumps(m).encode()
    (www / "manifest.json").write_bytes(dados)
    sig = json.dumps({"chave": 1, "assinatura": base64.b64encode(eddsa.new(k, "rfc8032").sign(dados)).decode()})
    (www / "manifest.json.sig").write_text(sig)


aberta = [False]
lancados = []
vivos = set()
atualizador.app_aberta = lambda: aberta[0]
atualizador.vivo = lambda pid: pid in vivos


def lanca(setup_, log_setup):
    lancados.append((Path(setup_), list(atualizador.PARAMETROS), Path(log_setup)))
    return 424242


atualizador._lanca = lanca


def limpa():
    for f in atualizador.PASTA.glob("*"):
        f.unlink()
    lancados.clear()
    pedidos.clear()


print("--- a rodada")
atualizador.PASTA.mkdir(parents=True)
publica(versao=VERSAO)
atualizador.rodada(espera_fechar=0)
e = atualizador.estado()
caso("sem versao nova: parado, nada baixado", e.get("estado") == "parado" and not lancados
     and "/setup.exe" not in pedidos, e)

limpa()
publica(k=outra)
atualizador.rodada(espera_fechar=0)
e = atualizador.estado()
caso("assinado por outra chave: recusa e nao baixa", e.get("estado") == "parado" and e.get("erro")
     and "/setup.exe" not in pedidos and not lancados, e.get("erro"))

limpa()
publica(sha="0" * 64)
atualizador.rodada(espera_fechar=0)
e = atualizador.estado()
caso("hash do setup errado: nao fica nada, nao instala", e.get("estado") == "parado" and e.get("erro") and not lancados
     and not list(atualizador.PASTA.glob("Vitrola-*")), e.get("erro"))

limpa()
publica()
aberta[0] = True
atualizador.rodada(espera_fechar=0)
e = atualizador.estado()
baixado = atualizador.PASTA / f"Vitrola-{NOVA}-setup.exe"
caso("versao nova com a Vitrola aberta: fica baixada e conferida, e nao instala",
     e.get("estado") == "pronta" and baixado.exists() and atu._hash(baixado) == SHA and not lancados, e.get("estado"))
caso("o estado leva o que a tela mostra (versao, notas, tamanho)",
     e.get("nova", {}).get("versao") == NOVA and e["nova"].get("notas_en") == ["A new thing."]
     and e["nova"].get("tamanho") == len(setup), e.get("nova"))

pedidos.clear()
aberta[0] = False
atualizador.rodada(espera_fechar=0)
e = atualizador.estado()
caso("a Vitrola fechou: instala sem baixar de novo", lancados and "/setup.exe" not in pedidos, pedidos)
if lancados:
    s, params, lg = lancados[0]
    caso("o instalador e o conferido, em silencio e sem /reabrir",
         s == baixado and "/VERYSILENT" in params and not any("reabrir" in p for p in params)
         and lg.parent == atualizador.PASTA, (s, params))
caso("o estado diz instalando, com o pid e a versao", e.get("estado") == "instalando" and e.get("pid") == 424242
     and e.get("versao") == NOVA, e)

lancados.clear()
atualizador.rodada(espera_fechar=0)
e = atualizador.estado()
caso("o instalador terminou sem trocar a versao: conta a falha e tenta de novo",
     len(lancados) == 1 and e.get("falhas") == {NOVA: 1} and e.get("estado") == "instalando", e.get("falhas"))
lancados.clear()
atualizador.rodada(espera_fechar=0)
e = atualizador.estado()
caso(f"falhou {atualizador.TENTATIVAS} vezes: nao roda mais, espera a proxima versao, e a tela ve o motivo",
     not lancados and e.get("falhas") == {NOVA: 2} and e.get("estado") == "parado" and "failed 2 times" in str(e.get("erro")),
     e.get("erro"))
publica(versao=mais(VERSAO, 2))
atualizador.rodada(espera_fechar=0)
caso("a proxima versao tenta normalmente", len(lancados) == 1, atualizador.estado().get("estado"))
publica()

limpa()
atualizador._grava(estado="instalando", pid=999, versao=VERSAO, de="0.0.1", log="x.log")
publica(versao=VERSAO)
atualizador.rodada(espera_fechar=0)
e = atualizador.estado()
caso("o instalador terminou e esta e a versao dele: instalada", e.get("instalada") == VERSAO and not e.get("erro"), e)

print("--- o setup trocado depois de conferido")
limpa()
falso = atualizador.PASTA / f"Vitrola-{NOVA}-setup.exe"
falso.write_bytes(setup[:-1] + b"X")
atualizador.instala(falso, SHA, NOVA)
e = atualizador.estado()
caso("nao roda, apaga e volta a baixar na proxima", not lancados and not falso.exists() and e.get("estado") == "parado"
     and e.get("erro"), e.get("erro"))

print("--- o lado da tela")
limpa()
atualizador._grava(estado="pronta", progresso=1.0, nova={"versao": NOVA, "data": "2026-11-18", "notas": ["Uma."],
                                                          "notas_en": ["One."], "tamanho": 123, "parcial": False})
a = atu.Atualizacao(ativa=True)
a.auto = True
p = a.publico()
caso("a tela ve a versao pronta, automatica", p["estado"] == "pronta" and p["automatica"] and p["nova"]["versao"] == NOVA
     and p["nova"]["notas"] == {"pt_BR": ["Uma."], "en": ["One."]}, p)
caso("o resumo do estado ao vivo tambem", a.resumo()["estado"] == "pronta" and a.resumo()["automatica"])
atu.REABRIR = False
ok, motivo = a.instalar()
caso("Instalar agora: marca o reabrir, sem abrir nada", ok and motivo is None and atu.REABRIR is True)
atualizador._grava(estado="parado", nova=None)
atu.REABRIR = False
ok, motivo = a.instalar()
caso("Instalar agora sem a versao baixada: recusa", not ok and motivo and atu.REABRIR is False, motivo)
atualizador._grava(estado="pronta", nova={"versao": "0.0.1", "tamanho": 1})
caso("versao mais velha no estado: a tela nao mostra", a.publico()["nova"] is None and a.publico()["estado"] == "parado")

if sys.platform == "win32":
    print("--- o reabre, com o PowerShell de verdade (no lugar de abrir a Vitrola, ele grava uma marca)")
    import subprocess
    import time
    popen = subprocess.Popen
    capturado = []
    subprocess.Popen = lambda args, **kw: capturado.append((args, kw))
    try:
        atualizador.reabre()
    finally:
        subprocess.Popen = popen
    args, kw = capturado[0]
    marca = tmp / "reabriu.txt"
    exe = str(atualizador.pastas.APP / "vitrola.exe")
    trocado = args[-1].replace(f"Start-Process -FilePath '{exe}'", f"Set-Content -LiteralPath '{marca}' -Value ok")
    caso("no fim, abre a Vitrola da pasta do app", trocado != args[-1])
    atualizador._grava(estado="pronta")
    try:
        popen([*args[:-1], trocado], **kw)
    except OSError:  # fora de um job que deixa sair dele (o reabre faz o mesmo)
        popen([*args[:-1], trocado], **dict(kw, creationflags=kw["creationflags"] & ~0x01000000))
    time.sleep(2)
    caso("antes de o instalador comecar, nao abre", not marca.exists())
    dorme = popen([sys.executable, "-c", "import time; time.sleep(3)"])
    atualizador._grava(estado="instalando", pid=dorme.pid)
    time.sleep(1.5)
    caso("com o instalador rodando, espera", not marca.exists())
    dorme.wait()
    fim = time.monotonic() + 15
    while not marca.exists() and time.monotonic() < fim:
        time.sleep(0.2)
    caso("o instalador terminou: abre (com as flags do reabre, o PowerShell escondido roda)", marca.exists())

print("--- o ao_sair")
disparos, reaberturas = [], []
atualizador.dispara = lambda: disparos.append(1) or True
atualizador.reabre = lambda: reaberturas.append(1)
atualizador._grava(estado="parado", nova=None)
atualizador.ao_sair(reabrir=True)
caso("sem versao pronta: nao dispara", not disparos and not reaberturas)
atualizador._grava(estado="pronta", nova={"versao": NOVA, "tamanho": 1})
atualizador.ao_sair()
caso("com a versao pronta: dispara, e so reabre se pediram", disparos == [1] and not reaberturas)
atualizador.ao_sair(reabrir=True)
caso("Instalar agora: dispara e reabre", len(disparos) == 2 and reaberturas == [1])

print("--- a tarefa e os processos")
x = ET.fromstring(atualizador.TAREFA_XML.split("\n", 1)[1].replace("{exe}", r"C:\Program Files\Vitrola\vitrola.exe"))
ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
caso("a tarefa roda como SYSTEM o vitrola.exe com --atualizador",
     x.find(".//t:Principal/t:UserId", ns).text == "S-1-5-18"
     and x.find(".//t:Exec/t:Arguments", ns).text == "--atualizador"
     and x.find(".//t:Exec/t:Command", ns).text.endswith("vitrola.exe"))
caso("no logon e de 4 em 4 horas, uma por vez", x.find(".//t:LogonTrigger", ns) is not None
     and x.find(".//t:Repetition/t:Interval", ns).text == "PT4H"
     and x.find(".//t:MultipleInstancesPolicy", ns).text == "IgnoreNew")
caso("quem usa o PC so le e roda a tarefa (nao muda)",
     x.find(".//t:SecurityDescriptor", ns).text == "D:(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;AU)")
if sys.platform == "win32":
    caso("os processos da maquina, sem abrir nenhum", any(p == os.getpid() for p, _ in atualizador._processos()))

if sys.platform == "win32":
    # a tela lendo o estado.json no instante em que a tarefa grava: o Windows recusa trocar o arquivo aberto, e a
    # rodada desistia no meio do download (esteira, 18/11). Agora espera a leitura acabar
    print("--- o estado.json aberto pela tela")
    atualizador._grava(estado="parado")
    leitor = open(atualizador.PASTA / "estado.json", encoding="utf-8")
    solta = threading.Timer(0.4, leitor.close)
    solta.start()
    try:
        t0 = time.monotonic()
        atualizador._grava(estado="baixando", progresso=0.5)
        caso("grava depois que a tela solta o arquivo", atualizador.estado().get("progresso") == 0.5,
             f"{time.monotonic() - t0:.2f} s")
    except PermissionError as ex:
        caso("grava depois que a tela solta o arquivo", False, str(ex))
    finally:
        solta.cancel()
        leitor.close()

srv.shutdown()
print(f"\n{'tudo certo' if not falhas else f'{len(falhas)} falharam: ' + ', '.join(falhas)}")
sys.exit(1 if falhas else 0)
