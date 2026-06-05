# skills

Claude Code skills I've built to augment how I develop — reusable, agentic capabilities I reach for across my own projects.

A *skill* here is a self-contained instruction set (the Claude Code `SKILL.md` convention) that gives an AI coding agent a specific, repeatable capability: a procedure to follow, with the judgement and guardrails baked in. These are tools I build **around** AI, not just prompts I type into it — each one encodes a workflow I'd otherwise repeat by hand, so the agent does it consistently and verifies its own work.

This repo is the canonical home for the generic, personal ones. Project- or client-specific skills live with their projects.

## Skills

### [page-audit](./page-audit)
Audits a UI surface and returns a prioritized punch list — **not** a redesign. Walks seven axes (information hierarchy, content accuracy, visual consistency, density at edge counts, copy, affordance clarity, cross-page coherence), **verifies every finding against the actual code before reporting it** (file:line citations, not vibes), and groups output by severity (P1 / P2 / P3). Built because I kept doing the same manual UI review by eye and wanted it systematic and evidence-backed.

### [emulator-verify](./emulator-verify)
Lets an agent visually confirm a Flutter app's UI on the Android emulator by capturing screenshots over `adb` and reading them back with vision — so it can check its own work between turns instead of asking me to look at my screen. Encodes the non-obvious bits: why `exec-out` matters, when to prefer semantic widget tooling over fragile pixel taps, and the common failure diagnostics.

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
