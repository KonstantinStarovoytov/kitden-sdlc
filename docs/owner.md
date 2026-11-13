# What you do

Everything the agents leave to you, one row each. Each is a click on GitHub or a label. The
daily page is the pinned issue "Kitden desk" in Kitden; it says what waits for you.

| You want to | You do |
|---|---|
| Release | Actions → Release prep → Run workflow; merge "Kitden X.Y.Z" |
| Accept an agent's pull request | review it, press Ready for review, merge |
| Turn one down | close it |
| Say a bot issue is real | put `confirmed` on it; it stays open until fixed |
| Say a bot issue is wrong | close it with `false-alarm` |
| Say a review was useful or wrong | 👍 or 👎 on the "Agent review" comment |
| A reviewer gave no answer (the review comment says so) | push again, or re-run the "Agent review" run |
| Ask for a test (not live yet) | put `agent-test` on the issue |
| Ask for a fix (not live yet) | put `agent-fix` on a `bug` issue |
| Skip review on one pull request | put `no-agent-review` on it |
| Start an agent again after a pause | close its "… is paused" issue |
| Stop one agent | set its switch variable to `false` |
| Stop everything | set `AGENTS_ENABLED` to `false` in both repositories |
| Answer a person | write yourself; no bot answers people |

## The five lights

The desk shows Works, Clients, Bugs, Agents and Queue. Green is fine, amber is worth a look
this week, red is worth a look today, and grey means the desk could not read something and
found nothing bad. The rules for each are in [agents.md](agents.md#the-desk).

- **Works:** `main`'s checks pass.
- **Clients:** no major client change you confirmed has been open long.
- **Bugs:** open bugs are not piling up, and no confirmed major one is old.
- **Agents:** none is paused or over its cap, and no agent job is a required check.
- **Queue:** nothing has waited for you for long.

## The switches

A switch is a repository variable, set to `true` or `false` on the repository's Variables page.

| Variable | Where | Stops |
|---|---|---|
| `AGENTS_ENABLED` | both repositories | every agent of that repository; the desk's issue in kitden-sdlc |
| `REVIEW_LIVE` | Kitden | the two reviewers |
| `WATCH_LIVE` | kitden-sdlc | the client watcher's daily run |

The Variables pages:

- Kitden: <https://github.com/KonstantinStarovoytov/kitden/settings/variables/actions>
- kitden-sdlc: <https://github.com/KonstantinStarovoytov/kitden-sdlc/settings/variables/actions>
