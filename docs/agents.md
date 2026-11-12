# The agents and workflows

The details behind the [README](../README.md): what each workflow runs, its model, what it may
do and its limits. Every workflow that runs an agent follows [RULES.md](../RULES.md).

## The agents

| Agent | Runs when | Model | May do | Limits |
|---|---|---|---|---|
| `claude` reviewer | a pull request opens or changes | Claude Sonnet or Opus, picked by [the review tasks](../evals/README.md); runs on a Max subscription | read the checkout, write findings | see below |
| `luna` reviewer | the same | GPT-6 Luna; runs on a project API key with a $5 monthly budget | read in a sandbox with no network, answer with findings | see below |
| workflow check | a pull request changes `.github/workflows/` | none | run zizmor, actionlint and the rule checker | read only |
| weekly numbers | every Monday at 06:00 UTC | none | count reviews, commit `numbers.md` and `numbers.json` to the `numbers` branch | no model, no pull request code |
| client watcher | every day at 05:17 UTC, or by hand | GPT-6 Luna, on the same key as the `luna` reviewer | read client release notes and docs; a job without the model opens issues in Kitden as Lantern and commits the memory to the `watch` branch | 15 minutes per job, 60 model calls, one run at a time, the `AGENTS_ENABLED` and `WATCH_LIVE` switches |
| release prep | the owner runs it by hand in Kitden | Claude, the model Kitden's caller names | read the checkout and the release context, write files to one output folder; jobs without the model set the version, record the README pictures and open the release pull request as the release app | 25 minutes, 40 turns, one run at a time, the `AGENTS_ENABLED` switch; it stops while a release pull request is open |
| release watch | every day in Kitden, or by hand | none | open or update two issues in Kitden as Lantern | no model, writes issues only, one run at a time, the `AGENTS_ENABLED` switch |
| publish | a `vX.Y.Z` tag in Kitden, after PyPI | none | move the `release` branch, publish to the MCP Registry, open the Homebrew pull request, write a summary | no model; each job writes to one place with its own short-lived token |

The weekly numbers have not run yet; the first run is on Monday. Then
[numbers.md](https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/numbers/numbers.md) fills in.

## The reviewers

A pull request gets one short review comment for both reviewers, never a comment per
finding. A job without a model writes it and edits it in place on later pushes, so only the
first one sends a notification. A finding both reviewers made is listed once.

The two reviewers work by different methods, so they do not repeat each other's blind spots.
Claude's skill follows Anthropic's
[code-review plugin](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/code-review):
report only what is surely wrong, and check each finding before keeping it. Luna's prompt
follows the review rubric of [OpenAI's Codex](https://github.com/openai/codex). Both sources
are under Apache-2.0; the text here is rewritten for Kitden.

Limits for both reviewers: 15 minutes, 5 findings each, at most 10 reviews a day, fork pull
requests and bots skipped, the `AGENTS_ENABLED` variable switches everything off, and the
label `no-agent-review` skips one pull request. The reviewers only comment: they never
approve and never block ([merge policy](../MERGE_POLICY.md)).

On Kitden, `agents-review.yml` calls [review.yml](../.github/workflows/review.yml), and the
Lantern app posts the "Agent review" comment. `agents-check.yml` calls
[check.yml](../.github/workflows/check.yml).

## The client watcher

Once a day a job reads the release notes and docs of Claude Code, Codex and Cursor and asks a
model whether anything touches what Kitden shows. It opens an issue in Kitden for a sure
break or wrong data (two a week at most) and one summary issue in the first run of the week,
normally Monday. It keeps its memory on the `watch` branch. The design is in [watcher-design.md](watcher-design.md).
To run, it needs the `watch` branch and Lantern (the review app) with Issues write on Kitden.
It also needs the secrets `OPENAI_API_KEY` and `AGENTS_APP_PRIVATE_KEY` in kitden-sdlc.
Before it is switched on, the `eval` job (run by hand) measures the model on [the watch tasks](../evals/watch/README.md).
The eval needs `AGENTS_ENABLED` only. The daily jobs also need the variable `WATCH_LIVE` set to `true`, which the owner sets after seeing the eval table.
Today the eval runs by hand and `WATCH_LIVE` is not set, so the daily run is off.
Optional: with the secrets `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` and the variable `LANGFUSE_HOST` (the region's address), the eval sends each model call (time, tokens) and its scores to [Langfuse](https://langfuse.com) as one experiment. Without them it is off.

| Label | Meaning |
|---|---|
| `client-change` | Opened by the watcher: a client changed |
| `claude-code`, `codex`, `cursor` | Which client |
| `breaks` | A Kitden action stops working |
| `wrong-data` | Kitden shows something that is not true |
| `minor` | Small; nothing a user would trip over |
| `kitden-gap` | The client added something Kitden does not show yet |
| `unsure` | The watcher is not sure Kitden is touched |
| `summary` | The weekly summary |
| `confirmed`, `false-alarm` | Set by the owner on closing: the watcher was right or wrong |

## The release flow

Being built: the code is merged, and it has not run on a real release yet. The owner reviews
one pull request per release; everything after the merge runs on its own. Three reusable
workflows live here, and Kitden calls them. The design is
[2026-11-12-release-flow-design.md](superpowers/specs/2026-11-12-release-flow-design.md).

- [release-prep.yml](../.github/workflows/release-prep.yml): the owner runs it by hand,
  usually from the "Time for a release?" issue. A job without a model gathers the log, the
  merged pull requests and the diff stat since the last tag. Claude reads them with read-only
  tools and writes the release notes, the README changes, the policy edits and its findings
  into one folder, using the `release-notes` and `readme-kitden` skills and
  [platform-rules.md](platform-rules.md). Jobs without a model then check and set the version,
  record the README pictures on macOS, and open the pull request `Kitden X.Y.Z` as the release
  app, with the policy edits in a commit of their own.
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
  no longer holds.

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

## What went wrong

The first versions broke in several ways: [LOG.md](../LOG.md). The design is in
[design.md](design.md) and the plan in [plan.md](plan.md); the watcher's plan is in
[watcher-plan.md](watcher-plan.md) and the release flow's in
[2026-11-12-release-flow.md](superpowers/plans/2026-11-12-release-flow.md).
