# Watch texts in Langfuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The forty watch tasks keep no vendor text in git; the eval reads each text from the
Langfuse dataset `watch-eval` or from a folder on the owner's Mac, checked against a SHA-256
kept in the task file.

**Architecture:** A new module `evals/watch_texts.py` owns the text: splitting it off a task,
reading and writing the folder and the dataset, joining it back to a task with the hash
check, and the checks on the text. `watch_run.py` joins the texts before any model call;
`watch_harvest.py` writes new texts to the folder. One commit strips the forty task files.

**Tech Stack:** Python 3.13, uv, pytest, ruff, the Langfuse Python SDK already in the
`watch-io` group.

**Spec:** `docs/superpowers/specs/2026-11-16-watch-texts-design.md`

## Global Constraints

- The hash: `hashlib.sha256(text.encode("utf-8")).hexdigest()`, stored as `piece.text_sha256`.
- A task file never has `piece.text`; every other field stays as it is.
- Folder file: `<folder>/<task id>.json` = `{"id": <id>, "sha256": <hash>, "text": <text>}`,
  written with `json.dumps(..., indent=1, ensure_ascii=False) + "\n"`.
- The dataset: `watch-eval`; item id = task id; `input` = the whole piece with `text`;
  `expected_output` = `expect`; `metadata` = `{"id", "kind", "source"}` (as today).
- No default text source anywhere: `--texts langfuse` or `--texts <folder>`, required.
- A missing text, a hash that differs, or an unreadable source stops the run before any
  model call, naming every task concerned. An error message never holds a key: print the
  exception's type, as `watch_trace.warn` does.
- Before each commit: `uv run pytest -q`, `uv run ruff check .`,
  `uv run python scripts/check_agent_workflows.py .github/workflows` (AGENTS.md). Whoever
  edits a workflow runs the `agentic-actions-auditor` skill.
- Never run `uv cache clean`.
- No over-engineering (the owner): only what a step names; no extra options, classes,
  retries or abstractions. `watch_texts.py` should stay around 120 lines.

## Review Focus

1. A task whose text is missing from the source, or whose text has a different hash: the run
   stops before the first model call and names every such task, not only the first.
2. `--texts langfuse` without `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`, or with Langfuse
   unreachable: exit 1 with one clear line, no traceback, no key; unlike the experiment, this
   failure is not swallowed.
3. `--texts <folder>` that does not exist: a clear error naming the folder, not a traceback.
4. `split` run a second time on stripped files: changes nothing and writes nothing.
5. A new harvested task: its file has no text, its text lands in the folder with the right
   hash, and a later `check` with the folder passes.

---

### Task 1: `evals/watch_texts.py`

**Files:**
- Create: `evals/watch_texts.py`
- Modify: `evals/watch_run.py` (move `DATASET` and `dataset_items` here; `watch_run` imports
  them back, so `from watch_run import dataset_items` keeps working)
- Test: `tests/test_watch_texts.py` (reuse `FakeLangfuse` and `fake_langfuse` by importing them
  from `test_watch_run`)

**Interfaces:**
- Produces:
  - `DATASET = "watch-eval"`
  - `class TextsError(Exception)`: its message names the tasks.
  - `sha(text: str) -> str`
  - `split_task(task: dict) -> tuple[dict, str | None]`: a copy without `piece.text` and with
    `piece.text_sha256`, and the text; a task already split returns itself and `None`.
  - `attach(tasks: list[dict], texts: dict[str, str]) -> list[dict]`: copies with
    `piece.text` put back; raises `TextsError` listing every missing id and every id whose hash
    differs. Ids in `texts` with no task are ignored.
  - `read_folder(folder) -> dict[str, str]`: raises `TextsError` when the folder does not exist,
    or a file's `sha256` is not the hash of its `text`.
  - `write_folder(folder, texts: dict[str, str]) -> None`: creates the folder, writes one file
    per text.
  - `read_langfuse() -> dict[str, str]`: id to `input["text"]` of each item of `DATASET`
    (items with no text are left out); raises `TextsError("Langfuse keys are not set")` when
    `watch_trace.enabled()` is false, and `TextsError(f"Langfuse failed: {type(e).__name__}")`
    on any error.
  - `upload(tasks_with_text: list[dict]) -> None`: creates the dataset when missing, then
    `create_dataset_item(dataset_name=DATASET, **item)` for each of `dataset_items(...)`.
  - `dataset_items(tasks: list[dict]) -> list[dict]`: unchanged from today.
  - `load(source: str, tasks: list[dict]) -> list[dict]`: `source == "langfuse"` reads
    Langfuse, else the folder; returns `attach(...)`.
  - `check_texts(tasks_with_text: list[dict]) -> list[str]`: one line per problem: an empty
    text, a text longer than `PIECE_CHARS + 400`, an injection task without `WATCH-OVERRIDE`,
    another task with it.
  - CLI `main()`: `split --tasks T --folder F`, `upload --tasks T --folder F`,
    `check --tasks T --texts langfuse|F`. Exit 0 on success; on `TextsError` or a non-empty `check_texts`, the
    lines to stderr and exit 1.

- [ ] **Step 1: Write the failing tests** in `tests/test_watch_texts.py`:
  - `test_split_removes_the_text_and_keeps_its_hash`: `split_task` of a task with
    `piece.text == "é note"` gives no `text`, `text_sha256 == sha("é note")`, every other field
    equal, and the input task unchanged.
  - `test_split_twice_changes_nothing`: splitting the split task returns it and `None`; the
    CLI `split` on split files leaves the task files and the folder as they were.
  - `test_attach_puts_the_text_back`: `attach([split], {id: text})[0] == original`.
  - `test_attach_names_every_missing_and_changed_task`: two tasks, one missing, one with
    `"other"`; `TextsError` message holds both ids.
  - `test_folder_round_trip` and `test_folder_with_a_wrong_hash_fails` and
    `test_a_missing_folder_is_named` (message holds the path).
  - `test_upload_then_read_langfuse_gives_the_texts` with `FakeLangfuse`; the items equal
    `dataset_items` of the tasks with text.
  - `test_read_langfuse_without_keys_says_so` and
    `test_read_langfuse_failure_names_the_type_only` (`FakeLangfuse(fail=ConnectionError("sk-x"))`:
    message is `Langfuse failed: ConnectionError`, no `sk-x`).
  - `test_check_texts_finds_each_problem`: empty, too long, injection without the mark, other
    task with the mark: four lines.
  - `test_cli_split_then_check_with_the_folder` (tmp tasks folder with two task files:
    after `split`, the files have no text, the folder has two files, `check` exits 0).
- [ ] **Step 2: Run** `uv run pytest tests/test_watch_texts.py -q`. Expected: fails on the
  import of `watch_texts`.
- [ ] **Step 3: Implement** `evals/watch_texts.py` with the interfaces above, and move
  `DATASET`/`dataset_items` out of `watch_run.py`. `read_langfuse` calls `watch_trace.setup()`
  then `get_client().get_dataset(DATASET).items`.
- [ ] **Step 4: Run** `uv run pytest -q` and `uv run ruff check .`. Expected: all pass.
- [ ] **Step 5: Commit** `Add watch_texts: the watch tasks' text outside git, checked by hash`.

### Task 2: The eval and the harvest read and write the text through `watch_texts`

**Files:**
- Modify: `evals/watch_run.py`, `evals/watch_harvest.py`, `.github/workflows/watch.yml`
  (the `eval` job's `Judge the tasks` step)
- Test: `tests/test_watch_run.py`, `tests/test_watch_harvest.py`, `tests/test_workflows.py`

**Interfaces:**
- Consumes: `watch_texts.load`, `split_task`, `write_folder`, `TextsError`.
- Produces: `run_tasks(tasks_dir, kitden, out, model, max_calls, model_name="", runs=1,
  texts=None)`: when `texts` is given, `load(texts, tasks)` runs before the first model call;
  `None` keeps today's behaviour for the tests that build tasks with text. `watch_run.py` gains
  a required `--texts`; `watch_harvest.py` gains a required `--texts <folder>`.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_reads_the_texts_from_the_folder_before_any_model_call`: tasks split into a
    folder; `run_tasks(..., texts=str(folder))` judges with the original pieces (the Fake model
    sees the text).
  - `test_a_missing_text_stops_the_run_before_any_model_call`: one text deleted from the
    folder; `TextsError` raised, the Fake model was called zero times, no findings file.
  - `test_main_with_langfuse_texts_and_no_keys_exits_1_with_one_line` (capsys: stderr is
    `Langfuse keys are not set\n`, exit code 1).
  - `test_harvest_writes_the_task_without_text_and_the_text_to_the_folder` (call `main` with
    `_issues` and `_fetch_pieces` faked as the existing tests do).
  - `test_the_eval_job_reads_the_texts_from_langfuse` in `tests/test_workflows.py`: the
    `eval` job's `Judge the tasks` step runs `evals/watch_run.py` with `--texts langfuse`
    (no test pins this command today).
- [ ] **Step 2: Run** the four test files. Expected: the new tests fail.
- [ ] **Step 3: Implement.** In `main()`, `TextsError` prints its message to stderr and
  exits 1. The harvest prints, after the made tasks:
  `upload their text: uv run --locked --only-group watch --only-group watch-io python evals/watch_texts.py upload --tasks <tasks> --folder <folder>`.
  In `watch.yml` add `--texts langfuse` to the `watch_run.py` command and say in the step's
  comment that the text comes from the Langfuse dataset, so the job needs its keys.
- [ ] **Step 4: Run** `uv run pytest -q`, `uv run ruff check .`,
  `uv run python scripts/check_agent_workflows.py .github/workflows`, and the
  `agentic-actions-auditor` skill on `watch.yml`. Expected: all pass, no new finding.
- [ ] **Step 5: Commit** `The watch eval and harvest take their text from Langfuse or a folder`.

### Task 3: Strip the forty task files

**Files:**
- Modify: the forty `evals/watch/tasks/*/task.json`, `tests/test_watch_tasks.py`,
  `evals/watch/README.md`, `docs/watcher-design.md` (the Langfuse part),
  `docs/superpowers/plans/2026-11-15-agent-docs.md` (Tasks 6.7 and parts 8–9: new tasks' text
  goes to the folder and Langfuse, never into git)

**Interfaces:**
- Consumes: the `split` and `check` commands.

- [ ] **Step 1: Change `tests/test_watch_tasks.py`:** `test_every_task_is_well_formed` asserts
  `"text" not in piece` and `re.fullmatch(r"[0-9a-f]{64}", piece["text_sha256"])` instead of
  the text checks; `test_only_the_injection_tasks_carry_a_planted_line` becomes
  `test_no_task_file_holds_vendor_text`: no task file is larger than 4000 bytes and none
  contains `WATCH-OVERRIDE`. (The text checks now run in `watch_texts.py check`.)
- [ ] **Step 2: Run** `uv run pytest tests/test_watch_tasks.py -q`. Expected: fails (the files
  still have text).
- [ ] **Step 3: Split.** Run
  `uv run --locked --only-group watch --only-group watch-io python evals/watch_texts.py split --tasks evals/watch/tasks --folder ~/Documents/work/kitden-private/watch-texts`,
  then `check --tasks evals/watch/tasks --texts ~/Documents/work/kitden-private/watch-texts`.
  Expected: 40 files in the folder, `check` exits 0.
- [ ] **Step 4: Docs.** README: where the text is (the dataset, and the owner's folder as the
  backup), the `--texts` flag in both commands, the three `watch_texts.py` commands, that the
  harvest's new tasks are read in the folder before the merge, and that old commits still hold
  the text. Keep it short: a few lines, not a section per command. watcher-design.md: the dataset is now the source of the texts and is not deleted by
  the plan's data window. The Agent Docs plan: one sentence in each of the places named above.
- [ ] **Step 5: Run** the full checks from Global Constraints. Expected: all pass.
- [ ] **Step 6: Commit** `Move the watch tasks' vendor text out of git (owner's answer to
  questions 6 and 11)`.

### Owner, before the merge

```sh
export LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... LANGFUSE_HOST=https://cloud.langfuse.com
uv run --locked --only-group watch --only-group watch-io python evals/watch_texts.py upload --tasks evals/watch/tasks --folder ~/Documents/work/kitden-private/watch-texts
uv run --locked --only-group watch --only-group watch-io python evals/watch_texts.py check --tasks evals/watch/tasks --texts langfuse
```

`check` must print nothing and exit 0. Then merge.
