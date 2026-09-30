---
name: browse-router
description: Routes any request to visit, open, scrape, click, fill, screenshot, or log into a website, check a live page, or research on the web when curl is not enough. Use it so browsing never runs on the main thread.
---

# browse-router

## Rule

Never browse in the main thread. Delegate to the `browser` agent (Agent tool, subagent_type `browser`), or run `/browse <task>`.

## What to pass the agent

- The task, stated as an outcome.
- Starting URLs.
- Allowed domains, if the scope should be limited.
- Keep-session flag, if the user wants the browser left open.
- "my Chrome" or `stack:bh` if the task needs the user's logged-in Chrome.

## What comes back

A summary of at most 12 lines: RESULT, KEY DATA, SOURCES, ARTIFACTS, SESSION and BLOCKERS. Relay it; do not re-browse to verify unless asked.

## When not to use

- Plain `curl` or WebFetch returns the content (static pages, APIs, raw files).
- The user only wants a local file read.

## Housekeeping

`browse ls` lists sessions in the ledger. `browse reap --dry-run` shows idle or orphaned daemons; ask before a real reap, since it closes live windows.
