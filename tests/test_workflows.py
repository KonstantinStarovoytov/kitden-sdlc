from pathlib import Path

import yaml

from check_agent_workflows import HOSTS_ACTION, _is_model_step, check_workflow

ROOT = Path(__file__).resolve().parent.parent


def test_a_failed_reviewer_leaves_no_red_mark():
    doc = yaml.safe_load((ROOT / ".github/workflows/review.yml").read_text())
    for name in ("claude", "luna"):
        job = doc["jobs"][name]
        steps = [s for s in job["steps"] if _is_model_step(s)]
        assert len(steps) == 1 and steps[0].get("continue-on-error") is True
        # GitHub fails a job that hits its own timeout; a step that hits its timeout only
        # fails the step, which continue-on-error lets pass.
        assert 0 < steps[0]["timeout-minutes"] < job["timeout-minutes"]
        warning = f"steps.{steps[0]['id']}.outcome == 'failure'"
        assert any(str(s.get("if", "")).strip() == warning for s in job["steps"])


# Every release prep artifact that can hold text a model wrote: the agent's files, first and
# fixed, the list of fixed files, and the two verdicts, whose problems quote the agent's files
# and the test output on them. The context and the pictures hold none.
MODEL_TEXT_ARTIFACTS = {
    "release-out",
    "release-out-fixed",
    "release-fix",
    "release-verdict-first",
    "release-verdict",
}


def test_model_output_is_kept_for_one_day():
    # Anyone signed in to GitHub can download a public repository's artifacts, and these
    # are uploaded before any check of the model's text.
    wanted = {
        "review.yml": {"findings-claude", "findings-luna"},
        "release-prep.yml": MODEL_TEXT_ARTIFACTS,
    }
    for file, names in wanted.items():
        doc = yaml.safe_load((ROOT / ".github/workflows" / file).read_text())
        uploads = {
            step["with"]["name"]: step["with"]
            for job in doc["jobs"].values()
            for step in job.get("steps") or []
            if "actions/upload-artifact" in str(step.get("uses", ""))
        }
        for name in names:
            assert uploads[name].get("retention-days") == 1, name


def _uploads(doc: dict) -> dict[str, dict]:
    return {
        step["with"]["name"]: step["with"]
        for job in doc["jobs"].values()
        for step in job.get("steps") or []
        if "actions/upload-artifact" in str(step.get("uses", ""))
    }


def test_release_prep_keeps_only_the_models_text_for_one_day():
    # The context (people's pull request text) and the pictures keep the repository's default.
    doc = yaml.safe_load((ROOT / ".github/workflows/release-prep.yml").read_text())
    uploads = _uploads(doc)
    assert set(uploads) == MODEL_TEXT_ARTIFACTS | {"release-context", "release-images"}
    kept = {name for name, upload in uploads.items() if "retention-days" in upload}
    assert kept == MODEL_TEXT_ARTIFACTS
    assert all(uploads[name]["retention-days"] == 1 for name in kept)


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
