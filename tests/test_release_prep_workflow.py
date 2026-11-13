"""release-prep.yml: the jobs, what each may hold, and the order they wait for each other."""

import re
from pathlib import Path

import yaml

from release_verify import DOCS_TESTS_DEFAULT

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / ".github" / "workflows" / "release-prep.yml").read_text()
doc = yaml.safe_load(TEXT)
JOBS = ["guard", "prepare", "agent", "bump", "check", "fix", "record", "final-check", "open-pr"]


def model_step(job: dict) -> dict:
    steps = [s for s in job["steps"] if "claude-code-action" in s.get("uses", "")]
    assert len(steps) == 1
    return steps[0]


def args(step: dict) -> str:
    return " ".join(step["with"]["claude_args"].split())


def tools(step: dict) -> list[str]:
    found = re.findall(r'--(?:allowed|disallowed)Tools "[^"]*"', args(step))
    assert len(found) == 2
    return found


def run_text(job: dict) -> str:
    return "\n".join(s.get("run", "") for s in job["steps"])


def test_the_jobs_are_these():
    assert list(doc["jobs"]) == JOBS


def test_jobs_that_run_kitdens_code_hold_no_secret():
    for name in ("check", "final-check", "record"):
        job = doc["jobs"][name]
        assert job["permissions"] == {"contents": "read"}
        assert "secrets." not in yaml.safe_dump(job)
        assert "environment" not in job


def test_kitdens_code_runs_with_no_token_in_the_environment():
    for name in ("check", "final-check"):
        for step in doc["jobs"][name]["steps"]:
            assert "GH_TOKEN" not in step.get("env", {})
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False


def test_the_fix_pass_has_the_first_pass_tools_and_its_own_limits():
    agent, fix = (model_step(doc["jobs"][n]) for n in ("agent", "fix"))
    assert tools(agent) == tools(fix)
    assert agent["uses"] == fix["uses"]
    assert doc["jobs"]["fix"]["timeout-minutes"] == 10
    assert "--max-turns 15" in args(fix)
    assert "needs.check.outputs.problems == 'true'" in doc["jobs"]["fix"]["if"]
    assert "vars.AGENTS_ENABLED == 'true'" in doc["jobs"]["fix"]["if"]
    assert doc["jobs"]["fix"]["permissions"] == {"contents": "read"}


def test_only_the_two_agent_jobs_run_a_model():
    with_model = [n for n, j in doc["jobs"].items() if "claude-code-action" in str(j)]
    assert with_model == ["agent", "fix"]


def test_the_last_jobs_run_when_the_fix_pass_did_not():
    for name in ("final-check", "open-pr"):
        assert "!cancelled()" in doc["jobs"][name]["if"]
    assert "needs.final-check.result == 'success'" in doc["jobs"]["open-pr"]["if"]


def test_open_pr_runs_no_model_and_no_release_check():
    job = doc["jobs"]["open-pr"]
    assert "claude-code-action" not in str(job)
    assert "release_check.py" not in run_text(job)


def test_history_is_whole_where_stale_is_judged():
    for name in ("final-check", "open-pr"):
        checkouts = [
            s
            for s in doc["jobs"][name]["steps"]
            if s.get("with", {}).get("path") == "kitden"
        ]
        assert checkouts[0]["with"]["fetch-depth"] == 0


def test_record_does_not_wait_for_the_agents_list():
    job = doc["jobs"]["record"]
    assert "scenes != ''" not in job["if"]
    assert job["needs"] == ["guard", "bump"]


def test_docs_tests_has_the_default():
    spec = doc[True]["workflow_call"]["inputs"]["docs_tests"]  # `on` loads as True
    assert spec["default"] == DOCS_TESTS_DEFAULT
    assert "\n" not in spec["default"]


def test_docs_tests_is_checked_before_the_prompt_uses_it():
    prepare = doc["jobs"]["prepare"]
    assert prepare["outputs"]["docs_tests"]
    assert "release_verify.py" in run_text(prepare)
    assert "${{ inputs.docs_tests }}" not in run_text(prepare)
    prompt = model_step(doc["jobs"]["agent"])["with"]["prompt"]
    assert "${{ needs.prepare.outputs.docs_tests }}" in prompt


def test_no_run_step_has_an_expression_in_it():
    for name, job in doc["jobs"].items():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), (name, step.get("name"))


def test_the_branch_is_looked_for_in_prepare_bump_and_open_pr():
    for name in ("prepare", "bump", "open-pr"):
        assert 'branches/$branch" --silent' in run_text(doc["jobs"][name]), name


def test_the_artifacts_have_these_names():
    names = set(re.findall(r"name: (release-[a-z-]+)\n", TEXT))
    assert names == {
        "release-context",
        "release-out",
        "release-verdict-first",
        "release-out-fixed",
        "release-fix",
        "release-images",
        "release-verdict",
    }


def test_every_job_that_runs_uv_sets_uv_up_first():
    for name, job in doc["jobs"].items():
        steps = job["steps"]
        for index, step in enumerate(steps):
            if re.search(r"\buv ", step.get("run", "")):
                before = [s.get("uses", "") for s in steps[:index]]
                assert any(u.startswith("astral-sh/setup-uv@") for u in before), name


def test_record_installs_the_recorders_tools_before_it_prints_them():
    steps = doc["jobs"]["record"]["steps"]
    names = [s.get("name", "") for s in steps]
    install = names.index("Install the recorder's tools")
    assert steps[install]["run"].strip() == "brew install ffmpeg webp"
    assert install < names.index("Which tools the runner has") < names.index("Record the scenes")


def test_the_body_step_says_how_the_fix_pass_ended():
    step = next(s for s in doc["jobs"]["open-pr"]["steps"] if s.get("id") == "body")
    assert step["env"]["FIX_RESULT"] == "${{ needs.fix.result }}"
    run = step["run"]
    assert '--fix-result "$FIX_RESULT"' in run
    assert run.count("--fixed") == 1
    assert 'if [ "$FIX_RESULT" = success ]; then fixed=(--fixed' in run
    # The pictures come from this job's own apply step, not from an artifact.
    assert '--pictures "$RUNNER_TEMP/lists/pictures.json"' in run
    assert "verdict/pictures.json" not in run


def test_final_check_and_open_pr_choose_the_output_by_the_fix_result():
    for name in ("final-check", "open-pr"):
        steps = doc["jobs"][name]["steps"]
        by_artifact = {
            s["with"]["name"]: s
            for s in steps
            if s.get("uses", "").startswith("actions/download-artifact@")
        }
        assert by_artifact["release-out-fixed"]["if"] == "needs.fix.result == 'success'"
        assert by_artifact["release-out"]["if"] == "needs.fix.result != 'success'"


def test_open_pr_can_open_a_draft():
    run = run_text(doc["jobs"]["open-pr"])
    assert 'if [ "$STATE" = draft ]; then draft=(--draft); fi' in run
    assert "gh pr create" in run and '"${draft[@]}"' in run


def test_the_fix_job_settles_the_files_and_keeps_them_after_that():
    steps = doc["jobs"]["fix"]["steps"]
    settle = next(i for i, s in enumerate(steps) if "release_fix.py settle" in s.get("run", ""))
    kept = {
        s["with"]["name"]: i
        for i, s in enumerate(steps)
        if s.get("uses", "").startswith("actions/upload-artifact@")
    }
    assert settle < kept["release-out-fixed"]
    assert settle < kept["release-fix"]


def test_the_branch_check_asks_for_the_exact_reference():
    # GitHub answers /branches/<old name> for a renamed branch with the new one (2026-11-13),
    # so a run stopped on a branch that was not there. /git/ref/heads/<name> does not redirect.
    assert "/branches/$branch" not in TEXT
    assert TEXT.count("git/ref/heads/$branch") == 3
