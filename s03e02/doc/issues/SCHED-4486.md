---
key: SCHED-4486
title: "audit log: how long to keep entries"
status: open
labels: [needs-human, from:finance]
---

## Question
Should audit log entries be deleted after 90 days, as finance asks?

## Options
1. Keep 90 days, then delete, as asked.
2. Keep 90 days in the live log, then move older entries to an archive and delete nothing.
3. Keep entries as now, with no limit.

## Recommendation
Option 2, unless finance or legal confirm that the deletion is required.

## Why
Because deleting stored data needs a person (AUT-2), and a deletion cannot be undone. The audit log
may also be the record behind invoices, which needs a person too (AUT-2).

## Request
Keep audit log entries for 90 days, then delete them.
