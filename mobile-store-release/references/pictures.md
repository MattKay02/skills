# Store pictures

What the stores accept, what gets a submission rejected, and how to check a
set before it goes up. Designing the pictures is a different job: the
`motion-sketchbook` skill draws options from the app's real screens. This
section is the gate between a finished design and an upload.

## Draw them from the app as it ships

Every picture's app screen should be the release candidate's real screen,
rendered from the current code (a screenshot test, a fixture-driven capture,
or a device), not a mockup. Two reasons:

- **Accuracy is a review guideline** (App Store 2.3.3, Play's misleading
  claims policy): pictures must show the app in use, as it is.
- **Pictures drift.** A redesign ships and the store still shows the old
  screens and last month's dates. When the UI a picture shows has changed
  since it was drawn, redraw it before release.

## Sizes and formats

| Store | Asset | Accepted |
|---|---|---|
| App Store | iPhone screenshots | the largest size, 6.9" (1320x2868 or 1290x2796, either orientation; 1260x2736 is newer and accepted by the tool); Apple scales it for smaller phones. 1 to 10 per size. |
| App Store | iPad screenshots | 13" (2064x2752 or 2048x2732), **only if the app runs natively on iPad**. An iPhone-only app needs none (but is still reviewed on an iPad: see preflight). |
| App Store | all | PNG or JPEG, RGB, **no alpha channel** (a transparent pixel gets the upload refused). |
| Play | phone screenshots | 2 to 8; PNG or 24-bit JPEG, no alpha; shortest side at least 320 px, longest at most 3840 px, at most 2:1. |
| Play | 7" and 10" tablet | optional; same rules. |
| Play | feature graphic | exactly 1024x500, no alpha. Required. |
| Play | icon | 512x512 32-bit PNG. |

If a store refuses a size this table allows, its spec has moved: check the
store's current screenshot specification and update the table.

The tool's folders: iOS pictures go in `<screenshots.ios>/<DISPLAY_TYPE>/`
(e.g. `APP_IPHONE_67/`), or loose in `<screenshots.ios>/`, where the tool works
out the display type from the pixel size. Android: `<screenshots.android>/`,
with optional `sevenInch/` and `tenInch/` subfolders. Files upload in name
order, so name them `01-...`, `02-...` (a bare `1-`, `10-` sorts wrongly
past nine).

App previews (videos on the product page) aren't handled by the tool;
they're uploaded in App Store Connect.

## The words on a picture

These have rejected real submissions. Check every picture for them:

- **No price, anywhere.** Not "Free", not "£4.99", not "Free trial", "50%
  off", "Sale" or "Limited time". App Review rejects it under 2.3.7 (metadata
  must not include pricing), Play under its store listing policy, and a price
  in a picture is wrong in every currency but one anyway.
- **Say which features need a subscription.** If a picture shows a paid
  feature, a small "Subscription" label beside it keeps the listing honest
  (2.3.2: make clear which features require additional purchases). Naming the
  tier is fine; naming its price is not.
- **Nothing the app doesn't do,** no "#1" or award claims you can't show, and
  no other company's marks or devices (no Android phone on the App Store,
  guideline 2.3.10; no iPhone frame on Play).
- **Every language.** A price word in one locale's pictures gets the whole
  submission rejected. If the app has localized pictures, check them all.

## The check

1. **`store.py pictures <app>`**: sizes, format, alpha, counts and order, for
   both stores. It exits 1 while anything is BLOCK; fix those. The script
   **cannot read the words** in an image.
2. **Look at every picture yourself, at full size.** Open each file and
   check:
   - price words and claims (above);
   - text clipped at an edge, or covered by a home indicator, navigation bar
     or the phone frame;
   - a stale screen: an old design, a date or a "today" that will look wrong
     next week, placeholder or test data;
   - the order tells the story (the first two are what most people see);
   - every picture in the set looks like the same release.
3. **Show the user** a before/after when replacing a set (a contact sheet of
   old beside new works well), and say what changed in each picture.

## Uploading

- iOS pictures go on the **version open for changes**, so they reach users
  with that version's approval. They stay with the version through a rename.
- **Play's pictures go on the live listing.** They change what every visitor
  sees once Google has reviewed them, independent of any release. Upload them
  with, or just before, the release they describe.
- **`screenshots` replaces the whole set** for each display type it has files
  for; there is no "add one". The plan lists what's there now and what will
  replace it ("delete 6 now there, upload 6"): show the user, since the old
  set is deleted. Display types with no files on disk are left alone. If an
  upload fails partway, the set can be left partial; the tool says what state
  it's in, and re-running with the full set repairs it.
- **One language at a time.** `screenshots` and `listing` work on the app's
  primary language unless given `--locale CODE`; `preflight` lists every
  language's sets so a missing or stale one shows.
- `assets` places the App Store's product page header film and search
  results picture on the open version (iOS only). `--poster HH:MM:SS:FF` sets
  the film's opening still; check it in App Store Connect's preview, where the
  icon and Get button sit over the film.
