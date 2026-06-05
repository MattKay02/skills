---
name: page-audit
description: Audit a UI page or surface and return concrete prioritized findings. Use when the user asks to audit, review, critique, or "look at" a page or screen — usually with a screenshot, route, or component name. Does NOT redesign and does NOT fix code; produces a punch list.
---

# Page audit

You're being asked to audit a UI surface. The output should help the user spot fixable issues without prescribing a redesign.

## Process — walk these axes in order

1. **Information hierarchy** — does the layout reflect what's most important? Does the user's eye land on the actionable surfaces first, or do signals/context dominate? What's the section ordering implying about priority?
2. **Content accuracy** — does the copy match the data and system state? Are example items in headers actually present in the seed/DB? Are referenced links/tabs/concepts still alive on this page (or migrated elsewhere)? Is anything making promises the system can't keep?
3. **Visual consistency** — patterns repeated correctly across analogous surfaces? Same empty states / cards / spacing / pills shape between sections of the same page? Same patterns as elsewhere in the app for the same conceptual gap?
4. **Layout density at edge counts** — what does this page look like with 0 / 1 / 2 / exactly N / N+1 items? Empty grid slots, sparse rows, awkward truncation, overflow. The screenshot shows one state — extrapolate to the others.
5. **Copy** — internal jargon leaking, references to retired concepts, awkward conjunctions, inconsistent voice between sections, descriptors that compete with each other for the same eye-line.
6. **Affordance clarity** — what's clickable, what's the obvious next action, what's labelled but does nothing, what's the same shape as something clickable but isn't.
7. **Cross-page coherence** — does this page contradict or duplicate state shown elsewhere in the app? Stale references to renamed surfaces? Concepts framed differently here than on related surfaces?

## Verify before reporting

Before tagging anything as a bug, grep / open the relevant component to confirm. "I think this copy is wrong" is much weaker than "src/components/Foo.tsx:125 says 'X' but it migrated to Y per ADR Z." Concrete file:line citations turn an audit into a fixable punch list.

If a project has docs (architecture decisions, design system, README), check whether your finding contradicts a documented intent before reporting — sometimes the "issue" is a deliberate design call.

## Output format

Group findings by severity. Each finding: one short description + concrete suggested fix or a clarifying question. Cite file paths and line numbers wherever possible.

- **P1** — bugs, data inaccuracies, misleading content (must-fix)
- **P2** — layout / visual issues affecting usability or visual rhythm
- **P3** — copy, density, polish

Aim for 8–15 findings. If a finding is genuinely subjective, mark it `(taste)` so the user can pick it up if they agree, but the call is theirs. Don't manufacture findings to hit the count target — 8 strong is better than 14 padded.

## What NOT to do

- Don't propose redesigns unless explicitly asked.
- Don't audit pages other than the one requested.
- Don't write or edit code in the audit pass — fix on follow-up.
- Don't flag missing infrastructure that's deliberately out of scope (e.g. auth/error-handling on a demo, telemetry on a prototype).
- Don't comment on things outside what the screenshot or component actually shows.
