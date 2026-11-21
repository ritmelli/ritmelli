"""As vozes do pedal de troca de voz (#129), do ritmelli-voices. O vozes.json da raiz diz as releases que esta versao do
app usa e o tamanho e o sha256 de cada arquivo delas; o instalador baixa os mesmos arquivos para a pasta vozes\\ do app
(instalador/vozes_iss.py), e quem roda pelo codigo baixa por aqui, para a vozes/ da raiz (fora do git).

    python dev/vozes.py baixa
        os arquivos do vozes.json na vozes/ da raiz: o que ja esta la com o sha256 certo fica, o resto vem do GitHub
    python dev/vozes.py manifesto engine-v0.1 mina=mina-v0.2 lira=lira-v0.2
        refaz o vozes.json pelas releases (a engine e as vozes, da mais grave para a mais aguda): de cada release, os
        modelos (.onnx, .npz), o meta.json, o voz.json e as licencas, com o sha256 que o GitHub publica

So a biblioteca padrao. Sai 1 se algo nao bater."""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MANIFESTO = RAIZ / "vozes.json"
REPO = "ritmelli/ritmelli-voices"
PEDACO = 1 << 20


def _vai(nome):
    """Os arquivos da release que o app usa: o .pth (o modelo de treino) e os .json do treino ficam de fora."""
    return nome.endswith((".onnx", ".npz")) or nome in ("meta.json", "voz.json") or nome.startswith("LICENSE")


def _abre(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ritmelli-dev"}), timeout=60)


def _sha(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for b in iter(lambda: f.read(PEDACO), b""):
            h.update(b)
    return h.hexdigest()


def url(repo, tag, nome):
    return f"https://github.com/{repo}/releases/download/{tag}/{nome}"


def _release(repo, tag):
    with _abre(f"https://api.github.com/repos/{repo}/releases/tags/{tag}") as r:
        rel = json.load(r)
    arqs = []
    for a in sorted(rel["assets"], key=lambda a: a["name"]):
        if not _vai(a["name"]):
            continue
        sha = (a.get("digest") or "").removeprefix("sha256:")
        if len(sha) != 64:  # asset de antes de o GitHub publicar o digest: o hash sai do proprio arquivo
            h = hashlib.sha256()
            with _abre(url(repo, tag, a["name"])) as r:
                for b in iter(lambda: r.read(PEDACO), b""):
                    h.update(b)
            sha = h.hexdigest()
        arqs.append({"nome": a["name"], "tamanho": a["size"], "sha256": sha})
    if not any(a["nome"].endswith(".onnx") for a in arqs):
        raise SystemExit(f"{tag}: the release has no .onnx model")
    return {"tag": tag, "arquivos": arqs}


def manifesto(engine, vozes):
    m = {"repo": REPO, "engine": _release(REPO, engine), "vozes": []}
    for par in vozes:
        vid, _, tag = par.partition("=")
        if not vid or not tag:
            raise SystemExit(f"expected id=tag, got {par!r}")
        m["vozes"].append({"id": vid, **_release(REPO, tag)})
    MANIFESTO.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(a["tamanho"] for r in [m["engine"], *m["vozes"]] for a in r["arquivos"])
    print(f"{MANIFESTO}: {1 + len(m['vozes'])} releases, {total / 1e6:.0f} MB")


def baixa(destino=RAIZ / "vozes", m=None):
    """Os arquivos do manifesto em destino/<tag>/: confere o sha256 do que ja esta la e baixa o resto (num .parte, que
    so vira o arquivo com o hash certo). Devolve quantos baixou."""
    m = m or json.loads(MANIFESTO.read_text(encoding="utf-8"))
    baixados = 0
    for rel in [m["engine"], *m["vozes"]]:
        pasta = Path(destino) / rel["tag"]
        pasta.mkdir(parents=True, exist_ok=True)
        for a in rel["arquivos"]:
            arq = pasta / a["nome"]
            if arq.is_file() and arq.stat().st_size == a["tamanho"] and _sha(arq) == a["sha256"]:
                continue
            print(f"baixando {rel['tag']}/{a['nome']} ({a['tamanho'] / 1e6:.1f} MB)...", flush=True)
            parte = arq.with_name(arq.name + ".parte")
            h = hashlib.sha256()
            with _abre(url(m["repo"], rel["tag"], a["nome"])) as r, open(parte, "wb") as f:
                for b in iter(lambda: r.read(PEDACO), b""):
                    h.update(b)
                    f.write(b)
            if h.hexdigest() != a["sha256"]:
                parte.unlink()
                raise SystemExit(f"{rel['tag']}/{a['nome']}: sha256 {h.hexdigest()}, expected {a['sha256']}")
            parte.replace(arq)
            baixados += 1
    sobra = sorted(p.name for p in Path(destino).iterdir()
                   if p.is_dir() and p.name not in {r["tag"] for r in [m["engine"], *m["vozes"]]})
    if sobra:
        print(f"not in vozes.json (the app ignores them): {', '.join(sobra)}")
    return baixados


def main(args):
    if args[:1] == ["baixa"] and len(args) == 1:
        n = baixa()
        print(f"vozes: {n} downloaded, everything matches vozes.json")
    elif args[:1] == ["manifesto"] and len(args) >= 3:
        manifesto(args[1], args[2:])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
