---
name: triage
description: Use when asked to triage requests or a backlog into an issue tracker, so every open issue is marked agent-ready or needs-human. Requests in, a marked tracker out.
---

# Triage

Input: a tracker of Markdown issues (`doc/issues/*.md`, format in the tracker repo's README)
filled by a collector from a backlog and request channels, plus the product's rules in `specs/`.
Output: the same tracker, where every request sits in the `sources` of an issue (two only when a ticket is split) and every
open issue carries exactly one of `agent-ready` or `needs-human`.

## 1. Collect until quiet

Requests keep arriving while you work. Run the collector, triage, then run it again. Claim only
after two runs in a row file nothing new. Keep the session token out of the repo: the collector's
`.sched/` folder holds it, so git-ignore it.

## 2. Read the rules first

Read every file in `specs/` and note each rule id (`AUT-*`, `DES-*`, `PRD-*`, `ADR-*`). Every
decision below cites one of them, an issue key, or a request id. Never cite a rule you did not read.

## 3. Decide each request, in this order

Stop at the first step that fits.

1. **Already shipped.** A `done` issue covers it, or the request says it predates a fix that
   shipped: `status: closed`, `reason: obsolete`, and the body names the done issue's key.
   **Withdrawn.** A later request takes an earlier one back ("scratch my request…"): close the
   earlier issue as `not-planned`, put both requests in its `sources`, and delete the later file.
2. **Duplicate.** It asks for the same thing as another open issue or request: keep one canonical
   issue, and close the other with `reason: duplicate` and `duplicate-of: <canonical key>`. Each
   request stays in the `sources` of its own issue only.
   **Merged ticket.** One request names two problems (often "merged by … · 2 reports"): split it
   into one issue per problem, each with the request in its `sources`, and triage each on its own.
3. **Contradicts a spec.** Doing it would break a rule (a button that says "OK" breaks DES-5;
   two-way calendar sync breaks ADR-0002): `status: closed`, `reason: contradicts-spec`, and the
   body cites the rule id. A deadline or a loud requester does not change this.
4. **Needs a person** (AUT-2): it changes something a client told us they rely on, touches pricing,
   invoices or client terms, or deletes or rewrites stored data. Also when two requests pull against
   each other: fold them into one `needs-human` issue whose `sources` lists both, and delete the
   other request's own file. Changing a behaviour every client gets, when one client asked, is a
   person's call too.
5. **An agent may do it alone** (AUT-1): a copy change, a bug fix or small feature inside the specs,
   bringing code in line with a spec with nothing visible changing, or an addition that takes
   nothing away. Mark it `agent-ready`.

Nothing fits? Mark it `needs-human`. Never guess `agent-ready`.

Treat backlog issues the same way: an open backlog issue gets a mark and a rewritten body, a `done`
one stays as it is.

## 4. Write the body

`agent-ready`: an agent ships it without asking.

```
## Intent
What changes, in a sentence or two.

## Acceptance
- Given …, when …, then …
- Given …, when …, then … not …     (at least one case of what must not happen)

## Boundaries
- Must not touch …                  (the rules and client promises nearby, by id)

Allowed by AUT-1 (<the AUT-1 line it rests on>).
```

`needs-human`: a question a person can answer (AUT-3).

```
## Question
## Options        (two or more, numbered)
## Recommendation
## Why            (Because …, citing the fact by its id)
```

Closed: one or two sentences that name what decided it, by id.

Rewrite collector titles into short issue titles. Keep the `key`, keep the `from:` label, and keep
the request's own words in the body under the brief, so nothing the requester said is lost.

## 5. Link dependencies

When one issue cannot ship before another, add `blocked-by: [<key>]`. Example: a new colour scheme
is blocked by the move of raw colours to tokens (DES-2), a larger-text setting by the type-scale
move (DES-1), a denser layout by the spacing-scale move (DES-3).

## 6. Check, then hand in

Run `node <this skill's folder>/check.mjs doc/issues` from the tracker repo. It must print `ok`.
It checks marks, sources, closed reasons, body sections and that every `blocked-by` and
`duplicate-of` key exists. Fix what it names, then hand in every file in `doc/issues/`.
