"""Testes do parcial.py e da parcial no publica.py, com um build de mentira e uma chave de teste gerada na hora.

    python testa_parcial.py

Precisa do pycryptodomex (o venv do build tem). Cada caso roda o script de verdade, num processo a parte, e confere o
codigo de saida e o que ele gravou: a pasta da parcial (o que mudou, o que entrou e o que saiu, com o { de um nome
dobrado para o Inno), o manifesto com a parcial e a conferencia do --assina.
"""
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from Cryptodome.PublicKey import ECC
from Cryptodome.Signature import eddsa

AQUI = Path(__file__).resolve().parent
falhas = []


def caso(nome, ok, detalhe=""):
    print(f"[{'ok' if ok else 'FALHOU'}] {nome}" + (f": {detalhe}" if detalhe and not ok else ""))
    if not ok:
        falhas.append(nome)


def roda(script, *args):
    p = subprocess.run([sys.executable, str(AQUI / script), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def sha(dados):
    return hashlib.sha256(dados).hexdigest()


tmp = Path(tempfile.mkdtemp(prefix="vitrola-parcial-"))
chave = ECC.generate(curve="Ed25519")
outra = ECC.generate(curve="Ed25519")
pub = base64.b64encode(chave.public_key().export_key(format="raw")).decode()
app_py = tmp / "atualizacao.py"
app_py.write_text(f'MANIFESTO = "x"\nCHAVES = {{1: "{pub}"}}\n', encoding="utf-8")
arq_chave = tmp / "teste.key"
arq_chave.write_text(base64.b64encode(chave.seed).decode() + "\n", encoding="ascii")

# o build anterior, como o manifesto dele descreve, e o build novo
antes = {"vitrola.exe": b"exe velho", "_internal/igual.dll": b"igual", "_internal/sai.pyd": b"so na anterior",
         "_internal/{chave}/muda.txt": b"velho", "bin/ffmpeg.exe": b"ffmpeg"}
dist, binf = tmp / "dist" / "vitrola", tmp / "bin"
for c, d in {"vitrola.exe": b"exe novo", "_internal/igual.dll": b"igual", "_internal/{chave}/muda.txt": b"novo",
             "_internal/novo/entra.pyd": b"so na nova"}.items():
    (dist / c).parent.mkdir(parents=True, exist_ok=True)
    (dist / c).write_bytes(d)
binf.mkdir()
(binf / "ffmpeg.exe").write_bytes(b"ffmpeg")


def manifesto_anterior(pasta, arquivos, k=chave, numero=1, mexe=False):
    pasta.mkdir(parents=True, exist_ok=True)
    m = {"formato": 1, "app": "vitrola", "versao": "0.3.3",
         "arquivos": [{"caminho": c, "sha256": sha(d), "tamanho": len(d)} for c, d in arquivos.items()]}
    dados = json.dumps(m).encode()
    sig = eddsa.new(k, "rfc8032").sign(dados)
    (pasta / "manifest.json").write_bytes(dados + (b" " if mexe else b""))
    s = {"chave": numero, "assinatura": base64.b64encode(sig).decode()}
    (pasta / "manifest.json.sig").write_text(json.dumps(s), encoding="ascii")
    return pasta / "manifest.json"


print("--- o parcial.py")
ant = manifesto_anterior(tmp / "ant", antes)
saida = tmp / "parcial"
cod, out = roda("parcial.py", "--anterior", ant, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
caso("separa o que mudou", cod == 0, out)
info = json.loads((saida / "parcial.json").read_text(encoding="utf-8")) if cod == 0 else {}
caso("traz o que mudou e o que entrou, e nao o que ficou igual",
     sorted(info.get("arquivos", [])) == ["_internal/novo/entra.pyd", "_internal/{chave}/muda.txt", "vitrola.exe"],
     info)
caso("apaga o que a nova nao tem", info.get("apaga") == ["_internal/sai.pyd"] and info.get("de") == "0.3.3", info)
caso("os arquivos da parcial sao os do build novo, nos caminhos do app",
     (saida / "arquivos" / "_internal" / "{chave}" / "muda.txt").read_bytes() == b"novo"
     and (saida / "arquivos" / "vitrola.exe").read_bytes() == b"exe novo"
     and not (saida / "arquivos" / "_internal" / "igual.dll").exists() and not (saida / "arquivos" / "bin").exists())
apaga = (saida / "apaga.iss").read_text(encoding="utf-8-sig")
caso("o apaga.iss no formato do Inno", 'Type: files; Name: "{app}\\_internal\\sai.pyd"' in apaga, apaga)

escape = manifesto_anterior(tmp / "ant-escape", {**antes, "_internal/{chave}/sai.txt": b"x"})
cod, out = roda("parcial.py", "--anterior", escape, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
apaga = (saida / "apaga.iss").read_text(encoding="utf-8-sig")
caso("a { de um nome sai dobrada (no Inno, ela abre uma constante)",
     cod == 0 and 'Name: "{app}\\_internal\\{{chave}\\sai.txt"' in apaga, apaga)

igual = manifesto_anterior(tmp / "ant-igual", {**{c: (dist / c).read_bytes() for c in
                                                    ("vitrola.exe", "_internal/igual.dll", "_internal/{chave}/muda.txt",
                                                     "_internal/novo/entra.pyd")}, "bin/ffmpeg.exe": b"ffmpeg"})
cod, out = roda("parcial.py", "--anterior", igual, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
caso("nada mudou: sem o parcial.json", cod == 0 and not (saida / "parcial.json").exists() and "nada mudou" in out, out)

for nome, pasta in (("o manifesto anterior mexido depois de assinado",
                     manifesto_anterior(tmp / "a1", antes, mexe=True)),
                    ("o manifesto assinado por outra chave", manifesto_anterior(tmp / "a2", antes, k=outra)),
                    ("a chave que o app nao conhece", manifesto_anterior(tmp / "a3", antes, numero=2))):
    cod, out = roda("parcial.py", "--anterior", pasta, "--app-py", app_py, "--app", dist, "--bin", binf,
                    "--saida", saida)
    caso(f"recusa {nome}", cod != 0 and "nao confere" in out, out)

print("--- a parcial no publica.py")
roda("parcial.py", "--anterior", ant, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
saida_m = tmp / "saida"
saida_m.mkdir()
setup = saida_m / "Vitrola-0.3.4-setup.exe"
setup.write_bytes(b"setup completo")
parc = saida_m / "Vitrola-0.3.4-parcial.exe"
parc.write_bytes(b"setup parcial")
url = "https://github.com/ritmelli/ritmelli-releases/releases/download/v0.3.4/Vitrola-0.3.4-setup.exe"
base = ["--setup", setup, "--url", url, "--app", dist, "--bin", binf, "--saida", saida_m]
cod, out = roda("publica.py", *base, "--parcial", parc, "--parcial-info", saida / "parcial.json")
m = json.loads((saida_m / "manifest.json").read_text(encoding="utf-8")) if cod == 0 else {}
p = m.get("parcial", {})
caso("o manifesto leva a parcial", cod == 0 and p.get("sha256") == sha(b"setup parcial") and p.get("tamanho") == 13
     and p.get("de") == "0.3.3" and p.get("apaga") == ["_internal/sai.pyd"], out)
caso("a parcial no mesmo endereco do setup",
     p.get("url") == url.replace("-setup.exe", "-parcial.exe"),
     p.get("url"))
caminhos = {f["caminho"] for f in m.get("arquivos", [])}
caso("tudo que a parcial traz esta na lista de arquivos", set(p.get("arquivos", [])) <= caminhos and caminhos)
cod, out = roda("publica.py", *base, "--parcial", parc)
caso("o --parcial sem o --parcial-info e recusado", cod != 0 and "juntos" in out, out)
cod, out = roda("publica.py", *base, "--parcial", saida_m / "outro-nome.exe", "--parcial-info", saida / "parcial.json")
caso("a parcial com outro nome e recusada", cod != 0 and "Vitrola-0.3.4-parcial.exe" in out, out)
errado = tmp / "parcial-errado.json"
errado.write_text(json.dumps({"de": "0.3.3", "arquivos": ["_internal/nao-existe.dll"], "apaga": []}), encoding="utf-8")
cod, out = roda("publica.py", *base, "--parcial", parc, "--parcial-info", errado)
caso("um parcial.json de outro build e recusado", cod != 0 and "nao bate" in out, out)

print("--- o --assina com a parcial")
roda("publica.py", *base, "--parcial", parc, "--parcial-info", saida / "parcial.json")
assina = ["--assina", saida_m / "manifest.json", "--setup", setup, "--chave", arq_chave, "--app-py", app_py]
cod, out = roda("publica.py", *assina, "--parcial", parc)
caso("assina com a parcial certa", cod == 0 and (saida_m / "manifest.json.sig").exists(), out)
cod, out = roda("publica.py", *assina)
caso("o manifesto com a parcial e sem o --parcial e recusado", cod != 0 and "nao veio" in out, out)
shutil.copy(parc, tmp / "guarda.exe")
parc.write_bytes(b"setup parcial trocado")
cod, out = roda("publica.py", *assina, "--parcial", parc)
caso("a parcial trocada depois do manifesto e recusada", cod != 0 and "nao e a parcial" in out, out)
shutil.copy(tmp / "guarda.exe", parc)
roda("publica.py", *base)
cod, out = roda("publica.py", *assina, "--parcial", parc)
caso("o --parcial num manifesto sem a parcial e recusado", cod != 0 and "nao tem a parcial" in out, out)

shutil.rmtree(tmp, ignore_errors=True)
print("tudo certo" if not falhas else f"FALHAS: {', '.join(falhas)}")
sys.exit(1 if falhas else 0)
