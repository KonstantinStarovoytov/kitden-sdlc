# What went wrong

Problems found while building the reviewers, and what changed because of each.

## 2026-11-09

- **A pull request could plant a `.review/` link.** In the first Claude workflow, the link could
  overwrite the reviewer's skill or forge its findings. Now the folder is wiped first.
- **Bare `Read` reached too much.** The model could open `.git/config` (it holds the job
  token) and maybe `/proc`. Now reads stay inside the checkout, `.git`, home dotfiles and
  `/proc` are denied, and the poster refuses any text that looks like a token.
- **The first secret filter was too eager.** It refused honest findings about Kitden's own
  token-redaction code. It now matches only real-looking tokens.
- **The plan's Codex setting was unsafe.** `safety-strategy: read-only` would let the model
  read the OpenAI key from memory, by the action's own docs. Now the default drop-sudo is used,
  with a read-only sandbox and no network.
- **Codex would obey the pull request's own `AGENTS.md` and `.agents/`.** Those files are now
  deleted before Codex runs, and project docs are capped at 0 bytes.
- **A pull request could switch off zizmor or actionlint** with its own config files. Both now
  use only this repository's config.
- **actionlint does not know GitHub's `job.workflow_*` contexts yet.** A narrow ignore sits in
  our own config.

## 2026-11-10

- **Two of the first 24 review tasks were unfair.** One "bug" was harmless because Kitden's
  tests sandbox `HOME`; the other could not be seen from its diff. Both were replaced. A failed
  run no longer looks like a clean pass.
- **The plan named a script `numbers.py`,** which shadows Python's own `numbers` module. It is
  `count_reviews.py`.
