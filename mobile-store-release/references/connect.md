# Connecting a project to the stores

Setting up a project once so every later release is a command: its own keys,
its config, and the console-only steps written down. Do this for a new app,
for a project that has no `.store-release.json`, or when `doctor` fails.

**You never create, see or handle the keys themselves.** The user generates
them in the consoles and saves them where the config points. You write the
config, tell them exactly where to click, and run `doctor` to prove it worked.
If a key's contents ever appear in the conversation, don't repeat them, and
suggest the user revokes that key and makes another.

## 0. Before the keys: what has to exist first

`doctor` can't pass until the stores know the app. Check these first, and
tell the user which are still to do:

- **The app's identifiers.** The bundle ID is Xcode's
  `PRODUCT_BUNDLE_IDENTIFIER` (in the project, or the Runner target in Flutter
  and React Native); the Android package is Gradle's `applicationId`. They go
  in the config exactly.
- **iOS:** the bundle ID registered in the Apple Developer portal
  (Identifiers), and the app record created in App Store Connect (*Apps → +*).
- **Android:** the app created in Play Console (*Create app*), and **its first
  build uploaded by hand** to a testing track in the console. The API can't
  see a package that has never had an upload.
- **A new personal Google Play developer account** must run a closed test
  with at least 12 testers for 14 days before it can apply for production
  access. Organisation accounts don't. Check which this is before promising a
  production date.
- **Builds have a way to reach the stores**: CI, or by hand (Xcode Organizer
  or Transporter for iOS; a Play Console upload for Android). This skill
  starts once a build is there.

## Why a dedicated key per project

- **It can be revoked alone.** A leaked or retired key takes down one
  product's release path, not every product on the account.
- **What changed a store is attributable.** App Store Connect records which
  API key submitted a version; one key per project makes that line mean
  something.
- **One project's tooling can't reach another product.** This needs saying
  honestly, store by store:
  - **Google Play** scopes a service account per app: invite it with access
    to only this project's apps, and it cannot touch the others.
  - **App Store Connect** team keys reach every app on the team, whatever the
    key is called. A dedicated team key is still worth having for the two
    reasons above, but the wall between products is the tool refusing any app
    not in this project's config. If the account offers *individual* API keys,
    a key belonging to a user whose app access is limited to this project's
    apps is a real wall; offer it as the stricter option.

## 1. App Store Connect key

The user does this in App Store Connect:

1. **Users and Access → Integrations → App Store Connect API → Team Keys**
   (requires an Admin or Account Holder). Generate a key.
2. **Name it after the project** (e.g. `myproduct-release`), so the key list
   says what each one is for.
3. **Role: App Manager.** Enough to prepare versions, upload screenshots,
   manage TestFlight and submit for review. Admin is more than release work
   needs.
4. **Download the `.p8` immediately.** Apple offers it once; a lost one means a
   new key.
5. Note the **Key ID** (on the key's row) and the **Issuer ID** (top of the
   page).

Then the key folder, outside every repository (e.g.
`~/.store-keys/<project>/`), holds:

- `AuthKey_<KEYID>.p8`
- `asc.json`: `{"issuer_id": "...", "key_id": "...", "key_file": "AuthKey_<KEYID>.p8"}`

Restrict the folder to the user's own account (`chmod 700` on macOS and
Linux; on Windows, `icacls` removing inherited access for everyone but the
user and SYSTEM).

## 2. Google Play service account

The user does this in Google Cloud and Play Console:

1. **Google Cloud console:** pick or create a project for this product, and
   enable the **Google Play Android Developer API** in it.
2. **IAM & Admin → Service Accounts → Create.** Name it after the product
   (`myproduct-play-publisher`). It needs no Cloud roles.
3. On the account: **Keys → Add key → JSON.** Save the downloaded file in the
   same key folder as `play-service-account.json`.
4. **Play Console → Users and permissions → Invite new users**, with the
   service account's email address:
   - **App permissions: add only this project's apps.** This is the wall
     between products.
   - Per app: the permissions to view app information, release to
     production, release to and manage testing tracks, and edit the store
     listing (Play's names for these change over time: today they read
     roughly *View app information*, *Release to production...*, *Release apps
     to testing tracks*, *Manage testing tracks...* and *Manage store
     presence*). No account-level permissions.
5. A newly invited service account can take a while before Play accepts it.
   If `doctor` says the account has no access and the invite is minutes old,
   wait and try again rather than changing permissions.

## 3. The project's config

Write `.store-release.json` at the project root (see the example in
`scripts/example.store-release.json`). Key paths use `~` so the same file
works for anyone who keeps their keys in the same place; it holds no secrets,
so commit it. One entry per app, with only the platforms it ships on.

Folders the config names don't have to exist yet; `pictures` and `doctor`
say what's missing.

Then `python <skill>/scripts/store.py doctor <app>`. Every check should be OK;
NOTE lines are store folders the config names that don't exist yet, which is
fine until there are pictures to put in them. Each FAIL is followed by a
`fix:` line saying which step above to revisit, and `doctor` exits 1 until
none are left.

**Key paths are refused inside any git work tree**, found by looking upward
for `.git`. If the user's home folder is itself a git repository (a dotfiles
setup), `~/.store-keys` is refused too: keep the keys somewhere no repository
contains.

## 4. What this tool leaves to the consoles

Some of these have no API at all (creating app records, App Privacy, a first
subscription's attachment); others do, but are one-time setup where the
console's own questions and checks are the safer place to answer them. List
the ones this app still needs in the project's `.store-release.md`, so a
release doesn't stall on one at the last minute:

- **Creating the app records** (see 0 above).
- **Agreements, tax and banking**, before anything paid or with
  subscriptions can be sold.
- **App Privacy** (Apple) and **Data safety** (Play): what the app collects
  and why. They must match what the app actually does and what its privacy
  policy says.
- **Age ratings** on both stores, and Play's **content declarations** (ads,
  target audience, health, news, financial features).
- **Pricing and availability**, and Play's **production countries** (a new
  production track has none).
- **In-app purchases and subscriptions**: created in the console. **A first
  subscription is attached on the version page** and goes for review with a
  version; after that it can be submitted on its own.
- **The App Review sign-in and contact details**, when the app needs an
  account: a demo account that works, entered in the console. The tool can
  set review notes but never carries a password.
- **Google Play's first release of a new app.** Play treats an app as a draft
  until it is first published, and takes only draft releases for it. Rolling
  a build out to internal testing does not end that. Set
  `"draft_until_published": true` for the app (then `submit --android` sends
  a draft on its own, and its plan says why), and roll the first production
  release out by hand in the console once. Set it back to `false` after;
  `preflight` warns if it's still on once production has a completed release.
- **Play's email lists of testers.**

## Moving a project off a shared key

1. Create the dedicated keys (1 and 2 above) and point the config at them.
2. `doctor` until every line is OK.
3. Run one read-only command per store (`status`) to be sure.
4. Then the user revokes the shared key's access for this project: removes
   the old Play service account from these apps, and, once no other project
   still depends on it, revokes the old App Store Connect key. Ask before
   suggesting a revocation that could break another project's releases.
