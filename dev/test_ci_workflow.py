import contextlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "testa.yml"
ACTION = ROOT / ".github" / "actions" / "python" / "action.yml"
TRAVAS = ROOT / "instalador" / "travas.txt"
REQUIREMENTS = (ROOT / "requirements.txt", ROOT / "requirements-dev.txt")
KNOWN_UNPINNED_ISSUE = "https://github.com/ritmelli/ritmelli/issues/231"
KNOWN_UNPINNED = {"yt-dlp", "pillow", "onnx", "jsonschema"}
HEAD = "c" * 40
QUEUE_URL = "https://example.invalid/queue/passed"
RUNS = [{"head_sha": HEAD, "conclusion": "failure", "html_url": "https://example.invalid/queue/failed"},
        {"head_sha": "d" * 40, "conclusion": "success", "html_url": "https://example.invalid/queue/other-commit"},
        {"head_sha": HEAD, "conclusion": "success", "html_url": QUEUE_URL}]

_spec = importlib.util.spec_from_file_location("testa_tudo", ROOT / "dev" / "testa_tudo.py")
testa_tudo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(testa_tudo)

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def jobs(text):
    out, current, in_jobs = {}, None, False
    for line in text.splitlines():
        if line == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        m = re.fullmatch(r"  ([\w-]+):", line)
        if m:
            current = out.setdefault(m.group(1), [])
        elif current is not None:
            current.append(line)
    return out


def step_run(lines, name):
    start = next(i for i, line in enumerate(lines) if re.fullmatch(rf"\s*- name: {re.escape(name)}", line))
    run = next(i for i in range(start + 1, len(lines)) if re.fullmatch(r"\s*run: \|", lines[i]))
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body).rstrip() + "\n"


def git_for_windows_bash():
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if not git:
        return None
    for base in Path(git).resolve().parents:
        for p in (base / "bin" / "bash.exe", base / "usr" / "bin" / "bash.exe"):
            if p.is_file():
                return str(p)
    return None


FAKE_GH = """#!/bin/bash
exec "$FAKE_PYTHON" "$FAKE_GH_PY" "$@"
"""
FAKE_GH_PY = r"""
import json
import os
import re
import sys
from urllib.parse import parse_qs, urlparse

args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write("gh " + " ".join(args) + "\n")
if args[:2] == ["pr", "comment"]:
    if os.environ.get("FAKE_COMMENT_FAILS"):
        sys.exit("non-200 OK status code: 502 Bad Gateway")
    sys.exit(0)
if args[0] != "api":
    sys.exit(f"fake gh: unexpected call: {args}")
url = urlparse(args[1])
if not url.path.endswith("/actions/workflows/testa.yml/runs"):
    print("Testes 4 min 10 s")
    sys.exit(0)
if os.environ.get("FAKE_QUEUE_FAILS"):
    sys.exit("HTTP 502")
query = parse_qs(url.query)
runs = [r for r in json.loads(os.environ["FAKE_RUNS"])
        if query.get("event") == ["merge_group"] and r["head_sha"] in query.get("head_sha", [r["head_sha"]])]
jq = args[args.index("--jq") + 1]
m = re.fullmatch(r'\[\.workflow_runs\[\] \| select\(\.conclusion == "(\w+)"\)\]\[0\]\.html_url // empty', jq)
if not m:
    sys.exit(f"fake gh: a --jq it does not know: {jq}")
print(next((r["html_url"] for r in runs if r["conclusion"] == m.group(1)), ""))
"""


def run_summary(bash, block, event, states, comment_fails=False, runs=RUNS, queue_fails=False, dono="success"):
    with tempfile.TemporaryDirectory(prefix="ritmelli-ci-") as tmp:
        tmp = Path(tmp)
        fake = tmp / "bin"
        fake.mkdir()
        (fake / "gh").write_text(FAKE_GH, encoding="utf-8", newline="\n")
        (fake / "gh").chmod(0o755)
        (tmp / "fake_gh.py").write_text(FAKE_GH_PY, encoding="utf-8")
        (tmp / "run.sh").write_text(block, encoding="utf-8", newline="\n")
        summary, log = tmp / "summary.md", tmp / "log.txt"
        summary.touch()
        log.touch()
        names = ("TESTES", "BANCA", "MICROFONE", "TELA", "COMPARA")
        env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ.get("PATH", ""), GITHUB_EVENT_NAME=event,
                   GITHUB_STEP_SUMMARY=str(summary), FAKE_LOG=str(log), FAKE_PYTHON=Path(sys.executable).as_posix(),
                   FAKE_GH_PY=(tmp / "fake_gh.py").as_posix(), FAKE_RUNS=json.dumps(runs),
                   FAKE_COMMENT_FAILS="1" if comment_fails else "",
                   FAKE_QUEUE_FAILS="1" if queue_fails else "", GH_TOKEN="x",
                   REPO="ritmelli/ritmelli", PR="7" if event == "pull_request" else "", HEAD=HEAD, RUN_ID="1",
                   ATTEMPT="1", EXECUCAO="https://example.invalid/run", S_DONO=dono, DONO="",
                   DO_REPO="true" if event == "pull_request" else "false", LINHAS="", MUDARAM="0",
                   **{f"S_{n}": s for n, s in zip(names, states)}, **{f"R_{n}": f"resumo {n}" for n in names})
        p = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "run.sh"], cwd=tmp, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        calls = log.read_text(encoding="utf-8").splitlines()
        return p.returncode, p.stdout + p.stderr, summary.read_text(encoding="utf-8"), calls


def test_summary_block(all_jobs):
    bash = git_for_windows_bash()
    check(bool(bash), "the bash of Git for Windows (or bash on the PATH outside Windows) runs the block")
    if not bash:
        return
    block = step_run(all_jobs["testa-o-pr"], "Resumo e resultado")
    ok5 = ["success"] * 5
    on_push = ["skipped"] * 4 + ["success"]

    code, out, summary, calls = run_summary(bash, block, "pull_request", ok5)
    comments = [c for c in calls if c.startswith("gh pr comment")]
    check(code == 0 and len(comments) == 1 and "tudo passou" in summary and "| Banca |" in summary,
          f"a PR whose jobs pass gets one comment, with the Banca column, and passes (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "pull_request", ok5, comment_fails=True)
    comments = [c for c in calls if c.startswith("gh pr comment")]
    check(code != 0 and len(comments) == 1 and "GitHub did not confirm the summary comment" in out
          and "não confirmou o comentário do resumo no PR" in summary,
          f"a comment GitHub does not confirm fails the check with that reason, tried once (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "push", on_push)
    queries = [c for c in calls if "event=merge_group" in c]
    check(code == 0 and summary.count("⏭️ neste push") == 4 and "a fila testou" not in summary and QUEUE_URL in summary and "queue/failed" not in summary
          and "other-commit" not in summary and len(queries) == 1
          and not any(c.startswith("gh pr comment") for c in calls),
          f"on the push, the four skipped jobs pass with the passed queue run of that very commit, asked once "
          f"(exit {code}, {len(queries)} queries)")

    code, out, summary, calls = run_summary(bash, block, "push", on_push, runs=RUNS[:2])
    check(code != 0 and "nenhuma execução aprovada da fila apareceu" in summary and "sem a fila" not in summary,
          f"on the push, with no passed queue run on the commit, the check fails (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "push", on_push, queue_fails=True)
    check(code != 0 and "a consulta das execuções da fila neste commit falhou" in summary
          and "nenhuma execução aprovada" not in summary,
          f"on the push, a failed query says so, and not that no queue run passed (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "push", ["skipped"] * 5)
    check(code != 0, f"on the push, a skipped Compara (no capture) fails the check even with the queue run (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "pull_request", ["skipped"] + ["success"] * 4)
    check(code != 0 and not any("event=merge_group" in c for c in calls),
          f"on a PR, a skipped job fails the check, and the queue is not asked (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "merge_group", ok5, dono="failure")
    check(code != 0, f"a failed needs-owner step fails the check (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "pull_request", ["success", "cancelled"] + ["success"] * 3)
    check(code != 0 and not any(c.startswith("gh pr comment") for c in calls) and "cancelada" in summary,
          f"a cancelled job fails the check and leaves the PR comment as it was (exit {code})")


def test_shape(all_jobs, text):
    skip = "    if: github.event_name != 'push'"
    for job in ("testes", "banca", "microfone", "tela"):
        check(skip in all_jobs.get(job, []), f"the {job} job skips on the push to main")
    for job in ("etiquetas", "compara"):
        check(job in all_jobs and not any(line.startswith("    if:") for line in all_jobs[job]),
              f"the {job} job runs on the push to main")
    needs = next((line for line in all_jobs["testa-o-pr"] if line.startswith("    needs:")), "")
    ids = {n.strip() for n in needs.partition("[")[2].rstrip("]").split(",")}
    check(ids == {"etiquetas", "testes", "banca", "microfone", "tela", "compara"},
          f"the Testa o PR needs the five jobs and the Etiquetas ({needs.strip()})")
    check("--captura" in "".join(all_jobs["compara"]), "the compara job runs the --captura on the push")
    saves = [line for line in all_jobs["compara"] if "steps.compara.outputs.head_cache == 'true'" in line]
    check(len(saves) == 2, f"the head capture is moved and saved to the cache when the step says head_cache ({len(saves)})")
    check(not any(re.search(r"\bsleep\b", line) for line in all_jobs["testa-o-pr"]), "the Testa o PR never sleeps")
    captura = ", ".join(f"'{f}'" for f in testa_tudo.CAPTURA)
    keys = re.findall(r"key: compara-.*hashFiles\(([^)]*)\)", text)
    check(len(keys) == 2 and all(k == captura for k in keys),
          f"both compara cache keys hash the CAPTURA files of dev/testa_tudo.py ({len(keys)} keys)")
    action = ACTION.read_text(encoding="utf-8")
    check(re.search(r"key: libs-.*hashFiles\([^)]*'instalador/travas.txt'", action) is not None,
          "the libraries cache key hashes the instalador/travas.txt")
    check(re.search(r"pip install .*-r \$env:REQUIREMENTS -c instalador/travas.txt", action) is not None,
          "the libraries are installed with the instalador/travas.txt as constraints")


def requirement(line):
    spec, _, marker = line.split("#")[0].partition(";")
    spec = spec.strip()
    m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)", spec)
    if not m:
        return None, False
    version = m.group(3).replace(" ", "")
    on_ci = not marker.strip() or re.fullmatch(r"\s*sys_platform\s*==\s*[\"']win32[\"']\s*", marker) is not None
    return re.sub(r"[-_.]+", "-", m.group(1)).lower(), on_ci and bool(re.fullmatch(r"==[^=*,<>!~]+", version))


def test_unpinned():
    pinned = {name for name, exact in map(requirement, TRAVAS.read_text(encoding="utf-8").splitlines()) if exact}
    unpinned = set()
    for req in REQUIREMENTS:
        for line in req.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("-"):
                continue
            name, exact = requirement(line)
            if name and not exact and name not in pinned:
                unpinned.add(name)
    check(unpinned == KNOWN_UNPINNED,
          f"the libraries the CI installs without a version in instalador/travas.txt are the known ones of "
          f"{KNOWN_UNPINNED_ISSUE} (now {sorted(unpinned)}; a new one gets a pin, one that got a pin leaves the list)")


def test_bench_order():
    with tempfile.TemporaryDirectory(prefix="ritmelli-ordem-") as tmp:
        tmp = Path(tmp)
        names = ["fast_a", "fast_b", "fast_c", "long_x", "long_y"]
        for n in names:
            (tmp / f"{n}.py").write_text("print('ok')\n", encoding="utf-8")
        tests = [str(tmp / f"{n}.py") for n in names]
        events, real, saved = [], testa_tudo.executa, testa_tudo.BANCA

        def recorded(cmd, *args, **kw):
            name = Path(cmd[-1]).stem
            events.append(("start", name, threading.get_ident()))
            try:
                return real(cmd, *args, **kw)
            finally:
                events.append(("end", name, threading.get_ident()))

        testa_tudo.BANCA, testa_tudo.executa = tests[3:], recorded
        try:
            with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet):
                testa_tudo.roda("order", tests, completo=False, jobs=4)
        finally:
            testa_tudo.BANCA, testa_tudo.executa = saved, real
        order = [(kind, n) for kind, n, _ in events]
        threads = {n: t for kind, n, t in events if kind == "start"}
        last_fast = max(order.index(("end", n)) for n in names[:3])
        check(order.index(("start", "long_x")) > last_fast
              and order[-4:] == [("start", "long_x"), ("end", "long_x"), ("start", "long_y"), ("end", "long_y")]
              and threads["long_x"] == threads["long_y"] == threading.get_ident(),
              "the plain run takes the BANCA one by one, after the others, on the calling thread")


def test_without_destination():
    with tempfile.TemporaryDirectory(prefix="ritmelli-dev-") as tmp:
        dev = Path(tmp)
        (dev / "test_lost.py").write_text("print('a new test in no list')\n", encoding="utf-8")
        (dev / "testa_perdido.py").write_text("print('an old-style test in no list')\n", encoding="utf-8")
        (dev / "test_by_hand.py").write_text("# manual: python dev\\test_by_hand.py precisa de um microfone\n",
                                             encoding="utf-8")
        (dev / "tester.py").write_text("print('a tool')\n", encoding="utf-8")
        (dev / "testa_tudo.py").write_text("print('the runner')\n", encoding="utf-8")
        found = [f for f in testa_tudo.sem_destino(dev=dev) if "runs nowhere" in f]
        flagged = sorted(f.split()[0] for f in found)
        check(flagged == ["dev/test_lost.py", "dev/testa_perdido.py"],
              f"the lock flags the dev/test_* and dev/testa_* tests without destination, and only them ({flagged})")
    check(testa_tudo.sem_destino() == [], "every test of dev/ has a destination, and the testa.yml calls every mode")
    check(not set(testa_tudo.BANCA) & set(testa_tudo.COMPLETO), "the bench is not in the COMPLETO (it would run twice)")
    check(testa_tudo.SERIAL <= set(testa_tudo.COMPLETO + testa_tudo.BANCA), "every SERIAL test is in a list")
    check("instalador/travas.txt" in testa_tudo.TODAS, "a change to instalador/travas.txt triggers every area")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    text = WORKFLOW.read_text(encoding="utf-8")
    all_jobs = jobs(text)
    test_shape(all_jobs, text)
    test_unpinned()
    test_bench_order()
    test_without_destination()
    test_summary_block(all_jobs)
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
