#!/usr/bin/env python3
"""Build a Sortie demo state that looks like ten days of operation.

Phase A runs the real Sortie binary with its mock agent at high speed, so
every row comes from Sortie itself. Phase B rewrites the timestamps of those
rows across the last ten days. The state it leaves also holds issues that
start running as soon as Sortie starts on it.

Usage: build.py   (environment: DEMO_BIN, DEMO_SEED, DEMO_BUILD_PORT, DEMO_GH_PORT)
"""
import json, os, random, shutil, signal, sqlite3, subprocess, sys, time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.environ["DEMO_BIN"]
SEED = os.environ["DEMO_SEED"]
STATE = SEED + ".building"
BUILD_PORT = os.environ.get("DEMO_BUILD_PORT", "7749")
DAYS = 10
random.seed(42)

TITLES = {
    "feature": [
        "Add CSV export to the reports page", "Show a summary card on the dashboard", "Support bulk editing of tasks",
        "Add a profile switcher to the header", "Show a trend line for weekly activity", "Add a usage forecast widget",
        "Support keyboard shortcuts in the editor", "Add saved searches", "Show the next scheduled job",
        "Add theme presets", "Support file attachments on comments", "Add a session timeout warning",
        "Show sync status in the sidebar", "Add a quick settings drawer", "Support a dark mode schedule",
        "Add rate limit headers to the API", "Show a dependency graph for tasks", "Add favorites to the file browser",
    ],
    "bug": [
        "Fix crash when resizing the editor", "Fix stale totals after reconnect",
        "Fix flicker in the date picker", "Fix missing avatars after login",
        "Fix wrong unit in the storage chart", "Fix overlapping labels in long translations",
        "Fix the activity feed not updating", "Fix a memory leak in the chart renderer",
        "Fix double click opening two dialogs", "Fix empty state on first start",
        "Fix truncated user names", "Fix scroll jump after saving",
        "Fix dark mode contrast on warnings", "Fix a race in settings loading",
    ],
    "documentation": [
        "Document the theming tokens", "Update the build instructions", "Describe the release process",
        "Document the API error codes", "Add an architecture overview diagram", "Explain the test setup",
        "Document accessibility guidelines", "Update the contribution guide",
    ],
    "research": [
        "Evaluate list virtualization performance", "Compare charting libraries",
        "Investigate cold start time", "Assess search engine options",
        "Measure frame drops while scrolling", "Review the framework upgrade impact",
    ],
    "flaky": ["Stabilize the end-to-end tests", "Retry the flaky screenshot comparison", "Harden the browser setup in CI"],
    "broken": ["Migrate signing to the new key", "Run lint on the legacy module"],
}

LIVE = [
    ("feature", "Add inline editing to the task list", []),
    ("feature", "Support multiple workspaces", []),
    ("bug", "Fix stutter when switching tabs", []),
    ("documentation", "Document the demo data generator", []),
    ("research", "Evaluate an embedded search index", []),
    ("feature", "Show inline editing in the mobile view", ["LIVE-1"]),
    ("flaky", "Stabilize the screenshot tests", []),
    ("broken", "Publish the SDK to the package registry", []),
    ("bug", "Fix wrong date format in the history", []),
    ("feature", "Add a schedule editor", []),
]

# Pull request numbers of the fake GitHub, one scenario each; see fakegh.py.
PULL_REQUESTS = [201, 202, 203, 204, 205, 206]
FAKE_GITHUB = "http://127.0.0.1:" + os.environ.get("DEMO_GH_PORT", "7750")
PROJECT = "example-org/example-project"

FRONTMATTER = """---
tracker:
  kind: file
  project: example-org/example-project
  active_states: [To Do, In Progress]
  terminal_states: [Done, Cancelled]
  in_progress_state: In Progress
  handoff_state: Human Review
file:
  path: issues.json
polling:
  interval_ms: {poll}
workspace:
  root: ./workspaces
db_path: ./state.db
agent:
  kind: mock
  max_turns: 3
  max_concurrent_agents: {conc}
  max_sessions: 3
  max_cost_usd: 25
  max_daily_cost_usd: 40
  max_weekly_cost_usd: 150
  max_monthly_cost_usd: 400
  max_retry_backoff_ms: {backoff}
mock:
  model_name: claude-opus-5-5
  turn_delay_ms: {delay}
  events_per_turn: 8
  input_tokens_per_turn: 150000
  cache_read_tokens_per_turn: 110000
  output_tokens_per_turn: 6000
  turn_outcomes: [success]
  tool_calls:
    - tool_name: skill
      duration_ms: 1200
    - tool_name: bash
      duration_ms: 3400
    - tool_name: edit
      duration_ms: 300
"""

PROMPT = """---

**{{ .issue.identifier }}**: {{ .issue.title }}

{{ .issue.description }}
"""


# The live phase watches the pull requests of the fake GitHub.
PULL_REQUEST_LOOP = """github:
  api_key: demo
  project: {project}
  endpoint: {endpoint}
reactions:
  ci_failure:
    provider: github
    max_log_lines: 50
    max_retries: 2
  bot_review:
    provider: github
    poll_interval_ms: 30000
    watch_window_ms: 0
    max_continuation_turns: 3
  review_comments:
    provider: github
    debounce_ms: 0
    poll_interval_ms: 30000
    watch_window_ms: 0
    max_continuation_turns: 3
  merge_conflicts:
    provider: github
    poll_interval_ms: 30000
    watch_window_ms: 0
    max_retries: 2
"""


def workflow(path, poll, conc, delay, backoff, loop=False):
    rules = open(os.path.join(HERE, "rules.yaml.part")).read()
    front = FRONTMATTER.format(poll=poll, conc=conc, delay=delay, backoff=backoff)
    if loop:
        front += PULL_REQUEST_LOOP.format(project=PROJECT, endpoint=FAKE_GITHUB)
    with open(path, "w") as f:
        f.write(front + rules + PROMPT)


def iso(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_ns(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ").replace("Z", "000Z")


def make_issues(now):
    issues, n = [], 0
    for kind, titles in TITLES.items():
        if kind in ("feature", "bug"):
            titles = titles + [t + " in the mobile app" for t in titles[::2]]
        for title in titles:
            n += 1
            created = now - timedelta(days=DAYS, hours=random.randint(1, 72))
            labels = [kind] + ([random.choice(["frontend", "backend", "api", "cli"])] if kind in ("feature", "bug") else [])
            issues.append({
                "id": str(n), "identifier": f"APP-{n}", "title": title,
                "description": f"{title}.\n\n**Acceptance**\n\n- Works in light and dark mode\n- Covered by a `ui` test\n",
                "priority": random.randint(1, 4), "state": "To Do", "labels": labels,
                "issue_type": {"bug": "Bug", "feature": "Story"}.get(kind, "Task"),
                "url": f"https://tracker.example.invalid/APP-{n}", "blocked_by": [], "comments": [],
                "created_at": iso(created), "updated_at": iso(created),
            })
    random.shuffle(issues)
    return issues


def handed_off():
    ids = set()
    for line in open(os.path.join(STATE, "phase-a.log")):
        if 'msg="handoff transition succeeded' in line:
            ids.add(line.split(" issue_id=")[1].split()[0])
    return ids


def run_phase_a():
    shutil.rmtree(STATE, ignore_errors=True)
    os.makedirs(STATE)
    now = datetime.now(timezone.utc)
    issues = make_issues(now)
    json.dump(issues, open(os.path.join(STATE, "issues.json"), "w"), indent=1)
    workflow(os.path.join(STATE, "WORKFLOW.md"), poll=500, conc=8, delay=150, backoff=2000)
    run_sortie()
    done = handed_off()
    for issue in issues:
        if issue["id"] in done and random.random() > 0.35:
            issue["state"] = "Done"
    json.dump(issues, open(os.path.join(STATE, "issues.json"), "w"), indent=1)
    run_sortie()


def run_sortie():
    log = open(os.path.join(STATE, "phase-a.log"), "a")
    proc = subprocess.Popen([BIN, "--port", BUILD_PORT, "WORKFLOW.md"], cwd=STATE, stdout=log, stderr=log)
    db = os.path.join(STATE, "state.db")
    last, still = -1, 0
    try:
        for _ in range(600):
            time.sleep(1)
            if not os.path.exists(db):
                continue
            count = sqlite3.connect(db).execute("select count(*) from run_history").fetchone()[0]
            still = still + 1 if count == last else 0
            last = count
            if count and still >= 8:
                break
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=30)
    print(f"phase A: {last} runs")


def run_phase_b():
    """Spread the runs across the last ten days, keeping their order per issue."""
    db = sqlite3.connect(os.path.join(STATE, "state.db"))
    db.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc)
    # The mock ignores turn outcomes set on a rule, so the variety of endings is set here.
    db.execute("update run_history set status='failed', error='turn failed: instrumentation tests timed out after 600s' where rule_name='flaky'")
    for (run_id,) in db.execute("select id from run_history where status='succeeded'").fetchall():
        roll = random.random()
        if roll < 0.04:
            db.execute("update run_history set status='cancelled', turns_completed=1 where id=?", (run_id,))
        elif roll < 0.07:
            db.execute("update run_history set status='needs_person', error='agent asked for a decision on the API shape' where id=?", (run_id,))
        elif roll < 0.09:
            db.execute("update run_history set status='budget_stopped', error='cost budget of $25.00 reached' where id=?", (run_id,))
        elif roll < 0.25:
            db.execute("update run_history set declared_outcome='needs-human-review' where id=?", (run_id,))
        elif roll < 0.30:
            db.execute("update run_history set declared_outcome='no-change-needed' where id=?", (run_id,))
    runs = db.execute("select id, issue_id, dispatch_id, started_at, completed_at, rule_name, status, turns_completed, reported_model from run_history order by id").fetchall()
    by_issue = {}
    for r in runs:
        by_issue.setdefault(r["issue_id"], []).append(r)
    minutes = {"specify": 9, "implement": 22, "bugfix": 14, "docs": 4, "research": 11, "flaky": 7, "broken": 0}
    effort = {"specify": "high", "implement": "medium", "bugfix": "high", "docs": "low", "research": "medium", "flaky": "medium"}
    issue_end = {}
    for issue_id, rs in by_issue.items():
        # A start during the working day, skewed toward recent days.
        day = DAYS - 1 - int(random.betavariate(1.3, 1.0) * (DAYS - 0.5))
        while (now - timedelta(days=day)).weekday() >= 5 and random.random() < 0.8:
            day = DAYS - 1 - int(random.betavariate(1.3, 1.0) * (DAYS - 0.5))
        t = (now - timedelta(days=day)).replace(hour=random.randint(6, 16), minute=random.randint(0, 59), second=random.randint(0, 59))
        if t > now - timedelta(hours=3):
            t = now - timedelta(hours=random.randint(3, 20))
        for r in rs:
            mean = minutes.get(r["rule_name"] or "default", 12)
            dur = timedelta(seconds=random.randint(20, 90)) if r["status"] != "succeeded" and mean == 0 else timedelta(minutes=max(1.0, random.gauss(mean, mean / 3)))
            start, end = t, t + dur
            db.execute("update run_history set started_at=?, completed_at=?, dispatched_at=?, configured_model=?, configured_effort=? where id=?",
                       (iso(start), iso(end), iso_ns(start - timedelta(seconds=2)), r["reported_model"] or "", effort.get(r["rule_name"], ""), r["id"]))
            events = db.execute("select seq from run_events where dispatch_id=? order by seq", (r["dispatch_id"],)).fetchall()
            for i, e in enumerate(events):
                at = start + dur * ((i + 1) / (len(events) + 1))
                db.execute("update run_events set at=?, completed_at=? where dispatch_id=? and seq=?", (iso_ns(at), iso(end), r["dispatch_id"], e["seq"]))
            t = end + timedelta(minutes=random.randint(1, 40))
        issue_end[issue_id] = end
    for issue_id, end in issue_end.items():
        for table, col in (("session_metadata", "updated_at"), ("budget_hold_notices", "noticed_at"), ("issue_outcomes", "observed_at"),
                           ("parked_issues", "parked_at"), ("stage_hops", "hopped_at"), ("retry_entries", "dispatched_at")):
            db.execute(f"update {table} set {col}=? where issue_id=?", (iso(end + timedelta(seconds=30)), issue_id))
    db.execute("delete from retry_entries")
    total = sum((datetime.fromisoformat(r["completed_at"].replace("Z", "+00:00")) - datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))).total_seconds()
                for r in db.execute("select started_at, completed_at from run_history"))
    db.execute("update aggregate_metrics set seconds_running=?, updated_at=?", (total, iso(now)))
    db.commit()

    # The file tracker keeps its writes in memory, so the handoffs come from the log.
    # Most handed-off issues were merged since, a few still wait for a person.
    done = handed_off()
    path = os.path.join(STATE, "issues.json")
    issues = json.load(open(path))
    for issue in issues:
        end = issue_end.get(issue["id"])
        if end:
            issue["updated_at"] = iso(end)
        if issue["id"] in done:
            issue["state"] = "Done" if random.random() < 0.8 else "Human Review"
        elif not {"broken", "flaky"} & set(issue["labels"]):
            issue["state"] = "Cancelled"
    # Live issues for the running phase.
    base = len(issues)
    for i, (kind, title, blockers) in enumerate(LIVE, start=1):
        issues.append({
            "id": str(base + i), "identifier": f"LIVE-{i}", "title": title,
            "description": f"{title}.\n\n- Keep the change small\n- Add a `ui` test\n",
            "priority": 1 if i <= 3 else 3, "state": "To Do",
            "labels": [kind] + (["slow"] if kind in ("feature", "bug", "research", "documentation") else []),
            "issue_type": {"bug": "Bug", "feature": "Story"}.get(kind, "Task"),
            "url": f"https://tracker.example.invalid/LIVE-{i}",
            "blocked_by": [{"id": str(base + int(b.split('-')[1])), "identifier": b, "state": "To Do"} for b in blockers],
            "comments": [], "created_at": iso(now - timedelta(hours=2)), "updated_at": iso(now - timedelta(hours=1)),
        })
    json.dump(issues, open(path, "w"), indent=1)
    # A merged issue ended some hours after its handoff, not when the demo starts.
    for issue in issues:
        end = issue_end.get(issue["id"])
        if end and issue["state"] == "Done":
            merged = min(end + timedelta(hours=random.uniform(0.5, 20)), now - timedelta(hours=1))
            db.execute("insert or replace into issue_outcomes (issue_id, kind, observed_at, state) values (?, 'terminal', ?, 'Done')", (issue["id"], iso(merged)))
    # Compound Engineering skills as a real run records them.
    skills = {"specify": ["ce-plan", "ce-doc-review"], "implement": ["ce-work", "ce-simplify-code", "ce-code-review", "ce-commit"],
              "bugfix": ["ce-debug", "ce-work", "ce-commit"], "docs": ["ce-work", "ce-commit"], "research": ["ce-explain"], "flaky": ["ce-debug"]}
    for rule, names in skills.items():
        for (run_id,) in db.execute("select id from run_history where rule_name=?", (rule,)).fetchall():
            picked = [n for n in names if random.random() < 0.9] or names[:1]
            db.execute("update run_history set skills=? where id=?", (json.dumps([{"skill": n} for n in picked], separators=(",", ":")), run_id))
    # Real deployments run several agents; the model decides which one a run used.
    agents = {"claude-opus-5-5": "claude-code", "claude-sonnet-5-5": "claude-code", "claude-haiku-5-5": "claude-code",
              "gpt-5.1-codex": "codex", "gemini-3.5-flash": "opencode", "": "copilot-cli"}
    for model, agent in agents.items():
        db.execute("update run_history set agent_adapter=? where reported_model=?", (agent, model))
    db.commit()
    states = {}
    for issue in issues:
        states[issue["state"]] = states.get(issue["state"], 0) + 1
    print("phase B: tracker", states)


def write_live_workflow():
    # Slow turns keep the live runs visibly in progress for hours.
    workflow(os.path.join(STATE, "WORKFLOW.md"), poll=15000, conc=3, delay=900000, backoff=300000, loop=True)


def open_pull_requests():
    """Give issues waiting in Human Review a pull request, so startup recovery watches it."""
    db = sqlite3.connect(os.path.join(STATE, "state.db"))
    succeeded = {row[0] for row in db.execute("select distinct issue_id from run_history where status='succeeded'")}
    path = os.path.join(STATE, "issues.json")
    issues = json.load(open(path))
    waiting = [i for i in issues if i["id"] in succeeded and i["state"] == "Human Review"]
    # Too few handoffs left waiting: reopen merged ones until every scenario has an issue.
    for issue in issues:
        if len(waiting) >= len(PULL_REQUESTS):
            break
        if issue["id"] in succeeded and issue["state"] == "Done":
            issue["state"] = "Human Review"
            db.execute("delete from issue_outcomes where issue_id=?", (issue["id"],))
            waiting.append(issue)
    db.commit()
    json.dump(issues, open(path, "w"), indent=1)
    pushed = datetime.now(timezone.utc) - timedelta(hours=3)
    owner, repo = PROJECT.split("/")
    for issue, number in zip(waiting, PULL_REQUESTS):
        folder = os.path.join(STATE, "workspaces", issue["identifier"], ".sortie")
        os.makedirs(folder, exist_ok=True)
        json.dump({"branch": f"sortie/pr-{number}", "sha": f"{number:04d}abcdef0123456789abcdef0123456789ab",
                   "pushed_at": iso(pushed), "pr_number": number, "owner": owner, "repo": repo},
                  open(os.path.join(folder, "scm.json"), "w"))
        print(f"pull request {number}: {issue['identifier']} {issue['title']}")


if __name__ == "__main__":
    run_phase_a()
    run_phase_b()
    write_live_workflow()
    open_pull_requests()
    shutil.rmtree(SEED, ignore_errors=True)
    shutil.move(STATE, SEED)
