# Release flow for Kitden — design

Date: 2026-11-12. Status: draft for the owner's review. Merged from two drafts written the
same day; the owner's answers are marked "(owner, 2026-11-12)".

## Why

Every Kitden release is a list of manual steps in Kitden's
[docs/development.md → Release](https://github.com/KonstantinStarovoytov/kitden/blob/main/docs/development.md#release),
and steps get missed:

- The Homebrew bump PR waits for a merge that gets forgotten. Merged with the button, it
  publishes no bottles (this happened on 0.7.0).
- Publishing to the MCP Registry needs a GitHub login in a browser every time.
- The version sits in eight files, and only one of them is checked against the tag.
- The product description exists in four different wordings (PyPI, `server.json`,
  marketplace, plugin), and Glama shows another one.
- The Claude plugin directory reads `main`, so it picked up two later `main` commits as "0.7.2"
  that differ from the tagged 0.7.2. The plugin itself changed after that tag.
- README, release notes, ROADMAP and the policy files (SECURITY.md, PRIVACY.md, AI_POLICY.md)
  are rewritten by hand, and their format drifts. The notes format in development.md lists three
  sections, while v0.7.2 has five.

The owner wants to review one pull request per release and nothing else: everything after
the merge happens on its own and ends with every place showing the same version and the same
words.

## Goals

1. One release PR per version, prepared by an agent, reviewed and merged by the owner.
2. After the merge: tag, PyPI, GitHub release, MCP Registry, Homebrew and the Claude
   directory's branch all update with no further human step, except the reviews that
   Anthropic does in its directory.
3. Before anything is published, checks prove the version and the descriptions are the same
   everywhere and fit each platform's limits.
4. After publishing, a check finds any place that is behind or different, and says so.
5. A scheduled job proposes a release when `main` has unreleased user-facing changes.
6. kitden-sdlc's README and GitHub description explain in one picture and a few lines what
   this repository runs: review, watching, release.

## Non-goals

- Publishing without the owner's merge.
- Clicking anything in the Claude directory's web UI (it has no API we know of). The workflow
  only tells the owner when the Listing tab or the "collects user data" switch needs a change.
- Windows packages; Kitden runs on macOS and Linux only.
- Launch posts (Reddit, Habr).
- Changing the review agents or the client watcher, except where this design says so.

## Anti-goals (a failure even if it works)

- A model job that holds a publishing token or write access. Rule 1 of [RULES.md](../../../RULES.md)
  holds for every new job.
- A half-published release that nobody notices.
- A README that grows with every release. The agent must also cut, not only add.
- More than the owner's limits: at most 3 PRs waiting for the owner and at most 2 new agent
  PRs a day (from the owner's decisions on 2026-11-09).
- Machinery beyond what one maintainer needs. Prefer a check script over a generator, a cron
  rule over a model, an issue over a PR.

## What runs where

Kitden keeps thin callers; the logic lives in kitden-sdlc as reusable workflows (`on:
workflow_call`), scripts and skills. A reusable workflow runs in the caller's context, so the
secrets, `GITHUB_TOKEN` and OIDC claims are Kitden's. No publishing secret is stored in
kitden-sdlc, next to its review agents.

| Piece | Lives in | Model | Writes |
|---|---|---|---|
| `release-prep` (caller) | kitden, `workflow_dispatch` | — | — |
| `release-prep` (reusable) | kitden-sdlc | Claude, read-only tools | a branch and a PR, from a job without a model, with the release app |
| Auto-tag | kitden, in `release.yml` on push to `main` | none | a tag, with the release app |
| Build, checks, PyPI, GitHub release | kitden `release.yml` (exists today) | none | PyPI, release |
| `publish` (reusable) | kitden-sdlc, called by `release.yml` after PyPI | none | MCP Registry, `release` branch, Homebrew PR |
| Homebrew auto pull | the tap repo | none | bottles, formula |
| `release-watch` (daily) | kitden-sdlc reusable, called by kitden on `schedule` | none | issues in Kitden |
| Skills | kitden-sdlc plugin `kitden-sdlc` | — | — |

PyPI publishing stays in Kitden's own `release.yml`, as now: its Trusted Publisher is that
file and the `pypi` environment.

### Identities and secrets

Lantern's private key is stored in kitden-sdlc for the client watcher. So Lantern must not get
write access to Kitden's code or to the tap: whoever holds a key that can push a `v*` tag can
publish to PyPI.

- **A new release-only GitHub App** (the release app), installed on `kitden` (contents and
  pull-requests write) and on `homebrew-tap` (contents and pull-requests write). Its private
  key is stored only in Kitden, as a secret of a new environment `release`. Only the auto-tag,
  open-pr and Homebrew jobs use that environment. No model job does.
- **Why an app at all:** a tag or PR made with `GITHUB_TOKEN` starts no workflows, and
  Kitden does not let Actions create PRs ("can_approve_pull_request_reviews": false).
- **Harden what exists** (state checked 2026-11-12): the `pypi` environment has no protection
  rules and no ref policy, and there are no rulesets. Limit `pypi` to tags `v*`. Add a tag
  ruleset on `v*`: only the release app and the owner may create one, nobody may move or
  delete one. `main` keeps its required checks; there are no required reviews, and the owner's
  merge is the review. Limit `release` (the environment) to `main` and `v*` tags.
- Lantern keeps its job: comments and issues.

## Part A — Publishing (no model)

### A1. Before publishing: one consistency check

A script in kitden-sdlc, run by Kitden's `release.yml` on every PR and on every tag, with the
data in Kitden:

- **Version.** The same `X.Y.Z` in all eight places listed in development.md: `pyproject.toml`,
  `src/kitden/__init__.py`, both `plugin.json` files, both versions in `server.json`,
  `install.sh`, `install.ps1`. On a tag it must also equal the tag. Kitden's
  `tests/unit/test_release_files.py` already checks that the eight match, and `release.yml`
  already compares the tag with `pyproject.toml`. The check reuses those and does not repeat
  them.
- **Descriptions.** One file in Kitden, `listing.toml`, holds each wording once:
  - `short` — PyPI `description`, `server.json` `description`, Kitden's GitHub repo
    description;
  - `brew` — Homebrew `desc`, a separate field because `brew audit` asks for less than 80
    characters and no full stop (today's `server.json` text has 99);
  - `tagline` — the top `description` in `.claude-plugin/marketplace.json`;
  - `plugin` — both `plugin.json` files and the plugin entry in the marketplace. The entry
    also carries `displayName` and `keywords` (see A5: with a non-relative source, Claude Code
    shows only the entry's fields before install).

  The check compares only files in Kitden, and fails when one differs from `listing.toml` or
  a text breaks a platform limit. Limits are written next to the field with the date they were
  checked (for example the `server.json` schema's maximum length). Builder: verify each limit
  from the platform's own docs or schema. The Homebrew `desc` is set by the tap bump PR (A6).
  The GitHub repo description cannot be set without admin rights, so `release-watch` (A7)
  reports it and the owner changes it by hand; it changes rarely.

  The first wordings: the agent that builds A1 drafts them from today's texts, and the owner
  approves them in that PR.
- **Registry line.** README holds `mcp-name: io.github.KonstantinStarovoytov/kitden`.
- **Notes.** `docs/releases/vX.Y.Z.md` exists and has the sections of the house format (see B3).

The two `plugin.json` files differ today: the Codex one (`plugins/kitden/plugin.json`) lacks
`keywords`, `privacyPolicyUrl` and `icon`. Not on purpose (owner, 2026-11-12): add what fits.
Its schema (`agent-plugins.org/schemas/1.0.0/plugin.schema.json`, checked 2026-11-12) has
`additionalProperties: false` and allows only `name`, `version`, `description`, `author`,
`homepage`, `repository`, `license`, `keywords` and `extensions`. So `keywords` is added, and
`icon`, `privacyPolicyUrl`, `displayName` and `documentationUrl` stay only in the Claude file:
adding them would break the Codex schema. The Claude directory reads
`.claude-plugin/plugin.json`, which does not change. The check compares the fields both
schemas allow.

A generator (`--fix`) that writes the wordings into the files is allowed if it stays small;
the check is required.

### A2. Auto-tag

On push to `main`: if `v$(uv version --short)` has no tag and its notes file exists, a job in
the `release` environment creates the tag with the release app's token. The tag push starts
`release.yml` on the tag, which publishes; `pypi` accepts only `v*` tags, so publishing from
the `main` run is impossible by design. The tag must lead to exactly one publish.

### A3. PyPI and GitHub release

Unchanged from today's `release.yml`. A macOS runner sometimes is not given in 15 minutes and
the run shows as cancelled with no steps (seen twice on 0.5.0); `release-watch` (A7) reports a
tag with no PyPI version, and a re-run finishes it.

### A4. MCP Registry

In the `publish` reusable workflow, a job with `id-token: write` and nothing else:

1. Wait until PyPI serves `kitden==X.Y.Z` (poll the JSON API, a time limit of about 15 min).
2. Skip if the registry already has this version.
3. Download a pinned `mcp-publisher` release and check its SHA-256.
4. `mcp-publisher login github-oidc`, then `mcp-publisher publish`.

No secret is needed: the registry trusts GitHub's OIDC token for the
`io.github.KonstantinStarovoytov/*` namespace. Builder: confirm on the registry's GitHub
Actions guide and note the date checked.

Glama and PulseMCP read from the registry (development.md, checked 2026-11-08). Builder: find
out where Glama takes the description it shows. If not from the registry, add Glama to the
manual list in the release summary.

### A5. Claude plugin directory

The directory reads a branch or tag set in its Settings and scans new commits about every 6
hours. Automatic publishing is on, and the first version still waits for an Anthropic
reviewer.

- The `publish` workflow moves a branch `release` to the tag (fast-forward only). Protect
  `release` so only the workflow moves it.
- The owner switches "Tracked branch or tag" to `release` once, when both are true: the
  `release` branch exists at a tag published by the new pipeline, and the publish request
  waiting now has been decided by Anthropic. Switching earlier cancels that request, and it is
  for a commit that holds the privacy page the plugin links to.
- The release summary links the directory page and lists hand steps when the release PR
  changed `listing.toml`'s `plugin` text or the plugin's data behaviour.
- The directory reported "Scan passed, with directory policy warnings". The owner copies these
  warnings into `docs/platform-rules.md` (B5), so the agent checks against them.

**Kitden's own marketplaces read the `release` branch too** (owner, 2026-11-12). Today
`/plugin install kitden --marketplace KonstantinStarovoytov/kitden` and Codex's
`.agents/plugins/marketplace.json` read the plugin from `main`, so between releases people get
unreleased plugin code under the last version: the same problem as the directory.

- The plugin entry in `.claude-plugin/marketplace.json` changes from `"./plugins/kitden"` to
  `{"source": "git-subdir", "url": "KonstantinStarovoytov/kitden", "path": "plugins/kitden",
  "ref": "release"}` (Claude Code docs, "Marketplace reference → Plugin sources", checked
  2026-11-12). The marketplace file is still read from `main`, but the plugin comes from
  `release`. The install line stays the same, and people who already added the marketplace
  get released plugins with no step on their side.
- With a source that is not a relative path, Claude Code shows only the entry's own fields
  before install, so the entry holds `description`, `displayName` and `keywords`, checked by
  A1.
- Builder: find out whether Codex's marketplace can pin a branch. If not, its install line in
  Kitden's README and the plugin README names the `release` branch.
- `release-watch` (A7) checks the entry still points at `ref: release`.

### A6. Homebrew

Two facts from past releases decide this part:

- On release day `brew bump-formula-pr` fails ("Unable to determine dependencies"): Homebrew
  takes only PyPI files more than a day old (seen on 0.7.0).
- Bottles are made only by the tap's `brew pr-pull` workflow (`publish.yml`), never by the
  Merge button.

So:

1. **In the tap:** a new small workflow runs after `tests.yml` succeeds on a PR whose branch
   matches `bump-kitden-*` or the autobump branch, and whose author is the tap's own bot or
   the release app. It dispatches `publish.yml` with the PR number and head SHA. Fork PRs never
   qualify. After it, the bottle block's `root_url` is checked. Builder: the tap's
   `autobump.yml` opens its PRs with `GITHUB_TOKEN`, and such PRs start no workflows, so
   `tests.yml` may not run on them today. If it does not, autobump uses the release app's
   token instead.
2. **From the release:** if Kitden's runtime dependencies did not change since the last tag,
   the `publish` workflow edits `url` and `sha256` (and `desc`, when it differs from
   `listing.toml`'s `brew`) in `Formula/kitden.rb` on a branch `bump-kitden-X.Y.Z` in the tap
   and opens a PR titled "kitden X.Y.Z", with the release app, in the `release` environment.
   Step 1 accepts PRs by the release app.
3. **If dependencies changed:** nothing on release day; the tap's daily autobump opens the PR
   the next day, and step 1 pulls it.

Either way no human merges anything. `release-watch` reports Homebrew still behind PyPI after
48 hours.

### A7. `release-watch` (daily, no model)

One scheduled job with two duties, each ending in at most one open issue in Kitden (an issue
is updated in place, never duplicated):

- **Drift.** Compares the latest tag, PyPI, GitHub release, MCP Registry, the Homebrew
  formula (version and `desc`), the `release` branch, the marketplace entry's `ref` and
  Kitden's GitHub repo description. An issue opens only when something is behind for more
  than 48 hours or differs.
- **Release proposal.** When `main` has merged PRs that change `src/`, `plugins/` or
  `install.*` since the last tag, and the last tag is 7 or more days old (or a PR labelled
  `bug` was merged), it opens "Time for a release?" with the list of changes and a link to run
  `release-prep`. It proposes no version number: without a model it cannot tell New from
  Fixed, and Kitden's PRs carry no prefixes for it. The agent picks the number in B2.

The thresholds (7 days, 48 hours) are the builder's defaults; keep them in one place.

### A8. Release summary

The last job of the `publish` workflow writes a table to the job summary: place, expected
version, seen version, state. The Claude directory and Glama show as "check by hand" with
links. The job fails if PyPI, the GitHub release, the registry or the `release` branch is wrong.

## Part B — Release prep (one agent)

### B1. Start

`release-prep` runs by hand (`workflow_dispatch`, optional version input), usually from the
`release-watch` issue. It refuses to start while another release PR is open.

### B2. Jobs

1. **prepare** (no model): collects the context into an artifact: `git log` since the last
   tag, the merged PRs (title, body, labels, author), the diff stat, and the files the agent
   must read.
2. **agent** (Claude, read-only tools by exact name, writes only to an output folder, no Bash,
   web or MCP, as rule 6): writes
   - the version, when none was given: minor when anything is New, patch otherwise (a
     breaking change is minor too, while below 1.0);
   - `docs/releases/vX.Y.Z.md` by the `release-notes` skill;
   - README changes by the `readme-kitden` skill, plus a list of scenes to re-record;
   - policy changes: what in this release touches data, network, secrets or permissions, and
     the edits themselves to SECURITY.md, PRIVACY.md, AI_POLICY.md and `listing.toml`, each
     with its reason (owner, 2026-11-12: the agent edits, it does not only propose);
   - platform findings against `docs/platform-rules.md`;
   - the hand-check list: the real-client checks from development.md "Check before a
     release" that this release's changes touch.
3. **bump** (no model): refuses a version that is not the next minor or patch, then sets it
   in all eight places, moves ROADMAP's "### Not released yet" under the version and sets
   "Last updated".
4. **record** (no model): runs Kitden's own `scripts/record_readme.py` and
   `scripts/record_scenes.py` for the listed scenes. Builder: find out whether they run on a
   GitHub runner and give the same picture as on the owner's Mac. If not, skip this job and
   list the scenes in the PR body for the owner to record.
5. **open-pr** (no model, release app, `release` environment): applies the files, runs the A1
   check, commits to `prepare-vX.Y.Z` and opens the PR. (Not `release/vX.Y.Z`: git cannot hold
   branches `release/…` next to the branch `release` from A5.) The policy and `listing.toml`
   edits go in a commit of their own, so the owner reads them apart from the notes and README.
   The body holds the findings, the hand-check list, any hand steps in the Claude directory,
   and a reminder to merge with a merge commit, not squash (the notes link branch commits).

MERGE_POLICY says changes to policy "go only to a human". That holds: the agent writes, and
nothing reaches `main` without the owner's merge.

The agent review does not run on this PR: the release app opens it, and the review skips bots
(rule 2). The code in it was reviewed in its own PRs; this one holds texts, pictures and the
version. Kitden's usual checks and A1 do run.

Model and limits follow RULES.md (timeout, turn limit, one run at a time, the
`AGENTS_ENABLED` switch). Model choice: start with the reviewer's model; measure later.

### B3. Skill `release-notes`

Based on the `release-notes` skill in [OpenHands/extensions](https://github.com/OpenHands/extensions/tree/main/plugins/release-notes)
(MIT; keep the license notice), rewritten for Kitden's house format, which the owner has used
since v0.3.0:

- title `# Kitden X.Y.Z — <theme>`, then a short overview;
- sections New, Better, Fixed, Documentation, each item linking its PR and author; empty
  sections are left out;
- "Upgrade and limits";
- a details block with every other commit;
- the full-changelog link.

Kitden's development.md is updated to this format in the same change, so the two do not
drift again. Plain, simple English, as Kitden's AGENTS.md asks.

### B4. Skill `readme-kitden`

Written from the owner's words and Kitden's `docs/readme-media.md`:

- small and easy to read; the value shows in the first screen;
- pictures of the real page do the convincing; text stays short;
- trust and safety are visible (local only, preview and undo, nothing leaves the Mac);
- a new feature earns a place only if it changes why someone would install Kitden;
  otherwise it goes to the guide. For anything added, the agent proposes something to cut
  or move;
- the scene rules in readme-media.md hold (sizes, light and dark, stills then one animation).

### B5. `docs/platform-rules.md`

A short digest of the rules each listing must follow: the Claude plugin directory (including
the policy warnings it reported), the MCP Registry, Glama, PyPI, Homebrew. Each rule has a
source link and the date checked. It lives in kitden-sdlc. Later, the client watcher may
watch these pages too; that is not part of this design.

### B6. Reminder for local work

One line in Kitden's AGENTS.md: a change that adds a feature, or changes what Kitden sends,
stores or reads, updates `listing.toml` and the policy files in the same PR. This reminds
agents; the A1 check and the release PR are what enforce it.

## Part C — kitden-sdlc's own face

- **GitHub description** (one line) and topics such as `github-actions`, `ai-code-review`,
  `claude-code`, `codex`, `sdlc`, `prompt-injection`, `release-automation`. The owner sees
  the text and says yes before it is set; it is public.
- **One picture**: an animated SVG, light and dark through `<picture>`, showing the cycle:
  PR → two reviewers → one comment; workflow change → rule check; client watcher → issues;
  release-watch → release PR → owner merges → tag → PyPI, Homebrew, MCP Registry, Claude
  directory → version check. The line "the model reads, a script writes" is drawn as the
  border between the two halves; it is the point of the repository. While Part A or B is not
  live, its part of the picture is marked "being built".
- **README**: one sentence of value, the picture, a short table of parts with an honest status
  (live, not switched on, being built), the eight rules in short, then "Copy this". Long
  details move to `docs/`. It reads as a working system, not a portfolio.
- **Badges**: license and the status of `checks.yml`. Nothing decorative.
- Updated in the same PR as each part that changes what the repository runs, per AGENTS.md.

## Order

0. The owner creates the release app, the `release` environment and the tag ruleset, and
   limits `pypi` to `v*` tags (see "Identities and secrets"). The builder writes the steps.
1. A1 and B6 (checks and the reminder). They help even before anything else is automated.
2. A4, A5, A8 (registry, `release` branch, summary), then A2 (auto-tag).
3. A6 (Homebrew, including the tap workflow).
4. A7 (`release-watch`).
5. B (release prep and its skills, `platform-rules.md`).
6. C in two steps: first with the current parts and the release marked "being built", final
   when B is live.

## Rules that apply to the builder

- kitden-sdlc's AGENTS.md: tests, ruff and `check_agent_workflows.py` before each commit; the
  `agentic-actions-auditor` skill for every workflow change; actions pinned by full SHA with
  the tag in a comment; RULES.md and README kept in step.
- Kitden's AGENTS.md for every change in Kitden (plain English, ROADMAP, checks before commit).
- New kitden-sdlc workflows are called at `@main`, like the review workflows today (rule 4).
  Downloads such as `mcp-publisher` are pinned to a version and a SHA-256.

## Left to the builder

- Script names, file layout and how the A1 check reports errors.
- Poll intervals and time limits, as long as a re-run is always safe.
- How the agent's output is handed between jobs (artifact layout).
- Exact SVG design and animation, within Part C.

## The next release

The owner wants a bigger step after "Update Kitden from the page" (Kitden PR 64, merged on
2026-11-12; `main` is 72 commits past v0.7.2). So the next version is **0.8.0**, not 0.7.3, and
it is released by hand, the old way, without waiting for this pipeline. (call: release it now;
the owner said only "after the update flow", which is already in.) The Claude directory
switches to `release` with the first release the new pipeline makes (A5).

## Still open for the owner

Nothing. All questions are answered.
