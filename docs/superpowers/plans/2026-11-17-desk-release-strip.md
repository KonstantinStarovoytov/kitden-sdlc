# The release strip on the desk: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the desk shows the Kitden release in flight, step by step, read live from GitHub's API.

**Architecture:** view.js gets one pure async function, `releaseNow(get, now)`, that asks
`get(url)` for GitHub's answers and returns the strip or null. index.html passes a `get` built
on `fetch`, draws the strip above the rest, and polls once a minute while visible. Tests run
`releaseNow` in Node on saved answers.

**Tech Stack:** plain ES modules, pytest + Node (as tests/test_desk_page.py already does).

**Spec:** `docs/superpowers/specs/2026-11-17-desk-release-strip-design.md`

## Global Constraints

- desk.json, `desk.yml` and the desk scripts do not change.
- Text goes in with textContent only; links only through `href()` (github.com).
- CSP `connect-src`: `https://raw.githubusercontent.com https://api.github.com`.
- After any change to view.js, the `?v=` in index.html is the first 12 hex of its SHA-256.
- A fact about a client comes from Agent Docs or the vendor's page, with the address and the
  date; a subagent that cannot reach them writes `not checked`. (No client facts here.)
- Words: steps `Checks on main`, `Tag`, `Build`, `PyPI`, `GitHub release`, `Stores`; title
  `Release <version>`; notes `waiting for a macOS machine · 12 min`, `running on macOS · 5 min`.

## Review Focus

- A re-run: jobs of the earlier attempt carried into the new one must not read as failed.
- A main push after a release with the same version must not show a strip.
- A job cancelled before any machine came says so, not just "cancelled".
- GitHub's limit (403, `x-ratelimit-remaining: 0`) after a strip was shown keeps the strip,
  marked with its time.
- Hostile or odd data (unknown status, a non-GitHub `html_url`) stays text and links nowhere.

---

### Task 1: `releaseNow` in view.js, tested on saved answers

**Files:**
- Modify: `docs/desk/view.js` (new section at the end)
- Create: `tests/fixtures/desk_release/*.json` (trimmed real answers, url → body or 404)
- Modify: `tests/test_desk_page.py`

**Interfaces:**
- Produces: `RELEASE_RUNS` (string URL), `async releaseNow(get, now) → null | {version, url,
  steps: [{name, state: 'done'|'now'|'ahead'|'failed', note: pieces}]}` where
  `get(url) → Promise<string|null>` (null = 404, throws otherwise).

- [ ] Tests `test_release_*`: running (`release` job queued → `● GitHub release`,
  `waiting for an Ubuntu machine · N min`), queued macOS build, failed attempt
  (`✕ Build`, reason "cancelled: no macOS machine came", link to the run), released (null),
  main run carrying 0.10.0 (Checks on main running, Tag ahead), main run without a new version
  (null), no answer (throws → page hides; `releaseNow` lets the error through).
- [ ] Run, see them fail; implement; run `uv run pytest -q tests/test_desk_page.py`; pass.
- [ ] Update `?v=` and the "reads only" test to allow the API URLs. Commit.

### Task 2: the strip on the page

**Files:** Modify `docs/desk/index.html`.

- [ ] A `<div id="release" hidden>` after `.head`; render the steps with ✓ ● ○ ✕ marks and the
  note under them; CSS for light and dark from the existing tokens.
- [ ] Poll: on load, every 60 s while `!document.hidden`, and on becoming visible. On an error
  with no strip shown: stay hidden. With one shown: keep it and add "From HH:MM UTC; GitHub
  did not answer" (with the reset time on a rate limit).
- [ ] `window.renderRelease(answers, now)` for a look in the browser, like `renderDesk`.
- [ ] Check in a browser, light and dark, desktop and 375 px; full test suite, ruff; commit.
