import pytest

from post_findings import SECRET_LIKE
from secret_filter import (
    clean,
    has_commit,
    in_git,
    in_text,
    kept_marks,
    random_runs,
    unknown_runs,
)
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


@pytest.mark.parametrize("mark", ["\u200b", "\u200d", "\ufeff"])
def test_a_token_split_by_a_format_character_is_left_out(mark):
    from doc_address import clean_heading

    heading = "ghp_" + "aB3" * 5 + mark + "cD4" * 6
    assert not SECRET_LIKE.search(heading)  # as written, the mark hides it
    assert SECRET_LIKE.search(clean_heading(heading))  # and cleaning would join it again
    kept, left_out = clean([passage(heading=heading), passage()], FIELDS, SECRET_LIKE)
    assert kept == [passage()] and left_out == 1


def test_a_random_string_split_by_a_format_character_is_left_out():
    half = len(KEY_TAIL) // 2
    text = KEY_TAIL[:half] + "\u200b" + KEY_TAIL[half:]
    assert not random_runs(text)
    assert clean([passage(text)], FIELDS, SECRET_LIKE) == ([], 1)


def test_harmless_format_characters_without_a_secret_stay():
    item = passage("zero\u200bwidth and joined\u200dwords\ufeff", heading="\u200bInstall")
    assert clean([item], FIELDS, SECRET_LIKE) == ([item], 0)


def test_clean_with_no_fields_is_a_caller_bug():
    with pytest.raises(ValueError):
        clean([passage()], (), SECRET_LIKE)


# Every character clean_heading drops can split a token that cleaning then joins again.
SEPARATORS = ["*", "`", "'", "#", "!", "|", "\u0301", "\ufe0f", "\x00", "\x7f",
              "\ue000", "\u0378", "\u200b", "\u200d", "\ufeff"]


@pytest.mark.parametrize("mark", SEPARATORS)
def test_a_token_split_by_any_mark_that_cleaning_drops_is_left_out(mark):
    from doc_address import clean_heading

    heading = "ghp_" + "aB3" * 5 + mark + "cD4" * 6
    assert not SECRET_LIKE.search(heading)
    assert SECRET_LIKE.search(clean_heading(heading))
    kept, left_out = clean([passage(heading=heading), passage()], FIELDS, SECRET_LIKE,
                           kept=("heading",))
    assert kept == [passage()] and left_out == 1


def test_a_field_not_in_kept_is_not_checked_as_cleaning_keeps_it():
    heading = "ghp_" + "aB3" * 5 + "*" + "cD4" * 6
    item = passage(heading=heading)
    assert clean([item], FIELDS, SECRET_LIKE) == ([item], 0)
    assert clean([item], FIELDS, SECRET_LIKE, kept=("heading",)) == ([], 1)


@pytest.mark.parametrize("kept", [(), ("heading",)])
def test_a_doc_line_that_sets_a_model_stays(kept):
    item = passage("export ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-5\n"
                   "Set `ANTHROPIC_MODEL` to pick the model.")
    assert clean([item], FIELDS, SECRET_LIKE, kept=kept) == ([item], 0)


@pytest.mark.parametrize("mark", ["\u200b", "\u200d", "\ufeff"])
def test_a_token_in_text_split_by_a_format_character_is_still_left_out(mark):
    item = passage("token: ghp_" + "aB3" * 5 + mark + "cD4" * 6)
    assert clean([item], FIELDS, SECRET_LIKE, kept=("heading",)) == ([], 1)


def test_a_kept_field_that_is_not_checked_is_a_caller_bug():
    with pytest.raises(ValueError):
        clean([passage()], ("text",), SECRET_LIKE, kept=("heading",))


def test_an_ordinary_heading_with_punctuation_stays():
    item = passage(heading="Install the plugin: step 2 (macOS)",
                   text="Run `zork --frob`, then *restart*! It's #1 | done.")
    assert clean([item], FIELDS, SECRET_LIKE, kept=("heading",)) == ([item], 0)


def test_kept_marks_keeps_letters_digits_spaces_and_a_few_marks():
    assert kept_marks("a*b`c'd#e!f|g\u0301h\x00i é 2-a_b.c,d:e(f)/g") == (
        "abcdefghi é 2-a_b.c,d:e(f)/g")
    assert kept_marks("One\nTwo\tThree") == "One Two Three"  # no collapse, no cut


def test_clean_heading_drops_exactly_what_kept_marks_drops():
    from doc_address import clean_heading

    for code in range(0x10000):
        mark = chr(code)
        if mark.isspace() or 0xD800 <= code <= 0xDFFF:
            continue
        assert clean_heading("a" + mark + "b") == "a" + kept_marks(mark) + "b", hex(code)


def test_secret_filter_imports_only_the_standard_library():
    # The post job imports it without the project's dependencies.
    import ast
    import sys
    from pathlib import Path

    import secret_filter

    tree = ast.parse(Path(secret_filter.__file__).read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
             for a in node.names}
    names |= {node.module.split(".")[0] for node in ast.walk(tree)
              if isinstance(node, ast.ImportFrom) and node.module}
    assert names <= sys.stdlib_module_names, names - sys.stdlib_module_names
