# skills

Claude Code skills I've built to augment how I develop — reusable, agentic capabilities I reach for across my own projects.

A *skill* here is a self-contained instruction set (the Claude Code `SKILL.md` convention) that gives an AI coding agent a specific, repeatable capability: a procedure to follow, with the judgement and guardrails baked in. These are tools I build **around** AI, not just prompts I type into it — each one encodes a workflow I'd otherwise repeat by hand, so the agent does it consistently and verifies its own work.

This repo is the canonical home for the generic, personal ones. Project- or client-specific skills live with their projects.

## Skills

<!-- SKILLS:START -->

### [page-audit](./page-audit) · UI Review

Audits a UI surface across seven axes and returns a prioritized P1/P2/P3 punch list — verifying every finding against the actual code (file:line citations) before reporting it. A review, not a redesign.

**Why:** I kept doing the same manual UI pass by eye — this makes it systematic and evidence-backed. · **Stack:** Claude Code, Playwright

### [emulator-verify](./emulator-verify) · Mobile QA

Lets an agent confirm a Flutter app's UI on the Android emulator by capturing screenshots over adb and reading them back with vision — so it checks its own work between turns instead of asking me to look.

**Why:** Closing the loop on mobile UI changes without a human in the middle every time. · **Stack:** Claude Code, adb, Flutter

### [lighthouse-audit](./lighthouse-audit) · Web Perf

Runs Lighthouse against a production build, takes the median of several mobile runs (single runs are noisy), and turns the result into an actionable punch list — category scores, Core Web Vitals, the exact failing audits, and LCP phase breakdown — with before/after support.

**Why:** I kept hand-running the same spin-up-preview → run-Lighthouse → diff-before/after loop on every perf pass — this makes it one repeatable, median-stable step. · **Stack:** Claude Code, Lighthouse, Chrome

<!-- SKILLS:END -->

> This list is generated from [`skills.json`](./skills.json) — the source of
> truth. Don't edit it by hand; add a skill there and the README syncs itself.

## Using a skill

Each skill is a folder containing a `SKILL.md`. To use one with Claude Code, copy the folder into your skills directory:

```bash
cp -r page-audit ~/.claude/skills/
```

Claude Code discovers it automatically — invoke it by asking for the capability ("audit this page") or as a slash command (`/page-audit`).

## License

MIT — see [LICENSE](./LICENSE). Use them, fork them, adapt them.

---

Built by **Matthew Kay** · [mgkcodes.com](https://mgkcodes.com) · [github.com/MattKay02](https://github.com/MattKay02)
