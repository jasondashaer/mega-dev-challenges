---
key: SCHED-4452
title: "calendar sync: Outlook events arrive twice"
status: open
labels: [agent-ready, from:support]
---

## Intent
Each booking reaches a connected Outlook calendar once. Push every booking with its stable id so
Outlook treats a re-push as an update, not a new event (ADR-0002).

## Acceptance
- Given a connected Outlook calendar, when a booking is pushed and the sync runs again, then the calendar has one event for it.
- Given a booking that changes in sched-prod, when it is pushed again, then the existing Outlook event updates and no second event appears.
- Given an event edited in Outlook, when the sync runs, then sched-prod does not read it back or change the booking (ADR-0002).

## Boundaries
- Must not read events back from external calendars (ADR-0002, one-way sync).
- Must not change sync for other calendar providers beyond using the same stable id.

Allowed by AUT-1 (bug fixes and small features inside the specs, with a test that shows the change).

## Request
Some Outlook calendars show each booking twice after a sync.
