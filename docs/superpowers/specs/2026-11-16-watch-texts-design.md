# The watch tasks' vendor text moves to Langfuse

The owner's answer to questions 6 and 11 of the Agent Docs design (2026-11-16): vendors' text
is not kept in this public repository. The forty tasks of `evals/watch/tasks` hold it in
`piece.text`, about 183 thousand characters of release notes and doc sections of Claude Code,
Codex and Cursor. This change moves that text out and keeps the eval working.

## What stays, what goes

- **Goes:** `piece.text` of every task, the planted tasks included (their planted lines sit
  inside vendor text).
- **Stays in git:** everything else in `task.json`: id, kind, source, the piece's other fields,
  `expect`, `kitden`. These are our work. A new field `piece.text_sha256` (SHA-256 of the
  text as UTF-8) pins the text each answer was checked against.
- **Stays, my call:** the short quotes in the "Why" column of `evals/watch/README.md`; they
  describe the answer and are a sentence each. The results files quote nothing longer.
- **Not touched:** git history (the text stays in old commits; rewriting a public repository's
  history does not remove copies and forks, so it is not done), and the `watch-input`
  artifacts (seven days, needed to debug a run).

Nothing else in the repository holds vendor text: not the reviewers' tasks (`evals/tasks`),
not `tests/fixtures`, not the `watch` branch (`archive.jsonl` holds the judge's own words).

## Approaches

1. **Langfuse dataset `watch-eval` plus a copy on the owner's Mac** (picked by the owner). The
   dataset already holds every task with its text: each eval run uploads it. Langfuse keeps
   datasets and their items whatever the plan's data window (docs: "Data retention",
   2026-11). The eval job already has the Langfuse keys. The eval runs by hand only, so the
   text is needed only when someone starts it.
2. A private GitHub repository read with a deploy key: history and a read-only key, but a new
   repository and key for an eval that runs a few times a month.
3. An encrypted file in this repository: the text would still be in the repository.

## How it works

- **The text source is named on the command line**: `watch_run.py --texts langfuse` or
  `--texts <folder>`. There is no default; without it, or when a task's text is missing, or
  when its SHA-256 differs from `text_sha256`, the run stops before any model call and names
  the tasks.
- **Langfuse:** item id = task id, `input` = the whole piece with its text, as today. The
  run no longer writes the input from the files alone (they have no text now): it joins each
  file to its text from `--texts`, checks the hash, and upserts the whole item through
  `watch_texts.upload`; the files stay the source of the answers.
- **The copy on the Mac:** a folder outside every repository, one `<task id>.json` per task
  (`{"id", "sha256", "text"}`). My call for the place: `~/Documents/work/kitden-private/watch-texts/`.
- **A small tool, `evals/watch_texts.py`:**
  - `split` (once): writes the copy from today's task files, then removes `text` from the
    task files and adds `text_sha256`; no network. The owner then runs `upload` with the
    Langfuse keys and `check --langfuse` before the pull request is merged (my call: the keys
    stay with the owner, and the move happens in two checked steps);
  - `upload`: folder → Langfuse (the folder is always the origin, so no copy back is
    needed);
  - `check`: the folder and Langfuse against the task files: same hashes, every text non-empty and
    at most the fetcher's length, `WATCH-OVERRIDE` only in the injection tasks (the checks
    `tests/test_watch_tasks.py` makes today on the text).
- **Harvest** (`watch_harvest.py`) writes new tasks without text, puts their text in the
  folder (`--texts <folder>`), and says to run `upload`. Reading new tasks before the merge
  means reading them in the folder.
- **CI:** the `eval` job passes `--texts langfuse`; with no Langfuse keys it fails with a
  clear message instead of running without them. No new secret.
- **A test** in `tests/test_watch_tasks.py` fails if any task file has `piece.text` or a
  missing or malformed `text_sha256`, so vendor text cannot come back unseen.
- **Docs:** `evals/watch/README.md` (where the text is, how to run, how to back up) and the
  Agent Docs plan's later eval tasks (Task 6.7, parts 8 and 9) follow the same path.

## Goals, non-goals

- Goal: no vendor text in new commits, and the eval scores as before on the same texts.
- Non-goal: changing the tasks, the judge or the score.
- Anti-goal: an eval that silently runs on a different or empty text.

## Risks

- The Langfuse key opens the whole project for reading and writing (Langfuse has no read-only
  key). The eval job already holds it, so this adds no exposure.
- Deleting the dataset by mistake loses the online copy: `upload` from the Mac folder puts
  it back.
