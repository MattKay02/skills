# Pre-flight: is it ready?

Run before every submission, after the uploads and after any fix:
`store.py preflight <app> [--ios] [--android] [--build N]`. It changes
nothing. It answers "what would block this, or get it rejected?" from what
both stores and the project hold, so a rejection's lesson becomes a line that
is checked every time instead of something someone has to remember.

## Reading the output

Each line reads `SEVERITY [what it guards] text`, and the output ends with a
`Summary:` line counting each severity. It exits 1 while anything is BLOCK
or UNCHECKED, 0 otherwise; read the summary either way.

- **BLOCK**: the store will refuse the submission, or review will reject it
  for certain. Fix before submitting.
- **WARN**: likely to cost a round trip or a surprise. Explain it to the user
  and let them decide.
- **OK**: checked and fine.
- **UNCHECKED**: a read failed, so that check couldn't run (the line says
  which). It is not a pass. Run preflight again; if it persists, the store is
  having a bad hour or the key lacks a permission (`doctor` tells which).
- **MANUAL**: neither API can see it. Go through each one: check what you can
  against the code yourself (below), and ask the user about the rest. Don't
  report MANUAL lines as passed.

Report the result as BLOCKs and UNCHECKEDs first, then WARNs, then the MANUAL items with
what you found for each, and finish with a plain verdict: ready, or not, and
what's left.

## What the script checks

**App Store**

| Check | Guards |
|---|---|
| A version open for changes; its number matches the build's, or a rename is due | the version is submitted once |
| The build exists, is `VALID`, not expired, and **export compliance is answered** | the submission can't be sent while compliance is missing |
| A build is attached to the version | — |
| Screenshots present per display type and language, and all finished processing; a language with none, or fewer than the primary, is flagged | listing completeness |
| App Review contact details; a demo account when sign-in is required | 2.1, information needed |
| Description, keywords and support URL in every language; copyright; a primary category | listing completeness |
| What's New: set on an update; absent (and must stay absent) on a first version | the submission fails otherwise |
| Privacy policy URL set **and loading**; support URL loading (a 401, 403 or 429 is a WARN: bot protection often refuses scripts, so open it in a browser) | 5.1.1, and listing completeness |
| Each subscription's state: missing metadata, or ready but not yet attached | 3.1.2; a first subscription goes with a version |
| A submission in Unresolved Issues (resubmit it; never cancel) | — |
| The release type (on approval, or held) | no surprise launch |

**Google Play**

| Check | Guards |
|---|---|
| The newest internal build and its version code; what production holds | the right build goes out |
| Whether the app is still a draft (needs `--draft`) | Play refuses a non-draft release |
| Release notes at most 500 characters per language | Play refuses longer |
| Icon, feature graphic, at least 2 phone screenshots on the listing | listing completeness |
| Contact email and website in the app details | listing completeness |

## The MANUAL items, and how to check them

Check against the code where you can. Searching the project usually settles
it, and evidence ("the purchase screen links terms and privacy at
`src/purchase/PaywallScreen.tsx:212`") is worth more than a yes.

- **Nothing asks for a name or email after Sign in with Apple** (cited by App
  Review as Guideline 4, Design). Follow the flow after an Apple sign-in in
  the code, including
  first-run and onboarding screens that run once an account exists. The fix
  is to skip the question for an Apple account, not to ask Apple for more
  than the privacy policy says it gets.
- **Account deletion in the app** if the app creates accounts (5.1.1(v)), and
  for Sign in with Apple accounts, the Apple token revoked on deletion.
- **The purchase screen** (3.1.2): the subscription's name, length and price
  per period; restore purchases; links to the terms of use and the privacy
  policy.
- **App Privacy / Data safety match the app.** What the code collects (health
  data, location, identifiers, analytics SDKs) against what the console
  answers say. A mismatch is a rejection on Play and a problem on both.
- **The privacy policy matches this build.** Review compares the published
  policy with the app; if this build changed what is collected or how
  deletion works, the published policy must say so when the build is
  submitted, not after.
- **Permission prompts explain why** (5.1.1): every usage string says what the
  app does with it, in plain words.
- **The demo account works**, now, with the build under review.
- **It works on an iPad.** Reviewers test iPhone-only apps on iPads in
  compatibility mode. Run the release candidate that way.
- **The pictures show no price and nothing the app doesn't do**
  (see pictures.md). The script can't read them; you can.
- **Play:** target API level current, content declarations answered, ads
  declaration right, and any sensitive permission (background location,
  health) declared with its reason.
- **The project's own list:** anything in `.store-release.md`.

## After a review

When a review rejects something preflight didn't catch, add the check: to the
project's `.store-release.md` if it's specific to that app, or to this skill
(the script's checks and this list) if any app could hit it. That is the
whole point of having a pre-flight.
