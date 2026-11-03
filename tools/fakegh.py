#!/usr/bin/env python3
"""A stand-in for the GitHub API that serves a few demo pull requests.

Each pull request has one scenario, so every pull request station of the demo
shows something: failing and pending checks, bot comments, a person's change
request, a merge conflict, and one pull request that waits on nothing.
Usage: fakegh.py PORT
"""
import json, re, sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NOW = datetime.now(timezone.utc)
HOST = "https://github.example.invalid"


def ts(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


# pr number -> scenario; the build script writes the same numbers into the workspaces.
SCENARIOS = {
    201: {"checks": [("lint", "failure"), ("unit-tests", "failure"), ("build", "success")]},
    202: {"checks": [("lint", "success"), ("unit-tests", "in_progress"), ("build", "success")]},
    203: {"checks": [("build", "success")], "bot": 3},
    204: {"checks": [("build", "success")], "human": 2},
    205: {"checks": [("build", "success")], "conflict": True},
    206: {"checks": [("lint", "success"), ("build", "success")]},
}
BOT_NOTES = ["Consider extracting this into a helper.", "This branch is never reached.", "Missing a test for the empty case."]
HUMAN_NOTES = ["Please rename this to match the API.", "Can we keep the old flag for one release?"]


def pr_of(n):
    s = SCENARIOS.get(n, {"checks": [("build", "success")]})
    return {
        "number": n, "state": "open", "draft": False, "merged": False,
        "mergeable": not s.get("conflict", False),
        "mergeable_state": "dirty" if s.get("conflict") else "clean",
        "html_url": f"{HOST}/example-org/example-project/pull/{n}",
        "head": {"sha": f"{n:04d}abcdef0123456789abcdef0123456789ab", "ref": f"sortie/pr-{n}"},
        "base": {"ref": "main"},
    }


def runs_of(n):
    out = []
    for i, (name, result) in enumerate(SCENARIOS.get(n, {"checks": [("build", "success")]})["checks"]):
        done = result in ("success", "failure")
        out.append({"id": n * 100 + i, "name": name, "status": "completed" if done else result,
                    "conclusion": result if done else None,
                    "html_url": f"{HOST}/example-org/example-project/actions/runs/{n * 100 + i}",
                    "app": {"slug": "github-actions"}})
    return out


def reviews_of(n):
    s = SCENARIOS.get(n, {})
    out = []
    if s.get("bot"):
        out.append({"id": n * 10 + 1, "state": "COMMENTED", "body": "",
                    "user": {"login": "copilot-pull-request-reviewer[bot]", "type": "Bot"}, "submitted_at": ts(2)})
    if s.get("human"):
        out.append({"id": n * 10 + 2, "state": "CHANGES_REQUESTED", "body": "",
                    "user": {"login": "maintainer", "type": "User"}, "submitted_at": ts(1)})
    return out


def comments_of(n):
    s = SCENARIOS.get(n, {})
    out = []
    for i in range(s.get("bot", 0)):
        out.append({"id": n * 1000 + i, "pull_request_review_id": n * 10 + 1, "path": f"src/app/module{i}.ts",
                    "line": 10 + i, "subject_type": "line", "body": BOT_NOTES[i % len(BOT_NOTES)],
                    "user": {"login": "copilot-pull-request-reviewer[bot]", "type": "Bot"}, "created_at": ts(2)})
    for i in range(s.get("human", 0)):
        out.append({"id": n * 1000 + 500 + i, "pull_request_review_id": n * 10 + 2, "path": "src/api/client.ts",
                    "line": 40 + i, "subject_type": "line", "body": HUMAN_NOTES[i % len(HUMAN_NOTES)],
                    "user": {"login": "maintainer", "type": "User"}, "created_at": ts(1)})
    return out


def pr_number_from_sha(sha):
    m = re.match(r"(\d{4})abcdef", sha)
    return int(m.group(1)) if m else None


def pr_number_from_ref(ref):
    m = re.match(r"sortie/pr-(\d+)$", ref)
    return int(m.group(1)) if m else pr_number_from_sha(ref)


class Handler(BaseHTTPRequestHandler):
    def send(self, body, status=200, kind="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        repo = r"/repos/[^/]+/[^/]+"
        if m := re.fullmatch(repo + r"/pulls/(\d+)", path):
            return self.send(pr_of(int(m.group(1))))
        if m := re.fullmatch(repo + r"/pulls/(\d+)/reviews", path):
            return self.send(reviews_of(int(m.group(1))))
        if m := re.fullmatch(repo + r"/pulls/(\d+)/comments", path):
            return self.send(comments_of(int(m.group(1))))
        if m := re.fullmatch(repo + r"/commits/([^/]+)/status", path):
            return self.send({"state": "success", "statuses": []})
        if m := re.fullmatch(repo + r"/commits/([^/]+)/check-runs", path):
            n = pr_number_from_ref(m.group(1).replace("%2F", "/"))
            runs = runs_of(n) if n else []
            return self.send({"total_count": len(runs), "check_runs": runs})
        if m := re.fullmatch(repo + r"/actions/jobs/(\d+)", path):
            return self.send({"id": int(m.group(1)), "steps": [{"name": "Run tests", "number": 3, "conclusion": "failure"}]})
        if m := re.fullmatch(repo + r"/actions/jobs/(\d+)/logs", path):
            return self.send("##[group]Run tests\nFAIL src/app/module1.test.ts\n  expected 3, received 2\n##[error]Process completed with exit code 1.\n", kind="text/plain")
        sys.stderr.write(f"fakegh: unhandled GET {self.path}\n")
        return self.send([] if path.endswith("s") else {}, 404 if not path.endswith("s") else 200)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.split("?")[0].endswith("/graphql"):
            n = body.get("variables", {}).get("number")
            decision = "CHANGES_REQUESTED" if SCENARIOS.get(n, {}).get("human") else "REVIEW_REQUIRED"
            return self.send({"data": {"repository": {"pullRequest": {"reviewDecision": decision, "mergeCommit": None}}}})
        sys.stderr.write(f"fakegh: unhandled POST {self.path}\n")
        return self.send({}, 404)

    def log_message(self, fmt, *args):
        sys.stderr.write("fakegh: " + (fmt % args) + "\n")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
