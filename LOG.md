# What went wrong

Problems found while building the reviewers, and what changed because of each.

## 2026-11-09

- **A pull request could plant a `.review/` link.** In the first Claude workflow, the link could
  overwrite the reviewer's skill or forge its findings. Now the folder is wiped first.
  Kept by: `tests/test_workflows.py::test_the_review_folder_is_wiped_before_anything_is_written_to_it`
  (`prepare_review.sh` must remove `.review` and make it new before it writes anything).
- **Bare `Read` reached too much.** The model could open `.git/config` (it holds the job
  token) and maybe `/proc`. Now reads stay inside the checkout, `.git`, home dotfiles and
  `/proc` are denied, and the poster refuses any text that looks like a token.
  Kept by: rule 6, `tests/test_run.py::test_claude_runs_with_the_workflows_tools` (review.yml
  and the evals must use the same tool lists, so a denial cannot be dropped from one alone)
  and `tests/test_post_findings.py::test_secret_like_text_is_refused` for the token check.
- **The first secret filter was too eager.** It refused honest findings about Kitden's own
  token-redaction code. It now matches only real-looking tokens.
  Kept by: `tests/test_post_findings.py::test_ordinary_text_is_not_taken_for_a_secret`.

## 2026-11-10

- Renamed kitden-agents to kitden-sdlc before the first push.
  Kept by: nothing to keep, a one-time rename.
- **The plan's Codex setting was unsafe.** `safety-strategy: read-only` would let the model
  read the OpenAI key from memory, by the action's own docs. Now the default drop-sudo is used,
  with a read-only sandbox and no network.
  Kept by: `tests/test_workflows.py::test_no_codex_step_names_a_safety_strategy_but_drop_sudo`.
- **Codex would obey the pull request's own `AGENTS.md` and `.agents/`.** Those files are now
  deleted before Codex runs, and project docs are capped at 0 bytes.
  Kept by: `tests/test_workflows.py::test_codex_never_sees_the_pull_requests_agent_files_or_project_docs`;
  the evals' own copy of the deletion is covered by
  `tests/test_run.py::test_luna_does_not_see_the_changes_agent_files`.
- **A pull request could switch off zizmor or actionlint** with its own config files. Both now
  use only this repository's config.
  Kept by: `tests/test_workflows.py::test_a_pull_request_cannot_switch_off_zizmor_or_actionlint`:
  the "zizmor" and "actionlint" steps of check.yml, which checks a caller's pull request,
  read only our config files and pass `--no-ignores`; checks.yml, which checks this
  repository, runs zizmor with `--no-config`.
- **actionlint does not know GitHub's `job.workflow_*` contexts yet.** A narrow ignore sits in
  our own config.
  Kept by: the ignore itself, in `config/actionlint.yaml`; the "actionlint" step goes red
  without it. Remove it when actionlint knows the contexts.
- **Four review tasks needed changes.** Two were unfair and were replaced: one
  "bug" was harmless because Kitden's tests sandbox `HOME`; the other could not be seen from
  its diff. A failed
  run no longer looks like a clean pass.
  Kept by: `tests/test_score.py::test_a_failed_run_is_not_found_and_marked_failed` for the
  failed run; replacing the two tasks was a one-time change.
- **The plan named a script `numbers.py`,** which shadows Python's own `numbers` module. It is
  `count_reviews.py`.
  Kept by: nothing to keep, a one-time rename.
- **A reviewer that gave no answer looked like a clean pass.** A missing or broken findings
  file ended green and silent, and one over-long text threw away the whole review. Now the
  summary comment says the reviewer gave no usable answer, and long text is cut instead.
  Kept by: `tests/test_post_findings.py::test_no_answer_at_all_says_so_and_is_not_a_review`,
  `tests/test_post_findings.py::test_a_silent_reviewer_is_named` and
  `tests/test_post_findings.py::test_long_summary_and_text_are_cut`.
- **The same finding came back on every push.** When lines moved, the finding got a new key
  and was posted again. Now a finding within 5 lines of one already posted, in the same file,
  is skipped.
  Kept by: `tests/test_post_findings.py::test_a_finding_made_again_is_one_item_by_everyone_who_made_it`.
- **Model text could ping real people.** `@pytest.fixture` in a finding would notify a GitHub
  user named `pytest`. Now an `@` that starts a word gets an invisible joiner after it.
  Kept by: `tests/test_post_findings.py::test_mentions_are_quieted_in_summary_and_text`.
- **Claude would read instruction files the pull request adds.** A `CLAUDE.md` or `.claude`
  folder in a subfolder was loaded as instructions. They are now deleted before Claude runs;
  the root ones come from the base branch.
  Kept by: `tests/test_workflows.py::test_claude_never_reads_a_claude_file_the_pull_request_adds`.
- **The daily cap counted the wrong runs.** Cancelled and skipped runs used up the cap, and
  whether the run doing the counting counted itself was left to chance. Now only runs that did
  work count, the counting run leaves itself out, and a cap of 10 means 10.
  Kept by: `tests/test_workflows.py::test_the_daily_cap_counts_only_runs_that_did_work_and_not_itself`.

## 2026-11-11

- **The checker knew agents only by the two model actions.** The watcher calls the model from
  a script, so a step that gets a model key now makes its job an agent job, held to the rules.
  Kept by: `tests/test_check_agent_workflows.py::test_script_agent_with_write_is_rule_1` and
  `tests/test_check_agent_workflows.py::test_script_agent_without_max_model_calls_is_rule_5`.
- **The first eval run was slow and we could not see why.** With the Langfuse keys set, each
  model call is traced (time, tokens) and an eval run is an experiment with per-task scores.
  Kept by: `tests/test_watch_run.py::test_with_keys_the_run_is_an_experiment_with_scores` and
  `tests/test_watch_trace.py::test_on_with_keys_the_handler_goes_to_every_model_call`.
- **Two runs of the same judge gave different answers.** The eval now runs three times and
  passes only when every run passes; the judge checks each row of the list and trusts only
  changes it can quote from the note.
  Kept by: `tests/test_watch_score.py::test_several_runs_pass_only_when_each_run_passes` (the table
  passes only when every run passes; that the eval runs three times is the default of the watch
  workflow's `runs` input, which no test reads),
  `tests/test_watch_judge.py::test_a_change_whose_quote_is_not_in_the_piece_is_dropped` and
  `tests/test_watch_judge.py::test_the_model_checks_rows_by_id_and_only_touched_ones_become_changes`.

## 2026-11-12

- **A valid finding vanished on the next push.** On Kitden pull request 70 the second push
  fixed only a type error, the new review did not repeat the ROADMAP.md finding, and the
  comment was overwritten with "No problems found". The comment now keeps its findings in a
  hidden line: one not repeated stays, marked fixed only when its lines changed, and the
  counts keep it.
  Kept by: `tests/test_post_findings.py::test_a_finding_the_next_review_does_not_repeat_stays`.
- **Luna failed on the ubuntu26 image.** The Codex action's drop-sudo step could not restrict
  the D-Bus socket there (openai/codex-action#188). The `luna` job runs on `ubuntu-24.04`
  until that is fixed; drop-sudo stays.
  Kept by: `runs-on: ubuntu-24.04` of the `luna` job in review.yml, and its comment. No test
  checks it yet.

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
  Kept by: `tests/test_release_prep_workflow.py::test_after_a_fix_pass_the_first_problems_are_given_text_too`,
  `tests/test_workflows.py::test_every_model_job_in_release_prep_starts_with_the_same_hosts_step`
  and `tests/test_workflows.py::test_model_output_is_kept_for_one_day`.
- **A refusal could show the agent's text in the public log, or nothing at all.** A file in
  out/ with a name that is not allowed was refused by its name, which the agent chose. A
  refused pull request body went to the captured output, so the step failed with no reason.
  The lists of problems, which quote the agent's files, were kept as long as the repository's
  default. Now a refusal counts what it refused and goes to the log on stderr, and the two
  verdicts are kept for a day.
  Kept by: `tests/test_release_apply.py::test_a_name_that_is_not_allowed_is_counted_and_never_shown`,
  `tests/test_release_prep_workflow.py::test_a_refused_body_fails_the_step_and_its_reason_reaches_the_log`
  and `tests/test_workflows.py::test_release_prep_keeps_only_the_models_text_for_one_day`.
