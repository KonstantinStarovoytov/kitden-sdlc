from pathlib import Path

import pytest

from release_fix import main, settle
from tests.fakes import KEY_TAIL, shows_key


def make(folder: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return folder


def test_the_version_and_the_scenes_are_put_back(tmp_path):
    before = make(tmp_path / "before", {"version.txt": "0.9.0"})
    after = make(tmp_path / "after", {"version.txt": "1.0.0", "scenes.txt": "pick"})
    assert settle(before, after, "0.9.0") == []
    assert (after / "version.txt").read_text() == "0.9.0"
    assert not (after / "scenes.txt").exists()


def test_scenes_that_the_pass_deleted_come_back(tmp_path):
    before = make(tmp_path / "before", {"scenes.txt": "pick"})
    after = make(tmp_path / "after", {})
    assert settle(before, after, "0.9.0") == []
    assert (after / "scenes.txt").read_text() == "pick"


def test_it_lists_what_the_pass_changed(tmp_path):
    before = make(tmp_path / "before", {"README.md": "a", "findings.md": "x", "notes.md": "n"})
    after = make(
        tmp_path / "after",
        {"README.md": "b", "findings.md": "y", "guide.md": "new", "notes.md": "n"},
    )
    assert settle(before, after, "0.9.0") == ["README.md", "docs/guide.md"]


def test_the_list_is_sorted_and_uses_the_version(tmp_path):
    before = make(tmp_path / "before", {"notes.md": "a", "policy/SECURITY.md": "a"})
    after = make(tmp_path / "after", {"notes.md": "b", "policy/SECURITY.md": "b"})
    assert settle(before, after, "0.9.0") == ["SECURITY.md", "docs/releases/v0.9.0.md"]


def test_a_file_the_pass_deleted_is_put_back_and_not_listed(tmp_path):
    before = make(tmp_path / "before", {"README.md": "a", "policy/PRIVACY.md": "p"})
    after = make(tmp_path / "after", {"README.md": "a"})
    assert settle(before, after, "0.9.0") == []
    assert (after / "policy/PRIVACY.md").read_text() == "p"


def test_a_file_it_does_not_know_is_refused_and_nothing_changes(tmp_path):
    # The model chose the name, and the log is public: the message counts, it never names.
    before = make(tmp_path / "before", {"version.txt": "0.9.0"})
    after = make(tmp_path / "after", {"version.txt": "1.0.0", "extra.sh": "x", KEY_TAIL: "y"})
    with pytest.raises(ValueError, match=r"names are not allowed \(2\)") as refused:
        settle(before, after, "0.9.0")
    assert "extra" not in str(refused.value) and not shows_key(str(refused.value))
    assert (after / "version.txt").read_text() == "1.0.0"


@pytest.mark.parametrize("name", ["guide.md", f"{KEY_TAIL}.md"], ids=["allowed", "unknown"])
def test_a_link_is_refused(tmp_path, name):
    # A link is refused under a name release_apply knows as well as under one it does not,
    # and the message never shows the name.
    before = make(tmp_path / "before", {})
    after = make(tmp_path / "after", {"README.md": "a"})
    (after / name).symlink_to(after / "README.md")
    with pytest.raises(ValueError, match=r"links or other files that are not plain \(1\)") as e:
        settle(before, after, "0.9.0")
    assert not shows_key(str(e.value)) and "guide" not in str(e.value)
    assert (after / name).is_symlink() and not (after / "version.txt").exists()


def test_the_command_writes_one_path_per_line(tmp_path, capsys):
    before = make(tmp_path / "before", {"README.md": "a"})
    after = make(tmp_path / "after", {"README.md": "b", "guide.md": "g"})
    changed = tmp_path / "changed.txt"
    args = ["settle", str(before), str(after), "--version", "0.9.0", "--changed", str(changed)]
    assert main(args) == 0
    assert changed.read_text() == "README.md\ndocs/guide.md\n"
    assert capsys.readouterr().out == ""


def test_the_command_writes_an_empty_file_when_nothing_changed(tmp_path):
    before = make(tmp_path / "before", {"README.md": "a"})
    after = make(tmp_path / "after", {"README.md": "a"})
    changed = tmp_path / "changed.txt"
    args = ["settle", str(before), str(after), "--version", "0.9.0", "--changed", str(changed)]
    assert main(args) == 0
    assert changed.read_text() == ""


def test_the_command_prints_the_error_and_returns_1(tmp_path, capsys):
    before = make(tmp_path / "before", {})
    after = make(tmp_path / "after", {"extra.sh": "x"})
    changed = tmp_path / "changed.txt"
    args = ["settle", str(before), str(after), "--version", "0.9.0", "--changed", str(changed)]
    assert main(args) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "not allowed (1)" in captured.err
    assert "extra" not in captured.err
