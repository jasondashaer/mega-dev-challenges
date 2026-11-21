---
key: SCHED-4431
title: "booking page: show remaining seats"
status: open
labels: [agent-ready, from:client]
---

## Intent
On the booking page, a group slot (more than one seat) shows how many seats are left.

## Acceptance
- Given a slot with 10 seats and 3 bookings, when the booking page shows it, then it reads 7 seats left.
- Given a slot that just filled, when the page refreshes, then it shows as full and cannot be booked.
- Given a one-seat slot, when the page shows it, then a seat count is not shown.

## Boundaries
- Must not change how seats are counted or how many a slot has.
- Must not change the booking flow or the API.

Allowed by AUT-1 (new columns, filters or fields that add to what is there and take nothing away).

## Request
Group slots should show how many seats are left.
