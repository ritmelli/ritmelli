r"""Checks the label gates of the required check without GitHub: the run blocks of the "Etiquetas do PR" step, the
"Verdict" step of the "Testa o PR" job (.github/workflows/testa.yml) and the "Leave the merge queue" step
(.github/workflows/dequeue-on-label.yml) run in bash with a fake gh, as the runner runs them.

The verdict reads the labels again from the API when it decides: a queue entry whose PR has the needs-owner label fails,
also when the label came after the etiquetas job read the list, and so does one with an extracao-tema label the screen
jobs did not see. The labeled workflow takes a PR with one of those labels out of the merge queue. Standard library only.

    python dev/test_needs_owner.py

Exits 1 if anything fails."""
import sys

from fake_gh import run_step
from workflow_yaml import ROOT, find_step, load

LABEL = "needs-owner"
FORK_ISSUE = "https://github.com/ritmelli/ritmelli/issues/255"
SHA = "c" * 40
QUEUE_BASE = "b" * 40
QUEUE_REF = f"refs/heads/gh-readonly-queue/main/pr-7-{QUEUE_BASE}"
NEEDS = ("ETIQUETAS", "TESTES", "BENCH", "CAPTURE", "MICROFONE", "TELA", "COMPARA")

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def blocks():
    testa = load(ROOT / ".github" / "workflows" / "testa.yml")["jobs"]
    dequeue = load(ROOT / ".github" / "workflows" / "dequeue-on-label.yml")
    return ((find_step(testa["etiquetas"], "Etiquetas do PR") or {}).get("run"),
            (find_step(testa["testa-o-pr"], "Verdict") or {}).get("run"),
            (find_step(dequeue["jobs"]["dequeue"], "Leave the merge queue") or {}).get("run"), testa, dequeue)


def etiquetas(block, event, labels, ref="", pr=""):
    return run_step(block, {"GITHUB_EVENT_NAME": event, "GITHUB_REF": ref, "GH_TOKEN": "x", "REPO": "ritmelli/ritmelli",
                            "PR": pr}, {"labels": labels})


def verdict(block, event, labels_now, seen="[]", labels_pr="7", states=None):
    env = {"GITHUB_EVENT_NAME": event, "GH_TOKEN": "x", "REPO": "ritmelli/ritmelli",
           "PR": "7" if event == "pull_request" else "", "HEAD": SHA, "RUN_ID": "1", "ATTEMPT": "1",
           "EXECUCAO": "https://example.invalid/run", "DO_REPO": "true" if event == "pull_request" else "false",
           "LABELS_PR": labels_pr, "LABELS": seen, "LINHAS": "", "MUDARAM": "0"}
    env.update({f"S_{n}": (states or {}).get(n, "success") for n in NEEDS})
    env.update({f"R_{n}": f"resumo {n}" for n in NEEDS[1:]})
    return run_step(block, env, {"labels": labels_now})


def test_etiquetas(block):
    ran = etiquetas(block, "merge_group", ["extracao-tema"], ref=QUEUE_REF)
    check(ran.code == 0 and ran.outputs == {"lista": '["extracao-tema"]', "pr": "7", "queue_base": QUEUE_BASE},
          f"a queue entry gives the labels, the PR number and the base commit of its ref ({ran.outputs})")
    for ref in ("refs/heads/gh-readonly-queue/main/pr-7", f"refs/heads/main/pr-7-{QUEUE_BASE}",
                "refs/heads/gh-readonly-queue/main/pr-7-abc"):
        ran = etiquetas(block, "merge_group", [], ref=ref)
        check(ran.code != 0 and "no PR number and base commit" in ran.out, f"a queue ref it cannot read fails ({ref})")
    ran = etiquetas(block, "merge_group", None, ref=QUEUE_REF)
    check(ran.code != 0 and "did not come" in ran.out, "a queue entry whose labels do not come fails")
    ran = etiquetas(block, "pull_request", [LABEL], pr="7")
    check(ran.code == 0 and ran.outputs == {"lista": f'["{LABEL}"]', "pr": "7", "queue_base": ""},
          f"a PR gives its labels and its number, with no base commit ({ran.outputs})")
    ran = etiquetas(block, "push", [LABEL])
    check(ran.code == 0 and ran.outputs == {"lista": "[]", "pr": "", "queue_base": ""} and not ran.calls,
          f"the push has no PR and asks for no labels ({ran.outputs})")


def test_verdict(block):
    ran = verdict(block, "merge_group", ["extracao-tema", LABEL], seen=f'["extracao-tema","{LABEL}"]')
    check(ran.code != 0 and f"::error::❌ {LABEL}:" in ran.out and f"❌ **{LABEL}:** the PR has the label" in ran.summary
          and ran.asked("pr", "view", "7"), f"a queue entry whose PR has the label fails (exit {ran.code})")
    ran = verdict(block, "merge_group", ["extracao-tema"], seen='["extracao-tema"]')
    check(ran.code == 0 and LABEL not in ran.summary, f"a queue entry without the label passes (exit {ran.code})")
    ran = verdict(block, "merge_group", [])
    check(ran.code == 0, f"a queue entry of a PR with no labels passes (exit {ran.code})")
    ran = verdict(block, "merge_group", [f"{LABEL}-later", "not-" + LABEL])
    check(ran.code == 0, f"only the exact label name blocks (exit {ran.code})")
    ran = verdict(block, "merge_group", None)
    check(ran.code != 0 and "did not come at the verdict" in ran.summary,
          f"a queue entry whose labels do not come at the verdict fails (exit {ran.code})")
    ran = verdict(block, "merge_group", [], labels_pr="")
    check(ran.code != 0 and "has no PR number" in ran.summary and not ran.asked("pr", "view"),
          f"a queue entry with no PR number fails (exit {ran.code})")
    ran = verdict(block, "pull_request", [LABEL], seen=f'["{LABEL}"]')
    check(ran.code == 0 and f"::notice::⚠️ {LABEL}:" in ran.out and "the merge queue refuses this PR" in ran.summary,
          f"a PR with the label passes and says the queue refuses it (exit {ran.code})")
    ran = verdict(block, "pull_request", ["extracao-tema"], seen='["extracao-tema"]')
    check(ran.code == 0 and LABEL not in ran.summary, f"a PR without the label passes quietly (exit {ran.code})")
    ran = verdict(block, "pull_request", None)
    check(ran.code != 0 and "did not come at the verdict" in ran.summary,
          f"on a PR, labels that do not come at the verdict fail it (exit {ran.code})")
    ran = verdict(block, "push", None, labels_pr="")
    check(ran.code == 0 and not ran.asked("pr", "view"), f"the push asks for no labels (exit {ran.code})")
    ran = verdict(block, "merge_group", [], states={"ETIQUETAS": "failure"})
    check(ran.code != 0 and "the labels job ended in failure" in ran.summary,
          f"a failed etiquetas job fails the check (exit {ran.code})")


def test_late_label(etiquetas_block, verdict_block):
    seen = etiquetas(etiquetas_block, "merge_group", ["extracao-tema"], ref=QUEUE_REF).outputs
    ran = verdict(verdict_block, "merge_group", ["extracao-tema", LABEL], seen=seen.get("lista", ""),
                  labels_pr=seen.get("pr", ""))
    check(ran.code != 0 and f"❌ **{LABEL}:** the PR has the label" in ran.summary,
          f"the {LABEL} label put after the etiquetas job read the list still fails the queue entry (exit {ran.code})")
    seen = etiquetas(etiquetas_block, "merge_group", [], ref=QUEUE_REF).outputs
    ran = verdict(verdict_block, "merge_group", ["extracao-tema"], seen=seen.get("lista", ""),
                  labels_pr=seen.get("pr", ""))
    check(ran.code != 0 and "❌ **extracao-tema:** the label came after the screen jobs" in ran.summary,
          f"an extracao-tema label the screen jobs did not see fails the queue entry (exit {ran.code})")
    seen = etiquetas(etiquetas_block, "merge_group", [LABEL], ref=QUEUE_REF).outputs
    ran = verdict(verdict_block, "merge_group", [], seen=seen.get("lista", ""), labels_pr=seen.get("pr", ""))
    check(ran.code == 0, f"a {LABEL} label taken off before the verdict lets the entry pass (exit {ran.code})")


def dequeue(block, label, pr, refused=False):
    return run_step(block, {"GH_TOKEN": "x", "REPO": "ritmelli/ritmelli", "PR": "7", "LABEL": label},
                    {"pr": pr, "mutation_refused": refused})


def mutations(ran):
    return [c for c in ran.asked("api", "graphql") if any("dequeuePullRequest" in a for a in c)]


def test_dequeue(block):
    queued = {"id": "PR_node", "queued": True, "labels": ["extracao-tema", LABEL]}
    for label in (LABEL, "extracao-tema"):
        ran = dequeue(block, label, queued)
        check(ran.code == 0 and len(mutations(ran)) == 1 and "id=PR_node" in mutations(ran)[0],
              f"the {label} label takes a PR in the merge queue out of it (exit {ran.code})")
    ran = dequeue(block, LABEL, {"id": "PR_node", "queued": True, "labels": ["extracao-tema", f"{LABEL}-later"]})
    check(ran.code == 0 and not mutations(ran) and "no longer on PR 7" in ran.out,
          f"a late run whose label was already taken off leaves the PR in the queue (exit {ran.code})")
    ran = dequeue(block, LABEL, queued, refused=True)
    check(ran.code != 0 and len(mutations(ran)) == 1,
          f"known failure, {FORK_ISSUE}: a refused dequeue (the read-only token of a fork PR) fails the run and the PR "
          f"stays in the queue (exit {ran.code})")
    ran = dequeue(block, LABEL, {"id": "PR_node", "queued": False, "labels": [LABEL]})
    check(ran.code == 0 and len(ran.calls) == 1, f"a PR outside the queue is only looked up (exit {ran.code})")
    ran = dequeue(block, "bug", queued)
    check(ran.code == 0 and not ran.calls, f"another label asks nothing (exit {ran.code})")
    ran = dequeue(block, LABEL, None)
    check(ran.code != 0, f"a lookup that fails fails the run (exit {ran.code})")


def test_shape(testa, flow):
    check(flow.get("on") == {"pull_request": {"types": ["labeled"]}},
          f"the dequeue workflow runs on pull_request labeled only ({flow.get('on')}); known failure, {FORK_ISSUE}: "
          "there a fork PR gets a read-only token and is not dequeued, and the trigger that fixes it closes the issue")
    job = flow["jobs"]["dequeue"]
    check("if" not in job and all("if" not in s for s in job.get("steps", [])),
          "the dequeue job and its steps have no if: (the label is chosen in the tested block)")
    check(job.get("permissions") == {"contents": "write", "pull-requests": "write"},
          f"the dequeue job may take a PR out of the queue ({job.get('permissions')})")
    step = find_step(job, "Leave the merge queue") or {}
    check((step.get("env") or {}).get("LABEL") == "${{ github.event.label.name }}"
          and (step.get("env") or {}).get("PR") == "${{ github.event.pull_request.number }}",
          "the dequeue step reads the label and the PR of the event")
    env = (find_step(testa["testa-o-pr"], "Verdict") or {}).get("env") or {}
    check(env.get("LABELS_PR") == "${{ needs.etiquetas.outputs.pr }}"
          and env.get("LABELS") == "${{ needs.etiquetas.outputs.lista }}"
          and env.get("S_ETIQUETAS") == "${{ needs.etiquetas.result }}",
          "the verdict reads the PR number, the list and the result of the etiquetas job")
    check("if" not in testa["etiquetas"], "the etiquetas job runs on every event")
    for name, step in (("Verdict", find_step(testa["testa-o-pr"], "Verdict")),
                       ("Etiquetas do PR", find_step(testa["etiquetas"], "Etiquetas do PR")),
                       ("Leave the merge queue", find_step(job, "Leave the merge queue"))):
        check(bool(step) and "${{" not in step.get("run", ""), f"no ${{{{ }}}} inside the {name} run block")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    etiquetas_block, verdict_block, dequeue_block, testa, flow = blocks()
    test_shape(testa, flow)
    if etiquetas_block and verdict_block and dequeue_block:
        test_etiquetas(etiquetas_block)
        test_verdict(verdict_block)
        test_late_label(etiquetas_block, verdict_block)
        test_dequeue(dequeue_block)
    else:
        check(False, "the Etiquetas do PR, Verdict and Leave the merge queue steps exist")
    print(f"\n{len(failures)} failure(s)" if failures else "\nall ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
