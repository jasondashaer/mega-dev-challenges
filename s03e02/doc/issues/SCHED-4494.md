---
key: SCHED-4494
title: "week view: a booking across midnight shows on its first day only"
status: open
labels: [agent-ready, from:support]
---

## Intent
A booking that runs past midnight shows on every day it covers in week view.

## Acceptance
- Given a booking from 23:00 to 01:00, when week view shows that week, then it appears at the end of its first day and the start of the second.
- Given that booking, when it is opened from either day, then it is the same single booking.
- Given that booking, when the bookings list or an export is read, then it is still one booking, not split into two (PRD-1).
- Given a viewer in another zone, when the booking does not cross midnight in their zone, then it shows on one day only (PRD-2).

## Boundaries
- Must not split a booking into two or change its slot (PRD-1).
- Must not change how times are stored (PRD-2, ADR-0001).

Allowed by AUT-1 (bug fixes and small features inside the specs, with a test that shows the change).

## Request
A booking from 23:00 to 01:00 shows on its first day and is missing from the second.
