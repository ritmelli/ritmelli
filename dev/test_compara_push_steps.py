import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("test_ci_workflow", ROOT / "dev" / "test_ci_workflow.py")
workflow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(workflow)
step_run, check, failures = workflow.step_run, workflow.check, workflow.failures


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


def test_compara_on_push(all_jobs):
    shell = powershell()
    check(bool(shell), "a PowerShell runs the compara steps")
    if not shell:
        return
    lines = all_jobs["compara"]
    areas, key = step_run(lines, "O PR mexe na tela?"), step_run(lines, "Capture key")
    gone = {"BASE": "0" * 40, "COMPARA_BASE": "0" * 40, "ETIQUETAS": "[]"}
    code, out, output = run_step(shell, areas, dict(gone, GITHUB_EVENT_NAME="push"))
    check(code == 0 and "roda=true" in output, f"on the push, the compara runs without the areas of a base (exit {code})")
    code, out, output = run_step(shell, key, dict(gone, GITHUB_EVENT_NAME="push"))
    check(code == 0 and any(re.fullmatch(r"chave=.*-chrome\d+(\.\d+){3}", line) for line in output),
          f"on the push, the capture key comes without resolving the base (exit {code}: {out.strip()[:200]})")
    code, out, output = run_step(shell, key, dict(gone, GITHUB_EVENT_NAME="pull_request"))
    check(code != 0 and "is not a commit here" in out, f"on a PR, a base that is not a commit fails the key (exit {code})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    test_compara_on_push(workflow.jobs(workflow.WORKFLOW.read_text(encoding="utf-8")))
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
