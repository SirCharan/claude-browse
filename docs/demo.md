# Demo transcript

The real run from 30 Sep 2026 on Y Combinator's news page. The reply is the whole text the main model received, unedited.

## The request

```text
/browse "top story on Hacker News, with points"
```

## The reply

```text
RESULT: The current top story on Hacker News is "Livenerf: Has Opus 5.5 been nerfed yet?", with 561 points and 239 comments.
KEY DATA:
- Title: Livenerf: Has Opus 5.5 been nerfed yet?
- Points: 561
- Comments: 239
- Linked URL: https://github.com/ninjahawk/livenerf
SOURCES: https://news.ycombinator.com
ARTIFACTS: none
SESSION: ab-hn-top (ab, closed) | BLOCKERS: none
```

## Measured

| What | Tokens |
|---|---|
| Whole page | about 6,400 |
| Clickable parts only | about 3,350 |
| Reply the main model read | about 90 |

The run took 11 seconds with agent-browser 0.38.1.
