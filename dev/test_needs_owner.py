r"""Checks the owner gate of the "Testa o PR" check (.github/workflows/testa.yml) without GitHub: the run block of its
"Needs owner" step goes to a temporary file and runs as the job runs it, with the event and the labels of each case.
Cases: a merge_group entry whose PR has the needs-owner label (fails), one without it (passes), one whose labels did
not come or came broken (fails); a PR with the label (passes, with the notice line for the summary); a PR and a push without
it. It also checks the shape the gate relies on: the pull_request trigger without edited, labeled or unlabeled (a run
on the same head hid the required check), the merge_group trigger, the required job still named "Testa o PR" and run
with always(), the gate reading the labels of the etiquetas job, its outcome in the result of the summary step, and no
${{ }} inside the run block. Standard library only.

    python dev/test_needs_owner.py

Exits 1 if anything fails."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "testa.yml"
LABEL = "needs-owner"

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def job(text, key):
    """The lines of one job of the workflow (from "  <key>:" to the next job), or an empty list."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line == f"  {key}:"]
    if not starts:
        return []
    body = []
    for line in lines[starts[0] + 1:]:
        if re.match(r"  \S", line):
            break
        body.append(line)
    return body


def step(lines, name):
    """The lines of the step named <name> inside a job (from "- name: <name>" to the next step)."""
    starts = [i for i, line in enumerate(lines) if re.fullmatch(rf"\s*- name: {re.escape(name)}", line)]
    if len(starts) != 1:
        return []
    indent = len(lines[starts[0]]) - len(lines[starts[0]].lstrip())
    body = [lines[starts[0]]]
    for line in lines[starts[0] + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return body


def run_block(lines):
    """The "run: |" block of a step, dedented."""
    starts = [i for i, line in enumerate(lines) if re.fullmatch(r"\s*run: \|", line)]
    if len(starts) != 1:
        return ""
    indent = len(lines[starts[0]]) - len(lines[starts[0]].lstrip()) + 2
    body = []
    for line in lines[starts[0] + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body).rstrip() + "\n"


def shape(text):
    on = re.search(r"^on:\n(.*?)^\S", text, re.M | re.S)
    triggers = on.group(1) if on else ""
    types = re.search(r"^  pull_request:\n(?:    #.*\n)*    types: \[([^\]]*)\]", triggers, re.M)
    check(types is not None and [t.strip() for t in types.group(1).split(",")] == ["opened", "synchronize", "reopened"],
          "the pull_request trigger is exactly opened, synchronize, reopened (no edited, labeled or unlabeled)")
    check(re.search(r"^  merge_group:", triggers, re.M) is not None, "the workflow runs on merge_group")
    required = job(text, "testa-o-pr")
    check(bool(required) and required[0] == "    name: Testa o PR", "the required job is still named \"Testa o PR\"")
    check("    if: ${{ always() }}" in required, "the required job runs with always()")
    needs = next((line for line in required if line.startswith("    needs: ")), "")
    check("etiquetas" in re.findall(r"[\w-]+", needs.split(":", 1)[-1]), f"the required job needs etiquetas ({needs})")
    gate = step(required, "Needs owner")
    check(bool(gate), "the required job has the \"Needs owner\" step")
    check("          LABELS: ${{ needs.etiquetas.outputs.lista }}" in gate
          and "          EVENT: ${{ github.event_name }}" in gate
          and "          LABELS_RESULT: ${{ needs.etiquetas.result }}" in gate,
          "the gate reads the event, the labels of the etiquetas job and its result")
    check("        if: ${{ !cancelled() }}" in gate, "the gate runs unless the run is cancelled")
    check("        shell: python3 {0}" in gate, "the gate runs in python3")
    summary = step(required, "Resumo e resultado")
    check(any("S_DONO: ${{ steps.dono.outcome }}" in line for line in summary)
          and any('"${estados[@]}" "$S_DONO"' in line for line in summary)
          and any("DONO: ${{ steps.dono.outputs.linha }}" in line for line in summary)
          and any('echo "$DONO"' in line for line in summary),
          "the summary step counts the outcome of the gate in its result and writes its line")
    block = run_block(gate)
    check(bool(block) and "${{" not in block, "no ${{ }} inside the gate's run block (event values come through env:)")
    return block


def run(script, tmp, event, labels, result="success"):
    output = Path(tmp) / "output.txt"
    output.write_text("", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "LABELS", "EVENT"))}
    env.update(EVENT=event, LABELS=labels if isinstance(labels, str) else json.dumps(labels), LABELS_RESULT=result,
               GITHUB_OUTPUT=str(output), PYTHONUTF8="1")
    p = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True, encoding="utf-8",
                       timeout=60)
    out = output.read_text(encoding="utf-8")
    line = next((x[len("linha="):] for x in out.splitlines() if x.startswith("linha=")), None)
    return p.returncode, p.stdout + p.stderr, line


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # the cases print the gate's emoji, also without PYTHONUTF8
    block = shape(WORKFLOW.read_text(encoding="utf-8"))
    if not block:
        print(f"\n{len(failures)} failure(s)")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        script = str(Path(tmp) / "needs_owner.py")
        Path(script).write_text(block, encoding="utf-8")

        code, out, line = run(script, tmp, "merge_group", ["extracao-tema", LABEL])
        check(code == 1 and "::error::" in out and line and LABEL in line and line.startswith("❌"),
              f"a queue entry whose PR has the label fails ({code}: {out.strip()})")
        code, out, line = run(script, tmp, "merge_group", ["extracao-tema"])
        check(code == 0 and line == "", f"a queue entry without the label passes ({code}: {out.strip()})")
        code, out, _ = run(script, tmp, "merge_group", [])
        check(code == 0, f"a queue entry of a PR with no labels passes ({code}: {out.strip()})")
        code, out, _ = run(script, tmp, "merge_group", [f"{LABEL}-later", "not-" + LABEL])
        check(code == 0, f"only the exact label name blocks ({code}: {out.strip()})")
        for labels, result, why in (([], "failure", "the etiquetas job failed"), ("", "success", "no list"),
                                    ("not json", "success", "a broken list"), ('{"a": 1}', "success", "not a list"),
                                    ([1, 2], "success", "a list of numbers")):
            code, out, _ = run(script, tmp, "merge_group", labels, result)
            check(code == 1 and "did not come" in out, f"a queue entry fails when {why} ({code}: {out.strip()})")

        code, out, line = run(script, tmp, "pull_request", [LABEL])
        check(code == 0 and "::notice::" in out and line and LABEL in line and line.startswith("⚠️"),
              f"a PR with the label passes and says the queue refuses it ({code}: {out.strip()})")
        code, out, line = run(script, tmp, "pull_request", ["extracao-tema"])
        check(code == 0 and line == "", f"a PR without the label passes quietly ({code}: {out.strip()})")
        code, out, _ = run(script, tmp, "pull_request", [], "failure")
        check(code == 0, f"on the PR, labels that did not come leave the result to the other jobs ({code})")
        code, out, line = run(script, tmp, "push", [])
        check(code == 0 and line == "", f"the push to main passes ({code}: {out.strip()})")
    print(f"\n{len(failures)} failure(s)" if failures else "\nall ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
