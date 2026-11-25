"""O manifesto de uma versao nova, para o atualizador do app (atualizacao.py, no repo ritmelli).

    python publica.py --setup <Ritmelli-X.Y.Z-setup.exe> --url <endereco https do setup> --app <dist\\ritmelli do build>
                      --bin <pasta> [--bin <pasta> ...] [--notas notas.txt] [--notas-en notas_en.txt] --saida <pasta>
                      [--parcial <Ritmelli-X.Y.Z-parcial.exe> --parcial-info <parcial.json>]

Writes manifest.json to the output folder, unsigned. This repo holds no signing key: the publishing pipeline of the
private ritmelli-server repo signs the manifest (manifest.json.sig) after the build, with a key from the CHAVES of
atualizacao.py.

Os dois arquivos vao para o mesmo endereco, um ao lado do outro, e o setup para o --url. O caminho A usa so o
instalador: o app baixa, confere o tamanho e o hash e roda. O caminho B e a parcial: um setup so com os arquivos que
mudaram desde a versao anterior (o parcial.py separa, e o --parcial-info e o parcial.json dele), no mesmo endereco do
setup. O app so usa a parcial se o que esta instalado bater com a lista de arquivos (o --app e as --bin, que o
instalador poe em bin\\) em tudo que ela nao traz. A versao sai do nome do setup. As notas: uma por linha, no maximo 30;
as do --notas em portugues, no campo que as versoes de antes leem, e as do --notas-en em ingles, que so as de agora
mostram (na tela em ingles; sem elas, essa tela mostra as em portugues).
"""
import argparse
import ast
import hashlib
import json
import re
import sys
import time
from pathlib import Path

# o "app" do manifesto: segue "vitrola", o nome de antes da troca de nome (#58). A 0.4.1 e as anteriores e o Ritmelli
# ate a 0.6.0 so aceitam o manifesto com ele (o m["app"] == "vitrola" do atualizacao.py delas), e com outro nunca
# mais atualizariam sozinhos. As versoes depois da 0.6.0 aceitam os dois (o APPS do atualizacao.py). So troque para
# "ritmelli" quando nenhuma versao que ainda deve atualizar conferir so "vitrola": quando a mais velha que se quer
# levar a versao nova ja for uma das que aceitam os dois. Antes disso, quem esta nelas fica para tras de vez
APP = "vitrola"


def sha(arq):
    h = hashlib.sha256()
    with open(arq, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def fontes(app, bins):
    """Caminho no app instalado -> arquivo do build: o dist\\ritmelli (menos uma bin\\ que tenha sobrado nele) e o que
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", type=Path, required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--app", type=Path, required=True)
    ap.add_argument("--saida", type=Path, required=True)
    ap.add_argument("--bin", type=Path, action="append", default=[])
    ap.add_argument("--notas", type=Path)
    ap.add_argument("--notas-en", type=Path)
    ap.add_argument("--parcial", type=Path)
    ap.add_argument("--parcial-info", type=Path)
    a = ap.parse_args()
    v = re.fullmatch(r"Ritmelli-(\d+\.\d+\.\d+)-setup\.exe", a.setup.name)
    if not v:
        sys.exit(f"o setup tem de se chamar Ritmelli-X.Y.Z-setup.exe, e nao {a.setup.name}")
    if a.parcial and a.parcial.name != f"Ritmelli-{v.group(1)}-parcial.exe":
        sys.exit(f"a parcial tem de se chamar Ritmelli-{v.group(1)}-parcial.exe, e nao {a.parcial.name}")
    if not a.url.startswith("https://"):
        sys.exit("o --url do setup tem de ser https: o app recusa outro")
    if not (a.app / "ritmelli.exe").exists():
        sys.exit(f"nao achei {a.app / 'ritmelli.exe'}")
    for b in a.bin:
        if not b.is_dir():
            sys.exit(f"nao achei a pasta {b}")
    # utf-8-sig: o Bloco de Notas pode gravar o BOM, que viraria parte da primeira nota
    def le_notas(arq):
        notas = [n.strip() for n in arq.read_text(encoding="utf-8-sig").splitlines() if n.strip()] if arq else []
        if len(notas) > 30 or any(len(n) > 500 for n in notas):
            sys.exit(f"notas demais em {arq}, ou uma passa de 500 letras")
        return notas
    notas, notas_en = le_notas(a.notas), le_notas(a.notas_en)
    if bool(a.parcial) != bool(a.parcial_info):
        sys.exit("o --parcial e o --parcial-info vem juntos")
    m = {"formato": 1, "app": APP, "versao": v.group(1), "data": time.strftime("%Y-%m-%d"), "notas": notas,
         "instalador": {"url": a.url, "sha256": sha(a.setup), "tamanho": a.setup.stat().st_size},
         "arquivos": arquivos(a.app, a.bin)}
    if notas_en:
        # um campo a mais no formato 1, como a parcial: o app de antes nao olha para ele
        m["notas_en"] = notas_en
    if a.parcial:
        # um campo a mais no formato 1: o app que nao conhece a parcial nao olha para ela e baixa o setup completo
        m["parcial"] = parcial(a.parcial, a.url, a.parcial_info, {f["caminho"] for f in m["arquivos"]})
    dados = json.dumps(m, ensure_ascii=False, indent=1).encode("utf-8")
    a.saida.mkdir(parents=True, exist_ok=True)
    (a.saida / "manifest.json").write_bytes(dados)
    print(f"versao {m['versao']}: setup de {m['instalador']['tamanho'] / 2**20:.0f} MB, {len(m['arquivos'])} arquivos, "
          f"{len(notas)} notas, {len(notas_en)} em ingles, em {a.saida}")
    if a.parcial:
        print(f"parcial de {m['parcial']['tamanho'] / 2**20:.1f} MB, desde a {m['parcial']['de']}: "
              f"{len(m['parcial']['arquivos'])} arquivos trazidos e {len(m['parcial']['apaga'])} apagados")


if __name__ == "__main__":
    main()
