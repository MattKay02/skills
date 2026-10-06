---
type: llm
---

The service has three pieces that look like silent failures but are handled: assistant.ts checks stop_reason and throws when a reply is cut off; search.ts returns no suggestions on error but pages on-call; reminders.ts marks failed sends, retries and escalates after three tries.
PASS if none of those three is reported as a problem that needs fixing (mentioning them as already handled, or as minor polish, is fine).
FAIL if any of them is listed as a silent failure or a serious reliability problem.
