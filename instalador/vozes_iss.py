"""As vozes do pedal de troca de voz no instalador (#129): do vozes.json da raiz, gera o vozes.iss que o ritmelli.iss
inclui e o licenca-vozes.txt da pagina de aceite (o LICENSE.md das releases das vozes, baixado aqui e conferido pelo
sha256 do vozes.json). O monta.ps1 chama antes do ISCC.

O vozes.iss traz a lista dos arquivos (VozesLista: tag|nome|sha256 de cada um, separados por ;), que o [Code] do
ritmelli.iss baixa do GitHub para a {tmp} no clique de Instalar, antes de a instalacao mexer em qualquer coisa (um
download que falha numa atualizacao em silencio nao deixa o app pela metade), e uma linha do [Files] por arquivo, que
copia o baixado para {app}\\vozes\\<tag>. O que ja esta instalado com o sha256 certo nao baixa (o FaltaVoz).

    python instalador/vozes_iss.py --saida <pasta>

So a biblioteca padrao."""
import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def url(repo, tag, nome):
    return f"https://github.com/{repo}/releases/download/{tag}/{nome}"


def iss(m):
    """O texto do vozes.iss."""
    rels = [m["engine"], *m["vozes"]]
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", m["repo"]):
        raise SystemExit(f"vozes.json: unexpected repo {m['repo']!r}")
    itens, arquivos = [], []
    for r in rels:
        for a in r["arquivos"]:
            if not re.fullmatch(r"[A-Za-z0-9._-]+", r["tag"] + a["nome"]) or not re.fullmatch(r"[0-9a-f]{64}", a["sha256"]):
                raise SystemExit(f"vozes.json: unexpected name or hash in {r['tag']}/{a['nome']}")
            itens.append(f"{r['tag']}|{a['nome']}|{a['sha256']}")
            # o baixado mora na {tmp} com a tag no nome (as vozes repetem nomes, como o LICENSE.md)
            arquivos.append(
                f'Source: "{{tmp}}\\vozes-{r["tag"]}-{a["nome"]}"; DestName: "{a["nome"]}"; '
                f'DestDir: "{{app}}\\vozes\\{r["tag"]}"; ExternalSize: {a["tamanho"]}; '
                f"Flags: external ignoreversion; Check: FaltaVoz('{r['tag']}\\{a['nome']}', '{a['sha256']}')")
    linhas = ["; gerado pelo instalador\\vozes_iss.py a partir do vozes.json: nao edite",
              f'#define VozesRepo "{m["repo"]}"',
              f'#define VozesTags "|{"|".join(r["tag"] for r in rels)}|"',
              f'#define VozesLista "{";".join(itens)}"',
              f'#define VozesMB "{round(sum(a["tamanho"] for r in rels for a in r["arquivos"]) / 1e6)}"',
              "", "[Files]", *arquivos]
    return "\n".join(linhas) + "\n"


def texto(md):
    """O LICENSE.md como texto simples para a pagina do Inno: sem os # dos titulos e sem o negrito."""
    out = []
    for linha in md.splitlines():
        linha = re.sub(r"^#+\s*", "", linha).replace("**", "")
        out.append(linha)
    return "\n".join(out).strip() + "\n"


def licenca(m):
    """O texto da licenca das vozes: o LICENSE.md de cada voz, uma vez so se for o mesmo."""
    vistos, partes = set(), []
    for v in m["vozes"]:
        a = next((a for a in v["arquivos"] if a["nome"] == "LICENSE.md"), None)
        if a is None:
            raise SystemExit(f"vozes.json: {v['tag']} has no LICENSE.md")
        if a["sha256"] in vistos:
            continue
        req = urllib.request.Request(url(m["repo"], v["tag"], "LICENSE.md"), headers={"User-Agent": "ritmelli-build"})
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read()
        if hashlib.sha256(b).hexdigest() != a["sha256"]:
            raise SystemExit(f"{v['tag']}/LICENSE.md doesn't match the sha256 in vozes.json")
        vistos.add(a["sha256"])
        partes.append(b.decode("utf-8"))
    return "\n\n".join(texto(p) for p in partes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", required=True)
    ap.add_argument("--manifesto", default=str(RAIZ / "vozes.json"))
    a = ap.parse_args()
    m = json.loads(Path(a.manifesto).read_text(encoding="utf-8"))
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "vozes.iss").write_text(iss(m), encoding="utf-8-sig")
    (saida / "licenca-vozes.txt").write_text(licenca(m), encoding="utf-8-sig")
    print(saida / "vozes.iss")


if __name__ == "__main__":
    main()
