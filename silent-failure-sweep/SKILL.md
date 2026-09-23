---
name: silent-failure-sweep
description: Hunt a codebase for failures that happen without anyone being told — AI calls capped at a token limit whose stop reason is never checked, errors caught and turned into empty results, background jobs with no failure handler that leave records stuck mid-state, counts that report the same problem every run without escalating, and limits applied quietly. Produces a ranked punch list with file:line, what silently goes wrong, who never finds out, and the loud alternative, and proves the worst with a cheap live probe. Use when asked to audit reliability, find silent failures, check "is anything failing quietly", review a pipeline or background-job system, or after one silent failure is found (there are usually more of the same shape).
---

# Silent failure sweep

You're looking for one specific shape of bug: **the system knows something went
wrong, and the person who could act on it doesn't.** The log is honest. The job
row says "processing". The summary line says "3 couldn't be checked" — the same
3, every week, for two months. Nothing is broken in the way tests catch; the
failure is that nobody was told.

These are worth a dedicated sweep because they cluster. They come from the same
habits — a limit set once and never checked, a `catch` that keeps the happy
path tidy, a status that has a way in but no way out — so finding one means the
same author, under the same pressure, probably wrote the others. In the session
this skill came out of, one finding led to five more of the same shape in a day.

## Before you start

Ask for scope if it isn't given: one feature, one pipeline, or the whole repo. A
whole-repo sweep is fine but say up front that you'll rank, not list — twenty
theoretical findings bury the one that's costing someone.

**Don't fix anything unless asked.** This skill produces a punch list. Fixes to
failure handling change behaviour users see, and the owner decides the order.

## The patterns

Work through each. The greps are starting points — every hit needs reading in
context, because many are deliberate and correctly commented.

### 1. Capped model calls nobody checks

An LLM call with a `max_tokens` / `max_output_tokens` limit whose response is
used without checking why it stopped. When the cap is hit the model simply
stops mid-sentence, and the truncated text is returned exactly like a finished
one. Long inputs (documents, transcripts, codebases) are where this bites.

```
grep -rn "max_tokens\|max_output_tokens\|maxOutputTokens" --include=*.{ts,js,py}
```

For each call: is `stop_reason` (Anthropic) / `finish_reason` (OpenAI) checked
before the output is used? If not, can the input be long enough to hit the cap?
Estimate: output tokens needed ≈ input size when the task is transcription,
extraction or translation. If one call carries a whole variable-length input,
it will eventually truncate.

**Loud version:** treat the cap as an error; split the input and retry, and
fail visibly when it can't be split.

### 2. Errors turned into empty results

A failed read that returns `[]`, `null` or `0` — which the caller then reports
as "none found". In a system people rely on for answers, "none" is almost
always the comfortable answer, which is what makes it dangerous.

```
grep -rn "catch *{ *return \[\]\|catch *(.*) *{ *return \[\]\|?? \[\]\|?? 0\b\|| \[\]" --include=*.{ts,js}
```

Supabase/PostgREST specifically: `const { data } = await db.from(...)` with
`error` never read, then `data ?? []`. A wrong column name fails the WHOLE
select and silently reads as zero rows.

**Loud version:** distinguish "none" from "couldn't tell". Return an error or
an explicit unknown state, and show the difference.

### 3. Background work with no way out on failure

A job sets a record to an in-progress state (`processing`, `extracting`,
`pending`) and only a *successful* path moves it on. When the job throws and
its retries run out, the record sits in progress forever — and any "stale"
detector in the UI will blame the wrong thing (usually the worker).

Look for: job/queue functions (Inngest, BullMQ, Sidekiq, Celery, cron handlers)
that write an in-progress status but have no failure hook (`onFailure`,
`on_failure`, `failed` event, `finally`) that writes a failed status.

Then check the data, which is usually faster than the code:

```sql
select status, count(*), min(updated_at)
from <jobs_table>
where status in (<in-progress states>) and updated_at < now() - interval '1 hour'
group by status;
```

**Loud version:** a failure handler that writes `failed` plus a message written
for the person who'll read it, not for the developer.

### 4. Counts that never escalate

A summary that reports a number of failures each run — "3 sources couldn't be
checked", "2 syncs failed" — without saying *which*, or *for how long*. Three
different things failing once reads identically to the same three failing for
months. The count is there; the alarm never is.

Look for: aggregate counters in reports, emails, dashboards and job summaries.
Ask of each: is there history to compare against? Does anything escalate when
the same item fails repeatedly?

**Loud version:** name the items, show their streak (how many runs in a row),
and escalate past a threshold — the same alarm as a real incident.

### 5. Limits applied without saying so

`.slice(0, N)` on text fed to a model, an export or a comparison; `.limit(N)`
on a query whose result is treated as "all of them"; a pagination loop that
stops at one page. Budgets are fine. **A budget nobody is told about is a
silent failure** — the consumer believes it saw everything.

```
grep -rn "\.slice(0, \|\.substring(0, \|\.limit(\|LIMIT " --include=*.{ts,js,py,sql}
```

Especially bad: a comparison or audit that only read part of its input and
then reports something as *missing* — when it was on the part it didn't read.

**Loud version:** record that the cut happened, tell the model it's reading an
excerpt, and tell the person the result is partial.

### 6. Defaults that hide absence

`?? 1`, `?? 0`, `|| "unknown"`, `|| default` on values that drive **billing,
metering, quotas or compliance**. A missing value silently becomes a plausible
one. Example shape: a usage meter reading `pages ?? 1` where nothing ever sets
`pages` — every document counts as one page, forever, and the number looks
reasonable.

**Loud version:** make the value required, or fail when it's absent.

### 7. Health checks that check the wrong thing

A monitor that confirms a job *ran*, when the question that matters is whether
it *achieved* anything. A cron can run green every week while the thing it
exists to produce never arrives (nothing approved, nothing sent, nothing
published).

**Loud version:** check the outcome, and name the blocker.

## Proving the worst ones

Reading code tells you the mechanism. It doesn't tell you the threshold, and
owners discount findings that sound theoretical. For the top one to three,
prove it — cheaply:

- **Truncation:** build a synthetic input that should cross the limit, with a
  unique marker on every section (e.g. `[P17-L04]` on every line of page 17),
  run it through the real function — not a copy — and count which markers came
  back. "Pages 19–40 missing, no error, ends mid-line" ends the discussion.
- **Stuck states:** the SQL above, against real data.
- **Empty-on-error:** point the query at a misspelled column in a test and
  watch it return `[]`.

State the cost before spending money on a live call, and keep it to one call
where one call proves it.

## Reporting

A ranked punch list. For each real finding:

| | |
|---|---|
| **Where** | `path/to/file.ts:123` |
| **What goes wrong** | one sentence, concrete |
| **Who never finds out** | the person who'd act on it |
| **Proven?** | how — or "read, not run" |
| **Loud version** | the smallest change that makes it visible |

Rank by consequence, not by count: *would someone act on a wrong answer?*
(compliance, safety, money) beats *would someone be confused?* beats *would a
developer eventually notice?*

Then list, briefly, what you checked and ruled out, so the owner knows the
coverage — and say plainly what you didn't look at.

## The principles, when a case is unclear

- **Honest isn't the same as loud.** A failure written to a log, or predicted in
  a design doc, is still silent if the person who can act never sees it.
- **The absence of recorded doubt is not recorded confidence.** When unsure
  whether something succeeded, the default is "unknown", not "fine".
- **Fail closed where someone acts on the answer.** A refusal they can see beats
  a confident wrong answer they can't.
- **Put the noise where the actor looks** — on the record in their queue, in
  the subject line — not in a log or behind a toggle.
