# What you do

Everything the agents leave to you, one row each. Each is a click on GitHub or a label. The
daily page is the pinned issue "Kitden desk" in Kitden; it says what waits for you.

| You want to | You do |
|---|---|
| See the desk now | in kitden-sdlc: Actions → desk → Run workflow, on `main` |
| The desk's date is old | the desk's job failed, or `AGENTS_ENABLED` is off in kitden-sdlc: look at the desk's runs in kitden-sdlc's Actions |
| Do not close the desk issue | a closed one is opened anew the next day, unpinned; to stop it, set `AGENTS_ENABLED` to `false` in kitden-sdlc |
| Release | in Kitden: Actions → Release prep → Run workflow; then accept "Kitden X.Y.Z" (next row) |
| Accept an agent's pull request | review it; if it is a draft, fix what "Fix before merge" names in its body and press Ready for review; merge it with a merge commit |
| Turn one down | close it |
| Say a bot issue is real | put `confirmed` on it; it stays open until fixed |
| Say a bot issue is wrong | close it with `false-alarm` |
| Say a review was useful or wrong | 👍 or 👎 on the "Agent review" comment |
| A reviewer gave no answer (the review comment says so) | push again, or re-run the "Agent review" run |
| Record a miss | in the bug form, write `#N` of the pull request that caused the bug under "Caused by" |
| Ask for a test (not live yet) | put `agent-test` on the issue |
| Ask for a fix (not live yet) | put `agent-fix` on a `bug` issue |
| Skip review on one pull request | put `no-agent-review` on it |
| Start an agent again after a pause | close its "… is paused" issue |
| Stop one agent | set its switch variable to `false` |
| Stop everything | set `AGENTS_ENABLED` to `false` in both repositories: every agent stops; the desk's count still runs |
| Answer a person | write yourself; no bot answers people |

## The five lights

The desk shows Works, Clients, Bugs, Agents and Queue. Green is fine, amber is worth a look
this week, red is worth a look today, and grey means the desk could not read something and
found nothing bad. The rules for each are in [agents.md](agents.md#the-desk).

On the desk each light is a badge on a line of its own: green with a check ("ok"), amber with
a question mark ("look"), red with a cross ("wrong"), grey ("not measured"). A light that is
not green has its reason beside the badge. Under the five, one line says how they stand.

- **Works:** on `main`'s newest commit, the checks its push started passed, and so did every
  check `main` requires.
- **Clients:** no major client change you confirmed has been open long.
- **Bugs:** open bugs did not grow three Mondays in a row, and no confirmed major bot issue is
  over 14 days old.
- **Agents:** none is paused, the watcher is within its two urgent issues a week, no agent job
  is a required check, none fails most of its runs.
- **Queue:** nothing has waited for you for long.

## The switches

A switch is a repository variable, set to `true` or `false` on the repository's Variables page.

| Variable | Where | Stops |
|---|---|---|
| `AGENTS_ENABLED` | both repositories | every agent of that repository; in kitden-sdlc also the desk's posting of its issue in Kitden |
| `REVIEW_LIVE` | Kitden | the two reviewers |
| `WATCH_LIVE` | kitden-sdlc | the client watcher's daily run |

The Variables pages:

- Kitden: <https://github.com/KonstantinStarovoytov/kitden/settings/variables/actions>
- kitden-sdlc: <https://github.com/KonstantinStarovoytov/kitden-sdlc/settings/variables/actions>
