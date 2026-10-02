---
name: motion-sketchbook
description: Sketch a design as rendered films and stills before anything is built - several distinct options for a launch animation, a logo treatment, store pictures, a product ad or a run of social posts, drawn in Remotion from the product's real screens, type and marks, checked on contact sheets, and shown side by side on one page so the user picks by watching. Use whenever the user wants options for an animation or brand motion, "a few versions to choose from", app store screenshots or a feature graphic, reels, carousels or posts made from the product, or mentions Remotion for anything that will be judged by eye. Also use when a Remotion render fails, or a render looks right in the code and wrong in the file. Works beside Remotion's own official skills (remotion-dev/skills), which teach the API - this one covers what to draw, how to check it, and how to show it.
---

# Motion sketchbook

You're being asked to help someone **choose a design by looking at it**. Not a
description of an animation, not a component they have to run: a handful of
finished films or pictures, side by side, made from their real product, that
they can watch and point at.

Remotion is the sketchbook. It renders React to video and to images, so an
option costs minutes instead of a day in the app's own toolkit. That is its
whole job here. **What is sketched is not what ships**: a launch animation
gets rebuilt in the app once it is chosen, and a post gets posted as a file.

## Use Remotion's own skills for the API

Remotion publishes official agent skills, kept in step with each release:

```bash
npx skills add remotion-dev/skills
```

`/remotion-best-practices` routes to the rest (creating a project, markup,
fonts, measuring text, video and audio, rendering, upgrading). **Load those for
how to write Remotion; don't answer API questions from memory or from this
file**, because the API moves and they move with it. If they aren't installed,
say so and offer to install them; until then read the docs page you need
(`https://www.remotion.dev/docs/<page>.md`).

This skill departs from them in two places, on purpose:

- **They say to open the Studio and not render until asked.** Here the
  rendered files are the deliverable: the user chooses between options on a
  page, away from your terminal. So render. The Studio is still the right
  place to iterate on one option before you do.
- **Their safe area is a floor.** A platform lays its own buttons and caption
  over a picture, far more than a general margin allows for. See the table
  below.

## Process

1. **Find what is real before drawing anything.** The screens: captures of the
   running app, from whatever the project already has (a screenshot test, a
   fixture walk, store-screenshot tooling). The type: the product's own font
   files. The logo: its geometry, from whatever draws the icon, as numbers.
   The words: the store listing or the site. If one of these doesn't exist
   yet, getting it is the first job, not something to approximate.

2. **Give it a folder of its own**, beside the project's other design sources:
   its own `package.json`, and a `.gitignore` for `node_modules/`, `out/` and
   `public/`. Fonts and captures are *copied into* `public/` by the render
   script, never committed twice.

   If that folder sits inside another TypeScript project, **exclude it from
   the parent's `tsconfig.json`**. Otherwise the parent's build type-checks
   files whose packages only exist on your machine, and the first you hear of
   it is a failed deploy.

3. **Put every word in one file**, with a comment at the top naming where the
   words come from and what may not be said. A design sketch is where an
   aspiration quietly becomes a claim: the headline that sounds best is often
   one the product can't back. If the words file can only copy from the
   listing, the sketch can't promise more than the listing does. Mark what
   costs money as costing money.

4. **Draw options that are different ideas**, not one idea in three colours.
   Three or four for a brand moment, two for something smaller. Give each a
   one-line idea you could say aloud ("the mark winds back, then goes"). Put
   some design *around* the subject: a bare logo on a blank ground tells the
   user nothing about how it will sit in the world.

5. **Pick the shape.** A set of pictures (store shots, a carousel) is one
   composition at 1 fps where each frame is a picture, rendered with
   `--sequence`: a whole set in one run, sharing one layout. A film is a
   normal composition. Sizes are in the table below.

6. **Write one render script** that copies the assets in, renders what is
   named (everything, by default), and writes a contact sheet beside each
   result. It should stop on the first error (`set -e`). Then the README can
   say "run this" and be true.

7. **Look at every render before anyone else does.** Use
   `scripts/contact_sheet.py` (below). This step is not optional, for the
   reasons under "How a render lies".

8. **Show the options on one page**: each film playing, side by side, with a
   speed control that drives all of them together, one line on each idea, and
   **which one you would pick and why**. Publish it somewhere the user can
   open, and republish to the same address when it changes. Stills and a
   paragraph are not enough: people ask "where can I watch it?"

9. **When one is chosen, write the choice down** in the folder's README, with
   the date. Keep the others as source; render only the chosen one by
   default, so an unchosen set isn't the folder somebody uploads by mistake.
   If it ships inside an app, rebuild it there with the same timings, film
   *that*, and compare frames against the sketch.

## Sizes, and what gets covered

For a 1080-wide picture. Scale the numbers with the width.

| Target | Size | Keep clear |
|---|---|---|
| Upright video (Reels, TikTok, Shorts) | 1080×1920 | The platform's caption and buttons sit over roughly the bottom 420 and the right 130. A profile grid trims to the middle 3:4, losing about 240 top and bottom. So words go between 240 and 1480, left of 950 |
| Feed post, tallest shown whole | 1080×1350 | A profile grid trims it to 3:4, about 34 off each side |
| App Store, 6.9" iPhone | 1290×2796 | The listing shows the first three at thumbnail size: the words have to read small |
| Google Play phone | 1080×1920 | Play refuses a picture more than twice as tall as it is wide |
| Play feature graphic | 1024×500 | It is cropped differently in different places; keep the subject central |

These were worked to in October 2026. Platforms move them, so check the
current guidance before relying on a number, and say when you haven't.

**A phone screenshot is taller than the room under a headline.** At a size its
text can be read, it won't fit whole. Let the phone run off an edge, and
choose which end of the screen each picture keeps: the head, or the foot.
When the point of a screen is at its foot and the platform covers the foot of
the picture, move the *phone* up under the words. Never scroll or re-lay-out
the capture; that is drawing a screen the app doesn't have.

## Checking a render

`scripts/contact_sheet.py` is in this skill's folder; call it by its full path
from the project. It needs Pillow, and ffmpeg for films.

```bash
python <skill>/scripts/contact_sheet.py film out/reel.mp4 --zones reel   # a frame a second, covered areas ruled
python <skill>/scripts/contact_sheet.py stills out/carousel/              # a folder of pictures, side by side
python <skill>/scripts/contact_sheet.py film out/logo.mp4 --ruler         # a line every 10%, to measure with
```

Read the sheet back with vision, then open one or two frames at full size.
Look for: a word outside the clear area, a line that wraps leaving one word
alone, text that collides with something moving behind it, a beat with
nothing on screen, the first and last frame (a film is judged by its cover),
and whether each option is visibly a different idea.

**A sheet of frames is not the film.** It shows layout and nothing about
pace: a move that creeps and then rushes looks fine a second apart. Say that
you checked frames and not motion, or sample closer where something moves.

When a position matters ("is the bar halfway down?"), use `--ruler` and read
the number. Positions judged by eye from a preview are routinely wrong by ten
points.

## How a render lies

**It succeeds and shows you the old one.** You change a layout, render the
films, and the pictures in the folder are from before the change. Nothing
errors; the file is simply stale. After any edit, re-render everything the
edit could touch, and check the file's time before you show it.

**It fails and tells nobody.** A render piped through `tail` or `head`
reports the pipe's exit code, which is success. A background job that "exits
0" after printing a stack trace is the usual way a missing film gets
described as finished. Write the log to a file, test the exit code of the
render itself, and confirm the output exists and is new.

**A video inside the film can't be seeked.** Seen with several clips, played
faster than they were made, in a long composition: the render died with
`No frame found at position …` on one clip, twice, at the same place.
Re-encoding the clips so that every frame is a keyframe and none leans on a
later one fixed it:

```bash
ffmpeg -i in.mp4 -an -r 24 -c:v libx264 -crf 12 -g 1 -bf 0 -pix_fmt yuv420p out.mp4
```

The files are large, and they are only an input, so that costs nothing. The
official skills embed video with `<Video>` from `@remotion/media`; start with
what they say, and keep this for when a render fails anyway. Remotion's own
page on the error is `docs/troubleshooting/no-frame-found-at-position`.

**The type was measured before the font arrived.** Anything that measures
text to fit a width must wait for the font, or it fits a fallback and the
real face overflows. Gate the whole composition on the fonts having loaded.

**The file is right and too big to show.** A full-quality upright film runs
to tens of megabytes. Keep that one for posting, and make a smaller copy for
the page people review on.

## What NOT to do

- **Don't redraw the product's screens in React.** Use captures. A redrawn
  screen drifts from the app the day after, and a sketch of a screen that
  doesn't exist is a claim.
- **Don't build letters or logos out of strokes.** Set words in the product's
  real typeface and keep a mark at its icon's exact proportions. Hand-built
  letterforms are what makes a sketch look home-made, and it is the first
  thing people see.
- **Don't change a mark's shape to animate it.** Move it, reveal it, bring it
  in along the way it points. Bending one logo into another is a new logo
  nobody asked for.
- **Don't show one option.** One option is a proposal to accept or reject;
  three are a conversation about what the user wants.
- **Don't describe a film in place of showing it.** If it can't be watched
  yet, it isn't ready to show.
- **Don't add sound you don't own.** Platform music libraries are not
  reachable from a rendered file or an API. Silent, or yours.
- **Don't treat the sketch as the product.** If the chosen design ships in an
  app, it is rebuilt there and that version is what gets checked.

## Licence

Remotion is free for individuals and for companies of up to three people; a
larger company needs a company licence. Check that still holds before
publishing anything rendered with it, and say so in the folder's README.
