# kitden-agents

A solo maintainer wants a second pair of eyes on every change, but not a bigger product and
not a bot that can leak a secret. These are the AI reviewers that look at pull requests of
[Kitden](https://github.com/KonstantinStarovoytov/kitden), and the rules that keep them safe.

Status: the reviewers are built and tested on a laptop. They go live when the repository and
the secrets are set up. There are no live numbers yet; [numbers.md](numbers.md) will fill in.

## The agents

| Agent | Runs when | Model | May do | Limits |
|---|---|---|---|---|
| `claude` reviewer | a pull request opens or changes | Claude Sonnet or Opus (picked by [the review tasks](evals/README.md)), on a Max subscription | read the checkout, write findings, post comments | see below |
| `luna` reviewer | the same | GPT-6 Luna, on a project API key with a $5 monthly budget | read in a sandbox with no network, post comments | see below |
| workflow check | a pull request changes `.github/workflows/` | none | run zizmor, actionlint and the rule checker | read only |
| weekly numbers | every Monday | none | count reviews, commit `numbers.md` | no model, no pull request code |

Limits for both reviewers: 15 minutes, 5 findings per push, 10 reviews a day, fork pull
requests and bots skipped, the `AGENTS_ENABLED` variable switches everything off, and the label
`no-agent-review` skips one pull request. A reviewer only comments: it never approves and
never blocks ([merge policy](MERGE_POLICY.md)).

## The rules

Every workflow that runs an agent must follow [RULES.md](RULES.md). A script checks them.

1. No job holds untrusted text, a secret and write permission together.
2. `pull_request` only; skip forks, bots and when the switch is off.
3. `permissions: {}` at the top; each job asks for the least.
4. Every action is pinned to a full SHA.
5. Every agent job has a timeout, a turn limit and one run per pull request. Luna has no turn
   limit, only the 15 minutes.
6. Tools are allowed by exact name: no Bash, web or MCP. Claude reads only the checkout. Luna
   can run shell commands, but only in a read-only sandbox without network, and it can read more
   than the checkout.
7. Secrets arrive as named inputs and are never printed; the two keys never share a job.
8. Every comment starts with one line saying it is automated and which model wrote it.

## What went wrong

Building this broke the first versions in several ways. [LOG.md](LOG.md) tells what failed and
what changed. The design is in [docs/design.md](docs/design.md) and the plan in [docs/plan.md](docs/plan.md).

## Copy this

Put these two files in your repository's `.github/workflows/`. They are the ones Kitden uses;
change the model, and the `uses` commits to the one you trust.

`agents-review.yml`

```yaml
name: Agent reviews

on:
  pull_request:
    branches: [main] # judged by main's PRINCIPLES.md and AGENTS.md
    types: [opened, synchronize, reopened, ready_for_review]

permissions: {}

concurrency:
  group: agents-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  claude:
    # Only with the switch on, only for branches in this repository, never for bots,
    # drafts, or pull requests labelled no-agent-review.
    if: >-
      vars.AGENTS_ENABLED == 'true'
      && github.event.pull_request.head.repo.full_name == github.repository
      && !endsWith(github.actor, '[bot]')
      && !github.event.pull_request.draft
      && !contains(github.event.pull_request.labels.*.name, 'no-agent-review')
    uses: KonstantinStarovoytov/kitden-agents/.github/workflows/review-claude.yml@ea71575bb84738473a3de6908d2d3563623138ea
    permissions:
      contents: read # the reviewer reads the code
      pull-requests: write # it posts comments
      actions: read # it counts today's runs
    with:
      model: claude-sonnet-5-5
    secrets:
      claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}

  luna:
    # Same conditions as the claude job above.
    if: >-
      vars.AGENTS_ENABLED == 'true'
      && github.event.pull_request.head.repo.full_name == github.repository
      && !endsWith(github.actor, '[bot]')
      && !github.event.pull_request.draft
      && !contains(github.event.pull_request.labels.*.name, 'no-agent-review')
    uses: KonstantinStarovoytov/kitden-agents/.github/workflows/review-luna.yml@ea71575bb84738473a3de6908d2d3563623138ea
    permissions:
      contents: read # the reviewer reads the code
      pull-requests: write # it posts comments
      actions: read # it counts today's runs
    secrets:
      openai_api_key: ${{ secrets.OPENAI_API_KEY }}
```

`agents-check.yml`

```yaml
name: Check agent workflows

on:
  pull_request:
    paths: [".github/workflows/**"]

permissions: {}

concurrency:
  group: agents-check-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  check:
    uses: KonstantinStarovoytov/kitden-agents/.github/workflows/check.yml@beec5f385050df81071b6ef77c95df3da40af56a
    permissions:
      contents: read # check out the code
```

Then, once:

1. Create the repository.
2. Run `claude setup-token` and save the result as the secret `CLAUDE_CODE_OAUTH_TOKEN`.
3. Make an OpenAI project key with a monthly budget; save it as `OPENAI_API_KEY`.
4. Set the variable `AGENTS_ENABLED` to `true`.
