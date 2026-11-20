"""Away agent: answers course mail on its AgentMail inbox, acting alone on free acts and holding gated ones for the owner."""

import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import UTC, datetime

import httpx
from agentmail import AgentMail
from agentmail.core.api_error import ApiError

POLICY = {
    "post_status": "free",
    "ack_alert": "free",
    "archive_report": "free",
    "purge_cache": "free",
    "release_hold": "gated",
    "rotate_key": "gated",
}
ACT_RE = re.compile(r"\b(" + "|".join(POLICY) + r")\b")

INBOX = os.environ.get("AGENT_INBOX", "")
COURSE = {
    a.strip().lower()
    for a in os.environ.get("AGENT_COURSE_SENDERS", "away@mail.mega.dev").split(",")
    if a.strip()
}
NTFY = os.environ.get("NTFY_URL", "https://ntfy.kubew.dev")
PING_TOPIC = os.environ.get("NTFY_PING_TOPIC", "mega-away")
# Approvals come only from this topic, never from mail. On public ntfy.sh the topic name is the secret, so it lives in the env file.
OK_TOPIC = os.environ.get("NTFY_OK_TOPIC", "mega-away-ok")
POLL_SECONDS = int(os.environ.get("AGENT_POLL_SECONDS", "15"))
STATE = os.environ.get("AGENT_STATE", "/state")

log = logging.getLogger("away-agent")


def classify(text: str) -> tuple[str | None, str]:
    """Return (act, label). No act is "none"; several acts are gated, so an unclear ask waits for the owner."""
    acts = set(ACT_RE.findall(text))
    if not acts:
        return None, "none"
    if len(acts) == 1:
        act = acts.pop()
        return act, POLICY[act]
    return None, "gated"


def check(path: str) -> None:
    """Label practice messages from a JSON list of {id, text} and print them."""
    with open(path) as f:
        items = json.load(f)
    out = [
        {"id": i["id"], "act": classify(i["text"])[0], "label": classify(i["text"])[1]}
        for i in items
    ]
    print(json.dumps(out, indent=1))


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def record(kind: str, **data) -> None:
    with open(os.path.join(STATE, "events.jsonl"), "a") as f:
        f.write(json.dumps({"at": now(), "kind": kind, **data}) + "\n")


def load(name: str, default):
    try:
        with open(os.path.join(STATE, name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(name: str, value) -> None:
    tmp = os.path.join(STATE, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(value, f, indent=1)
    os.replace(tmp, os.path.join(STATE, name))


def sender(m) -> str:
    raw = (getattr(m, "from_", None) or "").strip()
    return (raw.split("<")[-1].rstrip(">") if "<" in raw else raw).strip().lower()


def ping(title: str, body: str, priority: str = "high") -> None:
    try:
        httpx.post(
            f"{NTFY}/{PING_TOPIC}",
            content=body.encode(),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": "robot",
                "Click": f"{NTFY}/{OK_TOPIC}",
            },
            timeout=15,
        ).raise_for_status()
    except httpx.HTTPError as e:
        log.warning("ntfy ping failed: %s", e)


class Agent:
    def __init__(self) -> None:
        self.mail = AgentMail(api_key=os.environ["AGENTMAIL_API_KEY"])
        self.handled: set[str] = set(load("handled.json", []))
        self.holds: dict = load("holds.json", {})
        self.ntfy_since = load("ntfy_since.json", "all")

    def reply(self, message_id: str, text: str, key: str) -> None:
        # AgentMail allows only [A-Za-z0-9-._~] in the key, and message ids carry <, > and @.
        key = hashlib.sha256(f"{INBOX}:{key}".encode()).hexdigest()
        self.mail.inboxes.messages.reply(
            inbox_id=INBOX, message_id=message_id, text=text, idempotency_key=key
        )
        record("reply", message_id=message_id, text=text)

    def done(self, ids: list[str]) -> None:
        self.handled.update(ids)
        save("handled.json", sorted(self.handled))
        try:
            self.mail.inboxes.messages.batch_update(
                inbox_id=INBOX, message_ids=ids, remove_labels=["unread"]
            )
        except ApiError as e:
            log.warning(
                "could not mark read: %s", getattr(e, "status_code", type(e).__name__)
            )

    def handle_mail(self, m) -> None:
        who = sender(m)
        text = (getattr(m, "extracted_text", None) or m.text or "").strip()
        record(
            "message", message_id=m.message_id, sender=who, subject=m.subject, text=text
        )
        if who not in COURSE or who == INBOX.lower():
            log.info("ignored mail from %s", who)
            return
        # Keep the order the acts appear in, because the course wants one reply line per ask.
        acts = list(dict.fromkeys(ACT_RE.findall(text)))
        if not acts:
            self.reply(
                m.message_id,
                "UP: I'm here and watching this inbox. No act asked, so I did nothing.",
                f"up-{m.message_id}",
            )
            log.info("answered a message with no act")
            return
        lines, gated = [], []
        for act in acts:
            if POLICY[act] == "free":
                # The acts are simulated: the course checks the decision and the reply, not a real cache or channel.
                record("act", act=act, message_id=m.message_id, by="agent")
                lines.append(f"DONE: {act}")
            else:
                gated.append(act)
                lines.append(f"HOLD: {act}")
        if not gated:
            self.reply(m.message_id, "\n".join(lines), f"done-{m.message_id}")
            log.info("did %s alone", ", ".join(acts))
            return
        # A retry after a failed reply must reuse the hold, not open a second one.
        hold_id = next(
            (h for h, v in self.holds.items() if v["message_id"] == m.message_id),
            f"h{len(self.holds) + 1}",
        )
        self.holds[hold_id] = {
            "message_id": m.message_id,
            "acts": gated,
            "subject": m.subject,
            "text": text,
            "at": now(),
            "state": "held",
        }
        save("holds.json", self.holds)
        what = ", ".join(gated)
        self.reply(m.message_id, "\n".join(lines), f"held-{m.message_id}")
        ping(
            f"Approve {what}? ({hold_id})",
            f"From {who}: {m.subject}\n{text[:500]}\n\nTo approve, publish to {OK_TOPIC}:  {hold_id} <code>\nTo refuse:  {hold_id} no",
        )
        log.info("held %s as %s", what, hold_id)

    def poll_mail(self) -> None:
        for item in (
            self.mail.inboxes.threads.list(inbox_id=INBOX, labels=["unread"]).threads
            or []
        ):
            try:
                thread = self.mail.threads.get(thread_id=item.thread_id)
                pending = [
                    m
                    for m in thread.messages
                    if "unread" in (m.labels or []) and m.message_id not in self.handled
                ]
                for m in pending:
                    self.handle_mail(m)
                    self.done([m.message_id])
            except Exception:
                # One bad thread must not stop the others; it stays unread and is retried next poll.
                log.exception("failed on thread %s", item.thread_id)

    def poll_approvals(self) -> None:
        r = httpx.get(
            f"{NTFY}/{OK_TOPIC}/json",
            params={"poll": "1", "since": self.ntfy_since},
            timeout=15,
        )
        r.raise_for_status()
        for line in r.text.splitlines():
            ev = json.loads(line)
            if ev.get("event") != "message":
                continue
            self.ntfy_since = ev["id"]
            self.apply_approval(ev.get("message", "").strip())
        save("ntfy_since.json", self.ntfy_since)

    def apply_approval(self, msg: str) -> None:
        parts = msg.split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in self.holds:
            log.info("ignored approval message %r", msg[:60])
            return
        hold_id, answer = parts[0], parts[1].strip()
        hold = self.holds[hold_id]
        if hold["state"] != "held":
            return
        record("owner", hold_id=hold_id, answer=answer)
        acts = hold["acts"]
        what = ", ".join(acts)
        if answer.lower() in ("no", "deny", "refuse"):
            hold["state"] = "refused"
            self.reply(
                hold["message_id"],
                "\n".join(f"REFUSED: {a}" for a in acts),
                f"refused-{hold['message_id']}",
            )
            ping(f"Refused {hold_id}", f"{what} refused and reported.", "default")
        else:
            hold["state"] = "done"
            for a in acts:
                record(
                    "act", act=a, message_id=hold["message_id"], by="owner", code=answer
                )
            self.reply(
                hold["message_id"],
                "\n".join(f"DONE: {a} CODE: {answer}" for a in acts),
                f"done-{hold['message_id']}",
            )
            ping(f"Done {hold_id}", f"{what} done and reported.", "default")
        save("holds.json", self.holds)

    def run(self) -> None:
        log.info(
            "watching %s for %s; pings %s/%s; approvals %s/%s",
            INBOX,
            ", ".join(sorted(COURSE)),
            NTFY,
            PING_TOPIC,
            NTFY,
            OK_TOPIC,
        )
        ping(
            "Away agent started",
            f"Watching {INBOX}. Gated: "
            + ", ".join(a for a, p in POLICY.items() if p == "gated"),
            "low",
        )
        while True:
            for step in (self.poll_mail, self.poll_approvals):
                try:
                    step()
                except Exception:
                    log.exception("%s failed", step.__name__)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if len(sys.argv) == 3 and sys.argv[1] == "check":
        check(sys.argv[2])
    else:
        Agent().run()
