---
key: SCHED-4465
title: "API: add Retry-After to rate-limit replies"
status: open
labels: [agent-ready, from:client]
---

## Intent
A 429 reply from the API carries a Retry-After header with the seconds until the caller may try again.

## Acceptance
- Given a caller over the rate limit, when the API replies 429, then the reply has a Retry-After header with a whole number of seconds.
- Given a caller who waits that long, when they call again, then they are not rate-limited.
- Given a caller under the limit, when they call, then the reply does not carry Retry-After and is otherwise unchanged.

## Boundaries
- Must not change the rate limits, the 429 status or the reply body.

Allowed by AUT-1 (new columns, filters or fields that add to what is there and take nothing away).

## Request
When the API rate-limits a caller, the 429 reply does not say when to try again. Add a Retry-After header.
