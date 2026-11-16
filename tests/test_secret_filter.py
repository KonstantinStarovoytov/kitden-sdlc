import pytest

from post_findings import SECRET_LIKE
from secret_filter import clean, has_commit, in_git, in_text, random_runs, unknown_runs
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


# clean: outside text with a secret in it is left out

TOKEN = "ghp_" + "a" * 36
FIELDS = ("heading", "text")


def passage(text="plain words", heading="Install", **extra):
    return {"url": "https://code.claude.com/docs/en/a", "heading": heading, "text": text,
            **extra}


def test_clean_items_are_all_kept_as_they_are():
    items = [passage(), passage("other words")]
    kept, left_out = clean(items, FIELDS, SECRET_LIKE)
    assert kept == items and left_out == 0
    assert all(a is b for a, b in zip(kept, items, strict=True))
    assert clean([], FIELDS, SECRET_LIKE) == ([], 0)


@pytest.mark.parametrize("field", FIELDS)
def test_an_item_with_a_token_in_a_named_field_is_left_out_and_counted(field):
    bad = passage(**{field: f"set it to {TOKEN} first"})
    first, last = passage("first"), passage("last")
    kept, left_out = clean([first, bad, last], FIELDS, SECRET_LIKE)
    assert kept == [first, last] and left_out == 1


def test_an_item_with_a_long_random_string_is_left_out_and_counted():
    bad = passage(f"the key ends in {KEY_TAIL}")
    assert not SECRET_LIKE.search(bad["text"])  # only the random-string check finds it
    kept, left_out = clean([bad, passage()], FIELDS, SECRET_LIKE)
    assert kept == [passage()] and left_out == 1


def test_a_field_that_is_not_named_is_not_looked_at():
    item = passage(note=f"{TOKEN} {KEY_TAIL}", url=f"https://x/{KEY_TAIL}")
    assert clean([item], FIELDS, SECRET_LIKE) == ([item], 0)


@pytest.mark.parametrize("bad", [
    {"heading": "Install"},  # no text
    passage(None),
    passage(3),
    passage(["a", "list"]),
    passage(heading=b"bytes"),
])
def test_an_item_whose_named_field_is_missing_or_not_a_string_is_left_out(bad):
    kept, left_out = clean([bad, passage()], FIELDS, SECRET_LIKE)
    assert kept == [passage()] and left_out == 1


@pytest.mark.parametrize("bad", [None, "text", 3, ["heading", "text"]])
def test_an_item_that_is_not_a_dict_is_left_out_without_an_error(bad):
    kept, left_out = clean([bad, passage()], FIELDS, SECRET_LIKE)
    assert kept == [passage()] and left_out == 1


def test_clean_does_not_change_the_list_it_is_given():
    items = [passage(TOKEN), passage()]
    clean(items, FIELDS, SECRET_LIKE)
    assert items == [passage(TOKEN), passage()]


def test_clean_uses_the_pattern_it_is_given():
    import re

    kept, left_out = clean([passage("say SESAME"), passage()], FIELDS, re.compile("SESAME"))
    assert kept == [passage()] and left_out == 1
