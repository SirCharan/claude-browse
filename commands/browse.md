---
description: Browse the web with a Sonnet sub-agent in an isolated browser (or your logged-in Chrome); returns a short summary
---

Dispatch the `browser` agent (Agent tool, subagent_type `browser`) exactly once, with this as the task:

$ARGUMENTS

If the task contains `stack:bh` or mentions "my Chrome", tell the agent to use the browser-harness stack.

Relay the agent's summary verbatim. Add nothing.
