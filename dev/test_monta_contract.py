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
EXPRESSION = re.compile(r"\$\{\{.*?\}\}")
INPUTS = ("notas", "notas_en")
REQUIRED_JOBS = ("testa", "testa-atualizador", "testa-migracao", "testa-parcial")
SETUP, EXE = f"Ritmelli-{MARK}", f"ritmelli-exe-{MARK}"
NOTES = {"NOTAS": ("${{ inputs.notas }}", "--notas"), "NOTAS_EN": ("${{ inputs.notas_en }}", "--notas-en")}
OTHER_VERSION = re.compile(r"Ritmelli-(?:[0-9]|<version>|\$\{\{.*?\}\})(?:[0-9.]|<version>|\$\{\{.*?\}\})*")

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def display(job_id, job):
    return str(job.get("name") or job_id)


def inner(expression):
    text = str(expression).strip()
    return " ".join(text[3:-2].split()) if EXPRESSION.fullmatch(text) else None


def switched_off(condition):
    return condition is False or re.fullmatch(r"(\$\{\{)?\s*false\s*(\}\})?", str(condition).strip(), re.I) is not None


def mark(name, versions):
    return EXPRESSION.sub(lambda m: MARK if inner(m.group(0)) in versions else m.group(0), str(name))


def uploads(jobs):
    out = []
    for job in jobs.values():
        if switched_off(job.get("if")):
            continue
        needs = job.get("needs") or []
        versions = {f"needs.{n}.outputs.versao" for n in ([needs] if isinstance(needs, str) else needs)
                    if "versao" in ((jobs.get(n) or {}).get("outputs") or {})}
        if "versao" in (job.get("outputs") or {}):
            versions |= {inner(job["outputs"]["versao"])} - {None}
        for s in job_steps(job):
            if str(s.get("uses", "")).startswith("actions/upload-artifact@") and not switched_off(s.get("if")):
                w = s.get("with") or {}
                out.append((mark(w.get("name", ""), versions), w, "if" in job or "if" in s))
    return out


def normal_path(path):
    return str(path or "").strip().replace("\\", "/").rstrip("/")


def step_by_id(job, step_id):
    found = [s for s in job_steps(job) if s.get("id") == step_id and not switched_off(s.get("if"))]
    return found[0] if len(found) == 1 else None


def manifest_step(job):
    found = [s for s in job_steps(job)
             if "instalador/atualizacao/publica.py" in code(s.get("run", "")).replace("\\", "/")]
    return found[0] if len(found) == 1 else None


def writes_versao(run):
    return any(re.search(r"\$\{?env:GITHUB_OUTPUT\}?", c, re.I) and '"versao=$' in c for c in code(run).splitlines())


def code(run):
    return "\n".join(line.split("#", 1)[0] for line in str(run).splitlines())


def literal(value):
    return value[1:-1] if re.fullmatch(r"'[^']*'|\"[^\"$`]*\"", value) else None


def output_folder(run):
    value = re.findall(r"""['"]--saida['"],\s*('[^']*'|"[^"]*"|\$\w+)\s*[,)]""", code(run))
    if len(value) != 1 or not value[0].startswith("$"):
        return literal(value[0]) if len(value) == 1 else None
    assigned = re.findall(rf"\{value[0]}\b\s*([-+*/]?=)(?!=)\s*(.*?)\s*$", code(run), re.M | re.I)
    return literal(assigned[0][1]) if len(assigned) == 1 and assigned[0][0] == "=" else None


def one_literal_file(path, filename):
    path = str(path or "").strip()
    return "\n" not in path and not any(c in path for c in "*?[!") and Path(path).name == filename


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
    elif "if" in congela:
        problems.append("the congela step runs only under an if:, so the versao may be empty")
    elif not writes_versao(congela.get("run", "")):
        problems.append("the congela step does not write versao= to its GITHUB_OUTPUT")
    if inner((monta.get("outputs") or {}).get("versao", "")) != inner(VERSION):
        problems.append(f"the versao output of the monta job is not {VERSION}")
    problems += [f"the monta job has no {name} output, which the jobs the pipeline requires read"
                 for name in ("anterior", "parcial") if not str((monta.get("outputs") or {}).get(name) or "").strip()]
    run_uploads = uploads(jobs)
    found = {name: [w for n, w, _ in run_uploads if n == name] for name in (SETUP, EXE)}
    problems += [f"the run uploads {len(w)} artifacts named {n}, not 1" for n, w in found.items() if len(w) != 1]
    problems += [f"the {n} artifact is uploaded only under an if:" for n, _, c in run_uploads if n in found and c]
    fixed = [n for n, _, _ in run_uploads if n != SETUP and OTHER_VERSION.fullmatch(n)]
    if fixed:
        problems.append(f"the run uploads {fixed}, which the pipeline would take for the version of the build")
    if len(found[EXE]) == 1 and not one_literal_file(found[EXE][0].get("path"), "ritmelli.exe"):
        problems.append(f"the {EXE} artifact is not the ritmelli.exe alone ({found[EXE][0].get('path')!r})")
    manifest = manifest_step(monta)
    if manifest is None or switched_off(manifest.get("if")):
        problems.append("the monta job has no one step that runs publica.py")
    elif "if" in manifest:
        problems.append("the step that runs publica.py runs only under an if:, so the manifest may be missing")
    else:
        run = str(manifest.get("run", ""))
        saida = output_folder(run)
        if saida is None:
            problems.append("the step that runs publica.py has no one literal --saida")
        elif len(found[SETUP]) == 1 and normal_path(found[SETUP][0].get("path")) != normal_path(saida):
            problems.append(f"the {SETUP} artifact is {found[SETUP][0].get('path')!r}, not the folder publica.py "
                            f"writes the manifest to ({saida})")
        for name, (value, option) in NOTES.items():
            if inner((manifest.get("env") or {}).get(name, "")) != inner(value):
                problems.append(f"the step that runs publica.py does not get {name} from {value}")
            if not re.search(rf"""@\(['"]{name}['"], ['"][a-z_]+['"], ['"]{option}['"]\)""", code(run)):
                problems.append(f"the step that runs publica.py does not pass {name} as {option}")
    return problems


def comment_notes_loop(run):
    lines, out, depth = str(run).splitlines(), [], None
    for line in lines:
        if depth is None and line.lstrip().startswith("foreach") and "NOTAS_EN" in line:
            depth = 0
        if depth is not None:
            depth += line.count("{") - line.count("}")
            out.append("# " + line)
            if depth <= 0:
                depth = None
                continue
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def shown(doc, name):
    return next(j for k, j in doc["jobs"].items() if display(k, j) == name or display(k, j).startswith(name + " ("))


def mutant(doc, change):
    doc = copy.deepcopy(doc)
    change(doc)
    return doc


def upload(doc, name):
    versions = {inner(VERSION)}
    return next(s for s in doc["jobs"]["monta"]["steps"]
                if mark((s.get("with") or {}).get("name", ""), versions) == mark(name, versions))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    doc = load(MONTA)
    real = contract_problems(doc)
    check(real == [], f"monta.yml has every name the publishing pipeline reads ({real})")
    if failures:
        print("1 failed (the mutants need the real names)")
        return 1
    exe, setup = f"ritmelli-exe-{VERSION}", f"Ritmelli-{VERSION}"
    spaces = mutant(doc, lambda d: upload(d, setup)["with"].update(name="Ritmelli-${{steps.congela.outputs.versao}}"))
    check(contract_problems(spaces) == [], "the version expression written without spaces keeps the contract")
    renamed_step = mutant(doc, lambda d: step_by_id(d["jobs"]["monta"], "congela").update(name="Freeze the app"))
    check(contract_problems(renamed_step) == [], "a congela step renamed (same id) keeps the contract")
    path = str(upload(doc, setup)["with"]["path"])
    slash = mutant(doc, lambda d: upload(d, setup)["with"].update(path=path[:-1] if path.endswith("/") else path + "/"))
    check(contract_problems(slash) == [], "the Ritmelli artifact path with its final slash toggled keeps the contract")

    def edit_run(d, change):
        step = manifest_step(d["jobs"]["monta"])
        step.update(run=change(step["run"]))

    def assign_folder(d, value):
        edit_run(d, lambda run: re.sub(r"^(\s*\$saida\s*=\s*)('[^']*'|\"[^\"]*\")", lambda m: m.group(1) + value, run,
                                       count=1, flags=re.M))

    def move_folder(d):
        assign_folder(d, "'instalador\\out'")

    moved = mutant(doc, lambda d: (upload(d, setup)["with"].update(path="instalador/out/"), move_folder(d)))
    check(output_folder(manifest_step(moved["jobs"]["monta"])["run"]) == "instalador\\out"
          and contract_problems(moved) == [],
          "the --saida of publica.py and the Ritmelli artifact path moved together keep the contract")
    quoted = mutant(doc, lambda d: assign_folder(d, '"instalador\\saida"'))
    check('"instalador\\saida"' in manifest_step(quoted["jobs"]["monta"])["run"] and contract_problems(quoted) == [],
          "the folder of --saida in double quotes keeps the contract")
    option = mutant(doc, lambda d: edit_run(d, lambda run: run.replace("'--saida', $saida", '"--saida", $saida')))
    check('"--saida", $saida' in manifest_step(option["jobs"]["monta"])["run"] and contract_problems(option) == [],
          "the --saida option in double quotes keeps the contract")
    script = "instalador\\atualizacao\\publica.py"
    forward = mutant(doc, lambda d: edit_run(d, lambda run: run.replace(script, "instalador/atualizacao/publica.py")))
    check(script in manifest_step(doc["jobs"]["monta"])["run"] and contract_problems(forward) == [],
          "the publica.py call written with forward slashes keeps the contract")
    tuples = mutant(doc, lambda d: edit_run(d, lambda run: run.replace(
        "@('NOTAS', 'notas', '--notas')", '@("NOTAS", "notas", "--notas")')))
    check('@("NOTAS", "notas", "--notas")' in manifest_step(tuples["jobs"]["monta"])["run"]
          and contract_problems(tuples) == [], "the notes tuple in double quotes keeps the contract")
    helper = mutant(doc, lambda d: d["jobs"]["monta"]["steps"].append(
        {"uses": upload(d, setup)["uses"], "with": {"name": "Ritmelli-.1", "path": "x"}}))
    check(contract_problems(helper) == [], "an artifact named Ritmelli-.1, which the pipeline never takes for the "
                                           "version, keeps the contract")
    other_dir = mutant(doc, lambda d: upload(d, exe)["with"].update(path="dist/app/ritmelli.exe"))
    check(contract_problems(other_dir) == [], "the ritmelli.exe in another folder keeps the contract")
    dotted = mutant(doc, lambda d: upload(d, exe)["with"].update(path="./dist/ritmelli/ritmelli.exe"))
    check(contract_problems(dotted) == [], "the ritmelli.exe path written as ./dist/ritmelli/ritmelli.exe keeps the "
                                           "contract")
    written = "-Path $env:GITHUB_OUTPUT -Value \"versao=$v\""
    reordered = "-Value \"versao=$v\" -Path $env:GITHUB_OUTPUT"
    swapped = mutant(doc, lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
        run=step_by_id(d["jobs"]["monta"], "congela")["run"].replace(written, reordered)))
    check(written in step_by_id(doc["jobs"]["monta"], "congela")["run"] and contract_problems(swapped) == [],
          "the Add-Content of versao with its parameters swapped keeps the contract")
    packed = mutant(doc, lambda d: manifest_step(d["jobs"]["monta"])["env"].update(NOTAS="${{inputs.notas}}"))
    check(contract_problems(packed) == [], "the NOTAS expression written without spaces keeps the contract")
    mutants = {
        "the trigger": lambda d: d.update(on={"push": None}),
        "the notas input": lambda d: d["on"]["workflow_dispatch"]["inputs"].pop("notas"),
        "the notas_en input": lambda d: d["on"]["workflow_dispatch"]["inputs"].pop("notas_en"),
        "the congela step": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(id="freeze"),
        "the congela step switched off": lambda d: step_by_id(d["jobs"]["monta"], "congela").update({"if": "false"}),
        "the versao line of congela commented out": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
            run=step_by_id(d["jobs"]["monta"], "congela")["run"].replace(written, "# " + written)),
        "the versao output written as text": lambda d: d["jobs"]["monta"]["outputs"].update(
            versao="steps.congela.outputs.versao"),
        "the NOTAS of the manifest written as text": lambda d: manifest_step(d["jobs"]["monta"])["env"].update(
            NOTAS="inputs.notas"),
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
        "a Ritmelli artifact with a literal version": lambda d: d["jobs"]["monta"]["steps"].append(
            {"uses": upload(d, setup)["uses"], "with": {"name": "Ritmelli-0.0.0", "path": "x"}}),
        "the step that runs publica.py switched off": lambda d: manifest_step(d["jobs"]["monta"]).update(
            {"if": "false"}),
        "the ritmelli.exe path with a wildcard": lambda d: upload(d, exe)["with"].update(path="dist/*/ritmelli.exe"),
        "the ritmelli.exe path with two files": lambda d: upload(d, exe)["with"].update(
            path="dist/ritmelli/ritmelli.exe\ndist/ritmelli/ritmelli2.exe"),
        "the --saida of publica.py alone": move_folder,
        "the --saida of publica.py commented out": lambda d: edit_run(d, lambda run: run.replace(
            ", '--saida', $saida)", ") # '--saida', $saida")),
        "the folder of --saida joined again": lambda d: edit_run(d, lambda run: re.sub(
            r"^(\s*)(\$saida\s*=.*)$", r"\1\2\n\1$saida = Join-Path $saida 'x'", run, count=1, flags=re.M)),
        "the folder of --saida assigned again in other case": lambda d: edit_run(d, lambda run: re.sub(
            r"^(\s*)(\$saida\s*=.*)$", r"\1\2\n\1$Saida = 'instalador_out'", run, count=1, flags=re.M)),
        "a Ritmelli artifact named by a format expression": lambda d: d["jobs"]["monta"]["steps"].append(
            {"uses": upload(d, setup)["uses"],
             "with": {"name": "Ritmelli-${{ format('{0}', github.run_number) }}", "path": "x"}}),
        "a Ritmelli artifact named by the version and a suffix": lambda d: d["jobs"]["monta"]["steps"].append(
            {"uses": upload(d, setup)["uses"], "with": {"name": setup + ".1", "path": "x"}}),
        "the notes loop commented out": lambda d: edit_run(d, comment_notes_loop),
        "the publica.py call commented out": lambda d: edit_run(d, lambda run: re.sub(
            r"^(\s*)(&.*publica\.py.*)$", r"\1# \2", run, count=1, flags=re.M)),
        "the step that runs publica.py under a condition": lambda d: manifest_step(d["jobs"]["monta"]).update(
            {"if": "env.ASSINA == 'true'"}),
        "the congela step under a condition": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
            {"if": "github.event_name == 'push'"}),
        "a Ritmelli artifact named by another expression": lambda d: d["jobs"]["monta"]["steps"].append(
            {"uses": upload(d, setup)["uses"], "with": {"name": "Ritmelli-${{ github.run_number }}", "path": "x"}}),
        "the --saida of publica.py with a subfolder": lambda d: edit_run(d, lambda run: run.replace(
            "'--saida', $saida)", "'--saida', $saida + '\\sub')")),
        "the folder of --saida assigned twice": lambda d: edit_run(d, lambda run: re.sub(
            r"^(\s*)(\$saida\s*=.*)$", r"\1\2\n\1$saida += '_other'", run, count=1, flags=re.M)),
        "the ritmelli-exe upload under a condition": lambda d: upload(d, exe).update(
            {"if": "github.event_name == 'push'"}),
        "the --saida of publica.py": lambda d: manifest_step(d["jobs"]["monta"]).update(
            run=manifest_step(d["jobs"]["monta"])["run"].replace("'--saida', $saida", "'--out', $saida")),
        "a second Ritmelli artifact in another job": lambda d: shown(d, "testa")["steps"].append(
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
        mutants[f"the shown name of the job {job_id}"] = (lambda j: lambda d: shown(d, j).update(
            name=f"{j}-renamed"))(job_id)
    mutants["the name of the testa-migracao job"] = lambda d: shown(d, "testa-migracao").update(
        name="migracao (${{ matrix.scenario }})")
    packed_folder = mutant(doc, lambda d: edit_run(d, lambda run: run.replace("$saida = '", "$saida='")))
    check("$saida='" in manifest_step(packed_folder["jobs"]["monta"])["run"]
          and contract_problems(packed_folder) == [],
          "the folder of --saida assigned without spaces keeps the contract")
    renamed_job = mutant(doc, lambda d: d["jobs"].update(smoke=dict(d["jobs"].pop("testa"), name="testa")))
    check(contract_problems(renamed_job) == [], "the testa job with another id and the same shown name keeps the "
                                                "contract")
    item = mutant(doc, lambda d: edit_run(d, lambda run: re.sub(r"\$n\b", "$item", run)))
    check("$item" in manifest_step(item["jobs"]["monta"])["run"] and contract_problems(item) == []
          and comment_notes_loop(manifest_step(item["jobs"]["monta"])["run"]).count("# foreach") == 1,
          "the notes loop with another variable keeps the contract and its mutant still comments it out")
    for base, label in ((doc, ""), (spaces, " (version expression without spaces)"),
                        (packed_folder, " (folder of --saida assigned without spaces)"),
                        (renamed_job, " (testa job with another id)")):
        for name, change in mutants.items():
            check(contract_problems(mutant(base, change)) != [], f"the check catches {name} changed{label}")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
