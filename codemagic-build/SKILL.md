---
name: codemagic-build
description: Start a Codemagic CI build from the terminal, poll it to completion, and report the result with artifact download links. Use when asked to kick off a CI build, ship a TestFlight/Play build, check whether a build passed, cancel a running build, or fetch a build's artifacts. Reads the API token from the environment only — never from the repo. Builds cost money and may publish to a store, so it always confirms before starting one.
---

# Codemagic build

You're being asked to drive a Codemagic build without leaving the terminal:
start one, watch it, and come back with either an artifact link or the reason
it failed. The point is closing the loop — "ship a build and tell me when it
lands" should not require a human to sit on a browser tab for twenty minutes.

## Before anything else: this spends money and may publish

Two things are true of almost every Codemagic workflow and neither is
recoverable by apologising afterwards:

- **Build minutes are metered.** A started build bills whether or not anyone
  wanted it.
- **A workflow can publish.** If its `publishing:` block has
  `submit_to_testflight: true`, or a Google Play track, then a *successful
  build uploads to real testers*. There is no dry-run.

So: **never start a build without the user explicitly asking for that build,
now.** "Is CI set up?" and "what does the API do?" are not authorisation.
Before the first `POST /builds` of a session, state plainly which workflow,
which branch, and whether that workflow publishes — then wait.

Cancelling and reading status are free and safe; treat only `POST /builds` as
the gated action.

## The token lives in the environment, and nowhere else

Read `CODEMAGIC_API_TOKEN` from the environment. If it is unset, say so and
stop — do not prompt for the value, do not accept it pasted into chat, and do
not write it anywhere.

**Never create a `.env` (or any file) in the project for this.** A CI token
authenticates a *person's* account, not the software: a contributor cloning
the repo does not need it, cannot use it, and must not be told to obtain one.
Putting it in a repo file — even a gitignored one — makes personal tooling look
like project configuration, and it will be in a setup doc within a week. The
correct home is a user-level environment variable set once
(`setx` on Windows, the shell profile elsewhere).

If you ever see the token's value, do not echo it back, log it, or include it
in a command you print.

## Process

1. **Confirm the branch is pushed**, with `git ls-remote --heads origin`. A
   build runs a ref the *remote* has; a local-only branch fails with something
   unhelpful.

   **Do not use the app's `branches` field for this.** It reads like the
   authoritative answer and it is a cache: it can list two branches while the
   remote has three, and an API-started build on the missing one fetches
   sources perfectly well, because the `branch` in the request is what gets
   checked out. Treating it as authoritative means refusing to start builds
   that would have worked.
2. **Get the `workflowId` from the repo, not from memory.** It is the key under
   `workflows:` in the project's `codemagic.yaml` (e.g. `ios-release`), not the
   human-facing `name:` beneath it. Read the file.
3. **Resolve `appId` once.** `GET /apps` returns every app with its `_id`.
   Match on the repo/app name and keep it for the session. Do not write it to
   the repo — it is account-scoped, like the token.

   **Ignore the `workflows` field while doing it.** It lists *UI-configured*
   workflows keyed by opaque hashes, so an app built entirely from
   `codemagic.yaml` reports one meaningless id and none of the names you are
   looking for. The `workflowId` you want is the yaml key (step 2); the two
   look like the same concept and are not.
4. **Confirm, then start.** See the gate above. `POST /builds`.
5. **Poll, patiently, and know which states are terminal.** `GET /builds/<id>`
   and read `status`. Builds take minutes, not seconds: poll on the order of
   30–60s, and say what you are waiting on rather than going quiet.

   `publishing` **is not a finished build.** A poll loop that waits while the
   status is `building` will exit the moment it flips, and report a result on a
   build still uploading to a store. Wait while the status is any of
   `queued`, `preparing`, `building`, `publishing`; treat `finished`, `failed`,
   `canceled`, `skipped`, `timeout` as terminal.
6. **Report the outcome.** On success, the artifact download URLs. On failure,
   the failing step and what it said — a bare "build failed" makes the user go
   to the browser you were meant to save them.

   **There is no log endpoint.** `/builds/<id>/log`, `/actions/<id>/log` and
   the plural forms all 404; logs live in the web UI only. What you do have is
   `build.message`, which names the failing step and its exit status verbatim
   ("Step 5 script `Generate config/app_config.json from secure vars` exited
   with status code 1"), and `buildActions[]`, which shows every step's status
   so the last `success` before the first `failed` locates it. Read the
   failing script out of the repo's `codemagic.yaml` to explain *why* — that is
   usually enough without the log, and it is what you can actually get.

## API reference

Base `https://api.codemagic.io`. Either auth header works —
`Authorization: Bearer <token>` or the older `x-auth-token: <token>`. Prefer
Bearer; recognise the other, because a lot of existing scripts use it.

| Do | Call |
|---|---|
| List apps (find `appId`) | `GET /apps` → `_id` per app |
| One app's detail + workflows | `GET /apps/<app_id>` |
| **Start a build** | `POST /builds` → `{ buildId }` |
| Build status | `GET /builds/<build_id>` → `status` |
| Cancel | `POST /builds/<build_id>/cancel` (`208` if already finished) |
| Artifacts | on the build object, download URLs under `url` |

Start-build body — `branch` *or* `tag`, not both:

```json
{
  "appId": "...",
  "workflowId": "<key from codemagic.yaml>",
  "branch": "<pushed branch>",
  "environment": { "variables": {}, "groups": ["..."], "softwareVersions": {} }
}
```

## Things that will catch you out

- **The yaml's triggering and branch config is ignored for API-started
  builds.** The `branch` in the request wins. Convenient, but it means a
  workflow guarded by a branch pattern offers no protection here — the guard
  against building the wrong ref is you.
- **`environment` in the request *overrides*, it does not merge with what you
  expect.** Send `groups` explicitly if the workflow needs a variable group;
  omitting them silently builds without those variables, which usually fails
  late and confusingly (an app that compiles, launches, and cannot reach its
  backend).
- **A green build with no artifacts is a real outcome**, usually a glob that
  resolved relative to the wrong directory. If `status` is successful and the
  artifact list is empty, say so loudly rather than reporting success.

- **`Publishing` reports `success` on builds that never produced anything.** On
  a run that died at step 5, every later step was `skipped` — except
  `Publishing`, which was `success`, because it had nothing to do and did it
  faultlessly. Never read that step as evidence a build shipped. The artifact
  list is the evidence.
- **A build number normally comes from the CI counter**, not the project's
  version file. Don't bump a version to "make the build work" without
  checking — you will usually be wrong and the change will be committed.
- **`GET /builds` (plural) is for listing.** Use the single-build endpoint for
  polling; listing every build to find one you already have the id for is
  slower and noisier.

## Scope

Starting, watching, cancelling, and collecting. **Not** configuring CI: if a
workflow is wrong, fix `codemagic.yaml` in the project as ordinary work — the
API cannot edit it, and this skill should not pretend otherwise. Signing
identities, keystores, API keys and variable groups are one-time setup in the
Codemagic UI; when one is missing, name it and hand back rather than trying to
route around it.
