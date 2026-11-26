"""The names of .github/workflows/monta.yml that the publishing pipeline of ritmelli-server reads, read as YAML: the
workflow_dispatch trigger with the notas and notas_en inputs, the jobs it requires to have passed (by the name the jobs
API shows), the congela step whose versao names the artifacts, and the two artifacts it downloads. Every check also
runs on a mutant of the real file and has to catch it. Standard library only.

    python dev/test_monta_contract.py
"""
import copy
import sys
from pathlib import Path

from workflow_yaml import find_step, job_steps, load

ROOT = Path(__file__).resolve().parent.parent
MONTA = ROOT / ".github" / "workflows" / "monta.yml"
VERSION = "${{ steps.congela.outputs.versao }}"
INPUTS = ("notas", "notas_en")
REQUIRED_JOBS = ("testa", "testa-atualizador", "testa-migracao", "testa-parcial")
ARTIFACTS = {f"Ritmelli-{VERSION}": "instalador/saida/", f"ritmelli-exe-{VERSION}": "dist/ritmelli/ritmelli.exe"}
NOTES_ENV = {"NOTAS": "${{ inputs.notas }}", "NOTAS_EN": "${{ inputs.notas_en }}"}

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def display(job_id, job):
    return str(job.get("name") or job_id)


def contract_problems(doc):
    problems = []
    dispatch = (doc.get("on") or {}).get("workflow_dispatch") if isinstance(doc.get("on"), dict) else None
    inputs = (dispatch or {}).get("inputs") or {}
    if not isinstance(doc.get("on"), dict) or "workflow_dispatch" not in doc["on"]:
        problems.append("monta.yml does not run by hand (workflow_dispatch)")
    problems += [f"monta.yml has no {name} input" for name in INPUTS if name not in inputs]
    jobs = doc.get("jobs") or {}
    names = [display(k, j) for k, j in jobs.items()]
    for required in REQUIRED_JOBS:
        if not any(n == required or n.startswith(required + " (") for n in names):
            problems.append(f"monta.yml has no job shown as {required}")
    monta = jobs.get("monta") or {}
    if not any(s.get("id") == "congela" for s in job_steps(monta)):
        problems.append("the monta job has no congela step")
    if (monta.get("outputs") or {}).get("versao") != VERSION:
        problems.append(f"the versao output of the monta job is not {VERSION}")
    uploads = [(s.get("with") or {}) for s in job_steps(monta)
               if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    for name, path in ARTIFACTS.items():
        found = [w for w in uploads if w.get("name") == name]
        if len(found) != 1:
            problems.append(f"the monta job uploads {len(found)} artifacts named {name}, not 1")
        elif str(found[0].get("path", "")).strip() != path:
            problems.append(f"the {name} artifact is {found[0].get('path')!r}, not {path}")
    manifest = find_step(monta, "Manifesto") or {}
    problems += [f"the Manifesto step does not get {k} from {v}" for k, v in NOTES_ENV.items()
                 if (manifest.get("env") or {}).get(k) != v]
    return problems


def mutant(doc, change):
    doc = copy.deepcopy(doc)
    change(doc)
    return doc


def upload(doc, name):
    return next(s for s in doc["jobs"]["monta"]["steps"] if (s.get("with") or {}).get("name") == name)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    doc = load(MONTA)
    check(contract_problems(doc) == [], f"monta.yml has every name the publishing pipeline reads "
                                        f"({contract_problems(doc)})")
    exe, setup = f"ritmelli-exe-{VERSION}", f"Ritmelli-{VERSION}"
    mutants = {
        "the trigger": lambda d: d.update(on={"push": None}),
        "the notas input": lambda d: d["on"]["workflow_dispatch"]["inputs"].pop("notas"),
        "the notas_en input": lambda d: d["on"]["workflow_dispatch"]["inputs"].pop("notas_en"),
        "the congela step": lambda d: find_step(d["jobs"]["monta"], "Congela o app").update(id="freeze"),
        "the versao output": lambda d: d["jobs"]["monta"]["outputs"].update(
            versao="${{ steps.freeze.outputs.versao }}"),
        "the Ritmelli artifact name": lambda d: upload(d, setup)["with"].update(name="Ritmelli-build"),
        "the Ritmelli artifact path": lambda d: upload(d, setup)["with"].update(path="instalador/saida/*.exe"),
        "the ritmelli-exe artifact name": lambda d: upload(d, exe)["with"].update(name="ritmelli-app"),
        "the ritmelli-exe artifact path": lambda d: upload(d, exe)["with"].update(path="dist/ritmelli/"),
        "a second Ritmelli artifact": lambda d: d["jobs"]["monta"]["steps"].append(copy.deepcopy(upload(d, setup))),
        "the notas of the manifest": lambda d: find_step(d["jobs"]["monta"], "Manifesto")["env"].pop("NOTAS"),
        "the notas_en of the manifest": lambda d: find_step(d["jobs"]["monta"], "Manifesto")["env"].update(
            NOTAS_EN="${{ inputs.notas }}"),
    }
    for job_id in ("testa", "testa-atualizador", "testa-parcial"):
        mutants[f"the job {job_id}"] = (lambda j: lambda d: d["jobs"].update(
            {f"{j}-renamed": d["jobs"].pop(j)}))(job_id)
    mutants["the name of the testa-migracao job"] = lambda d: d["jobs"]["testa-migracao"].update(
        name="migracao (${{ matrix.scenario }})")
    for name, change in mutants.items():
        check(contract_problems(mutant(doc, change)) != [], f"the check catches {name} changed")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
