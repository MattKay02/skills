---
name: mobile-store-release
description: Take an iOS or Android app through App Store Connect and Google Play from the terminal - connect a project with its own dedicated API keys, check and upload store screenshots, listing text and release notes, run a read-only pre-flight for what App Review or Play would reject, submit or promote a build that is already on TestFlight or a Play testing track, release a held version, watch review status, and work a rejection through to resubmission. Use when the user wants to submit, resubmit, release or promote an app build; asks whether it is ready for the App Store or Play, or where a review stands; pastes an App Review rejection, an "Unresolved Issues" message or a Play policy email; wants store screenshots, listing copy, What's New or TestFlight testers updated; or needs store API keys for a new app. Not for building or uploading the binary itself (that is CI), designing or drawing the screenshots, or writing app code.
---

# Store release

You're being asked to take an app through the stores without living in two
web consoles: connect it, get its pictures and listing up, prove it is ready,
submit it, and answer App Review if it comes back. The point is that every
lesson a rejection teaches is checked *before* the next submission, by a
script, instead of being remembered by whoever happens to be releasing.

Almost everything here changes something public or something a reviewer sees,
so the working rule is: **read freely, change only with a plan shown and a yes
given.**

## The guards, and why each exists

- **Nothing changes without `--yes`.** Every changing command prints its plan
  first. Run it without `--yes`, show the user the plan, and run it again with
  `--yes` once they've agreed. A clear earlier request ("submit it to both
  stores") covers a plan that does exactly that; anything in the plan they
  didn't ask for (a version rename, a release type change, a draft release, a
  deletion of existing pictures) needs its own yes. Submissions, releases,
  Play listing changes and tester invites are all outward-facing.
- **Each project has its own keys, outside every repository.** A dedicated
  App Store Connect key and a dedicated Google Play service account per
  project, so either can be revoked alone and a leak touches one product. The
  tool refuses a key inside any git work tree and has no shared default
  location. Never print, paste or log a key's contents.
- **The tool only touches apps named in the project's config.** An App Store
  Connect team key reaches *every* app on the developer team, whatever it is
  called, so the config's app list (matched on the exact bundle ID) is what
  stops one project's session changing another product. Don't add an app to
  a project's config to "just check something" on it.
- **Never touch Google Play while CI is uploading to it.** Every command that
  reads or changes Play (all but `links`), plan-only runs included, opens a
  Play *edit*, and opening one expires the edit a CI upload is writing into:
  the build compiles, passes, and fails at publishing with "This edit has
  expired". Watch CI through its own API; read Play once it has finished.
- **Never cancel a review submission to get round an error.** Cancelling
  drops everything else in it (on iOS, a first subscription and its group fall
  back to the version page and must be re-attached by hand). A rejected
  submission is resubmitted, not replaced.
- **After a failed write, check before retrying.** A write that errored may
  still have landed. Run `status` (or `preflight`) and see what the store now
  holds before running the command again. Reads retry themselves briefly on a
  store's 5xx; writes never do.

## The project config

Each project has a `.store-release.json` at its root (the tool walks up from
the current directory to find it; `--config PATH` or `STORE_RELEASE_CONFIG`
overrides). It names the key files and the apps, and where each app's
pictures, listing and notes live:

```json
{
  "keys": {
    "app_store_connect": "~/.store-keys/myproduct/asc.json",
    "google_play": "~/.store-keys/myproduct/play-service-account.json"
  },
  "apps": {
    "myapp": {
      "name": "My App",
      "ios": { "bundle_id": "com.example.myapp" },
      "android": { "package": "com.example.myapp", "draft_until_published": false },
      "listing": "store/listing.json",
      "screenshots": { "ios": "store/screenshots/ios", "android": "store/screenshots/android" },
      "play_feature_graphic": "store/play-feature-graphic.png",
      "play_icon": "store/play-icon-512.png",
      "creative": "store/creative",
      "release_notes": "store/release-notes.txt"
    }
  }
}
```

It holds paths, not secrets, so it can be committed. `release_notes` is
Play's; an iOS update's What's New comes from the listing file's `whatsNew`
or `--notes`, and if neither exists, ask the user for it rather than writing
it yourself. Unknown fields are refused, so a typo can't drop a file from an
upload; fields starting with `_` are ignored, for comments.

A project may also keep a **`.store-release.md`** beside it: the checks and
history only that product has (a rejection it once had, a console step it
needs, a picture rule its brand needs). **Read it before releasing**, and add
to it when a review teaches something; that file is how the next release
starts where this one ended. If neither file exists, the project isn't
connected yet: start at [references/connect.md](references/connect.md).

## The tool

`python3 <this skill>/scripts/store.py <command> <app> [options]` (`python` on
Windows). Needs Python 3.10+ and `cryptography` (`pip install
cryptography`); `ffprobe` (from ffmpeg) only for App Store header videos.
`<app>` is a key from the config.

| Command | Does | Changes anything |
|---|---|---|
| `doctor` | config, keys, and that both stores accept them and see the app | no (opens and discards a Play edit) |
| `status`, `links` | where each version stands; the public pages and whether they're live | no |
| `pictures` | sizes, format, alpha, counts and order of the store pictures on disk | no (local) |
| `preflight [--build N]` | the punch list: what would block or reject this submission | no |
| `prepare --build N` | opens the iOS version (renaming the open one if its number differs), attaches the build | yes |
| `listing [--from FILE] [--locale L]` | store text from the listing file | yes |
| `screenshots [--ios\|--android] [--locale L]` | **replaces** the pictures (the plan lists what's there now) | yes |
| `assets [--poster T] [--from DIR]` | App Store product page header and search results asset | yes |
| `submit --ios --build N` | sends the iOS version for review | yes |
| `submit --android [--from-track T] [--rollout F]` | promotes a testing build to production (internal and 100% by default) | yes |
| `release`, `release-type` | release a held iOS version; switch automatic/manual | yes |
| `test-notes`, `testers`, `add-tester` | TestFlight and Play internal testing | `testers` no; others yes |

`prepare` and `submit` keep a version's release type unless given
`--manual` or `--automatic`; a new version releases itself on approval.
`preflight` and `pictures` exit 1 when anything is BLOCK or UNCHECKED, and
print a `Summary:` line; read it either way. Other commands exit 1 with
`Stopped: <reason>`. A flag a command doesn't use is refused (exit 2) rather
than ignored, so a wrong flag never quietly does the default.

## Where you are, and what to read

Read only the section for the step you're on; each is self-contained.

| Situation | Read |
|---|---|
| A new app, no `.store-release.json`, keys missing, or `doctor` fails | [references/connect.md](references/connect.md) |
| Making, checking or replacing store pictures | [references/pictures.md](references/pictures.md) |
| About to submit, or "is it ready?" | [references/preflight.md](references/preflight.md) |
| Uploading, submitting, releasing, watching a review | [references/release.md](references/release.md) |
| Rejected, "Unresolved Issues", a Play policy email, or resubmitting | [references/rejections.md](references/rejections.md) |

## A release, end to end

0. **Make sure no CI build is publishing to Play right now** (ask, or check
   the CI). Everything below except `links` touches Play.
1. `doctor <app>`. Fix anything it fails before going further.
2. Read the project's `.store-release.md`, if it has one.
3. The build is on the store already: CI or the developer uploads it, this
   skill doesn't. `status` shows it `VALID` on iOS, on a testing track on
   Play.
4. Pictures: `pictures <app>`, then **look at every image yourself** at full
   size. The script can't read the words in them.
5. Upload in the order [release.md](references/release.md) gives (plan, show,
   `--yes`).
6. `preflight <app> --build N`. Clear every BLOCK and UNCHECKED; go through
   every MANUAL line with the user, or against the code where you can.
7. `submit`, on the user's yes to the printed plan.
8. Report what went in and what to watch for. If a review comes back, go to
   [rejections.md](references/rejections.md).

## Things that will catch you out

- **One version, one submitted build (this skill's convention).** Stores
  allow a new build on a rejected version; this skill instead sends a fix
  that needs a new binary as the next version (1.0.0 rejected → 1.0.1), so
  each version number means one build. Apple keeps one version open, so
  `prepare` renames the open record to the new number. See release.md.
- **Reviewers test iPhone apps on an iPad.** Run the release candidate in
  iPad compatibility mode before submitting.
- **The store consoles and APIs have bad hours** (500s, "Sorry, something went
  wrong"). Wait and retry; never cancel or recreate something to make an
  error go away.
- **Play reads a release in review as `completed`.** `links` asks the public
  store page whether the app is actually live.

## Hand-offs

- **Building and uploading the binary:** the project's CI or the developer
  (Xcode Organizer or Transporter for iOS, a Play Console upload for a first
  Android build). If the `codemagic-build` skill is installed, it drives
  Codemagic.
- **Designing store pictures:** if the `motion-sketchbook` skill is
  installed, it draws options from the app's real screens; otherwise draw them
  from screenshot tests or a device. This skill checks and uploads them.
- **Finding a screen a rejection names:** a screenshot test, a UI walk, or
  the `screen-board` / `ui-walk` skills if installed.

## Scope

Connecting, checking, uploading, submitting, releasing and answering review.
**Not** building or uploading binaries, creating the app records, App
Privacy, or a first subscription's attachment to a version: those are left to
the developer and the consoles, listed in [connect.md](references/connect.md)
so they aren't forgotten, and the tool says when one is in the way rather
than pretending it can do it.
