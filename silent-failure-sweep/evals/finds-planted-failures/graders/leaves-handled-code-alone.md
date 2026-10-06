---
type: llm
---

Three files look like silent failures but are handled: assistant.ts throws when a reply hits max_tokens; search.ts returns no suggestions on error but pages on-call (at most once an hour); reminders.ts marks failed sends, rethrows, retries them every 10 minutes (including ones stuck in 'sending') and pages after three failures. alerts.ts throws when a page or post can't be delivered.
PASS if none of assistant.ts, search.ts, reminders.ts or alerts.ts is ranked among the silent failures that need fixing. Mentioning them as handled, or a one-line note about minor polish, is fine.
FAIL if any of them is presented as a silent failure or a serious reliability problem.
