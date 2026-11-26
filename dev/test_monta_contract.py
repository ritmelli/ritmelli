"""The names of .github/workflows/monta.yml that the publishing pipeline of ritmelli-server reads, read as YAML: the
workflow_dispatch trigger with the notas and notas_en inputs, the jobs it requires to have passed (by the name the jobs
API shows), the congela step whose versao names the artifacts, and the two artifacts it downloads. Every check also
runs on a mutant of the real file and has to catch it. Standard library only.

    python dev/test_monta_contract.py
"""
import copy
import re
import sys
from pathlib import Path

from workflow_yaml import job_steps, load

ROOT = Path(__file__).resolve().parent.parent
MONTA = ROOT / ".github" / "workflows" / "monta.yml"
VERSION = "${{ steps.congela.outputs.versao }}"
MARK = "<version>"
EXPRESSION = re.compile(r"\$\{\{[^}]*\}\}")
INPUTS = ("notas", "notas_en")
REQUIRED_JOBS = ("testa", "testa-atualizador", "testa-migracao", "testa-parcial")
ARTIFACTS = {f"Ritmelli-{MARK}": "instalador/saida", f"ritmelli-exe-{MARK}": "dist/ritmelli/ritmelli.exe"}
NOTES = {"NOTAS": ("${{ inputs.notas }}", "--notas"), "NOTAS_EN": ("${{ inputs.notas_en }}", "--notas-en")}
VERSION_OUTPUT = re.compile(r"\$env:GITHUB_OUTPUT\s+-Value\s+\"versao=\$")

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def display(job_id, job):
    return str(job.get("name") or job_id)


def inner(expression):
    return " ".join(str(expression).strip().removeprefix("${{").removesuffix("}}").split())


def switched_off(condition):
    return condition is False or re.fullmatch(r"(\$\{\{)?\s*false\s*(\}\})?", str(condition).strip(), re.I) is not None


def uploads(jobs):
    out = []
    for job in jobs.values():
        if switched_off(job.get("if")):
            continue
        needs = job.get("needs") or []
        versions = {f"needs.{n}.outputs.versao" for n in ([needs] if isinstance(needs, str) else needs)
                    if "versao" in ((jobs.get(n) or {}).get("outputs") or {})}
        if "versao" in (job.get("outputs") or {}):
            versions.add(inner(job["outputs"]["versao"]))
        for s in job_steps(job):
            if str(s.get("uses", "")).startswith("actions/upload-artifact@") and not switched_off(s.get("if")):
                w = s.get("with") or {}
                out.append((EXPRESSION.sub(lambda m: MARK if inner(m.group(0)) in versions else m.group(0),
                                           str(w.get("name", ""))), w))
    return out


def normal_path(path):
    return str(path or "").strip().replace("\\", "/").rstrip("/")


def step_by_id(job, step_id):
    found = [s for s in job_steps(job) if s.get("id") == step_id]
    return found[0] if len(found) == 1 else None


def manifest_step(job):
    found = [s for s in job_steps(job) if "instalador\\atualizacao\\publica.py" in str(s.get("run", ""))]
    return found[0] if len(found) == 1 else None


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
    congela = step_by_id(monta, "congela")
    if congela is None:
        problems.append("the monta job has no congela step")
    elif not any(VERSION_OUTPUT.search(line) for line in str(congela.get("run", "")).splitlines()):
        problems.append("the congela step does not write versao= to its GITHUB_OUTPUT")
    if inner((monta.get("outputs") or {}).get("versao", "")) != inner(VERSION):
        problems.append(f"the versao output of the monta job is not {VERSION}")
    problems += [f"the monta job has no {name} output, which the jobs the pipeline requires read"
                 for name in ("anterior", "parcial") if not str((monta.get("outputs") or {}).get(name) or "").strip()]
    run_uploads = uploads(jobs)
    for name, path in ARTIFACTS.items():
        found = [w for n, w in run_uploads if n == name]
        if len(found) != 1:
            problems.append(f"the run uploads {len(found)} artifacts named {name}, not 1")
        elif normal_path(found[0].get("path")) != normal_path(path):
            problems.append(f"the {name} artifact is {found[0].get('path')!r}, not {path}")
    manifest = manifest_step(monta)
    if manifest is None:
        problems.append("the monta job has no one step that runs publica.py")
    else:
        run = str(manifest.get("run", ""))
        for name, (value, option) in NOTES.items():
            if (manifest.get("env") or {}).get(name) != value:
                problems.append(f"the step that runs publica.py does not get {name} from {value}")
            if not re.search(rf"@\('{name}', '[a-z_]+', '{option}'\)", run):
                problems.append(f"the step that runs publica.py does not pass {name} as {option}")
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
    if failures:
        print("1 failed (the mutants need the real names)")
        return 1
    exe, setup = f"ritmelli-exe-{VERSION}", f"Ritmelli-{VERSION}"
    spaces = mutant(doc, lambda d: upload(d, setup)["with"].update(name="Ritmelli-${{steps.congela.outputs.versao}}"))
    check(contract_problems(spaces) == [], "the version expression written without spaces keeps the contract")
    renamed_step = mutant(doc, lambda d: step_by_id(d["jobs"]["monta"], "congela").update(name="Freeze the app"))
    check(contract_problems(renamed_step) == [], "a congela step renamed (same id) keeps the contract")
    slash = mutant(doc, lambda d: upload(d, setup)["with"].update(path="instalador/saida"))
    check(contract_problems(slash) == [], "the Ritmelli artifact path without its final slash keeps the contract")
    mutants = {
        "the trigger": lambda d: d.update(on={"push": None}),
        "the notas input": lambda d: d["on"]["workflow_dispatch"]["inputs"].pop("notas"),
        "the notas_en input": lambda d: d["on"]["workflow_dispatch"]["inputs"].pop("notas_en"),
        "the congela step": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(id="freeze"),
        "the versao the congela step writes": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
            run=step_by_id(d["jobs"]["monta"], "congela")["run"].replace('"versao=$v"', '"version=$v"')),
        "the Ritmelli upload switched off": lambda d: upload(d, setup).update({"if": "${{ false }}"}),
        "the anterior output": lambda d: d["jobs"]["monta"]["outputs"].pop("anterior"),
        "the parcial output": lambda d: d["jobs"]["monta"]["outputs"].pop("parcial"),
        "the versao output": lambda d: d["jobs"]["monta"]["outputs"].update(
            versao="${{ steps.freeze.outputs.versao }}"),
        "the Ritmelli artifact name": lambda d: upload(d, setup)["with"].update(name="Ritmelli-build"),
        "the Ritmelli artifact path": lambda d: upload(d, setup)["with"].update(path="instalador/saida/*.exe"),
        "the ritmelli-exe artifact name": lambda d: upload(d, exe)["with"].update(name="ritmelli-app"),
        "the ritmelli-exe artifact path": lambda d: upload(d, exe)["with"].update(path="dist/ritmelli/"),
        "a second Ritmelli artifact": lambda d: d["jobs"]["monta"]["steps"].append(copy.deepcopy(upload(d, setup))),
        "a second Ritmelli artifact in another job": lambda d: d["jobs"]["testa"]["steps"].append(
            {"uses": upload(d, setup)["uses"], "with": {"name": "Ritmelli-${{ needs.monta.outputs.versao }}",
                                                         "path": "saida/"}}),
        "the notas of the manifest": lambda d: manifest_step(d["jobs"]["monta"])["env"].pop("NOTAS"),
        "the notas_en of the manifest": lambda d: manifest_step(d["jobs"]["monta"])["env"].update(
            NOTAS_EN="${{ inputs.notas }}"),
        "the NOTAS_EN the manifest reads": lambda d: manifest_step(d["jobs"]["monta"]).update(
            run=manifest_step(d["jobs"]["monta"])["run"].replace("@('NOTAS_EN',", "@('NOTES_EN',")),
        "the option of the notas": lambda d: manifest_step(d["jobs"]["monta"]).update(
            run=manifest_step(d["jobs"]["monta"])["run"].replace("'--notas')", "'--notes')")),
    }
    for job_id in ("testa", "testa-atualizador", "testa-parcial"):
        mutants[f"the shown name of the job {job_id}"] = (lambda j: lambda d: d["jobs"][j].update(
            name=f"{j}-renamed"))(job_id)
    mutants["the name of the testa-migracao job"] = lambda d: d["jobs"]["testa-migracao"].update(
        name="migracao (${{ matrix.scenario }})")
    for name, change in mutants.items():
        check(contract_problems(mutant(doc, change)) != [], f"the check catches {name} changed")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
