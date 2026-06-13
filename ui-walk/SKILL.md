---
name: ui-walk
description: Drive the running app with Playwright through every surface and state of a feature, saving an ordered, numbered screenshot folder the user can flip through like a story. Use when the user asks to "walk the UI", "screenshot every state", "show me what X looks like", or wants visual evidence before/after an audit or fix pass. Captures only — it does not judge (pair with page-audit) and does not fix.
---

# UI walk

You're being asked to produce visual evidence of a feature: an **ordered
folder of numbered screenshots** that reads like a story — every surface, in
user-flow order, in every state that matters. The folder is the deliverable.
A human flips through it; an audit skill (e.g. `page-audit`) can consume it;
re-running it after fixes regenerates the same sequence for comparison.

## Process

1. **Discover how to drive the app.** Check the project's own docs/skills
   first (CLAUDE.md, a `run` skill, existing verify/E2E scripts) for: how the
   dev server starts, the login route and field selectors, and a seed/fixture
   login that survives the run. Never hardcode credentials — read them from
   wherever the project keeps its test fixture.
2. **Plan the shot list before writing code.** For each surface in the
   feature, list the *states*: empty, populated, mid-flow (a review screen
   with rows still needing attention), fixed/ready, success, collapsed vs
   expanded, error/warn affordances. Edge states are usually the point — a
   single happy-path shot hides everything an audit would care about.
3. **Write ONE self-contained walk script** (see conventions below), run it,
   and then **read the key screenshots back with vision yourself** before
   handing over. Confirm each shows the state you intended — a mid-animation
   capture or a blank panel reads as a bug to the user when it's actually a
   timing artifact. Call out capture artifacts explicitly so nobody chases
   ghosts.
4. **Hand over the folder** with a one-line caption per shot (or per group),
   and offer the audit as the natural next step.

## Walk-script conventions

- **Numbered, self-ordering output.** A `snap(name)` helper that prefixes an
  auto-incrementing `01-`, `02-`… and logs each path. Wipe and recreate the
  output folder at the start of every run (`rm -rf` + `mkdir`) so the folder
  is always canonical for the current code — never a mix of runs. Output
  lives under the project's gitignored tmp/scratch dir, one subfolder per
  walk (`tmp/<feature>-walk/`).
- **Real UI only.** Drive the actual running app through real logins and
  real clicks. Never screenshot mocked HTML or storybook-style isolates —
  the walk exists to show what users actually get.
- **Full page vs component clips.** `page.screenshot({ fullPage: true })`
  for orientation shots; `locator.screenshot()` to clip a card, modal, or
  widget when the detail is the subject.
- **Wait out animations.** Panels animating in capture as semi-transparent
  ghosts. After opening a modal/popover, wait for the state you need plus a
  short settle (`waitForTimeout(200–400)`) before snapping.
- **Locator hygiene.** Prefer accessible selectors (`getByRole`,
  `getByLabel`). Remember `getByRole(..., { exact: true })` is
  **case-sensitive** — derive display labels the same way the app does
  (e.g. an email-derived label may be capitalised), don't guess casing.
- **Fresh context for first-visit states.** Onboarding widgets, coachmarks
  and celebration states are usually gated on `localStorage` — capture them
  from a brand-new `browser.newContext()`, not the session you've been
  driving.
- **Conditional UI needs both branches.** If a promo card replaces a quiet
  button (or vice versa), the script should handle whichever renders —
  otherwise the walk breaks the day the product behaves as designed.
- **Create the data you need through the UI when the flow IS the subject**
  (filling the form is the screenshot); seed minimally otherwise. Either
  way, **track every id you create and delete it in a `finally` block** —
  the walk must be idempotent and leave the fixture exactly as found.
- **Ephemeral accounts for fresh-tenant states.** If signup requires email
  confirmation, create the user via the backend's admin API
  (pre-confirmed), log in through the real login page, and delete the
  account in cleanup.
- **Be cost-aware.** If a state requires a paid API call (an AI parse, a
  geocode), use the smallest input that produces a real result, once per
  run — and say so in the script header.

## What NOT to do

- Don't judge or fix during the walk — capture first; audits and fixes are
  separate passes (the folder makes them better).
- Don't commit screenshots; the script is committable, its output is not.
- Don't leave behind anything the walk created — data, accounts, files.
- Don't screenshot states you constructed by editing the DOM or DB into
  shapes the app can't actually reach.
- Don't ship a folder you haven't looked at — viewing the shots back is
  part of the walk, not optional.
