# claude-browse

Browsing from Claude Code that keeps the page out of your expensive context: a Sonnet sub-agent clicks, your main model reads a five-line summary.

## Why

- Browsing on the main thread dumps page snapshots into the costly context, where they stay for the rest of the session.
- Two engines exist (agent-browser and browser-harness) and nothing decides which one fits a task.
- Sessions leak. Daemons keep running with no record of their purpose or owner.

## Install

```
claude plugin marketplace add SirCharan/claude-browse
claude plugin install claude-browse
browse doctor
```

The agent calls `${CLAUDE_PLUGIN_ROOT}/bin/browse` and falls back to `browse` on your PATH. To use it in a terminal, link it:

```
ln -s "$(pwd)/bin/browse" ~/.local/bin/browse
```

To work from a local checkout instead, run `scripts/install-local.sh`. It symlinks the agent, command and skill into `~/.claude` and is safe to rerun.

## Use

```
/browse "what is the top story on news.ycombinator.com"
```

The `browse-router` skill also fires on its own when you ask for anything that needs a web page. Either way a Sonnet agent does the browsing and returns a block like this (sample):

```
RESULT: Top story is "Show HN: a tiny Rust database" with 412 points.
KEY DATA:
- Rank 1, 412 points, 187 comments
- Posted 3 hours ago by a user named example
SOURCES: https://news.ycombinator.com
ARTIFACTS: none
SESSION: hn-top (agent-browser, closed) | BLOCKERS: none
```

## How it routes

| Situation | Engine |
|---|---|
| Public pages, scraping, forms, clean isolated session | agent-browser |
| Logged-in sites, your real Chrome, bot-protected pages | browser-harness |
| Needs a saved profile across runs | agent-browser with `--profile` |
| Engine missing | exit code 4, the agent reports the blocker |

## The ledger

Every session gets an entry in `~/.claude-browse/sessions.json`, written with a file lock and an atomic rename.

| Field | Meaning |
|---|---|
| purpose | Why the session exists |
| owner | `claude_session`, `job_dir`, `cwd`, `ppid` of the creator |
| stack | `agent-browser` or `browser-harness` |
| url, profile | Current page and profile name, if any |
| allowed_domains, allowed_tools | Policy; a blocked domain exits with code 3 |
| created, last_used | ISO timestamps, UTC |
| pid, daemon_version | Daemon process and its version |
| headed | Whether the window is visible |
| state | `starting`, `live` or `closed` |

Action logs live in `~/.claude-browse/logs/<name>.jsonl` and screenshots in `~/.claude-browse/shots/<name>/`. Logs store a snapshot hash, never snapshot text.

`browse ls` (sample output):

```
NAME      STACK          PURPOSE            OWNER     AGE   IDLE  PID    STATE
hn-top    agent-browser  read HN front      a1b2c3d4  2m    10s   48211  live
kayak     agent-browser  legacy (unknown)   -         9d    9d    31877  version-mismatch
ey-book   agent-browser  legacy (unknown)   -         9d    9d    -      orphan
```

`browse log <name> -n 20` prints the last 20 logged calls for a session.

## Reaper

- A session is live when its pid answers `kill -0` and its `.sock` file exists.
- Idle longer than `--idle-hours` (default 4): `close`, then SIGTERM after 5 seconds.
- Headed or `--profile` sessions are skipped unless you pass `--force`, because closing them loses cookies.
- Orphans (state files with a dead or missing pid) have their state files deleted.
- Version mismatch (`<name>.version` differs from `agent-browser --version`) is flagged. With `--restart-mismatch`, sessions idle 10 minutes or more are closed and respawn on next open.
- Ledger entries with no daemon become `closed` and are pruned after 7 days. Logs are kept 30 days.

Run `browse reap --dry-run` first and read the plan. Then run it for real.

It never touches the `browsers/` directory, files outside the state set `{config,engine,pid,sock,stream,version,target}`, or any session of a running engine it cannot identify.

An optional SessionEnd hook in `hooks/hooks.json` runs `browse reap --quiet`.

## CLI reference

- `browse open <name> --purpose TEXT [--stack ab|bh] [--url U] [--profile P] [--allow-domains a,b] [--allow-tools t,u] [--headed]` creates a ledger entry and opens the page.
- `browse run <name> <agent-browser args...>` runs one engine command, logs it, prints trimmed output.
- `browse ls [--json] [--all]` lists sessions and daemon state.
- `browse log <name> [-n 20] [--json]` shows the action log.
- `browse reap [--idle-hours 4] [--dry-run] [--restart-mismatch] [--force] [--quiet]` cleans up.
- `browse doctor` checks binaries, versions, port 9222, ledger validity and unmanaged daemons.
- `browse adopt` registers existing daemons with purpose `legacy (unknown)`.

Exit codes: 0 ok, 1 generic, 2 usage, 3 policy, 4 engine unavailable.

## Requirements

- agent-browser 0.38 or newer
- Optional: browser-harness and Chrome with remote debugging on port 9222
- Python 3.9+, standard library only
- macOS or Linux

## Uninstall

```
claude plugin uninstall claude-browse
claude plugin marketplace remove claude-browse
rm -f ~/.local/bin/browse
```

Delete `~/.claude-browse` to remove the ledger and logs.

## Contributing

Run the tests with `python3 -m unittest discover tests`. They use a temporary home and a fake engine, so nothing touches real sessions.

## License

MIT
