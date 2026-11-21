---
key: SCHED-4418
title: "week view: first day of the week follows the account locale"
status: open
labels: [agent-ready, from:support]
---

## Intent
Week view starts on the first day of the week that the account's locale defines, not always on Sunday.

## Acceptance
- Given an account with locale en-US, when week view opens, then the week starts on Sunday.
- Given an account with locale de-DE, when week view opens, then the week starts on Monday.
- Given a booking on any day, when the start day changes, then the booking still shows on the same date and time, not shifted to another day.

## Boundaries
- Must not change how times are stored or converted (PRD-2, ADR-0001).
- Must not change the month view or exports.

Allowed by AUT-1 (bug fixes and small features inside the specs: an Account has a locale).

## Request
Week view always starts on Sunday. It should start on the day the account locale says.
