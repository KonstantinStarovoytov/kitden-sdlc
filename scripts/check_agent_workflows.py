"""Fail agent workflows that break the written rules (see RULES.md)."""

import re
import sys
from pathlib import Path

import yaml

MODEL_ACTIONS = ("anthropics/claude-code-action", "openai/codex-action")
SWITCH_PARTS = (
    "vars.AGENTS_ENABLED == 'true'",
    "github.event.pull_request.head.repo.full_name == github.repository",
    "!endsWith(github.actor, '[bot]')",
)
PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}")
# kitden-sdlc's own workflows may be called at main: that branch is protected.
OWN_MAIN = re.compile(r"^KonstantinStarovoytov/kitden-sdlc/\.github/workflows/[\w.-]+@main$")
# A step that gets one of these and is not a model action calls the model from a script.
MODEL_SECRET = re.compile(
    r"secrets\.(openai_api_key|claude_code_oauth_token|anthropic_api_key)", re.I
)
SCHEDULED_EVENTS = {"schedule", "workflow_dispatch"}


def _jobs(doc: dict) -> dict:
    return doc.get("jobs") or {}


def _events(doc: dict) -> set[str]:
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    return set(on or {})


def _is_model_step(step: dict) -> bool:
    return any(name in str(step.get("uses", "")) for name in MODEL_ACTIONS)


def _is_script_agent_step(step: dict) -> bool:
    if _is_model_step(step):
        return False
    values = [*(step.get("env") or {}).values(), *(step.get("with") or {}).values()]
    return any(MODEL_SECRET.search(str(value)) for value in values)


def _script_agent_steps(job: dict) -> list[dict]:
    return [step for step in job.get("steps") or [] if _is_script_agent_step(step)]


def _is_review_caller(job: dict) -> bool:
    uses = str(job.get("uses", "")).split("@")[0]
    return ".github/workflows/" in uses and uses.rsplit("/", 1)[-1].startswith("review")


def _has_model_step(job: dict) -> bool:
    return any(_is_model_step(step) for step in job.get("steps") or [])


def _is_agent_job(job: dict) -> bool:
    return _is_review_caller(job) or _has_model_step(job) or bool(_script_agent_steps(job))


def is_agent_workflow(doc: dict) -> bool:
    return any(_is_agent_job(job) for job in _jobs(doc).values())


def _cancels(concurrency) -> bool:
    return isinstance(concurrency, dict) and concurrency.get("cancel-in-progress") is True


def _uses_values(job: dict):
    if "uses" in job:
        yield str(job["uses"])
    for step in job.get("steps") or []:
        if "uses" in step:
            yield str(step["uses"])


def _marketplaces(job: dict):
    for step in job.get("steps") or []:
        value = (step.get("with") or {}).get("plugin_marketplaces")
        if isinstance(value, str):
            yield from value.split()
        elif isinstance(value, list):
            yield from map(str, value)


def _in_release_environment(job: dict) -> bool:
    environment = job.get("environment")
    if isinstance(environment, dict):
        environment = environment.get("name")
    # Fail closed: names are not case-sensitive, and an expression could be `release`.
    name = str(environment or "")
    return "${{" in name or name.lower() == "release"


def _job_mentions_model_secret(job: dict) -> bool:
    """Whole-job match, so a secret in job env, `secrets:` or a `run:` string is seen."""
    parts = [job.get("env"), job.get("with"), job.get("secrets")]
    for step in job.get("steps") or []:
        parts += [step.get("env"), step.get("with"), step.get("run")]
    return any(MODEL_SECRET.search(str(part)) for part in parts if part)


def _release_violations(doc: dict) -> list[tuple[int, str]]:
    """Rule 1, for every workflow: the job that holds the release key never runs a model."""
    found: list[tuple[int, str]] = []
    jobs = _jobs(doc)
    holders = [name for name, job in jobs.items() if _in_release_environment(job)]
    for name in holders:
        job = jobs[name]
        if _has_model_step(job) or _job_mentions_model_secret(job):
            found.append((1, f"job {name} holds the release environment and runs a model"))
    for event in ("pull_request_target", "issue_comment"):
        if event in _events(doc):
            for name in holders:
                found.append((1, f"job {name} holds the release environment on {event}"))
    return found


def check_workflow(doc: dict, path: str) -> list[str]:
    if not isinstance(doc, dict):
        return []
    release = _release_violations(doc)
    if not is_agent_workflow(doc):
        return [f"{path}: rule {rule}: {message}" for rule, message in release]
    found: list[tuple[int, str]] = release
    jobs = _jobs(doc)
    script_jobs = {name: job for name, job in jobs.items() if _script_agent_steps(job)}

    # Rule 1: a job that calls the model from a script may not write.
    for name, job in script_jobs.items():
        permissions = job.get("permissions")
        values = permissions.values() if isinstance(permissions, dict) else [permissions]
        if any("write" in str(value) for value in values):
            found.append((1, f"job {name} gets a model secret and has write permission"))

    # Rule 2: pull_request only, and callers carry the switch.
    if "pull_request_target" in _events(doc):
        found.append((2, "pull_request_target is not allowed"))
    for name, job in jobs.items():
        if "uses" in job:
            condition = str(job.get("if", ""))
            missing = [part for part in SWITCH_PARTS if part not in condition]
            if missing:
                found.append((2, f"job {name} has no switch condition for: {', '.join(missing)}"))
    # A scheduled agent: schedule and by hand only, and every job carries the switch.
    if script_jobs:
        extra = _events(doc) - SCHEDULED_EVENTS
        if extra:
            found.append((2, f"a scheduled agent may not run on: {', '.join(sorted(extra))}"))
        for name, job in jobs.items():
            if SWITCH_PARTS[0] not in str(job.get("if", "")):
                found.append((2, f"job {name} has no switch {SWITCH_PARTS[0]}"))

    # Rule 3: no permissions at the top, each job lists its own.
    if doc.get("permissions") != {}:
        found.append((3, "top-level permissions must be {}"))
    for name, job in jobs.items():
        if "permissions" not in job:
            found.append((3, f"job {name} has no permissions"))

    # Rule 4: pinned actions and marketplaces.
    for name, job in jobs.items():
        for uses in _uses_values(job):
            if uses.startswith("./") or PINNED.match(uses) or OWN_MAIN.match(uses):
                continue
            found.append((4, f"job {name}: {uses} is not pinned to a full SHA"))
        for marketplace in _marketplaces(job):
            if "#" not in marketplace:
                found.append((4, f"job {name}: marketplace {marketplace} has no tag after #"))

    # Rule 5: limits on every agent job.
    for name, job in jobs.items():
        if (_has_model_step(job) or name in script_jobs) and "timeout-minutes" not in job:
            found.append((5, f"job {name} has no timeout-minutes"))
        for step in job.get("steps") or []:
            if "anthropics/claude-code-action" in str(step.get("uses", "")):
                args = str((step.get("with") or {}).get("claude_args", ""))
                if "--max-turns" not in args:
                    found.append((5, f"job {name}: claude_args has no --max-turns"))
            if _is_script_agent_step(step) and "MAX_MODEL_CALLS" not in (step.get("env") or {}):
                found.append((5, f"job {name}: a step gets a model secret but no MAX_MODEL_CALLS"))
    agent_jobs = [job for job in jobs.values() if _is_agent_job(job)]
    covered = _cancels(doc.get("concurrency")) or all(
        _cancels(job.get("concurrency")) for job in agent_jobs
    )
    if "pull_request" in _events(doc) and not covered:
        found.append((5, "concurrency with cancel-in-progress: true is missing"))
    if script_jobs and not isinstance(doc.get("concurrency"), dict | str):
        found.append((5, "a scheduled agent needs a top-level concurrency, one run at a time"))

    return [f"{path}: rule {rule}: {message}" for rule, message in found]


def _files(args: list[str]) -> list[Path]:
    files: list[Path] = []
    for arg in args:
        path = Path(arg)
        if path.is_dir():
            files += sorted([*path.glob("*.yml"), *path.glob("*.yaml")])
        else:
            files.append(path)
    return files


def main(argv: list[str]) -> int:
    violations: list[str] = []
    for file in _files(argv):
        try:
            doc = yaml.safe_load(file.read_text())
        except yaml.YAMLError as error:
            violations.append(f"{file}: not valid YAML: {error}")
            continue
        violations += check_workflow(doc, str(file))
    for line in violations:
        print(line)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
