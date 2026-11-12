# Release Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kitden is released through one pull request the owner merges; tag, PyPI, MCP Registry,
Homebrew, the `release` branch and kitden-sdlc's README follow with no hand step.

**Architecture:** Logic lives in kitden-sdlc as Python scripts (tested offline with fixtures)
and reusable workflows; Kitden and the Homebrew tap get thin callers. Jobs with a model only
read; jobs that write hold the release app's token and run no model.

**Tech Stack:** Python 3.13, pytest, ruff, PyYAML, `tomllib`; GitHub Actions;
`anthropics/claude-code-action`; `mcp-publisher`; Homebrew `brew pr-pull`.

**Spec:** [docs/superpowers/specs/2026-11-12-release-flow-design.md](../specs/2026-11-12-release-flow-design.md)

## Where the work lands

Three repositories, so three pull requests. Each stays a draft until its tasks are done.

| Repository | Pull request | Tasks |
|---|---|---|
| kitden-sdlc | #8 (branch `release-flow-design`, holds the spec and this plan) | 1–8, 11 |
| kitden | new, branch `release-flow` | 9 |
| homebrew-tap | new, branch `auto-pull` | 10 |

Merge order: kitden-sdlc first (Kitden calls its workflows at `@main`), then the tap, then Kitden.
Task 12 is the owner's one-time setup; Task 13 is the first real release through the flow.

## Global Constraints

- kitden-sdlc's AGENTS.md: before each commit `uv run pytest -q`, `uv run ruff check .`,
  `uv run python scripts/check_agent_workflows.py .github/workflows`; run the
  `agentic-actions-auditor` skill on every new or changed workflow; pin every action by full
  SHA with the tag in a comment; keep RULES.md and README in step with the workflows.
- Kitden's AGENTS.md for Task 9: plain English; its five checks before each commit; ROADMAP and
  `docs/clients.md` rules.
- RULES.md's eight rules hold for every new job. No job holds untrusted text, a secret and
  write permission together; a model job never has `environment: release`.
- Every job checks `vars.AGENTS_ENABLED == 'true'` where it runs a model, and every publishing
  job runs only on `main` or a `v*` tag.
- Downloads (`mcp-publisher`) are pinned to a version and a SHA-256.
- The release app writes; Lantern only comments and opens issues (spec, "Identities and secrets").
- Owner limits: at most 3 PRs waiting for the owner, at most 2 new agent PRs a day; release-prep
  refuses to start while a release PR is open.
- Platform limits are taken from each platform's own docs or schema, with the date checked
  written next to them in `docs/platform-rules.md`.

## Review Focus

1. **A re-run after a partial failure.** Every publishing step first checks whether it is done
   (registry has the version, `release` is at the tag, a tap PR exists or the formula has the
   version) and skips. Tests: Task 4 `test_registry_skips_published`, `test_bump_skips_when_formula_current`.
2. **A tag pushed by hand.** Auto-tag skips an existing tag; publishing works the same. Test:
   Task 4 `test_autotag_skips_existing_tag`.
3. **A push to `main` that did not bump the version** (the tag for it already exists) or has no
   notes file. Auto-tag does nothing. Test: Task 4 `test_autotag_needs_new_version_and_notes`.
4. **PyPI slow to serve the version.** The registry job waits up to 15 minutes, then fails with
   "PyPI does not serve kitden X.Y.Z yet; re-run this job". Test: Task 4
   `test_wait_for_pypi_times_out_with_message`.
5. **A fork or bot PR that changes `listing.toml` or workflows.** It cannot reach the `release`
   environment (limited to `main` and `v*`) and the release check runs without secrets. Test:
   Task 6 `test_release_environment_only_without_model_and_on_main_or_tag`.

---

### Task 1: The release check (`release_check.py`)

Spec A1. Run by Kitden's CI on every PR and on every tag.

**Files:**
- Create: `scripts/release_check.py`
- Create: `tests/test_release_check.py`, `tests/fixtures/release/kitden/` (a minimal Kitden tree:
  `listing.toml`, `pyproject.toml`, `server.json`, `.claude-plugin/marketplace.json`,
  `plugins/kitden/plugin.json`, `plugins/kitden/.claude-plugin/plugin.json`, `README.md`,
  `docs/releases/v1.2.3.md`)
- Create: `docs/platform-rules.md` (the limits this task needs; Task 7 adds the rest)

**Interfaces:**
- Produces: `check(root: Path, tag: str | None = None) -> list[str]` (empty means pass; each
  string names the file and the field); CLI `python scripts/release_check.py ROOT [--tag vX.Y.Z]`,
  exit 1 and one line per problem. `LIMITS: dict[str, int]` and `load_listing(root) -> dict`.

`listing.toml` fields (spec A1): `short`, `brew`, `tagline`, `plugin`, `display_name`,
`keywords` (list). Mapping:

| Field | Compared with |
|---|---|
| `short` | `pyproject.toml` `project.description`, `server.json` `description` |
| `tagline` | `.claude-plugin/marketplace.json` top `description` |
| `plugin` | `description` in both `plugin.json` and in the marketplace plugin entry |
| `display_name`, `keywords` | the Claude `plugin.json` and the marketplace plugin entry; `keywords` also the Codex `plugin.json` |
| `brew` | length and `brew audit` rules only (the formula lives in the tap) |

The version fields are left to Kitden's `test_release_files.py`; on a tag the check compares the
tag with `pyproject.toml` only.

- [ ] **Step 1: Write the failing tests**

```python
def test_fixture_passes():
    assert check(FIXTURE) == []

def test_short_text_differs(tmp_path):
    root = copy_fixture(tmp_path); set_json(root / "server.json", "description", "Other")
    assert check(root) == ["server.json: description differs from listing.toml short"]

def test_server_description_over_limit(tmp_path): ...   # message names the limit and the length
def test_brew_text_breaks_audit(tmp_path): ...          # >= 80 chars, ends with ".", starts with "A "/"An "/"The ", or contains "Kitden"
def test_readme_lacks_mcp_name(tmp_path): ...           # "README.md: no mcp-name: io.github.KonstantinStarovoytov/kitden line"
def test_notes_missing_on_tag(tmp_path): ...            # check(root, "v1.2.4") reports docs/releases/v1.2.4.md missing
def test_notes_need_house_headings(tmp_path): ...       # title "# Kitden 1.2.3 — ", "## Upgrade and limits", the full-changelog line; New/Better/Fixed/Documentation optional
def test_tag_differs_from_pyproject(tmp_path): ...
def test_plugin_files_share_fields(tmp_path): ...       # name, version, description, author, homepage, repository, license, keywords must match
def test_cli_exit_codes(tmp_path): ...                  # 0 on the fixture, 1 with one line per problem
```

- [ ] **Step 2: Run `uv run pytest tests/test_release_check.py -q`.** Expected: FAIL, module missing.
- [ ] **Step 3: Implement `scripts/release_check.py`.** Read TOML with `tomllib`, JSON with `json`;
  the limits in `LIMITS` come from `docs/platform-rules.md` (verify the `server.json` schema's
  `description` maxLength and PyPI's summary rule; write them and the date there).
- [ ] **Step 4: Run the tests and the repo checks.** Expected: all pass.
- [ ] **Step 5: Commit** `scripts/release_check.py tests/test_release_check.py tests/fixtures/release docs/platform-rules.md`, message "Check that Kitden's listings agree before a release".

### Task 2: Reading the stores (`release_stores.py`)

Spec A7 (drift) and A8 (summary). No model, no secrets; every store is public.

**Files:**
- Create: `scripts/release_stores.py`, `tests/test_release_stores.py`,
  `tests/fixtures/release/stores/` (recorded JSON from PyPI, the registry, GitHub; a formula file)

**Interfaces:**
- Produces: `@dataclass Row(place: str, expected: str, seen: str, ok: bool | None)` (`None` =
  check by hand); `read_all(tag: str, fetch: Fetch) -> list[Row]` where
  `Fetch = Callable[[str], str]` returns a URL's body (tests pass a dict-backed fake);
  `summary(rows) -> str` (a Markdown table); `behind(rows, tag_age_hours: float) -> list[Row]`
  (rows not ok, Homebrew only after 48 hours).

Places, in order: PyPI, GitHub release, MCP Registry (version and `isLatest`), Homebrew formula
(version, `desc` equals `listing.toml` `brew`, bottle `root_url` ends with `kitden-X.Y.Z`),
`release` branch (at the tag's commit), marketplace entry (`ref` is `release`), Kitden's GitHub
description (equals `short`), Claude directory (`None`), Glama (`None`).

- [ ] **Step 1: Write the failing tests:** `test_all_current` (every row ok on the fixture),
  `test_registry_old_version`, `test_brew_bottles_old_root_url`, `test_marketplace_ref_main`,
  `test_hand_rows_are_none`, `test_behind_waits_48h_for_homebrew_only`, `test_summary_table`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** with `urllib.request` in the default `fetch`; registry URL
  `https://registry.modelcontextprotocol.io/v0/servers?search=io.github.KonstantinStarovoytov/kitden`.
- [ ] **Step 4: Run tests and repo checks.** Expected: pass.
- [ ] **Step 5: Commit**, "Read every store's Kitden version for the release summary".

### Task 3: Version, roadmap and formula edits (`release_bump.py`, `brew_bump.py`)

Spec B2 (bump) and A6 (formula fast path).

**Files:**
- Create: `scripts/release_bump.py`, `scripts/brew_bump.py`, `tests/test_release_bump.py`,
  `tests/test_brew_bump.py`, `tests/fixtures/release/kitden.rb`

**Interfaces:**
- Produces: `next_versions(current: str) -> tuple[str, str]` (minor, patch);
  `bump(root: Path, version: str) -> None` (the eight places from Kitden's development.md, the
  ROADMAP "### Not yet released" heading becomes `### X.Y.Z` and "Last updated" today's date);
  CLI `release_bump.py ROOT VERSION` refuses a version not in `next_versions`.
- Produces: `deps_changed(old_pyproject: str, new_pyproject: str) -> bool` (compares
  `project.dependencies`); `bump_formula(text: str, url: str, sha256: str, desc: str) -> str`
  (changes the top `url`, its `sha256` and `desc`, nothing in `resource` or `bottle` blocks).

- [ ] **Step 1: Failing tests:** `test_next_versions("0.8.0") == ("0.9.0", "0.8.1")`,
  `test_bump_sets_eight_places`, `test_bump_moves_roadmap_heading`,
  `test_cli_refuses_other_version`, `test_deps_changed_ignores_version`,
  `test_bump_formula_touches_top_only`, `test_bump_skips_when_formula_current`
  (`bump_formula` on a formula already at the URL returns it unchanged).
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** with plain text edits (regex anchored to the known lines); no TOML or
  Ruby writer.
- [ ] **Step 4: Run tests and checks.** Expected: pass.
- [ ] **Step 5: Commit**, "Bump Kitden's version and the formula from a script".

### Task 4: Publish workflow (`publish.yml`) and auto-tag

Spec A2, A4, A5, A6 step 2, A8.

**Files:**
- Create: `.github/workflows/publish.yml` (reusable), `scripts/release_publish.py`,
  `tests/test_release_publish.py`
- Create: `examples/release.yml` (Kitden's caller, copied into Kitden by Task 9)

**Interfaces:**
- Consumes: Task 2 `read_all`, `summary`; Task 3 `deps_changed`, `bump_formula`.
- Produces: `needs_tag(version: str, tags: set[str], notes_exist: bool) -> bool`;
  `wait_for_pypi(version: str, fetch: Fetch, sleep, timeout_s: int = 900) -> None` (raises
  `SystemExit("PyPI does not serve kitden X.Y.Z yet; re-run this job")`);
  `registry_has(version: str, fetch: Fetch) -> bool`.
- Produces: `publish.yml` inputs `version` (string); secrets `release_app_private_key`; vars
  `RELEASE_APP_CLIENT_ID` read by the caller.

Jobs in `publish.yml`, all `environment: release`, no model, `timeout-minutes`, least permissions:

| Job | Does | Token |
|---|---|---|
| `release-branch` | fast-forward `release` to the tag; skip if there | release app (contents write on kitden) |
| `registry` | `wait_for_pypi`, skip if `registry_has`, download pinned `mcp-publisher` and check SHA-256, `mcp-publisher login github-oidc`, `publish` | `id-token: write` only |
| `homebrew` | if not `deps_changed`: `bump_formula` on `bump-kitden-X.Y.Z` in the tap, PR "kitden X.Y.Z"; skip if the PR or version exists | release app (tap) |
| `summary` | `read_all` → job summary; fail if PyPI, GitHub release, registry or `release` branch is wrong; when `listing.toml` `plugin` or PRIVACY.md changed since the last tag, add "update the Claude directory's Listing tab / data switch" with its link | none |

Auto-tag lives in Kitden's `release.yml` (`examples/release.yml`): a job on push to `main` runs
`needs_tag` and pushes `vX.Y.Z` with the release app token.

- [ ] **Step 1: Failing tests:** `test_autotag_needs_new_version_and_notes`,
  `test_autotag_skips_existing_tag`, `test_wait_for_pypi_times_out_with_message`,
  `test_wait_for_pypi_returns_when_served`, `test_registry_skips_published`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement `scripts/release_publish.py`, then the two workflow files.** Verify the
  registry's GitHub Actions guide for `github-oidc` and note the date in `docs/platform-rules.md`.
- [ ] **Step 4: Run tests, the rule checker, `actionlint`, `zizmor` (configs in `config/`), and
  the `agentic-actions-auditor` skill on both files.** Expected: clean.
- [ ] **Step 5: Commit**, "Publish to every store after PyPI".

### Task 5: Release watch (`release-watch.yml`)

Spec A7. Daily, no model.

**Files:**
- Create: `.github/workflows/release-watch.yml` (reusable), `scripts/release_watch.py`,
  `tests/test_release_watch.py`, `examples/release-watch.yml` (Kitden caller, schedule daily)

**Interfaces:**
- Consumes: Task 2 `read_all`, `behind`.
- Produces: `propose(changed_paths_by_pr: dict[int, list[str]], labels_by_pr: dict[int, list[str]], last_tag_age_days: float) -> list[int] | None`
  (PR numbers to list, or `None`); `issue_body(...)` for both issues;
  `upsert(title: str, body: str, gh) -> None` (edits the open issue with that title, opens one if
  none, closes it when `body` is empty).

Rules (spec A7): propose when a merged PR since the last tag changed `src/`, `plugins/` or
`install.*`, and the last tag is at least 7 days old or a PR has the label `bug`. Title
"Time for a release?"; no version number. Drift issue title "Release vX.Y.Z is not everywhere".
Thresholds (7 days, 48 hours) are constants at the top of the script. Issues are posted by
Lantern in a job with no model.

- [ ] **Step 1: Failing tests:** `test_propose_needs_user_facing_change`,
  `test_propose_waits_7_days_unless_bug`, `test_upsert_edits_existing`,
  `test_upsert_closes_when_green`, `test_proposal_has_no_version`.
- [ ] **Step 2–4: Run (fail), implement, run tests + rule checker + auditor (pass).**
- [ ] **Step 5: Commit**, "Say each day whether a release is due or behind".

### Task 6: Rule checker knows the release jobs

**Files:**
- Modify: `scripts/check_agent_workflows.py`, `tests/test_check_agent_workflows.py`, `RULES.md`

**Interfaces:**
- Produces: a new check in `check_workflow`: a job with `environment: release` must not have a
  model step or a model secret, and the workflow's `on` must not include `pull_request_target`
  or `issue_comment`. Message: `job NAME holds the release environment and runs a model`.

- [ ] **Step 1: Failing tests:** `test_release_environment_only_without_model_and_on_main_or_tag`
  (a model step in a `release` job fails; Task 4's `publish.yml` passes).
- [ ] **Step 2–4: Run (fail), implement, run the checker on `.github/workflows` and `examples/` (pass).**
- [ ] **Step 5: Add one line to RULES.md rule 1 and commit**, "The release environment never runs a model".

### Task 7: Skills and platform rules

Spec B3, B4, B5.

**Files:**
- Create: `plugins/kitden-sdlc/skills/release-notes/SKILL.md` and `.../release-notes/LICENSE-OpenHands`
  (MIT notice from OpenHands/extensions)
- Create: `plugins/kitden-sdlc/skills/readme-kitden/SKILL.md`
- Modify: `docs/platform-rules.md` (Claude directory, MCP Registry, Glama, PyPI, Homebrew; each
  rule with link and date)
- Test: `tests/test_skills.py` (each skill has `name` and `description` frontmatter; the notes
  skill's example passes Task 1's notes-heading check)

The release-notes skill writes the house format (spec B3) and the version rule (any New → minor,
else patch). The readme skill carries the owner's words (spec B4): small, value on the first
screen, real pictures, visible trust, a cut for anything added, readme-media.md's scene rules.

- [ ] **Step 1: Failing test** `test_skills_have_frontmatter`, `test_notes_example_passes_check`.
- [ ] **Step 2–4: Run (fail), write the files, run (pass).** Leave a line in
  `platform-rules.md` for the directory's policy warnings, marked "owner fills in from the
  Review tab".
- [ ] **Step 5: Commit**, "Skills for release notes and Kitden's README".

### Task 8: Release prep (`release-prep.yml`)

Spec B1, B2.

**Files:**
- Create: `.github/workflows/release-prep.yml` (reusable), `scripts/release_context.py`,
  `scripts/release_apply.py`, `tests/test_release_context.py`, `tests/test_release_apply.py`,
  `examples/release-prep.yml` (Kitden caller, `workflow_dispatch` with optional `version`)

**Interfaces:**
- Consumes: Task 1 `check`; Task 3 `next_versions`, `bump`; Task 7 skills.
- Produces: `collect(root: Path, since_tag: str, gh) -> dict` (log, merged PRs with title, body,
  labels, author, diff stat) written as `context.json`; the agent writes `out/` with
  `version.txt`, `notes.md`, `README.md`, `policy/` (edited policy files and `listing.toml`),
  `findings.md`, `scenes.txt`; `apply(root: Path, out: Path) -> tuple[list[Path], list[Path]]`
  returns (content files, policy files) for the two commits, refusing any path outside the
  allowed set (`docs/releases/`, `README.md`, `ROADMAP.md`, `SECURITY.md`, `PRIVACY.md`,
  `AI_POLICY.md`, `listing.toml`).

Jobs: `guard` (no model: stop if a PR from a `prepare-v*` branch is open or the switch is off),
`prepare` (no model), `agent` (copy the `claude` job of `review.yml`: same action pin, plugin
dir, `--max-turns`, `Read(./**)`, `Edit(./out/**)`, the same `--disallowedTools`; Claude token
only, `contents: read`), `bump` (no model, Task 3 CLI with `out/version.txt`), `record` (no
model; runs Kitden's `record_readme.py` for `scenes.txt` on `macos-latest`; if a scene fails it
writes the scene into `findings.md` instead), `open-pr` (no model, `environment: release`,
release app: `apply`, `release_check.py`, two commits on `prepare-vX.Y.Z`, PR body =
`findings.md` + hand checks + "merge with a merge commit").

- [ ] **Step 1: Failing tests:** `test_collect_lists_prs_since_tag`,
  `test_apply_splits_policy_commit`, `test_apply_refuses_other_paths`
  (`out/.github/workflows/x.yml` is refused).
- [ ] **Step 2–4: Run (fail), implement scripts and workflow, run tests + checker + actionlint +
  zizmor + auditor (pass).**
- [ ] **Step 5: Commit**, "Prepare a Kitden release as one pull request".

### Task 9: Kitden side (repository `kitden`, branch `release-flow`)

Spec A1 data, A2, A5 marketplace, B6, and the docs.

**Files (in Kitden):**
- Create: `listing.toml` (first wordings drafted from today's texts; the owner picks in the PR)
- Modify: `.github/workflows/release.yml` (a step that checks out kitden-sdlc at `main` and runs
  `release_check.py .` on every PR and tag; the auto-tag job; after `release`, a job that calls
  `publish.yml@main`) — from `examples/release.yml`
- Create: `.github/workflows/release-prep.yml`, `.github/workflows/release-watch.yml` (from
  `examples/`)
- Modify: `pyproject.toml`, `server.json`, both `plugin.json`, `.claude-plugin/marketplace.json`
  to the `listing.toml` texts; the marketplace plugin entry becomes
  `{"source": "git-subdir", "url": "KonstantinStarovoytov/kitden", "path": "plugins/kitden", "ref": "release"}`
  with `description`, `displayName`, `keywords`
- Modify: `docs/development.md` "Release" (press Prepare release, review, merge; the notes
  format from spec B3 replaces the three-section line), `AGENTS.md` (spec B6 line), `ROADMAP.md`
- Test: Kitden's `tests/unit/test_release_files.py` gains `test_listing_matches_files` that runs
  kitden-sdlc's check only if it is importable (skip otherwise), so Kitden's own tests stay
  self-contained

- [ ] **Step 1: Write `listing.toml` and run `release_check.py` against Kitden.** Expected: it
  lists today's four wordings as differences.
- [ ] **Step 2: Update the files to the listing; run the check.** Expected: pass.
- [ ] **Step 3: Check Codex's marketplace can pin a branch** (its docs, dated); if not, point its
  install lines in README and `plugins/kitden/README.md` at `release`.
- [ ] **Step 4: Copy the three callers, run Kitden's five checks and `zizmor`.** Expected: pass.
- [ ] **Step 5: Commit, push, open the PR as a draft**, title "Release Kitden from one pull request".

### Task 10: Homebrew tap (repository `homebrew-tap`, branch `auto-pull`)

Spec A6 step 1.

**Files (in the tap):**
- Create: `.github/workflows/auto-pull.yml`: on `workflow_run` of `tests.yml` with conclusion
  `success` and event `pull_request`; continues only when the PR's head repo is the tap, its
  branch matches `bump-kitden-*` or the autobump branch, and its author is the tap's bot or the
  release app; then `gh workflow run publish.yml -f pull_request=N -f head_sha=SHA`, waits, and
  fails unless the formula's bottle `root_url` ends with `kitden-X.Y.Z`.
- Maybe modify: `.github/workflows/autobump.yml` to use the release app token, if PRs it opens
  with `GITHUB_TOKEN` do not start `tests.yml` (check the last autobump PR's checks first).

- [ ] **Step 1: Check whether autobump PRs get `tests.yml` runs** (`gh pr checks` on its last PR).
- [ ] **Step 2: Write `auto-pull.yml`; run `actionlint` and `zizmor`.** Expected: clean.
- [ ] **Step 3: Commit, push, open the PR as a draft**, title "Accept kitden bumps with pr-pull once tests pass".

### Task 11: kitden-sdlc's face

Spec C, and the README rule in AGENTS.md.

**Files:**
- Create: `docs/images/sdlc-light.svg`, `docs/images/sdlc-dark.svg` (one animated picture,
  `<picture>` switches them; motion off under `prefers-reduced-motion`)
- Create: `docs/agents.md` (moves the long parts of today's README: the agents table, the
  reviewers' methods and limits, the watcher's setup and labels)
- Modify: `README.md`, `pyproject.toml` `description`

Picture content (spec C): three lanes, PR → Claude + Luna → one comment (live); client docs →
Luna → issue in Kitden (eval, daily off); main → Claude drafts → release PR → owner merges →
tag → PyPI, Homebrew, MCP Registry, Claude directory (being built until Task 13). The border
"the model reads | a script writes" splits each lane.

README order: one sentence of value, the picture, badges (license, `checks.yml`), the parts table
with honest status (Review: live on Kitden; Workflow check: live; Client watcher: measuring, daily
run off; Weekly numbers: first run on Monday; Release flow: being built), the eight rules in
short, "Copy this", links (docs/agents.md, LOG.md, designs, MERGE_POLICY.md, evals).

- [ ] **Step 1: Draw both SVGs; open them in a browser in light and dark at 375 px and full width.**
  Expected: readable labels, no overlap, motion stops with reduced motion.
- [ ] **Step 2: Move the long sections to `docs/agents.md`; rewrite README.** Expected: README
  under 90 lines; every link resolves (`test_smoke.py` gains `test_readme_links_exist`).
- [ ] **Step 3: Run repo checks; commit**, "A README that shows what runs, in one picture".
- [ ] **Step 4 (after Task 13): mark the release lane live in the picture and the table; commit.**

### Task 12: Owner's one-time setup

Written by the builder as `docs/release-setup.md`; done by the owner.

1. Create the release GitHub App: contents and pull-requests write; install on `kitden` and
   `homebrew-tap`. Save its client id as variable `RELEASE_APP_CLIENT_ID` and its key as secret
   `RELEASE_APP_PRIVATE_KEY` in Kitden's new environment `release`.
2. Environment `release`: deployment branches `main` and tags `v*`. Environment `pypi`: tags `v*`
   only.
3. Tag ruleset on `v*`: only the release app and the owner create; nobody updates or deletes.
   Branch rule on `release`: only the release app pushes.
4. After the first release through the flow, and once Anthropic has decided the request now
   waiting: the directory's Settings → Tracked branch or tag = `release`.

### Task 13: First release through the flow

- [ ] **Step 1:** After all PRs are merged and Task 12 is done, press "Prepare release" in Kitden.
  Expected: one PR `prepare-vX.Y.Z` with notes, README and policy commits.
- [ ] **Step 2:** The owner merges with a merge commit. Expected: tag, PyPI, GitHub release,
  `release` branch, registry, tap PR, summary all green; `release-watch` shows Homebrew
  "waiting" or done.
- [ ] **Step 3:** Owner does Task 12 step 4; then Task 11 step 4.
