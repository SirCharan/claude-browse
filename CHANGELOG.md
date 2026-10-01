# Changelog

All notable changes to Claude Browse are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 0.1.0 - 2026-10-01

### Added

- `browser` helper agent. It runs on Sonnet, does the browsing, and returns a reply of 12 lines or fewer.
- `browse-router` skill. It sends ordinary browsing requests to the helper agent.
- `/browse` and `/browse-ls` commands.
- Two backends: agent-browser (isolated, the default) and browser-harness (your logged-in Chrome).
- Session ledger in `~/.claude-browse/sessions.json`, plus one action log per session.
- `browse` CLI with `open`, `run`, `ls`, `log`, `reap`, `adopt` and `check`.
- Domain allowlist with `--allow-domains`, and fixed exit codes for policy and engine errors.
- `scripts/install-local.sh` for installing from a clone.
