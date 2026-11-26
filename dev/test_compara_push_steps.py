import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import fake_gh
from workflow_yaml import ROOT, find_step, load

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def powershell():
    return shutil.which("pwsh") or shutil.which("powershell")


def run_step(shell, block, env):
    with tempfile.TemporaryDirectory(prefix="ritmelli-ci-") as tmp:
        script, output = Path(tmp) / "step.ps1", Path(tmp) / "github_output"
        script.write_text("$ErrorActionPreference = 'stop'\n" + block, encoding="utf-8-sig")
        output.touch()
        p = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(script)], cwd=ROOT,
                           env=dict(os.environ, GITHUB_OUTPUT=str(output), **env), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        return p.returncode, p.stdout + p.stderr, output.read_text(encoding="utf-8-sig").splitlines()


def test_compara_on_push(jobs):
    shell = powershell()
    check(bool(shell), "a PowerShell runs the compara steps")
    if not shell:
        return
    areas = find_step(jobs["compara"], "O PR mexe na tela?")["run"]
    key = find_step(jobs["compara"], "Capture key")["run"]
    gone = {"BASE": "0" * 40, "COMPARA_BASE": "0" * 40, "ETIQUETAS": "[]"}
    code, out, output = run_step(shell, areas, dict(gone, GITHUB_EVENT_NAME="push"))
    check(code == 0 and "roda=true" in output, f"on the push, the compara runs without the areas of a base (exit {code})")
    code, out, output = run_step(shell, key, dict(gone, GITHUB_EVENT_NAME="push"))
    check(code == 0 and any(re.fullmatch(r"chave=.*-chrome\d+(\.\d+){3}", line) for line in output),
          f"on the push, the capture key comes without resolving the base (exit {code}: {out.strip()[:200]})")
    code, out, output = run_step(shell, key, dict(gone, GITHUB_EVENT_NAME="pull_request"))
    check(code != 0 and "is not a commit here" in out, f"on a PR, a base that is not a commit fails the key (exit {code})")


def test_compara_base_in_the_queue(jobs):
    check(jobs["etiquetas"].get("outputs", {}).get("queue_base") == "${{ steps.le.outputs.queue_base }}"
          and find_step(jobs["etiquetas"], "Etiquetas do PR").get("id") == "le",
          "the etiquetas job exports the queue_base of its Etiquetas do PR step")
    check(jobs["compara"].get("env", {}).get("COMPARA_BASE") == "${{ github.event_name == 'merge_group' && "
          "needs.etiquetas.outputs.queue_base || github.event.pull_request.base.sha || github.event.before }}",
          "in a queue entry the compara compares to the queue_base of the etiquetas job")
    shell = powershell()
    if not (shell and fake_gh.bash()):
        check(False, "a PowerShell and a bash run the queue case")
        return
    parent, event_base = (subprocess.run(["git", "rev-parse", rev], cwd=ROOT, capture_output=True, text=True,
                                         check=True).stdout.strip() for rev in ("HEAD~1", "HEAD"))
    ran = fake_gh.run_step(find_step(jobs["etiquetas"], "Etiquetas do PR")["run"],
                           {"GITHUB_EVENT_NAME": "merge_group", "GH_TOKEN": "x", "REPO": "ritmelli/ritmelli", "PR": "",
                            "GITHUB_REF": f"refs/heads/gh-readonly-queue/main/pr-7-{parent}"}, {"labels": []})
    code, out, output = run_step(shell, find_step(jobs["compara"], "Capture key")["run"],
                                 {"GITHUB_EVENT_NAME": "merge_group", "BASE": event_base,
                                  "COMPARA_BASE": ran.outputs.get("queue_base", "")})
    check(ran.code == 0 and code == 0 and f"base={parent}" in output and f"base={event_base}" not in output,
          f"in a queue entry the capture key takes the commit of the entry's ref, not the event base (exit {code})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    jobs = load(ROOT / ".github" / "workflows" / "testa.yml")["jobs"]
    test_compara_on_push(jobs)
    test_compara_base_in_the_queue(jobs)
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
