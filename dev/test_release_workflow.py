"""The release path in the workflows, read as YAML: every action pinned to a commit, the SignPath steps, the
sparse checkouts of the monta.yml jobs and the version resource check of the DLLs. Each check also runs on a mutant
of the real file and has to catch it.

    python dev/test_release_workflow.py
"""
import copy
import importlib.util
import re
import sys
import tempfile
from pathlib import Path, PureWindowsPath

import yaml

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("testa_tudo", ROOT / "dev" / "testa_tudo.py")
testa_tudo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(testa_tudo)
WORKFLOWS = ROOT / ".github" / "workflows"
ACTIONS = ROOT / ".github" / "actions"
MONTA = WORKFLOWS / "monta.yml"
TESTA = WORKFLOWS / "testa.yml"
PINNED = re.compile(r"[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}")
SIGNPATH = "signpath/github-action-submit-signing-request"
INNO = "./.github/actions/inno-setup"
VERSION_CHECK = re.compile(r"microfone\\apo\\check_version\.ps1 -Folder (\S+)")
DLL_FOLDERS = {"monta": "dist\\ritmelli\\_internal\\microfone", "microfone": "microfone\\apo\\saida"}
DLL_IFS = {"monta": None, "microfone": "steps.areas.outputs.microfone == 'true'"}
SCRIPT_CALL = re.compile(r"^\s*(?:&\s*)?(?:\.[\\/])?(instalador[\\/][\w.-]+\.ps1)", re.M)
JOB_SCRIPTS = {"testa-atualizador": "/instalador/testa-atualizador.ps1",
               "testa-parcial": "/instalador/testa-parcial.ps1",
               "testa-migracao": "/instalador/testa-migracao.ps1"}

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def files(root=ROOT):
    workflows = [p for ext in ("*.yml", "*.yaml") for p in (root / ".github" / "workflows").glob(ext)]
    actions = {p for name in ("action.yml", "action.yaml") for p in (root / ".github" / "actions").rglob(name)}
    pending = workflows + sorted(actions)
    while pending:
        for _, u in uses(load(pending.pop())):
            for manifest in (root / u / name for name in ("action.yml", "action.yaml") if u.startswith("./")):
                if manifest.is_file() and manifest not in actions:
                    actions.add(manifest)
                    pending.append(manifest)
    return sorted(workflows) + sorted(actions)


def steps(doc):
    for job_id, job in (doc.get("jobs") or {}).items():
        for i, step in enumerate(job.get("steps") or []):
            yield f"{job_id}.steps[{i}]", step
    for i, step in enumerate((doc.get("runs") or {}).get("steps") or []):
        yield f"runs.steps[{i}]", step


def uses(doc):
    found = [(f"{job_id}.uses", job["uses"]) for job_id, job in (doc.get("jobs") or {}).items() if "uses" in job]
    return found + [(where, step["uses"]) for where, step in steps(doc) if "uses" in step]


def unpinned(doc):
    return [f"{where}: {u}" for where, u in uses(doc) if not u.startswith("./") and not PINNED.fullmatch(u)]


def missing_local(doc):
    return [u for _, u in uses(doc) if u.startswith("./")
            and not any((ROOT / u / name).is_file() for name in ("action.yml", "action.yaml"))]


def signpath_steps(doc):
    return [step for step in doc["jobs"]["monta"]["steps"] if step.get("uses", "").startswith(SIGNPATH + "@")]


def signpath_problems(doc):
    found = signpath_steps(doc)
    refs = {step["uses"] for step in found}
    if len(found) != 2:
        return [f"{len(found)} SignPath steps in the monta job, not 2"]
    return [] if len(refs) == 1 and all(PINNED.fullmatch(r) for r in refs) else [f"SignPath at {sorted(refs)}"]


def test_pins():
    for path in files():
        doc = load(path)
        rel = path.relative_to(ROOT).as_posix()
        check(any(True for _ in steps(doc)), f"the steps of {rel} are read")
        check(unpinned(doc) == [], f"every action {rel} uses is pinned to a commit sha ({unpinned(doc)})")
        check(missing_local(doc) == [], f"every local action {rel} uses exists ({missing_local(doc)})")
    monta = load(MONTA)
    check(signpath_problems(monta) == [], f"both SignPath steps use one pinned commit ({signpath_problems(monta)})")
    for job, prefix in (("monta", "actions/checkout@"), ("testa", "actions/download-artifact@"),
                        ("testa-migracao", "actions/checkout@")):
        mutant = copy.deepcopy(monta)
        step = next(s for s in mutant["jobs"][job]["steps"] if s.get("uses", "").startswith(prefix))
        step["uses"] = prefix + "v7"
        check(any(f"{prefix}v7" in u for u in unpinned(mutant)), f"the check catches {prefix}v7 in the {job} job")
    for i in range(2):
        mutant = copy.deepcopy(monta)
        signpath_steps(mutant)[i]["uses"] = SIGNPATH + "@v3"
        check(signpath_problems(mutant) != [] and unpinned(mutant) != [],
              f"the check catches SignPath step {i + 1} at @v3")
    action = load(ACTIONS / "python" / "action.yml")
    action["runs"]["steps"][0]["uses"] = "actions/setup-python@v7"
    check(unpinned(action) != [], "the check catches actions/setup-python@v7 in a local action")
    with tempfile.TemporaryDirectory(prefix="ritmelli-pins-") as tmp:
        tmp = Path(tmp)
        moving = ("jobs:\n  x:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@v7\n"
                  "      - uses: ./dev/actions/example\n")
        nested = "runs:\n  using: composite\n  steps:\n    - uses: actions/cache/save@v6\n"
        outside = "runs:\n  using: composite\n  steps:\n    - uses: actions/checkout@v7\n"
        for rel, text in ((".github/workflows/other.yaml", moving), (".github/actions/a/b/action.yaml", nested),
                          ("dev/actions/example/action.yml", outside)):
            (tmp / rel).parent.mkdir(parents=True)
            (tmp / rel).write_text(text, encoding="utf-8")
        found = {p.relative_to(tmp).as_posix(): unpinned(load(p)) for p in files(tmp)}
        check(sorted(found) == [".github/actions/a/b/action.yaml", ".github/workflows/other.yaml",
                                "dev/actions/example/action.yml"] and all(found.values()),
              f"the check reads a .yaml workflow, a nested action.yaml and a local action outside .github ({found})")


def ps1_refs(script):
    text = script.read_text(encoding="utf-8-sig")
    rels = re.findall(r"\$PSScriptRoot\\([\w.\\-]+)", text) + re.findall(r"Join-Path \$PSScriptRoot '([^']+)'", text)
    out = set()
    for rel in rels:
        resolved = list(script.parent.relative_to(ROOT).parts)
        for part in PureWindowsPath(rel).parts:
            if part == "..":
                resolved.pop()
            else:
                resolved.append(part)
        out.add("/" + "/".join(resolved))
    return out


def called_scripts(job_steps):
    runs = "\n".join(s.get("run", "") for s in job_steps)
    return {"/" + m.replace("\\", "/") for m in SCRIPT_CALL.findall(runs)}


def sparse_problems(doc):
    problems = []
    for job_id, job in doc["jobs"].items():
        checkout = next((s for s in job.get("steps") or [] if s.get("uses", "").startswith("actions/checkout@")), None)
        sparse = ((checkout or {}).get("with") or {}).get("sparse-checkout")
        if sparse is None:
            continue
        listed = {line.strip() for line in sparse.splitlines() if line.strip()}
        if any(p.startswith("/") for p in listed) and checkout["with"].get("sparse-checkout-cone-mode") is not False:
            problems.append(f"{job_id} lists /paths without sparse-checkout-cone-mode: false")
        after = job["steps"][job["steps"].index(checkout) + 1:]
        always = [s for s in after if "if" not in s and not s.get("continue-on-error")]
        if job_id in JOB_SCRIPTS and JOB_SCRIPTS[job_id] not in called_scripts(always):
            problems.append(f"{job_id} does not run {JOB_SCRIPTS[job_id]}")
        needed = called_scripts(after)
        for script in sorted(needed):
            if (ROOT / script.lstrip("/")).is_file():
                needed |= ps1_refs(ROOT / script.lstrip("/"))
        problems += [f"{job_id} needs {p}" for p in sorted(needed - listed)]
        problems += [f"{job_id} lists {p}, which does not exist" for p in sorted(listed)
                     if not (ROOT / p.lstrip("/")).exists()]
    return problems


def test_sparse_checkout():
    monta = load(MONTA)
    check(sparse_problems(monta) == [], f"each sparse checkout of the monta.yml brings what its scripts read "
                                        f"({sparse_problems(monta)})")
    for job, path in (("testa-migracao", "/vozes.json"), ("testa-migracao", "/instalador/testa-migracao.ps1"),
                      ("testa-atualizador", "/instalador/atualizacao/manifesto_de_teste.py"),
                      ("testa-parcial", "/instalador/testa-parcial.ps1")):
        mutant = copy.deepcopy(monta)
        checkout = next(s for s in mutant["jobs"][job]["steps"] if s.get("uses", "").startswith("actions/checkout@"))
        sparse = checkout["with"]["sparse-checkout"]
        checkout["with"]["sparse-checkout"] = "\n".join(line for line in sparse.splitlines() if line.strip() != path)
        check(f"{job} needs {path}" in sparse_problems(mutant), f"the check catches {path} missing in the {job} job")
    mutant = copy.deepcopy(monta)
    job = mutant["jobs"]["testa-migracao"]
    run = next(s for s in job["steps"] if "testa-migracao.ps1" in s.get("run", ""))
    run["run"] = run["run"].replace("instalador\\testa-migracao.ps1", "./instalador/testa-migracao.ps1")
    checkout = job["steps"][0]["with"]
    checkout["sparse-checkout"] = checkout["sparse-checkout"].replace("/vozes.json", "")
    check("testa-migracao needs /vozes.json" in sparse_problems(mutant),
          "the check catches /vozes.json missing with the script called as ./instalador/testa-migracao.ps1")
    run["run"] = run["run"].replace("./instalador/testa-migracao.ps1", "instalador\\testa-migracao.ps1")
    for name, change in (("under if: false", {"if": "${{ false }}"}),
                         ("with continue-on-error", {"continue-on-error": True})):
        disabled = copy.deepcopy(mutant)
        step = next(s for s in disabled["jobs"]["testa-migracao"]["steps"] if "testa-migracao.ps1" in s.get("run", ""))
        step.update(change)
        check("testa-migracao does not run /instalador/testa-migracao.ps1" in sparse_problems(disabled),
              f"the check catches the testa-migracao step {name}")
    conditional = copy.deepcopy(mutant)
    conditional["jobs"]["testa-migracao"]["steps"].append({"if": "matrix.scenario == 'update'", "shell": "powershell",
                                                           "run": "instalador\\testa-parcial.ps1 -Manifesto x"})
    check("testa-migracao needs /instalador/testa-parcial.ps1" in sparse_problems(conditional),
          "the check catches a script that only a conditional step calls, missing in the checkout")
    cone = copy.deepcopy(monta)
    del next(s for s in cone["jobs"]["testa-migracao"]["steps"]
             if s.get("uses", "").startswith("actions/checkout@"))["with"]["sparse-checkout-cone-mode"]
    check("testa-migracao lists /paths without sparse-checkout-cone-mode: false" in sparse_problems(cone),
          "the check catches the testa-migracao checkout without sparse-checkout-cone-mode: false")
    run["run"] = "Write-Host instalador\\testa-migracao.ps1"
    check("testa-migracao does not run /instalador/testa-migracao.ps1" in sparse_problems(mutant),
          "the check catches a step that only prints the script name")
    run["run"] = "instalador\\other.ps1"
    check("testa-migracao does not run /instalador/testa-migracao.ps1" in sparse_problems(mutant),
          "the check fails when the testa-migracao job no longer calls its script in a form it reads")


def version_check_after(job_steps, build, folder, required_if):
    i = next((n for n, s in enumerate(job_steps) if build(s)), None)
    if i is None or job_steps[i].get("if") != required_if:
        return False
    for s in job_steps[i + 1:]:
        m = VERSION_CHECK.fullmatch(s.get("run", "").strip())
        if (m and m.group(1) == folder and s.get("if") == job_steps[i].get("if")
                and s.get("shell") == "powershell" and not s.get("continue-on-error")):
            return True
    return False


def inno_runs(job_steps, required_if):
    calls = [s for s in job_steps if s.get("uses") == INNO]
    return len(calls) == 1 and calls[0].get("if") == required_if and not calls[0].get("continue-on-error")


def built_monta(step):
    return step.get("id") == "congela"


def built_testa(step):
    return "microfone\\apo\\compila.bat teste" in step.get("run", "")


def test_version_resource():
    monta, testa = load(MONTA), load(TESTA)
    for path in ("versao.py", "microfone/apo/version.rc"):
        check("microfone" in testa_tudo.areas([path]), f"a PR that changes only {path} runs the filter job")
    saved = testa_tudo.AREAS
    try:
        testa_tudo.AREAS = {**saved, "microfone": tuple(x for x in saved["microfone"] if x != "versao.py")}
        check("microfone" not in testa_tudo.areas(["versao.py"]), "the check catches versao.py out of the filter area")
    finally:
        testa_tudo.AREAS = saved
    check(version_check_after(monta["jobs"]["monta"]["steps"], built_monta, DLL_FOLDERS["monta"], DLL_IFS["monta"]),
          "the monta job checks the version resource of the DLLs after the build")
    check(version_check_after(testa["jobs"]["microfone"]["steps"], built_testa, DLL_FOLDERS["microfone"],
                              DLL_IFS["microfone"]),
          "the microfone job of the testa.yml checks the version resource of the DLLs it compiled, under the same if")
    mutations = {"without it": None, "with continue-on-error": {"continue-on-error": True},
                 "printing the call": lambda step: {"run": "Write-Host " + step["run"]},
                 "on another folder": {"run": "microfone\\apo\\check_version.ps1 -Folder dist"},
                 "under another if": {"if": "false"}}
    for doc, job, built in ((monta, "monta", built_monta), (testa, "microfone", built_testa)):
        for name, change in mutations.items():
            mutant = copy.deepcopy(doc)
            job_steps = mutant["jobs"][job]["steps"]
            i = next(n for n, s in enumerate(job_steps) if "check_version.ps1" in s.get("run", ""))
            if change is None:
                del job_steps[i]
            else:
                job_steps[i].update(change(job_steps[i]) if callable(change) else change)
            check(not version_check_after(job_steps, built, DLL_FOLDERS[job], DLL_IFS[job]),
                  f"the check catches the {job} job {name}")
    mutant = copy.deepcopy(testa)
    for s in mutant["jobs"]["microfone"]["steps"]:
        if built_testa(s) or "check_version.ps1" in s.get("run", ""):
            s["if"] = "${{ false }}"
    check(not version_check_after(mutant["jobs"]["microfone"]["steps"], built_testa, DLL_FOLDERS["microfone"],
                                  DLL_IFS["microfone"]), "the check catches the build and the check both skipped")
    for doc, job in ((monta, "monta"), (testa, "microfone")):
        check(inno_runs(doc["jobs"][job]["steps"], DLL_IFS[job]),
              f"the {job} job installs the Inno Setup once through {INNO}, under the if of its build")
    mutant = copy.deepcopy(monta)
    next(s for s in mutant["jobs"]["monta"]["steps"] if s.get("uses") == INNO)["if"] = DLL_IFS["microfone"]
    check(not inno_runs(mutant["jobs"]["monta"]["steps"], DLL_IFS["monta"]),
          "the check catches the Inno Setup step of the monta job under the if of the filter job")
    copies = [f"{p.name}:{w}" for p in files() if p.parent.name != "inno-setup"
              for w, s in steps(load(p)) if "innosetup-" in s.get("run", "")]
    check(copies == [], f"the Inno Setup is downloaded only in {INNO} ({copies})")


SHARED_STRINGS = re.compile(r'(?:VALUE|StringStruct\()\s*"(CompanyName|LegalCopyright|ProductName)",\s*"([^"]+)"')


def same_strings_as_the_exe(rc, spec):
    rc = re.sub(r"//[^\n]*|/\*.*?\*/", " ", rc, flags=re.S)
    spec = re.sub(r"#[^\n]*", " ", spec)
    dll, exe = dict(SHARED_STRINGS.findall(rc)), dict(SHARED_STRINGS.findall(spec))
    return (len(dll) == 3 and dll == exe and 'BLOCK "041604B0"' in rc and 'StringTable("041604B0"' in spec
            and re.search(r'VALUE "Translation", 0x0416, 1200\b', rc) is not None
            and re.search(r'VarStruct\("Translation", \[0x0416, 1200\]\)', spec) is not None)


def test_version_strings():
    rc = (ROOT / "microfone" / "apo" / "version.rc").read_text(encoding="utf-8")
    spec = (ROOT / "ritmelli.spec").read_text(encoding="utf-8")
    check(same_strings_as_the_exe(rc, spec), "the DLL version resource has the names and the table of the ritmelli.exe")
    for old, new in (("Behling Informática Ltda.", "Behling Informatica Ltda."), ("041604B0", "040904B0"),
                     ("Free software under the GPLv3", "Free software"), ("0x0416, 1200", "0x0409, 1200"),
                     ('"ProductName", "Ritmelli"', '"ProductName", "Ritmeli"')):
        check(not same_strings_as_the_exe(rc.replace(old, new, 1), spec),
              f"the check catches {old!r} changed in version.rc")
    check(not same_strings_as_the_exe(rc, spec.replace('VarStruct("Translation"', 'VarStruct("Translaton"', 1))
          and not same_strings_as_the_exe(rc.replace('VALUE "Translation"', 'VALUE "Translaton"', 1), spec),
          "the check catches the Translation field misnamed in ritmelli.spec or in version.rc")
    company_rc, company_spec = '      VALUE "CompanyName"', '            StringStruct("CompanyName"'
    check(not same_strings_as_the_exe(rc.replace(company_rc, "      // " + company_rc.strip(), 1), spec)
          and not same_strings_as_the_exe(rc, spec.replace(company_spec, "            # " + company_spec.strip(), 1)),
          "the check catches the CompanyName commented out in version.rc or in ritmelli.spec")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    test_pins()
    test_sparse_checkout()
    test_version_resource()
    test_version_strings()
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
