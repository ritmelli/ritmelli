"""O manifesto de uma versao nova e a assinatura dele, para o atualizador do app (atualizacao.py, no repo vitrola).

    python publica.py --setup <Vitrola-X.Y.Z-setup.exe> --url <endereco https do setup> --app <dist\\vitrola do build>
                      --bin <pasta> [--bin <pasta> ...] [--notas notas.txt] --saida <pasta>
                      [--parcial <Vitrola-X.Y.Z-parcial.exe> --parcial-info <parcial.json>]
                      [--chave <arquivo.key> [--numero 1]]
    python publica.py --assina <manifest.json> --setup <Vitrola-X.Y.Z-setup.exe> [--parcial <Vitrola-X.Y.Z-parcial.exe>]
                      --chave <arquivo.key> [--numero 1] [--app-py <atualizacao.py do app>]

A primeira forma grava o manifest.json na pasta de saida e, com a --chave, tambem o manifest.json.sig. A segunda so
assina um manifest.json que ja existe: e a da esteira, que monta o manifesto no job do build, sem a chave, e assina num
job a parte, que nao instala os pacotes do app. Antes de assinar, ela confere que o manifesto descreve aquele setup (e
aquela parcial, se ele tiver uma) e, com o --app-py, que a chave e a do numero no CHAVES do app: com outra, o app
recusaria a versao.

Os dois arquivos vao para o mesmo endereco, um ao lado do outro, e o setup para o --url. O caminho A usa so o
instalador: o app baixa, confere o tamanho e o hash e roda. O caminho B e a parcial: um setup so com os arquivos que
mudaram desde a versao anterior (o parcial.py separa, e o --parcial-info e o parcial.json dele), no mesmo endereco do
setup. O app so usa a parcial se o que esta instalado bater com a lista de arquivos (o --app e as --bin, que o
instalador poe em bin\\) em tudo que ela nao traz. A versao sai do nome do setup. As notas: uma por linha, no maximo 30.
O --numero e o da chave no CHAVES do app. No fim, a assinatura e conferida de novo com a chave publica.
"""
import argparse
import ast
import base64
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from Cryptodome.Signature import eddsa


def sha(arq):
    h = hashlib.sha256()
    with open(arq, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def fontes(app, bins):
    """Caminho no app instalado -> arquivo do build: o dist\\vitrola (menos uma bin\\ que tenha sobrado nele) e o que
    as --bin poem na bin\\ (menos o ffplay.exe, que o app nao usa). O manifesto e a parcial saem daqui."""
    out = {}
    for f in sorted(p for p in app.rglob("*") if p.is_file() and "bin" not in p.relative_to(app).parts[:1]):
        out[f.relative_to(app).as_posix()] = f
    for b in bins:
        for f in sorted(p for p in b.iterdir() if p.is_file() and p.name != "ffplay.exe"):
            out[f"bin/{f.name}"] = f
    return out


def arquivos(app, bins):
    return [{"caminho": c, "sha256": sha(f), "tamanho": f.stat().st_size} for c, f in fontes(app, bins).items()]


def parcial(arq, url_setup, info, caminhos):
    """A entrada "parcial" do manifesto: o setup parcial (no endereco do setup completo) e o parcial.json do
    parcial.py, com o que ela traz e o que ela apaga."""
    info = json.loads(info.read_text(encoding="utf-8"))
    if not set(info["arquivos"]) <= caminhos or set(info["apaga"]) & caminhos:
        sys.exit("o parcial.json nao bate com os arquivos deste build: rode o parcial.py de novo")
    return {"url": f"{url_setup.rsplit('/', 1)[0]}/{arq.name}", "sha256": sha(arq), "tamanho": arq.stat().st_size,
            "de": info["de"], "arquivos": info["arquivos"], "apaga": info["apaga"]}


def chaves_do_app(arq):
    """O CHAVES do atualizacao.py, lido sem importar o modulo (ele puxa o resto do app)."""
    for n in ast.parse(arq.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CHAVES" for t in n.targets):
            return ast.literal_eval(n.value)
    sys.exit(f"nao achei o CHAVES em {arq}")


def assina(dados, chave, numero, saida, chaves=None):
    """Grava o manifest.json.sig de dados (os bytes do manifest.json) e volta a chave publica."""
    k = eddsa.import_private_key(base64.b64decode(chave.read_text(encoding="ascii").strip(), validate=True))
    pub = base64.b64encode(k.public_key().export_key(format="raw")).decode()
    if chaves is not None and chaves.get(numero) != pub:
        sys.exit(f"a chave que assina nao e a {numero} do CHAVES do app: o app recusaria a versao")
    assinatura = eddsa.new(k, "rfc8032").sign(dados)
    eddsa.new(k.public_key(), "rfc8032").verify(dados, assinatura)
    (saida / "manifest.json.sig").write_text(
        json.dumps({"chave": numero, "assinatura": base64.b64encode(assinatura).decode()}) + "\n", encoding="ascii")
    return pub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", type=Path, required=True)
    ap.add_argument("--url")
    ap.add_argument("--chave", type=Path)
    ap.add_argument("--app", type=Path)
    ap.add_argument("--bin", type=Path, action="append", default=[])
    ap.add_argument("--notas", type=Path)
    ap.add_argument("--numero", type=int, default=1)
    ap.add_argument("--saida", type=Path)
    ap.add_argument("--assina", type=Path)
    ap.add_argument("--app-py", type=Path)
    ap.add_argument("--parcial", type=Path)
    ap.add_argument("--parcial-info", type=Path)
    a = ap.parse_args()
    v = re.fullmatch(r"Vitrola-(\d+\.\d+\.\d+)-setup\.exe", a.setup.name)
    if not v:
        sys.exit(f"o setup tem de se chamar Vitrola-X.Y.Z-setup.exe, e nao {a.setup.name}")
    if a.parcial and a.parcial.name != f"Vitrola-{v.group(1)}-parcial.exe":
        sys.exit(f"a parcial tem de se chamar Vitrola-{v.group(1)}-parcial.exe, e nao {a.parcial.name}")
    chaves = chaves_do_app(a.app_py) if a.app_py else None

    if a.assina:
        if not a.chave:
            sys.exit("o --assina precisa da --chave")
        dados = a.assina.read_bytes()
        m = json.loads(dados)
        inst = m["instalador"]
        if m["versao"] != v.group(1) or inst["url"].rsplit("/", 1)[-1] != a.setup.name:
            sys.exit(f"o manifesto e da versao {m['versao']} ({inst['url']}), e nao do {a.setup.name}")
        if inst["tamanho"] != a.setup.stat().st_size or inst["sha256"] != sha(a.setup):
            sys.exit(f"o {a.setup.name} nao e o que o manifesto descreve (tamanho ou hash)")
        p = m.get("parcial")
        if bool(p) != bool(a.parcial):
            sys.exit("o manifesto tem a parcial, e o --parcial nao veio" if p else
                     "o --parcial veio, e o manifesto nao tem a parcial")
        if p and (p["url"].rsplit("/", 1)[-1] != a.parcial.name or p["tamanho"] != a.parcial.stat().st_size
                  or p["sha256"] != sha(a.parcial)):
            sys.exit(f"o {a.parcial.name} nao e a parcial que o manifesto descreve (nome, tamanho ou hash)")
        pub = assina(dados, a.chave, a.numero, a.assina.parent, chaves)
        print(f"versao {m['versao']}: manifesto assinado com a chave {a.numero} ({pub}), em {a.assina.parent}")
        return

    if not (a.url and a.app and a.saida):
        sys.exit("sem o --assina, o --url, o --app e a --saida sao obrigatorios")
    if not a.url.startswith("https://"):
        sys.exit("o --url do setup tem de ser https: o app recusa outro")
    if not (a.app / "vitrola.exe").exists():
        sys.exit(f"nao achei {a.app / 'vitrola.exe'}")
    for b in a.bin:
        if not b.is_dir():
            sys.exit(f"nao achei a pasta {b}")
    # utf-8-sig: o Bloco de Notas pode gravar o BOM, que viraria parte da primeira nota
    notas = [n.strip() for n in a.notas.read_text(encoding="utf-8-sig").splitlines() if n.strip()] if a.notas else []
    if len(notas) > 30 or any(len(n) > 500 for n in notas):
        sys.exit("notas demais, ou uma passa de 500 letras")
    if bool(a.parcial) != bool(a.parcial_info):
        sys.exit("o --parcial e o --parcial-info vem juntos")
    m = {"formato": 1, "app": "vitrola", "versao": v.group(1), "data": time.strftime("%Y-%m-%d"), "notas": notas,
         "instalador": {"url": a.url, "sha256": sha(a.setup), "tamanho": a.setup.stat().st_size},
         "arquivos": arquivos(a.app, a.bin)}
    if a.parcial:
        # um campo a mais no formato 1: o app que nao conhece a parcial nao olha para ela e baixa o setup completo
        m["parcial"] = parcial(a.parcial, a.url, a.parcial_info, {f["caminho"] for f in m["arquivos"]})
    dados = json.dumps(m, ensure_ascii=False, indent=1).encode("utf-8")
    a.saida.mkdir(parents=True, exist_ok=True)
    (a.saida / "manifest.json").write_bytes(dados)
    print(f"versao {m['versao']}: setup de {m['instalador']['tamanho'] / 2**20:.0f} MB, {len(m['arquivos'])} arquivos, "
          f"{len(notas)} notas, em {a.saida}")
    if a.parcial:
        print(f"parcial de {m['parcial']['tamanho'] / 2**20:.1f} MB, desde a {m['parcial']['de']}: "
              f"{len(m['parcial']['arquivos'])} arquivos trazidos e {len(m['parcial']['apaga'])} apagados")
    if a.chave:
        pub = assina(dados, a.chave, a.numero, a.saida, chaves)
        print(f"assinado com a chave {a.numero} ({pub})")
    else:
        print("sem a --chave: o manifesto ainda nao esta assinado (python publica.py --assina)")


if __name__ == "__main__":
    main()
