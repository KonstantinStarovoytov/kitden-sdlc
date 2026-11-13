from pathlib import Path

import yaml

from check_agent_workflows import HOSTS_ACTION, _is_model_step, check_workflow

ROOT = Path(__file__).resolve().parent.parent


def test_a_failed_reviewer_leaves_no_red_mark():
    doc = yaml.safe_load((ROOT / ".github/workflows/review.yml").read_text())
    for name in ("claude", "luna"):
        steps = [s for s in doc["jobs"][name]["steps"] if _is_model_step(s)]
        assert len(steps) == 1 and steps[0].get("continue-on-error") is True
        all_steps = doc["jobs"][name]["steps"]
        assert any("outcome == 'failure'" in str(s.get("if", "")) for s in all_steps)


def test_every_model_job_in_release_prep_starts_with_the_same_hosts_step():
    doc = yaml.safe_load((ROOT / ".github/workflows/release-prep.yml").read_text())
    model_jobs = [j for j in doc["jobs"].values() if any(_is_model_step(s) for s in j["steps"])]
    assert len(model_jobs) == 2  # agent and fix
    firsts = [job["steps"][0] for job in model_jobs]
    for first in firsts:
        assert first["uses"].startswith(HOSTS_ACTION + "@")
        assert first["with"] == {"egress-policy": "audit"}
    assert firsts[0] == firsts[1]


def test_every_workflow_and_caller_passes_the_checker():
    files = [*(ROOT / ".github/workflows").glob("*.yml"), *(ROOT / "examples").glob("*.yml")]
    assert files
    for file in files:
        assert check_workflow(yaml.safe_load(file.read_text()), file.name) == [], file.name
