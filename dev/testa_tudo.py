r"""Runs the tests that need no sound, no device and no outside network (the loopback and the fake server are fine),
each in its own process, and exits 1 if any fails. It is what the .github/workflows/testa.yml runs on every PR.

    python dev\testa_tudo.py               the COMPLETO (the STDLIB plus the ones that use the app libraries and
                                           ffmpeg) and the LONG_TESTS, after them
    python dev\testa_tudo.py --without-long
                                           only the COMPLETO (the Testes job: the testa.yml runs the LONG_TESTS in a
                                           job of its own)
    python dev\testa_tudo.py --so-stdlib   the STDLIB, standard library only (the monta.yml runs it before installing)
    python dev\testa_tudo.py --microfone   the filter tests, with the DLLs of microfone\apo\compila.bat teste
    python dev\testa_tudo.py --long [bench|capture]
                                           only the LONG_TESTS (all, or the one named): the bench (the transition
                                           bench, the real engine, one pair per kind of transition) and the capture
                                           (the compara capture of the --capture). Each has a job of its own in the
                                           testa.yml, the Banca and the Captura, next to the Testes
    python dev\testa_tudo.py --tela [--base origin/main] [--pasta logs\tela] [--ref-cache <dir>]
                                           the fitcheck in both languages against a --mock with temporary data and,
                                           with --base, the compara: the reference comes from the server and the theme
                                           of the base (in a temporary worktree), the comparison from the ones here
    python dev\testa_tudo.py --compara --base origin/main [--ref-cache <dir>] [--head-cache <dir>]
                                           only the compara of the --tela (the testa.yml runs it in a job of its own)
    python dev\testa_tudo.py --capture <dir>
                                           only the compara capture of the HEAD, into the folder with its key (the
                                           push to main: the reference of the PRs that will have it as their base)
    python dev\testa_tudo.py --passo <name>
                                           a step of the testa.yml that runs one script (PASSOS): the "disco" is the
                                           testa_pasta_protegida.py --disco, the "metricas" the fitcheck.py --metricas
    python dev\testa_tudo.py --areas <base>
                                           (the PR labels come from the ETIQUETAS variable, a JSON list:
                                           $env:ETIQUETAS = '["extracao-tema"]'; in an argument, PowerShell 5.1 would
                                           drop the quotes)
                                           the path filter of the testa.yml: says (and writes to GITHUB_OUTPUT) whether
                                           what changed since the base, or a PR label, triggers the filter job and the
                                           screen jobs
    python dev\testa_tudo.py --linhas <base>
                                           the line count of the big files (LINHAS) against the base, for the summary
        [--resumo arquivo.md]              appends the result in markdown (the PR summary)
        [--jobs N]                         how many tests run at a time (default 4); the ones in SERIAL always run
                                           one by one, alone, after the others

In the COMPLETO and the --long, a missing library or ffmpeg is a failure, not a skipped test: without the server
libraries, the testa_mock and the testa_migra skip their part.

Every dev/testa_*.py and dev/test_*.py (a new test, in English, is named test_*) has a destination: a list here (STDLIB,
COMPLETO, LONG_TESTS, MICROFONE, PASSOS), or it only runs by hand and says so at the top of the file, in a comment before
the docstring, how and with what: "# manual: <comando> precisa de <aparelho>". Before running, the COMPLETO, the
--long, the --so-stdlib and the --microfone fail on a test without destination, on a dev/ file with the "manual:" line
that runs in the check, and on a mode of this script the testa.yml no longer calls.
They also fail an AGENTS.md over 80 lines or with a file in its map that doesn't exist (agents_md).

The --ref-cache is a folder with a capture of the compara: when it holds the one of the base (the commit and the key of
the capture, CAPTURA), the base is not captured again; when it does not, the base capture goes there. The --head-cache
gets the capture of the HEAD, which is the reference of the PRs that will have it as their base (the push to main).

Exits 0 if everything passed and 1 if something failed; in the --tela and the --compara, 2 if only the compara prints
changed (the testa.yml decides).
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# so a biblioteca padrao: a monta.yml roda estes antes de instalar as bibliotecas do app
STDLIB = [f"dev/testa_{n}.py" for n in ("i18n", "metricas", "migra", "mock", "vozes", "pareamento", "grava", "mfx",
                                             "ganchos", "pasta_protegida", "so_mock")] + [
    "dev/test_trusted_author.py", "dev/test_needs_owner.py", "dev/test_ci_workflow.py"]
# o STDLIB mais os que usam as bibliotecas do app (requirements-dev.txt) e o ffmpeg
COMPLETO = STDLIB + [f"dev/testa_{n}.py" for n in (
    "adianta", "anel", "atualizacao", "atualizador", "automatico", "comandos", "congela", "conversor", "ganho", "musica",
    "passagens", "pedal_voz", "pista", "preabre", "protocolo", "rapido", "transicao", "vivo")] + [
    "instalador/atualizacao/testa_parcial.py", "dev/test_compara_not_ready.py",
    "dev/test_compara_push_steps.py", "dev/test_release_workflow.py"]
LONG_TESTS = {"bench": "dev/testa_passagem.py", "capture": "dev/test_capture.py"}
# os do filtro, com as DLLs do microfone\apo\compila.bat teste: o testa.yml so roda quando a area do filtro muda
# o testa_aparelho_mudo fica aqui pelo Inno Setup, que o job do filtro instala: sem ele, os casos do instalador
# pulariam
MICROFONE = ["dev/testa_filtro.py", "dev/testa_voz.py", "dev/testa_microfone.py", "dev/testa_aparelho_mudo.py",
             "microfone/apo/teste/teste_reamostra.py"]
DLLS = ("teste_reamostra.dll", "voz.dll", "banca_filtro.dll")

# o que o COMPLETO precisa (os modulos do requirements-dev.txt e os programas do PATH): sem um deles, falha antes
MODULOS = ("numpy", "scipy", "sounddevice", "pedalboard", "aiohttp", "segno", "yt_dlp", "Cryptodome", "ytmusicapi",
           "onnxruntime", "comtypes", "webview", "websockets", "PIL", "onnx", "jsonschema", "yaml")
PROGRAMAS = ("ffmpeg", "ffprobe")
# a linha de quem pulou uma parte por falta de biblioteca ("--   o guard do servidor ficou de fora: ...")
PULOU = re.compile(r"^--\s.*ficou de fora.*$", re.M)
# a line a test wants in the PR summary ("-- summary: <text>"), copied under the title of its run
SUMMARY = re.compile(r"^-- summary: (.+?)\s*$", re.M)
LIMITE_S = 600
# the tests that measure time (a deadline, a cost per block, the wait between two events): with --jobs above 1 they run
# one by one, alone, after the others, so a neighbour's load does not push them past a limit
SERIAL = {f"dev/testa_{n}.py" for n in ("adianta", "mock", "grava", "comandos", "congela", "ganho", "musica", "passagem",
                                         "pedal_voz", "pista", "vivo")}
JOBS = 4
# the steps of the testa.yml that run one script of their own, by name (--passo): the protected folder on the real disk
# (it creates a folder in Program Files and changes its ACL with icacls, so it needs an administrator: the GitHub
# machine is one; on a PC, only a test Windows) and the usage data notice of the theme
PASSOS = {"disco": ("dev/testa_pasta_protegida.py", "--disco"), "metricas": ("dev/fitcheck.py", "--metricas")}
# what the --tela and the --compara run
TELA = ("dev/fitcheck.py", "dev/compara.py", "dev/missing_script.py", "dev/theme_scripts.py")
# the calls the testa.yml has to make, so every list and step above runs on the PR (sem_destino checks them)
INVOCATIONS = ("dev/testa_tudo.py --without-long", "dev/testa_tudo.py --microfone", "dev/testa_tudo.py --tela",
               "dev/testa_tudo.py --compara", "dev/testa_tudo.py --capture") + tuple(
    f"dev/testa_tudo.py --passo {n}" for n in PASSOS) + tuple(f"dev/testa_tudo.py --long {n}" for n in LONG_TESTS)
# the big files whose line count goes in the summary, against the base (--linhas)
LINHAS = ("engine.py", "server.py", "themes/ritmelli/index.html", "AGENTS.md")
# what goes into the key of a compara capture besides the commit and the Chrome version: the scripts that take it and
# the libraries of the server
CAPTURA = ("dev/compara.py", "dev/fitcheck.py", "dev/so_mock.py", "requirements.txt", "requirements-dev.txt",
           "instalador/travas.txt")
LONG_TITLES = {"bench": "Banca", "capture": "Captura"}
# o filtro por caminho do testa.yml (caminhos do git, com /; o que termina em / e a pasta inteira). O PR que leva
# codigo de renderizacao ou de traducao para outro modulo poe o modulo na "tela"
AREAS = {
    "microfone": ("microfone/", "fx.py", "engine.py", "versao.py", "dev/testa_filtro.py", "dev/testa_voz.py",
                  "dev/testa_microfone.py", "dev/testa_aparelho_mudo.py", "instalador/mudos.iss"),
    "tela": ("themes/", "server.py", "i18n.py", "metricas.py", "dev/compara.py", "dev/fitcheck.py", "dev/so_mock.py",
             "dev/missing_script.py", "dev/theme_scripts.py"),
}
TODAS = (".github/workflows/testa.yml", ".github/actions/", "dev/testa_tudo.py", "instalador/travas.txt")
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


def is_test(rel):
    return rel.startswith(("dev/testa_", "dev/test_")) and rel != "dev/testa_tudo.py"


def sem_destino(yml=RAIZ / ".github" / "workflows" / "testa.yml", dev=RAIZ / "dev"):
    """What takes a test out of the PR check unnoticed: a test of dev/ (is_test) in no list here (STDLIB, COMPLETO,
    LONG_TESTS, MICROFONE, PASSOS) and without the "manual:" line; a file with the line (a test or a dev/ tool) that runs in
    the check anyway, or with the line out of format; a call of INVOCATIONS that the testa.yml no longer makes, and a
    dev/ script it calls directly instead of through PASSOS (in the lines that are not comments). Returns the failure
    lines."""
    rodam = set(COMPLETO) | set(LONG_TESTS.values()) | set(MICROFONE) | {cmd[0] for cmd in PASSOS.values()} | set(TELA)
    falhas = []
    for p in sorted(Path(dev).glob("*.py")):
        rel, linha = f"dev/{p.name}", manual(p)
        if linha and not re.match(r"#\s*manual:\s*\S.*\s+precisa de\s+\S", linha):
            falhas.append(f"{rel}: the line \"{linha}\" does not follow \"# manual: <comando> precisa de <aparelho>\"")
        elif linha and rel in rodam:
            falhas.append(f"{rel} has the \"manual:\" line and runs in the testa.yml: drop the line or the test")
        elif not linha and is_test(rel) and rel not in rodam:
            falhas.append(f"{rel} runs nowhere (in no list of dev/testa_tudo.py: STDLIB, COMPLETO, LONG_TESTS, MICROFONE or "
                          "PASSOS) and has no \"# manual: <comando> precisa de <aparelho>\" line at the top")
    linhas = Path(yml).read_text(encoding="utf-8").splitlines()
    # the commands: a line that starts with python (in a run: block, or right after run:), the dev/ script with either
    # separator, with or without quotes, and the rest of the line
    comandos = [(m.group(2).replace("\\", "/"), m.group(3).strip()) for m in (
        re.match(r"\s*(?:-\s+)?(?:run:\s*)?python(?:\.exe)?\s+(['\"]?)(dev[/\\]\w+\.py)\1(.*)$", linha)
        for linha in linhas) if m]
    falhas += [f"the testa.yml no longer runs \"python {c}\"" for c in INVOCATIONS
               if not any(s == c.split()[0] and resto.startswith(c.split(maxsplit=1)[1]) for s, resto in comandos)]
    # a dev/ script the workflow calls anywhere but through testa_tudo would skip the check above: it goes in PASSOS
    citados = {m.replace("\\", "/") for linha in linhas if not linha.lstrip().startswith("#")
               for m in re.findall(r"python(?:\.exe)?\s+['\"]?(dev[/\\]\w+\.py)", linha)}
    falhas += [f"the testa.yml runs \"python {s}\" directly: declare it in the PASSOS of dev/testa_tudo.py and call "
               "\"python dev/testa_tudo.py --passo <name>\"" for s in sorted(citados - {"dev/testa_tudo.py"})]
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


def roda(titulo, lista, completo, jobs=1):
    """Runs each test of the list, each in its own process: with jobs above 1, the ones outside SERIAL and LONG_TESTS that
    many at a time, then the others one by one, alone, in the order of the list. Returns (the failures, the markdown lines), in the order of the
    list."""
    feitos, trava = {}, threading.Lock()

    def um(t):
        ini = time.monotonic()
        cod, saida = executa([sys.executable, t])
        dt = time.monotonic() - ini
        motivo = None
        if cod != 0:
            motivo = f"sai {cod}" if isinstance(cod, int) else cod
        elif completo and PULOU.search(saida):
            motivo = "pulou uma parte por falta de biblioteca: " + PULOU.search(saida).group(0).strip()
        with trava:  # the line and the output of a failure together, even with tests ending at the same time
            print(f"{'ok   ' if not motivo else 'FALHA'} {t} ({dt:.1f} s){'' if not motivo else ': ' + motivo}",
                  flush=True)
            if motivo:
                print(saida.rstrip(), flush=True)
        feitos[t] = (motivo, dt, saida)

    t0 = time.monotonic()
    juntos = [t for t in lista if t not in SERIAL and t not in LONG_TESTS.values()] if jobs > 1 else []
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        list(ex.map(um, juntos))
    for t in lista:
        if t not in feitos:
            um(t)
    total = time.monotonic() - t0
    falhas, tabela, md, notes = [], [], [], []
    for t in lista:
        motivo, dt, saida = feitos[t]
        tabela.append(f"| {'✅' if not motivo else '❌'} | `{t}` | {dt:.0f} s |")
        notes += [f"- `{t}`: {n}" for n in SUMMARY.findall(saida)]
        if motivo:
            falhas.append(t)
            md += [f"<details><summary>❌ <code>{t}</code>: {motivo}</summary>", "", cerca(cauda(saida)), "",
                   "</details>"]
    passou = len(lista) - len(falhas)
    como = f", {jobs} at a time and the {len(lista) - len(juntos)} that measure time one by one" if juntos else ""
    print(f"{passou} of {len(lista)} passed in {total:.0f} s{como}", flush=True)
    como = f" ({jobs} por vez; os {len(lista) - len(juntos)} que medem tempo, um a um)" if juntos else ""
    md = [f"**{titulo}:** {'✅' if not falhas else '❌'} {passou} de {len(lista)} passaram, em {total:.0f} s{como}",
          ""] + md
    md += [""] + notes if notes else []
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


AGENTS_MAX_LINES = 80
# a file in the map: a backticked path with a folder or an extension (its first word, before an option)
MAP_FILE = re.compile(r"^(?:[\w.-]+/)*[\w.-]+(?:/|\.[A-Za-z]\w*)$")


def agents_md(path=RAIZ / "AGENTS.md"):
    """What is wrong with the AGENTS.md: over AGENTS_MAX_LINES lines, or a file in the map table that doesn't exist (in
    the files column, from the repo root; in the test column, a bare testa_* from dev/, a path from the root, and a
    bare file name from dev/ or from the root, since a note there may name an app file)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    problems = [f"AGENTS.md has {len(lines)} lines (at most {AGENTS_MAX_LINES})"] if len(lines) > AGENTS_MAX_LINES else []
    rows = [line.split("|")[1:-1] for line in lines if line.startswith("|") and not line.startswith("| ---")]
    for files, tests in ((r[1], r[2]) for r in rows[1:] if len(r) == 3):
        cited = [(t, [RAIZ / t]) for t in (c.split()[0] for c in re.findall(r"`([^`]+)`", files)) if MAP_FILE.match(t)]
        for t in (c.split()[0] for c in re.findall(r"`([^`]+)`", tests)):
            if re.fullmatch(r"testa_\w+", t):
                cited.append((t, [RAIZ / "dev" / f"{t}.py"]))
            elif MAP_FILE.match(t):
                cited.append((t, [RAIZ / t] if "/" in t else [RAIZ / "dev" / t, RAIZ / t]))
        problems += [f"AGENTS.md cites {t}, which doesn't exist" for t, ps in cited if not any(p.exists() for p in ps)]
    return problems


def testes(a):
    names = list(LONG_TESTS) if a.long in (None, "all") else [a.long]
    titulo, lista = (("Testes so da biblioteca padrao", STDLIB) if a.so_stdlib else
                     ("Testes do filtro", MICROFONE) if a.microfone else
                     (LONG_TITLES.get(a.long, "Testes longos"), [LONG_TESTS[n] for n in names]) if a.long else
                     ("Testes", COMPLETO + ([] if a.without_long else list(LONG_TESTS.values()))))
    md = []
    for p in (agents := agents_md()):
        print(f"FALHA {p}")
    if agents:
        md += [f"**{titulo}:** ❌ AGENTS.md:", ""] + [f"- {p}" for p in agents] + [""]
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
    # the filter tests all measure a cost or a level of the filter: one by one
    falhas, linhas = roda(titulo, lista, completo=not a.so_stdlib and not a.microfone,
                          jobs=1 if a.microfone or a.long else a.jobs)
    escreve(a.resumo, md + linhas)
    return 1 if falhas or esquecidos or agents else 0


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
    etiquetas = json.loads(os.environ.get("ETIQUETAS") or "[]") or []  # null outside a PR (the push)
    disparadas = areas(arquivos, etiquetas)
    print(f"{len(arquivos)} arquivo(s) mudaram desde {a.areas}; etiquetas: {etiquetas or 'nenhuma'}")
    linhas = [f"{area}={'true' if area in disparadas else 'false'}" for area in AREAS]
    print("\n".join(linhas))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n")
    return 0


def tela(a):
    """The --tela: the fitcheck in both languages and, with --base, the compara of the base against the one here."""
    pasta = Path(a.pasta).resolve()
    pasta.mkdir(parents=True, exist_ok=True)  # without deleting: the --pasta can be a folder that already exists
    md, bloqueia = fitcheck(pasta)
    mudou = False
    if a.base:
        md_c, bloqueia_c, mudou = compara(a, pasta)
        md, bloqueia = md + md_c, bloqueia or bloqueia_c
    escreve(a.resumo, ["**Tela:**", ""] + md)
    return 1 if bloqueia else 2 if mudou else 0


def so_compara(a):
    """The --compara: the compara of the --tela alone (the testa.yml runs it in a job of its own)."""
    pasta = Path(a.pasta).resolve()
    pasta.mkdir(parents=True, exist_ok=True)
    md, bloqueia, mudou = compara(a, pasta)
    escreve(a.resumo, ["**Compara:**", ""] + md)
    return 1 if bloqueia else 2 if mudou else 0


def capture_head(a):
    folder = Path(a.pasta).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if Path(a.capture).resolve().is_relative_to(folder / "compara"):
        raise SystemExit(f"the cache folder {a.capture} is inside {folder / 'compara'}: give it a folder of its own")
    head = executa(["git", "rev-parse", "HEAD"], limite=60)[1].strip()
    tree = Path(tempfile.mkdtemp(prefix="ritmelli-head-")) / "head"
    code, out = executa(["git", "worktree", "add", "--detach", str(tree), head], limite=300)
    try:
        if code == 0:
            code, out = executa([sys.executable, "dev/compara.py", "--ref", "--raiz", str(tree),
                                 "--pasta", str(folder / "compara")])
    finally:
        executa(["git", "worktree", "remove", "--force", str(tree)], limite=300)
        shutil.rmtree(tree.parent, ignore_errors=True)
    print(f"--- compara --ref of the HEAD {head[:12]}: exits {code}\n{out.rstrip()}", flush=True)
    if code != 0:
        md = [f"<details><summary>❌ compara: a captura do HEAD <code>{head[:12]}</code> não vale (sai {code})"
              "</summary>", "", cerca(cauda(out)), "", "</details>"]
    else:
        guarda_captura(folder / "compara" / "ref", a.capture, chave_captura(head))
        saida_do_job({"head_cache": "true"})
        md = [f"- ✅ captura do HEAD `{head[:12]}` guardada para o cache"]
    escreve(a.resumo, ["**Compara:**", ""] + md)
    return 1 if code != 0 else 0


def fitcheck(pasta):
    """The fitcheck in both languages against a --mock with the fake shelf of the compara, the data and the
    LOCALAPPDATA temporary. Returns (the markdown lines, whether it blocks)."""
    sys.path.insert(0, str(RAIZ / "dev"))
    import so_mock
    import compara as cmp  # numpy, pillow and websockets: only here, so the --so-stdlib stays standard library only

    md, bloqueia = [], False
    tmp = Path(tempfile.mkdtemp(prefix="ritmelli-tela-"))
    try:
        dados = tmp / "dados"
        dados.mkdir()
        (tmp / "local").mkdir()
        (dados / "library.json").write_text(json.dumps(cmp.prateleira(), ensure_ascii=False), encoding="utf-8")
        porta = so_mock.free_port()
        with open(pasta / "fitcheck-servidor.log", "w", encoding="utf-8") as log:
            try:
                srv = so_mock.sobe([sys.executable, str(RAIZ / "server.py"), "--mock", "--no-browser", "--port",
                                    str(porta), "--data-dir", str(dados)], porta, cwd=RAIZ, stdout=log,
                                   stderr=subprocess.STDOUT, env=dict(os.environ, LOCALAPPDATA=str(tmp / "local")))
            except so_mock.Recusa as ex:
                srv = None
                print(f"FALHA the --mock of the fitcheck did not start: {ex}")
                md.append(f"- ❌ o `--mock` do fitcheck não subiu: {ex}")
                bloqueia = True
            if srv:
                try:
                    for lang in ("pt_BR", "en"):
                        cod, saida = executa([sys.executable, "dev/fitcheck.py", f"{srv.base}/t/ritmelli/?lang={lang}"])
                        print(f"--- fitcheck {lang}: exits {cod}\n{saida.rstrip()}", flush=True)
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
        for script, what in (("dev/missing_script.py", "a theme file that does not load"),
                             ("dev/theme_scripts.py", "the theme's scripts")):
            cod, saida = executa([sys.executable, script])
            print(f"--- {Path(script).stem}: exits {cod}\n{saida.rstrip()}", flush=True)
            if cod != 0:
                bloqueia = True
                md += [f"<details><summary>❌ {what}: {script} exits {cod}</summary>", "", cerca(cauda(saida)), "",
                       "</details>"]
            else:
                n = sum(linha.startswith("OK") for linha in saida.splitlines())
                md.append(f"- ✅ {what}: {n} checks of {script} pass")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return md, bloqueia


def chave_captura(commit):
    """What a compara capture of the commit depends on: the commit, the scripts that take it (CAPTURA) and the Chrome
    version (the newest version folder next to the chrome.exe). One line, written next to the prints."""
    sys.path.insert(0, str(RAIZ / "dev"))
    from fitcheck import CHROME
    h = hashlib.sha256()
    for f in CAPTURA:
        h.update((RAIZ / f).read_bytes())
    versoes = [p.name for p in Path(CHROME).parent.glob("*.*.*.*") if p.is_dir()]
    chrome = max(versoes, key=lambda v: tuple(int(x) for x in v.split(".") if x.isdigit()), default="?")
    return f"{commit} {h.hexdigest()[:16]} chrome {chrome}"


def le_captura(cache, chave):
    """The prints of the capture in the cache folder, if it is the one of the key; [] if not."""
    marca = Path(cache) / "captura.txt"
    if not marca.is_file() or marca.read_text(encoding="utf-8").strip() != chave:
        return []
    return sorted(Path(cache).glob("*.png"))


def guarda_captura(origem, cache, chave):
    """Puts the prints of the origem folder in the cache folder, with the key. Only the prints and the key of an older
    capture leave the cache folder: anything else in it stays."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    for velho in [*cache.glob("*.png"), cache / "captura.txt"]:
        velho.unlink(missing_ok=True)
    for png in Path(origem).glob("*.png"):
        shutil.copy2(png, cache / png.name)
    (cache / "captura.txt").write_text(chave + "\n", encoding="utf-8")


def compara(a, pasta):
    """The compara: the reference from the server and the theme of the base (from the --ref-cache when it holds the
    capture of the base, else in a temporary worktree), and the comparison from the ones here. Returns (the markdown
    lines, whether it blocks, whether only prints changed). Writes to GITHUB_OUTPUT how many prints changed and which
    caches it filled."""
    md, bloqueia, mudou, saidas = [], False, False, {"prints_mudaram": 0}
    ref = pasta / "compara" / "ref"
    # a cache folder inside the compara folder would be emptied by the capture it is meant to hold
    for c in (a.ref_cache, a.head_cache):
        if c and Path(c).resolve().is_relative_to(pasta / "compara"):
            raise SystemExit(f"the cache folder {c} is inside {pasta / 'compara'}: give it a folder of its own")
    cod, saida = executa(["git", "rev-parse", "--verify", f"{a.base}^{{commit}}"], limite=60)
    base = saida.strip()
    de_onde = ""
    cache = le_captura(a.ref_cache, chave_captura(base)) if a.ref_cache and cod == 0 else []
    if cache:
        shutil.rmtree(ref, ignore_errors=True)
        ref.mkdir(parents=True)
        for png in cache:
            shutil.copy2(png, ref / png.name)
        print(f"--- compara: the reference of the base {base[:12]} comes from the cache ({len(cache)} prints)",
              flush=True)
        de_onde = " (referência do cache)"
    elif cod != 0:
        print(f"FALHA the base {a.base} is not a commit here ({cod})")
        md.append(f"- ❌ a base `{a.base}` não é um commit daqui")
        bloqueia = True
    else:
        wt = Path(tempfile.mkdtemp(prefix="ritmelli-base-")) / "base"
        cod = executa(["git", "worktree", "add", "--detach", str(wt), base], limite=300)[0]
        if cod != 0:
            print(f"FALHA the worktree of the base {a.base} did not come out ({cod})")
            md.append(f"- ❌ o worktree da base `{a.base}` não saiu")
            bloqueia = True
        else:
            try:
                cod, saida = executa([sys.executable, "dev/compara.py", "--ref", "--raiz", str(wt),
                                      "--pasta", str(pasta / "compara")])
                print(f"--- compara --ref of the base {base[:12]}: exits {cod}\n{saida.rstrip()}", flush=True)
                if cod != 0:
                    bloqueia = True
                    md += [f"<details><summary>❌ compara: a captura da base <code>{base[:12]}</code> não vale "
                           f"(sai {cod})</summary>", "", cerca(cauda(saida)), "", "</details>"]
                elif a.ref_cache:
                    guarda_captura(ref, a.ref_cache, chave_captura(base))
                    saidas["ref_cache"] = "true"
            finally:
                executa(["git", "worktree", "remove", "--force", str(wt)], limite=300)
                shutil.rmtree(wt.parent, ignore_errors=True)
    if not bloqueia:
        cod, saida = executa([sys.executable, "dev/compara.py", "--pasta", str(pasta / "compara")])
        print(f"--- compara of the PR: exits {cod}\n{saida.rstrip()}", flush=True)
        fim = saida.strip().splitlines()[-1:] or [""]
        if cod in (0, 2) and a.head_cache:
            head = executa(["git", "rev-parse", "HEAD"], limite=60)[1].strip()
            guarda_captura(pasta / "compara" / "agora", a.head_cache, chave_captura(head))
            saidas["head_cache"] = "true"
        if cod == 2:
            mudou = True
            mudaram = [linha for linha in saida.splitlines() if linha.startswith(("MUDOU", "NOVO", "SUMIU"))]
            saidas["prints_mudaram"] = len(mudaram)
            md += [f"<details><summary>⚠️ compara: os prints mudaram ({fim[0]})</summary>", "",
                   cerca(cauda("\n".join(mudaram), 40)), "", "</details>"]
        elif cod != 0:
            bloqueia = True
            md += [f"<details><summary>❌ compara: a captura do PR não vale (sai {cod})</summary>", "",
                   cerca(cauda(saida)), "", "</details>"]
        else:
            md.append(f"- ✅ compara contra a base `{base[:12]}`{de_onde}: {fim[0]}")
    saida_do_job(saidas)
    return md, bloqueia, mudou


def saida_do_job(valores):
    """Writes name=value lines to the GITHUB_OUTPUT of the step, when there is one."""
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("".join(f"{k}={v}\n" for k, v in valores.items()))


def passo(a):
    """The --passo: runs the script of the step, with its output as it comes, and exits with its code."""
    return subprocess.run([sys.executable, *PASSOS[a.passo]], cwd=RAIZ, stdin=subprocess.DEVNULL,
                          env=dict(os.environ, PYTHONUTF8="1")).returncode


def linhas(a):
    """The --linhas: the line count of each file of LINHAS here and the change against the base, in one markdown line
    for the summary."""
    partes = []
    for f in LINHAS:
        agora = len((RAIZ / f).read_text(encoding="utf-8").splitlines()) if (RAIZ / f).is_file() else 0
        cod, antes = executa(["git", "show", f"{a.linhas}:{f}"], limite=60)
        delta = agora - (len(antes.splitlines()) if cod == 0 else 0)
        partes.append(f"`{f}` {agora}" + (f" ({delta:+d})" if delta else ""))
    texto = "**Linhas, contra a base:** " + " · ".join(partes)
    print(texto)
    escreve(a.resumo, [texto])
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--so-stdlib", action="store_true", help="only the STDLIB, which runs without the app libraries")
    modo.add_argument("--microfone", action="store_true", help="the filter tests (MICROFONE)")
    modo.add_argument("--long", nargs="?", const="all", choices=[*LONG_TESTS, "all"],
                      help="only the LONG_TESTS, or the one named")
    modo.add_argument("--without-long", action="store_true", help="the COMPLETO without the LONG_TESTS")
    modo.add_argument("--tela", action="store_true", help="the fitcheck and, with --base, the compara")
    modo.add_argument("--compara", action="store_true", help="only the compara of the --tela (needs --base)")
    modo.add_argument("--capture", metavar="DIR", help="only the compara capture of the HEAD, into DIR")
    modo.add_argument("--passo", choices=sorted(PASSOS), help="a step of the testa.yml that runs one script")
    modo.add_argument("--areas", metavar="BASE", help="the areas that what changed since BASE triggers")
    modo.add_argument("--linhas", metavar="BASE", help="the line count of the big files against BASE")
    ap.add_argument("--base", help="in the --tela and the --compara: the base of the compara (a commit, a branch)")
    ap.add_argument("--pasta", default=str(RAIZ / "logs" / "tela"), help="where the prints and the logs go")
    ap.add_argument("--ref-cache", help="a folder with the capture of the base, read and filled (see above)")
    ap.add_argument("--head-cache", help="a folder that gets the capture of the HEAD")
    ap.add_argument("--resumo", help="appends the result in markdown to this file")
    ap.add_argument("--jobs", type=int, default=JOBS, help=f"how many tests at a time (default {JOBS})")
    a = ap.parse_args()
    if a.compara and not a.base:
        ap.error("the --compara needs the --base")
    if a.areas:
        return diz_areas(a)
    if a.linhas:
        return linhas(a)
    if a.passo:
        return passo(a)
    if a.tela:
        return tela(a)
    if a.compara:
        return so_compara(a)
    if a.capture:
        return capture_head(a)
    return testes(a)


if __name__ == "__main__":
    sys.exit(main())
