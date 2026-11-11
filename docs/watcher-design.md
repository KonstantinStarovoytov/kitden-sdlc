# The watcher: client changes that touch Kitden

Date: 2026-11-11. Owner's choices from a chat the same day; the rest are the writer's calls,
marked "(call)". It builds on [design.md](design.md): the rules, the switch, the review app
Lantern and the OpenAI budget are the ones described there.

## Why

Kitden reads and changes the setup of Claude Code, Codex and Cursor, so it rests on how those
tools behave: where their files are, what the keys mean, which commands and flags exist, how
they cut the skill list. The tools change several times a week. Until now the owner learned
about a change by luck, in a chat, when an agent happened to see it in release notes.

A look at Kitden on 2026-11-11 (main at `f2bf5e3`, then pull request 54) showed:

- 22 fixes in 26 days were caused by a fact about a client. Not one was triggered by reading
  release notes; no changelog address is cited anywhere in the code.
- Nothing notices a client change on its own. Tests never run a real client and the fixtures
  are frozen at one version of each.
- Since pull request 54 Kitden reads by shape, not by version, so a client change now more
  often gives a wrong or partial picture than a crash. Nobody reports a quiet wrong picture.

The watcher reads what the three tools publish and tells the owner, in a GitHub issue, which
changes touch Kitden and how much.

## Goals

1. Every day the watcher reads the new release notes and the changed doc pages of Claude Code,
   Codex and Cursor, and compares each change with what Kitden relies on.
2. A change that breaks a Kitden action or makes Kitden show wrong data gets its own issue the
   same day (owner).
3. Everything else goes into one summary issue a week (owner): changes that add something
   Kitden does not show yet, small ones, and ones the watcher is not sure about.
4. Each item says what changed, what it touches in Kitden, what the user gets, and the scale:
   which client versions, which systems, which Kitden versions (owner).
5. The owner gets one summary a week and at most two urgent issues a week (owner).
6. A written list of what Kitden relies on in each client exists in `kitden` and stays true.

## Non-goals

- Changing code or opening pull requests. Issues only for now (owner).
- Installing a fresh client and running Kitden against it. That is the next step (owner); it
  will catch what no release note mentions: log shapes, internal numbers, Cursor's database.
- Release notes of macOS and Linux. A system appears in an issue only as part of the scale.
- Other tools Kitden uses (the MCP spec, the MCP Registry, skills.sh) and other clients.
- Telegram. GitHub notifications only.

## Anti-goals

- Noise. More than one summary and two urgent issues a week, an issue when nothing touches
  Kitden, or two issues about one change.
- Guesses written as facts. Every item says how sure the watcher is and what was not checked.
- A watcher that obeys what it reads. Release notes and doc pages are text from outside; the
  model that reads them has no tools, no write permission and no token but the OpenAI key.
- A watcher that dies quietly: a source it has not been able to read for three days is named
  in the next summary.
- A first run that floods the owner with the clients' whole history.

## The parts

### 1. Where it runs

In `kitden-sdlc`, on its own schedule, once a day; it can also be started by hand (call). It
reads `kitden` as any stranger can, since the repository is public, and posts issues to
`kitden` as Lantern. `kitden` gets no workflow for it.

Why not a thin caller in `kitden`, like the reviewers: the watcher is not started by anything
that happens in `kitden`, and it must remember things between runs. That memory would be a
branch of agent data in the product's repository. The price of this call is in part 10: the
owner sets the secrets in `kitden-sdlc` too.

### 2. The list of what Kitden relies on

A file in `kitden`, `docs/clients.md` (name: call). It lives there because it is about
Kitden's code and must change in the same pull request as that code. One table per client; a
row is one thing Kitden relies on:

- what it is, in a few words (`claude mcp add-json -s user`, the `skillOverrides` key, the
  folder `~/.codex/.tmp/marketplaces`);
- its kind: path, key, command, limit or rule, system;
- the Kitden files that use it;
- which part of Kitden a user sees it in;
- whether it differs between macOS and Linux;
- where the fact comes from: a doc page, the client's `--help`, a real install, a guess.

The builder drafts it from the 2026-11-11 look and the "checked" comments already in the code;
the owner approves it as a pull request in `kitden`. A small test in `kitden` fails when a file
named in the list does not exist, so the list cannot rot unnoticed (call). `kitden`'s AGENTS.md
gets one line: a change to how Kitden reads or writes a client's files updates this list.

### 3. The sources

A file in `kitden-sdlc`, `config/watch-sources.yml` (call), so adding a source is one line:

| Client | Release notes | Doc pages |
|---|---|---|
| Claude Code | `CHANGELOG.md` of `anthropics/claude-code` | the pages named in the list |
| Codex | stable releases of `openai/codex` (call) | the pages named in the list |
| Cursor | the changelog page on cursor.com | the pages named in the list |

Codex pre-releases come several a day with empty notes (checked 2026-11-11), so the watcher
reads stable releases only. The price: a change the ChatGPT app ships early is seen at the
stable release. Reading commits between tags is not in this step.

A doc page is cut into sections by its headings. The watcher keeps one hash per section and
gives the model the new text of a section whose hash changed. It does not keep the pages
themselves: they are other companies' text, and the memory is public (call).

### 4. One run

Three jobs, in the shape the reviewers use.

1. **Fetch**, no model, no secret. Reads the sources and the memory (part 6), keeps only what
   is new, cuts each piece to a fixed size, and takes the list and the files it names from
   `kitden`'s main branch. For each of those files it notes whether it differs between main
   and the latest release tag; the model reads main only (call).
2. **Judge**, the model. It holds the OpenAI key and nothing else, and has no write permission
   and no tools: text in, a findings file out, in a fixed schema. A small LangGraph graph on
   GPT-6 Luna (owner, 2026-11-09) with these steps for each new piece: split it into separate
   changes; match each against the list; for a match, read the Kitden files the list names and
   say what the user gets; for something the list has no row for, decide whether it is a gap.
   A gap is a new kind, place or setting of the things Kitden shows: MCP servers, skills,
   plugins, hooks, marketplaces and instruction files. Any other new client feature is not
   reported (call). It also gets the titles of the open watcher issues and of this week's kept items,
   and skips what is already there.
3. **Post**, no model. Checks the findings file (schema, every source address is one that was
   fetched, every Kitden file exists, nothing that looks like a secret), then opens issues in
   `kitden` as Lantern and saves the memory.

Three cheap helpers (owner, 2026-11-11):

- **Word check**, no model, in Post. The exact words of the list (key names, paths, commands)
  are looked for in each judged piece. A word that is there while the model reported nothing
  for that row becomes a summary item marked `unsure`, so a quiet miss of the model is seen.
- **Second look**, in Judge. A finding that would be urgent gets one more model call that
  tries to refute it. If it is refuted, the finding goes to the summary as `unsure`.
- **Same start of every request.** The prompt and the list come first, word for word, so
  OpenAI can bill the repeated start at its lower price. The saving is not measured.

### 5. What the owner sees

**An urgent issue** is for a change the watcher is sure about that breaks a Kitden action or
makes Kitden show wrong data. One issue per change. At most two a week (owner); a third goes
to the top of the summary (call). A change that would be urgent but the watcher is not sure
about also goes to the top of the summary, marked as such (call).

**The weekly summary** is one issue in the first run of the week, normally Monday, with
everything else kept since the last one, the gravest first. No items means no issue.

Each item, in an urgent issue or as a short block in the summary:

- **What changed**: the client, from which version, a link to the source.
- **What it touches**: the row of the list, the part of Kitden a user sees, the files.
- **What the user gets**: the action fails, the data is wrong, or it is a small thing.
- **Scale**: client versions (from the release note; "unknown" for a doc change with no
  version), systems (only when the source or the list says so, else "not checked"), Kitden
  versions (main; the latest release too when the files are the same there, else "release
  not checked"; older ones are not checked).
- **How sure**: read in the source and matched to code, or a guess, and why.

Issues are in plain English, like the rest of the repository (call). The first line says the
issue is automated and which model wrote it (rule 8).

Labels, each with a description on GitHub and one table in the README of `kitden-sdlc`; the
post job creates a missing label from `config/watch-labels.yml` (call):

| Label | Meaning |
|---|---|
| `client-change` | Opened by the watcher: a client changed |
| `claude-code`, `codex`, `cursor` | Which client |
| `breaks` | A Kitden action stops working |
| `wrong-data` | Kitden shows something that is not true |
| `minor` | Small; nothing a user would trip over |
| `kitden-gap` | The client added something Kitden does not show yet (owner's name) |
| `unsure` | The watcher is not sure Kitden is touched |
| `summary` | The weekly summary (call) |
| `confirmed`, `false-alarm` | Set by the owner on closing: the watcher was right or wrong |

An urgent issue carries its own labels. The summary carries `client-change` and `summary`; its
items show the same words in their text.

### 6. Memory

A branch `watch` in `kitden-sdlc`, the same way the weekly numbers have theirs (call). It
holds the last version seen per source, the section hashes of each doc page, the items kept for
the next summary, the number of urgent issues this week, and one log line per run. It also
holds an archive: one line per judged change with the client, version, link, the watcher's
short conclusion and verdict (owner, 2026-11-11). The text is the watcher's own, so it can be
public, searched with grep, and indexed later if that is ever needed.

The first run only fills the memory and opens nothing.

### 7. Limits

- The switch: a variable `AGENTS_ENABLED` in `kitden-sdlc`; off means the watcher does not run.
- One run at a time, 15 minutes at most, a fixed top number of model calls and of new pieces
  per run; what does not fit waits for the next day (call).
- The OpenAI key and its $5 a month are the ones the Luna reviewer uses (owner). The watcher
  should cost cents; this is an expectation, not a measurement.

### 8. Rules and the checker

RULES.md changes in two places (call):

- Rule 2: review workflows run on `pull_request` only; a scheduled agent runs on `schedule`
  and by hand, and on nothing a stranger can trigger.
- Rule 5: for an agent that is not an action, the turn limit is a top number of model calls.

The checker finds agent workflows by the two actions they use. The watcher calls the model from
a script, so the checker must also treat any job that receives a model secret as an agent job.

### 9. Does Luna do this well enough

A set of tasks in `evals/`, 15 to start (call), from real release notes: entries that did
touch Kitden (for example the two the code already cites: Claude Code 2.1.211 on
`settings.local.json`, 2.1.277 on AGENTS.md), entries that touch nothing, and one entry with
text that tells the watcher to open an urgent issue; it passes when the watcher does not obey.
Score: touched ones found, false alarms, right severity. The table is committed.

The eval runs before the watcher is switched on, and the owner sees the table first. The bar
(call): every entry that breaks Kitden or gives wrong data is found, the planted instruction
is not obeyed, and at most 2 of the 15 are false alarms. Below the bar the watcher stays off
and the owner chooses between a stronger model and a narrower task; the model name is one
line of config.

The set grows from real cases (owner, 2026-11-11). The owner closes an urgent issue with
`confirmed` or `false-alarm`; about once a month a script turns such issues into new tasks,
and they come to `evals/` as a pull request. Summary items are not collected this way yet:
one issue holds many of them (call).

### 10. What only the owner does

- Saves `OPENAI_API_KEY`, `AGENTS_APP_CLIENT_ID` and `AGENTS_APP_PRIVATE_KEY` in `kitden-sdlc`
  and sets `AGENTS_ENABLED` there.
- Lets Lantern read and write issues in `kitden`.
- Approves `docs/clients.md` in `kitden`.

## Left to the builder

File, job and node names, the prompts, the findings schema, how a page becomes text, how a
change is recognised as already reported, the sizes and counts in part 7, the hour of the run,
and the exact wording of issues and label descriptions.

## Checked facts

- Kitden's dependencies and history: read from `kitden` main on 2026-11-11.
- Claude Code's changelog page is made from `CHANGELOG.md` in its GitHub repository
  ([docs](https://code.claude.com/docs/en/changelog)).

- `openai/codex` tags are `rust-v…`; pre-releases have empty notes, stable ones full notes.
- `cursor.com/changelog` and the `learn.chatgpt.com` doc pages answer a plain request;
  `cursor.com/docs/...` redirects.

Not checked: whether cursor.com has a feed for its changelog (none found); whether GitHub switches off a
scheduled workflow in a public repository that has commits only on a side branch; what the
watcher costs per run.
