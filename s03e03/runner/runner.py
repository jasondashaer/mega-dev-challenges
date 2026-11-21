"""Out-of-office runner: polls the course tracker, acknowledges each new issue at once, and hands the work to headless Claude one issue at a time."""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

HOME = os.path.expanduser("~")
REPO = os.environ.get("OOO_REPO", f"{HOME}/out-of-office/mega-dev-challenges")
APP = f"{REPO}/s03e03/sched-prod-api"
STATE = os.environ.get("OOO_STATE", f"{HOME}/out-of-office/state")
ENV_FILE = os.environ.get("OOO_ENV", f"{HOME}/.config/out-of-office/env")
POLL = int(os.environ.get("OOO_POLL_SECONDS", "20"))
# A waiting issue is re-checked this often, because its condition can come true without a new comment.
WAIT_RECHECK = int(os.environ.get("OOO_WAIT_RECHECK_SECONDS", "180"))
RUN_TIMEOUT = int(os.environ.get("OOO_RUN_TIMEOUT_SECONDS", "1500"))


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def record(kind: str, **data) -> None:
    with open(f"{STATE}/events.jsonl", "a") as f:
        f.write(json.dumps({"at": now(), "kind": kind, **data}) + "\n")


def load_env() -> dict | None:
    # The round hands out the tracker address and token only when it opens; until then the runner idles.
    if not os.path.exists(ENV_FILE):
        return None
    env = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k] = v
    return env if env.get("TRACKER_URL") and env.get("TRACKER_TOKEN") else None


def call(env: dict, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        env["TRACKER_URL"].rstrip("/") + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {env['TRACKER_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def load_state() -> dict:
    try:
        with open(f"{STATE}/seen.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(seen: dict) -> None:
    tmp = f"{STATE}/seen.json.tmp"
    with open(tmp, "w") as f:
        json.dump(seen, f, indent=1)
    os.replace(tmp, f"{STATE}/seen.json")


def newest_verbs(env: dict) -> dict:
    verbs = {}
    for line in call(env, "GET", "/shiplog").get("text", "").splitlines():
        parts = [p.strip() for p in line.split("·")]
        if len(parts) >= 2 and parts[0].startswith("#"):
            verbs[parts[0].lstrip("#")] = parts[1]
    return verbs


def work(issue: dict, reason: str) -> int:
    n = issue["n"]
    prompt = (
        f"You are the out-of-office agent for sched-prod-api. Work tracker issue #{n} now ({reason}).\n"
        "Follow the triage skill, section 'Running alone', and s03e03/sched-prod-api/AGENTS.md. "
        "Use the `tracker` and `ship` commands on PATH; never read or print their tokens.\n"
        f"The issue as the tracker gave it a moment ago:\n{json.dumps(issue, indent=1)}"
    )
    out = f"{STATE}/runs/{n}-{now().replace(':', '')}.log"
    record("run-start", issue=n, reason=reason, log=out)
    with open(out, "w") as log:
        try:
            p = subprocess.run(
                ["claude", "-p", prompt, "--dangerously-skip-permissions", "--output-format", "text"],
                cwd=REPO, stdout=log, stderr=subprocess.STDOUT, timeout=RUN_TIMEOUT,
            )
            code = p.returncode
        except subprocess.TimeoutExpired:
            code = -1
    record("run-end", issue=n, code=code)
    return code


def tick(env: dict, seen: dict) -> None:
    issues = call(env, "GET", "/issues").get("issues", [])
    # Acknowledge every new issue before any long run, so each one is picked up within minutes even in a burst.
    for i in issues:
        key = str(i["n"])
        if key not in seen:
            call(env, "POST", f"/issues/{i['n']}/comments",
                 {"body": f"Picked up by the out-of-office agent at {now()}. Working it now; the ship log will say how it lands."})
            seen[key] = {"handled": 0, "acked": now()}
            record("ack", issue=i["n"], title=i["title"])
            save_state(seen)
    verbs = newest_verbs(env)
    for i in sorted(issues, key=lambda x: x["n"]):
        key = str(i["n"])
        others = [t for t in i.get("thread", []) if t.get("by") != "agent"]
        s = seen[key]
        reason = None
        if s["handled"] == 0:
            reason = "new issue"
        elif len(others) > s.get("others", 0):
            reason = "new entry from " + ", ".join(sorted({t["by"] for t in others[s.get("others", 0):]}))
        elif verbs.get(key) == "waiting" and time.time() - s.get("last", 0) > WAIT_RECHECK:
            reason = "re-check whether the held change's condition is met"
        elif not i.get("closed") and key not in verbs and s.get("tries", 0) < 3:
            reason = "no ship line yet after the last run"
        if not reason:
            continue
        code = work(i, reason)
        # Re-read the issue, so entries the run itself caused (or that landed during it) are not worked twice.
        fresh = call(env, "GET", f"/issues/{i['n']}")
        s.update(handled=s["handled"] + 1, others=len([t for t in fresh.get("thread", []) if t.get("by") != "agent"]),
                 last=time.time(), tries=s.get("tries", 0) + 1 if key not in newest_verbs(env) else 0, code=code)
        save_state(seen)
        return  # one run per tick, then poll again so new issues are acknowledged first


def main() -> None:
    os.makedirs(f"{STATE}/runs", exist_ok=True)
    seen = load_state()
    record("start", repo=REPO)
    while True:
        env = load_env()
        if env:
            try:
                tick(env, seen)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                record("tracker-error", error=str(e))
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
