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
| Find doc pages for the list | in kitden-sdlc, with `COHERE_API_KEY` set: `uv run --only-group watch-io python scripts/watch_sources.py --kitden <Kitden checkout> > table.md`; see [below](#find-doc-pages-for-the-list) |

## The five lights

The desk shows Works, Clients, Bugs, Agents and Queue. Green is fine, amber is worth a look
this week, red is worth a look today, and grey means the desk could not read something and
found nothing bad. The rules for each are in [agents.md](agents.md#the-desk).

The desk opens with a small table, a row for each light: its name, its mark, what it checks
and why it is not green. The
mark is green with a check ("ok"), amber with a question mark ("look"), red with a cross
("wrong") or grey ("not measured"); only a light that is not green has a reason. Under the
table one line says how the five stand.

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
`WATCH_FEED` is the one switch with three values.

| Variable | Where | Stops |
|---|---|---|
| `AGENTS_ENABLED` | both repositories | every agent of that repository; in kitden-sdlc also the desk's posting of its issue in Kitden |
| `REVIEW_LIVE` | Kitden | the two reviewers |
| `WATCH_LIVE` | kitden-sdlc | the client watcher's daily run |
| `WATCH_FEED` | kitden-sdlc | the watcher's reading of Agent Docs' feed of new doc pages. `off` (or unset, or any other value): the feed is not read at all. `shadow`: the watcher reads the new pages and makes their pieces, but gives none to the model; it only counts them. `live`: the model judges them like any other piece |

After a shadow week (seven daily runs), look at what live would have sent:

- Each run's `watch-input` artifact (kept seven days, on the run's page in Actions) holds
  `feed-shadow.json`: one row a piece, with the page, its day in the feed, the words that kept
  its sections (each once) and its length in characters. No page text is in it: open the page to read it.
- Each run's line in `log.jsonl` on the `watch` branch has `feed`: `pieces` and `waiting` are
  that run's, `dropped`, `held` and `gone` are totals since the feed was first read.
- If the pieces look about what Kitden shows, set `WATCH_FEED` to `live`. The pieces of the
  shadow week are not sent again.

The Variables pages:

- Kitden: <https://github.com/KonstantinStarovoytov/kitden/settings/variables/actions>
- kitden-sdlc: <https://github.com/KonstantinStarovoytov/kitden-sdlc/settings/variables/actions>

## Find doc pages for the list

For each row of Kitden's `docs/clients.md` whose `Source` is `help`, `install` or `guess`, the
script asks Agent Docs for a page that states it, and writes a table. Agent Docs' `/search`
must take `product` first. A trial key works, slowly: 62 rows take 8 to 10 minutes with the
default pause of 7 seconds (`--pause 2` with a paid key). `--client codex`, `--all` or
`--rows CC-04,CX-12` change which rows. Change `Source` in `docs/clients.md` in a Kitden pull
request.

```sh
uv run --only-group watch-io python scripts/watch_sources.py --kitden <Kitden checkout> > table.md
```

- Exit 2: `COHERE_API_KEY` is not set or cannot be used, the list cannot be read, or an option is wrong.
- Exit 3: Agent Docs' `/search` does not take `product`, or its API description could not be read.
- Exit 4: Agent Docs did not wake up; try again later.
- Exit 5: the first 3 searches failed: check the key, the per-minute limit or the server; the table so far is written.

## Agent Docs in a session

Agent Docs, your own index of the clients' docs, reaches your sessions through Kitden. To set
it up again:

- Run `kitden open` and add Agent Docs as a server on Kitden's local page.
- Its key or token stays in the local settings on your machine.
- Nothing about it is committed to any repository.
