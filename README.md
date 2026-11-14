<p align="center">
  <a href="https://konstantinstarovoytov.github.io/kitden-sdlc/map/"><img src="docs/images/logo-animated.svg" width="96" alt="kitden-sdlc: Kitden's house cut by a dashed line, an outline on the reading side and solid on the writing side. Opens the live map."></a>
</p>

<h1 align="center">kitden-sdlc</h1>

<p align="center">
  AI reviewers, a client watcher and a release flow for
  <a href="https://github.com/KonstantinStarovoytov/kitden">Kitden</a>.<br>
  The job that runs a model can never write.
</p>

<p align="center">
  <a href="https://konstantinstarovoytov.github.io/kitden-sdlc/map/"><img src="https://img.shields.io/badge/Open_the_live_map-C85835?style=for-the-badge" alt="Open the live map"></a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License: Apache-2.0"></a>
  <a href="https://github.com/KonstantinStarovoytov/kitden-sdlc/actions/workflows/checks.yml"><img src="https://github.com/KonstantinStarovoytov/kitden-sdlc/actions/workflows/checks.yml/badge.svg" alt="Tests and checks"></a>
</p>

## What it does

- **Reviews every pull request.** Claude and Luna read it; you get one comment. It never blocks.
- **Watches the clients every day.** When Claude Code, Codex or Cursor changes something Kitden reads, you get an issue.
- **Ships releases.** You press one button and merge one pull request. PyPI, GitHub, the MCP Registry and Homebrew follow.

The [live map](https://konstantinstarovoytov.github.io/kitden-sdlc/map/) shows every workflow, what starts it, its jobs and their steps.
The three pictures below are its three stories. A column is a place; an arrow says why the
next thing starts; a dot on a job means a model runs in it.

### A pull request

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/map-pull-request-dark.png">
  <img src="docs/images/map-pull-request-light.png" width="820" alt="You open a pull request in Kitden. Always: release.yml runs the checks. To main: agents-review.yml uses review.yml, where Claude and Luna read the change and Lantern posts one review comment that never blocks. If a workflow changed: agents-check.yml uses check.yml. If the page changed: scenes.yml records the README pictures.">
</picture>

### A release

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/map-release-dark.png">
  <img src="docs/images/map-release-light.png" width="820" alt="You press Run workflow: release-prep.yml in Kitden uses release-prep.yml in kitden-sdlc, where Claude drafts and scripts check, and Beacon opens the pull request Kitden X.Y.Z. You read it and merge; release.yml builds and Beacon tags. The tag starts release.yml again: PyPI and the GitHub release, then it uses publish.yml, which moves the release branch, publishes to the MCP Registry and opens a pull request in the tap. There tests.yml, auto-pull.yml and publish.yml run one after another, and brew install kitden works.">
</picture>

### Every day

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/map-every-day-dark.png">
  <img src="docs/images/map-every-day-light.png" width="820" alt="By the clock, in UTC. 05:17: watch.yml reads what Claude Code, Codex and Cursor changed, and Lantern opens an issue in Kitden. 05:17: latest-deps.yml tests Kitden on the newest dependencies. 06:23: release-watch.yml in Kitden uses release-watch.yml in kitden-sdlc, and Lantern opens Time for a release. 06:41: desk.yml updates the Kitden desk issue. 13:10: autobump.yml in the tap opens a pull request for a new version.">
</picture>

## The bots

Everything is posted by one of three GitHub Apps, so you see who did what.

| | Bot | What it does |
|---|---|---|
| <img src="docs/images/apps/lantern.svg" width="40" alt="Lantern"> | **Lantern** | review comments and issues |
| <img src="docs/images/apps/beacon.svg" width="40" alt="Kitden Beacon"> | **Beacon** | the release pull request, the tag, the Homebrew pull request |
| <img src="docs/images/apps/kettle.svg" width="40" alt="Kitden Kettle"> | **Kettle** | the daily Homebrew update |

## The rule

No job holds untrusted text, a secret and write access together. So the work is split in
three: one job reads, one runs the model with no way to write, one writes with no model.

All eleven rules, checked by a script on every change: [RULES.md](RULES.md).

## It checks itself

The agents are measured, and what they get wrong becomes the next test.

- **Your verdict is the data.** You mark a watcher issue `confirmed` or `false-alarm`.
- **Verdicts become tests.** About once a month they are turned into new eval tasks, as a pull request: [evals/watch](evals/watch/README.md).
- **No change without a score.** A change to a prompt, a skill or a model comes with its eval table, before and after.
- **A noisy agent pauses itself.** When more than half of its last 10 verdicts are false alarms, it stops and asks you.

The desk shows the same health every day in one issue: [docs/agents.md](docs/agents.md#the-desk).

## What you do

Read the comments, answer the issues, press **Run workflow** to release. Every action and
the three switches that turn it all off: [docs/owner.md](docs/owner.md).

## Use it yourself

Copy the callers in [examples/](examples/) into your `.github/workflows/`, rewrite the
Kitden-specific skills and prompts, then do the one-time setup:
[docs/setup.md](docs/setup.md) and [docs/release-setup.md](docs/release-setup.md).

## More

- [docs/agents.md](docs/agents.md): every agent and workflow, the watcher's labels, the release flow
- [docs/owner.md](docs/owner.md): everything you do, one table; the switches
- [desk.json](https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/numbers/desk.json) on the `numbers` branch: the desk's data
- [docs/setup.md](docs/setup.md) and [docs/release-setup.md](docs/release-setup.md): the one-time setup
- [docs/decisions.md](docs/decisions.md): every standing choice, why, and when to look again
- [LOG.md](LOG.md): what went wrong while building, and what changed
- Designs: [reviewers](docs/design.md), [client watcher](docs/watcher-design.md),
  [release flow](docs/superpowers/specs/2026-11-12-release-flow-design.md)
- [MERGE_POLICY.md](MERGE_POLICY.md): what agents may and may not do to a pull request
- Evals: [review tasks](evals/README.md), [watch tasks](evals/watch/README.md)
