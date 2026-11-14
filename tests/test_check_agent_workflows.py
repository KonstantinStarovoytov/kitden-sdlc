from pathlib import Path

import yaml

from check_agent_workflows import (
    _in_release_environment,
    check_workflow,
    is_agent_workflow,
    main,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
REVIEW = "KonstantinStarovoytov/kitden-sdlc/.github/workflows/review.yml"
CHECK = "KonstantinStarovoytov/kitden-sdlc/.github/workflows/check.yml"
SWITCH = (
    "vars.AGENTS_ENABLED == 'true'"
    " && vars.REVIEW_LIVE == 'true'"
    " && github.event.pull_request.head.repo.full_name == github.repository"
    " && !endsWith(github.actor, '[bot]')"
)


def run(text: str) -> list[str]:
    doc = yaml.safe_load(text.replace("SHA", SHA).replace("SWITCH", SWITCH))
    return check_workflow(doc, "wf.yml")


CLEAN_CALLER = f"""
on:
  pull_request:
permissions: {{}}
concurrency:
  group: review-${{{{ github.event.pull_request.number }}}}
  cancel-in-progress: true
jobs:
  review:
    if: SWITCH
    permissions:
      contents: read
    uses: {REVIEW}@SHA
"""

HOSTS_STEP = (
    "      - uses: step-security/harden-runner@SHA\n"
    "        with:\n"
    "          egress-policy: audit\n"
)

CLEAN_MODEL = """
on:
  pull_request:
permissions: {}
concurrency:
  group: review
  cancel-in-progress: true
jobs:
  review:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
    steps:
""" + HOSTS_STEP + """      - uses: anthropics/claude-code-action@SHA
        with:
          claude_args: --max-turns 5
"""


def test_clean_caller_passes():
    assert run(CLEAN_CALLER) == []


def test_clean_model_job_passes():
    assert run(CLEAN_MODEL) == []


def test_pull_request_target_is_rule_2():
    text = CLEAN_CALLER.replace("  pull_request:", "  pull_request_target:")
    violations = run(text)
    assert any("rule 2" in v for v in violations)


def test_caller_without_switch_is_rule_2():
    text = CLEAN_CALLER.replace("    if: SWITCH\n", "")
    violations = run(text)
    assert any("wf.yml: rule 2" in v for v in violations)


def test_caller_with_partial_switch_is_rule_2():
    text = CLEAN_CALLER.replace("if: SWITCH", "if: vars.AGENTS_ENABLED == 'true'")
    assert any("rule 2" in v for v in run(text))


def test_review_caller_without_review_live_is_rule_2():
    text = CLEAN_CALLER.replace("SWITCH", SWITCH.replace(" && vars.REVIEW_LIVE == 'true'", ""))
    assert any("rule 2" in v and "REVIEW_LIVE" in v for v in run(text))


def test_caller_with_extra_condition_passes():
    text = CLEAN_CALLER.replace("if: SWITCH", "if: SWITCH && github.event.action != 'closed'")
    assert run(text) == []


def test_missing_top_permissions_is_rule_3():
    text = CLEAN_CALLER.replace("permissions: {}\n", "")
    assert any("rule 3" in v for v in run(text))


def test_job_without_permissions_is_rule_3():
    text = CLEAN_CALLER.replace("    permissions:\n      contents: read\n", "")
    assert any("rule 3" in v for v in run(text))


def test_tag_pinned_action_is_rule_4():
    text = CLEAN_MODEL.replace("claude-code-action@SHA", "claude-code-action@v1")
    assert any("rule 4" in v for v in run(text))


def test_tag_pinned_caller_is_rule_4():
    text = CLEAN_CALLER.replace("review.yml@SHA", "review.yml@v1")
    assert any("rule 4" in v for v in run(text))


def test_own_workflow_at_main_is_allowed():
    text = CLEAN_CALLER.replace("review.yml@SHA", "review.yml@main")
    assert run(text) == []


def test_other_repo_at_main_is_rule_4():
    text = CLEAN_CALLER.replace("review.yml@SHA", "review.yml@main").replace(
        "KonstantinStarovoytov/kitden-sdlc", "someone/else"
    )
    assert any("rule 4" in v for v in run(text))


def test_local_action_is_allowed():
    text = CLEAN_MODEL.replace(
        HOSTS_STEP, HOSTS_STEP + "      - uses: ./.github/actions/post\n"
    )
    assert run(text) == []


def test_marketplace_without_ref_is_rule_4():
    text = CLEAN_MODEL.replace(
        "          claude_args: --max-turns 5\n",
        "          claude_args: --max-turns 5\n          plugin_marketplaces: https://example.com/m.git\n",
    )
    assert any("rule 4" in v for v in run(text))


def test_marketplace_with_tag_passes():
    text = CLEAN_MODEL.replace(
        "          claude_args: --max-turns 5\n",
        "          claude_args: --max-turns 5\n          plugin_marketplaces: https://example.com/m.git#v1.2.0\n",
    )
    assert run(text) == []


def test_model_job_without_timeout_is_rule_5():
    text = CLEAN_MODEL.replace("    timeout-minutes: 10\n", "")
    assert any("rule 5" in v for v in run(text))


def test_claude_step_without_max_turns_is_rule_5():
    text = CLEAN_MODEL.replace("--max-turns 5", "--model sonnet")
    assert any("rule 5" in v for v in run(text))


def test_pull_request_without_concurrency_is_rule_5():
    text = CLEAN_CALLER.replace(
        "concurrency:\n  group: review-${{ github.event.pull_request.number }}\n"
        "  cancel-in-progress: true\n",
        "",
    )
    assert any("rule 5" in v for v in run(text))


def test_concurrency_without_cancel_is_rule_5():
    text = CLEAN_CALLER.replace("cancel-in-progress: true", "cancel-in-progress: false")
    assert any("rule 5" in v for v in run(text))


def test_job_level_concurrency_passes():
    text = CLEAN_MODEL.replace(
        "concurrency:\n  group: review\n  cancel-in-progress: true\n", ""
    ).replace(
        "    timeout-minutes: 10\n",
        "    timeout-minutes: 10\n"
        "    concurrency:\n      group: r\n      cancel-in-progress: true\n",
    )
    assert run(text) == []


def test_check_caller_is_not_an_agent_workflow():
    text = f"""
on:
  pull_request:
permissions: {{}}
jobs:
  check:
    permissions:
      contents: read
    uses: {CHECK}@SHA
"""
    assert run(text) == []


def test_non_agent_workflow_is_ignored():
    text = """
on: [push, pull_request_target]
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
    assert run(text) == []


def test_is_agent_workflow():
    assert is_agent_workflow(yaml.safe_load(CLEAN_MODEL.replace("SHA", SHA)))
    assert is_agent_workflow(yaml.safe_load(CLEAN_CALLER.replace("SHA", SHA)))
    assert not is_agent_workflow({"jobs": {"a": {"steps": [{"run": "x"}]}}})


def test_main_reports_and_returns_1(tmp_path, capsys):
    text = CLEAN_CALLER.replace("    if: SWITCH\n", "").replace("SHA", SHA)
    (tmp_path / "bad.yml").write_text(text)
    assert main([str(tmp_path)]) == 1
    assert "rule 2" in capsys.readouterr().out


def test_main_returns_0_when_clean(tmp_path):
    (tmp_path / "ok.yml").write_text(CLEAN_CALLER.replace("SWITCH", SWITCH).replace("SHA", SHA))
    assert main([str(tmp_path)]) == 0


CLEAN_SCHEDULED = """
on:
  schedule:
    - cron: "17 5 * * *"
  workflow_dispatch:
permissions: {}
concurrency:
  group: watch
  cancel-in-progress: false
jobs:
  fetch:
    if: vars.AGENTS_ENABLED == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@SHA
  judge:
    needs: fetch
    if: vars.AGENTS_ENABLED == 'true' && needs.fetch.outputs.pieces != '0'
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
    steps:
""" + HOSTS_STEP + """      - name: Judge
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          MAX_MODEL_CALLS: "60"
        run: python scripts/watch_judge.py
  post:
    needs: [fetch, judge]
    if: vars.AGENTS_ENABLED == 'true' && !cancelled()
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: write
    steps:
      - run: python scripts/watch_post.py
"""


def test_clean_scheduled_script_agent_passes():
    assert run(CLEAN_SCHEDULED) == []


def test_scheduled_jobs_with_both_switches_pass():
    both = "vars.AGENTS_ENABLED == 'true' && vars.WATCH_LIVE == 'true'"
    text = CLEAN_SCHEDULED.replace("vars.AGENTS_ENABLED == 'true'", both)
    assert run(text) == []


def test_script_agent_is_an_agent_workflow():
    assert is_agent_workflow(yaml.safe_load(CLEAN_SCHEDULED.replace("SHA", SHA)))


def test_script_agent_with_write_is_rule_1():
    text = CLEAN_SCHEDULED.replace(
        "      contents: read\n    steps:\n" + HOSTS_STEP + "      - name: Judge",
        "      contents: write\n    steps:\n" + HOSTS_STEP + "      - name: Judge",
    )
    assert any("rule 1" in v for v in run(text))


def test_script_agent_on_push_is_rule_2():
    text = CLEAN_SCHEDULED.replace("  workflow_dispatch:\n", "  workflow_dispatch:\n  push:\n")
    assert any("rule 2" in v for v in run(text))


def test_script_agent_workflow_job_without_switch_is_rule_2():
    text = CLEAN_SCHEDULED.replace(
        "    if: vars.AGENTS_ENABLED == 'true' && !cancelled()\n", "    if: ${{ !cancelled() }}\n"
    )
    assert any("rule 2" in v for v in run(text))


def test_script_agent_without_max_model_calls_is_rule_5():
    text = CLEAN_SCHEDULED.replace('          MAX_MODEL_CALLS: "60"\n', "")
    assert any("rule 5" in v for v in run(text))


def test_script_agent_without_timeout_is_rule_5():
    text = CLEAN_SCHEDULED.replace(
        "    timeout-minutes: 15\n    permissions:\n      contents: read\n    steps:\n"
        + HOSTS_STEP,
        "    permissions:\n      contents: read\n    steps:\n" + HOSTS_STEP,
    )
    assert any("rule 5" in v for v in run(text))


def test_script_agent_without_concurrency_is_rule_5():
    text = CLEAN_SCHEDULED.replace(
        "concurrency:\n  group: watch\n  cancel-in-progress: false\n", ""
    )
    assert any("rule 5" in v for v in run(text))


def test_model_secret_in_with_makes_a_script_agent():
    text = CLEAN_SCHEDULED.replace(
        "      - run: python scripts/watch_post.py\n",
        "      - uses: some/action@SHA\n        with:\n"
        "          key: ${{ secrets.ANTHROPIC_API_KEY }}\n",
    )
    assert any("rule 1" in v for v in run(text))


RELEASE_JOB = """
on:
  push:
    tags: ["v*"]
permissions: {}
jobs:
  publish:
    runs-on: ubuntu-latest
    environment: release
    permissions: {}
    steps:
      - run: echo publish
"""

ROOT = Path(__file__).resolve().parent.parent


def test_release_environment_only_without_model_and_on_main_or_tag():
    assert run(RELEASE_JOB) == []

    model = RELEASE_JOB.replace(
        "      - run: echo publish\n", "      - uses: anthropics/claude-code-action@SHA\n"
    )
    assert "wf.yml: rule 1: job publish holds the release environment and runs a model" in run(
        model
    )

    script = RELEASE_JOB.replace(
        "      - run: echo publish\n",
        "      - run: echo publish\n        env:\n"
        "          KEY: ${{ secrets.OPENAI_API_KEY }}\n",
    )
    assert any("holds the release environment and runs a model" in v for v in run(script))

    mapping = model.replace("environment: release", "environment:\n      name: release")
    assert any("holds the release environment and runs a model" in v for v in run(mapping))

    for event in ("pull_request_target", "issue_comment"):
        text = RELEASE_JOB.replace('  push:\n    tags: ["v*"]', f"  {event}:")
        assert f"wf.yml: rule 1: job publish holds the release environment on {event}" in run(
            text
        )

    for name in (".github/workflows/publish.yml", "examples/release.yml"):
        doc = yaml.safe_load((ROOT / name).read_text())
        assert check_workflow(doc, name) == []
        assert any(_in_release_environment(job) for job in doc["jobs"].values()), name


RUNS_MODEL = "holds the release environment and runs a model"


def _flagged(text: str) -> bool:
    return any(RUNS_MODEL in v for v in run(text))


def test_release_job_with_model_secret_in_job_env_fails():
    text = RELEASE_JOB.replace(
        "    environment: release\n",
        "    environment: release\n    env:\n      K: ${{ secrets.ANTHROPIC_API_KEY }}\n",
    )
    assert _flagged(text)


def test_release_job_with_model_secret_in_call_secrets_fails():
    text = RELEASE_JOB.replace(
        "    runs-on: ubuntu-latest\n    environment: release\n",
        "    environment: release\n    uses: o/r/.github/workflows/x.yml@SHA\n"
        "    secrets:\n      k: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}\n",
    ).replace("    steps:\n      - run: echo publish\n", "")
    assert _flagged(text)


def test_release_job_with_model_secret_in_run_fails():
    text = RELEASE_JOB.replace("echo publish", "curl -H ${{ secrets.OPENAI_API_KEY }} x")
    assert _flagged(text)


def test_expression_environment_with_model_step_fails():
    text = RELEASE_JOB.replace(
        "environment: release", "environment: ${{ inputs.env }}"
    ).replace("      - run: echo publish\n", "      - uses: openai/codex-action@SHA\n")
    assert _flagged(text)


def test_capitalised_release_environment_with_model_step_fails():
    text = RELEASE_JOB.replace("environment: release", "environment: Release").replace(
        "      - run: echo publish\n", "      - uses: anthropics/claude-code-action@SHA\n"
    )
    assert _flagged(text)


def test_full_output_inputs_are_rule_10():
    for name in ("show_full_output", "display_report"):
        text = CLEAN_MODEL.replace(
            "claude_args: --max-turns 5", f"claude_args: --max-turns 5\n          {name}: true"
        )
        assert any("rule 10" in v and name in v for v in run(text))
        assert run(text.replace(f"{name}: true", f'{name}: "false"')) == []


def test_debug_flag_in_the_arguments_is_rule_10():
    for flag in ("--debug", "--verbose", "--mcp-debug"):
        text = CLEAN_MODEL.replace("--max-turns 5", f"--max-turns 5 {flag}")
        assert any("rule 10" in v for v in run(text))


def _with_args(args: str, codex: bool = False) -> str:
    """CLEAN_MODEL with the model step's arguments written as `args` (YAML, after the key)."""
    if codex:
        step = CLEAN_MODEL.replace("anthropics/claude-code-action", "openai/codex-action")
        return step.replace("claude_args: --max-turns 5", f"codex-args: {args}")
    return CLEAN_MODEL.replace("claude_args: --max-turns 5", f"claude_args: {args}")


def test_a_debug_flag_is_found_in_every_form():
    forms = [
        """'["-c", "x=1", "--debug"]'""",  # a JSON list in a string, as review.yml writes it
        """'--max-turns 5 "--debug"'""",  # a quoted word
        """\n            - --max-turns\n            - "5"\n            - --debug""",  # a YAML list
        "--max-turns 5 --debug=1",  # with a value
    ]
    for args in forms:
        found = [v for v in run(_with_args(args)) if "rule 10" in v]
        assert found and "--debug" in found[0], args
    codex = _with_args("""'["--verbose"]'""", codex=True)
    assert any("rule 10" in v and "codex-args has --verbose" in v for v in run(codex))


def test_a_flag_that_only_starts_like_a_debug_flag_passes():
    assert run(_with_args("--max-turns 5 --debugger --verbosely")) == []
    assert run(_with_args("""'["--max-turns", "5", "--debug-file-free"]'""")) == []


def test_debug_env_is_rule_10_at_every_level():
    top = CLEAN_SCHEDULED.replace(
        "permissions: {}", 'permissions: {}\nenv:\n  RUNNER_DEBUG: "1"', 1
    )
    job = CLEAN_SCHEDULED.replace(
        "    needs: fetch\n", '    needs: fetch\n    env:\n      ACTIONS_STEP_DEBUG: "true"\n'
    )
    step = CLEAN_SCHEDULED.replace(
        '          MAX_MODEL_CALLS: "60"',
        '          MAX_MODEL_CALLS: "60"\n          ANTHROPIC_LOG: debug',
    )
    for text in (top, job, step):
        assert any("rule 10" in v for v in run(text))


def test_model_job_without_the_hosts_step_is_rule_9():
    text = CLEAN_MODEL.replace(HOSTS_STEP, "")
    assert any("rule 9" in v and "review" in v for v in run(text))


def test_hosts_step_must_come_first_and_name_a_policy():
    moved = CLEAN_MODEL.replace(HOSTS_STEP, "      - run: echo first\n" + HOSTS_STEP)
    assert any("rule 9" in v for v in run(moved))
    unnamed = CLEAN_MODEL.replace("        with:\n          egress-policy: audit\n", "", 1)
    assert any("rule 9" in v for v in run(unnamed))


def test_script_agent_job_needs_the_hosts_step_and_other_jobs_do_not():
    text = CLEAN_SCHEDULED.replace(HOSTS_STEP, "")
    found = [v for v in run(text) if "rule 9" in v]
    assert len(found) == 1 and "judge" in found[0]
