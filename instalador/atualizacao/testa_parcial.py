"""Testes do parcial.py e da parcial no publica.py, com um build de mentira e uma chave de teste gerada na hora.

    python testa_parcial.py

Precisa do pycryptodomex (o venv do build tem). Cada caso roda o script de verdade, num processo a parte, e confere o
codigo de saida e o que ele gravou: a pasta da parcial (o que mudou, o que entrou e o que saiu, com o { de um nome
dobrado para o Inno) e o manifesto com a parcial.

The manifest goes out unsigned: publica.py takes no key (the ritmelli-server pipeline signs it).
"""
import ast
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


tmp = Path(tempfile.mkdtemp(prefix="ritmelli-parcial-"))
chave = ECC.generate(curve="Ed25519")
outra = ECC.generate(curve="Ed25519")
key_two = ECC.generate(curve="Ed25519")
pub, pub2 = (base64.b64encode(k.public_key().export_key(format="raw")).decode() for k in (chave, key_two))
app_py = tmp / "atualizacao.py"
app_py.write_text(f'MANIFESTO = "x"\nCHAVES = {{1: "{pub}", 2: "{pub2}"}}\n', encoding="utf-8")
arq_chave = tmp / "teste.key"
arq_chave.write_text(base64.b64encode(chave.seed).decode() + "\n", encoding="ascii")

# o build anterior, como o manifesto dele descreve, e o build novo. Os dois com a sentinela da pasta protegida (o
# parcial.py so tira parcial de uma anterior que ja a tem, igual)
SENTINELA = "_internal/pasta-protegida.txt"
SENT = (AQUI.parent / "pasta-protegida.txt").read_bytes()
antes = {"ritmelli.exe": b"exe velho", "_internal/igual.dll": b"igual", "_internal/sai.pyd": b"so na anterior",
         "_internal/{chave}/muda.txt": b"velho", "bin/ffmpeg.exe": b"ffmpeg", SENTINELA: SENT}
dist, binf = tmp / "dist" / "ritmelli", tmp / "bin"
for c, d in {"ritmelli.exe": b"exe novo", "_internal/igual.dll": b"igual", "_internal/{chave}/muda.txt": b"novo",
             "_internal/novo/entra.pyd": b"so na nova", SENTINELA: SENT}.items():
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
     sorted(info.get("arquivos", [])) == ["_internal/novo/entra.pyd", "_internal/{chave}/muda.txt", "ritmelli.exe"],
     info)
caso("apaga o que a nova nao tem", info.get("apaga") == ["_internal/sai.pyd"] and info.get("de") == "0.3.3", info)
caso("os arquivos da parcial sao os do build novo, nos caminhos do app",
     (saida / "arquivos" / "_internal" / "{chave}" / "muda.txt").read_bytes() == b"novo"
     and (saida / "arquivos" / "ritmelli.exe").read_bytes() == b"exe novo"
     and not (saida / "arquivos" / "_internal" / "igual.dll").exists() and not (saida / "arquivos" / "bin").exists())
apaga = (saida / "apaga.iss").read_text(encoding="utf-8-sig")
caso("o apaga.iss no formato do Inno", 'Type: files; Name: "{app}\\_internal\\sai.pyd"' in apaga, apaga)

escape = manifesto_anterior(tmp / "ant-escape", {**antes, "_internal/{chave}/sai.txt": b"x"})
cod, out = roda("parcial.py", "--anterior", escape, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
apaga = (saida / "apaga.iss").read_text(encoding="utf-8-sig")
caso("a { de um nome sai dobrada (no Inno, ela abre uma constante)",
     cod == 0 and 'Name: "{app}\\_internal\\{{chave}\\sai.txt"' in apaga, apaga)

igual = manifesto_anterior(tmp / "ant-igual", {**{c: (dist / c).read_bytes() for c in
                                                    ("ritmelli.exe", "_internal/igual.dll", "_internal/{chave}/muda.txt",
                                                     "_internal/novo/entra.pyd", SENTINELA)}, "bin/ffmpeg.exe": b"ffmpeg"})
cod, out = roda("parcial.py", "--anterior", igual, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
caso("nada mudou: sem o parcial.json", cod == 0 and not (saida / "parcial.json").exists() and "nada mudou" in out, out)

# a sentinela da pasta protegida: as versoes de antes dela nao conferem a pasta, e so caem no setup completo enquanto a
# parcial nao traz a sentinela
cod, out = roda("parcial.py", "--anterior", ant, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
info = json.loads((saida / "parcial.json").read_text(encoding="utf-8")) if cod == 0 else {}
caso("a anterior com a sentinela igual: a parcial sai, e sem a sentinela",
     cod == 0 and info.get("arquivos") and SENTINELA not in info["arquivos"]
     and not (saida / "arquivos" / "_internal" / "pasta-protegida.txt").exists(), info)
sem = manifesto_anterior(tmp / "ant-sem-sentinela", {c: d for c, d in antes.items() if c != SENTINELA})
cod, out = roda("parcial.py", "--anterior", sem, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
caso("a anterior sem a sentinela: sem o parcial.json (a versao vai so com o setup completo)",
     cod == 0 and not (saida / "parcial.json").exists() and "pasta-protegida" in out, out)
outra_s = manifesto_anterior(tmp / "ant-outra-sentinela", {**antes, SENTINELA: SENT + b" "})
cod, out = roda("parcial.py", "--anterior", outra_s, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
caso("a anterior com outra sentinela: sem o parcial.json", cod == 0 and not (saida / "parcial.json").exists(), out)
(dist / SENTINELA).unlink()
cod, out = roda("parcial.py", "--anterior", ant, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
caso("o build sem a sentinela: recusa", cod != 0 and "pasta-protegida" in out, out)
(dist / SENTINELA).write_bytes(SENT)

# a anterior de antes da troca de nome (#58): o vitrola.exe no lugar do ritmelli.exe, e a parcial nao serve
velha = manifesto_anterior(tmp / "ant-vitrola", {("vitrola.exe" if c == "ritmelli.exe" else c): d for c, d in antes.items()})
cod, out = roda("parcial.py", "--anterior", velha, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
caso("a anterior de antes da troca de nome: sem o parcial.json",
     cod == 0 and not (saida / "parcial.json").exists() and "troca de nome" in out, out)

for nome, pasta in (("o manifesto anterior mexido depois de assinado",
                     manifesto_anterior(tmp / "a1", antes, mexe=True)),
                    ("o manifesto assinado por outra chave", manifesto_anterior(tmp / "a2", antes, k=outra)),
                    ("a chave que o app nao conhece", manifesto_anterior(tmp / "a3", antes, numero=3)),
                    ("a signature of key 1 labelled as key 2", manifesto_anterior(tmp / "a4", antes, numero=2)),
                    ("a signature of key 2 labelled as key 1", manifesto_anterior(tmp / "a5", antes, k=key_two))):
    cod, out = roda("parcial.py", "--anterior", pasta, "--app-py", app_py, "--app", dist, "--bin", binf,
                    "--saida", saida)
    caso(f"recusa {nome}", cod != 0 and "nao confere" in out, out)

cod, out = roda("parcial.py", "--anterior", manifesto_anterior(tmp / "a6", antes, k=key_two, numero=2),
                "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
caso("a previous manifest signed by key 2, labelled 2, is accepted",
     cod == 0 and (saida / "parcial.json").exists(), out)

print("--- a parcial no publica.py")
roda("parcial.py", "--anterior", ant, "--app-py", app_py, "--app", dist, "--bin", binf, "--saida", saida)
saida_m = tmp / "saida"
saida_m.mkdir()
setup = saida_m / "Ritmelli-0.3.4-setup.exe"
setup.write_bytes(b"setup completo")
parc = saida_m / "Ritmelli-0.3.4-parcial.exe"
parc.write_bytes(b"setup parcial")
url = "https://github.com/ritmelli/ritmelli-releases/releases/download/v0.3.4/Ritmelli-0.3.4-setup.exe"
base = ["--setup", setup, "--url", url, "--app", dist, "--bin", binf, "--saida", saida_m]
cod, out = roda("publica.py", *base, "--parcial", parc, "--parcial-info", saida / "parcial.json")
m = json.loads((saida_m / "manifest.json").read_text(encoding="utf-8")) if cod == 0 else {}
p = m.get("parcial", {})
caso("the manifest with the partial is written, and no .sig", cod == 0 and m and not list(saida_m.rglob("*.sig")), out)
full_only = tmp / "saida-full-only"
full_only.mkdir()
full_setup = full_only / setup.name
shutil.copy(setup, full_setup)
full_cod, full_out = roda("publica.py", "--setup", full_setup, "--url", url, "--app", dist, "--bin", binf,
                          "--saida", full_only)
caso("the manifest without a partial is written, and no .sig",
     full_cod == 0 and (full_only / "manifest.json").exists() and not list(full_only.rglob("*.sig")), full_out)
caso("o manifesto leva a parcial", cod == 0 and p.get("sha256") == sha(b"setup parcial") and p.get("tamanho") == 13
     and p.get("de") == "0.3.3" and p.get("apaga") == ["_internal/sai.pyd"], out)
caso("a parcial no mesmo endereco do setup",
     p.get("url") == url.replace("-setup.exe", "-parcial.exe"),
     p.get("url"))
# o "app" de antes da troca de nome (#58): a 0.4.1 e o Ritmelli ate a 0.6.0 so aceitam o manifesto com ele (o APP do
# publica.py diz quando ele pode trocar)
caso("o manifesto sai com o app vitrola, o que as versoes instaladas conferem", m.get("app") == "vitrola",
     m.get("app"))
caminhos = {f["caminho"] for f in m.get("arquivos", [])}
caso("tudo que a parcial traz esta na lista de arquivos", set(p.get("arquivos", [])) <= caminhos and caminhos)
cod, out = roda("publica.py", *base, "--parcial", parc)
caso("o --parcial sem o --parcial-info e recusado", cod != 0 and "juntos" in out, out)
cod, out = roda("publica.py", *base, "--parcial", saida_m / "outro-nome.exe", "--parcial-info", saida / "parcial.json")
caso("a parcial com outro nome e recusada", cod != 0 and "Ritmelli-0.3.4-parcial.exe" in out, out)
errado = tmp / "parcial-errado.json"
errado.write_text(json.dumps({"de": "0.3.3", "arquivos": ["_internal/nao-existe.dll"], "apaga": []}), encoding="utf-8")
cod, out = roda("publica.py", *base, "--parcial", parc, "--parcial-info", errado)
caso("um parcial.json de outro build e recusado", cod != 0 and "nao bate" in out, out)

print("--- publica.py does not sign")
for flag in (["--chave", arq_chave], ["--assina", saida_m / "manifest.json"]):
    (saida_m / "manifest.json.sig").unlink(missing_ok=True)
    cod, out = roda("publica.py", *base, *flag)
    caso(f"{flag[0]} is refused and no manifest.json.sig is written",
         cod != 0 and "unrecognized arguments" in out and not (saida_m / "manifest.json.sig").exists(), out)


def signature_imports(source):
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.startswith("Cryptodome.Signature")]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("Cryptodome.Signature"):
                found.append(node.module)
            elif node.module == "Cryptodome":
                found += [f"Cryptodome.{a.name}" for a in node.names if a.name == "Signature"]
    return found


print("--- publica.py imports no signing code")
publica = (AQUI / "publica.py").read_text(encoding="utf-8")
caso("publica.py imports nothing from Cryptodome.Signature", signature_imports(publica) == [],
     signature_imports(publica))
for form in ("from Cryptodome.Signature import eddsa", "import Cryptodome.Signature.eddsa",
             "from Cryptodome import Signature", "def main():\n    from Cryptodome.Signature import eddsa"):
    caso(f"the check catches {form!r}", signature_imports(f"{publica}\n{form}\n") != [])

shutil.rmtree(tmp, ignore_errors=True)
print("tudo certo" if not falhas else f"FALHAS: {', '.join(falhas)}")
sys.exit(1 if falhas else 0)
