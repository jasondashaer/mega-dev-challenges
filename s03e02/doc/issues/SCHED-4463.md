---
key: SCHED-4463
title: "type: move hard-coded font sizes to the type scale"
status: open
labels: [agent-ready, from:product]
---

## Intent
Replace every font size set in a component with the matching step of the type scale in the tokens
(DES-1). Nothing visible changes.

## Acceptance
- Given the component sources, when they are searched for font sizes, then every one is a type-scale token.
- Given any page before and after the change, when screenshots are compared, then they match.
- Given a size that is not on the scale, when it is migrated, then it maps to the nearest step and the scale does not get a new step.

## Boundaries
- Must not add steps to the type scale or change their values (DES-1).
- Must not change colours, layout or spacing.

Allowed by AUT-1 (bringing code in line with a rule in `specs/` when nothing visible changes).

## Request
Some components still set their own font sizes. Move every size to the type scale in the tokens (DES-1). Nothing visible changes. Until this ships, a text-size setting cannot follow the type scale.
