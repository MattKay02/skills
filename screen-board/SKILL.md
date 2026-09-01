---
name: screen-board
description: Build and maintain a pan-and-zoom board of every screen in an app — full-page captures laid out in reading order, each paired with what the screen is FOR and what good looks like — published as one design canvas that updates in place instead of becoming a new link. Use when the user asks for a "screen board", "screen map", "board of all the screens", a Figma-style overview of the product, or wants an existing board refreshed. Also carries the staleness check that says which screens' DESCRIPTIONS may have gone out of date. Documents an existing app — it does not design new screens, and it does not judge the ones it captures (pair with page-audit for that).
---

# Screen board

You're being asked to produce a **map of a product you can scan**: every screen
as it actually looks, laid out so the flow is visible, with a short piece of
writing beside each one saying why that screen exists. It lives as a single
published canvas with a stable link, so refreshing it updates the same board
rather than scattering versions.

The screenshots are the easy half. The writing is the deliverable.

## Process

1. **Enumerate the real routes** from the router, not from memory — every page
   file, including the dynamic ones. Then decide with the user what is in
   scope: internal admin and operator tooling usually is *not*, because a board
   about what a product does is a different thing from a board about how its
   owner runs it. Say what you're excluding and why.
2. **Write the content before the mechanism.** For each screen, two fields:
   - **The job** — why it exists, in the product's terms. If it reads like a
     caption of the screenshot, rewrite it.
   - **Done right** — what success looks like, stated so *failure* is
     recognisable. "The manager is willing to put their name to it" makes
     "clicking confirm without reading" legible as the screen failing. A goal
     you cannot fail is not a goal.
   Keep this in one config file, separate from the generator, so a diff shows
   which *descriptions* changed rather than which pixels did.
3. **Capture full-page against a populated fixture.** Discover how to drive the
   app from the project's own docs and fixtures (see `ui-walk` — it is the same
   discovery problem, and if the project already has a walk script, reuse it).
   Full page, not the viewport: the board exists to show the screen as someone
   actually meets it. Cap the height rather than the quality — past ~2500px a
   screen is a long table nobody reads at thumbnail size.
4. **Lay it out in bands, not columns.** A band is one subject, read left to
   right the way the work goes; you move *down* to change subject. Stacking a
   group vertically puts nine frames and twelve thousand pixels into one strip
   — you scroll forever and never see a relationship. Number the frames only in
   bands where left-to-right is a genuine sequence; numbering a set that isn't
   ordered invents structure that isn't there.
5. **Publish through the `design` skill** to a design canvas, and **republish
   to the same artifact URL** every time. Invoke that skill rather than
   hardcoding its helper's path — it moves between versions. Keep each image
   under ~70 KB; the whole document republishes on every save.
6. **Record what it was captured at**, per screen, and show it on the board.
   See "Keeping it current" — this is the part that stops the board becoming
   confidently wrong.

## Two failure modes, and only one of them is obvious

**A capture can silently photograph the wrong screen.** A route that redirects
(an onboarding wizard that skips once you're set up, an admin route that 404s
for the account you signed in as) produces a perfectly valid JPEG of somewhere
else, wearing the right caption. This has happened repeatedly and was never
caught by the capture succeeding, because it did succeed.

Two defences, both cheap: **refuse to save when the final URL isn't the one you
asked for**, and give screens that need a particular state a declared
precondition that sets it up and **restores it in a `finally`**. Leave the
fixture exactly as you found it or the run is a bug.

**The prose rots and nothing notices.** Screenshots regenerate in minutes; the
job and goal text was written against code that has since changed, and no test,
type or lint will ever tell you. This is the dangerous one, because a board
that reads confidently and is wrong is worse than no board.

## Keeping it current

Record the commit each screen was captured at — **per screen, not per run**,
since capture is usually resumable and a per-run stamp goes quiet about exactly
the screens that drifted furthest. Commit that record; a staleness file living
in a temp directory records nothing.

Then a `--stale` mode diffs those SHAs against HEAD and reports **which screens'
descriptions to re-read**. Two rules make that report worth reading:

- **Separate direct hits from shared breadth.** One edit to a shared component
  otherwise flags every screen with the same filenames repeated, which reads as
  noise and gets ignored — burying the one line that mattered. Name the shared
  files once, at the bottom.
- **Match routes exactly.** A `page.tsx` owns its own route, not its
  descendants. Prefix-matching makes a change to the app's root page flag every
  screen beneath it. Files that genuinely do own descendants — layouts, shared
  styles — belong in the shared bucket.

Wire the check into whatever bookends the user's sessions, as a **report and an
offer**, never an automatic refresh: it needs the app running and the fixture
seeded, which at the end of a session often isn't true, and a heavy ritual is a
skipped ritual.

## What NOT to do

- **Don't recreate the screens in code.** Capture the running app. A rebuilt
  screen is a copy that drifts from the thing it documents, and this board's
  only job is to be true.
- **Don't put implementation detail on it** — routes, tables, jobs, decision
  records. It drifts fastest, it belongs on a technical map, and if the project
  has one, duplicating it means two boards to keep true and neither will be.
- **Don't publish a new artifact each time.** Same URL, new version, or the
  board stops being a place and becomes a pile of links.
- **Don't caption a capture you haven't looked at.** Read the questionable ones
  back with vision before publishing — redirects, blank hero sections and
  mid-animation frames all produce valid-looking files.
- **Don't judge the screens.** This documents; `page-audit` critiques.
