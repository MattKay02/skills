# Rejections and resubmission

From "there's an issue with your submission" to back in the review queue,
usually the same day. The shape is always: read it exactly, reproduce it,
decide whether it needs a new binary, fix the cause rather than the symptom,
reply, resubmit.

## 1. Read the rejection exactly

The tool can't read App Review's message: ask the user to paste it (the
email, or App Store Connect's App Review page for the submission), with any
screenshot it carries. It gives four things to note before doing anything:

- **The guideline number** (e.g. "Guideline 4 - Design", "2.3.7"). It names
  the rule; the paragraph under it names the instance.
- **The review device** (often an iPad Air, even for an iPhone-only app).
- **The version and build reviewed.** If it isn't the build you think it is,
  stop and work out why.
- **Any screenshot attached.** It shows the exact screen. A screen with no
  back button, a sheet, a particular state, tells you which path the reviewer
  took.

Play's rejection or policy email names the policy and usually the element
(listing, Data safety, a permission).

## 2. Reproduce it

Find the path the reviewer took to that screen, in the code and ideally on the
review device class. The cause is often one step earlier than the screen in
the message, or on a second path to the same screen. Fix every path, and
write a test for the reviewer's path.

## 3. Binary or metadata?

- **Metadata only** (a picture, the description, a console answer, review
  notes): fix it in the console or with `listing` / `screenshots`, and
  resubmit **the same build**.
- **Needs a new binary**: the fix goes out as the **next version** (a version
  is submitted once; see release.md). Bump the version and build, build it,
  then `prepare --build N`, which renames the open rejected record to the new
  number and attaches the build.
- **Information needed, not a defect** (the demo account didn't work, the
  reviewer couldn't find a feature): reply with exact steps; often nothing
  needs rebuilding.

## Rejections seen often, and their real fixes

| Guideline | What it usually means | Fix |
|---|---|---|
| **2.3.7** (metadata) | a price in a picture or text: "Free", "trial", "% off" | remove it everywhere it appears: every language's pictures and text, app previews, the product page header, and the Play listing too; resubmit the same build |
| **2.3.2** | paid features shown without saying they need a purchase | label them ("Subscription") in the pictures and description |
| **2.3.3** | pictures that don't show the app in use, or show an old app | redraw from the current app |
| **4** (Design), cited for Sign in with Apple | the app asks for a name or email after Sign in with Apple | skip the question for an Apple account; don't widen what's asked of Apple's sheet beyond what the privacy policy says |
| **4.8** (login services) | the app offers a third-party login without an equivalent privacy-focused option such as Sign in with Apple | offer one |
| **5.1.1(v)** | an app with accounts and no in-app deletion; or deletion that doesn't revoke the Apple token | add in-app deletion; revoke Sign in with Apple tokens on delete |
| **5.1.1** (data) | permission prompts that don't explain the use; data asked for that the feature doesn't need | rewrite the usage strings; make the request optional |
| **3.1.1** | digital content or features unlocked outside in-app purchase | sell it through in-app purchase |
| **3.1.2** | subscription terms missing: length, price per period, restore, links to terms and privacy | add them to the purchase screen and the listing |
| **2.1** (completeness) | a crash, a dead end, a broken demo account; often on iPad | reproduce on the review device; fix; check the demo account |

When a guideline isn't here, read its current text in Apple's App Review
Guidelines (or Play's policy centre) before deciding on a fix.

## 4. Reply

Reply in App Store Connect (App Review, the submission, *Reply to App
Review*). Short and factual: what was wrong, what changed, which version and
build has the fix, and how to check it in a few taps. No apology essay, no
argument.

```
Hello,

Thank you for the review. We have fixed the <issue> in version <x.y.z> (build <N>).

<One or two sentences: what the app does now, in the reviewer's terms.>

To check: <the exact taps to reach it>.

Best regards,
<Name>
```

If you believe the rejection is wrong, say so politely in the reply with the
reasoning and ask for approval as is; Apple sometimes offers that. A formal
appeal goes to the App Review Board, and is for when a reply hasn't settled
it.

## 5. Resubmit

**Use the same submission. Never cancel it to start again.** Cancelling drops
everything else in it, and on iOS a first subscription and its group fall
back to the version page and must be attached again by hand.

**iOS**, in App Store Connect, App Review, the submission marked *Unresolved
Issues*:

1. Put the fix on the version:
   - **Metadata only:** fix the text or pictures (`listing`, `screenshots`,
     or the console). The build stays as it is; don't run `prepare`.
   - **New binary:** `prepare --build N` attaches the new build (and renames
     the version if its number changed). It keeps the version's release type.
2. If the version's row still says *Rejected* and **Resubmit to App Review**
   is grey, open the row's **Edit** (the version page): a change made through
   the API isn't always seen until the version page is opened. Back on the
   submission, the row reads *Ready for Review*.
3. Post the reply, then press **Resubmit to App Review**.
4. Confirm with `status <app>`: the submission and version read
   `WAITING_FOR_REVIEW`.

`submit` deliberately refuses while a submission is in Unresolved Issues,
because sending a second one is refused and cancelling the first loses its
contents.

**Expedited review:** Apple offers one through its contact form for a genuine
time-critical reason (an event the release is tied to, a serious bug in the
live version). Whether a resubmission after a rejection keeps the expedited
place isn't guaranteed; if time matters, say so in the reply.

**Play:** fix the listing, Data safety or declaration the email names, or
release a fixed build with `submit --android`; Play re-reviews on its own.

## 6. Make it the last time

Add what this rejection taught to the pre-flight: to the project's
`.store-release.md` if it's specific to this app, or as a check in this skill
if any app could hit it. Note it in the project's changelog with the
guideline and the date.
