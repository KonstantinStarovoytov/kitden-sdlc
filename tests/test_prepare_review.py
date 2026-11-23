import json
import os
import subprocess
from pathlib import Path

import pytest

from post_findings import skipped_bytes

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/prepare_review.sh"
LIMIT = 300_000
TEXT = "diff --git a/PRIVACY.md b/PRIVACY.md\n@@ -1 +1 @@\n-old\n+new\n"
PICTURE = (
    "diff --git a/docs/a.webp b/docs/a.webp\nindex 1..2 100644\n"
    "Binary files a/docs/a.webp and b/docs/a.webp differ\n"
)
# gh answers from a file, and fails `pr diff` when there is none; git only has to succeed.
GH = """#!/usr/bin/env bash
case "$*" in
  *--name-only*) echo PRIVACY.md ;;
  "pr diff "*) cat "$FAKE_DIFF" ;;
  *) echo "# Title" ;;
esac
"""


def prepare(tmp_path: Path, diff: str | None) -> tuple[str, Path]:
    """Run the script in an empty folder; give what it prints and its findings.json."""
    tools, work = tmp_path / "bin", tmp_path / "work"
    tools.mkdir()
    work.mkdir()
    for name, text in {"gh": GH, "git": "#!/usr/bin/env bash\n"}.items():
        (tools / name).write_text(text)
        (tools / name).chmod(0o755)
    if diff is not None:
        (tmp_path / "diff").write_text(diff)
    output = tmp_path / "output"
    env = os.environ | {
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DIFF": str(tmp_path / "diff"),
        "GITHUB_OUTPUT": str(output),
    }
    subprocess.run([str(SCRIPT), "7", "main"], cwd=work, env=env, check=True, capture_output=True)
    return output.read_text().strip(), work / ".review/findings.json"


@pytest.mark.parametrize("diff", [TEXT, TEXT + PICTURE, PICTURE + TEXT + PICTURE])
def test_a_small_diff_is_reviewed_with_or_without_pictures(tmp_path, diff):
    said, findings = prepare(tmp_path, diff)
    assert said == "skip=false"
    assert not findings.exists()


def test_a_diff_at_the_limit_is_reviewed(tmp_path):
    assert prepare(tmp_path, "x" * LIMIT)[0] == "skip=false"


def test_a_diff_over_the_limit_is_skipped_and_says_its_size(tmp_path):
    said, findings = prepare(tmp_path, "x" * (LIMIT + 1))
    assert said == "skip=true"
    assert json.loads(findings.read_text()) == {"skipped": LIMIT + 1}
    assert skipped_bytes(findings) == LIMIT + 1


def test_a_diff_github_does_not_return_is_skipped_with_no_size(tmp_path):
    said, findings = prepare(tmp_path, None)
    assert said == "skip=true"
    assert skipped_bytes(findings) == 0
