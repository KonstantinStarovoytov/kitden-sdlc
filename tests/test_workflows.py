import re
from pathlib import Path

import pytest
import yaml

from check_agent_workflows import HOSTS_ACTION, PINNED, _is_model_step, check_workflow

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
                '--config "$GITHUB_WORKSPACE/.kitden-sdlc/config/zizmor.yml"',
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


# --- uv runs a .venv/bin/python it finds in its working folder or any folder above it, even
# --- with --no-project --no-config (uv 0.10.10). A pull request can commit one, so where a job
# --- has someone else's checkout at the top of the workspace, uv and python run from the
# --- runner's temp folder, with absolute paths.

RUNS_PYTHON = re.compile(r"(?<![\w./-])(?:uv\s+run|uv\s+tool\s+run|uvx|python3?)(?![\w-])")
OWN_REPOSITORY = "${{ job.workflow_repository }}"
TEMP = "${{ runner.temp }}"

# Jobs that run uv or python on someone else's checkout on purpose, and why that is safe.
# Each is checked below: an entry that is no longer needed fails the test too.
OWN_CODE_ON_PURPOSE = {
    # kitden-sdlc's own tests: the job's whole point is to run the pull request's code, and a
    # pull request can change the tests and the rule checker directly. No secret, read only.
    ("checks.yml", "checks"),
    # Kitden's main only: every job needs guard, which stops a run that is not on Kitden's
    # main, so the checkout at the top is code the owner merged, never a pull request's.
    ("release-prep.yml", "fix"),
    ("release-prep.yml", "record"),
}


def _triggers(doc: dict) -> set[str]:
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on}
    return set(on or ())


def _someone_elses_checkout_on_top(doc: dict, job: dict) -> bool:
    """A checkout at the top of the workspace that is not kitden-sdlc's own: the caller's,
    in a workflow another repository calls, or a pull request's. A scheduled or pushed run of
    one of this repository's own workflows checks out this repository."""
    outside = bool(_triggers(doc) & {"workflow_call", "pull_request", "pull_request_target"})
    for step in job.get("steps") or []:
        if "actions/checkout" not in str(step.get("uses", "")):
            continue
        given = step.get("with") or {}
        if str(given.get("path", ".")).strip("/") not in ("", "."):
            continue
        repository = given.get("repository")
        if (repository is None and outside) or repository not in (None, OWN_REPOSITORY):
            return True
    return False


def _outside_folder_problems(text: str, file: str) -> list[str]:
    doc = yaml.safe_load(text)
    problems = []
    for name, job in doc["jobs"].items():
        if not _someone_elses_checkout_on_top(doc, job) or (file, name) in OWN_CODE_ON_PURPOSE:
            continue
        default = ((job.get("defaults") or {}).get("run") or {}).get("working-directory")
        for step in job.get("steps") or []:
            run = str(step.get("run", ""))
            if not RUNS_PYTHON.search(run):
                continue
            where = f"{name}: {step.get('name') or ' '.join(run.split())[:40]}"
            folder = str(step.get("working-directory", default or "."))
            if folder != TEMP and not folder.startswith(TEMP + "/"):
                problems.append(f"{where}: runs inside the checkout ({folder})")
            if re.search(r"(?<![\w-])(?:cd|pushd)\s|--directory|--project", run):
                problems.append(f"{where}: changes its folder")
            # From the temp folder a relative path would name nothing.
            for path in re.findall(r"\S*(?:\.kitden-sdlc|\.github)/", run):
                if "$GITHUB_WORKSPACE/" not in path:
                    problems.append(f"{where}: {path} is not under $GITHUB_WORKSPACE")
    return problems


def test_uv_and_python_never_run_inside_a_checkout_someone_else_controls():
    for file in sorted(WORKFLOWS.glob("*.yml")):
        assert _outside_folder_problems(file.read_text(), file.name) == [], file.name
    text = (WORKFLOWS / "check.yml").read_text()
    for guard, swap in (
        ("        working-directory: ${{ runner.temp }}\n", ""),
        ("working-directory: ${{ runner.temp }}", "working-directory: ."),
        ("working-directory: ${{ runner.temp }}", "working-directory: ${{ github.workspace }}"),
        ('python "$GITHUB_WORKSPACE/.kitden-sdlc/', "python .kitden-sdlc/"),
        ('"$GITHUB_WORKSPACE/.github/workflows"', ".github/workflows"),
        ("uv run --no-project", 'cd "$GITHUB_WORKSPACE" && uv run --no-project'),
        ("uv run --no-project", 'uv run --directory "$GITHUB_WORKSPACE" --no-project'),
    ):
        # Each uv step of check.yml is guarded on its own: undoing either one complains.
        parts = text.split(guard)
        assert len(parts) > 1, guard
        for n in range(1, len(parts)):
            cut = guard.join(parts[:n]) + swap + guard.join(parts[n:])
            assert _outside_folder_problems(cut, "check.yml") != [], (guard, n)


def test_a_planted_python_is_looked_for_in_every_job_that_could_hold_one():
    # Reached at all: check.yml's job counts as holding the pull request's files, the review
    # post job (kitden-sdlc's own checkout) and a scheduled job of this repository do not.
    def held(file: str, job: str) -> bool:
        doc = yaml.safe_load((WORKFLOWS / file).read_text())
        return _someone_elses_checkout_on_top(doc, doc["jobs"][job])

    assert held("check.yml", "check")
    assert held("review.yml", "claude") and held("review.yml", "luna")
    assert not held("review.yml", "post")
    assert not held("desk.yml", "measure") and not held("watch.yml", "fetch")
    assert not held("publish.yml", "registry")  # Kitden sits in kitden/, not on top
    # Each job let off holds someone else's checkout and runs uv or python: without its entry
    # it would fail, so an entry that is no longer needed is noticed.
    for file, job in OWN_CODE_ON_PURPOSE:
        assert held(file, job), (file, job)
        doc = yaml.safe_load((WORKFLOWS / file).read_text())
        assert any(RUNS_PYTHON.search(str(s.get("run", ""))) for s in doc["jobs"][job]["steps"])
    # The release-prep jobs are let off because guard stops any run that is not Kitden's main.
    doc = yaml.safe_load((WORKFLOWS / "release-prep.yml").read_text())
    guard = " ".join(str(_step(doc, "guard", "May release prep start?")["run"]).split())
    assert 'if [ "$GITHUB_REF" != "refs/heads/main" ]; then' in guard
    for file, job in OWN_CODE_ON_PURPOSE:
        if file == "release-prep.yml":
            needs = doc["jobs"][job]["needs"]
            assert "guard" in ([needs] if isinstance(needs, str) else needs), job


# --- list-check.yml: Kitden calls it on every pull request that changes docs/clients.md, forks
# --- included. The pull request's files are untrusted; no model runs and no secret is near.

LIST_CHECK = WORKFLOWS / "list-check.yml"
LIST_STEP = "Check the changed rows against their pages"


def _uses(doc: dict) -> list[str]:
    return [str(s["uses"]) for job in doc["jobs"].values() for s in job["steps"] if "uses" in s]


def _list_check_problems(text: str) -> list[str]:
    doc = yaml.safe_load(text)
    problems = []
    if doc.get("on", doc.get(True)) != {"workflow_call": None}:
        problems.append("it runs on something other than workflow_call, or takes inputs")
    if doc.get("permissions") != {}:
        problems.append("the top permissions are not {}")
    if "secrets" in text:
        problems.append("the file names secrets")
    (job,) = doc["jobs"].values()
    if job.get("permissions") != {"contents": "read"}:
        problems.append("the job may do more than read the code")
    if job.get("timeout-minutes") != 10:
        problems.append("the job's timeout is not 10 minutes")
    if job.get("continue-on-error") is not None:
        problems.append("the job hides its own failures")
    steps = job["steps"]
    first = steps[0]
    if not str(first.get("uses", "")).startswith(HOSTS_ACTION + "@") or first.get("with") != {
        "egress-policy": "audit"
    }:
        problems.append("the first step does not record the hosts")
    if not all(PINNED.match(uses) for uses in _uses(doc)):
        problems.append("an action is not pinned to a full SHA")
    checkouts = [s for s in steps if "actions/checkout" in str(s.get("uses", ""))]
    if len(checkouts) != 2 or any(
        (s.get("with") or {}).get("persist-credentials") is not False for s in checkouts
    ):
        problems.append("a checkout keeps the token")
    # The merge commit and its parents: the base list is the merge's first parent, the commit
    # the head was made from, not the base branch's tip at the time of a re-run.
    if checkouts and (checkouts[0].get("with") or {}).get("fetch-depth") != 2:
        problems.append("the pull request's checkout does not bring the merge's parents")
    if checkouts and (checkouts[-1].get("with") or {}).get("ref") != "${{ job.workflow_sha }}":
        problems.append("kitden-sdlc is not checked out at this workflow's own commit")
    if not _before(doc, "check", "Clear the tools folder", "Check out kitden-sdlc"):
        problems.append("the tools folder is not cleared before kitden-sdlc is checked out")
    runs = [str(s["run"]) for s in steps if "run" in s]
    if any("${{" in run for run in runs):
        problems.append("an expression sits inside run")
    if any("git fetch" in run for run in runs):
        problems.append("a step fetches: the base list comes from the merge's first parent")
    problems += _list_files_problems(_step(doc, "check", LISTS_STEP))
    step = _step(doc, "check", LIST_STEP)
    if step is None:
        return [*problems, "the script step is missing"]
    run = " ".join(str(step["run"]).split())
    if "uv run --no-project --no-config" not in run or "list_sources.py" not in run:
        problems.append("the script is not run with --no-project --no-config")
    if "--base base.md --head head.md" not in run or "docs/clients.md" in run:
        problems.append("the script reads a list other than the two written by git show")
    # uv runs a .venv/bin/python it finds in its folder or any folder above it, and the pull
    # request can bring one: the script runs from the runner's temp folder instead.
    if step.get("working-directory") != "${{ runner.temp }}":
        problems.append("the script runs inside the pull request's checkout")
    return problems


LISTS_STEP = "Get the list before and after the pull request"


def _list_files_problems(step: dict | None) -> list[str]:
    """Both lists are written by `git show` into $RUNNER_TEMP: a docs/clients.md that is a link
    is read as its link text, and a base.md the pull request brings is never written through."""
    if step is None:
        return ["the step that writes the lists is missing"]
    lines = [line.strip() for line in str(step["run"]).splitlines()]
    problems = []
    for line in lines:
        if "docs/clients.md" in line and not line.startswith(("git show ", "if git cat-file -e ")):
            problems.append(f"the list is read by something other than git: {line}")
        writes = re.findall(r"(?<![0-9&])> *([^\s;]+)", line)
        if any(w != "/dev/null" and not w.startswith('"$RUNNER_TEMP/') for w in writes):
            problems.append(f"a file is written outside the temp folder: {line}")
    for wanted in ('list "HEAD^1" base', "list HEAD head"):
        if wanted not in lines:
            problems.append(f"missing: {wanted}")
    return problems


def test_the_list_check_runs_kitden_sdlcs_script_and_nothing_the_pull_request_brings():
    text = LIST_CHECK.read_text()
    assert _list_check_problems(text) == []
    for guard, swap in (
        ("  workflow_call:\n", "  workflow_call:\n  pull_request_target:\n"),
        ("permissions: {}\n", "permissions: write-all\n"),
        ("      contents: read", "      contents: write"),
        ("timeout-minutes: 10", "timeout-minutes: 30"),
        ("egress-policy: audit", "egress-policy: none"),
        ("persist-credentials: false", "persist-credentials: true"),
        ("ref: ${{ job.workflow_sha }}", "ref: main"),
        ("- name: Clear the tools folder", "- name: Something else"),
        ("fetch-depth: 2", "fetch-depth: 1"),
        ('list "HEAD^1" base', 'list "origin/main" base'),
        ("--no-project", ""),
        ("--no-config", ""),
        ("working-directory: ${{ runner.temp }}", "working-directory: ."),
    ):
        # The flags are cut where the step names them, not in the comment above it.
        cut = _cut_last(text, guard) if guard.startswith("--") else text.replace(guard, swap, 1)
        assert cut != text, guard
        assert _list_check_problems(cut) != [], guard
    assert _list_check_problems(text + "# secrets.GITHUB_TOKEN\n") != []
    unpinned = re.sub(r"(harden-runner@)[0-9a-f]{40}", r"\1v2", text)
    assert unpinned != text and _list_check_problems(unpinned) != []
    late = text.replace('list "HEAD^1" base', 'list "${{ github.base_ref }}" base', 1)
    assert late != text and _list_check_problems(late) != []
    fetch = 'git fetch origin main\n          list "HEAD^1" base'
    fetched = text.replace('list "HEAD^1" base', fetch)
    assert fetched != text and _list_check_problems(fetched) != []


@pytest.mark.parametrize(("old", "new"), [
    ('git show "$1:docs/clients.md" > "$RUNNER_TEMP/$2.md"',
     'cp docs/clients.md "$RUNNER_TEMP/$2.md"'),
    ('git show "$1:docs/clients.md" > "$RUNNER_TEMP/$2.md"',
     'cat docs/clients.md > "$RUNNER_TEMP/$2.md"'),
    ('git show "$1:docs/clients.md" > "$RUNNER_TEMP/$2.md"',
     'git show "$1:docs/clients.md" > "$2.md"'),
    ("list HEAD head", 'cp docs/clients.md "$RUNNER_TEMP/head.md"'),
    ("--head head.md", '--head "$GITHUB_WORKSPACE/docs/clients.md"'),
])
def test_the_list_check_reads_both_lists_only_from_git_show_in_the_temp_folder(old, new):
    text = LIST_CHECK.read_text()
    assert _list_check_problems(text) == []
    changed = text.replace(old, new, 1)
    assert changed != text and _list_check_problems(changed) != []


def test_the_list_check_stops_red_when_the_checkout_is_not_a_merge():
    run = str(_step(yaml.safe_load(LIST_CHECK.read_text()), "check", LISTS_STEP)["run"])
    assert 'git rev-parse --verify --quiet "HEAD^1"' in run
    assert run.count("::error::") == 1 and "exit 1" in run


def test_the_list_check_uses_the_same_pins_as_the_workflows_it_copies():
    doc = yaml.safe_load(LIST_CHECK.read_text())
    known = set(_uses(yaml.safe_load((WORKFLOWS / "check.yml").read_text())))
    known |= set(_uses(yaml.safe_load((WORKFLOWS / "watch.yml").read_text())))
    assert set(_uses(doc)) <= known
    uv = next(s for s in doc["jobs"]["check"]["steps"] if "setup-uv" in str(s.get("uses")))
    check = yaml.safe_load((WORKFLOWS / "check.yml").read_text())
    uv_check = next(s for s in check["jobs"]["check"]["steps"] if "setup-uv" in str(s.get("uses")))
    assert uv["with"] == uv_check["with"] == {"version": "0.10.10", "enable-cache": False}


def test_the_list_check_cannot_turn_red_for_a_page():
    # The script always exits 0; nothing in the workflow may make a warning a failure.
    doc = yaml.safe_load(LIST_CHECK.read_text())
    run = " ".join(str(_step(doc, "check", LIST_STEP)["run"]).split())
    assert "||" not in run and "exit" not in run
    assert check_workflow(doc, "list-check.yml") == []
