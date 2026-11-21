---
key: IN-6187-calendar
title: "confirmation email: 'Add to calendar' opens a blank page"
status: open
labels: [agent-ready, from:support]
sources: [IN-6187]
---

## Intent
The "Add to calendar" link in the booking confirmation email adds the booking to the person's
calendar instead of opening a blank page. Split from IN-6187, which merged two problems.

## Acceptance
- Given a confirmation email, when the person opens "Add to calendar", then they get the booking as a calendar event with its start and end in UTC with zone (ADR-0001).
- Given the same booking added twice, when the calendar imports it, then it carries the booking's stable id and does not make a second event (ADR-0002).
- Given the link, when it is opened, then it does not ask for a login or show any other booking.

## Boundaries
- Must not change calendar sync for connected calendars; that stays one-way (ADR-0002).
- Must not change the cancel link (SCHED-4498 covers it).

Allowed by AUT-1 (bug fixes and small features inside the specs, with a test that shows the change).

## Request
Ticket: the client's logo is stretched in the booking confirmation email, and the 'Add to calendar' link in the same email opens a blank page. (reporter: merged by tove · 2 reports)
