# kitden-sdlc

AI reviewers, a client watcher and a release flow for
[Kitden](https://github.com/KonstantinStarovoytov/kitden), with rules so no agent job holds
untrusted text, a secret and write access at once.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/sdlc-dark.svg">
  <img src="docs/images/sdlc-light.svg" width="720" alt="What kitden-sdlc runs: review (live), the client watcher (measuring) and the release flow (being built). In every lane the model only reads, and a script without a model writes.">
</picture>

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE) [![checks](https://github.com/KonstantinStarovoytov/kitden-sdlc/actions/workflows/checks.yml/badge.svg)](https://github.com/KonstantinStarovoytov/kitden-sdlc/actions/workflows/checks.yml)

| Part | What it does | Status |
|---|---|---|
| Review ([review.yml](.github/workflows/review.yml)) | Claude and Luna read each pull request; the Lantern app posts one "Agent review" comment | live on Kitden |
| Workflow check ([check.yml](.github/workflows/check.yml)) | zizmor, actionlint and the rule checker on every workflow change | live on Kitden |
| Client watcher ([watch.yml](.github/workflows/watch.yml)) | Claude Sonnet 5.5 reads the release notes of Claude Code, Codex and Cursor; a script opens issues in Kitden | measuring: the eval runs by hand, the daily run is off |
| Weekly numbers ([numbers.yml](.github/workflows/numbers.yml)) | counts the reviews, no model | set up; first run on Monday |
| Release prep ([release-prep.yml](.github/workflows/release-prep.yml)) | Claude drafts the notes, README and policy edits with read-only tools; a job without a model opens the release pull request | being built |
| Publish ([publish.yml](.github/workflows/publish.yml)) | no model; in the `release` environment it moves the `release` branch and opens the Homebrew pull request, and it publishes to the MCP Registry | being built |
| Release watch ([release-watch.yml](.github/workflows/release-watch.yml)) | daily, no model: an issue when a release is due or a store is behind | being built |

Every agent, its model and its limits: [docs/agents.md](docs/agents.md).

## How to use it, step by step

Everything below runs in GitHub Actions. Kitden calls these workflows from its own files (the
copies are in [examples/](examples/)). Bots post as GitHub Apps, so you always see who wrote
what: **Lantern** comments and opens issues, **Kitden Beacon** makes releases, **Kitden Kettle**
updates the Homebrew formula. No bot ever writes `@name`, so nobody is mentioned by a bot.

### 1. You open a pull request: the review

- **When:** you open, update or reopen a pull request to `main` in Kitden.
- **You do:** nothing.
- **What happens:** Claude Sonnet 5.5 and GPT-6 Luna read the change on their own. Lantern
  posts one comment, "Agent review", with what they found, and updates the same comment on
  every push. A finding that is fixed stays in the comment, marked fixed.
- **What it does not do:** it never approves or blocks; merging is yours
  ([MERGE_POLICY.md](MERGE_POLICY.md)). At most 10 reviews a day.
- **You get:** the usual GitHub notification for a new comment on your pull request.

### 2. A pull request changes a workflow: the workflow check

- **When:** a pull request in Kitden changes `.github/workflows/`.
- **What happens:** zizmor, actionlint and the rule checker run, no model. A red check means a
  workflow breaks one of the [rules](RULES.md).

### 3. Every day at 05:17 UTC: the client watcher

- **What happens:** it reads the new release notes and docs of Claude Code, Codex and Cursor,
  and Claude Sonnet 5.5 checks each new piece against Kitden's list of client facts. For a sure
  `major` break or wrong data, Lantern opens an issue in Kitden at once (two a week at most).
  Everything else goes into one summary issue on Monday.
- **Each issue** has the labels `automated`, `client-change`, the client, the type and the
  severity, and the same sections: what changed, what it means for Kitden, why, where in
  Kitden, scale, how sure. The words are explained in [docs/watch-effects.md](docs/watch-effects.md).
- **You do:** read it, then close it with `confirmed` (the watcher was right) or `false-alarm`.
  Add `good first issue` or `help wanted` only after `confirmed`.
- **You get:** a notification for each new issue, if you watch Kitden's issues. Most days there
  is none.
- **Off until** you set the variable `WATCH_LIVE` to `true` in kitden-sdlc. To measure it first:
  Actions → "watch" → Run workflow, with `eval` on; the result table is in the run's summary
  and in [evals/watch](evals/watch/README.md).
- **Cost:** about $0.05 a new piece, $2 to $5 a month.

### 4. Every Monday at 06:00 UTC: the weekly numbers

- **What happens:** a script without a model counts the reviews of the week and commits
  `numbers.md` to the `numbers` branch.
- **You get:** nothing; open the branch when you want to see how the reviewers do.

### 5. Every day at 06:23 UTC: the release watch

- **What happens:** a script without a model checks two things and keeps one issue for each.
  - "Time for a release?": opened when merged changes to `src/`, `plugins/` or `install.*`
    wait and the last release is 7 days old, or sooner when one of them is labelled `bug`.
  - "Release vX.Y.Z is not everywhere": opened when a store (PyPI, Homebrew, the MCP
    Registry, the `release` branch) is behind; Homebrew counts only after 48 hours.
- Each issue closes itself when it no longer holds.
- **You get:** a notification when one of them opens.

## How to release Kitden

1. **Start.** Open the "Time for a release?" issue, or any time: in Kitden, Actions → "Release
   prep" → Run workflow. Leave the version empty to let the agent pick the next one, or type
   one, like `0.9.0`.
2. **Wait.** It takes up to about an hour; each step has its own time limit. Claude reads what changed since the last release with read-only
   tools and writes the release notes, the README changes and any policy edits. Scripts check
   them, set the version, record the README pictures, and Kitden Beacon opens one pull request,
   `Kitden X.Y.Z`. You get a notification for it.
3. **Review that pull request.** It is the only thing you check. The policy edits are in a
   commit of their own. You can edit it like any pull request.
4. **Merge it.** From here everything runs on its own:
   - the merge tags `vX.Y.Z`;
   - the tag builds the package, publishes it to PyPI and makes the GitHub release;
   - then the stores: the `release` branch moves to the tag (the Claude directory and Kitden's
     marketplaces read it), Kitden Kettle opens the Homebrew formula pull request, and
     `server.json` goes to the MCP Registry.
5. **Check.** The tag's run has a summary table with every store's version. If a store is still
   behind a day later, the release watch opens "Release vX.Y.Z is not everywhere".

Nothing in the release asks for a key by hand, and no job that runs a model can publish.
The one-time setup is in [docs/release-setup.md](docs/release-setup.md).

## When you get a notification

| What | From | When |
|---|---|---|
| "Agent review" comment | Lantern | each pull request to `main` in Kitden, updated on each push |
| Urgent client-change issue | Lantern | a sure major break or wrong data; two a week at most |
| Weekly client summary | Lantern | Monday, when there was anything that week |
| "Time for a release?" | Lantern | changes wait for 7 days, or a `bug` fix waits |
| Pull request `Kitden X.Y.Z` | Kitden Beacon | after you run release prep |
| "Release vX.Y.Z is not everywhere" | Lantern | a store is behind after a release |
| A red check or a failed run | GitHub Actions | something broke; the run's log says what |

Two switches stop it all: the variable `AGENTS_ENABLED` (review, the watcher, release prep and
the release watch) and `WATCH_LIVE` (the watcher's daily run).

## The rules

Every workflow that runs an agent must follow [RULES.md](RULES.md). A script checks them.

1. No job holds untrusted text, a secret and write permission together. A job in the
   `release` environment never runs a model.
2. `pull_request` only; skip forks, bots and when the switch is off. A scheduled agent runs
   on a schedule or by hand only, and every job checks the switch.
3. `permissions: {}` at the top; each job asks for the least.
4. Every action is pinned to a full SHA. The caller may use this repository's workflows at
   `main`, which is protected.
5. Every agent job has a timeout, a turn limit and one run per pull request. Luna has only
   the 15 minutes. An agent that is a script has `MAX_MODEL_CALLS` and runs one at a time.
6. Tools are allowed by exact name: no Bash, web or MCP. Claude reads only the checkout. Luna
   can run shell commands, but only in a read-only sandbox without network, and it can read
   more than the checkout.
7. Secrets arrive as named inputs and are never printed; the Claude token and the OpenAI key
   never share a job.
8. An agent's comment starts with one line saying it is automated and which model wrote it
   (today the "Agent review" title).

## Copy this

The callers in [examples/](examples/) are Kitden's own workflow files. Copy them into your
`.github/workflows/`, rewrite the Kitden-specific skills and prompts, then do the one-time
setup: [docs/setup.md](docs/setup.md) for review and the watcher,
[docs/release-setup.md](docs/release-setup.md) for the release flow.

## More

- [docs/agents.md](docs/agents.md): every agent and workflow, the watcher's labels, the release flow
- [docs/setup.md](docs/setup.md) and [docs/release-setup.md](docs/release-setup.md): the one-time setup
- [LOG.md](LOG.md): what went wrong while building, and what changed
- Designs: [reviewers](docs/design.md), [client watcher](docs/watcher-design.md),
  [release flow](docs/superpowers/specs/2026-11-12-release-flow-design.md)
- [MERGE_POLICY.md](MERGE_POLICY.md): the reviewers only comment, never approve or block
- Evals: [review tasks](evals/README.md), [watch tasks](evals/watch/README.md)
