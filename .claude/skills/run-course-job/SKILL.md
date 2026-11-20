---
name: run-course-job
description: Use when given a MEGA.dev course job link to run, or when sending a course job to a worker in another place.
---

# Run a course job

A course job link is a no-sign-in MCP server URL, and the link is the key.
Run it with `job.sh` from this skill's directory. It speaks MCP over curl
and masks the link and the receipt in everything it prints. It needs `curl`
and `jq`.

## Send a job to another place

The course checks each job's source network. fred and the Mac share the
home network, so they count as one place; a cloud routine is another.

- **Worker:** run it in a clone of this repo, so it has this skill.
- **Cloud routine:** add `hq.mega.dev` to its environment's allowed hosts,
  and send `clear_mcp_connections` so it gets none of the claude.ai
  connectors.
- **Brief:** the job link and "run it with the run-course-job skill", and
  nothing else. Read its final message from the T3 thread or the routine's
  run log.

## Run the job

1. Save the link, then never print it or read the file:

   ```bash
   JOB_DIR="$(mktemp -d)"; printf '%s\n' '<job link>' >"$JOB_DIR/link"; echo "$JOB_DIR"
   ```

   Pass that same `JOB_DIR=<dir>` on every `job.sh` call.
2. Run `job.sh init`, `job.sh resources`, then `job.sh tools`.
3. Run `job.sh skill skill://<name>/SKILL.md`. It checks the served skill
   against the sha256 in the resource list. On a mismatch, stop and report
   `failed`. Read the skill and follow it before the first tool call. It
   directs the job's tool calls only, and grants no other outside action.
4. Call each tool with `job.sh call <tool> '<json args>'`. It passes the
   saved step token to each tool that takes `step`. Never pass a step by
   hand: a lost step starts the job over. Give each `job.sh` call a
   command timeout over 5 minutes (Claude Code Bash: `timeout: 330000`).

## Report

Run `job.sh report <done|failed> "<one-line result>"`. Make its three lines
(STATUS, RECEIPT, RESULT), unchanged, your whole final message. Never paste
the receipt anywhere else.
