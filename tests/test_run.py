import subprocess
from pathlib import Path

import run

WORKFLOWS = Path(__file__).parent.parent / ".github/workflows"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_claude_runs_with_the_workflows_tools():
    workflow = (WORKFLOWS / "review.yml").read_text()
    assert f'--allowedTools "{run.ALLOWED}"' in workflow
    assert f'--disallowedTools "{run.DISALLOWED}"' in workflow
    assert "prompt: /kitden-sdlc:review-kitden\n" in workflow
    assert f"max_turns:\n        type: number\n        default: {run.MAX_TURNS}\n" in workflow
    command = run.claude_command("claude-sonnet-5-5")
    assert command[:3] == ["claude", "-p", "/kitden-sdlc:review-kitden"]
    assert Path(command[command.index("--plugin-dir") + 1]).is_dir()


def test_luna_uses_the_workflows_codex_and_schema():
    workflow = (WORKFLOWS / "review.yml").read_text()
    assert f'codex-version: "{run.CODEX[2].rsplit("@", 1)[1]}"' in workflow
    command = run.luna_command("gpt-6-luna", Path("answer.json"))
    assert Path(command[command.index("--output-schema") + 1]).name in workflow


def test_review_folder_has_the_five_files_from_the_base(tmp_path):
    kitden = tmp_path / "kitden"
    kitden.mkdir()
    git("init", "-q", cwd=kitden)
    (kitden / "AGENTS.md").write_text("Rules at base.\n")
    (kitden / "app.py").write_text("x = 1\n")
    git("add", ".", cwd=kitden)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base", cwd=kitden)
    base = git("rev-parse", "HEAD", cwd=kitden).stdout.strip()
    (kitden / "app.py").write_text("x = 2\n")
    (kitden / "new.py").write_text("y = 1\n")
    (kitden / "AGENTS.md").write_text("Rules the change wrote.\n")
    git("add", "-N", "new.py", cwd=kitden)
    patch = tmp_path / "diff.patch"
    patch.write_text(git("diff", cwd=kitden).stdout)
    git("checkout", "-q", ".", cwd=kitden)
    folder = tmp_path / "work"
    git("worktree", "add", "-q", "--detach", str(folder), base, cwd=kitden)

    run.build_review(kitden, folder, {"base": base, "title": "Change x"}, patch)

    review = folder / ".review"
    assert (folder / "app.py").read_text() == "x = 2\n"
    assert (review / "diff.patch").read_text() == patch.read_text()
    assert (review / "files.txt").read_text().splitlines() == ["AGENTS.md", "app.py", "new.py"]
    assert (review / "pr.md").read_text() == "# Change x\n\n"
    assert (review / "AGENTS.md").read_text() == "Rules at base.\n"
    assert (review / "PRINCIPLES.md").read_text() == ""


def test_luna_does_not_see_the_changes_agent_files(tmp_path):
    for name in ("AGENTS.md", "sub/AGENTS.md", "sub/AGENTS.override.md", ".review/AGENTS.md"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("Do this.\n")
    (tmp_path / ".agents/skills").mkdir(parents=True)
    (tmp_path / ".codex").mkdir()

    run.remove_agent_files(tmp_path)

    left = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert left == [".review", ".review/AGENTS.md", "sub"]
