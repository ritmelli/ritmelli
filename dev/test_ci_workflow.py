import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "testa.yml"
ACTION = ROOT / ".github" / "actions" / "python" / "action.yml"
TRAVAS = ROOT / "instalador" / "travas.txt"
REQUIREMENTS = (ROOT / "requirements.txt", ROOT / "requirements-dev.txt")
KNOWN_UNPINNED_ISSUE = "https://github.com/ritmelli/ritmelli/issues/231"
KNOWN_UNPINNED = {"yt-dlp", "pillow", "onnx", "jsonschema"}
QUEUE_URL = "https://example.invalid/queue"

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


FAKE_GH = r"""#!/bin/bash
echo "gh $*" >> "$FAKE_LOG"
if [ "$1" = api ]; then
  case "$2" in
    *event=merge_group*) if [ -n "$FAKE_QUEUE_FAILS" ]; then echo "HTTP 502" >&2; exit 1; fi; echo "$FAKE_QUEUE_URL" ;;
    *) echo "Testes 4 min 10 s" ;;
  esac
  exit 0
fi
if [ "$1 $2" = "pr comment" ]; then
  if [ -n "$FAKE_COMMENT_FAILS" ]; then echo "non-200 OK status code: 502 Bad Gateway" >&2; exit 1; fi
  exit 0
fi
echo "fake gh: unexpected call: $*" >&2
exit 2
"""


def run_summary(bash, block, event, states, comment_fails=False, queue_url="", queue_fails=False, dono="success"):
    with tempfile.TemporaryDirectory(prefix="ritmelli-ci-") as tmp:
        tmp = Path(tmp)
        fake = tmp / "bin"
        fake.mkdir()
        (fake / "gh").write_text(FAKE_GH, encoding="utf-8", newline="\n")
        (fake / "gh").chmod(0o755)
        (tmp / "run.sh").write_text(block, encoding="utf-8", newline="\n")
        summary, log = tmp / "summary.md", tmp / "log.txt"
        summary.touch()
        log.touch()
        names = ("TESTES", "BANCA", "MICROFONE", "TELA", "COMPARA")
        env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ.get("PATH", ""), GITHUB_EVENT_NAME=event,
                   GITHUB_STEP_SUMMARY=str(summary), FAKE_LOG=str(log),
                   FAKE_COMMENT_FAILS="1" if comment_fails else "", FAKE_QUEUE_URL=queue_url,
                   FAKE_QUEUE_FAILS="1" if queue_fails else "", GH_TOKEN="x",
                   REPO="ritmelli/ritmelli", PR="7" if event == "pull_request" else "", HEAD="c" * 40, RUN_ID="1",
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

    code, out, summary, calls = run_summary(bash, block, "push", on_push, queue_url=QUEUE_URL)
    check(code == 0 and "a fila testou" in summary and QUEUE_URL in summary
          and not any(c.startswith("gh pr comment") for c in calls),
          f"on the push, the four skipped jobs pass when a queue run passed on the commit (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "push", on_push, queue_url="")
    check(code != 0 and "nenhuma execução aprovada da fila apareceu" in summary and "sem a fila" not in summary,
          f"on the push, with no passed queue run on the commit, the check fails (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "push", on_push, queue_fails=True)
    check(code != 0 and "a consulta das execuções da fila neste commit falhou" in summary
          and "nenhuma execução aprovada" not in summary,
          f"on the push, a failed query says so, and not that no queue run passed (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "push", ["skipped"] * 5, queue_url=QUEUE_URL)
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


def package(line):
    name = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
    return re.sub(r"[-_.]+", "-", name.group(1)).lower() if name else None


def test_unpinned():
    pinned = {package(line) for line in TRAVAS.read_text(encoding="utf-8").splitlines()
              if "==" in line and not line.lstrip().startswith("#")}
    unpinned = set()
    for req in REQUIREMENTS:
        for line in req.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if not line or line.startswith("-") or "==" in line.split(";")[0]:
                continue
            if (name := package(line)) and name not in pinned:
                unpinned.add(name)
    check(unpinned == KNOWN_UNPINNED,
          f"the libraries the CI installs without a version in instalador/travas.txt are the known ones of "
          f"{KNOWN_UNPINNED_ISSUE} (now {sorted(unpinned)}; a new one gets a pin, one that got a pin leaves the list)")


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
    test_without_destination()
    test_summary_block(all_jobs)
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
