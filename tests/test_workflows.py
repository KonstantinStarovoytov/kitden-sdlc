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


def test_the_desk_measures_without_the_switch_and_posts_only_with_it():
    doc = yaml.safe_load((ROOT / ".github/workflows/desk.yml").read_text())
    measure, post = doc["jobs"]["measure"], doc["jobs"]["post"]
    assert "if" not in measure
    assert measure["permissions"] == {"contents": "write", "actions": "read"}
    assert "vars.AGENTS_ENABLED == 'true'" in post["if"] and post["permissions"] == {}
    assert not any("PRIVATE_KEY" in str(step) for step in measure["steps"])
    assert check_workflow(doc, "desk.yml") == []


def test_the_desk_posts_after_the_numbers_as_the_review_app_on_kitden_only():
    doc = yaml.safe_load((ROOT / ".github/workflows/desk.yml").read_text())
    measure, post = doc["jobs"]["measure"], doc["jobs"]["post"]
    assert (measure["timeout-minutes"], post["timeout-minutes"]) == (10, 5)
    assert post["needs"] == "measure"
    sign_in = [s for s in post["steps"] if "create-github-app-token" in str(s.get("uses"))]
    assert len(sign_in) == 1
    assert sign_in[0]["with"]["repositories"] == "kitden"
    assert sign_in[0]["with"]["permission-issues"] == "write"
    permissions = [k for k in sign_in[0]["with"] if k.startswith("permission-")]
    assert permissions == ["permission-issues"]
    # The job holds no contents permission, so its checkout is the workflow's own commit.
    checkouts = [s for s in post["steps"] if "checkout" in str(s.get("uses"))]
    assert checkouts and all("ref" not in (s.get("with") or {}) for s in checkouts)


def test_the_desk_posts_and_pushes_only_from_main():
    # Started by hand from another branch, it would post as Lantern and push to `numbers`
    # with that branch's scripts.
    doc = yaml.safe_load((ROOT / ".github/workflows/desk.yml").read_text())
    main = "github.ref == 'refs/heads/main'"
    assert main in doc["jobs"]["post"]["if"]
    commit = next(s for s in doc["jobs"]["measure"]["steps"] if "git push" in str(s.get("run")))
    assert commit["if"] == main


def test_the_desk_reads_the_reviews_once_and_writes_every_file_in_one_step():
    doc = yaml.safe_load((ROOT / ".github/workflows/desk.yml").read_text())
    steps = doc["jobs"]["measure"]["steps"]
    assert not any("count_reviews.py" in str(step.get("run", "")) for step in steps)
    gather = [s for s in steps if "desk_gather.py" in str(s.get("run", ""))]
    assert len(gather) == 1 and "--out out" in gather[0]["run"]
    commit = next(s for s in steps if "git push" in str(s.get("run", "")))
    assert "git add numbers.md numbers.json desk.json" in commit["run"]


def test_the_desk_does_not_stop_when_the_watchers_log_is_missing():
    doc = yaml.safe_load((ROOT / ".github/workflows/desk.yml").read_text())
    memory = [
        s for s in doc["jobs"]["measure"]["steps"]
        if "checkout" in str(s.get("uses")) and (s.get("with") or {}).get("ref") == "watch"
    ]
    assert len(memory) == 1 and memory[0]["continue-on-error"] is True


def test_the_watcher_knows_only_the_bots_own_issues_as_known_titles():
    doc = yaml.safe_load((ROOT / ".github/workflows/watch.yml").read_text())
    steps = doc["jobs"]["fetch"]["steps"]
    step = next(s for s in steps if s.get("name") == "List the open watcher issues")
    assert 'select(.user.login == "kitden-lantern[bot]")' in step["run"]
    assert "select(.pull_request | not)" in step["run"]


# --- Guards that LOG.md names. Each is a function of the file's text, so a negative case can
# --- check the same function on a copy of the text with the guard cut out.

WORKFLOWS = ROOT / ".github/workflows"


def _without(text: str, guard: str) -> str:
    assert guard in text, guard
    return text.replace(guard, "")


def _cut_last(text: str, guard: str) -> str:
    head, found, tail = text.rpartition(guard)
    assert found, guard
    return head + tail


def _steps(doc: dict, job: str) -> list[dict]:
    return doc["jobs"][job]["steps"]


def _step(doc: dict, job: str, name: str) -> dict | None:
    return next((s for s in _steps(doc, job) if s.get("name") == name), None)


def _before(doc: dict, job: str, first: str, second: str) -> bool:
    names = [s.get("name") for s in _steps(doc, job)]
    return first in names and second in names and names.index(first) < names.index(second)


def _codex_safety_problems(text: str) -> list[str]:
    doc = yaml.safe_load(text)
    steps = [s for job in doc["jobs"].values() for s in job.get("steps") or []]
    codex = [s for s in steps if "openai/codex-action" in str(s.get("uses", ""))]
    problems = [] if codex else ["no codex step"]
    for step in codex:
        # Not setting it means the action's default, drop-sudo. read-only would leave the
        # OpenAI key where the model can read it from memory.
        if step.get("with", {}).get("safety-strategy", "drop-sudo") != "drop-sudo":
            problems.append("safety-strategy is not drop-sudo")
    return problems


def test_no_codex_step_names_a_safety_strategy_but_drop_sudo():
    for file in WORKFLOWS.glob("*.yml"):
        text = file.read_text()
        if "openai/codex-action" in text:
            assert _codex_safety_problems(text) == [], file.name
    review = (WORKFLOWS / "review.yml").read_text()
    assert _codex_safety_problems(review) == []
    for bad in ("safety-strategy: read-only", "safety-strategy: unsafe"):
        marked = review.replace(
            "          output-file: .review/findings.json\n",
            f"          output-file: .review/findings.json\n          {bad}\n",
        )
        assert marked != review
        assert _codex_safety_problems(marked) == ["safety-strategy is not drop-sudo"]
    explicit = review.replace(
        "          output-file: .review/findings.json\n",
        "          output-file: .review/findings.json\n          safety-strategy: drop-sudo\n",
    )
    assert _codex_safety_problems(explicit) == []


PREPARE = ROOT / "scripts/prepare_review.sh"


def _review_folder_problems(script: str) -> list[str]:
    lines = [line.strip() for line in script.splitlines()]
    try:
        wipe, make, first_write = (
            lines.index("rm -rf .review"),
            lines.index("mkdir .review"),
            next(i for i, line in enumerate(lines) if "> .review/" in line),
        )
    except (ValueError, StopIteration):
        return ["the folder is not wiped and made before the first write"]
    return [] if wipe < make < first_write else ["the wipe is not first"]


def test_the_review_folder_is_wiped_before_anything_is_written_to_it():
    script = PREPARE.read_text()
    assert _review_folder_problems(script) == []
    assert _review_folder_problems(_without(script, "rm -rf .review\n")) != []
    swapped = script.replace(
        "rm -rf .review\nmkdir .review\n", "mkdir -p .review\nrm -rf .review\n"
    )
    assert swapped != script and _review_folder_problems(swapped) != []


AGENT_FILES_STEP = "Remove the pull request's agent instructions"
CODEX_REVIEW_STEP = "Review"


def _luna_problems(text: str) -> list[str]:
    doc = yaml.safe_load(text)
    problems = []
    step = _step(doc, "luna", AGENT_FILES_STEP)
    if step is None:
        return ["the step that removes the agent instructions is missing"]
    run = step["run"]
    for wanted in ("AGENTS.md", "AGENTS.override.md", ".agents", ".codex", "-name AGENTS.md"):
        if wanted not in run:
            problems.append(f"it does not remove {wanted}")
    if "rm " not in run or "find " not in run:
        problems.append("it does not delete")
    if step.get("if") != "steps.prepare.outputs.skip != 'true'":
        problems.append("it does not run whenever Codex runs")
    if not _before(doc, "luna", AGENT_FILES_STEP, CODEX_REVIEW_STEP):
        problems.append("it does not run before Codex")
    review = _step(doc, "luna", CODEX_REVIEW_STEP)
    if "project_doc_max_bytes=0" not in str(review["with"]["codex-args"]):
        problems.append("project docs are not capped at 0 bytes")
    return problems


def test_codex_never_sees_the_pull_requests_agent_files_or_project_docs():
    text = (WORKFLOWS / "review.yml").read_text()
    assert _luna_problems(text) == []
    assert (
        _luna_problems(text.replace("rm -rf AGENTS.md AGENTS.override.md .agents .codex\n", ""))
        != []
    )
    assert _luna_problems(_without(text, "project_doc_max_bytes=0")) != []
    assert (
        _luna_problems(text.replace(f"- name: {AGENT_FILES_STEP}", "- name: Something else")) != []
    )
    late = text.replace(
        f"- name: {AGENT_FILES_STEP}\n        if: steps.prepare.outputs.skip != 'true'",
        f"- name: {AGENT_FILES_STEP}\n        if: false",
    )
    assert late != text and _luna_problems(late) != []


def _check_problems(text: str, zizmor: tuple[str, ...], actionlint: tuple[str, ...]) -> list[str]:
    (job,) = yaml.safe_load(text)["jobs"].values()
    runs = [" ".join(str(s["run"]).split()) for s in job["steps"] if "run" in s]
    problems = []
    for name, flags in (("zizmor", zizmor), ("actionlint", actionlint)):
        run = next((r for r in runs if name in r), "")
        if not run:
            problems.append(f"no {name} step")
        problems += [f"{name} lacks {flag}" for flag in flags if flag not in run]
    return problems


def test_a_pull_request_cannot_switch_off_zizmor_or_actionlint():
    # check.yml runs on the caller's checkout, where our files sit in .kitden-sdlc; checks.yml
    # runs in this repository, where they are in config/.
    cases = {
        "check.yml": (
            (
                "uvx --no-config zizmor==1.32.0",
                "--config .kitden-sdlc/config/zizmor.yml",
                "--no-ignores",
            ),
            ("-config-file .kitden-sdlc/config/actionlint.yaml",),
        ),
        "checks.yml": (
            ("uvx --no-config zizmor==1.32.0 --no-config --no-ignores",),
            ("-config-file config/actionlint.yaml",),
        ),
    }
    for file, (zizmor, actionlint) in cases.items():
        text = (WORKFLOWS / file).read_text()
        assert _check_problems(text, zizmor, actionlint) == [], file
        for guard in (*zizmor, *actionlint):
            # The same check on a copy with one guard cut out must complain.
            # (the last place it occurs: a comment above the step may name the flag too).
            cut = _cut_last(text, guard.removeprefix("uvx "))
            assert _check_problems(cut, zizmor, actionlint) != [], (file, guard)
    assert (ROOT / "config/zizmor.yml").is_file() and (ROOT / "config/actionlint.yaml").is_file()


NESTED_STEP = "Remove the pull request's nested Claude files"


def _nested_claude_problems(text: str) -> list[str]:
    doc = yaml.safe_load(text)
    step = _step(doc, "claude", NESTED_STEP)
    if step is None:
        return ["the step is missing"]
    run = " ".join(str(step["run"]).split())
    problems = [
        f"it does not remove {wanted}"
        for wanted in ("-name CLAUDE.md", "-name CLAUDE.local.md", "-name .claude", "rm -rf")
        if wanted not in run
    ]
    if not _before(doc, "claude", NESTED_STEP, "Review"):
        problems.append("it does not run before Claude")
    return problems


def test_claude_never_reads_a_claude_file_the_pull_request_adds():
    text = (WORKFLOWS / "review.yml").read_text()
    assert _nested_claude_problems(text) == []
    for wanted in (
        "-name CLAUDE.md",
        "-name CLAUDE.local.md",
        "-name .claude",
        "-exec rm -rf {} +",
    ):
        assert (
            _nested_claude_problems(
                text.replace(wanted, "-name x" if wanted.startswith("-name") else "", 1)
            )
            != []
        ), wanted
    assert _nested_claude_problems(text.replace(NESTED_STEP, "Something else")) != []


def _cap_problems(text: str) -> list[str]:
    doc = yaml.safe_load(text)
    step = next((s for s in _steps(doc, "cap") if s.get("id") == "count"), None)
    if step is None:
        return ["no counting step"]
    run = " ".join(str(step["run"]).split())
    problems = []
    for wanted, why in (
        ('.conclusion != "cancelled"', "cancelled runs would use up the cap"),
        ('.conclusion != "skipped"', "skipped runs would use up the cap"),
        ("(.databaseId | tostring) != env.RUN_ID", "the run would count itself"),
        ('[ "$runs" -ge "$DAILY_CAP" ]', "a cap of 10 would not mean 10"),
        ("--created", "yesterday's runs would count"),
    ):
        if wanted not in run:
            problems.append(why)
    if step["env"].get("RUN_ID") != "${{ github.run_id }}":
        problems.append("the run's own id is not given")
    return problems


def test_the_daily_cap_counts_only_runs_that_did_work_and_not_itself():
    text = (WORKFLOWS / "review.yml").read_text()
    assert _cap_problems(text) == []
    for guard in (
        '.conclusion != "cancelled"',
        '.conclusion != "skipped"',
        "(.databaseId | tostring) != env.RUN_ID",
        '-ge "$DAILY_CAP"',
        "--created",
    ):
        assert _cap_problems(text.replace(guard, "", 1)) != [], guard
    assert _cap_problems(text.replace("RUN_ID: ${{ github.run_id }}", "RUN_ID: ''")) != []
