---
name: screen-board
description: Build and maintain a board of every screen in an app, published as one page read top to bottom that updates in place instead of becoming a new link. Every screen and state as it actually looks, each with a pinned code and what the screen is FOR and what good looks like, plus a large view, two tables and a list of what isn't on it. Use when the user asks for a "screen board", "screen map", "board of all the screens", a Figma-style overview of the product, or wants an existing board refreshed. Also carries the staleness check that says which screens' DESCRIPTIONS may have gone out of date. Documents an existing app; it does not design new screens, and it does not judge the ones it captures (pair with page-audit for that).
---

# Screen board

You're being asked to produce a **map of a product you can scan**: every screen
as it actually looks, in the order the work goes, with a short piece of writing
beside each one saying why that screen exists. It lives as a single published
page with a stable link, so refreshing it updates the same board rather than
scattering versions.

The screenshots are the easy half. The writing is the deliverable.

## Process

1. **Enumerate the real routes** from the router, not from memory: every page
   file, including the dynamic ones. Then decide with the user what is in
   scope: internal admin and operator tooling usually is *not*, because a board
   about what a product does is a different thing from a board about how its
   owner runs it. Say what you're excluding and why.
2. **Then the states, not just the routes.** A route is one picture of many.
   The ones people actually get stuck on are the states: the wrong password,
   the expired code, nothing loaded, the confirm sheet, the dialog, the
   locked or paused app. List them beside the routes, and put the ones you
   can't draw in a "Not on the board" list with the reason (drawn by the
   phone, another app, a result only a real submission produces). A board of
   happy paths reads as finished and isn't.
3. **Write the content before the mechanism.** For each screen, two fields:
   - **The job**: why it exists, in the product's terms. If it reads like a
     caption of the screenshot, rewrite it.
   - **Done right**: what success looks like, stated so *failure* is
     recognisable. "The manager is willing to put their name to it" makes
     "clicking confirm without reading" legible as the screen failing. A goal
     you cannot fail is not a goal.
   Plus the way in, the way out and the obvious next step. Keep all of it in
   one config file, separate from the generator, so a diff shows which
   *descriptions* changed rather than which pixels did.
4. **Capture full-page against a populated fixture.** Discover how to drive the
   app from the project's own docs and fixtures (see `ui-walk`: it is the same
   discovery problem, and if the project already has a walk script, reuse it).
   Full page, not the viewport: the board exists to show the screen as someone
   actually meets it. Cap the height rather than the quality: past ~2500px a
   screen is a long table nobody reads at thumbnail size. For a Flutter app,
   see "Drawing instead of photographing" below.
5. **Draw at the narrowest phone you support.** A wider device hides overflows:
   one board shot on a 411pt-wide Android emulator showed a clean answer card
   that ran off the edge on a 393pt iPhone. Pick the size most of the product's
   users hold, say which on the board, and treat a layout error during capture
   as a finding, not noise.
6. **Lay it out as a document, not a canvas.** One page read top to bottom:
   - a masthead (how many screens, what it was drawn from, at which commit),
   - an index where **every screen has a pinned code** (`A2`: the letter is the
     section, the number its place), so a screen can be named in one word in
     conversation, an issue or a commit,
   - sections that open with a sentence on what they're for, then the screens
     as thumbnails cropped to one phone screen (badge the ones that are longer),
   - a **large view** for any screen: the whole capture beside its job, done
     right, way in, way out and next, with previous / next and the arrow keys,
   - two tables (what each screen is for; ways in, out and on), what building
     the board turned up, and what isn't on it.

   A pan-and-zoom canvas was tried first and was hard to get around: nothing
   could be read without zooming, and nothing could be found without panning.
   Number frames only in sections where order is a genuine sequence; numbering
   a set that isn't ordered invents structure that isn't there. Codes are
   pinned: a new screen takes the next free number and nothing is renumbered.
7. **Publish as one artifact page** and **republish to the same URL** every
   time. Keep each image under ~70 KB; the whole page republishes on every save.
8. **Record what it was captured at**, per screen, and show it on the board.
   See "Keeping it current": this is the part that stops the board becoming
   confidently wrong.

## Drawing instead of photographing (Flutter)

A Flutter app can be drawn rather than photographed: a test file (named so the
test runner skips it, e.g. `board.dart`, not `*_test.dart`) pumps the real app,
router, shell and gates included, at a phone's size, goes to a route or taps to
a state, and writes the widget tree's pixels to a PNG with
`RenderRepaintBoundary.toImage`. About a second a screen, no device, no dev
server, no seeded account, none of the emulator's own furniture (system bars, a
floating keyboard bar) in the picture, and every error, dialog and sheet a tap
away. This is capture, not recreation: it is the shipping widget tree, not a
copy of it. Keep the device for what only a device shows: push notifications,
the biometric prompt, links opened from other apps, the keyboard, platform
sheets.

What it takes, each learned the hard way:

- **Real fonts and icons.** The test engine draws every glyph as a box without
  them. Load the app's font files with `FontLoader`; for `google_fonts`, fetch
  its pinned files once and answer the `flutter/assets` channel with them under
  the names it looks for, as if bundled (with runtime fetching off, a style it
  can't find fails the test after the fact). Load the Material icon font from
  the SDK. Emoji stay boxes: the engine has no fallback font. Say so on any
  screen that shows them.
- **The view, not only the surface.** Set the test view's size, density and
  safe-area padding to the phone's; `MediaQuery` reads the view, and anything
  sized off the screen comes out wrong otherwise. Set the platform the board is
  read against (tests run as Android by default).
- **Recorded answers through one seam.** If the app's requests go through one
  HTTP client, replace its transport and nothing else, and serve the API's own
  answers, recorded once for a test login and scrubbed of personal data.
  Repositories, parsers and caches then run as on a phone. A fixture typed by
  hand to satisfy a widget leaves the optional fields empty, and the board
  shows an empty state as the design. Move recorded dates to the week the
  board is drawn in, in whole weeks.
- **Fixed pumps, never `pumpAndSettle`**, since a syncing screen animates.
  `toImage` inside `runAsync`, or it never completes under the fake clock.
  Keep local storage in memory: a file write begun under one test's fake clock
  never finishes, and the next test waits on it forever.
- **Full page by growing the phone** to the height of the longest vertical
  scroll, capped. Not for a sheet, dialog or notice: those are about the screen
  as it stands.
- **Nothing reaches a server.** That is what makes states that write (a
  sign-off sheet, a request form) safe to draw: open them, never confirm, and
  the fake transport makes even a confirm harmless.

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

Record the commit each screen was captured at, **per screen, not per run**,
since capture is usually resumable and a per-run stamp goes quiet about exactly
the screens that drifted furthest. Commit that record; a staleness file living
in a temp directory records nothing. Commit code before capturing, so the
stamps name a commit that has the code in the pictures.

Then a `--stale` mode diffs those SHAs against HEAD and reports **which screens'
descriptions to re-read**. Two rules make that report worth reading:

- **Separate direct hits from shared breadth.** One edit to a shared component
  otherwise flags every screen with the same filenames repeated, which reads as
  noise and gets ignored, burying the one line that mattered. Name the shared
  files once, at the bottom.
- **Match routes exactly.** A `page.tsx` owns its own route, not its
  descendants. Prefix-matching makes a change to the app's root page flag every
  screen beneath it. Files that genuinely do own descendants (layouts, shared
  styles) belong in the shared bucket.

Wire the check into whatever bookends the user's sessions, at the start (link
the board, say what's stale, so work starts from the whole app) and at the end,
as a **report and an offer**, never an automatic refresh. The end-of-session
check should also name any screen or state the session added that has no
capture yet. A refresh rewrites descriptions and republishes a page other
people read, so it needs a yes even where capture is cheap; where capture
needs the app running and a fixture seeded, at session end it often can't
run, and a heavy ritual is a skipped ritual. A declined refresh goes in the
session log as "board stale: A2, G4", so the next session sees it.

## What NOT to do

- **Don't recreate the screens in code.** Capture the running app, or draw its
  real widget tree. A rebuilt screen is a copy that drifts from the thing it
  documents, and this board's only job is to be true.
- **Don't put implementation detail on it**: routes, tables, jobs, decision
  records. It drifts fastest, it belongs on a technical map, and if the project
  has one, duplicating it means two boards to keep true and neither will be.
- **Don't publish a new artifact each time.** Same URL, new version, or the
  board stops being a place and becomes a pile of links.
- **Don't caption a capture you haven't looked at.** Read every capture back
  with vision before publishing (a contact sheet of the lot is quick):
  redirects, blank hero sections, mid-animation frames and a scroll that moved
  the screen behind a dialog all produce valid-looking files.
- **Don't judge the screens.** This documents; `page-audit` critiques. What
  drawing them turns up (a raw error message, an overflow, a crash on focus)
  goes in a findings list on the board, fixed or not, and the fixes go through
  the project's own process with a test each.
