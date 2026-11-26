"""Runs the bash run block of a workflow step the way the runner does (bash --noprofile --norc -eo pipefail), with a
fake gh on the PATH, for the workflow tests. Standard library only.

The fake answers the calls the steps of .github/workflows/ make, from a dict (FakeGh) that the case sets; any other call
fails the step. It logs every call, so a case can check what was asked."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_SHIM = """#!/bin/bash
exec "$FAKE_PYTHON" "$FAKE_GH_PY" "$@"
"""
_FAKE = r"""
import json
import os
import re
import sys
from urllib.parse import parse_qs, urlparse

args = sys.argv[1:]
conf = json.loads(os.environ["FAKE_GH"])
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")


def flag(name):
    return args[args.index(name) + 1] if name in args else None


def fields():
    out = {}
    for i, a in enumerate(args[:-1]):
        if a in ("-f", "-F"):
            k, _, v = args[i + 1].partition("=")
            out[k] = v
    return out


if args[:2] == ["pr", "comment"]:
    sys.exit("non-200 OK status code: 502 Bad Gateway" if conf.get("comment_fails") else 0)
if args[:2] == ["pr", "view"]:
    labels = conf.get("labels")
    if labels is None or flag("--json") != "labels":
        sys.exit("HTTP 502: the labels did not come")
    jq = flag("--jq")
    if jq == ".labels[].name":
        print("\n".join(labels))
    elif jq == "[.labels[].name]":
        print(json.dumps(labels, separators=(",", ":")))
    else:
        sys.exit(f"fake gh: a --jq it does not know: {jq}")
    sys.exit(0)
if args[:2] == ["api", "graphql"]:
    query = fields().get("query", "")
    if query.startswith("mutation"):
        if "dequeuePullRequest" not in query or not fields().get("id"):
            sys.exit(f"fake gh: a mutation it does not know: {query}")
        print("{}")
        sys.exit(0)
    pr = conf.get("pr")
    if pr is None:
        sys.exit("HTTP 502")
    if flag("--jq") != '.data.repository.pullRequest | "\\(.id) \\(.isInMergeQueue)"':
        sys.exit(f"fake gh: a --jq it does not know: {flag('--jq')}")
    print(f"{pr['id']} {'true' if pr['queued'] else 'false'}")
    sys.exit(0)
if args[0] != "api":
    sys.exit(f"fake gh: unexpected call: {args}")
url = urlparse(args[1])
if url.path.endswith("/jobs"):
    print("Testes 4 min 10 s")
    sys.exit(0)
if not url.path.endswith("/actions/workflows/testa.yml/runs"):
    sys.exit(f"fake gh: unexpected call: {args}")
if conf.get("queue_fails"):
    sys.exit("HTTP 502")
query = parse_qs(url.query)
runs = [r for r in conf.get("runs", [])
        if query.get("event") == ["merge_group"] and r["head_sha"] in query.get("head_sha", [r["head_sha"]])]
m = re.fullmatch(r'\[\.workflow_runs\[\] \| select\(\.conclusion == "(\w+)"\)\]\[0\]\.html_url // empty', flag("--jq"))
if not m:
    sys.exit(f"fake gh: a --jq it does not know: {flag('--jq')}")
print(next((r["html_url"] for r in runs if r["conclusion"] == m.group(1)), ""))
"""


def bash():
    """The bash of Git for Windows (bash on the PATH outside Windows), or None."""
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if not git:
        return None
    for base in Path(git).resolve().parents:
        for p in (base / "bin" / "bash.exe", base / "usr" / "bin" / "bash.exe"):
            if p.is_file():
                return str(p)
    return None


@dataclass
class Ran:
    code: int
    out: str
    summary: str
    calls: list
    outputs: dict = field(default_factory=dict)

    def asked(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


def run_step(run, env, fake=None, cwd=None):
    """Runs the run block with env (on top of the os.environ without the GITHUB_ variables) and the fake gh set by the
    dict fake: labels (a list, or None when they do not come), comment_fails, runs, queue_fails, pr ({"id", "queued"},
    or None when it does not come)."""
    shell = bash()
    if not shell:
        raise RuntimeError("no bash: the Git for Windows one (or bash on the PATH outside Windows) runs the block")
    with tempfile.TemporaryDirectory(prefix="ritmelli-step-") as tmp:
        tmp = Path(tmp)
        (tmp / "bin").mkdir()
        (tmp / "bin" / "gh").write_text(_SHIM, encoding="utf-8", newline="\n")
        (tmp / "bin" / "gh").chmod(0o755)
        (tmp / "fake_gh.py").write_text(_FAKE, encoding="utf-8")
        (tmp / "run.sh").write_text(run, encoding="utf-8", newline="\n")
        summary, log, output = tmp / "summary.md", tmp / "log.txt", tmp / "output.txt"
        for f in (summary, log, output):
            f.touch()
        full = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
        full.update(PATH=str(tmp / "bin") + os.pathsep + os.environ.get("PATH", ""), GITHUB_STEP_SUMMARY=str(summary),
                    GITHUB_OUTPUT=str(output), FAKE_LOG=str(log), FAKE_PYTHON=Path(sys.executable).as_posix(),
                    FAKE_GH_PY=(tmp / "fake_gh.py").as_posix(), FAKE_GH=json.dumps(fake or {}))
        full.update(env)
        p = subprocess.run([shell, "--noprofile", "--norc", "-eo", "pipefail", (tmp / "run.sh").as_posix()],
                           cwd=cwd or tmp, env=full, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
        outputs = {}
        for line in output.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                outputs[key] = value
        calls = [json.loads(c) for c in log.read_text(encoding="utf-8").splitlines()]
        return Ran(p.returncode, p.stdout + p.stderr, summary.read_text(encoding="utf-8"), calls, outputs)
