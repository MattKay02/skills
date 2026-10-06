# skills

Claude Code skills I've built to augment how I develop: reusable, agentic capabilities I reach for across my own projects.

A *skill* here is a self-contained instruction set (the Claude Code `SKILL.md` convention) that gives an AI coding agent a specific, repeatable capability: a procedure to follow, with the judgement and guardrails baked in. These are tools I build **around** AI, not just prompts I type into it. Each one encodes a workflow I'd otherwise repeat by hand, so the agent does it consistently and verifies its own work.

This repo is the canonical home for the generic, personal ones. Project- or client-specific skills live with their projects.

## Install

Any agent that supports [Agent Skills](https://agentskills.io) (Claude Code, Cursor, Codex and others):

```bash
npx skills add MattKay02/skills                  # choose from the list
npx skills add MattKay02/skills --skill ui-walk  # or name the ones you want
```

Claude Code, as plugins (one per skill):

```text
/plugin marketplace add MattKay02/skills
/plugin install ui-walk@mattkay02
```

Or copy a skill's folder into `~/.claude/skills/`. Each skill below shows its own install line.

## Skills

<!-- SKILLS:START -->

### [codemagic-build](./codemagic-build) · Mobile CI

Starts a Codemagic build from the terminal, polls it to completion, and reports the result with artifact download links, so "ship a build and tell me when it lands" doesn't mean sitting on a browser tab for twenty minutes. Reads the API token from the environment only, never the repo, and treats starting a build as a gated action because minutes are metered and a green build can upload straight to real testers.

**Why:** Kicking off a TestFlight build meant leaving the terminal, clicking through a UI, and coming back later to find out. The safety rails are the interesting half: a CI token is personal tooling, not project config, and it does not belong in the repo. · **Stack:** Claude Code, Codemagic, REST API

**Install:** `npx skills add MattKay02/skills --skill codemagic-build` · Claude Code: `/plugin install codemagic-build@mattkay02`

### [ui-walk](./ui-walk) · UI Evidence

Drives the running app with Playwright through every surface and state of a feature (empty, mid-flow, success, collapsed/expanded), saving an ordered, numbered screenshot folder that reads like a story. Idempotent: it cleans up everything it creates, so re-running after fixes regenerates the same sequence for comparison.

**Why:** I kept hand-writing the same walk script before every UI review: ordered captures of every state, then feed the folder to page-audit. Third time was the skill. · **Stack:** Claude Code, Playwright

**Install:** `npx skills add MattKay02/skills --skill ui-walk` · Claude Code: `/plugin install ui-walk@mattkay02`

### [page-audit](./page-audit) · UI Review

Audits a UI surface across seven axes and returns a prioritized P1/P2/P3 punch list, verifying every finding against the actual code (file:line citations) before reporting it. A review, not a redesign.

**Why:** I kept doing the same manual UI pass by eye. This makes it systematic and evidence-backed. · **Stack:** Claude Code, Playwright

**Install:** `npx skills add MattKay02/skills --skill page-audit` · Claude Code: `/plugin install page-audit@mattkay02`

### [emulator-verify](./emulator-verify) · Mobile QA

Lets an agent confirm a Flutter app's UI on the Android emulator by driving it with adb input, capturing screenshots over adb, and reading them back with vision, so it checks its own work between turns instead of asking me to look. Shell-aware: the byte-safe screencap command differs between PowerShell and bash, and getting it wrong yields a corrupt PNG that looks fine on disk.

**Why:** Closing the loop on mobile UI changes without a human in the middle every time. · **Stack:** Claude Code, adb, Flutter

**Install:** `npx skills add MattKay02/skills --skill emulator-verify` · Claude Code: `/plugin install emulator-verify@mattkay02`

### [lighthouse-audit](./lighthouse-audit) · Web Perf

Runs Lighthouse against a production build, takes the median of several mobile runs (single runs are noisy), and turns the result into an actionable punch list (category scores, Core Web Vitals, the exact failing audits and the LCP phase breakdown), with before/after support.

**Why:** I kept hand-running the same spin-up-preview → run-Lighthouse → diff-before/after loop on every perf pass. This makes it one repeatable, median-stable step. · **Stack:** Claude Code, Lighthouse, Chrome

**Install:** `npx skills add MattKay02/skills --skill lighthouse-audit` · Claude Code: `/plugin install lighthouse-audit@mattkay02`

### [screen-board](./screen-board) · Product Map

Builds a pan-and-zoom board of every screen in an app: full-page captures laid out in reading order, each paired with what that screen is FOR and what good looks like, published as one design canvas that updates in place. Records the commit each screen was captured at, so it can tell you which descriptions have gone out of date rather than just re-taking the pictures.

**Why:** I kept rebuilding the same board and it kept going quietly wrong: two frames were screenshots of a 404 for four days, and a panel described a feature three tools out of date. The screenshots were never the problem; the writing beside them was. · **Stack:** Claude Code, Playwright, Claude Design

**Install:** `npx skills add MattKay02/skills --skill screen-board` · Claude Code: `/plugin install screen-board@mattkay02`

### [silent-failure-sweep](./silent-failure-sweep) · Reliability

Hunts a codebase for failures that happen without anyone being told: capped AI calls whose stop reason is never checked, errors turned into empty results, background jobs with no failure handler that leave records stuck mid-state, counts that report the same problem every run without escalating, and limits applied quietly. Produces a ranked punch list with file:line and the loud alternative, and proves the worst with a cheap live probe rather than asserting it.

**Why:** In one day on a production app, the same shape turned up five times: a document pipeline that silently kept only the first 17 pages of a 40-page file, background jobs that hung forever and made the UI blame the wrong thing, a usage meter counting every document as one page, and a weekly check reporting the same three failures for two months without naming them. Each was honest in its logs and silent to the person who needed to know. · **Stack:** Claude Code, Static analysis, SQL

**Install:** `npx skills add MattKay02/skills --skill silent-failure-sweep` · Claude Code: `/plugin install silent-failure-sweep@mattkay02`

### [motion-sketchbook](./motion-sketchbook) · Motion Design

Sketches a design as rendered films and stills before anything is built: several distinct options for a launch animation, store pictures or a run of social posts, drawn in Remotion from the product's real screens, type and marks, and shown side by side on one page to pick by watching. Checks every render on a contact sheet with the platform's covered areas ruled in, and leaves the Remotion API itself to Remotion's official skills.

**Why:** Third time building the same thing: a launch animation, then store screenshots, then a set of social posts, each with its own fonts, phone frame, render script and contact sheet. My first try at the animation drew its letters by hand and looked home-made; four options rendered as video got picked on the first look. The part worth keeping was never the React. It was the checks: a render that fails quietly, or succeeds and shows you last hour's picture. · **Stack:** Claude Code, Remotion, ffmpeg

**Install:** `npx skills add MattKay02/skills --skill motion-sketchbook` · Claude Code: `/plugin install motion-sketchbook@mattkay02`

<!-- SKILLS:END -->

> This list and the install manifests are generated from [`skills.json`](./skills.json)
> and each `SKILL.md`. Don't edit them by hand: add a skill there and they sync themselves.

Once installed, ask for the capability in plain words ("audit this page") and the agent picks
the skill up, or run it as a slash command.

## License

MIT, see [LICENSE](./LICENSE). Use them, fork them, adapt them.

---

Built by **Matthew Kay** · [mgkcodes.com](https://mgkcodes.com) · [github.com/MattKay02](https://github.com/MattKay02)
