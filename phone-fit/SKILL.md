---
name: phone-fit
description: Check a web page or step-by-step UI on phones the way phones actually show it, with Safari's address bar taking part of the screen. Steps through every state, stop or step at real iPhone and Android sizes and measures what a desktop check misses, such as a sheet or card that has to scroll, a Next or Submit button pushed off screen, text overlapping other content, and a page that never goes quiet (the usual reason iPhone Safari lags or reloads with "A problem repeatedly occurred"). Saves a screenshot strip of the worst cases and re-measures after fixes. Use when asked to check mobile or iPhone layout, why a bottom sheet or modal hides its buttons, or why a page lags or crashes on phones.
---

# Phone fit

Desktop checks pass and phones still break: the sheet scrolls, the Next button
sits below the screen, a label lands on the frame above, Safari stalls and
reloads. This skill measures those things at the sizes phones really give a
page, step by step, and reports numbers, not impressions.

## The sizes that matter

A phone's screen is not the page's size. Safari's toolbars take part of it, and
that part changes as the user scrolls. Check the tight case first.

| Device | Page area, bar showing | Bar hidden |
|---|---|---|
| iPhone 12 to 15 (390 wide) | about 390 x 664 | about 390 x 750 |
| iPhone SE / 8 | about 375 x 553 | about 375 x 628 |
| Pro Max (430 wide) | about 430 x 740 | about 430 x 830 |
| Common Android (Chrome) | about 360 x 740 | |

These are approximate. If the user can report `innerWidth x innerHeight` from
their own phone, use that. Never test at the full screen size (390 x 844):
Safari never gives a page that much.

## Process

1. **Find every step.** List the states a phone user moves through: tour
   stops, wizard steps, sheets, modals, tabs, the empty and the full state.
   Drive them through the UI's own controls (its Next button, its tabs), not by
   editing the DOM.
2. **Measure each step at each size** with one Playwright script (mobile
   emulation: `isMobile: true, hasTouch: true, deviceScaleFactor: 3`):
   - **Scrolls?** The container that holds the step's content and its main
     action: `scrollHeight > clientHeight + 1`.
   - **Action on screen?** The main button's box is inside the viewport.
   - **Room left?** How much height is left for the main content once the
     sheet or card is drawn. A sheet that fits by taking the whole screen is
     not a fix.
   - **Overlaps.** Bounding-box intersections between labels or text and the
     content they sit near. Check the zoomed-out views too: anything that keeps
     a fixed size on screen grows relative to the content as it zooms out.
   - **Sideways overflow.** `document.documentElement.scrollWidth > innerWidth`.
   - **Console errors.**
   Print one line per size: how many steps fit, the tallest step, the least
   room left, then each offender with what it needs.
3. **Look at it.** Screenshot the worst steps at the tightest size, put them
   side by side (`ffmpeg ... hstack`), and read the strip yourself before
   reporting. A capture taken mid-animation looks like a bug; say so when it is
   one.
4. **Fix, then measure again.** In this order:
   - make secondary content compact on phones (a wrapping chip list becomes
     one row you swipe sideways; things already in the top bar or elsewhere on
     the page don't need repeating);
   - then pin the main action to the bottom of its container (`position:
     sticky; bottom: 0`) as a safety net for the smallest screens.
   Pinning alone doesn't fix it: the complaint is having to scroll. Re-run the
   same script and report before and after.

## Does the page rest?

A page that lags or crashes in iPhone Safari but is fine in desktop Chrome is
usually doing work every frame. Check, in this order:

- **Idle writes.** After load and a few seconds of settling, with nothing
  touched, count DOM mutations for 2 seconds (`MutationObserver` on the
  document: attributes, childList, characterData, subtree). Anything above zero
  means a loop is writing every frame. Chrome skips writes that don't change a
  value; Safari may restyle everything below the element each time, so one CSS
  variable written per frame on a big container can stall a phone. Fix: write
  only when the value changes, and snap eased animations to their target once
  the remaining movement is invisible.
- **Rescaling a big container every frame.** A canvas, map or board moved by
  changing its transform scale in JavaScript can mean a full redraw per frame on
  iPhone. On touch screens prefer cutting between views, or one CSS transition
  (run on the GPU) with a fallback if it proves slow.
- **Huge layers.** An element the size of the whole page or canvas (an SVG
  overlay, a full-size wrapper) that sits above anything animating gets its own
  GPU layer in WebKit. Size overlays to what they draw.
- **Blur over moving content.** `backdrop-filter` re-blurs whatever changes
  behind it. Drop it on touch screens if the content behind moves.
- **Expensive paint repeated.** Large blurred `box-shadow`s, CSS `filter`s and
  opacity fades across many elements all repaint during movement. Lighten them
  on touch screens rather than everywhere.

If the cause still isn't clear and only the user's phone shows it, either ship
temporary URL switches that turn one suspect off each (`?lite=blur`,
`?lite=motion`) and give the user the links, or, if they'd rather not test,
apply every mitigation at once for touch screens and say that's what you did.

Playwright's WebKit on Windows or Linux is not iOS Safari. Use it to confirm
behaviour (touch mode engages, no errors, the right fallback fires), not to
judge smoothness, and say what can only be confirmed on a real phone.

## Report

- Per size: steps that fit out of the total, the tallest step, the least room
  left, and each offender.
- Idle writes over 2 seconds.
- The screenshots you looked at.
- What changed, with the numbers before and after.
- What still needs the user's own phone to confirm.

## What not to do

- Don't test at the full screen height; test the page area.
- Don't call a scrolling sheet fixed because its button is now pinned.
- Don't claim an iPhone problem is fixed from emulation alone.
- Don't hide content that matters on phones just to make the numbers pass; move
  it, compact it, or say what had to go.
