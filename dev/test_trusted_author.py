r"""Checks the "Trusted author" check (.github/workflows/trusted-author.yml) without GitHub: the run block of the
workflow goes to a temporary file and runs as the job runs it, against a fake REST API on localhost that answers
with the PR and the reviews of each case. Cases: a maintainer's PR; a PR from outside with no review, with a
maintainer approval on the head, on an old commit, by someone from outside, and with a change request after the
approval; the reviews on a second page; a merge queue ref that is valid and one that is not; an API error. It also
checks the shape the rule relies on: the two triggers, read-only permissions, no checkout and no ${{ }} inside the
run block. Standard library only.

    python dev/test_trusted_author.py

Exits 1 if anything fails."""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "trusted-author.yml"
REPO = "ritmelli/ritmelli"
HEAD, OLD = "a" * 40, "b" * 40
MAINTAINER, OTHER_MAINTAINER, OUTSIDER = "christianbehlingaraujo", "WilliamBehlingAraujo", "someone-else"

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def run_block(text):
    """The text of the only "run: |" block of the workflow, dedented."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if re.fullmatch(r"\s*run: \|", line)]
    if len(starts) != 1:
        raise SystemExit(f"expected one 'run: |' block in {WORKFLOW.name}, found {len(starts)}")
    indent = len(lines[starts[0]]) - len(lines[starts[0]].lstrip()) + 2
    body = []
    for line in lines[starts[0] + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body).rstrip() + "\n"


class FakeApi(BaseHTTPRequestHandler):
    routes = {}  # path -> (status, body), set per case
    seen = []

    def do_GET(self):
        FakeApi.seen.append((self.path, self.headers.get("Authorization")))
        status, body = FakeApi.routes.get(self.path, (404, {"message": "Not Found"}))
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def review(login, state, commit):
    return {"user": {"login": login}, "state": state, "commit_id": commit}


def reviews_route(number, items, page=1):
    return {f"/repos/{REPO}/pulls/{number}/reviews?per_page=100&page={page}": (200, items)}


def pr_route(number, author, head=HEAD):
    return {f"/repos/{REPO}/pulls/{number}": (200, {"user": {"login": author}, "head": {"sha": head}})}


def run(script, api_url, routes, event, summary, **env):
    FakeApi.routes, FakeApi.seen[:] = routes, []
    Path(summary).write_text("", encoding="utf-8")
    full = {k: v for k, v in os.environ.items() if not k.startswith(("PR_", "QUEUE_", "GITHUB_"))}
    full.update(GH_TOKEN="fake-token", API_URL=api_url, REPO=REPO, GITHUB_EVENT_NAME=event,
                GITHUB_STEP_SUMMARY=summary, PYTHONUTF8="1", **env)
    p = subprocess.run([sys.executable, script], env=full, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr, Path(summary).read_text(encoding="utf-8")


def shape(text):
    check("pull_request_target:" in text and re.search(r"types: \[opened, synchronize, reopened\]", text) is not None,
          "the workflow runs on pull_request_target (opened, synchronize, reopened)")
    check(re.search(r"^\s*pull_request:", text, re.M) is None, "the workflow does not run on pull_request")
    check(re.search(r"^\s*merge_group:", text, re.M) is not None, "the workflow runs on merge_group")
    check(re.search(r"^\s*name: Trusted author$", text, re.M) is not None, "the job is named \"Trusted author\"")
    perms = re.findall(r"^\s+(\w[\w-]*): (read|write|none)$", text, re.M)
    check(sorted(perms) == [("contents", "read"), ("pull-requests", "read")],
          f"the only permissions are contents and pull-requests read ({perms})")
    code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    check(not any("checkout" in line for line in code), "the workflow checks out nothing")
    check("${{" not in run_block(text), "no ${{ }} inside the run block (event values come through env:)")


def main():
    text = WORKFLOW.read_text(encoding="utf-8")
    shape(text)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api_url = f"http://127.0.0.1:{server.server_address[1]}"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "trusted_author.py"
        script.write_text(run_block(text), encoding="utf-8")
        summary = str(Path(tmp) / "summary.md")

        def pr_event(routes, author, head=HEAD, number="7"):
            return run(str(script), api_url, routes, "pull_request_target", summary,
                       PR_NUMBER=number, PR_AUTHOR=author, PR_HEAD_SHA=head)

        code, out, summ = pr_event({}, MAINTAINER)
        check(code == 0 and "a maintainer" in out and not FakeApi.seen,
              f"a maintainer's PR passes without reading the API ({code}: {out.strip()})")
        check(summ.startswith("✅"), "the passing run writes the summary")
        code, out, _ = pr_event({}, "WilliamBehlingAraujo")
        check(code == 0, f"the login is compared without case ({code}: {out.strip()})")

        code, out, summ = pr_event(reviews_route(7, []), OUTSIDER)
        check(code == 1 and "::error::" in out and "re-runs this job" in out and summ.startswith("❌"),
              f"a PR from outside with no review fails and says what to do ({code}: {out.strip()})")
        check(FakeApi.seen and FakeApi.seen[0][1] == "Bearer fake-token", "the API call carries the token")

        code, out, _ = pr_event(reviews_route(7, [review(OUTSIDER, "COMMENTED", HEAD),
                                                  review(OTHER_MAINTAINER, "APPROVED", HEAD)]), OUTSIDER)
        check(code == 0 and "williambehlingaraujo approved" in out,
              f"a PR from outside approved by a maintainer on the head passes ({code}: {out.strip()})")

        code, out, _ = pr_event(reviews_route(7, [review(MAINTAINER, "APPROVED", OLD)]), OUTSIDER)
        check(code == 1, f"an approval on an old commit (a push after it) fails ({code}: {out.strip()})")

        code, out, _ = pr_event(reviews_route(7, [review("another-outsider", "APPROVED", HEAD)]), OUTSIDER)
        check(code == 1, f"an approval by someone from outside fails ({code}: {out.strip()})")

        code, out, _ = pr_event(reviews_route(7, [review(MAINTAINER, "APPROVED", HEAD),
                                                  review(MAINTAINER, "COMMENTED", HEAD),
                                                  review(MAINTAINER, "CHANGES_REQUESTED", HEAD)]), OUTSIDER)
        check(code == 1, f"a change request after the approval takes it back ({code}: {out.strip()})")

        code, out, _ = pr_event(reviews_route(7, [review(MAINTAINER, "CHANGES_REQUESTED", OLD),
                                                  review(MAINTAINER, "APPROVED", HEAD)]), OUTSIDER)
        check(code == 0, f"an approval after a change request counts ({code}: {out.strip()})")

        first = [review(OUTSIDER, "COMMENTED", HEAD)] * 100
        code, out, _ = pr_event(reviews_route(7, first) | reviews_route(7, [review(MAINTAINER, "APPROVED", HEAD)], 2),
                                OUTSIDER)
        check(code == 0, f"an approval on the second page of reviews counts ({code}: {out.strip()})")

        code, out, _ = pr_event({}, OUTSIDER)
        check(code == 1 and "could not read the pull request from the API" in out,
              f"an API error fails the check ({code}: {out.strip()})")

        code, out, _ = pr_event({}, MAINTAINER, number="")
        check(code == 1, f"an event without a PR number fails ({code}: {out.strip()})")

        def queue(routes, ref):
            return run(str(script), api_url, routes, "merge_group", summary, QUEUE_REF=ref)

        ref = f"refs/heads/gh-readonly-queue/main/pr-42-{'c' * 40}"
        code, out, _ = queue(pr_route(42, MAINTAINER), ref)
        check(code == 0 and "#42" in out, f"a queue entry of a maintainer's PR passes ({code}: {out.strip()})")
        code, out, _ = queue(pr_route(42, OUTSIDER) | reviews_route(42, [review(MAINTAINER, "APPROVED", HEAD)]), ref)
        check(code == 0, f"a queue entry of an approved PR from outside passes ({code}: {out.strip()})")
        code, out, _ = queue(pr_route(42, OUTSIDER) | reviews_route(42, [review(MAINTAINER, "APPROVED", OLD)]), ref)
        check(code == 1, f"a queue entry of a PR from outside not approved on its head fails ({code}: {out.strip()})")
        code, out, _ = queue(pr_route(42, OUTSIDER, "d" * 40) | reviews_route(42, []),
                             f"refs/heads/gh-readonly-queue/release/1.0/pr-42-{'c' * 40}")
        check(code == 1 and FakeApi.seen[0][0] == f"/repos/{REPO}/pulls/42",
              f"a queue ref whose base has a slash still gives the PR number ({code}: {out.strip()})")
        for bad in ("", "refs/heads/main", "refs/heads/gh-readonly-queue/main/pr-x-abc",
                    f"refs/heads/gh-readonly-queue/main/pr-42-{'c' * 40}\n::warning::x"):
            code, out, _ = queue(pr_route(42, MAINTAINER), bad)
            check(code == 1 and "could not read the pull request number" in out and not FakeApi.seen,
                  f"the queue ref {bad!r} fails without reading the API ({code})")
    server.shutdown()
    print(f"\n{len(failures)} failure(s)" if failures else "\nall ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
