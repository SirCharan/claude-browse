# Demo transcript

Illustrative until replaced by a real capture. Output is abbreviated.

## The request

```
> /browse "what is the top story on news.ycombinator.com"
```

## The agent's calls

```
$ browse open hn-top --purpose "read HN front page" --url https://news.ycombinator.com
opened hn-top (agent-browser)

$ browse run hn-top snapshot -i --compact
@e1 link "Show HN: a tiny Rust database"
@e2 link "412 points"
... (trimmed)

$ browse run hn-top click @e2
ok

$ browse run hn-top get text @e2
412 points

$ browse run hn-top close
closed
```

## Summary returned to the main thread

```
RESULT: Top story is "Show HN: a tiny Rust database" with 412 points.
KEY DATA:
- Rank 1, 412 points
SOURCES: https://news.ycombinator.com
ARTIFACTS: none
SESSION: hn-top (agent-browser, closed) | BLOCKERS: none
```

## Afterwards

```
$ browse ls --all
NAME    STACK          PURPOSE             OWNER     AGE  IDLE  PID  STATE
hn-top  agent-browser  read HN front page  a1b2c3d4  1m   5s    -    closed

$ browse log hn-top
ts                    action    target  ok   ms   url
2026-09-30T10:02:11Z  open      -       yes  840  https://news.ycombinator.com/
2026-09-30T10:02:13Z  snapshot  -       yes  210  https://news.ycombinator.com/
2026-09-30T10:02:15Z  click     @e2     yes  95   https://news.ycombinator.com/
2026-09-30T10:02:16Z  get       @e2     yes  60   https://news.ycombinator.com/
2026-09-30T10:02:17Z  close     -       yes  120  -
```
