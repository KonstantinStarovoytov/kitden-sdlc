from secret_filter import has_commit, in_git, in_text, random_runs, unknown_runs
from tests.fakes import KEY_TAIL, repo


def test_a_cut_key_is_a_random_run_and_plain_text_is_not():
    assert random_runs(f"see {KEY_TAIL} here") == [KEY_TAIL]
    assert random_runs("src/kitden/clients/claude_code/settings_reader.py") == []
    assert random_runs("a" * 40) == [] and random_runs("0123456789abcdef" * 3) == []
    assert random_runs("Ab1" * 10) == []  # 30 characters: under RUN_MIN


def test_unknown_runs_keeps_only_what_the_input_lacks():
    known = in_text(f"token = '{KEY_TAIL}'", "other")
    assert unknown_runs([f"quotes {KEY_TAIL}"], known) == []
    assert unknown_runs([f"leaks {KEY_TAIL}x"], known) == [KEY_TAIL + "x"]


def test_in_git_knows_file_text_and_file_names(tmp_path):
    folder = repo(tmp_path, {"a.py": f"X = '{KEY_TAIL}'\n", f"{KEY_TAIL}Name.txt": "x\n"})
    known = in_git(folder, "HEAD")
    assert known(KEY_TAIL) and known(KEY_TAIL + "Name")
    assert not known("Qw3" + KEY_TAIL)


def test_in_git_follows_no_link_and_survives_a_bad_commit(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text(KEY_TAIL)
    folder = repo(tmp_path / "r", {"a.py": "x\n"}, links={"link": str(outside)})
    assert not in_git(folder, "HEAD")(KEY_TAIL)
    assert not in_git(folder, "0" * 40)(KEY_TAIL)
    assert not in_git(tmp_path / "missing", "HEAD")(KEY_TAIL)


def test_has_commit_knows_only_a_commit_the_folder_holds(tmp_path):
    folder = repo(tmp_path / "r", {"a.py": "x\n"})
    assert has_commit(folder, "HEAD")
    assert not has_commit(folder, "1" * 40)
    assert not has_commit(folder, "--all") and not has_commit(folder, "")
    assert not has_commit(tmp_path / "missing", "HEAD")


def test_in_git_reads_no_repository_above_the_folder(tmp_path):
    folder = repo(tmp_path, {"sub/b.py": f"X = '{KEY_TAIL}'\n"})
    assert in_git(folder, "HEAD")(KEY_TAIL)
    assert not in_git(folder / "sub", "HEAD")(KEY_TAIL)
