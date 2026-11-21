---
key: SCHED-4446
title: "CSV export: add a UTC offset column next to start and end"
status: open
labels: [agent-ready, from:analytics]
---

## Intent
Add a UTC offset column to the CSV export next to the start and end times, so tools reading it know
the zone (ADR-0001: data that leaves the product says which zone a time is in).

## Acceptance
- Given a booking at 10:00 Europe/Berlin in winter, when the CSV is exported, then the new offset column reads +01:00.
- Given any export, when it is compared with one made before the change, then every existing column is there with the same values, in the same relative order, and not one is lost (PRD-3).
- Given a booking across a daylight-saving change, when exported, then its offset is the one in force at its start.

## Boundaries
- Must not change the existing start and end columns or their format.
- Must not remove or reorder any column (PRD-3).

Allowed by AUT-1 (new columns, filters or fields that add to what is there and take nothing away).

## Request
Start and end times in the CSV export have no offset, so every tool that reads them has to guess the zone. Add a UTC offset column next to them; the start and end columns stay as they are.
