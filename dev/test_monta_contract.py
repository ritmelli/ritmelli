import copy
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

from workflow_yaml import job_steps, load

ROOT = Path(__file__).resolve().parent.parent
MONTA = ROOT / ".github" / "workflows" / "monta.yml"
BUILD_MANIFEST = ROOT / "instalador" / "atualizacao" / "build_manifest.py"
MANIFEST_RUN = ['& "$env:LOCALAPPDATA\\ritmelli-build\\Scripts\\python.exe" '
                'instalador\\atualizacao\\build_manifest.py',
                'if ($LASTEXITCODE -ne 0) { throw "build_manifest.py exited with $LASTEXITCODE" }']
DIRECTIVE = re.compile(r"#requires\b", re.I)
CALLS = re.compile(r"\b(build_manifest|publica)\b", re.I)
VERSION = "${{ steps.congela.outputs.versao }}"
MARK = "<version>"
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.S)
INPUTS = ("notas", "notas_en")
REQUIRED_JOBS = ("testa", "testa-atualizador", "testa-migracao", "testa-parcial")
GATED_JOBS = {"testa-migracao": "anterior", "testa-parcial": "parcial"}
BUILDS = ({"anterior": True, "parcial": True}, {"anterior": True, "parcial": False})
SETUP, EXE = f"Ritmelli-{MARK}", f"ritmelli-exe-{MARK}"
NOTES = {"NOTAS": "${{ inputs.notas }}", "NOTAS_EN": "${{ inputs.notas_en }}"}
STEP_OUTPUTS = {"anterior": r"steps\.([\w-]+)\.outputs\.([\w-]+)\s*!=\s*''",
                "parcial": r"steps\.([\w-]+)\.outputs\.(parcial)"}
RESERVED = ("Ritmelli-", "ritmelli-exe-")
OTHER_VERSION = re.compile(
    r"(?:Ritmelli|ritmelli-exe)-(?:[0-9]|<version>|\$\{\{.*?\}\})(?:[0-9.]|<version>|\$\{\{.*?\}\})*", re.S)

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
                conditional = "if" in job or "if" in s or not all(runs(jobs, job_id, b) for b in BUILDS)
                out.append((mark(w.get("name", ""), versions), w, conditional))
    return out


def could_be_reserved(name):
    head = name.split("${{", 1)[0]
    return "${{" in name and head not in RESERVED and any(r.startswith(head) for r in RESERVED)


def normal_path(path):
    return str(path or "").strip().replace("\\", "/").rstrip("/")


def step_by_id(job, step_id):
    found = [s for s in job_steps(job) if s.get("id") == step_id and not switched_off(s.get("if"))]
    return found[0] if len(found) == 1 else None


def commands(run):
    return [line.strip() for line in str(run).splitlines()
            if line.strip() and not (line.strip().startswith("#") and not DIRECTIVE.match(line.strip()))]


def manifest_step(job):
    found = [s for s in job_steps(job) if commands(s.get("run", "")) == MANIFEST_RUN]
    return found[0] if len(found) == 1 else None


def texts(node):
    if isinstance(node, dict):
        return [t for k, v in node.items() for t in (*texts(k), *texts(v))]
    if isinstance(node, list):
        return [t for v in node for t in texts(v)]
    return [str(node)]


def manifest_folder(script=BUILD_MANIFEST):
    spec = importlib.util.spec_from_file_location("build_manifest", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.OUTPUT.as_posix()


def output_lines(run, key):
    path = r"""(?:^|\s)-Path\s+("?)(?:\$env:GITHUB_OUTPUT|\$\{env:GITHUB_OUTPUT\})\1(?=\s|$)"""
    lines = re.finditer(r"(?<![^\n;{}])[ \t]*Add-Content\b[^\n;]*", code(run), re.I)
    return [(m.start(), m.group(0)) for m in lines
            if re.search(path, m.group(0), re.I) for _ in re.finditer(rf"""["']{key}=""", m.group(0), re.I)]


def writes_output(run, key):
    lines = output_lines(run, key)
    return len(lines) == 1 and re.search(rf'"{key}=\$', lines[0][1], re.I) is not None


def bare(condition):
    text = str(condition).strip()
    return inner(text) if "${{" in text or "}}" in text else text


def partial_probed(job, folder):
    source = re.fullmatch(STEP_OUTPUTS["parcial"], inner((job.get("outputs") or {}).get("parcial", "")) or "")
    step = source and step_by_id(job, source.group(1))
    wanted = normal_path(folder) + "/Ritmelli-$env:VERSAO-parcial.exe"
    if not step or inner((step.get("env") or {}).get("VERSAO", "")) != inner(VERSION):
        return False
    run = code(step.get("run", ""))
    probes = re.finditer(r'^\s*\$(\w+)\s*=\s*Test-Path\s+(?:-Path\s+)?"([^"]+)"\s*$', run, re.M)
    written = r'"parcial=\$\(\${0}\.ToString\(\)\.ToLower\(\)\)"|"parcial=\${0}"'
    return any(normal_path(m.group(2)) == wanted
               and len(re.findall(rf"\${m.group(1)}\b\s*[-+*/]?=(?!=)", run, re.I)) == 1
               and any(at > m.start() and re.search(written.format(m.group(1)), line, re.I)
                       for at, line in output_lines(run, "parcial")) for m in probes)


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


def condition_holds(condition, build, needs):
    if condition is None:
        return True
    text = bare(condition) or ""
    if re.fullmatch(r"(always|success)\(\)", text):
        return True
    gate = re.fullmatch(r"needs\.monta\.outputs\.(\w+)\s*==\s*'(?i:true)'", text)
    return bool(gate) and "monta" in needs and build.get(gate.group(1), False)


def runs(jobs, job_id, build, seen=()):
    job = jobs.get(job_id)
    if job is None or job_id in seen:
        return False
    needs = job.get("needs") or []
    needs = [needs] if isinstance(needs, str) else needs
    return condition_holds(job.get("if"), build, needs) and all(runs(jobs, n, build, seen + (job_id,)) for n in needs)


def one_literal_file(path, filename):
    path = str(path or "").strip()
    return "\n" not in path and not any(c in path for c in "*?[!") and Path(path).name == filename


def contract_problems(doc, script=BUILD_MANIFEST):
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
            if not re.fullmatch(rf"needs\.monta\.outputs\.{output}\s*==\s*'(?i:true)'", bare(job.get("if", "")) or ""):
                problems.append(f"the if: of {required} does not read the {output} output of the monta job")
    run_uploads = uploads(jobs)
    found = {name: [w for n, w, _ in run_uploads if n == name] for name in (SETUP, EXE)}
    if len(found[SETUP]) == 1 and not partial_probed(monta, found[SETUP][0].get("path")):
        problems.append("the step behind the parcial output does not Test-Path the partial setup in the "
                        f"{SETUP} folder")
    problems += [f"the run uploads {len(w)} artifacts named {n}, not 1" for n, w in found.items() if len(w) != 1]
    problems += [f"the {n} artifact is uploaded under an if: or in a job that does not run in every build the "
                 "pipeline expects" for n, _, c in run_uploads if n in found and c]
    fixed = [n for n, _, _ in run_uploads
             if n not in (SETUP, EXE) and OTHER_VERSION.fullmatch(n.replace("<written version>", MARK))]
    open_names = [n for n, _, _ in run_uploads if could_be_reserved(n)]
    if open_names:
        problems.append(f"the run uploads {open_names}, whose expression could make a Ritmelli- or ritmelli-exe- name")
    if fixed:
        problems.append(f"the run uploads {fixed}, which the pipeline would take for the version or for the {EXE} "
                        "artifact of the build")
    if len(found[EXE]) == 1 and not one_literal_file(found[EXE][0].get("path"), "ritmelli.exe"):
        problems.append(f"the {EXE} artifact is not the ritmelli.exe alone ({found[EXE][0].get('path')!r})")
    manifest = manifest_step(monta)
    callers = [s for j in jobs.values() for s in job_steps(j) if any(CALLS.search(t) for t in texts(s))]
    folder = manifest_folder(script)
    if manifest is None or switched_off(manifest.get("if")):
        problems.append("the monta job has no one step that runs build_manifest.py, the script that runs publica.py")
    elif callers != [manifest]:
        problems.append("another step mentions build_manifest or publica, and the pipeline reads only the step that "
                        "runs build_manifest.py")
    elif "if" in manifest:
        problems.append("the step that runs build_manifest.py runs only under an if:, so the manifest may be missing")
    else:
        if len(found[SETUP]) == 1 and normal_path(found[SETUP][0].get("path")) != normal_path(folder):
            problems.append(f"the {SETUP} artifact is {found[SETUP][0].get('path')!r}, not the folder "
                            f"build_manifest.py writes the manifest to ({folder})")
        for name, value in NOTES.items():
            if inner((manifest.get("env") or {}).get(name, "")) != inner(value):
                problems.append(f"the step that runs build_manifest.py does not get {name} from {value}")
    return problems


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


def move_output_before_probe(run):
    lines = str(run).split("\n")
    probe = next(i for i, line in enumerate(lines) if "= Test-Path" in line and "-parcial.exe" in line)
    output = next(i for i, line in enumerate(lines) if '"parcial=$' in line)
    lines.insert(probe, lines.pop(output))
    return "\n".join(lines)


def move_exe_upload(doc):
    step = upload(doc, f"ritmelli-exe-{VERSION}")
    doc["jobs"]["monta"]["steps"].remove(step)
    step["with"]["name"] = "ritmelli-exe-${{ needs.monta.outputs.versao }}"
    parcial = next(k for k, j in doc["jobs"].items() if j is shown(doc, "testa-parcial"))
    doc["jobs"][free_job(doc, "exe")] = {"runs-on": "ubuntu-latest", "needs": ["monta", parcial], "steps": [step]}


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

    folder, other = manifest_folder(), manifest_folder() + "_moved"
    moved = mutant(doc, lambda d: (upload(d, setup)["with"].update(path=other + "/"),
                                   source_step(d, "parcial").update(run=source_step(d, "parcial")["run"].replace(
                                       f'Test-Path "{folder}/'.replace("/", "\\"),
                                       f'Test-Path "{other}/'.replace("/", "\\")))))
    with tempfile.TemporaryDirectory() as temp:
        script = Path(temp, BUILD_MANIFEST.name)
        source, count = re.subn(r"(?m)^OUTPUT = [^\r\n]+", f"OUTPUT = Path({other!r})",
                                BUILD_MANIFEST.read_text(encoding="utf-8"))
        script.write_text(source, encoding="utf-8")
        check(count == 1 and contract_problems(moved, script) == [],
              "the folder build_manifest.py writes to and the Ritmelli artifact path moved together keep the contract")
        check([p for p in contract_problems(doc, script) if "not the folder build_manifest.py writes" in p] != [],
              "the check catches the folder build_manifest.py writes to changed alone")
    marks = mutant(doc, lambda d: edit_run(d, lambda run: "# a <# in a line comment\n" + run + "# and a #> later\n"))
    check(contract_problems(marks) == [], "line comments that mention <# and #> keep the contract")
    cased = mutant(doc, lambda d: source_step(d, "parcial").update(
        run=source_step(d, "parcial")["run"].replace('"parcial=$($parcial.', '"parcial=$($Parcial.')))
    check('"parcial=$($Parcial.' in source_step(cased, "parcial")["run"] and contract_problems(cased) == [],
          "the parcial variable written in another case keeps the contract")
    shouted = mutant(doc, lambda d: [shown(d, j).update({"if": shown(d, j)["if"].replace("'true'", "'TRUE'")})
                                     for j in GATED_JOBS])
    check(all("'TRUE'" in shown(shouted, j)["if"] for j in GATED_JOBS) and contract_problems(shouted) == [],
          "the gated if: compared with 'TRUE' keeps the contract")
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
        "the step that runs build_manifest.py switched off": lambda d: manifest_step(d["jobs"]["monta"]).update(
            {"if": "false"}),
        "the ritmelli.exe path with a wildcard": lambda d: upload(d, exe)["with"].update(path="dist/*/ritmelli.exe"),
        "the ritmelli.exe path with two files": lambda d: upload(d, exe)["with"].update(
            path="dist/ritmelli/ritmelli.exe\ndist/ritmelli/ritmelli2.exe"),
        "a Ritmelli artifact named by a format expression": lambda d: d["jobs"]["monta"]["steps"].append(
            {"uses": upload(d, setup)["uses"],
             "with": {"name": "Ritmelli-${{ format('{0}', github.run_number) }}", "path": "x"}}),
        "a Ritmelli artifact named by the version and a suffix": lambda d: d["jobs"]["monta"]["steps"].append(
            {"uses": upload(d, setup)["uses"], "with": {"name": setup + ".1", "path": "x"}}),
        "the manifest step running publica.py instead of build_manifest.py": lambda d: edit_run(
            d, lambda run: run.replace("build_manifest.py", "publica.py")),
        "a step after the manifest that mentions publica.py": lambda d: shown(d, "testa")["steps"].append(
            {"name": "Lista", "shell": "powershell", "run": "# publica.py wrote the manifest\n"}),
        "a switched-off step that runs publica.py": lambda d: shown(d, "testa")["steps"].append(
            {"if": "false", "run": "python instalador\\atualizacao\\publica.py --app outro\n"}),
        "an action whose script mentions publica": lambda d: shown(d, "testa")["steps"].append(
            {"uses": "actions/github-script@v7", "with": {"script": "// publica"}}),
        "the build_manifest.py call written with forward slashes": lambda d: edit_run(d, lambda run: run.replace(
            "instalador\\atualizacao\\build_manifest.py", "instalador/atualizacao/build_manifest.py")),
        "a second line in the manifest step that runs publica.py": lambda d: edit_run(
            d, lambda run: run + "& python instalador\\atualizacao\\publica.py --app outro\n"),
        "a #Requires line in the manifest step": lambda d: edit_run(d, lambda run: "#Requires -Version 7.0\n" + run),
        "the build's Python from another folder": lambda d: edit_run(d, lambda run: run.replace(
            "ritmelli-build", "ritmelli-other")),
        "the step that runs build_manifest.py under a condition": lambda d: manifest_step(d["jobs"]["monta"]).update(
            {"if": "env.ASSINA == 'true'"}),
        "the congela step under a condition": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
            {"if": "github.event_name == 'push'"}),
        "a Ritmelli artifact named by another expression": lambda d: d["jobs"]["monta"]["steps"].append(
            {"uses": upload(d, setup)["uses"], "with": {"name": "Ritmelli-${{ github.run_number }}", "path": "x"}}),
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
        "the ritmelli-exe upload in a job that needs testa-parcial": lambda d: move_exe_upload(d),
        "a second partial probe for another file": lambda d: source_step(d, "parcial").update(
            run=re.sub(r'^(\s*)(\$parcial = Test-Path "[^"]*)-parcial\.exe"$', r'\1\2-parcial.exe"\n\1\2-partial.exe"',
                       source_step(d, "parcial")["run"], count=1, flags=re.M)),
        "a log line with the parcial before an Add-Content from another variable": lambda d: source_step(
            d, "parcial").update(run=source_step(d, "parcial")["run"].replace(
                'Add-Content -Path $env:GITHUB_OUTPUT -Value "parcial=$($parcial.',
                '"parcial=$($parcial.ToString().ToLower())"\n'
                'Add-Content -Path $env:GITHUB_OUTPUT -Value "parcial=$($other.')),
        "the parcial written before the probe": lambda d: source_step(d, "parcial").update(
            run=move_output_before_probe(source_step(d, "parcial")["run"])),
        "a second Add-Content writing parcial=false": lambda d: source_step(d, "parcial").update(
            run=source_step(d, "parcial")["run"].rstrip("\n")
            + '\nAdd-Content -Path $env:GITHUB_OUTPUT -Value "parcial=false" -Encoding ascii\n'),
        "a parcial=false after the real write on the same line": lambda d: source_step(d, "parcial").update(
            run=re.sub(r'("parcial=\$\(\$parcial[^"]*" -Encoding ascii)',
                       r'\1; Add-Content -Path $env:GITHUB_OUTPUT -Value "parcial=false"',
                       source_step(d, "parcial")["run"])),
        "a second versao= in the -Value array": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
            run=step_by_id(d["jobs"]["monta"], "congela")["run"].replace(
                '-Value "versao=$v"', '-Value "versao=$v", "versao="')),
        "a second parcial=false in the -Value array": lambda d: source_step(d, "parcial").update(
            run=source_step(d, "parcial")["run"].replace(".ToLower())\"", '.ToLower())", "parcial=false"')),
        "a second ritmelli-exe named by the versao output of its own job": lambda d: d["jobs"].update(
            {free_job(d, "copy"): {"runs-on": "ubuntu-latest", "needs": ["monta"],
                                   "outputs": {"versao": "${{ steps.v.outputs.versao }}"},
                                   "steps": [{"id": "v", "run": "echo"},
                                             {"uses": upload(d, exe)["uses"],
                                              "with": {"name": "ritmelli-exe-${{ steps.v.outputs.versao }}",
                                                       "path": "dist/ritmelli/ritmelli.exe"}}]}}),
        "the assinar-app upload renamed to a literal ritmelli-exe version": lambda d: next(
            s for s in d["jobs"]["monta"]["steps"]
            if str((s.get("with") or {}).get("name", "")).startswith("assinar-app-"))["with"].update(
                name="ritmelli-exe-0.6.0"),
        "a second upload named ritmelli-exe-<version> literally": lambda d: d["jobs"]["monta"]["steps"].append(
            {"uses": upload(d, exe)["uses"], "with": {"name": f"ritmelli-exe-{MARK}", "path": "x/ritmelli.exe"}}),
        "a second Ritmelli artifact with the version expression across lines": lambda d: d["jobs"]["monta"][
            "steps"].append({"uses": upload(d, setup)["uses"],
                             "with": {"name": "Ritmelli-${{\n steps.congela.outputs.versao }}", "path": "x"}}),
        "a Ritmelli artifact named by another expression across lines": lambda d: d["jobs"]["monta"]["steps"].append(
            {"uses": upload(d, setup)["uses"], "with": {"name": "Ritmelli-${{\n github.run_number }}", "path": "x"}}),
        "a later PARCIAL=false in capitals": lambda d: source_step(d, "parcial").update(
            run=source_step(d, "parcial")["run"].rstrip("\n")
            + '\nAdd-Content -Path $env:GITHUB_OUTPUT -Value "PARCIAL=false" -Encoding ascii\n'),
        "a later empty VERSAO= in capitals": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
            run=step_by_id(d["jobs"]["monta"], "congela")["run"].rstrip("\n")
            + '\nAdd-Content -Path $env:GITHUB_OUTPUT -Value "VERSAO=" -Encoding ascii\n'),
        "the assinar-app upload named by a whole format expression": lambda d: next(
            s for s in d["jobs"]["monta"]["steps"]
            if str((s.get("with") or {}).get("name", "")).startswith("assinar-app-"))["with"].update(
                name="${{ format('Ritmelli-{0}', github.run_number) }}"),
        "an upload whose expression completes the Ritmelli- prefix": lambda d: d["jobs"]["monta"]["steps"].append(
            {"uses": upload(d, setup)["uses"], "with": {"name": "Rit${{ format('melli-{0}', github.run_number) }}",
                                                        "path": "x"}}),
        "a parcial=false in a one-line if block": lambda d: source_step(d, "parcial").update(
            run=source_step(d, "parcial")["run"].rstrip("\n")
            + '\nif ($env:ANTERIOR) { Add-Content -Path $env:GITHUB_OUTPUT -Value "parcial=false" -Encoding ascii }\n'),
        "an empty versao in a one-line if block": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
            run=step_by_id(d["jobs"]["monta"], "congela")["run"].rstrip("\n")
            + '\nif ($v) { Add-Content -Path $env:GITHUB_OUTPUT -Value "versao=" }\n'),
        "a later parcial write from another variable": lambda d: source_step(d, "parcial").update(
            run=source_step(d, "parcial")["run"].rstrip("\n")
            + '\nAdd-Content -Path $env:GITHUB_OUTPUT -Value "parcial=$($other.ToString())" -Encoding ascii\n'),
        "a second Add-Content writing an empty versao": lambda d: step_by_id(d["jobs"]["monta"], "congela").update(
            run=step_by_id(d["jobs"]["monta"], "congela")["run"].rstrip("\n")
            + '\nAdd-Content -Path $env:GITHUB_OUTPUT -Value "versao=" -Encoding ascii\n'),
        "the partial probe negated": lambda d: source_step(d, "parcial").update(
            run=re.sub(r'= Test-Path ("[^"]*-parcial\.exe")', r"= -not (Test-Path \1)",
                       source_step(d, "parcial")["run"])),
        "the parcial written from another variable": lambda d: source_step(d, "parcial").update(
            run=source_step(d, "parcial")["run"].replace('"parcial=$($parcial.', '"parcial=$($other.')),
        "the partial setup looked for in single quotes": lambda d: source_step(d, "parcial").update(
            run=re.sub(r'Test-Path "([^"]*-parcial\.exe)"', r"Test-Path '\1'", source_step(d, "parcial")["run"])),
        "the VERSAO of the step behind the parcial output": lambda d: source_step(d, "parcial")["env"].update(
            VERSAO="${{ steps.congela.outputs.version }}"),
        "the partial setup the monta step looks for": lambda d: source_step(d, "parcial").update(
            run=source_step(d, "parcial")["run"].replace("-parcial.exe\"", "-partial.exe\"")),
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
        "testa-atualizador needing testa-parcial through an always() job": lambda d: (
            d["jobs"].update({free_job(d, "bridge"): {
                "runs-on": "ubuntu-latest", "if": "always()", "steps": [{"run": "echo"}],
                "needs": [next(k for k, j in d["jobs"].items() if j is shown(d, "testa-parcial"))]}}),
            shown(d, "testa-atualizador").update(
                needs=["monta", [k for k in d["jobs"] if k.startswith("bridge")][-1]])),
        "testa-atualizador needing a switched-off job": lambda d: (
            d["jobs"].update({free_job(d, "gate"): {"runs-on": "ubuntu-latest", "if": "false",
                                                    "steps": [{"run": "echo"}]}}),
            shown(d, "testa-atualizador").update(needs=["monta", [k for k in d["jobs"] if k.startswith("gate")][-1]])),
        "a switched-off job shown like testa-atualizador": lambda d: d["jobs"].update(
            {free_job(d, "extra"): dict(copy.deepcopy(shown(d, "testa-atualizador")),
                                        name="testa-atualizador (extra)", **{"if": "${{ false }}"})}),
        "the Ritmelli artifact named with the marker itself": lambda d: upload(d, setup)["with"].update(
            name=f"Ritmelli-{MARK}"),
        "the testa-atualizador job switched off": lambda d: shown(d, "testa-atualizador").update(
            {"if": "${{ false }}"}),
        "the ritmelli-exe upload under a condition": lambda d: upload(d, exe).update(
            {"if": "github.event_name == 'push'"}),
        "a second Ritmelli artifact in another job": lambda d: shown(d, "testa")["steps"].append(
            {"uses": upload(d, setup)["uses"], "with": {"name": "Ritmelli-${{ needs.monta.outputs.versao }}",
                                                         "path": "saida/"}}),
        "the notas of the manifest": lambda d: manifest_step(d["jobs"]["monta"])["env"].pop("NOTAS"),
        "the notas_en of the manifest": lambda d: manifest_step(d["jobs"]["monta"])["env"].update(
            NOTAS_EN="${{ inputs.notas }}"),
    }
    for job_id in ("testa", "testa-atualizador", "testa-parcial"):
        mutants[f"the shown name of the job {job_id}"] = (lambda j: lambda d: shown(d, j).update(
            name=f"{j}-renamed"))(job_id)
    mutants["the name of the testa-migracao job"] = lambda d: shown(d, "testa-migracao").update(
        name="migracao (${{ matrix.scenario }})")
    testa_id = next(k for k, j in doc["jobs"].items() if display(k, j) == "testa")
    renamed_job = mutant(doc, lambda d: d["jobs"].update(smoke=dict(d["jobs"].pop(testa_id), name="testa")))
    check(contract_problems(renamed_job) == [], "the testa job with another id and the same shown name keeps the "
                                                "contract")
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
                        (renamed_job, " (testa job with another id)"),
                        (renamed_steps, " (steps behind anterior and parcial with other ids)")):
        for name, change in mutants.items():
            check(contract_problems(mutant(base, change)) != [], f"the check catches {name} changed{label}")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
