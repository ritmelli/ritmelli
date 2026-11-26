import argparse
import contextlib
import copy
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

from fake_gh import bash, run_step
from workflow_yaml import YamlError, find_step, job_steps, load, loads, workflows

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "testa.yml"
TESTA = ".github/workflows/testa.yml"
ACTION = ROOT / ".github" / "actions" / "python" / "action.yml"
TRAVAS = ROOT / "instalador" / "travas.txt"
DEV_TRAVAS = ROOT / "dev" / "travas.txt"
REQUIREMENTS = (ROOT / "requirements.txt", ROOT / "requirements-dev.txt")
ALWAYS_NEWEST = {"yt-dlp"}
REQUIRED_NAME = "Testa o PR"
TRIGGERS = {"pull_request": {"types": ["opened", "synchronize", "reopened"]}, "push": {"branches": ["main"]},
            "merge_group": None}
HEAD = "c" * 40
PR_HEAD = "b" * 40
BUILD_URL = "https://example.invalid/monta/passed"
QUEUE_URL = "https://example.invalid/queue/passed"
RUNS = [{"head_sha": HEAD, "conclusion": "failure", "html_url": "https://example.invalid/queue/failed"},
        {"head_sha": "d" * 40, "conclusion": "success", "html_url": "https://example.invalid/queue/other-commit"},
        {"head_sha": HEAD, "conclusion": "success", "html_url": QUEUE_URL}]
NEEDS = ("ETIQUETAS", "TESTES", "BENCH", "CAPTURE", "MICROFONE", "TELA", "COMPARA")

_spec = importlib.util.spec_from_file_location("testa_tudo", ROOT / "dev" / "testa_tudo.py")
testa_tudo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(testa_tudo)

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def test_reader():
    sample = """# a comment
name: Sample  # a trailing comment
on:
  pull_request:
    types: [opened, 'a b', "c#d"]
  merge_group:
jobs:
  one:
    if: ${{ !cancelled() && x != 'y' }}
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - name: Run
        run: |
          echo "a: b # not a comment"

            indented
      - plain
key: 'it''s'
"""
    check(loads(sample) == {
        "name": "Sample", "on": {"pull_request": {"types": ["opened", "a b", "c#d"]}, "merge_group": None},
        "jobs": {"one": {"if": "${{ !cancelled() && x != 'y' }}", "steps": [
            {"uses": "actions/checkout@v7", "with": {"fetch-depth": "0"}},
            {"name": "Run", "run": 'echo "a: b # not a comment"\n\n  indented\n'}, "plain"]}},
        "key": "it's"}, "the reader reads the constructs the workflows use")
    for why, text in (("a repeated key", "a: 1\na: 2\n"), ("an anchor", "a: &x 1\n"), ("an alias", "a: *x\n"),
                      ("a tag", "a: !!str 1\n"), ("a flow mapping", "a: {b: 1}\n"), ("a folded scalar", "a: >\n  b\n"),
                      ("a plain scalar on two lines", "a: b\n  c\n"), ("a tab", "a:\n\tb: 1\n"),
                      ("two documents", "a: 1\n---\nb: 2\n"), ("a plain scalar with ': '", "a: b: c\n"),
                      ("a nested flow sequence", "a: [b, [c]]\n"), ("an unclosed quote", "a: 'b\n")):
        try:
            loads(text)
            raised = False
        except YamlError:
            raised = True
        check(raised, f"the reader refuses {why}")


def required_check_failures(flows):
    """What lets the required check hide or skip: the triggers of the testa.yml other than TRIGGERS, a job named
    "Testa o PR" other than the testa-o-pr of the testa.yml, a condition on that job other than always(), a step of it
    with an if: (only the Cancelada, last, has one), a continue-on-error, a job of the testa.yml it does not need or
    whose result its Verdict does not read."""
    out = []
    testa = flows.get(TESTA) or {}
    if testa.get("on") != TRIGGERS:
        out.append(f"the triggers of the testa.yml are {testa.get('on')}, not {TRIGGERS}")
    named = [(path, job_id) for path, flow in flows.items() for job_id, job in (flow.get("jobs") or {}).items()
             if job.get("name") == REQUIRED_NAME]
    if named != [(TESTA, "testa-o-pr")]:
        out.append(f"the jobs named \"{REQUIRED_NAME}\" are {named}, not only the testa-o-pr of the testa.yml")
    jobs = testa.get("jobs") or {}
    required = jobs.get("testa-o-pr") or {}
    if required.get("if") != "${{ always() }}":
        out.append(f"the required job runs with if: {required.get('if')}, not ${{{{ always() }}}}")
    steps = job_steps(required)
    conditioned = [(s.get("name"), s.get("if")) for s in steps if "if" in s]
    if conditioned != [("Cancelada", "${{ cancelled() }}")] or steps[-1:] != [s for s in steps if "if" in s]:
        out.append(f"the steps of the required job with an if: are {conditioned}, not only the Cancelada, last")
    if any("continue-on-error" in x for x in [required, *steps]):
        out.append("the required job or a step of it has continue-on-error")
    if "defaults" in testa or "defaults" in required or any("shell" in s for s in steps):
        out.append("the required job runs its steps in a shell of its own (defaults or shell:)")
    verdict = find_step(required, "Verdict") or {}
    if steps[:1] != [verdict] or len(steps) != 2:
        out.append(f"the required job is not the Verdict and the Cancelada ({[s.get('name') for s in steps]})")
    others = set(jobs) - {"testa-o-pr"}
    if set(required.get("needs") or []) != others:
        out.append(f"the required job needs {required.get('needs')}, not every other job ({sorted(others)})")
    env = verdict.get("env") or {}
    unread = sorted(j for j in others if env.get(f"S_{j.upper()}") != f"${{{{ needs.{j}.result }}}}")
    if unread:
        out.append(f"the Verdict does not read the result of {unread} in S_<JOB>")
    if "${{" in (verdict.get("run") or ""):
        out.append("a ${{ }} inside the Verdict run block")
    return out


def mutated(flows, change):
    flows = copy.deepcopy(flows)
    change(flows)
    return flows


def step_of(flows, job, name):
    return find_step(flows[TESTA]["jobs"][job], name)


def test_required_check(flows, text):
    found = required_check_failures(flows)
    check(found == [], f"the required check runs on every PR, queue entry and push and cannot be skipped ({found})")
    verdict_if = text.replace("      - name: Verdict\n",
                              "      - name: Verdict\n        if: ${{ !cancelled() && github.event_name != 'merge_group' }}\n")
    check(verdict_if != text and required_check_failures({**flows, TESTA: loads(verdict_if)}) != [],
          "the mutant with an if: on the Verdict step fails")
    for why, change in (
            ("paths-ignore on the pull_request", lambda f: f[TESTA]["on"]["pull_request"].update({"paths-ignore": ["docs/**"]})),
            ("paths on the pull_request", lambda f: f[TESTA]["on"]["pull_request"].update({"paths": ["dev/**"]})),
            ("branches on the pull_request", lambda f: f[TESTA]["on"]["pull_request"].update({"branches": ["other"]})),
            ("edited in the pull_request types", lambda f: f[TESTA]["on"]["pull_request"]["types"].append("edited")),
            ("branches on the merge_group", lambda f: f[TESTA]["on"].update({"merge_group": {"branches": ["other"]}})),
            ("another branch on the push", lambda f: f[TESTA]["on"]["push"].update({"branches": ["other"]})),
            ("a pull_request_target trigger", lambda f: f[TESTA]["on"].update({"pull_request_target": None})),
            ("the Etiquetas job named Testa o PR", lambda f: f[TESTA]["jobs"]["etiquetas"].update({"name": REQUIRED_NAME})),
            ("a job of another workflow named Testa o PR",
             lambda f: f[".github/workflows/dequeue-on-label.yml"]["jobs"]["dequeue"].update({"name": REQUIRED_NAME})),
            ("the required job renamed", lambda f: f[TESTA]["jobs"]["testa-o-pr"].update({"name": "Testa"})),
            ("!cancelled() on the required job", lambda f: f[TESTA]["jobs"]["testa-o-pr"].update({"if": "${{ !cancelled() }}"})),
            ("an if: on the Verdict", lambda f: step_of(f, "testa-o-pr", "Verdict").update({"if": "always()"})),
            ("a second step before the Verdict",
             lambda f: f[TESTA]["jobs"]["testa-o-pr"]["steps"].insert(0, {"name": "Needs owner", "if": "success()", "run": "true\n"})),
            ("continue-on-error on the Verdict", lambda f: step_of(f, "testa-o-pr", "Verdict").update({"continue-on-error": "true"})),
            ("a job the required job does not need", lambda f: f[TESTA]["jobs"].update({"extra": {"runs-on": "x"}})),
            ("the result of the etiquetas job not read", lambda f: step_of(f, "testa-o-pr", "Verdict")["env"].pop("S_ETIQUETAS")),
            ("shell: cat {0} on the Verdict", lambda f: step_of(f, "testa-o-pr", "Verdict").update({"shell": "cat {0}"})),
            ("shell: cat {0} on the Cancelada", lambda f: step_of(f, "testa-o-pr", "Cancelada").update({"shell": "cat {0}"})),
            ("a default shell on the required job",
             lambda f: f[TESTA]["jobs"]["testa-o-pr"].update({"defaults": {"run": {"shell": "cat {0}"}}})),
            ("a default shell on the testa.yml", lambda f: f[TESTA].update({"defaults": {"run": {"shell": "cat {0}"}}})),
    ):
        check(required_check_failures(mutated(flows, change)) != [], f"the mutant with {why} fails")
    with tempfile.TemporaryDirectory(prefix="ritmelli-flows-") as tmp:
        folder = Path(tmp) / ".github" / "workflows"
        folder.mkdir(parents=True)
        (folder / "testa.yml").write_text(text, encoding="utf-8")
        (folder / "duplicate.yaml").write_text("on: push\njobs:\n  again:\n    name: Testa o PR\n    runs-on: x\n",
                                               encoding="utf-8")
        found = required_check_failures(workflows(tmp))
        check(any("duplicate.yaml" in f for f in found),
              f"a job named Testa o PR in a .yaml workflow fails ({found})")


def test_modes(flows):
    found = testa_tudo.mode_failures(flows)
    check(found == [], f"every mode of REQUIRED_MODES runs in its job and step, with its condition ({found})")
    for mode, (job, _, step, _, _) in testa_tudo.REQUIRED_MODES.items():
        for why, change in (
                ("if: false on its step", lambda s: s.update({"if": "false"})),
                ("continue-on-error on its step", lambda s: s.update({"continue-on-error": "true"})),
                ("another command in its step", lambda s: s.update({"run": s["run"].replace(f" {mode}", " --areas")})),
                ("--help after its command", lambda s: s.update({"run": s["run"].replace(f" {mode}", f" {mode} --help")})),
                ("its run under if ($false)", lambda s: s.update({"run": "if ($false) {\n" + s["run"] + "}\n"})),
                ("an exit 0 after its run", lambda s: s.update({"run": s["run"] + "exit 0\n"})),
                ("its step renamed", lambda s: s.update({"name": s["name"] + " (renamed)"}))):
            found = testa_tudo.mode_failures(mutated(flows, lambda f: change(step_of(f, job, step))))
            check(found != [], f"the mutant with {why} fails the {mode} mode")
        found = testa_tudo.mode_failures(mutated(flows, lambda f: f[TESTA]["jobs"][job].update({"if": "false"})))
        check(found != [], f"the mutant with if: false on the {job} job fails the {mode} mode")
        found = testa_tudo.mode_failures(mutated(flows, lambda f: f[TESTA]["jobs"]["testa-o-pr"]["needs"].remove(job)))
        check(found != [], f"the mutant where the required job does not need {job} fails the {mode} mode")
    for job, step, why, change in (
            ("compara", "O PR mexe na tela?", "the id of the areas step removed", lambda s: s.pop("id")),
            ("compara", "Capture key", "the id of the capture key step removed", lambda s: s.pop("id")),
            ("compara", "compara", "the compara base taken from the event", lambda s: s["env"].update({"BASE_SHA": "${{ env.BASE }}"})),
            ("tela", "fitcheck", "the id of the fitcheck step removed", lambda s: s.pop("id")),
            ("tela", "O PR mexe na tela?", "the id of the areas step changed",
             lambda s: s.update({"id": "areas-later"})),
            ("compara", "O PR mexe na tela?", "if: false on the areas step", lambda s: s.update({"if": "false"})),
            ("compara", "O PR mexe na tela?", "an exit 0 first in the areas step",
             lambda s: s.update({"run": "exit 0\n" + s["run"]})),
            ("compara", "Capture key", "continue-on-error on the capture key step",
             lambda s: s.update({"continue-on-error": "true"})),
            ("microfone", "O PR mexe no filtro?", "if: false on the filter areas step", lambda s: s.update({"if": "false"})),
            ("tela", "O PR mexe na tela?", "another env on the areas step", lambda s: s.update({"env": {"ETIQUETAS": "[]"}})),
            ("testes", "ruff", "if: false on the ruff step", lambda s: s.update({"if": "false"})),
            ("compara", "compara", "shell: cmd on the compara step", lambda s: s.update({"shell": "cmd"})),
            ("compara", "O PR mexe na tela?", "BASE: HEAD on the areas step",
             lambda s: s.update({"env": {**s["env"], "BASE": "HEAD"}}))):
        found = testa_tudo.mode_failures(mutated(flows, lambda f: change(step_of(f, job, step))))
        check(found != [], f"the mutant with {why} ({job} job) fails")
    for why, change in (("BASE: HEAD on the testa.yml", lambda f: f[TESTA]["env"].update({"BASE": "HEAD"})),
                        ("BASE: HEAD on the tela job", lambda f: f[TESTA]["jobs"]["tela"].update({"env": {"BASE": "HEAD"}})),
                        ("BASE: HEAD on a step of the tela job",
                         lambda f: f[TESTA]["jobs"]["tela"]["steps"][0].update({"env": {"BASE": "HEAD"}})),
                        ("a default shell on the testa.yml", lambda f: f[TESTA].update({"defaults": {"run": {"shell": "cmd"}}})),
                        ("a default shell on the microfone job",
                         lambda f: f[TESTA]["jobs"]["microfone"].update({"defaults": {"run": {"shell": "cmd"}}}))):
        check(testa_tudo.mode_failures(mutated(flows, change)) != [], f"the mutant with {why} fails the modes")
    monta = ".github/workflows/monta.yml"
    for rel, (job, _, step, _, _) in testa_tudo.PS1_TESTS.items():
        for why, change in (("if: false on its step", lambda s: s.update({"if": "false"})),
                            ("shell: cmd on its step", lambda s: s.update({"shell": "cmd"})),
                            ("if: false on its job", None)):
            found = testa_tudo.ps1_failures(mutated(flows, lambda f: (
                change(find_step(f[monta]["jobs"][job], step)) if change else f[monta]["jobs"][job].update({"if": "false"}))))
            check(found[rel] != [], f"the mutant with {why} fails the {rel} test")


def test_shape(flows):
    jobs = flows[TESTA]["jobs"]
    for job in ("testes", "bench", "capture", "microfone", "tela"):
        check(jobs.get(job, {}).get("if") == "github.event_name != 'push'", f"the {job} job skips on the push to main")
    for job in ("etiquetas", "compara"):
        check(job in jobs and "if" not in jobs[job], f"the {job} job runs on the push to main")
    saves = [s for s in job_steps(jobs["compara"]) if "steps.compara.outputs.head_cache == 'true'" in (s.get("if") or "")]
    check(len(saves) == 2, f"the head capture is moved and saved to the cache when the step says head_cache ({len(saves)})")
    check(not any(re.search(r"\bsleep\b", s.get("run") or "") for s in job_steps(jobs["testa-o-pr"])),
          "the Testa o PR never sleeps")
    capture_files = ", ".join(f"'{f}'" for f in testa_tudo.CAPTURA)
    keys = [re.search(r"hashFiles\(([^)]*)\)", (s.get("with") or {}).get("key", "")) for s in job_steps(jobs["compara"])
            if (s.get("uses") or "").startswith("actions/cache/")]
    keys = [k.group(1) for k in keys if k]
    check(len(keys) == 2 and all(k == capture_files for k in keys),
          f"both compara cache keys hash the CAPTURA files of dev/testa_tudo.py ({len(keys)} keys)")
    action = load(ACTION)
    steps = job_steps(action["runs"])
    check(any("'instalador/travas.txt'" in (s.get("with") or {}).get("key", "") for s in steps
              if (s.get("with") or {}).get("key", "").startswith("libs-")),
          "the libraries cache key hashes the instalador/travas.txt")
    check(any(re.search(r"pip install .*-r \$env:REQUIREMENTS -c instalador/travas.txt", s.get("run") or "") for s in steps),
          "the libraries are installed with the instalador/travas.txt as constraints")


def run_summary(block, event, states, comment_fails=False, runs=RUNS, queue_fails=False, monta="false",
                build_runs=(), build_fails=False, pr_head=PR_HEAD, fork=False):
    env = {"GITHUB_EVENT_NAME": event, "GH_TOKEN": "x", "REPO": "ritmelli/ritmelli",
           "PR": "7" if event == "pull_request" else "", "HEAD": HEAD, "RUN_ID": "1", "ATTEMPT": "1",
           "EXECUCAO": "https://example.invalid/run",
           "DO_REPO": "true" if event == "pull_request" and not fork else "false",
           "LABELS_PR": "" if event == "push" else "7", "LABELS": "[]", "MUDARAM": "0",
           "MONTA": "" if event == "push" else monta, "PR_HEAD": PR_HEAD if event == "pull_request" else ""}
    env.update({f"S_{n}": s for n, s in zip(NEEDS, states)})
    env.update({f"R_{n}": f"resumo {n}" for n in NEEDS[1:]})
    ran = run_step(block, env, {"labels": [], "comment_fails": comment_fails, "runs": runs, "queue_fails": queue_fails,
                                "build_runs": list(build_runs), "build_fails": build_fails, "pr_head": pr_head})
    return ran.code, ran.out, ran.summary, [" ".join(["gh", *c]) for c in ran.calls]


def test_build_gate(block):
    ok = ["success"] * 7
    green = {"head_sha": PR_HEAD, "conclusion": "success", "html_url": BUILD_URL}
    other = {"head_sha": "e" * 40, "conclusion": "success", "html_url": "https://example.invalid/monta/other-commit"}
    red = {"head_sha": PR_HEAD, "conclusion": "failure", "html_url": "https://example.invalid/monta/failed"}

    def builds(calls):
        return [c for c in calls if "actions/workflows/monta.yml/runs" in c]

    code, out, summary, calls = run_summary(block, "pull_request", ok)
    check(code == 0 and not builds(calls), f"a PR that does not change the build passes without asking for monta.yml "
                                           f"(exit {code})")
    for event in ("pull_request", "merge_group"):
        code, out, summary, calls = run_summary(block, event, ok, monta="true", build_runs=[green])
        check(code == 0 and BUILD_URL in summary and len(builds(calls)) == 1 and f"head_sha={PR_HEAD}" in builds(calls)[0],
              f"in a {event}, a PR that changes the build passes with the passed monta.yml run on the PR head "
              f"(exit {code})")
        code, out, summary, calls = run_summary(block, event, ok, monta="true", build_runs=[other, red])
        check(code != 0 and "no passed Monta o instalador run" in summary and "other-commit" not in summary,
              f"in a {event}, a PR that changes the build fails with monta.yml passed only on another commit or "
              f"failed on its head (exit {code})")
        code, out, summary, calls = run_summary(block, event, ok, monta="true", build_fails=True)
        check(code != 0 and "the query of the Monta o instalador runs failed" in summary,
              f"in a {event}, a failed monta.yml query fails the check and says so (exit {code})")
        code, out, summary, calls = run_summary(block, event, ok, monta="")
        check(code != 0 and "did not say whether the PR changes the build" in summary,
              f"in a {event}, an empty build answer from the filter job fails the check (exit {code})")
    code, out, summary, calls = run_summary(block, "pull_request", ok, monta="true", fork=True)
    check(code != 0 and "it comes from a fork, so a maintainer pushes this commit to a branch of ritmelli/ritmelli"
          in summary, f"a fork PR that changes the build fails and says how a maintainer gets the run (exit {code})")
    code, out, summary, calls = run_summary(block, "pull_request", ok, monta="true", fork=True, build_runs=[green])
    check(code == 0 and BUILD_URL in summary,
          f"a fork PR that changes the build passes once the run on its head is in the repository (exit {code})")
    code, out, summary, calls = run_summary(block, "merge_group", ok, monta="true", build_runs=[green], pr_head=None)
    check(code != 0 and "the head of PR 7 did not come" in summary and not builds(calls),
          f"in a merge_group, a PR head that does not come fails the check (exit {code})")
    code, out, summary, calls = run_summary(block, "push", ["success"] + ["skipped"] * 5 + ["success"])
    check(code == 0 and not builds(calls), f"the push to main does not ask for monta.yml (exit {code})")


def test_build_base_in_queue():
    with tempfile.TemporaryDirectory(prefix="ritmelli-queue-") as tmp:
        repo = Path(tmp)

        def git(*args):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=repo,
                                  capture_output=True, text=True, check=True).stdout.strip()

        def commit(path, text):
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(text, encoding="utf-8")
            git("add", "-A")
            git("commit", "-q", "-m", path)
            return git("rev-parse", "HEAD")

        git("init", "-q")
        main = commit("README.md", "main\n")
        ahead = commit("instalador/ritmelli.iss", "the PR ahead in the queue\n")
        commit("dev/notes.txt", "this PR\n")
        only_ahead = testa_tudo.touches_build(testa_tudo.changed_files(main, cwd=repo))
        mine = testa_tudo.touches_build(testa_tudo.changed_files(ahead, cwd=repo))
        check(only_ahead and not mine, "in a queue entry, only the base before its own PR keeps a build change of the "
                                       "PR ahead out of its monta answer")
        git("reset", "-q", "--hard", ahead)
        git("rm", "-q", "instalador/ritmelli.iss")
        git("commit", "-q", "-m", "this PR undoes the PR ahead")
        cumulative = testa_tudo.touches_build(testa_tudo.changed_files(main, cwd=repo))
        mine = testa_tudo.touches_build(testa_tudo.changed_files(ahead, cwd=repo))
        check(mine and not cumulative, "in a queue entry, a PR that undoes the build change of the PR ahead counts as "
                                       "a build change against the base before its own PR")


def areas_output(changes, build_base=None):
    calls = []

    def fake_executa(cmd, **kw):
        calls.append(cmd)
        return 0, "".join(f"{f}\0" for f in changes[cmd[-2]])

    with tempfile.TemporaryDirectory() as d, mock.patch.object(testa_tudo, "executa", fake_executa), \
            mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(Path(d) / "out"), "ETIQUETAS": "[]"}), \
            contextlib.redirect_stdout(io.StringIO()):
        code = testa_tudo.diz_areas(argparse.Namespace(areas="base", build_base=build_base))
        written = (Path(d) / "out").read_text(encoding="utf-8").splitlines() if code == 0 else []
    return code, written, calls


def test_areas_output():
    code, written, calls = areas_output({"base": ["instalador/ritmelli.iss", "server.py"]})
    check(code == 0 and "monta=true" in written and "tela=true" in written,
          f"the --areas writes monta=true for a build change, with the other areas ({written})")
    check(bool(calls) and all("--no-renames" in c for c in calls),
          "the --areas diffs without renames: a build file renamed out of the build paths still counts")
    code, written, calls = areas_output({"base": ["server.py"]})
    check(code == 0 and "monta=false" in written, f"the --areas writes monta=false otherwise ({written})")
    code, written, calls = areas_output({"base": ["instalador/ritmelli.iss", "server.py"], "before": ["server.py"]},
                                        build_base="before")
    check(code == 0 and "monta=false" in written and "tela=true" in written and [c[-2] for c in calls] == ["base", "before"],
          f"with --build-base, the monta answer comes from its own diff and the other areas from the base ({written})")


def test_build_wiring(flows):
    def problems(f):
        jobs = f[TESTA]["jobs"]
        verdict = find_step(jobs["testa-o-pr"], "Verdict") or {}
        areas = find_step(jobs["microfone"], "O PR mexe no filtro?") or {}
        found = []
        if jobs["microfone"].get("needs") not in ("etiquetas", ["etiquetas"]):
            found.append("the filter job does not need the etiquetas job, whose queue_base it reads")
        if (jobs["microfone"].get("outputs") or {}).get("monta") != "${{ steps.areas.outputs.monta }}":
            found.append("the filter job does not output monta from its areas step")
        if (verdict.get("env") or {}).get("MONTA") != "${{ needs.microfone.outputs.monta }}":
            found.append("the Verdict does not read monta from the filter job")
        if (verdict.get("env") or {}).get("PR_HEAD") != "${{ github.event.pull_request.head.sha }}":
            found.append("the Verdict does not read the PR head")
        if (areas.get("id") != "areas" or "if" in areas or areas.get("run") != testa_tudo.BUILD_AREAS_RUN
                or areas.get("env") != testa_tudo.BUILD_BASE_ENV):
            found.append("the areas step of the filter job does not run the --areas unconditionally")
        return found

    check(problems(flows) == [], f"the build answer goes from the --areas of the filter job to the Verdict "
                                 f"({problems(flows)})")
    for name, change in (
            ("the filter job output", lambda f: f[TESTA]["jobs"]["microfone"]["outputs"].pop("monta")),
            ("the filter job needs", lambda f: f[TESTA]["jobs"]["microfone"].pop("needs")),
            ("the Verdict env", lambda f: find_step(f[TESTA]["jobs"]["testa-o-pr"], "Verdict")["env"].update(
                MONTA="${{ needs.testes.outputs.monta }}")),
            ("the PR head", lambda f: find_step(f[TESTA]["jobs"]["testa-o-pr"], "Verdict")["env"].pop("PR_HEAD")),
            ("the areas step under an if", lambda f: find_step(f[TESTA]["jobs"]["microfone"],
                                                               "O PR mexe no filtro?").update({"if": "false"})),
            ("the build base of the queue", lambda f: find_step(f[TESTA]["jobs"]["microfone"],
                                                                "O PR mexe no filtro?")["env"].update(
                BUILD_BASE="${{ github.event.merge_group.base_sha || github.event.pull_request.base.sha }}"))):
        check(problems(mutated(flows, change)) != [], f"the wiring check catches {name} changed")
    for path in ("instalador/ritmelli.iss", "atualizador.py", "atualizacao.py", "migra.py", "pastas.py",
                 "microfone/microfone.py", "microfone/apo/version.rc", "ritmelli.spec", ".github/workflows/monta.yml",
                 ".github/actions/inno-setup/action.yml"):
        check(testa_tudo.touches_build([path]), f"a change to {path} counts as a build change")
    for path in ("dev/testa_tudo.py", ".github/workflows/testa.yml", "server.py", "microfone/injeta.py", "atualiza.txt"):
        check(not testa_tudo.touches_build([path]), f"a change to {path} alone is not a build change")


def test_summary_block(flows):
    check(bool(bash()), "the bash of Git for Windows (or bash on the PATH outside Windows) runs the block")
    if not bash():
        return
    block = step_of(flows, "testa-o-pr", "Verdict")["run"]
    ok = ["success"] * 7
    on_push = ["success"] + ["skipped"] * 5 + ["success"]

    code, out, summary, calls = run_summary(block, "pull_request", ok)
    comments = [c for c in calls if c.startswith("gh pr comment")]
    check(code == 0 and len(comments) == 1 and "tudo passou" in summary and "| Banca | Captura |" in summary,
          f"a PR whose jobs pass gets one comment, with the Banca and Captura columns, and passes (exit {code})")

    code, out, summary, calls = run_summary(block, "pull_request", ok, comment_fails=True)
    comments = [c for c in calls if c.startswith("gh pr comment")]
    check(code != 0 and len(comments) == 1 and "GitHub did not confirm the summary comment" in out
          and "não confirmou o comentário do resumo no PR" in summary,
          f"a comment GitHub does not confirm fails the check with that reason, tried once (exit {code})")

    code, out, summary, calls = run_summary(block, "push", on_push)
    queries = [c for c in calls if "event=merge_group" in c]
    check(code == 0 and summary.count("⏭️ neste push") == 5 and QUEUE_URL in summary and "queue/failed" not in summary
          and "other-commit" not in summary and len(queries) == 1
          and not any(c.startswith("gh pr comment") for c in calls),
          f"on the push, the five skipped jobs pass with the passed queue run of that very commit, asked once "
          f"(exit {code}, {len(queries)} queries)")

    code, out, summary, calls = run_summary(block, "push", on_push, runs=RUNS[:2])
    check(code != 0 and "nenhuma execução aprovada da fila apareceu" in summary,
          f"on the push, with no passed queue run on the commit, the check fails (exit {code})")

    code, out, summary, calls = run_summary(block, "push", on_push, queue_fails=True)
    check(code != 0 and "a consulta das execuções da fila neste commit falhou" in summary
          and "nenhuma execução aprovada" not in summary,
          f"on the push, a failed query says so, and not that no queue run passed (exit {code})")

    code, out, summary, calls = run_summary(block, "push", ["success"] + ["skipped"] * 6)
    check(code != 0, f"on the push, a skipped Compara (no capture) fails the check even with the queue run (exit {code})")

    for i, name in enumerate(NEEDS):
        code, out, summary, calls = run_summary(block, "pull_request", ok[:i] + ["failure"] + ok[i + 1:])
        check(code != 0, f"on a PR, a failed {name.lower()} job fails the check (exit {code})")
    code, out, summary, calls = run_summary(block, "pull_request", ok[:1] + ["skipped"] + ok[2:])
    check(code != 0 and not any("event=merge_group" in c for c in calls),
          f"on a PR, a skipped testes job fails the check, and the queue is not asked (exit {code})")
    for event in ("pull_request", "merge_group"):
        code, out, summary, calls = run_summary(block, event, ["skipped"] + ok[1:])
        check(code != 0 and not any("event=merge_group" in c for c in calls),
              f"in a {event}, a skipped etiquetas job fails the check, and the queue is not asked (exit {code})")

    code, out, summary, calls = run_summary(block, "pull_request", ["cancelled"] + ["success"] * 6)
    check(code != 0 and not any(c.startswith("gh pr comment") for c in calls) and "cancelada" in summary,
          f"a cancelled etiquetas job fails the check and leaves the PR comment as it was (exit {code})")
    code, out, summary, calls = run_summary(block, "pull_request", ["success", "success", "cancelled"] + ["success"] * 4)
    check(code != 0 and not any(c.startswith("gh pr comment") for c in calls) and "cancelada" in summary,
          f"a cancelled job fails the check and leaves the PR comment as it was (exit {code})")
    test_build_gate(block)
    cancelled = step_of(flows, "testa-o-pr", "Cancelada")["run"]
    ran = run_step(cancelled, {})
    check(ran.code != 0 and not ran.calls and "cancelada" in ran.summary,
          f"the Cancelada step, which runs when the Verdict is skipped, fails the check (exit {ran.code})")
    ran = run_step(cancelled.replace("exit 1", "exit 0"), {})
    check(ran.code == 0, f"the mutant Cancelada with exit 0 passes, so the case above catches it (exit {ran.code})")


def requirement(line):
    spec, _, marker = line.split("#")[0].partition(";")
    spec = spec.strip()
    m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)", spec)
    if not m:
        return None, False
    version = m.group(3).replace(" ", "")
    on_ci = not marker.strip() or re.fullmatch(r"\s*sys_platform\s*==\s*[\"']win32[\"']\s*", marker) is not None
    return re.sub(r"[-_.]+", "-", m.group(1)).lower(), on_ci and bool(re.fullmatch(r"==[^=*,<>!~]+", version))


def test_unpinned():
    def pins(travas):
        return {name for name, exact in map(requirement, travas.read_text(encoding="utf-8").splitlines()) if exact}

    app, dev_only = pins(TRAVAS), pins(DEV_TRAVAS)
    unpinned = set()
    for req, pinned in zip(REQUIREMENTS, (app, app | dev_only)):
        for line in req.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("-"):
                continue
            name, exact = requirement(line)
            if name and not exact and name not in pinned:
                unpinned.add(name)
    check(unpinned == ALWAYS_NEWEST,
          f"every library the CI installs has an exact version (requirements.txt by instalador/travas.txt or its own "
          f"line, requirements-dev.txt by dev/travas.txt too), except yt-dlp, always the newest (unpinned: "
          f"{sorted(unpinned)})")
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    check("-c dev/travas.txt" in dev, "requirements-dev.txt takes dev/travas.txt as constraints")
    steps = job_steps(load(ACTION)["runs"])
    saved = next((i for i, s in enumerate(steps) if (s.get("uses") or "").startswith("actions/cache/save@")), None)
    newest = [i for i, s in enumerate(steps) if re.search(r'pip install .*--upgrade "yt-dlp\[default\]" yt-dlp-ejs ', s.get("run") or "")]
    check(saved is not None and len(newest) == 1 and newest[0] > saved and "if" not in steps[newest[0]],
          f"the python action installs the newest yt-dlp and yt-dlp-ejs on every run, after the cache is saved and on a "
          f"hit too (cache save at {saved}, yt-dlp at {newest})")
    check(any("'dev/travas.txt'" in (s.get("with") or {}).get("key", "") for s in steps
              if (s.get("with") or {}).get("key", "").startswith("libs-")),
          "the libraries cache key hashes the dev/travas.txt")


def test_bench_order():
    with tempfile.TemporaryDirectory(prefix="ritmelli-ordem-") as tmp:
        tmp = Path(tmp)
        names = ["fast_a", "fast_b", "fast_c", "long_x", "long_y"]
        for n in names:
            (tmp / f"{n}.py").write_text("print('ok')\n", encoding="utf-8")
        tests = [str(tmp / f"{n}.py") for n in names]
        events, real, saved = [], testa_tudo.executa, testa_tudo.LONG_TESTS

        def recorded(cmd, *args, **kw):
            name = Path(cmd[-1]).stem
            events.append(("start", name, threading.get_ident()))
            try:
                return real(cmd, *args, **kw)
            finally:
                events.append(("end", name, threading.get_ident()))

        testa_tudo.LONG_TESTS, testa_tudo.executa = {"x": tests[3], "y": tests[4]}, recorded
        try:
            with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet):
                testa_tudo.roda("order", tests, completo=False, jobs=4)
        finally:
            testa_tudo.LONG_TESTS, testa_tudo.executa = saved, real
        order = [(kind, n) for kind, n, _ in events]
        threads = {n: t for kind, n, t in events if kind == "start"}
        last_fast = max(order.index(("end", n)) for n in names[:3])
        check(order.index(("start", "long_x")) > last_fast
              and order[-4:] == [("start", "long_x"), ("end", "long_x"), ("start", "long_y"), ("end", "long_y")]
              and threads["long_x"] == threads["long_y"] == threading.get_ident(),
              "the plain run takes the LONG_TESTS one by one, after the others, on the calling thread")


def test_without_destination(flows):
    with tempfile.TemporaryDirectory(prefix="ritmelli-root-") as tmp:
        root = Path(tmp)
        files = {
            "dev/test_lost.py": "print('a new test in no list')\n",
            "dev/testa_perdido.py": "print('an old-style test in no list')\n",
            "dev/test_by_hand.py": "# manual: python dev\\test_by_hand.py precisa de um microfone\n",
            "dev/tester.py": "print('a tool')\n",
            "dev/testa_tudo.py": "print('the runner')\n",
            "instalador/test_new.py": "print('a new test outside dev/')\n",
            "microfone/apo/teste/teste_novo.py": "print('a new C++ test runner')\n",
            "instalador/ffmpeg/testa.py": "print('a test named testa.py')\n",
            "instalador/testa-novo.ps1": "Write-Output 'a PowerShell test no workflow runs'\n",
            "instalador/test_new.ps1": "Write-Output 'a new PowerShell test named test_'\n",
            "instalador/testa-atualizador.ps1": "Write-Output 'run by the monta.yml'\n",
            "instalador/testa-a-mao.ps1": "# manual: instalador\\testa-a-mao.ps1 precisa de um Windows de teste\n",
            "instalador/atualizacao/testa_parcial.py": "print('in the COMPLETO')\n",
            "dev/bad_manual.py": "# manual: run me\n",
        }
        for rel, body in {**files, "instalador/test_untracked.py": "print('not in the git index')\n"}.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "--", *files], cwd=root, check=True)
        found = testa_tudo.sem_destino(root=root, flows=flows)
        flagged = sorted(f.split()[0].rstrip(":") for f in found if "runs nowhere" in f or "does not follow" in f)
        check(flagged == ["dev/bad_manual.py", "dev/test_lost.py", "dev/testa_perdido.py", "instalador/ffmpeg/testa.py",
                          "instalador/test_new.ps1", "instalador/test_new.py", "instalador/testa-novo.ps1",
                          "microfone/apo/teste/teste_novo.py"],
              f"the lock flags every test of the git ls-files without destination, in or out of dev/, and only them, "
              f"not a file outside the index "
              f"({flagged})")
        echo = mutated(flows, lambda f: next(
            s for j in f[".github/workflows/monta.yml"]["jobs"].values() for s in job_steps(j)
            if (s.get("run") or "").startswith("instalador\\testa-atualizador.ps1")).update(
            {"run": "Write-Output 'instalador\\testa-atualizador.ps1'"}))
        found = testa_tudo.sem_destino(root=root, files=["instalador/testa-atualizador.ps1"], flows=echo)
        check(any(f.startswith("instalador/testa-atualizador.ps1 (the monta.yml") for f in found),
              f"a .ps1 test only named in a step, not run by it, has no destination ({found})")
    check(testa_tudo.sem_destino() == [], "every test of the repo has a destination, and the testa.yml calls every mode")
    long_tests = set(testa_tudo.LONG_TESTS.values())
    check(not long_tests & set(testa_tudo.COMPLETO), "no long test is in the COMPLETO (it would run twice)")
    check(testa_tudo.SERIAL <= set(testa_tudo.COMPLETO) | long_tests, "every SERIAL test is in a list")
    check({"instalador/travas.txt", "dev/travas.txt"} <= set(testa_tudo.TODAS),
          "a change to instalador/travas.txt or dev/travas.txt triggers every area")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    flows = workflows(ROOT)
    test_reader()
    test_required_check(flows, WORKFLOW.read_text(encoding="utf-8"))
    test_modes(flows)
    test_shape(flows)
    test_unpinned()
    test_bench_order()
    test_without_destination(flows)
    test_summary_block(flows)
    test_build_wiring(flows)
    test_build_base_in_queue()
    test_areas_output()
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
