# The release strip on the desk

## Why

On 17 Nov the release of Kitden 0.10.0 stood still for 15 minutes: the macOS build job
waited for a machine GitHub did not have, was cancelled, and PyPI, the GitHub release and
the stores were skipped. Nothing on the desk said so. The desk is built once a day, so it
cannot follow a release that takes about 20 minutes.

## What the owner sees

Only while a Kitden release runs, or when the last one failed:

```
Release 0.10.0
 ✓ Pull request → ✓ Checks on main → ✓ Tag → ● Build → ○ PyPI → ○ GitHub release → ○ Stores
   waiting for a macOS machine · 12 min
```

- ✓ done, ● running now, ○ ahead, ✕ failed.
- Under ● one short line: what happens and for how many minutes.
- Under ✕ a short reason and a link to the run, where GitHub has the re-run button.
- When the release is out, the strip goes away; the Stores block already says the rest.
- When GitHub does not answer, there is no strip. Nothing claims "all good" by default.

The page is in English, like the rest of the desk; the owner approved the Russian draft above
with these English words.

## Where the data comes from

The page itself reads GitHub's public API, without a token, when it opens and then once a
minute while it is open and visible. desk.json and `desk.yml` do not change.

Kitden's `.github/workflows/release.yml` ("Checks and release"):

| Step | Run | Jobs |
| --- | --- | --- |
| Pull request | the release prep's pull request `prepare-v<version>` | the whole run |
| Checks on main | the push to main | `build (macos-latest)`, `build (ubuntu-latest)` |
| Tag | the same run | `autotag` |
| Build | the push of tag `v<version>` | `build (macos-latest)`, `build (ubuntu-latest)` |
| PyPI | the same run | `publish` |
| GitHub release | the same run | `release` |
| Stores | the same run | `stores / …` (kitden-sdlc's publish.yml) |

Each poll:

1. `GET /repos/KonstantinStarovoytov/kitden/actions/workflows/release.yml/runs?per_page=30`.
   The newest run on a `v*` tag is the release; the newest run on `main` counts only when
   it is newer than that and carries a new release (below); the newest run of a pull request
   from `prepare-v<version>` counts when that version is newer than the newest tag's.
2. A main run carries a release when its `pyproject.toml` version has
   `docs/releases/v<version>.md` and no tag `v<version>` yet: two files from
   raw.githubusercontent.com at the run's commit and one `git/matching-refs/tags/v<version>`.
   That is read once per commit.
3. `GET …/actions/runs/<id>/jobs` of the run shown. Without a filter GitHub gives the jobs of
   the newest attempt, so a re-run is read as it is now.

A job's state: `queued`, `waiting` or `pending` is "waiting for a macOS (or Ubuntu) machine",
counted from when the job was made; `in_progress` is "running", counted from its start.
`success` is done; `failure`, `cancelled` or `timed_out` is failed. A job skipped or not made
yet is ahead. A cancelled job that never got a machine says so.

The pull request (added 17 Nov, after the owner looked for 0.10.1 while its pull request was
open): its run of the checks says how far it is; one more `GET …/pulls/<number>` says whether
it is still open and a draft. A pull request found closed is not asked again. Its one line:
"checks running · 4 min", "a check failed" with a link to the run, "a draft: finish what its
body lists", or "waiting for your merge", each with a link to the pull request.

Which strip:

- the newest main run carries a new release → the strip of that run: Checks on main and Tag
  from its jobs, Pull request done, the rest ahead;
- else an open release pull request with a newer version than the newest tag → its step,
  the rest ahead;
- else the newest tag run, unless it finished with success → Pull request, Checks on main
  and Tag done, the rest from its jobs;
- else no strip.

## Limits

- GitHub allows 60 requests an hour from one address without a token. A poll is one request
  with nothing to show and two while a strip is shown, so a page left open through an hour of
  release uses that up. The page does not poll while it is hidden. When GitHub refuses after
  a strip was shown, the strip stays with the time it is from, and says when the limit ends.
- A tag run that is not among the newest 30 runs of the workflow (pull requests count too,
  so about a day) is not found: a release that failed longer ago leaves the strip.

## Safety

The page still puts every text in as text. Links go only to github.com (the run). The CSP
allows `connect-src` to api.github.com besides raw.githubusercontent.com. All logic is in
view.js, without the DOM; tests/test_desk_page.py runs it in Node on saved API answers:
running, waiting in the queue, failed, released, a main run carrying a release, a main run
without one, and no answer.
