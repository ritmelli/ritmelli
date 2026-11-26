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
    python dev\testa_tudo.py --compara --base origin/main [--ref-cache <dir>] [--head-capture <dir>]
                                           only the compara of the --tela; with --head-capture, of that HEAD capture
    python dev\testa_tudo.py --capture <dir> | --capture-base <dir> --base <rev>
                                           only the compara capture of the HEAD or of the base, into the folder with
                                           its key (the jobs Compara: HEAD and Compara: base of the testa.yml)
    python dev\testa_tudo.py --passo <name> [--base <rev>]
                                           a step of the testa.yml that runs one script (PASSOS), with the --base as
                                           its last argument when given
    python dev\testa_tudo.py --areas <base> [--build-base <base>]
                                           (the PR labels come from the ETIQUETAS variable, a JSON list:
                                           $env:ETIQUETAS = '["extracao-tema"]'; in an argument, PowerShell 5.1 would
                                           drop the quotes)
                                           the path filter of the testa.yml: says (and writes to GITHUB_OUTPUT) whether
                                           what changed since the base, or a PR label, triggers the filter job and the
                                           screen jobs, and whether what changed since the --build-base (the base when
                                           there is none) changes the build (monta=, the BUILD_PATHS: the Verdict then
                                           asks for a passed monta.yml run on the PR head)
        [--resumo arquivo.md]              appends the result in markdown (the PR summary)
        [--jobs N]                         how many tests run at a time (default 4); the ones in SERIAL always run
                                           one by one, alone, after the others

In the COMPLETO and the --long, a missing library or ffmpeg is a failure, not a skipped test: without the server
libraries, the testa_mock and the testa_migra skip their part.

Every test of the git ls-files, in any folder (test*.py, testa*.py, teste*.py and the test*.ps1; a new test, in English,
is named test_*), has a destination: a list here (STDLIB, COMPLETO, LONG_TESTS, MICROFONE, PASSOS) or a workflow step for
a .ps1, or it only runs by hand and says so at the top of the file, in a comment before the docstring, how and with
what: "# manual: <comando> precisa de <aparelho>". Before running, the COMPLETO, the --long, the --so-stdlib and the
--microfone fail on a test without destination, on a file with the "manual:" line that runs in the checks, and on a
mode of REQUIRED_MODES that left the required check (its job, step, command or condition).
They also fail an AGENTS.md over 80 lines or with a file in its map that doesn't exist (agents_md).

The --ref-cache is a folder with a capture of the compara: when it holds the one of the base (the commit and the key of
the capture, CAPTURA), the base is not captured again; when it does not, the base capture goes there. The --head-cache
gets the capture of the HEAD, which is the reference of the PRs that will have it as their base (the push to main).

Exits 0 if everything passed and 1 if something failed; in the --tela and the --compara, 2 if only the compara prints
changed (the testa.yml decides).
"""
import argparse
import fnmatch
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

from workflow_yaml import find_step, job_steps, workflows

RAIZ = Path(__file__).resolve().parent.parent

# so a biblioteca padrao: a monta.yml roda estes antes de instalar as bibliotecas do app
STDLIB = [f"dev/testa_{n}.py" for n in ("i18n", "metricas", "migra", "mock", "vozes", "pareamento", "grava", "mfx",
                                             "ganchos", "pasta_protegida", "so_mock")] + [
    "dev/test_trusted_author.py", "dev/test_needs_owner.py", "dev/test_ci_workflow.py",
    "dev/test_forbidden_terms.py", "dev/test_music.py", "dev/test_bumbo_grid.py", "dev/garden.py",
    "dev/test_garden.py", "dev/test_audio_imports.py", "dev/test_monta_contract.py", "dev/test_syntax.py"]
# o STDLIB mais os que usam as bibliotecas do app (requirements-dev.txt) e o ffmpeg
COMPLETO = STDLIB + [f"dev/testa_{n}.py" for n in (
    "adianta", "anel", "atualizacao", "atualizador", "automatico", "comandos", "congela", "conversor", "ganho", "musica",
    "passagens", "pedal_voz", "pista", "preabre", "protocolo", "rapido", "transicao", "vivo")] + [
    "instalador/atualizacao/testa_parcial.py", "dev/test_compara_not_ready.py",
    "dev/test_compara_push_steps.py", "dev/test_external_module.py", "dev/test_release_workflow.py",
    "dev/test_fitcheck_ready.py", "dev/test_mock_stop.py", "dev/test_stretch_outgoing.py", "dev/test_grava_cfg.py",
    "dev/test_andamento.py", "dev/test_compasso.py", "dev/test_winvol.py", "dev/test_uninstall_wait.py",
    "dev/test_theme_rebuild.py", "dev/test_syntax_oracles.py"]
LONG_TESTS = {"bench": "dev/testa_passagem.py", "capture": "dev/test_capture.py"}
# os do filtro, com as DLLs do microfone\apo\compila.bat teste: o testa.yml so roda quando a area do filtro muda
# o testa_aparelho_mudo fica aqui pelo Inno Setup, que o job do filtro instala: sem ele, os casos do instalador
# pulariam
MICROFONE = ["dev/testa_filtro.py", "dev/testa_voz.py", "dev/testa_microfone.py", "dev/testa_aparelho_mudo.py",
             "microfone/apo/teste/teste_reamostra.py"]
DLLS = ("teste_reamostra.dll", "voz.dll", "banca_filtro.dll")

# o que o COMPLETO precisa (os modulos do requirements-dev.txt e os programas do PATH): sem um deles, falha antes
MODULOS = ("numpy", "scipy", "sounddevice", "pedalboard", "aiohttp", "segno", "yt_dlp", "Cryptodome", "ytmusicapi",
           "onnxruntime", "comtypes", "webview", "websockets", "PIL", "onnx", "jsonschema", "yaml", "tree_sitter",
           "tree_sitter_javascript", "tree_sitter_css")
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
# the steps of the testa.yml that run one script of their own, by name (--passo), with the --base as the last argument
# when given: the protected folder on the real disk (it needs an administrator: the GitHub machine is one; on a PC, only
# a test Windows), the usage data notice of the theme, the PR description and the two proofs of a theme extraction
PASSOS = {"disco": ("dev/testa_pasta_protegida.py", "--disco"), "metricas": ("dev/fitcheck.py", "--metricas"),
          "pr-description": ("dev/garden.py", "--pr-description"), "theme-rebuild": ("dev/theme_rebuild.py",),
          "theme-listeners": ("dev/theme_listeners.py",)}
# what the --tela and the --compara run
TELA = ("dev/fitcheck.py", "dev/compara.py", "dev/missing_script.py", "dev/theme_scripts.py",
        "dev/test_theme_listeners.py", "dev/theme_page_oracle.py")
NOT_ON_PUSH = "github.event_name != 'push'"
AFTER_RUFF = "${{ !cancelled() && steps.ruff.outcome != 'skipped' }}"
SUMMARY_ARG = r'--resumo "$env:RUNNER_TEMP\resumo.md"'
EXTRACTION = ("${{ !cancelled() && steps.areas.outputs.extracao == 'true' && steps.areas.outputs.tela == 'true' && "
              "steps.tela.outcome != 'skipped' }}")
HEAD_RUN = ('python dev/testa_tudo.py --capture "$env:RUNNER_TEMP\\compara-ref" --pasta "$env:RUNNER_TEMP\\tela" '
            f'{SUMMARY_ARG}')
BASE_RUN = ('python dev/testa_tudo.py --capture-base "$env:RUNNER_TEMP\\compara-ref" --base $env:BASE_SHA --pasta '
            f'"$env:RUNNER_TEMP\\tela" {SUMMARY_ARG}')
COMPARA_RUN = "\n".join((
    'python dev/testa_tudo.py --compara --base $env:BASE_SHA --pasta "$env:RUNNER_TEMP\\tela" --ref-cache '
    f'"$env:RUNNER_TEMP\\compara-ref" --head-capture "$env:RUNNER_TEMP\\compara-head" {SUMMARY_ARG}',
    "$cod = $LASTEXITCODE",
    "if ($cod -eq 2) {",
    "  Add-Content -Path $env:GITHUB_OUTPUT -Value 'mudou=true' -Encoding utf8",
    "  if ($env:EXTRACAO -eq 'true') { '::error::the compara prints changed, and the PR has the extracao-tema label'; exit 1 }",
    "  '::warning::the compara prints changed: the differences are in the compara artifact, for review'",
    "  exit 0",
    "}",
    "exit $cod"))
REQUIRED_MODES = {
    "--without-long": ("testes", NOT_ON_PUSH, "Testes", AFTER_RUFF,
                       f"python dev/testa_tudo.py --without-long {SUMMARY_ARG}"),
    "--passo disco": ("testes", NOT_ON_PUSH, "Pasta protegida no disco", AFTER_RUFF,
                      "python dev/testa_tudo.py --passo disco"),
    "--long bench": ("bench", NOT_ON_PUSH, "Banca", None, f"python dev/testa_tudo.py --long bench {SUMMARY_ARG}"),
    "--long capture": ("capture", NOT_ON_PUSH, "Captura", "steps.areas.outputs.tela == 'true'",
                       f"python dev/testa_tudo.py --long capture {SUMMARY_ARG}"),
    "--microfone": ("microfone", NOT_ON_PUSH, "Testes do filtro", "steps.areas.outputs.microfone == 'true'",
                    f"python dev/testa_tudo.py --microfone {SUMMARY_ARG}"),
    "--tela": ("tela", NOT_ON_PUSH, "fitcheck", "steps.areas.outputs.tela == 'true'",
               f'python dev/testa_tudo.py --tela --pasta "$env:RUNNER_TEMP\\tela" {SUMMARY_ARG}'),
    "--passo metricas": ("tela", NOT_ON_PUSH, "Aviso dos dados de uso",
                         "${{ !cancelled() && steps.areas.outputs.tela == 'true' && steps.tela.outcome != 'skipped' }}",
                         "python dev/testa_tudo.py --passo metricas"),
    "--passo pr-description": ("testes", NOT_ON_PUSH, "PR description", "${{ !cancelled() }}",
                               "python dev/testa_tudo.py --passo pr-description"),
    "--passo theme-rebuild": ("tela", NOT_ON_PUSH, "Only moves code", EXTRACTION,
                              "python dev/testa_tudo.py --passo theme-rebuild --base $env:PROOF_BASE"),
    "--passo theme-listeners": ("tela", NOT_ON_PUSH, "Same listeners", EXTRACTION,
                                "python dev/testa_tudo.py --passo theme-listeners --base $env:PROOF_BASE"),
    "--compara": ("compara", NOT_ON_PUSH, "compara", "steps.areas.outputs.roda == 'true'", COMPARA_RUN),
    "--capture": ("compara-head", None, "Captura do HEAD", "steps.areas.outputs.roda == 'true'", HEAD_RUN),
    "--capture-base": ("compara-base", NOT_ON_PUSH, "Captura da base", "steps.areas.outputs.roda == 'true'", BASE_RUN),
}
COMPARA_ENV = {"EXTRACAO": "${{ steps.areas.outputs.extracao }}", "BASE_SHA": "${{ steps.chave.outputs.base }}"}
PROOF_BASE_ENV = {"PROOF_BASE": "${{ github.event_name == 'merge_group' && needs.etiquetas.outputs.queue_base || "
                                "github.event.pull_request.base.sha }}"}
REQUIRED_ENV = {"--compara": COMPARA_ENV, "--capture-base": {"BASE_SHA": "${{ steps.chave.outputs.base }}"},
                "--passo pr-description": {"GH_TOKEN": "${{ github.token }}"},
                "--passo theme-rebuild": PROOF_BASE_ENV, "--passo theme-listeners": PROOF_BASE_ENV}
BASE_ENV = "${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before }}"
AREAS_RUN = "python dev/testa_tudo.py --areas $env:BASE"
BUILD_AREAS_RUN = "python dev/testa_tudo.py --areas $env:BASE --build-base $env:BUILD_BASE"
BUILD_BASE_ENV = {"BUILD_BASE": "${{ github.event_name == 'merge_group' && needs.etiquetas.outputs.queue_base || "
                                "github.event.pull_request.base.sha || github.event.before }}"}
SCREEN_AREAS_RUN = "\n".join((
    AREAS_RUN,
    "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
    """$extracao = if ($env:ETIQUETAS -match '"extracao-tema"') { 'true' } else { 'false' }""",
    'Add-Content -Path $env:GITHUB_OUTPUT -Value "extracao=$extracao" -Encoding utf8'))
LABELS_ENV = {"ETIQUETAS": "${{ needs.etiquetas.outputs.lista }}"}
SOURCE_STEPS = {
    ("testes", "ruff"): ("ruff", None, "python -m ruff check --output-format github .", None),
    ("microfone", "areas"): ("O PR mexe no filtro?", None, BUILD_AREAS_RUN, BUILD_BASE_ENV),
    ("tela", "areas"): ("O PR mexe na tela?", None, SCREEN_AREAS_RUN, LABELS_ENV),
    ("capture", "areas"): ("O PR mexe na tela?", None, SCREEN_AREAS_RUN, LABELS_ENV),
    ("compara", "areas"): ("O PR mexe na tela?", None, "\n".join((
        """if ($env:GITHUB_EVENT_NAME -eq 'push') { Add-Content -Path $env:GITHUB_OUTPUT -Value "roda=true" -Encoding utf8; """
        "exit 0 }",
        SCREEN_AREAS_RUN,
        "$tela = Select-String -Path $env:GITHUB_OUTPUT -Pattern '^tela=true$' -Quiet",
        "$roda = if ($tela) { 'true' } else { 'false' }",
        'Add-Content -Path $env:GITHUB_OUTPUT -Value "roda=$roda" -Encoding utf8')), LABELS_ENV),
    ("compara", "chave"): ("Capture key", "steps.areas.outputs.roda == 'true'", "\n".join((
        r"$chrome = (Get-Item 'C:\Program Files\Google\Chrome\Application\chrome.exe').VersionInfo.ProductVersion",
        "$base = ''",
        "if ($env:GITHUB_EVENT_NAME -ne 'push') {",
        '  $base = git rev-parse --verify "$env:COMPARA_BASE^{commit}"',
        '  if ($LASTEXITCODE -ne 0) { "::error::the compara base $env:COMPARA_BASE is not a commit here"; exit 1 }',
        "}",
        'Add-Content -Path $env:GITHUB_OUTPUT -Value "chave=$env:ImageOS-$env:ImageVersion-chrome$chrome`nbase=$base" '
        "-Encoding utf8")), None),
}
SOURCE_STEPS.update({(job, step): SOURCE_STEPS[("compara", step)] for job in ("compara-base", "compara-head")
                     for step in ("areas", "chave")})
PS1_TESTS = {
    "instalador/testa-atualizador.ps1": (
        "testa-atualizador", None, "Instala, a tarefa atualiza e o Ritmelli abre de novo", None,
        r'instalador\testa-atualizador.ps1 -Setup "saida\Ritmelli-$env:VERSAO-setup.exe" -Manifesto saida\manifest.json'),
    "instalador/testa-parcial.ps1": (
        "testa-parcial", "needs.monta.outputs.parcial == 'true'", "Instala a anterior, aplica a parcial e confere", None,
        r'instalador\testa-parcial.ps1 -Manifesto saida\manifest.json -Parcial "saida\Ritmelli-$env:VERSAO-parcial.exe"'),
    "instalador/testa-migracao.ps1": (
        "testa-migracao", "needs.monta.outputs.anterior == 'true'",
        "Instala a publicada, o setup novo por cima e confere (${{ matrix.scenario }})", None,
        r'instalador\testa-migracao.ps1 -Setup "saida\Ritmelli-$env:VERSAO-setup.exe" -Versao $env:VERSAO '
        r'-Scenario $env:SCENARIO'),
}
PS1_ENV = {"instalador/testa-atualizador.ps1": {"VERSAO": "${{ needs.monta.outputs.versao }}"},
           "instalador/testa-parcial.ps1": {"VERSAO": "${{ needs.monta.outputs.versao }}"},
           "instalador/testa-migracao.ps1": {"VERSAO": "${{ needs.monta.outputs.versao }}",
                                             "SCENARIO": "${{ matrix.scenario }}"}}
REQUIRED_JOB = "testa-o-pr"
VERDICT_STEP = "Verdict"
# what goes into the key of a compara capture besides the commit and the Chrome version: the scripts that take it and
# the libraries of the server
CAPTURA = ("dev/compara.py", "dev/fitcheck.py", "dev/so_mock.py", "requirements.txt", "requirements-dev.txt",
           "instalador/travas.txt", "dev/travas.txt")
LONG_TITLES = {"bench": "Banca", "capture": "Captura"}
# o filtro por caminho do testa.yml (caminhos do git, com /; o que termina em / e a pasta inteira). O PR que leva
# codigo de renderizacao ou de traducao para outro modulo poe o modulo na "tela"
AREAS = {
    "microfone": ("microfone/", "fx.py", "engine.py", "versao.py", "dev/testa_filtro.py", "dev/testa_voz.py",
                  "dev/testa_microfone.py", "dev/testa_aparelho_mudo.py", "instalador/mudos.iss"),
    "tela": ("themes/", "gallery/", "server.py", "theme_page.py", "i18n.py", "metricas.py", "dev/compara.py",
             "dev/fitcheck.py", "dev/so_mock.py", "dev/missing_script.py", "dev/theme_scripts.py",
             "dev/theme_listeners.py", "dev/test_theme_listeners.py", "dev/test_capture.py",
             "dev/theme_page_oracle.py", "dev/theme_page_cases.py"),
}
TODAS = (".github/workflows/testa.yml", ".github/actions/", "dev/testa_tudo.py", "instalador/travas.txt", "dev/travas.txt")
# a etiqueta do PR que dispara uma area mesmo sem arquivo dela: a extracao-tema, do PR que leva codigo de
# renderizacao ou de traducao do tema para outro modulo (posta por quem mantem o repo)
ETIQUETAS = {"extracao-tema": "tela"}


BUILD_PATHS = ("instalador/", "atualiza*.py", "migra.py", "pastas.py", "microfone/microfone.py", "microfone/apo/",
               "ritmelli.spec", ".github/workflows/monta.yml", ".github/actions/inno-setup/")


def touches_build(files):
    return any(f.startswith(p) if p.endswith("/") else fnmatch.fnmatchcase(f, p) for f in files for p in BUILD_PATHS)


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


TEST_NAME = re.compile(r"(?:test|testa|teste)(?:_\w+)?\.py|(?:test|testa|teste)(?:[-_][\w-]+)?\.ps1")


def is_test(rel):
    return TEST_NAME.fullmatch(rel.rsplit("/", 1)[-1]) is not None and rel != "dev/testa_tudo.py"


def tracked(root=RAIZ):
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return [f for f in out.decode("utf-8").split("\0") if f]


def step_failures(where, jobs, job_id, job_if, step_name, step_if, run, env, sources=None, shell=None):
    """What takes a step out of its run: its job or step gone, a condition other than job_if and step_if, a
    continue-on-error, defaults on the job, a shell other than shell, a run other than run, an env other than env, or
    a step its condition and env read by id that is
    not a single earlier step of the job, or (with sources, the ids of the job whose steps are pinned) not one of
    them."""
    job = jobs.get(job_id)
    if job is None:
        return [f"{where}: the job is gone"]
    falhas = []
    if job.get("if") != job_if:
        falhas.append(f"{where}: the job runs with if: {job.get('if')}, not {job_if}")
    if job.get("continue-on-error") is not None:
        falhas.append(f"{where}: the job has continue-on-error")
    if job.get("defaults") is not None:
        falhas.append(f"{where}: the job has defaults")
    step = find_step(job, step_name)
    if step is None:
        return falhas + [f"{where}: no single step with that name"]
    if step.get("if") != step_if:
        falhas.append(f"{where}: the step runs with if: {step.get('if')}, not {step_if}")
    if step.get("continue-on-error") is not None:
        falhas.append(f"{where}: the step has continue-on-error")
    if step.get("shell") != shell:
        falhas.append(f"{where}: the step runs in the shell {step.get('shell')}, not {shell}")
    if (step.get("run") or "").rstrip("\n") != run:
        falhas.append(f"{where}: the step no longer runs exactly {run!r}")
    if step.get("env") != env:
        falhas.append(f"{where}: the step env is {step.get('env')}, not {env}")
    steps = job_steps(job)
    before = [s.get("id") for s in steps[:steps.index(step)]]
    read = set(re.findall(r"steps\.([\w-]+)\.", " ".join([step_if or "", *(env or {}).values()])))
    falhas += [f"{where}: it reads steps.{i}, which is not a single earlier step of the job" for i in sorted(read)
               if before.count(i) != 1]
    if sources is not None:
        falhas += [f"{where}: it reads steps.{i}, a step with no row in SOURCE_STEPS" for i in sorted(read - sources)]
    return falhas


def source_failures(jobs):
    """The step_failures of each step of SOURCE_STEPS, and the ids of each job whose steps are pinned (its
    SOURCE_STEPS and the steps of its REQUIRED_MODES)."""
    sources = {}
    for (job_id, step_id), _ in SOURCE_STEPS.items():
        sources.setdefault(job_id, set()).add(step_id)
    for job_id, _, step_name, _, _ in REQUIRED_MODES.values():
        step = find_step(jobs.get(job_id) or {}, step_name) or {}
        if step.get("id"):
            sources.setdefault(job_id, set()).add(step["id"])
    falhas = []
    for (job_id, step_id), (step_name, step_if, run, env) in SOURCE_STEPS.items():
        job = jobs.get(job_id) or {}
        where = f"the testa.yml step \"{step_name}\" (job {job_id}, id {step_id}), which a required mode reads"
        falhas += step_failures(where, jobs, job_id, job.get("if"), step_name, step_if, run, env, sources[job_id])
        if (find_step(job, step_name) or {}).get("id") != step_id:
            falhas.append(f"{where}: its id is not {step_id}")
    return falhas, sources


def ps1_failures(flows):
    """The step_failures of each PowerShell test of PS1_TESTS in the monta.yml, by its path."""
    monta = flows.get(".github/workflows/monta.yml") or {}
    jobs = monta.get("jobs") or {}
    top = ["the monta.yml has defaults"] if monta.get("defaults") is not None else []
    return {rel: top + step_failures(f"{rel} (the monta.yml job {row[0]}, step \"{row[2]}\")", jobs, *row,
                                     PS1_ENV[rel], shell="powershell")
            for rel, row in PS1_TESTS.items()}


def mode_failures(flows):
    """What takes a mode of REQUIRED_MODES out of the required check: its step_failures, the source_failures of the
    steps it reads, or its job missing from the needs and the verdict of the required job."""
    testa = flows.get(".github/workflows/testa.yml") or {}
    jobs = testa.get("jobs") or {}
    required = jobs.get(REQUIRED_JOB) or {}
    verdict = find_step(required, VERDICT_STEP) or {}
    results = set((verdict.get("env") or {}).values())
    falhas, sources = source_failures(jobs)
    if testa.get("defaults") is not None:
        falhas.append("the testa.yml has defaults")
    if (testa.get("env") or {}).get("BASE") != BASE_ENV:
        falhas.append(f"the BASE of the testa.yml is {(testa.get('env') or {}).get('BASE')}, not {BASE_ENV}")
    falhas += [f"the {job_id} job of the testa.yml sets its own BASE" for job_id, job in jobs.items()
               if "BASE" in (job.get("env") or {}) or any("BASE" in (s.get("env") or {}) for s in job_steps(job))]
    for mode, (job_id, job_if, step_name, step_if, run) in REQUIRED_MODES.items():
        where = f"the testa.yml mode {mode} (job {job_id}, step \"{step_name}\")"
        falhas += step_failures(where, jobs, job_id, job_if, step_name, step_if, run, REQUIRED_ENV.get(mode),
                                sources.get(job_id, set()))
        if job_id not in (required.get("needs") or []):
            falhas.append(f"{where}: the {REQUIRED_JOB} job does not need it")
        if f"${{{{ needs.{job_id}.result }}}}" not in results:
            falhas.append(f"{where}: the {VERDICT_STEP} step does not read its result")
    passos = {f"--passo {n}" for n in PASSOS} | {f"--long {n}" for n in LONG_TESTS}
    falhas += [f"{m} has no row in REQUIRED_MODES" for m in sorted(passos - set(REQUIRED_MODES))]
    return falhas


def sem_destino(root=RAIZ, files=None, flows=None):
    """What takes a test out of the checks unnoticed: a Python test of the repo (is_test, in any folder of the git
    ls-files) in no list here (STDLIB, COMPLETO, LONG_TESTS, MICROFONE, PASSOS, TELA), a PowerShell test outside
    PS1_TESTS, either without the "manual:" line; a PS1_TESTS step out of the monta.yml (ps1_failures); a file with the line that runs anyway, or with the line out
    of format; a mode of REQUIRED_MODES out of the required check (mode_failures), and a dev/ script the testa.yml calls
    directly instead of through PASSOS. Returns the failure lines."""
    root = Path(root)
    files = tracked(root) if files is None else files
    flows = workflows(root) if flows is None else flows
    rodam = set(COMPLETO) | set(LONG_TESTS.values()) | set(MICROFONE) | {cmd[0] for cmd in PASSOS.values()} | set(TELA)
    ps1 = ps1_failures(flows)
    falhas = []
    for rel in sorted(f for f in files if f.endswith((".py", ".ps1"))):
        if not (root / rel).is_file():
            continue
        linha = manual(root / rel)
        runs_somewhere = rel in rodam if rel.endswith(".py") else rel in ps1
        falhas += ps1.get(rel, [])
        if linha and not re.match(r"#\s*manual:\s*\S.*\s+precisa de\s+\S", linha):
            falhas.append(f"{rel}: the line \"{linha}\" does not follow \"# manual: <comando> precisa de <aparelho>\"")
        elif linha and runs_somewhere:
            falhas.append(f"{rel} has the \"manual:\" line and runs in the checks: drop the line or the test")
        elif not linha and is_test(rel) and not runs_somewhere:
            falhas.append(f"{rel} runs nowhere (in no list of dev/testa_tudo.py: STDLIB, COMPLETO, LONG_TESTS, "
                          "MICROFONE or PASSOS, or PS1_TESTS for a .ps1) and has no "
                          "\"# manual: <comando> precisa de <aparelho>\" line at the top")
    falhas += mode_failures(flows)
    testa = flows.get(".github/workflows/testa.yml") or {}
    citados = {m.replace("\\", "/") for job in (testa.get("jobs") or {}).values() for step in job_steps(job)
               for m in re.findall(r"python(?:\.exe)?\s+['\"]?(dev[/\\]\w+\.py)", step.get("run") or "")}
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


# a file in the map: a backticked path with a folder or an extension (its first word, before an option)
MAP_FILE = re.compile(r"^(?:[\w.-]+/)*[\w.-]+(?:/|\.[A-Za-z]\w*)$")


def agents_md(path=RAIZ / "AGENTS.md"):
    """What is wrong with the AGENTS.md: a file in the map table that doesn't exist (in the files column, from the repo
    root; in the test column, a bare testa_* from dev/, a path from the root, and a bare file name from dev/ or from the
    root, since a note there may name an app file). Its line count is a counter of dev/garden.py."""
    lines = path.read_text(encoding="utf-8").splitlines()
    problems = []
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


def changed_files(base, cwd=RAIZ):
    cod, saida = executa(["git", "diff", "--name-only", "-z", "--no-renames", base, "HEAD"], limite=60, cwd=cwd)
    if cod != 0:
        print(f"o git diff contra {base} falhou ({cod}):\n{saida}")
        return None
    return [arq for arq in saida.split(chr(0)) if arq.strip()]


def diz_areas(a):
    """O --areas: o git diff --name-only da base ate o HEAD. Sem rename: o arquivo que sai de uma area conta nela. Com o
    -z, o caminho com acento vem inteiro, e nao entre aspas."""
    arquivos = changed_files(a.areas)
    build_files = arquivos if a.build_base is None else changed_files(a.build_base)
    if arquivos is None or build_files is None:
        return 1
    etiquetas = json.loads(os.environ.get("ETIQUETAS") or "[]") or []  # null outside a PR (the push)
    disparadas = areas(arquivos, etiquetas)
    print(f"{len(arquivos)} arquivo(s) mudaram desde {a.areas}; etiquetas: {etiquetas or 'nenhuma'}")
    linhas = [f"{area}={'true' if area in disparadas else 'false'}" for area in AREAS]
    linhas.append(f"monta={'true' if touches_build(build_files) else 'false'}")
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


def capture(a):
    folder = Path(a.pasta).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    cache = a.capture or a.capture_base
    if Path(cache).resolve().is_relative_to(folder / "compara"):
        raise SystemExit(f"the cache folder {cache} is inside {folder / 'compara'}: give it a folder of its own")
    rev, what, de, output = ((a.base, "the base", "da base", "ref_cache") if a.capture_base else
                             ("HEAD", "the HEAD", "do HEAD", "head_cache"))
    title = "**Compara: base:**" if a.capture_base else "**Compara: HEAD:**"
    code, commit = executa(["git", "rev-parse", "--verify", f"{rev}^{{commit}}"], limite=60)
    commit = commit.strip()
    if code != 0:
        print(f"FALHA {rev} is not a commit here ({code})")
        escreve(a.resumo, [title, "", f"- ❌ `{rev}` não é um commit daqui"])
        return 1
    if a.capture_base and le_captura(cache, chave_captura(commit)):
        print(f"--- compara: the capture of the base {commit[:12]} is already in {cache}", flush=True)
        escreve(a.resumo, [title, "", f"- ✅ captura da base `{commit[:12]}` já no cache"])
        return 0
    tree = Path(tempfile.mkdtemp(prefix="ritmelli-capture-")) / "tree"
    code, out = executa(["git", "worktree", "add", "--detach", str(tree), commit], limite=300)
    try:
        if code == 0:
            code, out = executa([sys.executable, "dev/compara.py", "--ref", "--raiz", str(tree),
                                 "--pasta", str(folder / "compara")])
    finally:
        executa(["git", "worktree", "remove", "--force", str(tree)], limite=300)
        shutil.rmtree(tree.parent, ignore_errors=True)
    print(f"--- compara --ref of {what} {commit[:12]}: exits {code}\n{out.rstrip()}", flush=True)
    if code != 0:
        md = [f"<details><summary>❌ compara: a captura {de} <code>{commit[:12]}</code> não vale (sai {code})"
              "</summary>", "", cerca(cauda(out)), "", "</details>"]
    else:
        guarda_captura(folder / "compara" / "ref", cache, chave_captura(commit))
        saida_do_job({output: "true"})
        md = [f"- ✅ captura {de} `{commit[:12]}` guardada para o cache"]
    escreve(a.resumo, [title, ""] + md)
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
        for script, what in (("dev/missing_script.py", "the theme page as the server sends it"),
                             ("dev/theme_scripts.py", "the theme's scripts"),
                             ("dev/test_theme_listeners.py", "the listener reader of dev/theme_listeners.py"),
                             ("dev/theme_page_oracle.py", "the theme page's grammar against Chrome")):
            started = time.monotonic()
            cod, saida = executa([sys.executable, script])
            took = time.monotonic() - started
            print(f"--- {Path(script).stem}: exits {cod} in {took:.0f} s\n{saida.rstrip()}", flush=True)
            if cod != 0:
                bloqueia = True
                md += [f"<details><summary>❌ {what}: {script} exits {cod}</summary>", "", cerca(cauda(saida)), "",
                       "</details>"]
            else:
                n = sum(linha.startswith("OK") for linha in saida.splitlines())
                md.append(f"- ✅ {what}: {n} checks of {script} pass in {took:.0f} s")
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
    for c in (a.ref_cache, a.head_cache, a.head_capture):
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
    extra = []
    if not bloqueia and a.head_capture:
        head = executa(["git", "rev-parse", "HEAD"], limite=60)[1].strip()
        prints = le_captura(a.head_capture, chave_captura(head))
        if prints:
            agora = pasta / "compara" / "agora"
            shutil.rmtree(agora, ignore_errors=True)
            agora.mkdir(parents=True)
            for png in prints:
                shutil.copy2(png, agora / png.name)
            extra = ["--compare-only"]
        else:
            print(f"--- compara: {a.head_capture} has no capture of the HEAD {head[:12]} with this Chrome and these "
                  "scripts: the HEAD is captured here", flush=True)
            md.append(f"- ⚠️ a captura do HEAD `{head[:12]}` do job Compara: HEAD não vale aqui (outro Chrome ou "
                      "outros scripts): refeita neste job")
    if not bloqueia:
        cod, saida = executa([sys.executable, "dev/compara.py", "--pasta", str(pasta / "compara"), *extra])
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
    return subprocess.run([sys.executable, *PASSOS[a.passo], *([a.base] if a.base else [])], cwd=RAIZ,
                          stdin=subprocess.DEVNULL,
                          env=dict(os.environ, PYTHONUTF8="1")).returncode


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
    modo.add_argument("--capture-base", metavar="DIR", help="only the compara capture of the --base, into DIR")
    modo.add_argument("--passo", choices=sorted(PASSOS), help="a step of the testa.yml that runs one script")
    modo.add_argument("--areas", metavar="BASE", help="the areas that what changed since BASE triggers")
    ap.add_argument("--base", help="in the --tela and the --compara: the base of the compara (a commit, a branch)")
    ap.add_argument("--build-base", help="in the --areas: the base the monta= line compares to (the commit before the "
                                         "PR in a queue entry), when it is not the BASE of the other areas")
    ap.add_argument("--pasta", default=str(RAIZ / "logs" / "tela"), help="where the prints and the logs go")
    ap.add_argument("--ref-cache", help="a folder with the capture of the base, read and filled (see above)")
    ap.add_argument("--head-cache", help="a folder that gets the capture of the HEAD")
    ap.add_argument("--head-capture", help="in the --compara: a folder with the --capture of the HEAD, compared as is")
    ap.add_argument("--resumo", help="appends the result in markdown to this file")
    ap.add_argument("--jobs", type=int, default=JOBS, help=f"how many tests at a time (default {JOBS})")
    a = ap.parse_args()
    if (a.compara or a.capture_base) and not a.base:
        ap.error("the --compara and the --capture-base need the --base")
    if a.areas:
        return diz_areas(a)
    if a.passo:
        return passo(a)
    if a.tela:
        return tela(a)
    if a.compara:
        return so_compara(a)
    if a.capture or a.capture_base:
        return capture(a)
    return testes(a)


if __name__ == "__main__":
    sys.exit(main())
