r"""Checks the parts of the .github/workflows/testa.yml that no PR run exercises, without GitHub:

- the run block of the "Testa o PR" job, in bash as the job runs it, with a fake gh and a fake sleep first on the PATH:
  a summary comment that fails with a 502 is tried again, and after the last try the check fails with that reason; on
  the push to main the jobs the queue already ran are skipped, and they pass only when a queue run passed on the same
  commit; a skipped job outside the push and a cancelled job fail;
- the jobs that skip on the push (all but the Etiquetas and the Compara) and the needs of the "Testa o PR";
- the cache keys: the compara capture hashes the CAPTURA files of the dev/testa_tudo.py, and the libraries are
  installed with the instalador/travas.txt as constraints, which is in their key;
- the "test without destination" lock of the dev/testa_tudo.py, on a folder of its own: it sees the dev/testa_* and the
  dev/test_* tests, and only those.

Standard library only, plus the bash of Git for Windows (or the bash of the PATH outside Windows) for the run block.
Without that bash, on a PC, the run block is skipped with a "ficou de fora" line (which the COMPLETO of the
dev/testa_tudo.py counts as a failure); on GitHub Actions it fails.

    python dev/test_ci_workflow.py

Exits 1 if anything fails."""
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
sys.path.insert(0, str(ROOT / "dev"))
import testa_tudo  # noqa: E402

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def jobs(text):
    """Each job of the workflow: its id and the lines of its block."""
    out, current = {}, None
    in_jobs = False
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
    """The run: | block of the step with that name, dedented."""
    start = next(i for i, line in enumerate(lines) if re.fullmatch(rf"\s*- name: {re.escape(name)}", line))
    run = next(i for i in range(start + 1, len(lines)) if re.fullmatch(r"\s*run: \|", lines[i]))
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body).rstrip() + "\n"


def find_bash():
    """The bash of Git for Windows (never the one of System32, which is WSL), or the bash of the PATH elsewhere. The
    git.exe of the PATH can be in Git/cmd, Git/bin or Git/mingw64/bin: the bash is looked for above it."""
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
  n=$(($(cat "$FAKE_COUNT" 2>/dev/null || echo 0) + 1))
  echo "$n" > "$FAKE_COUNT"
  if [ "$n" -le "${FAKE_COMMENT_FAILS:-0}" ]; then echo "non-200 OK status code: 502 Bad Gateway" >&2; exit 1; fi
  exit 0
fi
echo "fake gh: unexpected call: $*" >&2
exit 2
"""
FAKE_SLEEP = '#!/bin/bash\necho "sleep $*" >> "$FAKE_LOG"\n'


def run_summary(bash, block, event, states, comment_fails=0, queue_url="", queue_fails=False, dono="success"):
    """Runs the block of the "Testa o PR" with the states of the five jobs. Returns (exit code, stdout+stderr, step
    summary, the fake calls)."""
    with tempfile.TemporaryDirectory(prefix="ritmelli-ci-") as tmp:
        tmp = Path(tmp)
        fake = tmp / "bin"
        fake.mkdir()
        (fake / "gh").write_text(FAKE_GH, encoding="utf-8", newline="\n")
        (fake / "sleep").write_text(FAKE_SLEEP, encoding="utf-8", newline="\n")
        for f in fake.iterdir():
            f.chmod(0o755)
        # the PATH inside bash: Git for Windows puts its /usr/bin (with the real sleep) before the PATH it gets
        (tmp / "run.sh").write_text('PATH="$PWD/bin:$PATH"\n' + block, encoding="utf-8", newline="\n")
        summary, log = tmp / "summary.md", tmp / "log.txt"
        summary.touch()
        log.touch()
        names = ("TESTES", "BANCA", "MICROFONE", "TELA", "COMPARA")
        env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ.get("PATH", ""), GITHUB_EVENT_NAME=event,
                   GITHUB_STEP_SUMMARY=str(summary), FAKE_LOG=str(log), FAKE_COUNT=str(tmp / "count"),
                   FAKE_COMMENT_FAILS=str(comment_fails), FAKE_QUEUE_URL=queue_url,
                   FAKE_QUEUE_FAILS="1" if queue_fails else "", GH_TOKEN="x",
                   REPO="ritmelli/ritmelli", PR="7" if event == "pull_request" else "", HEAD="c" * 40, RUN_ID="1",
                   ATTEMPT="1", EXECUCAO="https://example.invalid/run", S_DONO=dono, DONO="",
                   DO_REPO="true" if event == "pull_request" else "false", LINHAS="", MUDARAM="0",
                   **{f"S_{n}": s for n, s in zip(names, states)}, **{f"R_{n}": f"resumo {n}" for n in names})
        p = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "run.sh"], cwd=tmp, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        return (p.returncode, p.stdout + p.stderr, summary.read_text(encoding="utf-8"),
                log.read_text(encoding="utf-8").splitlines())


def test_summary_block(all_jobs):
    bash = find_bash()
    if not bash and not os.environ.get("GITHUB_ACTIONS"):
        # the marker line of dev/testa_tudo.py (PULOU): fine in the --so-stdlib, a failure in the COMPLETO
        print("--   o bloco do Testa o PR ficou de fora: no bash of Git for Windows here", flush=True)
        return
    check(bool(bash), "a bash to run the block (Git for Windows, or bash on the PATH)")
    if not bash:
        return
    block = step_run(all_jobs["testa-o-pr"], "Resumo e resultado")
    ok5 = ["success"] * 5
    on_push = ["skipped"] * 4 + ["success"]

    code, out, summary, calls = run_summary(bash, block, "pull_request", ok5, comment_fails=2)
    comments = [c for c in calls if c.startswith("gh pr comment")]
    sleeps = [c for c in calls if c.startswith("sleep")]
    check(code == 0 and len(comments) == 3 and "tudo passou" in summary,
          f"a comment that fails twice with a 502 goes out on the third try and the check passes "
          f"(exit {code}, {len(comments)} tries)")
    check(sleeps == ["sleep 5", "sleep 20"], f"the waits between the tries went to the fake sleep ({sleeps})")
    check("| Banca |" in summary, "the summary table has the Banca column")

    code, out, summary, calls = run_summary(bash, block, "pull_request", ok5, comment_fails=9)
    comments = [c for c in calls if c.startswith("gh pr comment")]
    check(code != 0 and len(comments) == 3 and "GitHub did not confirm the summary comment" in out
          and "não confirmou o comentário do resumo no PR em 3 tentativas" in summary,
          f"a comment that never goes out fails the check after 3 tries, saying so (exit {code}, {len(comments)} tries)")

    code, out, summary, calls = run_summary(bash, block, "push", on_push, queue_url="https://example.invalid/queue")
    check(code == 0 and "a fila testou" in summary and "https://example.invalid/queue" in summary
          and not any(c.startswith("gh pr comment") for c in calls),
          f"on the push, the skipped jobs pass when a queue run passed on the commit, with no PR comment (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "push", on_push, queue_url="")
    queries = [c for c in calls if "event=merge_group" in c]
    check(code != 0 and "nenhuma execução aprovada da fila apareceu" in summary and "sem a fila" not in summary
          and len(queries) == 4,
          f"on the push, with no queue run passed on the commit, the check fails after asking 4 times "
          f"(exit {code}, {len(queries)} queries)")

    code, out, summary, calls = run_summary(bash, block, "push", on_push, queue_url="", queue_fails=True)
    check(code != 0 and "a consulta das execuções da fila neste commit falhou" in summary
          and "nenhuma execução aprovada" not in summary,
          f"on the push, a query that fails says so, and does not say the commit came without the queue (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "push", ["skipped"] * 5, queue_url="https://example.invalid/q")
    check(code != 0, f"on the push, a skipped Compara (no capture) fails the check even with the queue run (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "pull_request", ["skipped"] + ["success"] * 4)
    check(code != 0 and not any("event=merge_group" in c for c in calls),
          f"on a PR, a skipped job fails the check, and the queue is not asked (exit {code})")

    code, out, summary, calls = run_summary(bash, block, "merge_group", ok5, dono="failure")
    check(code != 0, f"a failed needs-owner step fails the check, as before (exit {code})")

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
    captura = ", ".join(f"'{f}'" for f in testa_tudo.CAPTURA)
    keys = re.findall(r"key: compara-.*hashFiles\(([^)]*)\)", text)
    check(len(keys) == 2 and all(k == captura for k in keys),
          f"both compara cache keys hash the CAPTURA files of dev/testa_tudo.py ({len(keys)} keys)")
    action = ACTION.read_text(encoding="utf-8")
    check(re.search(r"key: libs-.*hashFiles\([^)]*'instalador/travas.txt'", action) is not None,
          "the libraries cache key hashes the instalador/travas.txt")
    check(re.search(r"pip install .*-r \$env:REQUIREMENTS -c instalador/travas.txt", action) is not None,
          "the libraries are installed with the instalador/travas.txt as constraints")


def test_without_destination():
    with tempfile.TemporaryDirectory(prefix="ritmelli-dev-") as tmp:
        dev = Path(tmp)
        (dev / "test_lost.py").write_text('"""A new test in no list."""\n', encoding="utf-8")
        (dev / "testa_perdido.py").write_text('"""An old-style test in no list."""\n', encoding="utf-8")
        (dev / "test_by_hand.py").write_text('# manual: python dev\\test_by_hand.py precisa de um microfone\n"""x"""\n',
                                             encoding="utf-8")
        (dev / "tester.py").write_text('"""A tool, not a test."""\n', encoding="utf-8")
        (dev / "testa_tudo.py").write_text('"""The runner."""\n', encoding="utf-8")
        found = [f for f in testa_tudo.sem_destino(dev=dev) if "runs nowhere" in f]
        flagged = sorted(f.split()[0] for f in found)
        check(flagged == ["dev/test_lost.py", "dev/testa_perdido.py"],
              f"the lock flags the dev/test_* and dev/testa_* tests without destination, and only them ({flagged})")
    check(testa_tudo.sem_destino() == [], "every test of dev/ has a destination, and the testa.yml calls every mode")
    check(not set(testa_tudo.BANCA) & set(testa_tudo.COMPLETO), "the bench is not in the COMPLETO (it would run twice)")
    check(testa_tudo.SERIAL <= set(testa_tudo.COMPLETO + testa_tudo.BANCA), "every SERIAL test is in a list")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    text = WORKFLOW.read_text(encoding="utf-8")
    all_jobs = jobs(text)
    test_shape(all_jobs, text)
    test_without_destination()
    test_summary_block(all_jobs)
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
