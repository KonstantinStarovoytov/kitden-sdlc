# Safe review of fork pull requests

Status: proposed, not enabled. Date: 2026-11-14.

This extends the original [review design](design.md). It does not change the running
workflows. Today forks are skipped. [The rollout plan](fork-review-plan.md) lists the
evidence needed before that changes. No design can promise zero vulnerabilities; the
boundaries below must be tested with hostile inputs before secrets are connected.

## Outcome

An eligible internal or fork PR gets the same two independent reviewers, the same models,
effort, prompts and context, and one Lantern comment. Review remains advisory. Ordinary
tests stay in separate, unprivileged CI. A failed or incomplete review never means clean.

Use a secret-free `pull_request` gate and a trusted `workflow_run` receiver. The receiver
must exist on the default branch. Changing the trigger alone is not a security fix.
GitHub documents both the elevated access and the risks of `workflow_run` (checked
2026-11-14; sources below).

## Boundaries

| Stage | Executes | Reads | Credentials | Writes |
|---|---|---|---|---|
| PR gate | a minimal workflow; no checkout | event identity | no secrets; read-only token | bounded request metadata only |
| Resolve and collect | pinned trusted scripts | GitHub API, immutable Git objects | short-lived read token | validated manifest and inert source bundle |
| Claude | pinned runner and trusted skill | source bundle through confined read/search tools | Claude credential outside model-accessible files and environment | bounded findings only |
| Luna | pinned runner and trusted prompt | the identical source bundle | OpenAI credential outside model-accessible files and environment | bounded findings only |
| Publish | pinned validator and renderer; no model | validated results and current GitHub state | read token, then narrowly scoped Lantern token | one review comment |

The gate can be altered by the PR. Treat everything it emits as a hint, including success.
It grants no trust to code, artifacts, workflow names, authors or future commits.
No privileged stage executes PR scripts, tests, dependencies, hooks, actions or plugins.
No shared cache, self-hosted runner, Docker socket, submodule or LFS execution path.
Use fresh hosted runners. No release credentials or contents-write permission in this flow.

## Resolve an exact request

1. Accept only a completed, successful run in the expected repository, from the allowlisted
   gate workflow ID and path, with event `pull_request`. Fetch the run through GitHub's API;
   do not trust a display name or a caller-supplied URL. Check its run ID and attempt.
2. Obtain candidate PRs from the run and GitHub's commit-to-PR association. A small JSON
   artifact from that exact run may supply a PR-number hint when the association is empty.
   Never download executable content from the gate. Enforce one JSON file, a 4 KiB limit,
   exact keys and integer/string types; reject archive paths, links and extra entries.
3. Resolve exactly one open PR against the expected base repository and branch. Verify
   numeric repository IDs, head repository ID and head SHA against authoritative run/PR
   data. Do not confuse a PR merge SHA with the head SHA: test both event shapes against
   GitHub fixtures. Ambiguous or missing provenance stops before any model call.
4. Freeze the head SHA, current base SHA, diff merge-base SHA and trusted policy SHA. Fetch
   all code by these SHAs. Recheck PR head and base after collection; if either changed,
   discard and request a fresh run. Do not mix a live `gh pr diff` with frozen files.
5. Recheck `AGENTS_ENABLED`, `REVIEW_LIVE`, draft state, closed state, author/actor bot
   policy and `no-agent-review`. These checks live in trusted code, not only in the gate.

The manifest records schema version, repository IDs, PR number, source run ID/attempt,
head/base/merge-base/policy SHAs, workflow SHA, bundle digest, file hashes and coverage.
A digest detects a mismatch; it does not authenticate an untrusted producer. Only the
trusted collector may create the manifest used for review and publication.

## Admission, repeats and cost

For the first version, every fork revision needs a maintainer admission of its exact head
and base SHAs through a default-branch `workflow_dispatch`. Check the initiating user's
current write/maintain/admin permission through the API. A label, `author_association`,
an earlier merge or GitHub's approval of the gate is not admission to spend model credits.
New commits invalidate admission. Internal PRs use the same validation without that step.
No comment command or `pull_request_target` path is added.

Use one repository-wide review concurrency group with `cancel-in-progress: false` for the
first version, so admission, accounting and publication cannot race across PRs. Revalidate
when a queued run starts; GitHub concurrency is not a durable FIFO queue. A replaced pending
run can be retried by the maintainer. Never cancel an active writer halfway through a post.

Keep the caller's current cap of 20 review attempts per UTC day (reusable default: 10),
timeouts and model-call limits. Count all eligible trusted attempts, including failures,
reruns and cancelled runs that may have spent credits. Paginate the run/attempt list;
API or accounting failure stops admission. Do not subtract cancelled work as free.
Use `(repository ID, PR, head SHA, base SHA, workflow SHA)` as the review identity. Before
spending, skip a completed identity; retries of failed work still count against the cap.
Explicit maintainer retries use the same limits. Budget alerts alone are not a hard cap.

## Keep source context without loading PR settings

Do not replace full review with a diff-only prompt. Build a read-only virtual source store
from Git blobs: full changed files on both sides, the full text diff, the tree index, and
unchanged text files needed to trace callers, imports and tests. Preserve logical paths and
line numbers. Both reviewers receive the same store and can read/search related files.

Store blobs under generated IDs outside the agent's working directory. A trusted mapping
resolves logical paths. The read/search tools accept only manifest entries and bounded
ranges; they cannot accept arbitrary paths, URLs or commands. Policy comes from the frozen
trusted base, and prompts/plugins from the pinned SDLC commit. A proposed policy edit is
still visible as review data. No PR file becomes an agent's settings or instructions.

Reject absolute paths, traversal, NUL/control characters and ambiguous normalization.
Never materialize symlinks, hardlinks, executable modes or device entries. Show link targets
and submodule changes as text metadata. Treat `.claude`, `.codex`, `.agents`, instruction
files and config as ordinary inert data. Do not run archive extraction or package installs
on the PR tree. Fixed GitHub API origins only; never forward authorization on redirects to
another host or fetch a URL supplied by the PR.

Keep the existing 300,000-byte diff limit initially. Set and test separate bounds for tree
entries, per-file bytes, total source bytes and tool responses before rollout. Record every
omission, binary, missing blob, API truncation and exhausted context budget. If required
context cannot be read, report `incomplete`, not an empty clean review. No silent clipping.

## Model isolation is a release gate

Read-only filesystem access is not a confidentiality boundary. Tool allowlists and prompts
alone do not prevent secret reads or prompt injection. Existing Claude/Codex actions must
prove the following properties at their pinned versions before they are reused for forks:

- The model and every tool subprocess see only the source store, trusted prompts and an
  empty temporary home. They cannot read host environment, credentials, `.git`, `/proc`,
  other jobs, sibling directories or runner service tokens.
- Authentication stays in a trusted broker outside that sandbox. The broker accepts only
  model inference for the fixed provider/account, not arbitrary URLs or proxy requests.
- Disable automatic project instructions, hooks, MCP, plugins from the PR, shell, package
  execution, web tools and telemetry. Trusted read/search tools are the only source access.
- Deny network from tool execution. Restrict broker/setup traffic to explicit destinations;
  Harden-Runner audit mode does not enforce this. Test blocked egress, not just a config flag.
- Validate and scan outputs before any public artifact or log upload. Raw model responses,
  debug logs and rejected text never become public artifacts. Retention is not prevention.

If a current action cannot meet these boundaries, keep forks disabled and implement a small
trusted inference runner with the confined read/search interface. Do not silently switch
Claude from the Max subscription to a paid API. Record the authentication/cost decision and
rerun quality evals first. The final runner and endpoint allowlist remain implementation
decisions, backed by tests rather than assumed from CLI flags.

## Publish only validated data

The publisher checks expected artifact names and producer jobs from this trusted run, with
bounded sizes and exact schemas. No model output controls PR number, commit, repository,
artifact location, token permissions or commands. Validate finding paths and line ranges
against the manifest. Escape rendered text and suppress unwanted mentions and remote images.
Do not shell-evaluate output. Scan before upload as well as before posting; scanners are
defence in depth, not the protection for secrets.

Immediately before writing, fetch the PR again and recheck SHAs, state and switches. Stale
results never replace the comment for a newer revision. Render the reviewed head/base SHAs
and per-reviewer status in the comment. A push can race the final API call: serialize our
publishers, recheck after writing and mark our comment stale if needed. GitHub comment writes
are not a transaction against the PR head. Never describe that race as impossible.

Keep the existing single-comment update, deduplication and finding history. Bind the marker
to a verified bot author and repository/PR; an author's copied marker is not our comment.
Preserve history without implying that a finding omitted by a reviewer is fixed.

| Outcome | User sees |
|---|---|
| Both complete | results and exact revision from both reviewers |
| One fails | other findings plus the named failed reviewer; partial coverage |
| Both fail or required context missing | review unavailable or incomplete; never “No problems found” |
| Not admitted, capped, draft or opted out | explicit reason in run summary; no stale clean result presented as current |
| Stale revision | discarded result with reviewed SHA and reason in run summary |
| Invalid provenance or unsafe output | failed infrastructure check, no raw output posted |

## Prove quality and safety before switching

Run all 42 current eval tasks on both old and proposed paths, using identical models,
effort, prompts and limits; repeat three times. Add cross-file, deletion, rename, policy
change, large-context and partial-failure cases. Publish per-task results, defect recall,
false findings on clean cases, injection compliance, completion rate, time and tokens.
The owner checks disagreements blind to the runner. No aggregate recall reduction or
increase in false findings, no new miss on a known real bug without resolution, no lower
completion rate and zero observed injection compliance are the initial acceptance gates.
These are measured release criteria, not a promise that every future review is correct.

Hostile tests use dummy canary secrets only: forged run/PR metadata; empty PR associations;
replayed artifacts; wrong attempts; push/base-change races; malicious settings/hooks;
symlinks/traversal; shell syntax in filenames/title; archive bombs; binary/oversized content;
requests to read environment/home/proc; arbitrary outbound requests; output exfiltration;
copied bot markers; duplicate runs; both model failures; disabled switches while queued.
Pass means no canary in output, artifacts, logs or network captures, no unauthorized call,
no execution of PR content and no wrong-revision publication. A sandbox failure blocks
rollout regardless of the model's answer.

## Sources checked 2026-11-14

- [GitHub workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run): default-branch receiver and privileged execution.
- [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use): untrusted code and artifacts at privilege boundaries.
- [GitHub on pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target): PR workflows are untrusted; artifact contents remain untrusted.
- [GitHub announced default blocking on December 2](https://github.blog/changelog/2026-11-02-pull_request_target-blocked-by-default-december-2/): this design does not require that event. The architecture does not depend on the announced date.
