# kitden-sdlc

A solo maintainer wants a second pair of eyes on every change, but not a bigger product and
not a bot that can leak a secret. These are the AI reviewers that look at pull requests of
[Kitden](https://github.com/KonstantinStarovoytov/kitden), and the rules that keep them safe.

Status: the reviewers are built and tested on a laptop. They go live when the repository and
the secrets are set up. There are no live numbers yet; [numbers.md](https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/numbers/numbers.md) will fill in.

## The agents

| Agent | Runs when | Model | May do | Limits |
|---|---|---|---|---|
| `claude` reviewer | a pull request opens or changes | Claude Sonnet or Opus, picked by [the review tasks](evals/README.md); meant to run on a Max subscription, once set up | read the checkout, write findings | see below |
| `luna` reviewer | the same | GPT-6 Luna; meant to run on a project API key with a $5 monthly budget, once set up | read in a sandbox with no network, answer with findings | see below |
| workflow check | a pull request changes `.github/workflows/` | none | run zizmor, actionlint and the rule checker | read only |
| weekly numbers | every Monday | none | count reviews, commit `numbers.md` and `numbers.json` to the `numbers` branch | no model, no pull request code |

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
approve and never block ([merge policy](MERGE_POLICY.md)).

## The rules

Every workflow that runs an agent must follow [RULES.md](RULES.md). A script checks them.

1. No job holds untrusted text, a secret and write permission together.
2. `pull_request` only; skip forks, bots and when the switch is off.
3. `permissions: {}` at the top; each job asks for the least.
4. Every action is pinned to a full SHA. The caller may use this repository's workflows at
   `main`, which is protected.
5. Every agent job has a timeout, a turn limit and one run per pull request. Luna has no turn
   limit, only the 15 minutes.
6. Tools are allowed by exact name: no Bash, web or MCP. Claude reads only the checkout. Luna
   can run shell commands, but only in a read-only sandbox without network, and it can read more
   than the checkout.
7. Secrets arrive as named inputs and are never printed; the two keys never share a job.
8. Every comment starts with the title "Agent review", so it is clear an agent wrote it.

## The client watcher

Once a day a job reads the release notes and docs of Claude Code, Codex and Cursor and asks a
model whether anything touches what Kitden shows. It opens an issue in Kitden for a sure
break (two a week at most) and one summary issue on Mondays. It keeps its memory on the `watch`
branch. The design is in [docs/watcher-design.md](docs/watcher-design.md).

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

## What went wrong

The first versions broke in several ways: [LOG.md](LOG.md). The design is in
[docs/design.md](docs/design.md) and the plan in [docs/plan.md](docs/plan.md).

## Copy this

Put [agents-review.yml](examples/agents-review.yml) and [agents-check.yml](examples/agents-check.yml)
in your `.github/workflows/`. They are Kitden's own files; the `uses` pins are bumped at each
release.

- `kitden-sdlc`, or your copy of it, must be public: another repository's `uses` cannot
  reach a private one.
- The review skill, the Luna prompt and `count_reviews.py` (`REPO`, `MAINTAINER`) are about
  Kitden. Rewrite them for your project.
- The model and the `uses` pins in the caller files are Kitden's choices. Change them to yours.

Then, once:

1. Create the repository `kitden-sdlc` (or your copy) on GitHub.
2. Run `claude setup-token` and save the result as the secret `CLAUDE_CODE_OAUTH_TOKEN`.
3. Make an OpenAI project key with a monthly budget; save it as `OPENAI_API_KEY`.
4. Set the variable `AGENTS_ENABLED` to `true`.
5. Optional: to post the comment under a bot's own name, create a GitHub App with write
   access to pull requests, install it on the repository, and save its client id as the variable
   `AGENTS_APP_CLIENT_ID` and its private key as the secret `AGENTS_APP_PRIVATE_KEY`. Kitden's app
   is called Lantern. Without an app the comment comes from `github-actions`. With your own
   app, put its bot name into `BOTS` in `post_findings.py`.
