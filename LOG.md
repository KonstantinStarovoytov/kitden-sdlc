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

## 2026-11-10

- Renamed kitden-agents to kitden-sdlc before the first push.
- **The plan's Codex setting was unsafe.** `safety-strategy: read-only` would let the model
  read the OpenAI key from memory, by the action's own docs. Now the default drop-sudo is used,
  with a read-only sandbox and no network.
- **Codex would obey the pull request's own `AGENTS.md` and `.agents/`.** Those files are now
  deleted before Codex runs, and project docs are capped at 0 bytes.
- **A pull request could switch off zizmor or actionlint** with its own config files. Both now
  use only this repository's config.
- **actionlint does not know GitHub's `job.workflow_*` contexts yet.** A narrow ignore sits in
  our own config.
- **Four review tasks needed changes.** Two were unfair and were replaced: one
  "bug" was harmless because Kitden's tests sandbox `HOME`; the other could not be seen from
  its diff. A failed
  run no longer looks like a clean pass.
- **The plan named a script `numbers.py`,** which shadows Python's own `numbers` module. It is
  `count_reviews.py`.
- **A reviewer that gave no answer looked like a clean pass.** A missing or broken findings
  file ended green and silent, and one over-long text threw away the whole review. Now the
  summary comment says the reviewer gave no usable answer, and long text is cut instead.
- **The same finding came back on every push.** When lines moved, the finding got a new key
  and was posted again. Now a finding within 5 lines of one already posted, in the same file
  and of the same kind, is skipped.
- **Model text could ping real people.** `@pytest.fixture` in a finding would notify a GitHub
  user named `pytest`. Now an `@` that starts a word gets an invisible joiner after it.
- **Claude would read instruction files the pull request adds.** A `CLAUDE.md` or `.claude`
  folder in a subfolder was loaded as instructions. They are now deleted before Claude runs;
  the root ones come from the base branch.
- **The daily cap counted the wrong runs.** Cancelled and skipped runs used up the cap, and
  whether the run doing the counting counted itself was left to chance. Now only runs that did
  work count, the counting run leaves itself out, and a cap of 10 means 10.

## 2026-11-11

- **The checker knew agents only by the two model actions.** The watcher calls the model from
  a script, so a step that gets a model key now makes its job an agent job, held to the rules.
- **The first eval run was slow and we could not see why.** With the Langfuse keys set, each
  model call is traced (time, tokens) and an eval run is an experiment with per-task scores.
- **Two runs of the same judge gave different answers.** The eval now runs three times and
  passes only when every run passes; the judge checks each row of the list and trusts only
  changes it can quote from the note.

## 2026-11-12

- **A valid finding vanished on the next push.** On Kitden pull request 70 the second push
  fixed only a type error, the new review did not repeat the ROADMAP.md finding, and the
  comment was overwritten with "No problems found". The comment now keeps its findings in a
  hidden line: one not repeated stays, marked fixed only when its lines changed, and the
  counts keep it.
- **Luna failed on the ubuntu26 image.** The Codex action's drop-sudo step could not restrict
  the D-Bus socket there (openai/codex-action#188). The `luna` job runs on `ubuntu-24.04`
  until that is fixed; drop-sudo stays.

## 2026-11-13

- **A failed reviewer left a red mark on the pull request.** One reviewer's error turned its
  job red even though the other review was fine. Now a failed reviewer no longer fails its job:
  the comment says which one gave no answer, or that neither did. The model step's timeout is
  under the job's, so a hang fails only the step. A refusal to post secret-like text still
  turns the job red, and so does a failure of the workflow's own steps.
  Kept by: `tests/test_workflows.py::test_a_failed_reviewer_leaves_no_red_mark`.
- **Release prep gained a second model step without the new rules.** The fix pass came from
  main while the safety work was under way. It had no Harden-Runner step, its output was kept
  as long as the repository's default, and the secret check did not know the first list of
  problems the pass was given. Now it starts like the first pass, its output is kept for a
  day, and the fixed files and every part of the body pass both secret checks, against what
  each pass was given.
  Kept by: `tests/test_release_prep_workflow.py::test_after_a_fix_pass_the_first_problems_are_given_text_too`.
