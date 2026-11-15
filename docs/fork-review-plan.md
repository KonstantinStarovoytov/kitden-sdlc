# Fork review rollout

Status: planned, not enabled. Date: 2026-11-14.
Contract: [fork-review-design.md](fork-review-design.md). No runtime changes in this design PR.

## Implementation order

1. **Trusted collector and admission.** Add `scripts/review_request.py` and its manifest
   schema, immutable blob collection and confined read/search interface. Add negative tests
   for provenance, paths, truncation, accounting and revision races. Keep existing review live.
2. **Runner boundary.** Test pinned Claude/Codex actions with dummy secrets. If isolation
   cannot be demonstrated, build the broker/runner described in the design. Record the
   exact endpoints, versions, limits and authentication choice. No real secrets in attack tests.
3. **Result contract.** Extend `scripts/post_findings.py`, schemas and tests for trusted
   identity, completion/coverage, safe rendering, stale results and artifact validation.
   Preserve history and one-comment behaviour. Filter before upload, not only before posting.
4. **Workflows and rules together.** Replace `prepare_review.sh`'s checkout assumption.
   Update `.github/workflows/review.yml`, add gate/receiver callers to `examples/`, and
   update `scripts/check_agent_workflows.py` and its tests. Keep the new path disabled.
   Rule 2 gets a narrow validated `workflow_run`/maintainer-dispatch exception; rule 4
   requires full-SHA review pins; rules 6 and 9 must describe enforced isolation.
5. **Measure.** Extend `evals/run.py` to exercise the actual collector and runner, not an
   imitation. Run the paired 42-task baseline and added context/security cases three times.
   Save before/after tables and inspect disagreements. Retain model, effort and prompts.
6. **Kitden canary.** Add the secret-free `agents-review-gate.yml` and trusted receiver in
   `.github/workflows/agents-review.yml`, pinned to the reviewed SDLC commit. The new
   reusable interface takes only a source run ID/attempt or admitted PR/head/base identity;
   trusted code validates them. No caller-provided checkout path or source URL.
7. **Enable after evidence.** Exercise a maintainer-controlled fork PR and an internal PR,
   update each during review, retry, opt out and force each reviewer to fail. Confirm the
   exact comment revision, statuses, cap and absence of secret exposure. Switch the single
   production path only after all gates pass; remove the old direct caller then.

Each workflow PR must run the local `agentic-actions-auditor`, the repository rule checker,
actionlint and zizmor. Run all checks required by each repository's AGENTS.md before commits.
Do not mark safety, quality, live tests or publishing as passed without recorded evidence.

## Documentation in the activation PRs

| Repository | Update together |
|---|---|
| kitden-sdlc | README, RULES, ROADMAP, LOG, decisions, agents, owner, setup, original design/plan pointers, eval guide, examples, GitHub Pages map and its README screenshots |
| kitden | AI_POLICY, CONTRIBUTING, development guide, SECURITY, ROADMAP and review callers; README links to the policy |

The Pages map must distinguish the running path from the proposal. Its current workflow
nodes and screenshots must not claim that the future gate already runs. At activation,
update the actual workflow nodes and regenerate both-theme screenshots with the repository
script; check narrow screens, keyboard navigation and reduced motion. Do not rewrite
historical release notes or unrelated product/client documentation.

## Acceptance record

| Evidence | State |
|---|---|
| Design and current implementation compared | documented |
| Provenance and hostile-data test suite | not built |
| Credential isolation and blocked-egress evidence | not run |
| Paired quality tables, three repetitions | not run |
| Canary fork and internal PR, stale/failed/retry cases | not run |
| Runtime activation and Pages deployment | not done |

## Rollback

Set `REVIEW_LIVE=false`; use `AGENTS_ENABLED=false` to stop all agents. Trusted jobs recheck
the switches before calls and publication. Cancel active model runs, inspect outputs and
rotate affected credentials if exposure is suspected. Restore the previous pinned caller
for internal PRs only after inspection; forks remain manual. Do not restore a live `@main`
review reference or bypass provenance checks to make a failed review green. Record the
failed case as a regression test and in LOG before another canary.
