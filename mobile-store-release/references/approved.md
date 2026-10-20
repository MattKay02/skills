# Approved, and after

From "review of your submission is complete" to every place that says where
the app stands saying it too. The shape is always: read what was approved,
prove it is public, then update the project's own record of its state, place
by place, and check each one.

Approval is the moment a project's documents go most out of date at once: the
site still says "coming soon", the README says "in review", the changelog
says "submitted", a plan still counts the release as open. Nothing breaks, so
nothing notices, and the next person to read any of them is misled.

## 1. Read what was approved

Ask for the approval email (or read the submission in App Store Connect). It
says more than "approved":

- **The submission ID and the items accepted**: the version, and anything
  sent with it. A first subscription, its group or an in-app purchase is
  approved in the same submission, which is worth recording: the next version
  goes for review without them.
- **When it was submitted**, so the record can say how long review took.

Then `status <app>`:

- `READY_FOR_DISTRIBUTION`: released (it was set to release itself on
  approval).
- `PENDING_DEVELOPER_RELEASE`: approved and held for a manual release.
  `release <app>` on the user's yes to its plan, and only then is anything
  below true.

Play has no approval email worth waiting for, and reads a release in review
as `completed`: its check is the public page in step 2.

## 2. Prove it is public

Don't write "live" anywhere until the public store says so.

- `links <app>` asks each store's public page whether the app answers.
- **The App Store's own record** gives the version on sale and when it was
  released: `https://itunes.apple.com/lookup?id=<apple id>&country=<cc>`
  (`version`, `currentVersionReleaseDate`). Apple says an approved version can
  take up to 24 hours to appear everywhere; the lookup is usually there within
  the minute.
- **Google Play's public page** shows the version and "Updated on" date once
  the release has rolled out.

Note what each store holds now, both of them: an app can be on its second
version in one store and its first in the other.

## 3. Update the project's record, place by place

Every project keeps its state in more places than anyone remembers. The list
belongs in the project's **`.store-release.md`**, under **`## After
approval`**, so this step is a checklist rather than a search:

- **The website's store links**: a badge or button held as "coming soon"
  until the app is on sale. Turning it on usually deploys the live site, so
  **check the live page afterwards**, and anything that reads from it (a
  parent company's site, a link preview) on its own refresh.
- **The README's status**: the badge, the status paragraph, a table of where
  each app is.
- **The changelog**: the version's heading moves from "submitted" to its
  release date, and its note says what happened in review.
- **The release-state document**, if the project keeps one: what is on sale,
  in which store, from which build and commit.
- **The project's own tracker**: a goal or milestone of "on the stores" done,
  tasks it finished closed, and the ones it did not left open.
- **Notes and memory** that say the release is pending.

**If the project has no `## After approval` list, build it now**: search the
repository for the version number and for words like "in review", "submitted"
and "coming soon", ask the user where else they track it, and write the list
into `.store-release.md` before working through it. The next approval then
starts from the list.

Change only what is now true. A place that says a *different* app or version
is pending stays as it is.

## 4. Record what review taught

Add to `.store-release.md`'s history: the date, how long the review took,
what the submission carried, and anything that went differently from last
time. Approvals teach too: that resubmitting a rejected submission kept its
subscriptions, or that a version released itself the minute it was approved.

## Don't

- **Announce it** (a post, a newsletter, a message to testers) unless asked.
  It is the user's moment and their channel.
- **Move branches or tags** because of an approval unless the project's own
  convention says to. Many projects promote at submission, not approval.
- **Say "live" on the strength of `status` alone.** Step 2 is the proof.
