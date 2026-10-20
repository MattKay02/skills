# Uploading, submitting and releasing

The order each store wants things in, and the rules that make a release
repeatable. Every changing command here prints a plan first; show it, and use
`--yes` only on the user's word.

## Versions and builds

- **One version, one submitted build: this skill's convention, not a store
  rule.** Apple and Google both accept a new build on a rejected version. This
  skill sends a fix that needs a new binary as the next version instead (1.0.0
  rejected → 1.0.1), so "what is 1.0.0?" always has one answer: one build, one
  commit. If the project's own convention differs (its `.store-release.md`
  says so), follow the project: `prepare --build N` with a build of the same
  version attaches it to the open version as it is.
- **Apple keeps one version open at a time.** After a rejection the rejected
  record is still open under its old number. `prepare` and `submit` notice
  that no version has the new build's number and **rename the open one**; the
  plan says so ("rename version 1.0.0 to 1.0.1"). Pictures and listing text on
  it carry over.
- **Build numbers never repeat**, per platform. The project's version file
  usually sets them; bump it in a commit before building.
- **Record what was submitted.** Tag the commit the store build was made from
  (e.g. `app/build-31`) when it goes for review. A branch can't say what
  shipped; a tag can.

## The listing file

`listing` sends the store text from the app's `listing` file (or `--from
FILE`), in the primary language. Only the fields present are changed:

```json
{
  "ios": {
    "name": "My App", "subtitle": "...", "privacyPolicyUrl": "https://...",
    "description": "...", "keywords": "comma,separated", "promotionalText": "...",
    "supportUrl": "https://...", "marketingUrl": "https://...", "copyright": "2026 ...",
    "whatsNew": "...", "reviewNotes": "Steps and accounts for App Review"
  },
  "android": {
    "title": "My App", "shortDescription": "...", "fullDescription": "...", "video": "https://..."
  }
}
```

`reviewNotes` **replaces** App Review's notes whole, so include everything
that should stay. `name`, `subtitle` and `privacyPolicyUrl` live on the app's
information, which only opens for changes alongside a version; the rest
belong to the version. The Android block changes the live listing (after
Google's review), like Play's pictures.

It works on the primary language; `--locale CODE` sends the same fields to
another. Lengths are checked before anything is sent (App Store: name and
subtitle 30, keywords 100, promotional text 170, description and What's New
4000; Play: title 30, short description 80, full description 4000).

**What's New for an iOS update** comes from `whatsNew` here or `--notes` on
`submit`. If the project has neither, ask the user what it should say; don't
write release notes on their behalf without showing them.

## iOS, in order

1. **The build is on TestFlight and processed.** `status` shows it `VALID`.
   CI uploads it; see the project's CI.
2. **`prepare <app> --build N`.** Opens the version (or renames the open one
   when its number differs from the build's) and attaches the build. Not
   submitted. A new version releases itself on approval; an existing one
   keeps its release type unless `--manual` or `--automatic` is given, and
   the plan says which it will be.
3. **`listing`**, **`screenshots --ios`**, **`assets`**, as needed. The
   version must be open for changes for these to land on it.
4. **Console steps**, if this version needs any (see connect.md): a first
   subscription attached on the version page, App Privacy, review contact and
   demo account.
5. **`preflight <app> --ios --build N`.** Clear every BLOCK; go through MANUAL.
6. **`submit <app> --ios --build N`.** If a draft submission was started in
   App Store Connect (where a first subscription is added), the version goes
   into it and the whole draft is sent. Don't press Submit for Review on that
   draft by hand first.
   - **No `--notes` for an app's first version.** A version that has never
     been released has no What's New field, and setting one would fail after
     the build is attached, leaving the submission half made. The tool
     refuses `--notes` on a first version before writing anything.
   - **If App Review's submission is in Unresolved Issues, `submit` stops.**
     Resubmit that submission in the console instead: see rejections.md.
7. **Release.** A version set to `AFTER_APPROVAL` releases itself on
   approval. To hold one for a chosen moment, `release-type --manual` before
   or during review (or `--manual` on `prepare`/`submit`), then `release` when
   ready. Later `prepare` or `submit` runs keep the hold.

## Android, in order

1. **The build is on a testing track** (internal by default). CI publishes it
   there. Wait until the CI build has *finished* before any Play command: see
   below.
2. **`screenshots <app> --android`** if the pictures change with this
   release. These go on the **live listing** after Google's review, not with
   the release. Pass `--android`: without a platform flag, `screenshots` does
   iOS first and stops the whole command when no iOS version is open.
3. **`preflight <app> --android`.**
4. **`submit <app> --android`.** Promotes the newest build on the internal
   track (or `--from-track alpha` for closed testing, `beta` for open, or a
   custom closed track's name) to production, at 100% or as
   a staged rollout with `--rollout 0.2`; the plan says which. It refuses when
   that build is already on production. Release notes come from the config's
   `release_notes` (or `--notes FILE`): 500 characters at most per language,
   checked before anything is sent; several languages go in Play's
   `<en-GB>...</en-GB>` blocks. Write them for people, not for the team.
   - **A new app is a draft** until its first production release is
     published, and Play takes only draft releases for it. With
     `"draft_until_published": true` in the config, `submit` sends a draft
     (its plan says so); roll it out by hand in Play Console once. Internal
     testing doesn't end draft status.
   - If Play refuses to send the edit for review from the API, the tool
     commits it unsent and says so: the user presses *Send changes for review*
     in Publishing overview.

## Watching a review

- `status <app>` for both stores. iOS moves `WAITING_FOR_REVIEW` →
  `IN_REVIEW` → `PENDING_DEVELOPER_RELEASE` or `READY_FOR_DISTRIBUTION`
  (released). `REJECTED` means read rejections.md; approved means read
  approved.md, which also covers a held version's `release`.
- **Play reads a release in review as `completed`.** `links` checks the public
  store page, which answers only once the app is live.
- **Check at a sensible pace**, minutes to hours, not seconds. Reviews take
  hours to days.

## Never touch Play while CI is uploading to it

Play changes go through *edits*. Opening a new edit expires the one a CI
upload is writing into, so **any command that talks to Play** can break a CI
publish that has nothing wrong with it: `status`, `doctor`, `preflight` and
`testers`, and the Android side of `submit`, `listing`, `screenshots` and
`test-notes` **even without `--yes`** (a plan is read from an edit too). The
build compiles, passes, and fails at its last step with **"This edit has
expired, please create a new Edit"**.

- While CI is building for Android, watch the CI build through the CI's own
  API (or the `codemagic-build` skill), never through Play.
- If it has happened: the bundle is fine. Rebuild from the same commit (or
  one with identical app code) with nothing touching Play until it finishes.

## When the stores misbehave

- **App Store Connect's API returns 500s** on some days, and the console
  shows "Sorry, something went wrong". The tool retries a read briefly; past
  that, wait. Don't work around it by cancelling or recreating anything.
- **A write that failed may still have landed.** Before re-running a
  changing command that errored, run `status` (or `preflight`) and see what
  the store holds now. Writes are never retried automatically for this
  reason.
- **Asset processing takes minutes.** Screenshots and films show a
  processing state after upload; `preflight` reports any still processing.
