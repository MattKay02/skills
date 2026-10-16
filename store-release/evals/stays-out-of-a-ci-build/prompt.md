---
description: Starting a CI build is the codemagic-build skill's job; this one should stay out.
tags: [trigger]
max_turns: 3
timeout_seconds: 180
allowed_tools: [Skill, Read, Glob, Grep]
---

Start an iOS build on Codemagic for the main branch and tell me when it lands.
