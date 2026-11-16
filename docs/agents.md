# The agents and workflows

The details behind the [README](../README.md): what each workflow runs, its model, what it may
do and its limits. Every workflow that runs an agent follows [RULES.md](../RULES.md).

## The agents

| Agent | Runs when | Model | May do | Limits | Switch |
|---|---|---|---|---|---|
| `claude` reviewer | a pull request opens or changes | Claude Sonnet or Opus, picked by [the review tasks](../evals/README.md) | read the checkout, write findings | see below | `AGENTS_ENABLED` and `REVIEW_LIVE`, in Kitden |
| `luna` reviewer | the same | GPT-6 Luna | read in a sandbox with no network, answer with findings | see below | the same |
| workflow check | a pull request changes `.github/workflows/` | none | run zizmor, actionlint and the rule checker | read only | none |
| list check | a Kitden pull request changes `docs/clients.md` | none: a script, not an agent | read the doc page of each row it adds or changes, and warn | read only, no secret; 10 minutes; at most 20 pages, 40 exact words a row and 3 minutes of checking; never turns red for a page | none |
| the desk | every day at 06:41 UTC, or by hand | none | count reviews, read Kitden's facts, commit `numbers.md`, `numbers.json` and `desk.json` to the `numbers` branch; a second job shows `desk.json` as the issue "Kitden desk" in Kitden, and opens a `ci-failure` issue for each red nightly part, as Lantern | no model, no pull request code; 10 and 5 minutes, one run at a time | `AGENTS_ENABLED`, in kitden-sdlc, for the issue only: the numbers update without it |
| client watcher | every day at 05:17 UTC, or by hand | Claude Sonnet 5.5 at effort medium, on `ANTHROPIC_API_KEY` | read client release notes and docs; a job without the model opens issues in Kitden as Lantern and commits the memory to the `watch` branch | 15 minutes per job, 60 model calls, one run at a time | `AGENTS_ENABLED` and `WATCH_LIVE`, in kitden-sdlc |
| release prep | the owner runs it by hand in Kitden | Claude, the model Kitden's caller names | read the checkout and the release context; write the notes, the README, the guide, the policy files and the plugin README to one output folder; scripts check them, and the model gets one pass to fix what they find; jobs without the model set the version, record the README pictures and open the release pull request as the release app (a draft when a problem is left) | two agent jobs with the same read-only tools: 25 minutes and 60 turns, then 10 minutes and 15 turns; one run at a time; it does not start while a release pull request is open or three bot pull requests wait, and stops when the branch `prepare-vX.Y.Z` exists | `AGENTS_ENABLED`, in Kitden; started by hand |
| release watch | every day in Kitden, or by hand | none | open or update two issues in Kitden as Lantern | no model, writes issues only, one run at a time | `AGENTS_ENABLED`, in Kitden |
| publish | a `vX.Y.Z` tag in Kitden, after PyPI | none | move the `release` branch, publish to the MCP Registry, open the Homebrew pull request, write a summary | no model; each job writes to one place with its own short-lived token | none |

## One look

Everything a bot posts is built the same way, by [bot_style.py](../scripts/bot_style.py): the
watcher's issues, the review comment, the release pull request, the release watch's issues and
the desk.

| You see | It means |
|---|---|
| A row of badges, first | The facts at a glance |
| A name and a number on orange | A version: a client's or Kitden's |
| `risk` with three bars, one to three filled | The risk for a Kitden user: low, medium, high |
| `sure` with a check or a question mark | Whether the bot is sure |
| Green with a check, red with a cross, amber with a question mark | A check passed, failed, or needs a look |
| A grey badge | A plain count or fact |
| One plain line under the badges | What happened |
| Problem, Fix, Checklist, Checked by scripts | The parts, by the same names everywhere |
| A purple "Important" box | You must do something; it says what |
| A blue "Note" box | Nothing is needed from you |
| An amber "Warning" box | Something is wrong |
| Small grey text, last | Who wrote it, the sources, how it works |

A badge is a picture from shields.io, light or dark by the reader's theme, in Kitden's own
colors. Its text is plain letters and digits, cut at 40, whatever it was given; when the
picture does not load, the reader sees that text. A model's text never draws a box or a
heading of its own: it is put on one line, or inside a quote.

## The desk

Once a day a job without a model reads facts from GitHub and files and works out five lights and
what waits for the owner ([desk.py](../scripts/desk.py)). It saves them as `desk.json` on the
`numbers` branch, next to the public page
[numbers.md](https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/numbers/numbers.md). A
second job, only with `AGENTS_ENABLED` on, shows `desk.json` as the pinned issue "Kitden desk" and
adds one comment with the week's first run. Started by hand from another branch, the desk
neither commits nor posts. What the owner does about each line is in [owner.md](owner.md).

A light is the worst thing the read facts prove: bad news that was read always wins, and grey
means something was not read and nothing bad was found. A red or amber light also says what it
could not read, and links the issue it names. The overall light is the worst of the five, red
first, then amber, grey and green.

Works judges the newest run of each check on `main`'s newest commit, among the checks that
the push to `main` started. A check `main` requires counts whatever started it, and so does a
check whose start is not known. Release prep started by hand and scheduled runs do not count.

Works and Clients also judge Kitden's nightly tests: the newest finished scheduled run on
`main` of `nightly.yml` (parts `systems`, `clients`, `browser`) and of `latest-deps.yml` (part
`test`). The jobs of one matrix are one part. A part is red when one of its jobs ended
`failure`, `timed_out`, `action_required` or `startup_failure`, green when every one of its
jobs passed, and grey otherwise. Grey covers a job that ended `cancelled` (stopped by hand or
by a newer run, or past its time limit: `nightly.yml` has fail-fast off), a skipped job, no job
of the part, and a run that could not be read. It also covers a skipped night: the run must be
dated (UTC) the desk's day or the day before. Clients judges the part `clients`, Works the
rest. GitHub starts scheduled runs hours late, so the desk may show the night before; each
reason gives the run's date.

A grey night does not wipe what came before it. A red part keeps the day it turned red
through grey nights, and its light stays as a red part's would (amber, then red from 3 days
after that day), because nothing has shown it fixed; the "Nightly:" line still says "red
since". A part grey for 3 nights in a row with no red before turns its light amber, so a
nightly that hangs every night is seen. Grey never opens or closes an issue.

`desk.json` keeps one row per part under `nightly`. A row holds the state, the failed jobs
with their first failed step, the run, and the run's date as `night`. It also holds `since`
(the day a red part turned red), `grey_since` and `grey_nights` (the grey stretch), and `why`
for a grey part. The count of the tests in Kitden's `tests/set-aside.txt` is `set_aside`.
`nightly` and `set_aside` are `null` when they were not read.

The second job also gives each red part one issue in Kitden, "<workflow>: <part> is red" (for
example "Nightly tests: clients is red"; the workflow is the run's name, or its file's name when
the run has none), with the labels `automated` and `ci-failure` and the bots' one look. It is
rewritten each day and closed when the part is green: one issue per part, not per night or per
system. A grey part's issue stays as it is. When no part is grey, an open `ci-failure` issue of
the bot that names no part of today is closed, because its job no longer exists. The desk issue's
Health section has one "Nightly:" line: each part's mark, since when a red part is red, since
when a part grey for a second night has had no finished run, the night the rows are about, and
the count of the tests set aside.

The desk also checks the [workflow map](map/index.html) against the workflow files, as
`map_text.py --check` does: this repository's from the desk's checkout of `main`, Kitden's and
the tap's from their `main` (their lists of files through `gh`, with the job's token).
`desk.json` keeps each difference under `map.stale`; `map` is `null` when a file or a list
could not be read. With one or more differences the Health section has one more line, "The
workflow map is out of date in N places. Run `scripts/map_text.py --write`." It is no light
and waits for nobody.

| Light | Red | Amber | Grey |
|---|---|---|---|
| Works | a check `main` requires failed, timed out, was cancelled, needs an action or failed to start; any check did, when `main`'s rules were not read whole; a nightly part has been red since 3 or more days before its newest run, or was before grey nights | a check `main` does not require failed; a check has not finished or ended neither well nor badly; a check `main` requires has not run or did not pass; a nightly part is red, or has been grey 3 nights in a row | no check run of `main` was read, or none passed; `main`'s rules were not read, or only in part; the nightly runs were not read, or a nightly part is grey |
| Clients | a `confirmed` `major` client change has been open over 7 days; the nightly part `clients` has been red since 3 or more days before its newest run, or was before grey nights | the same change, over 3.5 days; the nightly part `clients` is red, or has been grey 3 nights in a row | the issues were not read; the watcher logged no run that read something in the last 2 days; the nightly runs were not read, or the part `clients` is grey |
| Bugs | a `confirmed` `major` bot issue has been open over 14 days; open bugs grew on each of the last 3 Mondays | the same issue over 7 days; open bugs grew on the last 2 Mondays | the issues were not read |
| Agents | `main` requires a review check; the watcher opened more than 2 issues this week | an issue says an agent is paused; in 7 days an agent failed more than half of 4 or more runs, or a reviewer gave no answer in more than half of 4 or more review comments | `main`'s rules, the issues, an agent's runs or the reviews were not read; `main`'s rules were read only in part |
| Queue | something has waited for you over 7 days | something has waited over 3.5 days | what waits was not read, or not all of it |

## The reviewers

A pull request gets one short review comment for both reviewers, never a comment per
finding. A job without a model writes it and edits it in place on later pushes, so only the
first one sends a notification. A finding both reviewers made is listed once. A finding from
an earlier push that the latest review does not repeat stays in the comment: under "Fixed"
when the lines it points to changed since, or else under "Not repeated by the latest
review". The counts keep it either way. If one reviewer fails, the comment says which gave no
answer; if both fail, it says neither did and that it is not a review. A failed reviewer
leaves no red mark. The posting job refuses a reviewer's text that holds a long random string
found nowhere in the pull request's title, body or files. That refusal, like one of text that
looks like a secret, turns the job red, and so does a failure of the workflow's own steps
(checkout, the prepare script, the cap, GitHub's API). Each findings file is kept as a run
artifact for a day before these checks run, and anyone signed in to GitHub can download a
public repository's artifacts.

The two reviewers work by different methods, so they do not repeat each other's blind spots.
Claude's skill follows Anthropic's
[code-review plugin](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/code-review):
report only what is surely wrong, and check each finding before keeping it. Luna's prompt
follows the review rubric of [OpenAI's Codex](https://github.com/openai/codex). Both sources
are under Apache-2.0; the text here is rewritten for Kitden.

Limits for both reviewers: 12 minutes for the model step and 15 for its job, 5 findings
each, at most 10 reviews a day by default (Kitden's caller sets `AGENTS_REVIEW_DAILY_CAP`, or
20), fork pull requests and bots skipped, and the label `no-agent-review` skips one pull
request. The reviewers only comment: they never approve and never block
([rule 11](../RULES.md)).

On Kitden, `agents-review.yml` calls [review.yml](../.github/workflows/review.yml), and the
Lantern app posts the "Agent review" comment. `agents-check.yml` calls
[check.yml](../.github/workflows/check.yml).

Kitden's `list-check.yml` calls [list-check.yml](../.github/workflows/list-check.yml) when a pull
request changes `docs/clients.md`, forks too. It is a script, not an agent:
[list_sources.py](../scripts/list_sources.py) reads the doc page of each row the pull request adds
or changes, and warns when an exact word of the row is not on its page. It holds no secret and
only reads; nothing from the pull request runs. A warning never turns the check red.

## The client watcher

Once a day a job reads the release notes and docs of Claude Code, Codex and Cursor and asks a
model whether anything touches what Kitden shows. It opens an issue in Kitden for a sure
break or wrong data (two a week at most) and one summary issue in the first run of the week,
normally Monday. Once a week the summary also says which doc pages of Kitden's list are not in the Agent Docs manifest. It keeps its memory on the `watch` branch. The design is in [watcher-design.md](watcher-design.md).
To run, it needs the `watch` branch and Lantern (the review app) with Issues write on Kitden.
It also needs the secrets `ANTHROPIC_API_KEY` and `AGENTS_APP_PRIVATE_KEY` in kitden-sdlc (`OPENAI_API_KEY` too, to run the eval on Luna or Terra).
Before it is switched on, the `eval` job (run by hand) measures the model on [the watch tasks](../evals/watch/README.md).
The eval needs `AGENTS_ENABLED` only. The daily jobs also need the variable `WATCH_LIVE` set to `true`, which the owner sets after seeing the eval table.
`WATCH_LIVE` is set: the daily run is on; the eval still runs by hand.
The variable `WATCH_FEED` (`off`, `shadow` or `live`, [owner.md](owner.md#the-switches)) decides whether the watcher reads Agent Docs' feed of new doc pages, and whether their pieces reach the model; only the fetch step, which has no secret, gets it.
Optional: with the secrets `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` and the variable `LANGFUSE_HOST` (the region's address), the eval sends each model call (time, tokens) and its scores to [Langfuse](https://langfuse.com) as one experiment, and the daily run sends each piece as one trace, in one session a run ([where to look](watcher-design.md)). Without them it is off.

An issue is short and in plain words, in the bots' [one look](#one-look). GitHub shows
Lantern as its author and the label `automated` says a bot opened it, so the body says neither;
the run log names the model. The badges give the client and its version, the risk and whether
the watcher is sure; one line says what the Kitden user gets. Then three parts: Problem (what
changed and why it matters for Kitden), Fix (the model's words: the file and the change, then
the files) and Checklist. The checklist depends only on the type and follows Kitden's
CONTRIBUTING.md: a sandbox home for tests; preview, Apply with a backup, verify and Undo for a
change to client settings; the row in `docs/clients.md` and its date; `ROADMAP.md`,
`docs/guide.md` and `PRIVACY.md` when they apply. The "Important" box says what to do: put
`confirmed` on it if it is right (it stays open until it is fixed), or close it with
`false-alarm`. Add `good first issue` or `help wanted` only after `confirmed`, so no
contributor works on a false alarm. Only a sure major break or wrong data gets an issue of its
own at once, two a week at most; the rest waits for Monday's summary. The summary lists its
items the same way in short and one checklist at the end. With several items a table on top
holds each one's badges, so the items under it do not repeat them; words of a row that the note mentions but the model found nothing for go into one line at the end.

| Label | Meaning |
|---|---|
| `automated` | Opened by an automated check; a maintainer confirms it before work starts |
| `client-change` | Opened by the watcher: a client changed |
| `release` | Opened by the release watch |
| `desk` | The owner's desk |
| `ci-failure` | Opened by the desk: a nightly test job is red |
| `claude-code`, `codex`, `cursor` | Which client |
| `breaks` | A Kitden action stops working |
| `wrong-data` | Kitden shows one thing while the client has another |
| `unknown` | Kitden cannot read the new value and says so |
| `outdated` | Kitden stays right; the list or a comment is out of date |
| `kitden-gap` | The client added something Kitden does not show yet |
| `major`, `medium`, `minor` | What a user who trusts Kitden ends up doing: a wrong action, extra steps, or nothing else ([watch-effects.md](watch-effects.md)) |
| `unsure` | The watcher is not sure Kitden is touched |
| `summary` | The weekly summary |
| `confirmed` | Set by the owner: the bot was right; the issue stays open until fixed |
| `false-alarm` | Set by the owner on closing: the bot was wrong |

The watcher knows its open issues by the label `client-change` and its own authorship. Remove
that label, or close the issue, and it may report the same finding again.

When more than half of its last 10 issues with a verdict are `false-alarm`, the watcher opens
one issue, "The client watcher is paused", with the labels `automated` and `desk`, and opens
nothing else while that issue is open. What it finds in that time waits for its first summary
after the pause. The owner lifts the pause by closing that issue as it is, not renamed and
with `automated` still on it: the watcher finds it by its author, that label and its title.
The count starts again from the issues opened after that.

## The release flow

Ready: set up in Kitden; the first release with it is still to come. The owner reviews
one pull request per release; everything after the merge runs on its own. Three reusable
workflows live here, and Kitden calls them. The design is
[2026-11-12-release-flow-design.md](superpowers/specs/2026-11-12-release-flow-design.md).

- [release-prep.yml](../.github/workflows/release-prep.yml): the owner runs it by hand,
  usually from the "Time for a release?" issue. A job without a model gathers the log, the
  merged pull requests and the diff stat since the last tag. Claude reads them with read-only
  tools and writes the release notes, the README changes, the policy edits and its findings
  into one folder, using the `release-notes` and `readme-kitden` skills and
  [platform-rules.md](platform-rules.md). Jobs without a model then check and set the version
  and run Kitden's docs tests and the release check on the files (`check`). When that finds
  problems, Claude gets one pass (10 minutes, 15 turns) to fix them (`fix`), and a script keeps
  the version and the scene list as they were. The README pictures are recorded on macOS, every
  scene, beside these jobs (`record`). `final-check` runs the checks again with the pictures in,
  and `open-pr` opens the pull request `Kitden X.Y.Z` as the release app, with the policy edits
  in a commit of their own. The pull request is a draft when a problem or a failed picture is
  left; its body lists them first. Both agent jobs start with Harden-Runner. The files each
  pass writes, and the lists of problems that quote them, are kept as run artifacts for a day.
  Before anything is committed or posted, a script refuses the agent's files and the body's
  text when they look like a secret or hold a long random string that is not in Kitden,
  `context.json` or, after a fix pass, the first list of problems. A refusal says why in the
  job's log and shows no part of the string, nor the name of a file the agent was not allowed
  to write.
- Merging that pull request tags the version: Kitden's `release.yml` does it as the release
  app. The tag builds the package, publishes it to PyPI and makes the GitHub release, then
  calls publish.
- [publish.yml](../.github/workflows/publish.yml): no model. In the `release` environment, one
  job moves Kitden's `release` branch to the tag and another opens the formula pull request in
  the Homebrew tap. A third publishes `server.json` to the MCP Registry with GitHub's OIDC
  token and no secret. The last job writes a table of every store's version to the job summary.
  The Claude directory and Kitden's marketplaces read the `release` branch. It has no run of
  its own: its jobs show inside the tag's Checks and release run as `stores / registry`,
  `stores / release-branch`, `stores / homebrew` and `stores / summary`.
- [release-watch.yml](../.github/workflows/release-watch.yml): once a day, no model. Lantern
  opens or updates "Time for a release?" while merged changes to `src/`, `plugins/` or
  `install.*` wait and the last tag is 7 days old (sooner when one is labelled `bug`). It
  opens "Release vX.Y.Z is not everywhere" while a store is behind or different; Homebrew
  counts only after 48 hours, because its bottles take time. An issue closes itself when it
  no longer holds. It knows its issues by author, the label `automated` and title, so it never
  touches one a person opened; remove `automated` from one and it may open a new issue. Both
  carry the labels `automated` and `release` and have the bots' [one look](#one-look): the
  badges (how old the last release is and how many changes wait, or each store with a check or
  a cross), one line, the list or Problem and Fix, a box that says what to do, and in the small
  print that release-watch opened it and no model wrote it.

Identities: three GitHub Apps, each with its own name and icon, so nobody mistakes one
for another. Lantern (a lantern on deep teal) comments and opens issues. Kitden Beacon (a
lighthouse on night blue, `kitden-beacon`) is the release app. Kitden Kettle (a brew kettle
on cellar red, `kitden-kettle`) bumps the Homebrew formula. The icons are in
[images/apps](images/apps/).

The release app, Beacon, is apart from Lantern. It can write contents
and pull requests in Kitden and in the tap, and workflows in Kitden (GitHub refuses an app's
tag or branch move whose commits change `.github/workflows` otherwise). Its private key is
stored only in Kitden, as the secret `RELEASE_APP_PRIVATE_KEY` of the environment `release`,
and its client id is the variable `RELEASE_APP_CLIENT_ID`. Only the jobs that tag, move the
branch, open the release pull request and open the Homebrew pull request name that
environment. No job that runs a model holds the release key: the agent's files are only data
to the job that commits them. Lantern's key lives in kitden-sdlc for the watcher, so Lantern
gets no write access to code. The tap has its own app, Kettle (`kitden-kettle`; contents
and pull requests write, on the tap only), whose key `TAP_APP_PRIVATE_KEY` is the only app key
stored in the tap: its daily autobump runs `brew bump`, code from outside the tap, so it must
never hold the release key. The tap's auto-pull accepts bump pull requests from the release
app's bot (`RELEASE_APP_BOT`), the tap app's bot (`TAP_APP_BOT`) and `github-actions[bot]`.
The owner's one-time setup of the app, environments and rules is in
[release-setup.md](release-setup.md).

## The keys

| Key | Stored in | Used by | Money cap |
|---|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Kitden | `claude` reviewer, release prep | the Max plan |
| `OPENAI_API_KEY` | Kitden | `luna` reviewer | $5 a month |
| `OPENAI_API_KEY` | kitden-sdlc | the watch eval on an OpenAI model | not set |
| `ANTHROPIC_API_KEY` | kitden-sdlc | client watcher, the watch eval | not set |

Until the owner makes the second OpenAI key, the kitden-sdlc one may be the same as Kitden's.

## What went wrong

The first versions broke in several ways: [LOG.md](../LOG.md). The design is in
[design.md](design.md) and the plan in [plan.md](plan.md); the watcher's plan is in
[watcher-plan.md](watcher-plan.md) and the release flow's in
[2026-11-12-release-flow.md](superpowers/plans/2026-11-12-release-flow.md).
