import yaml

from check_agent_workflows import check_workflow, is_agent_workflow, main

SHA = "0123456789abcdef0123456789abcdef01234567"
REVIEW = "KonstantinStarovoytov/kitden-sdlc/.github/workflows/review-claude.yml"
CHECK = "KonstantinStarovoytov/kitden-sdlc/.github/workflows/check.yml"
SWITCH = (
    "vars.AGENTS_ENABLED == 'true'"
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
      - uses: anthropics/claude-code-action@SHA
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
    text = CLEAN_CALLER.replace("review-claude.yml@SHA", "review-claude.yml@main")
    assert any("rule 4" in v for v in run(text))


def test_local_action_is_allowed():
    text = CLEAN_MODEL.replace(
        "    steps:\n",
        "    steps:\n      - uses: ./.github/actions/post\n",
    )
    assert run(text) == []


def test_marketplace_without_ref_is_rule_4():
    text = CLEAN_MODEL.replace(
        "        with:\n",
        "        with:\n          plugin_marketplaces: https://example.com/m.git\n",
    )
    assert any("rule 4" in v for v in run(text))


def test_marketplace_with_tag_passes():
    text = CLEAN_MODEL.replace(
        "        with:\n",
        "        with:\n          plugin_marketplaces: https://example.com/m.git#v1.2.0\n",
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
