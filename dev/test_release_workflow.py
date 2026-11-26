"""The release path in the workflows, read as YAML: every action pinned to a commit, the SignPath steps, the
sparse checkouts of the monta.yml jobs and the version resource check of the DLLs. Each check also runs on a mutant
of the real file and has to catch it.

    python dev/test_release_workflow.py
"""
import copy
import re
import sys
from pathlib import Path, PureWindowsPath

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
ACTIONS = ROOT / ".github" / "actions"
MONTA = WORKFLOWS / "monta.yml"
TESTA = WORKFLOWS / "testa.yml"
PINNED = re.compile(r"[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}")
SIGNPATH = "signpath/github-action-submit-signing-request"
INNO = "./.github/actions/inno-setup"
VERSION_CHECK = re.compile(r"(^|\s)microfone\\apo\\check_version\.ps1\s")

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def files():
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(ACTIONS.glob("*/action.yml"))


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
    return [u for _, u in uses(doc) if u.startswith("./") and not (ROOT / u / "action.yml").is_file()]


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


def sparse_problems(doc):
    problems = []
    for job_id, job in doc["jobs"].items():
        checkout = next((s for s in job.get("steps") or [] if s.get("uses", "").startswith("actions/checkout@")), None)
        sparse = ((checkout or {}).get("with") or {}).get("sparse-checkout")
        if sparse is None:
            continue
        listed = {line.strip() for line in sparse.splitlines() if line.strip()}
        runs = " ".join(s.get("run", "") for s in job["steps"])
        needed = {"/" + m.replace("\\", "/") for m in re.findall(r"(instalador\\[\w.-]+\.ps1)", runs)}
        for script in sorted(needed):
            needed |= ps1_refs(ROOT / script.lstrip("/"))
        problems += [f"{job_id} needs {p}" for p in sorted(needed - listed)]
        problems += [f"{job_id} lists {p}, which does not exist" for p in sorted(listed) if not (ROOT / p.lstrip("/")).exists()]
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


def version_check_after(job_steps, build):
    i = next((n for n, s in enumerate(job_steps) if build(s)), None)
    if i is None:
        return False
    return any(VERSION_CHECK.search(s.get("run", "") + " ") for s in job_steps[i + 1:]
               if s.get("if") == job_steps[i].get("if"))


def built_monta(step):
    return step.get("id") == "congela"


def built_testa(step):
    return "microfone\\apo\\compila.bat teste" in step.get("run", "")


def test_version_resource():
    monta, testa = load(MONTA), load(TESTA)
    check(version_check_after(monta["jobs"]["monta"]["steps"], built_monta),
          "the monta job checks the version resource of the DLLs after the build")
    check(version_check_after(testa["jobs"]["microfone"]["steps"], built_testa),
          "the microfone job of the testa.yml checks the version resource of the DLLs it compiled, under the same if")
    for doc, job, built in ((monta, "monta", built_monta), (testa, "microfone", built_testa)):
        mutant = copy.deepcopy(doc)
        mutant["jobs"][job]["steps"] = [s for s in mutant["jobs"][job]["steps"]
                                        if not VERSION_CHECK.search(s.get("run", "") + " ")]
        check(not version_check_after(mutant["jobs"][job]["steps"], built), f"the check catches the {job} job without it")
    for doc, job in ((monta, "monta"), (testa, "microfone")):
        names = [s.get("uses") for s in doc["jobs"][job]["steps"]]
        check(INNO in names, f"the {job} job installs the Inno Setup through {INNO}")
    copies = [f"{p.name}:{w}" for p in files() if p.parent.name != "inno-setup"
              for w, s in steps(load(p)) if "innosetup-" in s.get("run", "")]
    check(copies == [], f"the Inno Setup is downloaded only in {INNO} ({copies})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    test_pins()
    test_sparse_checkout()
    test_version_resource()
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
