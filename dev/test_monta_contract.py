"""The names of .github/workflows/monta.yml that the publishing pipeline of ritmelli-server reads, read as YAML: the
workflow_dispatch trigger with the notas and notas_en inputs, which reach the step that runs publica.py, the jobs it
requires to have passed (by the name the jobs API shows), the congela step whose versao names the artifacts, the
anterior and parcial outputs of the monta job and the if: of the two jobs they gate, and the two artifacts it
downloads. Every check also runs on a mutant of the real file and has to catch it. Standard library only.

    python dev/test_monta_contract.py
"""
import copy
import json
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
GATED_JOBS = {"testa-migracao": "anterior", "testa-parcial": "parcial"}
BUILDS = ({"anterior": True, "parcial": True}, {"anterior": True, "parcial": False})
SETUP, EXE = f"Ritmelli-{MARK}", f"ritmelli-exe-{MARK}"
NOTES = {"NOTAS": ("${{ inputs.notas }}", "--notas"), "NOTAS_EN": ("${{ inputs.notas_en }}", "--notas-en")}
STEP_OUTPUTS = {"anterior": r"steps\.([\w-]+)\.outputs\.([\w-]+)\s*!=\s*''",
                "parcial": r"steps\.([\w-]+)\.outputs\.(parcial)"}
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
    text = str(name).replace(MARK, "<written version>")
    return EXPRESSION.sub(lambda m: MARK if inner(m.group(0)) in versions else m.group(0), text)


def uploads(jobs):
    out = []
    for job_id, job in jobs.items():
        if switched_off(job.get("if")):
            continue
        needs = job.get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        versions = {"needs.monta.outputs.versao"} if "monta" in needs else set()
        if job_id == "monta":
            versions.add(inner(VERSION))
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


def writes_output(run, key):
    path = r"""(?:^|\s)-Path\s+("?)(?:\$env:GITHUB_OUTPUT|\$\{env:GITHUB_OUTPUT\})\1(?=\s|$)"""
    return any(re.match(r"\s*Add-Content\b", c, re.I) and re.search(path, c, re.I) and f'"{key}=$' in c
               for c in code(run).splitlines())


def bare(condition):
    text = str(condition).strip()
    return inner(text) if "${{" in text or "}}" in text else text


def step_output_problem(job, name):
    value = inner((job.get("outputs") or {}).get(name, ""))
    source = re.fullmatch(STEP_OUTPUTS[name], value or "")
    step = source and step_by_id(job, source.group(1))
    if not step or not writes_output(step.get("run", ""), source.group(2)):
        return f"the {name} output of the monta job does not come from a step that writes it to its GITHUB_OUTPUT"
    if "if" in step:
        return f"the step behind the {name} output of the monta job runs only under an if:"
    return None


def code(run):
    return re.sub(r"<#.*?#>|#[^\n]*", lambda m: re.sub(r"[^\n]", " ", m.group(0)), str(run), flags=re.S)


def active(run, found):
    return bool(found) and code(run)[found.start():found.end()] == found.group(0)


def condition_holds(condition, build, needs):
    if condition is None:
        return True
    text = bare(condition) or ""
    if re.fullmatch(r"(always|success)\(\)", text):
        return True
    gate = re.fullmatch(r"needs\.monta\.outputs\.(\w+)\s*==\s*'true'", text)
    return bool(gate) and "monta" in needs and build.get(gate.group(1), False)


def runs(jobs, job_id, build, seen=()):
    job = jobs.get(job_id)
    if job is None or job_id in seen:
        return False
    needs = job.get("needs") or []
    needs = [needs] if isinstance(needs, str) else needs
    return condition_holds(job.get("if"), build, needs) and all(runs(jobs, n, build, seen + (job_id,)) for n in needs)


SAIDA = r"""['"]--saida['"],\s*(?:(['"])([^'"]*)\1|\$(\w+))\s*[,)]"""


def output_folder(run):
    run = str(run)
    found = re.search(SAIDA, run)
    if not active(run, found) or len(re.findall(SAIDA, code(run))) != 1:
        return None
    if found.group(3):
        if len(re.findall(rf"\${found.group(3)}\s*[-+*/]?=(?!=)", run, re.I)) != 1:
            return None
        found = re.search(rf"""^[ \t]*\${found.group(3)}\s*=\s*(['"])([^'"]*)\1[ \t]*$""", run, re.M | re.I)
        if not active(run, found):
            return None
    value = found.group(2)
    return value if value and "$" not in value else None


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
    for required in REQUIRED_JOBS:
        ids = [k for k, j in jobs.items() if display(k, j) == required or display(k, j).startswith(required + " (")]
        builds = [b for b in BUILDS if required != "testa-parcial" or b["parcial"]]
        if not ids or not all(runs(jobs, k, b) for k in ids for b in builds):
            problems.append(f"monta.yml has no job shown as {required} that runs in every build the pipeline expects")
    monta = jobs.get("monta") or {}
    congela = step_by_id(monta, "congela")
    if congela is None:
        problems.append("the monta job has no congela step")
    elif "if" in congela:
        problems.append("the congela step runs only under an if:, so the versao may be empty")
    elif not writes_output(congela.get("run", ""), "versao"):
        problems.append("the congela step does not write versao= to its GITHUB_OUTPUT")
    if inner((monta.get("outputs") or {}).get("versao", "")) != inner(VERSION):
        problems.append(f"the versao output of the monta job is not {VERSION}")
    problems += [p for p in (step_output_problem(monta, name) for name in ("anterior", "parcial")) if p]
    for required, output in GATED_JOBS.items():
        gated = [j for k, j in jobs.items() if display(k, j) == required or display(k, j).startswith(required + " (")]
        for job in gated:
            needs = job.get("needs") or []
            if "monta" not in ([needs] if isinstance(needs, str) else needs):
                problems.append(f"{required} does not need the monta job, so its if: cannot read the monta outputs")
            if not re.fullmatch(rf"needs\.monta\.outputs\.{output}\s*==\s*'true'", bare(job.get("if", "")) or ""):
                problems.append(f"the if: of {required} does not read the {output} output of the monta job")
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
    first = next((s for j in jobs.values() if not switched_off(j.get("if")) for s in job_steps(j)
                  if "publica.py" in str(s.get("run", "")) and not switched_off(s.get("if"))), None)
    if manifest is None or switched_off(manifest.get("if")):
        problems.append("the monta job has no one step that runs publica.py")
    elif first is not manifest:
        problems.append("an earlier step mentions publica.py, and the pipeline reads that step as the one that runs it")
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


def notes_loop(lines):
    start = next(i for i, line in enumerate(lines) if line.lstrip().startswith("foreach") and "NOTAS_EN" in line)
    depth = 0
    for end in range(start, len(lines)):
        depth += lines[end].count("{") - lines[end].count("}")
        if depth <= 0:
            return start, end
    return start, len(lines) - 1


def comment_notes_loop(run):
    lines = str(run).splitlines()
    start, end = notes_loop(lines)
    return "\n".join(lines[:start] + ["# " + line for line in lines[start:end + 1]] + lines[end + 1:]) + "\n"


def block_notes_loop(run):
    lines = str(run).splitlines()
    start, end = notes_loop(lines)
    return "\n".join(lines[:start] + ["<#"] + lines[start:end + 1] + ["#>"] + lines[end + 1:]) + "\n"


def shown(doc, name):
    return next(j for k, j in doc["jobs"].items() if display(k, j) == name or display(k, j).startswith(name + " ("))


def source_step(doc, name):
    value = inner(doc["jobs"]["monta"]["outputs"][name])
    return step_by_id(doc["jobs"]["monta"], re.fullmatch(STEP_OUTPUTS[name], value).group(1))


def free_job(doc, base):
    return next(f"{base}{n or ''}" for n in range(len(doc["jobs"]) + 1) if f"{base}{n or ''}" not in doc["jobs"])


def free_id(doc, base):
    taken = {s.get("id") for s in job_steps(doc["jobs"]["monta"])}
    return next(f"{base}{n or ''}" for n in range(len(taken) + 1) if f"{base}{n or ''}" not in taken)


def rename_step(doc, old, base):
    monta = doc["jobs"]["monta"]
    new = free_id(doc, base)
    step_by_id(monta, old)["id"] = new
    text = json.dumps(monta).replace(f"steps.{old}.", f"steps.{new}.")
    doc["jobs"]["monta"] = json.loads(text)


def version_from_other_job(doc, name):
    other = free_job(doc, "metadata")
    doc["jobs"][other] = {"runs-on": "ubuntu-latest", "outputs": {"versao": "${{ steps.n.outputs.versao }}"},
                          "steps": [{"id": "n", "run": "echo versao=1 >> $GITHUB_OUTPUT"}]}
    doc["jobs"]["monta"]["needs"] = [other]
    upload(doc, name)["with"]["name"] = f"ritmelli-exe-${{{{ needs.{other}.outputs.versao }}}}"


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
        "@('NOTAS', 'notas', '--notas')", '@("NOTAS", "notas", "--notas")').replace(
        "@('NOTAS_EN', 'notas_en', '--notas-en')", '@("NOTAS_EN", "notas_en", "--notas-en")')))
    check('@("NOTAS", "notas", "--notas")' in manifest_step(tuples["jobs"]["monta"])["run"]
          and '@("NOTAS_EN", "notas_en", "--notas-en")' in manifest_step(tuples["jobs"]["monta"])["run"]
          and contract_problems(tuples) == [], "the notes tuples in double quotes keep the contract")
    broken = mutant(doc, lambda d: edit_run(d, lambda run: run.replace("'--saida', $saida)",
                                                                       "'--saida',\n    $saida)")))
    check("'--saida',\n" in manifest_step(broken["jobs"]["monta"])["run"] and contract_problems(broken) == [],
          "the --saida value on the next line keeps the contract")
    marks = mutant(doc, lambda d: edit_run(d, lambda run: "# a <# in a line comment\n" + run + "# and a #> later\n"))
    check(contract_problems(marks) == [], "line comments that mention <# and #> keep the contract")
    migration_first = mutant(doc, lambda d: shown(d, "testa").update(
        needs=["monta", next(k for k, j in d["jobs"].items() if j is shown(d, "testa-migracao"))]))
    quoted_output = mutant(doc, lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
        run=step_by_id(d["jobs"]["monta"], "congela")["run"].replace(
            "-Path $env:GITHUB_OUTPUT -Value \"versao=", '-Path "${env:GITHUB_OUTPUT}" -Value "versao=')))
    check("${env:GITHUB_OUTPUT}" in step_by_id(quoted_output["jobs"]["monta"], "congela")["run"]
          and contract_problems(quoted_output) == [], "the output file written as \"${env:GITHUB_OUTPUT}\" keeps the "
                                                      "contract")
    check(contract_problems(migration_first) == [],
          "testa needing testa-migracao, which runs in every published build, keeps the contract")
    cited = mutant(doc, lambda d: edit_run(d, lambda run: run + "# publica.py also takes '--saida', $other)\n"))
    check(contract_problems(cited) == [], "a comment citing --saida after the real option keeps the contract")
    later = mutant(doc, lambda d: shown(d, "testa")["steps"].append(
        {"name": "Lista", "shell": "powershell", "run": "# publica.py wrote the manifest\n"}))
    check(contract_problems(later) == [], "a step after the manifest that mentions publica.py keeps the contract")
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
        "the anterior output written as a constant": lambda d: d["jobs"]["monta"]["outputs"].update(anterior="false"),
        "the anterior output inverted": lambda d: d["jobs"]["monta"]["outputs"].update(
            anterior=d["jobs"]["monta"]["outputs"]["anterior"].replace("!=", "==")),
        "the step behind the anterior output under a condition": lambda d: source_step(d, "anterior").update(
            {"if": "github.event_name == 'push'"}),
        "the parcial output with a longer key": lambda d: d["jobs"]["monta"]["outputs"].update(
            parcial=d["jobs"]["monta"]["outputs"]["parcial"].replace("outputs.parcial", "outputs.parcial-exe")),
        "the parcial output from another key": lambda d: d["jobs"]["monta"]["outputs"].update(
            parcial="${{ steps.congela.outputs.versao }}"),
        "the id of the step behind the anterior output": lambda d: source_step(d, "anterior").update(
            id=free_id(d, "previous")),
        "the needs of testa-parcial": lambda d: shown(d, "testa-parcial").update(needs=["testa"]),
        "a step before the manifest that mentions publica.py": lambda d: d["jobs"]["monta"]["steps"].insert(
            d["jobs"]["monta"]["steps"].index(step_by_id(d["jobs"]["monta"], "congela")) + 1,
            {"name": "Lista", "shell": "powershell", "run": "# publica.py writes the manifest later\n"}),
        "the ritmelli-exe artifact named by the versao of another job": lambda d: version_from_other_job(d, exe),
        "a second testa-migracao job gated by parcial": lambda d: d["jobs"].update(
            {free_job(d, "partial-checks"): dict(copy.deepcopy(shown(d, "testa-parcial")),
                                                 name="testa-migracao (partial checks)")}),
        "the needs of testa-migracao": lambda d: shown(d, "testa-migracao").update(needs=["testa"]),
        "the comparison in the if: of testa-parcial": lambda d: shown(d, "testa-parcial").update(
            {"if": shown(d, "testa-parcial")["if"].replace("==", "!=")}),
        "the parcial the monta step writes": lambda d: source_step(d, "parcial").update(
            run=source_step(d, "parcial")["run"].replace('"parcial=$', '"partial=$')),
        "the parcial output": lambda d: d["jobs"]["monta"]["outputs"].pop("parcial"),
        "the output the if: of testa-parcial reads": lambda d: shown(d, "testa-parcial").update(
            {"if": shown(d, "testa-parcial")["if"].replace("outputs.parcial", "outputs.partial")}),
        "the output the if: of testa-migracao reads": lambda d: shown(d, "testa-migracao").update(
            {"if": shown(d, "testa-migracao")["if"].replace("outputs.anterior", "outputs.previous")}),
        "an output the monta job does not declare in the if: of testa-parcial": lambda d: shown(
            d, "testa-parcial").update(
                {"if": bare(shown(d, "testa-parcial")["if"]) + " && needs.monta.outputs.migra == 'true'"}),
        "the if: of testa-parcial with an unclosed ${{": lambda d: shown(d, "testa-parcial").update(
            {"if": "${{ " + bare(shown(d, "testa-parcial")["if"])}),
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
        "the only assignment of the --saida folder commented out": lambda d: edit_run(d, lambda run: re.sub(
            r"^(\s*)(\$saida\s*=.*)$", r"\1# \2", run, count=1, flags=re.M)),
        "testa-atualizador gated by anterior without needing monta": lambda d: shown(d, "testa-atualizador").update(
            {"if": shown(d, "testa-migracao")["if"],
             "needs": [next(k for k, j in d["jobs"].items() if j is shown(d, "testa"))]}),
        "testa-atualizador needing a bridge gated by anterior that does not need monta": lambda d: (
            d["jobs"].update({free_job(d, "bridge"): {
                "runs-on": "ubuntu-latest", "if": shown(d, "testa-migracao")["if"], "steps": [{"run": "echo"}],
                "needs": [next(k for k, j in d["jobs"].items() if j is shown(d, "testa-migracao"))]}}),
            shown(d, "testa-atualizador").update(
                needs=["monta", [k for k in d["jobs"] if k.startswith("bridge")][-1]])),
        "the congela writing versao to another file": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
            run=step_by_id(d["jobs"]["monta"], "congela")["run"].replace(
                "-Path $env:GITHUB_OUTPUT -Value \"versao=", '-Path "$env:GITHUB_OUTPUT.tmp" -Value "versao=')),
        "testa-atualizador only on push": lambda d: shown(d, "testa-atualizador").update(
            {"if": "github.event_name == 'push'"}),
        "testa-atualizador needing a job that runs only on push": lambda d: (
            d["jobs"].update({free_job(d, "gate"): {"runs-on": "ubuntu-latest", "if": "github.event_name == 'push'",
                                                    "steps": [{"run": "echo"}]}}),
            shown(d, "testa-atualizador").update(needs=["monta", [k for k in d["jobs"] if k.startswith("gate")][-1]])),
        "testa-atualizador gated like testa-parcial": lambda d: shown(d, "testa-atualizador").update(
            {"if": shown(d, "testa-parcial")["if"]}),
        "the congela writing to another environment variable": lambda d: step_by_id(
            d["jobs"]["monta"], "congela").update(run=step_by_id(d["jobs"]["monta"], "congela")["run"].replace(
                "$env:GITHUB_OUTPUT", "$env:GITHUB_OUTPUT_FILE")),
        "testa needing testa-parcial": lambda d: shown(d, "testa").update(
            needs=["monta", next(k for k, j in d["jobs"].items() if j is shown(d, "testa-parcial"))]),
        "a block comment with the artifact folder before a --saida moved elsewhere": lambda d: (
            edit_run(d, lambda run: re.sub(r"^(\s*)(\$args_ = )", lambda m: m.group(1) + "<# '--saida', '"
                                           + output_folder(run) + "') #>\n" + m.group(1) + m.group(2), run,
                                           count=1, flags=re.M)),
            move_folder(d)),
        "a block comment on its own lines with the artifact folder before a --saida moved elsewhere": lambda d: (
            edit_run(d, lambda run: re.sub(r"^(\s*)(\$args_ = )", lambda m: m.group(1) + "<#\n" + m.group(1)
                                           + "'--saida', '" + output_folder(run) + "')\n" + m.group(1) + "#>\n"
                                           + m.group(1) + m.group(2), run, count=1, flags=re.M)),
            move_folder(d)),
        "testa-atualizador needing testa-parcial through an always() job": lambda d: (
            d["jobs"].update({free_job(d, "bridge"): {
                "runs-on": "ubuntu-latest", "if": "always()", "steps": [{"run": "echo"}],
                "needs": [next(k for k, j in d["jobs"].items() if j is shown(d, "testa-parcial"))]}}),
            shown(d, "testa-atualizador").update(
                needs=["monta", [k for k in d["jobs"] if k.startswith("bridge")][-1]])),
        "the --saida assignment in a block comment": lambda d: edit_run(d, lambda run: re.sub(
            r"^(\s*)(\$saida\s*=.*)$", r"\1<#\n\1\2\n\1#>", run, count=1, flags=re.M)),
        "a comment with the artifact folder before a --saida moved elsewhere": lambda d: (
            edit_run(d, lambda run: re.sub(r"^(\s*)(\$args_ = )", lambda m: m.group(1) + "# '--saida', '"
                                           + output_folder(run) + "')\n" + m.group(1) + m.group(2), run,
                                           count=1, flags=re.M)),
            move_folder(d)),
        "a second active --saida": lambda d: edit_run(d, lambda run: run.replace(
            "'--saida', $saida)", "'--saida', $saida, '--saida', 'elsewhere')")),
        "testa-atualizador needing a switched-off job": lambda d: (
            d["jobs"].update({free_job(d, "gate"): {"runs-on": "ubuntu-latest", "if": "false",
                                                    "steps": [{"run": "echo"}]}}),
            shown(d, "testa-atualizador").update(needs=["monta", [k for k in d["jobs"] if k.startswith("gate")][-1]])),
        "the notes loop in a block comment": lambda d: edit_run(d, block_notes_loop),
        "a switched-off job shown like testa-atualizador": lambda d: d["jobs"].update(
            {free_job(d, "extra"): dict(copy.deepcopy(shown(d, "testa-atualizador")),
                                        name="testa-atualizador (extra)", **{"if": "${{ false }}"})}),
        "the Ritmelli artifact named with the marker itself": lambda d: upload(d, setup)["with"].update(
            name=f"Ritmelli-{MARK}"),
        "the --saida option left only in a comment": lambda d: edit_run(d, lambda run: run.replace(
            ", '--saida', $saida)", ")\n# '--saida', $saida)")),
        "a comment that assigns the folder of --saida": lambda d: edit_run(d, lambda run: re.sub(
            r"^(\s*)(\$saida\s*=.*)$", r"\1# $saida = 'saida'\n\1\2", run, count=1, flags=re.M)),
        "a trailing comment on the --saida assignment": lambda d: edit_run(d, lambda run: re.sub(
            r"^(\s*)(\$saida\s*=.*)$", r"\1\2  # the artifact folder", run, count=1, flags=re.M)),
        "the --saida assignment with a type": lambda d: edit_run(d, lambda run: re.sub(
            r"^(\s*)(\$saida\s*=)", r"\1[string]\2", run, count=1, flags=re.M)),
        "a statement before the --saida assignment on its line": lambda d: edit_run(d, lambda run: re.sub(
            r"^(\s*)(\$saida\s*=)", r"\1$x = 1; \2", run, count=1, flags=re.M)),
        "a $ in the single-quoted folder of --saida": lambda d: (
            assign_folder(d, "'instalador\\$saida'"), upload(d, setup)["with"].update(path="instalador/$saida/")),
        "the testa-atualizador job switched off": lambda d: shown(d, "testa-atualizador").update(
            {"if": "${{ false }}"}),
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
            run=re.sub(r"@\((['\"])NOTAS_EN\1,", r"@(\1NOTES_EN\1,", manifest_step(d["jobs"]["monta"])["run"])),
        "the option of the notas": lambda d: manifest_step(d["jobs"]["monta"]).update(
            run=re.sub(r"(['\"])--notas\1\)", "'--notes')", manifest_step(d["jobs"]["monta"])["run"])),
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
    testa_id = next(k for k, j in doc["jobs"].items() if display(k, j) == "testa")
    renamed_job = mutant(doc, lambda d: d["jobs"].update(smoke=dict(d["jobs"].pop(testa_id), name="testa")))
    check(contract_problems(renamed_job) == [], "the testa job with another id and the same shown name keeps the "
                                                "contract")
    item = mutant(doc, lambda d: edit_run(d, lambda run: re.sub(r"\$n\b", "$item", run)))
    check("$item" in manifest_step(item["jobs"]["monta"])["run"] and contract_problems(item) == []
          and comment_notes_loop(manifest_step(item["jobs"]["monta"])["run"]).count("# foreach") == 1,
          "the notes loop with another variable keeps the contract and its mutant still comments it out")
    compact = mutant(doc, lambda d: d["jobs"]["monta"]["outputs"].update(
        anterior=d["jobs"]["monta"]["outputs"]["anterior"].replace(" != ", "!=")))
    check("!=''" in compact["jobs"]["monta"]["outputs"]["anterior"] and contract_problems(compact) == [],
          "the anterior comparison written without spaces keeps the contract")
    renamed_steps = mutant(doc, lambda d: (rename_step(d, source_step(d, "anterior")["id"], "previous_build"),
                                           rename_step(d, source_step(d, "parcial")["id"], "build")))
    check(contract_problems(renamed_steps) == [], "the steps behind anterior and parcial with other ids keep the "
                                                  "contract")
    taken = mutant(doc, lambda d: manifest_step(d["jobs"]["monta"]).update(id="build"))
    taken_renamed = mutant(taken, lambda d: rename_step(d, source_step(d, "parcial")["id"], "build"))
    check(contract_problems(taken) == [] and contract_problems(taken_renamed) == []
          and source_step(taken_renamed, "parcial")["id"] != "build",
          "renaming the step behind parcial picks an id no other step has")
    for form, label in (("${{ %s }}", "wrapped in ${{ }}"), ("%s", "without ${{ }}")):
        gated_form = mutant(doc, lambda d: [shown(d, j).update({"if": form % bare(shown(d, j)["if"])})
                                            for j in GATED_JOBS])
        check(contract_problems(gated_form) == [], f"the if: of the gated jobs {label} keeps the contract")
    for base, label in ((doc, ""), (spaces, " (version expression without spaces)"),
                        (packed_folder, " (folder of --saida assigned without spaces)"),
                        (renamed_job, " (testa job with another id)"),
                        (renamed_steps, " (steps behind anterior and parcial with other ids)"),
                        (tuples, " (notes tuple in double quotes)")):
        for name, change in mutants.items():
            check(contract_problems(mutant(base, change)) != [], f"the check catches {name} changed{label}")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
