---
key: SCHED-4412
title: "colours: move hard-coded colours to design tokens"
status: open
labels: [agent-ready, from:product]
---

## Intent
Replace every raw hex, rgb or named colour in components with the matching `--color-*` token, so
colour comes only from tokens (DES-2). Nothing visible changes.

## Acceptance
- Given the component sources, when they are searched for hex, rgb() or named colours, then none are found.
- Given any page before and after the change, when screenshots are compared, then they match pixel for pixel.
- Given a colour with no exact token, when it is migrated, then it maps to the nearest existing palette token and the tokens file does not get a new colour value.

## Boundaries
- Must not add colours to the palette or change any token's value (DES-2).
- Must not change layout, type or spacing.

Allowed by AUT-1 (bringing code in line with a rule in `specs/` when nothing visible changes).

## Request
Components still carry raw hex values. Move every colour to the tokens in specs/design.md (DES-2). Nothing visible changes. Until this ships, a new colour scheme cannot be a token set: the raw values would not follow it.
