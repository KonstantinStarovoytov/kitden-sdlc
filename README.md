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
| Client watcher ([watch.yml](.github/workflows/watch.yml)) | Luna reads the release notes of Claude Code, Codex and Cursor; a script opens issues in Kitden | measuring: the eval runs by hand, the daily run is off |
| Weekly numbers ([numbers.yml](.github/workflows/numbers.yml)) | counts the reviews, no model | set up; first run on Monday |
| Release prep ([release-prep.yml](.github/workflows/release-prep.yml)) | Claude drafts the notes, README and policy edits with read-only tools; a job without a model opens the release pull request | being built |
| Publish ([publish.yml](.github/workflows/publish.yml)) | no model; in the `release` environment it moves the `release` branch and opens the Homebrew pull request, and it publishes to the MCP Registry | being built |
| Release watch ([release-watch.yml](.github/workflows/release-watch.yml)) | daily, no model: an issue when a release is due or a store is behind | being built |

Every agent, its model and its limits: [docs/agents.md](docs/agents.md).

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

Put [agents-review.yml](examples/agents-review.yml) and [agents-check.yml](examples/agents-check.yml)
in your `.github/workflows/`. For the release flow, add [release.yml](examples/release.yml),
[release-watch.yml](examples/release-watch.yml) and [release-prep.yml](examples/release-prep.yml).
They are Kitden's own files; the `uses` pins are bumped at each release. The one-time
GitHub App, environment and rule setup is in [release-setup.md](docs/release-setup.md).

- `kitden-sdlc`, or your copy of it, must be public: another repository's `uses` cannot
  reach a private one.
- The review skill, the Luna prompt and `count_reviews.py` (`REPO`, `MAINTAINER`) are about
  Kitden, and so are the release skills, `release_check.py` and
  [platform-rules.md](docs/platform-rules.md). Rewrite them for your project.
- The model and the `uses` pins in the caller files are Kitden's choices. Change them to yours.

Then, once:

1. Create the repository `kitden-sdlc` (or your copy) on GitHub.
2. Run `claude setup-token` and save the result as the secret `CLAUDE_CODE_OAUTH_TOKEN`.
3. Make an OpenAI project key with a monthly budget; save it as `OPENAI_API_KEY`.
4. Set the variable `AGENTS_ENABLED` to `true`; it switches review, the watcher, release prep and
   release watch. For the client watcher, set `WATCH_LIVE` to `true` only after the eval has passed.
5. Create a GitHub App, install it on the repository, and save its client id as the variable
   `AGENTS_APP_CLIENT_ID` and its private key as the secret `AGENTS_APP_PRIVATE_KEY`. Kitden's app
   is called Lantern. For the review it is optional: it posts the comment under the bot's own
   name (write access to pull requests), and without it the comment comes from `github-actions`.
   Release watch and the client watcher need it, with write access to issues. With your own
   app, put its bot name into `BOTS` in `post_findings.py`.
6. For the release flow, create a second GitHub App, the release app, with contents and pull
   requests write, on your project and its Homebrew tap. Save its client id as the variable
   `RELEASE_APP_CLIENT_ID`. Create the environment `release`, limited to `main` and `v*` tags,
   and save the app's private key there as the secret `RELEASE_APP_PRIVATE_KEY`. Do not reuse
   the review app: its key is stored in kitden-sdlc. `release.yml` publishes to PyPI through a
   Trusted Publisher and the environment `pypi`; limit `pypi` to `v*` tags. Its publish step
   expects a Homebrew tap: Kitden's is `homebrew-tap`, named in `publish.yml`.

## More

- [docs/agents.md](docs/agents.md): every agent and workflow, the watcher's labels, the release flow
- [LOG.md](LOG.md): what went wrong while building, and what changed
- Designs: [reviewers](docs/design.md), [client watcher](docs/watcher-design.md),
  [release flow](docs/superpowers/specs/2026-11-12-release-flow-design.md)
- [MERGE_POLICY.md](MERGE_POLICY.md): the reviewers only comment, never approve or block
- Evals: [review tasks](evals/README.md), [watch tasks](evals/watch/README.md)
