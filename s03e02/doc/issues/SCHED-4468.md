---
key: SCHED-4468
title: "spacing: move hard-coded margins to the spacing scale"
status: open
labels: [agent-ready, from:product]
---

## Intent
Replace every margin and padding set in a component with a step of the 4 px spacing scale in the
tokens (DES-3). Nothing visible changes.

## Acceptance
- Given the component sources, when they are searched for margin and padding values, then every one is a spacing-scale token.
- Given any page before and after the change, when screenshots are compared, then they match.
- Given a value off the 4 px scale, when it is migrated, then it maps to the nearest step and the scale does not get a new step.

## Boundaries
- Must not change the spacing scale itself (DES-3).
- Must not change colours or type.

Allowed by AUT-1 (bringing code in line with a rule in `specs/` when nothing visible changes).

## Request
Some components still set their own margins and padding. Move every one to the 4 px scale in the tokens (DES-3). Nothing visible changes. Until this ships, a denser layout cannot come from the spacing scale.
