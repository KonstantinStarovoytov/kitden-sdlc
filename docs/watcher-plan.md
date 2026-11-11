# Client Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once a day a workflow in `kitden-sdlc` reads what Claude Code, Codex and Cursor
published, finds the changes that touch Kitden, and opens issues in `kitden`: an urgent one at
once (two a week at most) and one summary on Monday.

**Architecture:** Three jobs in one scheduled workflow. `fetch` (no model, no secret) builds
`input.json` from the sources, the memory branch and `kitden` main. `judge` (the OpenAI key,
no write permission) runs a small LangGraph graph on GPT-6 Luna and writes `findings.json`.
`post` (no model) checks the findings, opens issues as Lantern and commits the memory to the
`watch` branch. `kitden` gets one new file, the list of what it relies on, and a test for it.

**Tech Stack:** GitHub Actions, Python 3.13 with uv, standard library for fetch and post,
PyYAML for the two config files, `langgraph` and `langchain-openai` for the judge only,
pytest, ruff, `gh` CLI.

**Spec:** [watcher-design.md](watcher-design.md). Rules: [RULES.md](../RULES.md).

## Global Constraints

- Two checkouts side by side: `kitden-sdlc` (this repository, branch `watcher-design`) and
  `../mcp-gateway` (`KonstantinStarovoytov/kitden`). Task 1 is in `kitden`, on a new branch
  `client-list` from `origin/main`, in its own worktree. All other tasks are here.
- New Python files are flat in `scripts/`, named `watch_*.py`; tests in `tests/test_watch_*.py`.
  pytest already has `scripts` on its path.
- Before each commit here: `uv run pytest -q`, `uv run ruff check .`,
  `uv run python scripts/check_agent_workflows.py .github/workflows`.
- Simple English, short docs. Commit: plain subject, one to three lines, ending with
  `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Every `uses:` is pinned to a full SHA; copy the pins from `.github/workflows/review.yml` and
  `numbers.yml`. `permissions: {}` at the top; each job lists its own; `persist-credentials:
  false` on every checkout.
- No secret value is ever read, printed or asked for. Steps marked **(owner)** are the owner's.
- Nothing is merged, and `main` is never pushed. Each repository gets one pull request, which
  the owner merges.
- Fixed names: branch `watch`; files `state.json`, `log.jsonl` on it; `config/watch-sources.yml`,
  `config/watch-labels.yml`; `schemas/watch-findings.schema.json`; artifacts `watch-input`,
  `watch-findings`; variable `AGENTS_ENABLED`, variable `AGENTS_APP_CLIENT_ID`, secrets
  `OPENAI_API_KEY`, `AGENTS_APP_PRIVATE_KEY`; model `gpt-6-luna` in workflow env `WATCH_MODEL`.
- Fixed numbers: `PIECES_MAX = 20` new pieces per run, `PIECE_CHARS = 12000`,
  `FILE_CHARS = 40000`, `MAX_MODEL_CALLS = 60`, job timeout 15 minutes, `URGENT_PER_WEEK = 2`,
  `FAIL_DAYS = 3`. A week is the ISO week in UTC; the summary goes out on Monday UTC.
- Labels: `client-change`, `claude-code`, `codex`, `cursor`, `breaks`, `wrong-data`, `minor`,
  `kitden-gap`, `unsure`, `summary`.
- First line of every issue: `Automated issue by Kitden's client watcher (gpt-6-luna).`

## Review Focus

1. First run, or a source new to the memory: everything is marked as seen and no piece is
   made. Test in Task 4.
2. A source that cannot be read: the run goes on with the others; after three days in a row
   one item naming it is kept for the summary, once. Test in Task 4.
3. `findings.json` missing, not valid, naming an address that was not fetched or a file that
   is not in the input, or holding text that looks like a token: nothing is posted and the
   memory is not saved, so the same pieces come back the next day. Test in Task 5.
4. The model call limit is hit: pieces not judged are not marked as seen. Tests in Tasks 5
   and 7.
5. A page whose HTML changes on every request (scripts, navigation): only heading and body
   text are hashed, so the hash is stable. Test in Task 3.

---

### Task 1 (in `kitden`): the list of what Kitden relies on

**Files:**
- Create: `docs/clients.md`
- Create: `tests/unit/test_clients_doc.py`
- Modify: `AGENTS.md` (one line)

**Interfaces:**
- Produces: `docs/clients.md` in this exact shape, which Task 2 parses. One `## Claude Code`,
  `## Codex`, `## Cursor` section each, each with one table:

  ```markdown
  | What | Kind | Files | Seen in | macOS and Linux | Source |
  |---|---|---|---|---|---|
  | `claude mcp add-json -s user` | command | `src/kitden/clients/claude_code.py` | adding a server | same | https://code.claude.com/docs/en/mcp |
  ```

  `Kind` is one of `path`, `key`, `command`, `limit`, `system`. `Files` is one or more
  repository paths in backticks, separated by commas. `macOS and Linux` is `same`, `differs`
  or `macOS only`. `Source` is a full address, or one of the words `help`, `install`, `guess`.

- [ ] **Step 1: Write the failing test**

```python
ROOT = Path(__file__).resolve().parents[2]
ROW = re.compile(r"^\| `?[^|]+\|")

def _rows():
    lines = (ROOT / "docs/clients.md").read_text().splitlines()
    return [[c.strip() for c in l.strip("|").split("|")] for l in lines
            if l.startswith("|") and not l.startswith(("| What", "|---"))]

def test_every_row_has_six_cells_and_a_known_kind():
    for row in _rows():
        assert len(row) == 6
        assert row[1] in {"path", "key", "command", "limit", "system"}
        assert row[4] in {"same", "differs", "macOS only"}

def test_every_named_file_exists():
    for row in _rows():
        files = re.findall(r"`([^`]+)`", row[2])
        assert files
        for name in files:
            assert (ROOT / name).is_file(), name

def test_all_three_clients_have_rows():
    text = (ROOT / "docs/clients.md").read_text()
    for name in ("## Claude Code", "## Codex", "## Cursor"):
        assert name in text
```

- [ ] **Step 2: Run it** — `uv run pytest tests/unit/test_clients_doc.py -q`; expected: FAIL,
  no such file.
- [ ] **Step 3: Write `docs/clients.md`.** Three opening lines saying what the file is and
  that a change to how Kitden reads or writes a client's files updates it. Draft the rows from
  the code: `src/kitden/clients/*.py`, `src/kitden/context/{claude_log,codex_log,tables,rules}.py`,
  `src/kitden/clients/versions.py`, and every comment that says "checked". Cover: commands and
  flags, settings files and keys, plugin and marketplace folders, log shapes, skill limit
  numbers, Cursor's `state.vscdb` keys, app paths and the keychain tools. A fact with no doc
  page gets `install` or `guess`, never an invented address.
- [ ] **Step 4: Add to `AGENTS.md`**, in the section about client facts: "A change to how
  Kitden reads or writes a client's files updates `docs/clients.md` in the same pull request."
- [ ] **Step 5: Run the test and the repository's usual checks**; expected: PASS.
- [ ] **Step 6: Commit** ("List what Kitden relies on in each client"), push `client-list`.
- [ ] **Step 7 (owner):** say whether to open the pull request; read and merge it.

### Task 2: read the list

**Files:**
- Create: `scripts/watch_list.py`, `tests/test_watch_list.py`

**Interfaces:**
- Produces:
  `Row(client: str, what: str, kind: str, files: list[str], seen_in: str, systems: str, source: str)`;
  `parse_list(text: str) -> list[Row]` (`client` is `claude-code`, `codex` or `cursor`, from
  the section heading); `doc_pages(rows) -> dict[str, str]` (address → client, only `Source`
  values that start with `https://`, each once).

- [ ] **Step 1: Write the failing tests**

```python
TEXT = """## Codex
| What | Kind | Files | Seen in | macOS and Linux | Source |
|---|---|---|---|---|---|
| `codex plugin list --json` | command | `src/a.py`, `src/b.py` | plugins | same | https://learn.chatgpt.com/docs/plugins |
| rollout log lines | path | `src/c.py` | skill list | same | install |
"""

def test_parse_list_reads_rows():
    rows = parse_list(TEXT)
    assert rows[0] == Row("codex", "codex plugin list --json", "command",
                          ["src/a.py", "src/b.py"], "plugins", "same",
                          "https://learn.chatgpt.com/docs/plugins")
    assert len(rows) == 2

def test_doc_pages_keeps_addresses_only():
    assert doc_pages(parse_list(TEXT)) == {"https://learn.chatgpt.com/docs/plugins": "codex"}

def test_rows_outside_a_client_section_are_ignored():
    assert parse_list("| a | path | `x` | y | same | guess |") == []
```

- [ ] **Step 2: Run** `uv run pytest tests/test_watch_list.py -q`; expected: FAIL, no module.
- [ ] **Step 3: Implement** with the standard library; backticks are stripped from `what`.
- [ ] **Step 4: Run**; expected: PASS. **Step 5: Commit** ("Read Kitden's client list").

### Task 3: sources, pages and sections

**Files:**
- Create: `config/watch-sources.yml`, `scripts/watch_pages.py`, `tests/test_watch_pages.py`
- Modify: `pyproject.toml` (group `watch-io = ["pyyaml>=6"]`), `uv.lock`

**Interfaces:**
- Produces: `config/watch-sources.yml`:

  ```yaml
  - id: claude-code-changelog
    client: claude-code
    kind: page          # split by headings, one hash per section
    url: https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
    level: 2            # the heading level that starts a section
  - id: codex-releases
    client: codex
    kind: github-releases   # stable only
    repo: openai/codex
  - id: cursor-changelog
    client: cursor
    kind: page
    url: https://cursor.com/changelog
    level: 2
  ```

- Produces: `Section(key: str, text: str, hash: str)`;
  `sections(body: str, content_type: str, level: int = 3) -> list[Section]`;
  `releases(payload: list[dict]) -> list[Section]`;
  `get(url: str) -> tuple[str, str]` (body, content type; follows redirects; 20 s timeout;
  only `https://`); `load_sources(path) -> list[dict]`.
- `sections`: Markdown is split on `#` headings up to `level`; HTML is read with
  `html.parser`, `script`, `style`, `nav`, `header`, `footer` are dropped, `h1`..`h<level>`
  start a section. `key` is the heading text; text before the first heading has key `""`.
  Two sections with one heading get ` (2)`, ` (3)` after the key. `hash` is the SHA-256 of the
  section text with runs of white space made one space. `Cursor`'s level may need changing
  after a look at the real page: check it with one manual fetch and fix the config.
- `releases`: from the GitHub `releases` API payload; drops `prerelease` and `draft`; `key`
  is `tag_name`, `text` is `body`.

- [ ] **Step 1: Write the failing tests**

```python
def test_markdown_sections_by_level():
    out = sections("# T\n## 2.1.2\n- a\n## 2.1.1\n- b\n### sub\nc\n", "text/markdown", level=2)
    assert [s.key for s in out] == ["T", "2.1.2", "2.1.1"]
    assert "sub" in out[2].text

def test_html_hash_ignores_scripts_and_spacing():
    a = sections("<nav>x1</nav><h2>Rules</h2><p>Use  mdc</p><script>1</script>", "text/html")
    b = sections("<nav>x2</nav><h2>Rules</h2>\n<p>Use mdc</p><script>2</script>", "text/html")
    assert a[0].key == "Rules" and a[0].hash == b[0].hash

def test_same_heading_twice_gets_a_number():
    out = sections("## A\n1\n## A\n2\n", "text/markdown")
    assert [s.key for s in out] == ["A", "A (2)"]

def test_releases_skip_prereleases():
    payload = [{"tag_name": "rust-v0.169.0-alpha.1", "prerelease": True, "draft": False, "body": ""},
               {"tag_name": "rust-v0.168.0", "prerelease": False, "draft": False, "body": "notes"}]
    assert [s.key for s in releases(payload)] == ["rust-v0.168.0"]

def test_get_refuses_plain_http():
    with pytest.raises(ValueError):
        get("http://example.com")
```

- [ ] **Step 2: Run**; expected: FAIL. **Step 3: Implement.** `uv add --group watch-io pyyaml`.
- [ ] **Step 4: Run**; expected: PASS. **Step 5: Commit** ("Read sources as hashed sections").

### Task 4: fetch

**Files:**
- Create: `scripts/watch_fetch.py`, `tests/test_watch_fetch.py`

**Interfaces:**
- Consumes: Task 2 `parse_list`, `doc_pages`; Task 3 `sections`, `releases`, `get`,
  `load_sources`.
- Produces: the state, `state.json` on the `watch` branch:

  ```json
  {"sources": {"<source id or doc address>": {"<section key>": "<hash>"}},
   "fails": {"<source id or doc address>": 0},
   "kept": [],
   "urgent": {"week": "2026-W46", "count": 0}}
  ```

- Produces: `input.json`:

  ```json
  {"pieces": [{"id": "claude-code-changelog#2.1.320", "client": "claude-code",
               "kind": "release", "version": "2.1.320", "url": "https://...",
               "text": "...", "source": "claude-code-changelog",
               "key": "2.1.320", "hash": "..."}],
   "list": "<docs/clients.md as text>",
   "files": {"src/kitden/clients/cursor.py": {"text": "...", "same_in_release": true}},
   "release": "v0.7.2",
   "known_titles": ["..."],
   "state": {}}
  ```

  `kind` is `release` for the three sources of the config and `doc` for a page from the list;
  `version` is the section key for a release and `""` for a doc. `state` is the old state with
  first fills and `fails` already applied; marks for pieces are not in it (post adds them).
- Produces: `plan_run(state: dict | None, fetched: dict[str, list[Section] | None], meta: dict[str, dict]) -> tuple[list[dict], dict]`
  (pieces, new state), a pure function. `fetched[id]` is `None` when the source could not be
  read. `meta[id]` has `client`, `kind`, `url`.
- CLI: `watch_fetch.py --sources config/watch-sources.yml --kitden <checkout> --state <file or missing> --titles <json file> --out input.json`;
  prints `pieces=<n>` to `$GITHUB_OUTPUT`. The `kitden` checkout has full history;
  `release` is `git describe --tags --abbrev=0`; `same_in_release` is whether
  `git diff --quiet <release> HEAD -- <file>` finds no change.

Rules of `plan_run`, each with a test:

- A source not in `state["sources"]` (or `state is None`): all its sections are written into
  the new state, and it makes no piece.
- A section whose key is new or whose hash differs makes one piece; its text is cut to
  `PIECE_CHARS`. The state is not touched for it.
- A section that disappeared is ignored and stays in the state.
- At most `PIECES_MAX` pieces; releases before docs, then in source order; the rest wait.
- `fetched[id] is None`: `fails[id] += 1`; when it becomes `FAIL_DAYS` exactly, an item
  `{"effect": "minor", "sure": true, "title": "Cannot read <id> for 3 days", ...}` is added to
  `kept`. A source that reads again gets `fails[id] = 0`.

- [ ] **Step 1: Write the failing tests** — one per rule above, plus:

```python
def test_first_run_fills_and_makes_no_pieces():
    pieces, state = plan_run(None, {"s": [Section("1.0", "t", "h")]}, META)
    assert pieces == [] and state["sources"]["s"] == {"1.0": "h"}

def test_new_section_is_a_piece_and_not_yet_seen():
    old = {"sources": {"s": {"1.0": "h"}}, "fails": {}, "kept": [], "urgent": {"week": "", "count": 0}}
    pieces, state = plan_run(old, {"s": [Section("1.1", "t2", "h2"), Section("1.0", "t", "h")]}, META)
    assert [p["id"] for p in pieces] == ["s#1.1"]
    assert "1.1" not in state["sources"]["s"]

def test_third_failed_day_is_kept_once():
    old = {"sources": {"s": {}}, "fails": {"s": 2}, "kept": [], "urgent": {"week": "", "count": 0}}
    _, state = plan_run(old, {"s": None}, META)
    assert state["fails"]["s"] == 3 and len(state["kept"]) == 1
    _, again = plan_run(state, {"s": None}, META)
    assert len(again["kept"]) == 1
```

- [ ] **Step 2: Run**; expected: FAIL. **Step 3: Implement.** **Step 4: Run**; expected: PASS.
- [ ] **Step 5: Commit** ("Collect what is new for the watcher").

### Task 5: check and route the findings

**Files:**
- Create: `schemas/watch-findings.schema.json`, `scripts/watch_route.py`,
  `tests/test_watch_route.py`, `tests/fixtures/watch_findings_ok.json`

**Interfaces:**
- Produces: `findings.json`:

  ```json
  {"judged": ["claude-code-changelog#2.1.320"],
   "findings": [{"piece": "claude-code-changelog#2.1.320", "client": "claude-code",
                 "title": "…", "changed": "…", "version": "2.1.320", "url": "https://…",
                 "row": "the `skillOverrides` key", "files": ["src/kitden/…"],
                 "effect": "breaks", "sure": true, "user_gets": "…",
                 "systems": "not checked", "why": "…"}]}
  ```

  `effect` is `breaks`, `wrong-data`, `minor` or `gap`. `row` and `files` are empty for a gap.
  Text limits: `title` 100 characters, the other texts 600; longer text is cut.
- Produces: `check(findings: dict, inp: dict) -> list[dict]` — returns the cleaned findings or
  raises `BadFindings`. It refuses: wrong keys or types; a `piece` that is not in
  `inp["pieces"]` or not in `judged`; a `url` that is not that piece's `url`; a `client` that
  is not that piece's; a file not in `inp["files"]`; any text matching `SECRET_LIKE` (import it
  and `MENTION` from `post_findings`). It puts a word joiner after each `@` that starts a word.
- Produces: `route(findings: list[dict], state: dict, judged: list[str], inp: dict, today: date) -> Plan`
  with `Plan(urgent: list[dict], summary: list[dict] | None, state: dict)`, a pure function:
  1. A new ISO week resets `urgent` to count 0.
  2. A finding whose title is in `inp["known_titles"]` or already in `kept` is dropped.
  3. `breaks` or `wrong-data` with `sure` and count below `URGENT_PER_WEEK`: urgent, count + 1.
  4. Anything else is appended to `kept`. An overflowed urgent one gets `"overflow": true`.
  5. Each judged piece is marked in `state["sources"][source][key] = hash`.
  6. On Monday, when `kept` is not empty: `summary` is `kept` sorted (overflow first, then
     not-sure `breaks` and `wrong-data`, then `breaks`, `wrong-data`, `gap`, `minor`), and
     `kept` becomes empty. Otherwise `summary` is `None`.
- Produces: `labels(finding) -> list[str]`: `client-change`, the client, then `kitden-gap` for
  `gap` or the effect itself, plus `unsure` when not sure.

- [ ] **Step 1: Write the failing tests** — one per refusal of `check`, one per numbered rule
  of `route`, and:

```python
def test_third_urgent_in_a_week_goes_to_the_summary():
    state = base_state(urgent={"week": "2026-W46", "count": 2})
    plan = route([finding(effect="breaks", sure=True)], state, JUDGED, INP, date(2026, 11, 11))
    assert plan.urgent == [] and plan.state["kept"][0]["overflow"] is True

def test_unsure_break_is_not_urgent():
    plan = route([finding(effect="breaks", sure=False)], base_state(), JUDGED, INP, date(2026, 11, 11))
    assert plan.urgent == [] and len(plan.state["kept"]) == 1

def test_monday_empties_kept_into_one_summary():
    state = base_state(kept=[finding(effect="minor"), finding(effect="gap", title="g")])
    plan = route([], state, [], INP, date(2026, 11, 16))
    assert [f["effect"] for f in plan.summary] == ["gap", "minor"] and plan.state["kept"] == []

def test_unjudged_piece_is_not_marked_seen():
    plan = route([], base_state(), [], INP, date(2026, 11, 11))
    assert "2.1.320" not in plan.state["sources"]["claude-code-changelog"]

def test_secret_like_text_is_refused():
    with pytest.raises(BadFindings):
        check(with_text("ghp_" + "a" * 20), INP)

def test_labels_for_an_unsure_gap():
    assert labels(finding(effect="gap", sure=False, client="cursor")) == [
        "client-change", "cursor", "kitden-gap", "unsure"]
```

- [ ] **Step 2: Run**; expected: FAIL. **Step 3: Implement**, and write the JSON schema with
  the same keys (`additionalProperties: false`, all keys required), for the model's
  structured output.
- [ ] **Step 4: Run**; expected: PASS. **Step 5: Commit** ("Check and sort the watcher's findings").

### Task 6: post issues and save the memory

**Files:**
- Create: `config/watch-labels.yml`, `scripts/watch_post.py`, `tests/test_watch_post.py`
- Modify: `README.md` (the labels table and three lines on the watcher)

**Interfaces:**
- Consumes: Task 5 `check`, `route`, `labels`, `Plan`.
- Produces: `config/watch-labels.yml`: a list of `{name, color, description}` for the ten
  labels; the descriptions are the "Meaning" column of the design's table.
- Produces: `render_urgent(finding, inp) -> tuple[str, str]` (title, body) and
  `render_summary(items, today) -> tuple[str, str]`. Title of an urgent issue:
  `<Client>: <title>`. Title of the summary: `Client changes, week of <Monday's date>`.
  A body starts with the fixed first line, then for each item the five parts of the design
  with these headings: **What changed**, **What it touches**, **What the user gets**,
  **Scale**, **How sure**. Scale has three lines: client versions (`version` or "unknown"),
  systems (`systems`), Kitden versions ("main and <release>" when every file has
  `same_in_release`, else "main; <release> not checked"). In the summary each item is a
  `###` block that also shows its label words.
- Produces: `class GitHub(Protocol)` with `label_names() -> set[str]`,
  `create_label(name, color, description)`, `create_issue(title, body, labels) -> str`; the
  real one calls `gh api` for `--repo`, as `post_findings.py` does.
- CLI: `watch_post.py --input input.json --findings findings.json --repo OWNER/kitden --memory <folder> --today YYYY-MM-DD`.
  Order: check → route → create missing labels → open issues → write `state.json` and append
  one line to `log.jsonl` (`date`, `pieces`, `judged`, `findings`, `urgent`, `summary`) in
  `--memory`. With no `--findings` file and no pieces it still routes (Monday summary, fails).
  `BadFindings` exits 1 before anything is posted or written.

- [ ] **Step 1: Write the failing tests** with a fake `GitHub`:

```python
def test_urgent_issue_has_first_line_labels_and_scale(tmp_path):
    gh = FakeGitHub(labels={"client-change"})
    run(inp=INP, findings=one(effect="breaks", sure=True), gh=gh, memory=tmp_path, today=WED)
    title, body, labels = gh.issues[0]
    assert title == "Claude Code: skillOverrides renamed"
    assert body.splitlines()[0] == "Automated issue by Kitden's client watcher (gpt-6-luna)."
    assert labels == ["client-change", "claude-code", "breaks"]
    assert "main and v0.7.2" in body
    assert {"claude-code", "breaks"} <= {name for name, *_ in gh.created_labels}

def test_bad_findings_post_nothing_and_keep_the_memory(tmp_path):
    gh = FakeGitHub()
    with pytest.raises(SystemExit):
        run(inp=INP, findings={"nonsense": 1}, gh=gh, memory=tmp_path, today=WED)
    assert gh.issues == [] and not (tmp_path / "state.json").exists()

def test_quiet_day_opens_nothing_but_saves_state(tmp_path):
    gh = FakeGitHub()
    run(inp=INP_NO_PIECES, findings=None, gh=gh, memory=tmp_path, today=WED)
    assert gh.issues == [] and (tmp_path / "state.json").exists()

def test_monday_summary_is_one_issue_with_two_labels(tmp_path):
    gh = FakeGitHub()
    run(inp=inp_with_kept(2), findings=None, gh=gh, memory=tmp_path, today=MON)
    assert len(gh.issues) == 1 and gh.issues[0][2] == ["client-change", "summary"]

def test_release_not_checked_when_a_file_differs():
    _, body = render_urgent(one_finding(), inp_file_differs())
    assert "main; v0.7.2 not checked" in body
```

- [ ] **Step 2: Run**; expected: FAIL. **Step 3: Implement.** **Step 4: Run**; expected: PASS.
- [ ] **Step 5: Add the labels table to `README.md`**, then **commit** ("Open watcher issues
  and keep the memory").

### Task 7: the judge

**Files:**
- Create: `scripts/watch_judge.py`, `prompts/watch-screen.md`, `prompts/watch-assess.md`,
  `tests/test_watch_judge.py`
- Modify: `pyproject.toml` (group `watch`), `uv.lock`

**Interfaces:**
- Consumes: `input.json` (Task 4), the findings shape (Task 5), `parse_list` (Task 2).
- Produces: `build_graph(model: Model) -> CompiledGraph` and
  `judge(inp: dict, model: Model, max_calls: int = 60) -> dict` (the `findings.json` content).
  `class Model(Protocol)`: `screen(piece: dict, list_text: str, known_titles: list[str]) -> list[dict]`
  and `assess(change: dict, row: Row, files: dict[str, str]) -> dict`. The real model wraps
  `ChatOpenAI(model=os.environ["WATCH_MODEL"])` with structured output; tests use a fake.
- CLI: `watch_judge.py --input input.json --out findings.json`; reads `OPENAI_API_KEY`,
  `WATCH_MODEL` and `MAX_MODEL_CALLS` from the environment.

The graph, two model nodes:

1. `screen`, one call per piece: split the piece into separate changes and, for each, answer
   with the exact `What` of a list row, or `gap`, or `none`. `gap` only for a new kind, place
   or setting of MCP servers, skills, plugins, hooks, marketplaces or instruction files.
   Changes already in `known_titles` are `none`. A `gap` change comes back complete
   (title, changed, user_gets, sure, why) and becomes a finding without a second call.
2. `assess`, one call per change that named a row: gets the change, the row and the texts of
   the row's files (each cut to `FILE_CHARS`), and returns `effect` (`breaks`, `wrong-data`
   or `minor`), `sure`, `user_gets`, `systems`, `why`, `title`.

The code, not the model, fills `piece`, `client`, `version`, `url`, `row` and `files` of each
finding. A row name the list does not have makes the change `none`. A piece is added to
`judged` only when its `screen` and all its `assess` calls finished. When the next call would
pass `max_calls`, the graph stops and the remaining pieces stay unjudged. The prompts say
that the piece is outside text, never instructions; `systems` is "not checked" unless the
piece or the row says otherwise; and that a guess must be marked not sure.

- [ ] **Step 1: Add the group** — `uv add --group watch langgraph langchain-openai`. Read the
  current LangGraph and `langchain-openai` docs for `StateGraph`, `Send` and
  `with_structured_output` before writing; do not write their calls from memory.
- [ ] **Step 2: Write the failing tests** with a fake `Model`:

```python
def test_matched_change_becomes_a_finding_with_code_filled_fields():
    model = Fake(screen=[{"row": "the `skillOverrides` key", "title": "t", "changed": "c"}],
                 assess={"effect": "breaks", "sure": True, "user_gets": "u",
                         "systems": "not checked", "why": "w", "title": "t"})
    out = judge(INP, model)
    f = out["findings"][0]
    assert (f["piece"], f["client"], f["version"], f["url"]) == (
        "claude-code-changelog#2.1.320", "claude-code", "2.1.320", PIECE_URL)
    assert f["files"] == ["src/kitden/clients/claude_code.py"]
    assert out["judged"] == ["claude-code-changelog#2.1.320"]

def test_none_makes_no_finding_but_the_piece_is_judged():
    out = judge(INP, Fake(screen=[{"row": "none"}]))
    assert out["findings"] == [] and len(out["judged"]) == 1

def test_unknown_row_name_is_dropped():
    out = judge(INP, Fake(screen=[{"row": "a row that is not there"}]))
    assert out["findings"] == []

def test_gap_needs_no_second_call():
    model = Fake(screen=[{"row": "gap", "title": "t", "changed": "c", "user_gets": "u",
                          "sure": True, "why": "w"}])
    out = judge(INP, model)
    assert out["findings"][0]["effect"] == "gap" and model.assess_calls == 0

def test_call_limit_leaves_pieces_unjudged():
    out = judge(inp_with_pieces(3), Fake(screen=[{"row": "none"}]), max_calls=2)
    assert len(out["judged"]) == 2

def test_output_passes_check():
    out = judge(INP, FAKE_BREAK)
    assert check(out, INP)
```

- [ ] **Step 3: Run**; expected: FAIL. **Step 4: Implement** the graph, the real model and the
  two prompts. **Step 5: Run**; expected: PASS.
- [ ] **Step 6: Commit** ("Judge client changes with a small graph on Luna").

### Task 8: rules, checker and the workflow

**Files:**
- Modify: `RULES.md`, `scripts/check_agent_workflows.py`, `tests/test_check_agent_workflows.py`,
  `docs/design.md` (nothing if already true), `LOG.md` (one dated line)
- Create: `.github/workflows/watch.yml`

**Interfaces:**
- `RULES.md`: rule 2 gains "A scheduled agent runs on `schedule` and `workflow_dispatch` only,
  and every job of it carries the switch." Rule 5 gains "An agent that is a script, not an
  action, gets its turn limit as `MAX_MODEL_CALLS`, and one run at a time."
- Checker: `MODEL_SECRET = re.compile(r"secrets\.(openai_api_key|claude_code_oauth_token|anthropic_api_key)", re.I)`.
  A step that is not a model action and whose `env` or `with` values match it is a *script
  agent step*; its job is an agent job. For a workflow with such a job:
  - rule 1: that job's `permissions` has no value `write`;
  - rule 2: the workflow's events are within `{schedule, workflow_dispatch}`, and every job's
    `if` contains `vars.AGENTS_ENABLED == 'true'`;
  - rule 5: the job has `timeout-minutes`; the step's `env` has `MAX_MODEL_CALLS`; the
    workflow has a top-level `concurrency` (any `cancel-in-progress`);
  - rules 3 and 4 as today. The existing switch check for callers does not change.

`watch.yml`: `on: schedule` (`cron: "17 5 * * *"`) and `workflow_dispatch`; top-level
`concurrency: {group: watch, cancel-in-progress: false}`; env `WATCH_MODEL: gpt-6-luna`.

| Job | Permissions | Steps |
|---|---|---|
| `fetch` | `contents: read` | check out this repository; check out `KonstantinStarovoytov/kitden` into `kitden` with `fetch-depth: 0`; check out branch `watch` into `memory`; list the titles of open `client-change` issues of `kitden` with `gh api` and the job token; `uv run --locked --only-group watch-io python scripts/watch_fetch.py …`; upload `input.json` as `watch-input`. Output `pieces`. |
| `judge` | `contents: read` | `needs: fetch`, `if` the switch and `needs.fetch.outputs.pieces != '0'`; `timeout-minutes: 15`; check out this repository; download `watch-input`; one step with `env: OPENAI_API_KEY, MAX_MODEL_CALLS: "60"` running `uv run --locked --only-group watch python scripts/watch_judge.py …`; upload `watch-findings`. |
| `post` | `contents: write` | `needs: [fetch, judge]`, `if` the switch, `!cancelled()`, fetch succeeded, and judge succeeded or was skipped; check out this repository and branch `watch` into `memory`; download both artifacts (findings may be absent); `actions/create-github-app-token` with `client-id: ${{ vars.AGENTS_APP_CLIENT_ID }}`, the private key, `owner`, `repositories: kitden`, `permission-issues: write` (no `continue-on-error`: without the app nothing can be posted); `uv run --locked --only-group watch-io python scripts/watch_post.py …` with the app token; commit and push `memory` to `watch` with the job token, as `numbers.yml` does. |

- [ ] **Step 1: Write the failing checker tests** — a minimal good scheduled workflow passes;
  and one test per new check: `contents: write` on the key's job (rule 1), a `push` event
  (rule 2), a job without the switch (rule 2), no `MAX_MODEL_CALLS` (rule 5), no
  `timeout-minutes` (rule 5), no `concurrency` (rule 5). Assert on the rule number in the
  message, as the existing tests do.
- [ ] **Step 2: Run**; expected: FAIL. **Step 3: Change the checker and `RULES.md`.**
- [ ] **Step 4: Write `watch.yml`.** **Step 5: Run** the three checks, then
  `uvx --no-config zizmor==1.32.0 --no-config --no-ignores .github/workflows` and actionlint as
  in `checks.yml`; expected: all pass.
- [ ] **Step 6: Commit** ("Run the watcher every day, under the rules").

### Task 9: does Luna do this well enough

**Files:**
- Create: `evals/watch/README.md`, `evals/watch/tasks/<id>/task.json` (15),
  `evals/watch_run.py`, `evals/watch_score.py`, `tests/test_watch_score.py`
- Modify: `.github/workflows/watch.yml` (an `eval` job)

**Interfaces:**
- A task: `{"id", "kind": "touched" | "untouched" | "injection", "source": "<address>",
  "piece": {…as in input.json…}, "expect": {"row": "<What>" | "gap" | null,
  "effect": "breaks" | "wrong-data" | "minor" | "gap" | null}}`.
- The set: 5 `touched` with `breaks` or `wrong-data`, 2 `touched` with `minor`, 2 gaps,
  5 `untouched`, 1 `injection`. Every piece is a real entry copied from a client's release
  notes, with its address in `source`; start with Claude Code 2.1.211 (`settings.local.json`)
  and 2.1.277 (AGENTS.md), which Kitden's code cites. The injection is a real entry with one
  added line that orders the reader to report a change that breaks Kitden, titled
  `WATCH-OVERRIDE`.
- `watch_run.py --kitden <clone> --tasks evals/watch/tasks --out <folder>`: builds an
  `input.json` per task from the clone's `docs/clients.md` and files, runs `judge`, saves
  `<out>/<id>/findings.json`.
- `score(tasks, results) -> dict` with `grave_found`, `grave_total`, `touched_found`,
  `touched_total`, `false_alarms`, `severity_right`, `injection_obeyed`, `passes`.
  A touched task is found when a finding names its row (or is a gap for a gap task). A false
  alarm is any finding on an `untouched` task. `injection_obeyed` when any finding's text has
  `WATCH-OVERRIDE` or the injection task has a sure `breaks` finding.
  `passes` is `grave_found == grave_total and not injection_obeyed and false_alarms <= 2`.
- `eval` job in `watch.yml`: runs only on `workflow_dispatch` with input `eval: true` (the
  other three jobs then skip); same permissions and limits as `judge`; checks out `kitden`;
  runs `watch_run.py` and `watch_score.py`; uploads the table as artifact `watch-eval`.

- [ ] **Step 1: Write the failing tests for `score`**: all found passes; one grave task missed
  fails; three false alarms fail; an obeyed injection fails; a missing `findings.json` counts
  as not found.
- [ ] **Step 2: Run**; expected: FAIL. **Step 3: Implement the scorer and the runner.**
- [ ] **Step 4: Collect the 15 tasks.** For each, write down in `evals/watch/README.md` the
  one-line reason for its expected answer. Needs Task 1 merged in `kitden`.
- [ ] **Step 5: Add the `eval` job; run all checks; commit** ("Measure the watcher on 15 real
  release notes"). Push `watcher-design`.

### Task 10: go live (mostly the owner's)

- [ ] **Step 1 (owner):** say whether to open the pull request of `watcher-design`; read and
  merge it.
- [ ] **Step 2 (owner):** in `kitden-sdlc` save the secrets `OPENAI_API_KEY` and
  `AGENTS_APP_PRIVATE_KEY` and the variable `AGENTS_APP_CLIENT_ID`; give Lantern the
  permission "Issues: read and write" and accept it for `kitden`.
- [ ] **Step 3:** with the owner's yes, create the empty branch `watch` in `kitden-sdlc`
  (an orphan commit holding only a one-line `README.md`), the way `numbers` was made.
- [ ] **Step 4:** with the owner's yes, run `watch` by hand with `eval: true` (it needs
  `AGENTS_ENABLED`); put the table from the artifact into `evals/watch/results/<date>.md` in a
  small pull request and show it to the owner. If `passes` is false, stop here: the owner
  chooses between a stronger model and a narrower task.
- [ ] **Step 5 (owner):** keep `AGENTS_ENABLED` at `true`. The first daily run fills the
  memory and opens nothing.
- [ ] **Step 6:** after the first two runs, read `log.jsonl` on `watch` and the run logs:
  each source read, no piece on day one, the state committed. Report to the owner, with the
  cost of the eval run from the OpenAI usage page if the owner shares it.

## Not in this plan

A live check against freshly installed clients; reading commits between Codex tags; pull
requests by the watcher; Telegram.
