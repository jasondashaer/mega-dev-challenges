---
key: SCHED-4498
title: "confirmation email: the cancel link opens the login page"
status: open
labels: [agent-ready, from:support]
---

## Intent
The cancel link in the booking confirmation email opens that booking without a login, the way the
reminder email's cancel link already does.

## Acceptance
- Given a confirmation email, when the person who booked opens its cancel link, then the booking opens and can be cancelled without a login.
- Given the reminder email, when its cancel link is opened, then it behaves as it does today.
- Given a cancel link, when it is opened, then it opens only its own booking and not the account, the calendar or other bookings.

## Boundaries
- Must not change the reminder email's link.
- Must not open staff or account pages without a login.

Allowed by AUT-1 (bug fixes and small features inside the specs, with a test that shows the change).

## Request
The cancel link in the booking confirmation email asks for a login. People who booked have no account. The cancel link in the reminder email opens the booking without one, as it should.
