r"""Roda os testes que nao usam som, aparelho nem rede externa (o loopback e o servidor falso valem), cada um no seu
processo e um depois do outro, e sai 1 se algum falhar. E o que o .github/workflows/testa.yml roda em todo PR.

    python dev\testa_tudo.py               o COMPLETO: o STDLIB mais os que usam as bibliotecas do app e o ffmpeg
    python dev\testa_tudo.py --so-stdlib   o STDLIB, so da biblioteca padrao (a monta.yml roda antes de instalar)
    python dev\testa_tudo.py --microfone   os do filtro, com as DLLs do microfone\apo\compila.bat teste
    python dev\testa_tudo.py --tela [--base origin/main] [--pasta logs\tela]
                                           o fitcheck nas duas linguas contra um --mock com dados temporarios e, com
                                           --base, o compara: a referencia sai do servidor e do tema da base (num
                                           worktree temporario), e a comparacao, dos daqui
    python dev\testa_tudo.py --areas <base>
                                           (as etiquetas do PR vem da variavel ETIQUETAS, uma lista em JSON:
                                           $env:ETIQUETAS = '["extracao-tema"]'; no argumento, o PowerShell 5.1
                                           tiraria as aspas)
                                           o filtro por caminho do testa.yml: diz (e grava no GITHUB_OUTPUT) se o que
                                           mudou desde a base, ou uma etiqueta do PR, dispara o job do filtro e o da tela
        [--resumo arquivo.md]              acrescenta o resultado em markdown (o resumo do PR)

No COMPLETO, biblioteca ou ffmpeg faltando e falha, e nao teste pulado: sem as bibliotecas do servidor, o testa_mock,
o testa_migra e o testa_pareamento pulam a parte dele.

Todo dev/testa_*.py tem destino: ou roda no testa.yml (numa lista daqui ou num passo proprio, como o --disco do
testa_pasta_protegida), ou so roda a mao e diz no topo do arquivo, num comentario antes da docstring, como e com o que:
"# manual: <comando> precisa de <aparelho>". Antes de rodar, o COMPLETO, o --so-stdlib e o --microfone leem os passos do
testa.yml e reprovam o teste sem destino e o arquivo de dev/ com a linha "manual:" que roda la.
Sai 0 se tudo passou e 1 se algo falhou; no --tela, 2 se so os prints do compara mudaram (o testa.yml decide).
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# so a biblioteca padrao: a monta.yml roda estes antes de instalar as bibliotecas do app
STDLIB = [f"dev/testa_{n}.py" for n in ("i18n", "metricas", "migra", "mock", "vozes", "pareamento", "grava", "mfx",
                                             "ganchos", "pasta_protegida")]
# o STDLIB mais os que usam as bibliotecas do app (requirements-dev.txt) e o ffmpeg
COMPLETO = STDLIB + [f"dev/testa_{n}.py" for n in (
    "adianta", "anel", "atualizacao", "atualizador", "congela", "conversor", "ganho", "musica", "passagens",
    "pedal_voz", "pista", "preabre", "rapido", "vivo")] + ["instalador/atualizacao/testa_parcial.py"]
# os do filtro, com as DLLs do microfone\apo\compila.bat teste: o testa.yml so roda quando a area do filtro muda
MICROFONE = ["dev/testa_filtro.py", "dev/testa_voz.py", "dev/testa_microfone.py",
             "microfone/apo/teste/teste_reamostra.py"]
DLLS = ("teste_reamostra.dll", "voz.dll", "banca_filtro.dll")

# o que o COMPLETO precisa (os modulos do requirements-dev.txt e os programas do PATH): sem um deles, falha antes
MODULOS = ("numpy", "scipy", "sounddevice", "pedalboard", "aiohttp", "segno", "yt_dlp", "Cryptodome", "ytmusicapi",
           "onnxruntime", "comtypes", "webview", "websockets", "PIL", "onnx")
PROGRAMAS = ("ffmpeg", "ffprobe")
# a linha de quem pulou uma parte por falta de biblioteca ("--   o guard do servidor ficou de fora: ...")
PULOU = re.compile(r"^--\s.*ficou de fora.*$", re.M)
LIMITE_S = 600

# o filtro por caminho do testa.yml (caminhos do git, com /; o que termina em / e a pasta inteira). O PR que leva
# codigo de renderizacao ou de traducao para outro modulo poe o modulo na "tela"
AREAS = {
    "microfone": ("microfone/", "fx.py", "engine.py", "dev/testa_filtro.py", "dev/testa_voz.py",
                  "dev/testa_microfone.py"),
    "tela": ("themes/", "server.py", "i18n.py", "metricas.py", "dev/compara.py", "dev/fitcheck.py", "dev/so_mock.py"),
}
# os dois disparam todas as areas: o testa.yml e as listas e o filtro daqui
TODAS = (".github/workflows/testa.yml", "dev/testa_tudo.py")
# a etiqueta do PR que dispara uma area mesmo sem arquivo dela: a extracao-tema, do PR que leva codigo de
# renderizacao ou de traducao do tema para outro modulo (posta por quem mantem o repo)
ETIQUETAS = {"extracao-tema": "tela"}


def areas(arquivos, etiquetas=()):
    """As areas do AREAS que os arquivos mudados e as etiquetas do PR disparam."""
    def bate(arq, padroes):
        return any(arq.startswith(p) if p.endswith("/") else arq == p for p in padroes)
    return ({a for a, padroes in AREAS.items() if any(bate(f, padroes + TODAS) for f in arquivos)}
            | {ETIQUETAS[e] for e in etiquetas if e in ETIQUETAS})


def manual(arquivo):
    """A linha "# manual: <comando> precisa de <aparelho>" do comentario do topo do arquivo (as linhas com # antes do
    codigo e da docstring), ou None. A linha que comeca com "# manual:" fora desse formato volta tambem: a conferencia
    acusa."""
    for linha in Path(arquivo).read_text(encoding="utf-8-sig").splitlines():
        if not linha.strip():
            continue
        if not linha.startswith("#"):
            return None
        if re.match(r"#\s*manual:", linha):
            return linha.strip()
    return None


def roda_no_yml(texto):
    """Os scripts que os passos do testa.yml rodam: os que o run: de cada passo chama pelo python e os que o testa_tudo.py
    chamado ali roda (sem modo, o COMPLETO; com --microfone, o MICROFONE; com --so-stdlib, o STDLIB; com --tela, o
    fitcheck e, com --base, o compara). Caminho so citado (num echo, num comentario) nao conta."""
    linhas, runs, i = texto.splitlines(), [], 0
    while i < len(linhas):
        m = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", linhas[i])
        i += 1
        if not m:
            continue
        if not m.group(2).startswith(("|", ">")):
            runs.append(m.group(2))
            continue
        bloco = []
        while i < len(linhas) and (not linhas[i].strip() or len(linhas[i]) - len(linhas[i].lstrip()) > len(m.group(1))):
            bloco.append(linhas[i])
            i += 1
        # o > dobra as linhas num comando so
        runs.append(" ".join(b.strip() for b in bloco) if m.group(2).startswith(">") else "\n".join(bloco))
    rodam = set()
    for run in runs:
        for linha in run.replace("\\", "/").splitlines():
            linha = linha.split("#")[0]
            for chamada in re.finditer(r"(?:^|[\s;&|(\"'])py(?:thon[\d.]*)?(?:\.exe)?[\"']?(?:\s+-\S+)*\s+[\"']?"
                                       r"([\w./-]+\.py)\b", linha):
                script, resto = chamada.group(1).removeprefix("./"), linha[chamada.end():]
                rodam.add(script)
                if script == "dev/testa_tudo.py":
                    if "--tela" in resto:
                        rodam.update(["dev/fitcheck.py"] + (["dev/compara.py"] if "--base" in resto else []))
                    elif "--areas" not in resto:
                        rodam.update(MICROFONE if "--microfone" in resto else STDLIB if "--so-stdlib" in resto else
                                     COMPLETO)
    return rodam


def sem_destino(yml=RAIZ / ".github" / "workflows" / "testa.yml"):
    """O que tira um teste do PR sem ninguem ver: o dev/testa_*.py que o testa.yml nao roda (nem por uma lista daqui nem
    num passo proprio) e nao tem a linha "manual:"; e o que tem a linha (teste ou ferramenta de dev/) e roda la mesmo,
    ou a tem fora do formato. Volta as linhas da falha."""
    rodam = roda_no_yml(Path(yml).read_text(encoding="utf-8"))
    falhas = []
    for p in sorted((RAIZ / "dev").glob("*.py")):
        rel, linha = p.relative_to(RAIZ).as_posix(), manual(p)
        if linha and not re.match(r"#\s*manual:\s*\S.*\s+precisa de\s+\S", linha):
            falhas.append(f"{rel}: a linha \"{linha}\" nao segue o formato \"# manual: <comando> precisa de <aparelho>\"")
        elif linha and rel in rodam:
            falhas.append(f"{rel} tem a linha \"manual:\" e roda no testa.yml: tire a linha ou tire o teste de la")
        elif not linha and rel.startswith("dev/testa_") and rel != "dev/testa_tudo.py" and rel not in rodam:
            falhas.append(f"{rel} nao roda no testa.yml (nem numa lista do dev/testa_tudo.py, STDLIB, COMPLETO ou "
                          "MICROFONE, nem num passo) e nao tem no topo a linha \"# manual: <comando> precisa de "
                          "<aparelho>\"")
    return falhas


def cerca(texto):
    """Um bloco de codigo do markdown que o texto nao fecha."""
    n = max([3] + [len(m) + 1 for m in re.findall(r"`{3,}", texto)])
    return f"{'`' * n}text\n{texto.rstrip()}\n{'`' * n}"


def cauda(texto, linhas=60):
    partes = texto.rstrip().splitlines()
    return "\n".join((["(...)"] if len(partes) > linhas else []) + partes[-linhas:])


def executa(cmd, limite=LIMITE_S, **kw):
    """(o codigo de saida, ou o texto do limite estourado; a saida inteira, stdout e stderr juntos). A saida vai para
    um arquivo, e nao para um pipe: um neto que herda o pipe seguraria o run depois do limite."""
    env = dict(os.environ, PYTHONUTF8="1")
    env.update(kw.pop("env", {}))
    with tempfile.TemporaryFile() as f:
        try:
            cod = subprocess.run(cmd, cwd=kw.pop("cwd", RAIZ), env=env, stdin=subprocess.DEVNULL, stdout=f,
                                 stderr=subprocess.STDOUT, timeout=limite, **kw).returncode
        except subprocess.TimeoutExpired:
            cod = f"passou de {limite} s"
        f.seek(0)
        return cod, f.read().decode("utf-8", "replace")


def roda(titulo, lista, completo):
    """Roda cada teste da lista. Volta (as falhas, as linhas do markdown)."""
    falhas, tabela, md = [], [], []
    t0 = time.monotonic()
    for t in lista:
        ini = time.monotonic()
        cod, saida = executa([sys.executable, t])
        dt = time.monotonic() - ini
        motivo = None
        if cod != 0:
            motivo = f"sai {cod}" if isinstance(cod, int) else cod
        elif completo and PULOU.search(saida):
            motivo = "pulou uma parte por falta de biblioteca: " + PULOU.search(saida).group(0).strip()
        print(f"{'ok   ' if not motivo else 'FALHA'} {t} ({dt:.1f} s){'' if not motivo else ': ' + motivo}", flush=True)
        tabela.append(f"| {'✅' if not motivo else '❌'} | `{t}` | {dt:.0f} s |")
        if motivo:
            print(saida.rstrip(), flush=True)
            falhas.append(t)
            md += [f"<details><summary>❌ <code>{t}</code>: {motivo}</summary>", "", cerca(cauda(saida)), "",
                   "</details>"]
    total = time.monotonic() - t0
    passou = len(lista) - len(falhas)
    print(f"{passou} de {len(lista)} passaram em {total:.0f} s", flush=True)
    md = [f"**{titulo}:** {'✅' if not falhas else '❌'} {passou} de {len(lista)} passaram, em {total:.0f} s", ""] + md
    md += ["", "<details><summary>Cada teste</summary>", "", "| | Teste | Tempo |", "| --- | --- | --- |"] + tabela
    md += ["", "</details>"]
    return falhas, md


def falta_para_o_completo():
    """O que o COMPLETO precisa e nao esta aqui. O ffmpeg e o ffprobe pela regra do motor: o do bin/ da raiz
    (pastas.ferramenta) ou o do PATH."""
    sys.path.insert(0, str(RAIZ))
    import pastas  # so da biblioteca padrao
    falta = [f"o modulo {m}" for m in MODULOS if importlib.util.find_spec(m) is None]
    return falta + [f"o {p} (nem no bin/ nem no PATH)" for p in PROGRAMAS
                    if not (pastas.ferramenta(p) or shutil.which(p))]


def testes(a):
    titulo, lista = (("Testes so da biblioteca padrao", STDLIB) if a.so_stdlib else
                     ("Testes do filtro", MICROFONE) if a.microfone else ("Testes", COMPLETO))
    md = []
    esquecidos = sem_destino()
    for t in esquecidos:
        print(f"FALHA {t}")
    if esquecidos:
        md += [f"**{titulo}:** ❌ teste sem destino ou \"manual:\" que roda no `testa.yml`:", ""]
        md += [f"- {t}" for t in esquecidos] + [""]
    impede = []
    if a.microfone:
        saida = RAIZ / "microfone" / "apo" / "saida"
        impede = [f"sem o {saida / d}: rode antes o microfone\\apo\\compila.bat teste" for d in DLLS
                  if not (saida / d).exists()]
    elif not a.so_stdlib:
        impede = [f"sem {f}" for f in falta_para_o_completo()]
    if impede:
        for i in impede:
            print(f"FALHA {i}")
        md += [f"**{titulo}:** ❌ nada rodou: " + "; ".join(impede)]
        escreve(a.resumo, md)
        return 1
    falhas, linhas = roda(titulo, lista, completo=not a.so_stdlib and not a.microfone)
    escreve(a.resumo, md + linhas)
    return 1 if falhas or esquecidos else 0


def escreve(resumo, linhas):
    if resumo:
        with open(resumo, "a", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n\n")


def diz_areas(a):
    """O --areas: o git diff --name-only da base ate o HEAD. Sem rename: o arquivo que sai de uma area conta nela. Com o
    -z, o caminho com acento vem inteiro, e nao entre aspas."""
    cod, saida = executa(["git", "diff", "--name-only", "-z", "--no-renames", a.areas, "HEAD"], limite=60)
    if cod != 0:
        print(f"o git diff contra {a.areas} falhou ({cod}):\n{saida}")
        return 1
    arquivos = [arq for arq in saida.split(chr(0)) if arq.strip()]
    etiquetas = json.loads(os.environ.get("ETIQUETAS") or "[]")
    disparadas = areas(arquivos, etiquetas)
    print(f"{len(arquivos)} arquivo(s) mudaram desde {a.areas}; etiquetas: {etiquetas or 'nenhuma'}")
    linhas = [f"{area}={'true' if area in disparadas else 'false'}" for area in AREAS]
    print("\n".join(linhas))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n")
    return 0


def tela(a):
    """O --tela: o fitcheck nas duas linguas e, com --base, o compara da base contra o daqui."""
    sys.path.insert(0, str(RAIZ / "dev"))
    import so_mock
    import compara  # numpy, pillow e websockets: so aqui, para o --so-stdlib seguir so da biblioteca padrao

    pasta = Path(a.pasta).resolve()
    pasta.mkdir(parents=True, exist_ok=True)  # sem apagar: o --pasta pode ser uma pasta que ja existe
    md, bloqueia, mudou = ["**Tela:**", ""], False, False

    # o fitcheck contra um --mock com a prateleira de mentira do compara, os dados e a LOCALAPPDATA temporarios
    tmp = Path(tempfile.mkdtemp(prefix="ritmelli-tela-"))
    try:
        dados = tmp / "dados"
        dados.mkdir()
        (tmp / "local").mkdir()
        (dados / "library.json").write_text(json.dumps(compara.prateleira(), ensure_ascii=False), encoding="utf-8")
        porta = so_mock.free_port()
        with open(pasta / "fitcheck-servidor.log", "w", encoding="utf-8") as log:
            try:
                srv = so_mock.sobe([sys.executable, str(RAIZ / "server.py"), "--mock", "--no-browser", "--port",
                                    str(porta), "--data-dir", str(dados)], porta, cwd=RAIZ, stdout=log,
                                   stderr=subprocess.STDOUT, env=dict(os.environ, LOCALAPPDATA=str(tmp / "local")))
            except so_mock.Recusa as ex:
                srv = None
                print(f"FALHA o --mock do fitcheck nao subiu: {ex}")
                md.append(f"- ❌ o `--mock` do fitcheck não subiu: {ex}")
                bloqueia = True
            if srv:
                try:
                    for lang in ("pt_BR", "en"):
                        cod, saida = executa([sys.executable, "dev/fitcheck.py", f"{srv.base}/t/ritmelli/?lang={lang}"])
                        print(f"--- fitcheck {lang}: sai {cod}\n{saida.rstrip()}", flush=True)
                        ruins = [linha for linha in saida.splitlines() if linha.startswith(("FALHA", "Traceback"))]
                        if cod != 0:
                            bloqueia = True
                            md += [f"<details><summary>❌ fitcheck em {lang}: sai {cod}</summary>", "",
                                   cerca(cauda("\n".join(ruins) or saida)), "", "</details>"]
                        else:
                            n = sum(linha.startswith("OK") for linha in saida.splitlines())
                            md.append(f"- ✅ fitcheck em {lang}: {n} tamanhos cabem, sem erro no console")
                finally:
                    srv.encerra()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if a.base:
        cod, saida = executa(["git", "rev-parse", "--verify", f"{a.base}^{{commit}}"], limite=60)
        base = saida.strip()
        wt = Path(tempfile.mkdtemp(prefix="ritmelli-base-")) / "base"
        cod = cod or executa(["git", "worktree", "add", "--detach", str(wt), base], limite=300)[0]
        if cod != 0:
            print(f"FALHA o worktree da base {a.base} nao saiu ({cod})")
            md.append(f"- ❌ o worktree da base `{a.base}` não saiu")
            bloqueia = True
        else:
            try:
                cod, saida = executa([sys.executable, "dev/compara.py", "--ref", "--raiz", str(wt),
                                      "--pasta", str(pasta / "compara")])
                print(f"--- compara --ref da base {base[:12]}: sai {cod}\n{saida.rstrip()}", flush=True)
                if cod != 0:
                    bloqueia = True
                    md += [f"<details><summary>❌ compara: a captura da base <code>{base[:12]}</code> não vale "
                           f"(sai {cod})</summary>", "", cerca(cauda(saida)), "", "</details>"]
                else:
                    cod, saida = executa([sys.executable, "dev/compara.py", "--pasta", str(pasta / "compara")])
                    print(f"--- compara do PR: sai {cod}\n{saida.rstrip()}", flush=True)
                    fim = saida.strip().splitlines()[-1:] or [""]
                    if cod == 2:
                        mudou = True
                        mudaram = [linha for linha in saida.splitlines() if linha.startswith(("MUDOU", "NOVO", "SUMIU"))]
                        md += [f"<details><summary>⚠️ compara: os prints mudaram ({fim[0]})</summary>", "",
                               cerca(cauda("\n".join(mudaram), 40)), "", "</details>"]
                    elif cod != 0:
                        bloqueia = True
                        md += [f"<details><summary>❌ compara: a captura do PR não vale (sai {cod})</summary>", "",
                               cerca(cauda(saida)), "", "</details>"]
                    else:
                        md.append(f"- ✅ compara contra a base `{base[:12]}`: {fim[0]}")
            finally:
                executa(["git", "worktree", "remove", "--force", str(wt)], limite=300)
                shutil.rmtree(wt.parent, ignore_errors=True)
    escreve(a.resumo, md)
    return 1 if bloqueia else 2 if mudou else 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--so-stdlib", action="store_true", help="so o STDLIB, que roda sem as bibliotecas do app")
    modo.add_argument("--microfone", action="store_true", help="os testes do filtro (MICROFONE)")
    modo.add_argument("--tela", action="store_true", help="o fitcheck e, com --base, o compara")
    modo.add_argument("--areas", metavar="BASE", help="as areas que o que mudou desde BASE dispara")
    ap.add_argument("--base", help="no --tela: a base do compara (um commit, um branch)")
    ap.add_argument("--pasta", default=str(RAIZ / "logs" / "tela"), help="no --tela: onde ficam os prints e os logs")
    ap.add_argument("--resumo", help="acrescenta o resultado em markdown a este arquivo")
    a = ap.parse_args()
    if a.areas:
        return diz_areas(a)
    if a.tela:
        return tela(a)
    return testes(a)


if __name__ == "__main__":
    sys.exit(main())
