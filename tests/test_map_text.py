"""The map's names, What and Why come from the workflow files, and stay so."""
import re
from pathlib import Path

import yaml

import map_text
from map_text import (
    differences,
    header,
    map_ids,
    map_jobs,
    map_links,
    read_block,
    write_block,
)

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "docs/map/index.html").read_text()


def test_header_reads_name_what_and_why_and_stops_at_the_bare_comment_line():
    text = "# What: does a\n# thing.\n# Why: because\n# reasons.\n#\n# More.\nname: A thing\n"
    assert header(text) == {"name": "A thing", "what": "does a thing.", "why": "because reasons."}


def test_the_maps_text_for_this_repositorys_workflows_is_what_the_files_say():
    block = read_block(HTML)
    for wf_id, (repo, file) in map_ids(HTML).items():
        assert set(block[wf_id]) == {"name", "what", "why"} and all(block[wf_id].values()), wf_id
        if repo == "s":
            assert block[wf_id] == header((ROOT / ".github/workflows" / file).read_text()), wf_id


def test_every_workflow_file_here_is_on_the_map_and_no_other():
    here = {file for repo, file in map_ids(HTML).values() if repo == "s"}
    assert here == {path.name for path in (ROOT / ".github/workflows").glob("*.yml")}


def test_every_job_the_map_names_for_a_workflow_here_is_in_its_file():
    for wf_id, (repo, file) in map_ids(HTML).items():
        if repo == "s":
            jobs = yaml.safe_load((ROOT / ".github/workflows" / file).read_text())["jobs"]
            assert set(map_jobs(HTML)[wf_id]) == set(jobs), wf_id


def test_a_stale_text_is_named_and_the_real_page_has_none():
    block = read_block(HTML)
    block["s-desk"] = {**block["s-desk"], "name": "Desk"}
    (line,) = differences(write_block(HTML, block), ROOT, None)
    assert line == 's-desk: name is "Desk", the file says "Kitden desk"'
    assert differences(HTML, ROOT, None) == []


def test_a_file_of_another_repository_that_cannot_be_read_is_a_difference():
    asked = []

    def offline(url):
        asked.append(url)
        raise OSError("offline")

    lines = differences(HTML, ROOT, offline)
    assert asked and all(url.startswith("https://") for url in asked)
    assert any(line.endswith("could not be read") for line in lines)


def test_the_page_reads_its_text_from_the_block():
    assert "getElementById('wf-text')" in HTML
    assert not re.search(r"\{id:'[\w-]+', r:'\w', file:'[\w.-]+', name:", HTML)


# Beyond the brief: the other two repositories, read through a fake.

def test_with_the_other_repositories_a_missing_and_an_extra_file_are_named(tmp_path):
    ids = map_ids(HTML)
    files = {repo: sorted(f for r, f in ids.values() if r == repo) for repo in "kt"}
    block = read_block(HTML)
    texts = {f"{r}/{f}": block[i] for i, (r, f) in ids.items() if r != "s"}
    gone = files["k"][0]
    files["k"] = [f for f in files["k"] if f != gone] + ["new.yml"]

    def fake(url):
        repo = "k" if "/kitden/" in url else "t"
        if "api.github.com" in url:
            return "[" + ",".join(f'{{"name": "{f}", "type": "file"}}' for f in files[repo]) + "]"
        text = texts[f"{repo}/{url.rsplit('/', 1)[1]}"]
        return f"# What: {text['what']}\n# Why: {text['why']}\nname: {text['name']}\n"

    lines = differences(HTML, ROOT, fake)
    gone_id = next(i for i, (r, f) in ids.items() if r == "k" and f == gone)
    assert sorted(lines) == sorted([f"{gone_id}: kitden has no {gone}",
                                    "kitden: new.yml is not on the map"])


def test_the_block_cannot_close_the_script_it_sits_in():
    block = read_block(HTML)
    block["s-desk"] = {**block["s-desk"], "what": "a </script> and <b>&</b>"}
    page = write_block(HTML, block)
    assert page.count("</script>") == HTML.count("</script>")
    assert read_block(page)["s-desk"]["what"] == "a </script> and <b>&</b>"


# The fix wave: a check that read nothing never passes, and an empty text is never written.

def _repo_fake(texts_by_file):
    """A fetch that lists the map's files in Kitden and the tap and answers each with a text."""
    files = {r: sorted(f for rr, f in map_ids(HTML).values() if rr == r) for r in "kt"}

    def fake(url):
        repo = "k" if "/kitden/" in url else "t"
        if "api.github.com" in url:
            return "[" + ",".join(f'{{"name": "{f}", "type": "file"}}' for f in files[repo]) + "]"
        return texts_by_file(repo, url.rsplit("/", 1)[1])

    return fake


def _good(repo, file):
    wf_id = next(i for i, (r, f) in map_ids(HTML).items() if (r, f) == (repo, file))
    text = read_block(HTML)[wf_id]
    return f"# What: {text['what']}\n# Why: {text['why']}\nname: {text['name']}\n"


def test_the_repositories_to_read_come_from_the_map_not_from_repo():
    def offline(url):
        raise OSError("offline")

    kitden_moved = HTML.replace("k:{name:", "k: {name:")
    assert "k: its repository is not in REPO" in differences(kitden_moved, ROOT, offline)
    both_moved = kitden_moved.replace("t:{name:", "t: {name:")
    lines = differences(both_moved, ROOT, offline)
    assert lines == ["k: its repository is not in REPO", "t: its repository is not in REPO"]


def test_an_answer_that_is_not_a_workflow_is_a_difference_and_is_not_written(tmp_path,
                                                                              monkeypatch):
    def portal(repo, file):
        return "<html>captive portal</html>" if file == "release.yml" else _good(repo, file)

    fake = _repo_fake(portal)
    lines = differences(HTML, ROOT, fake)
    assert lines == [f"k-release: its file has no {field}" for field in ("name", "what", "why")]
    page = tmp_path / "index.html"
    page.write_text(HTML)
    monkeypatch.setattr(map_text, "PAGE", page)
    assert map_text.main(["--write"], fetch=fake) == 1
    assert read_block(page.read_text())["k-release"] == read_block(HTML)["k-release"]


def test_a_file_whose_header_is_not_at_the_top_has_no_text():
    for text in ("\n# What: a.\n# Why: b.\nname: A b\n", "---\n# What: a.\n# Why: b.\nname: A b\n",
                 "# what: a.\n# why: b.\nname: A b\n"):
        said = header(text)
        assert said["what"] == "" and said["why"] == "", text


def test_the_name_loses_a_windows_line_end_and_a_trailing_comment():
    assert header("# What: a.\r\n# Why: b.\r\nname: A b\r\n")["name"] == "A b"
    assert header("# What: a.\n# Why: b.\nname: A b  # the title\n")["name"] == "A b"
    assert header("# What: a.\n# Why: b.\nname: 'A # b'\n")["name"] == "A # b"


def test_what_keeps_its_second_paragraph_and_why_stops_at_a_tool_directive():
    text = ("# What: one.\n#\n# Two.\n# Why: because.\n# zizmor: ignore[artipacked]\n"
            "name: A b\n")
    assert header(text) == {"name": "A b", "what": "one. Two.", "why": "because."}
    assert header("# What: a\n# zizmor, actionlint.\n# Why: b.\nname: A b\n")["what"] == (
        "a zizmor, actionlint.")


# Task 16: the nightly run on the map. The desk does not read the nightly runs yet (S1 is not
# built), so the map shows no `reads` link today; the tests below say so.

def test_the_nightly_run_is_on_the_map_with_its_jobs_and_no_link_yet():
    assert map_ids(HTML)["k-nightly"] == ("k", "nightly.yml")
    assert map_jobs(HTML)["k-nightly"] == ["systems", "clients", "browser"]
    links = map_links(HTML)
    assert links["k-nightly"] == {} and "reads" not in links["s-desk"]
    assert links["s-review"] == {"calledBy": ["k-agents-review"]}
    assert "All 22 workflows" in HTML


def test_every_link_names_a_workflow_on_the_map_and_has_its_other_end():
    links, ids = map_links(HTML), map_ids(HTML)
    back = {"calls": "calledBy", "calledBy": "calls", "reads": "readBy", "readBy": "reads"}
    assert any(links.values())
    for wf_id, kinds in links.items():
        for kind, others in kinds.items():
            for other in others:
                assert other in ids, (wf_id, kind, other)
                assert wf_id in links[other].get(back[kind], []), (wf_id, kind, other)


def test_a_reads_link_is_read_and_the_page_shows_it():
    page = HTML.replace("{id:'s-desk', r:'s', file:'desk.yml', kind:'own',",
                        "{id:'s-desk', r:'s', file:'desk.yml', kind:'own', reads:['k-nightly'],")
    assert map_links(page)["s-desk"] == {"reads": ["k-nightly"]}
    for kind, label in (("reads", "Reads"), ("readBy", "Read by")):
        shown = (f"(w.{kind} ? '<div class=\"fact\"><span class=\"cap\">{label}</span>"
                 f"<span>' + w.{kind}.map(ref)")
        assert shown in HTML, kind


def test_a_link_to_a_workflow_opens_it_because_the_start_keeps_the_hash():
    start = HTML.index("const first = location.hash.slice(1);")
    assert HTML.index("select('s-review'); setHash(first);") > start
    assert "setHash('')" not in HTML


def test_the_every_day_story_draws_the_nightly_run():
    day = HTML.split("day:{")[1].split("\n};")[0]
    assert "{id:'c0', kind:'clock', t:'02:37'}, {wf:'k-nightly'}" in day
    assert "t:'Nightly tests: green or red'" in day and "a real browser" in day
    assert "emails" not in day
    assert "['c0','k-nightly','','h'],['k-nightly','d0','','h']" in day
    assert "the desk reads it" not in day
