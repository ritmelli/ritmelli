r"""Roda os testes que nao usam som, aparelho nem rede externa (o loopback e o servidor falso valem), cada um no seu
processo e um depois do outro, e sai 1 se algum falhar. E o que o .github/workflows/testa.yml roda em todo PR.

    python dev\testa_tudo.py               o COMPLETO: o STDLIB mais os que usam as bibliotecas do app e o ffmpeg
    python dev\testa_tudo.py --so-stdlib   o STDLIB, so da biblioteca padrao (a monta.yml roda antes de instalar)
    python dev\testa_tudo.py --microfone   os do filtro, com as DLLs do microfone\apo\compila.bat teste
    python dev\testa_tudo.py --tela [--base origin/main] [--pasta logs\tela]
                                           o fitcheck nas duas linguas contra um --mock com dados temporarios e, com
                                           --base, o compara: a referencia sai do servidor e do tema da base (num
                                           worktree temporario), e a comparacao, dos daqui
    python dev\testa_tudo.py --areas <base> [--etiquetas '["extracao-tema"]']
                                           (sem o --etiquetas, a lista vem da variavel ETIQUETAS)
                                           o filtro por caminho do testa.yml: diz (e grava no GITHUB_OUTPUT) se o que
                                           mudou desde a base, ou uma etiqueta do PR, dispara o job do filtro e o da tela
        [--resumo arquivo.md]              acrescenta o resultado em markdown (o resumo do PR)

No COMPLETO, biblioteca ou ffmpeg faltando e falha, e nao teste pulado: sem as bibliotecas do servidor, o testa_mock,
o testa_migra e o testa_pareamento pulam a parte dele. Todo dev/testa_*.py tem de estar numa lista daqui.
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
                                             "ganchos")]
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


def fora_das_listas():
    """Os dev/testa_*.py que nao estao em lista nenhuma (um teste novo esquecido aqui nunca rodaria no PR)."""
    todos = {p.relative_to(RAIZ).as_posix() for p in (RAIZ / "dev").glob("testa_*.py")}
    return sorted(todos - set(COMPLETO) - set(MICROFONE) - {"dev/testa_tudo.py"})


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
    """O que o COMPLETO precisa e nao esta aqui."""
    falta = [f"o modulo {m}" for m in MODULOS if importlib.util.find_spec(m) is None]
    return falta + [f"o {p} no PATH" for p in PROGRAMAS if not shutil.which(p)]


def testes(a):
    titulo, lista = (("Testes so da biblioteca padrao", STDLIB) if a.so_stdlib else
                     ("Testes do filtro", MICROFONE) if a.microfone else ("Testes", COMPLETO))
    md = []
    esquecidos = fora_das_listas()
    for t in esquecidos:
        print(f"FALHA {t} nao esta em nenhuma lista do dev/testa_tudo.py (STDLIB, COMPLETO ou MICROFONE)")
    if esquecidos:
        md += [f"**{titulo}:** ❌ fora das listas do `dev/testa_tudo.py`: " + ", ".join(f"`{t}`" for t in esquecidos),
               ""]
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
    etiquetas = json.loads(a.etiquetas or os.environ.get("ETIQUETAS") or "[]")
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
    ap.add_argument("--etiquetas", help="no --areas: as etiquetas do PR, numa lista em JSON (sem ele, a da variavel ETIQUETAS)")
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
