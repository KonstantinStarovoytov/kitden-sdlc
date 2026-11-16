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


# Task 16, finished in task 17: the nightly run on the map, and the desk that reads it.

def test_the_nightly_run_is_on_the_map_with_its_jobs_and_links():
    assert map_ids(HTML)["k-nightly"] == ("k", "nightly.yml")
    assert map_jobs(HTML)["k-nightly"] == ["systems", "clients", "browser"]
    links = map_links(HTML)
    assert links["s-desk"]["reads"] == ["k-nightly", "k-latest-deps"]
    assert links["k-nightly"]["readBy"] == links["k-latest-deps"]["readBy"] == ["s-desk"]
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
    assert map_links(HTML)["s-desk"] == {"reads": ["k-nightly", "k-latest-deps"]}
    for kind, label in (("reads", "Reads"), ("readBy", "Read by")):
        shown = (f"(w.{kind} ? '<div class=\"fact\"><span class=\"cap\">{label}</span>"
                 f"<span>' + w.{kind}.map(ref)")
        assert shown in HTML, kind


def test_a_link_to_a_workflow_opens_it_because_the_start_keeps_the_hash():
    start = HTML.index("const first = location.hash.slice(1);")
    assert HTML.index("select('s-review'); setHash(first);") > start
    assert "setHash('')" not in HTML


def test_the_every_day_story_draws_the_nightly_run_and_who_reads_it():
    day = HTML.split("day:{")[1].split("\n};")[0]
    assert "{id:'c0', kind:'clock', t:'02:37'}, {wf:'k-nightly'}" in day
    assert "t:'Breaks found before your users find them'" in day and "a real browser" in day
    assert "red: a ci-failure issue" in day and "emails" not in day
    assert "['c0','k-nightly','','h'],['k-nightly','d0','','h']" in day
    assert day.count("'s-desk','the desk reads it'") == 2
    assert "['d0','s-desk','the desk reads it','t']" in day
    assert "['d2','s-desk','the desk reads it','r']" in day


def test_the_every_day_clock_runs_in_time_order():
    """The wires into the desk go down the gap before the last column, so no row moves."""
    rows = HTML.split("day:{")[1].split("rows:[")[1].split("\n    ],")[0]
    times = re.findall(r"kind:'clock', t:'(\d\d:\d\d)'", rows)
    assert times == sorted(times) and times[0] == "02:37" and len(times) == 6


def test_both_wires_the_desk_reads_run_from_a_result_card_into_the_desk():
    day = HTML.split("day:{")[1].split("\n};")[0]
    things = set(re.findall(r"\{id:'(\w+)', kind:'thing'", day))
    edges = re.findall(r"\['(\w+)','([\w-]+)','the desk reads it','(\w)'\]", day)
    assert sorted(edges) == [("d0", "s-desk", "t"), ("d2", "s-desk", "r")]
    assert {"d0", "d2"} <= things
    assert "if (shape === 'r')" in HTML and "if (shape === 't')" in HTML


def test_pointing_at_the_desk_lists_what_it_reads_not_what_starts_it():
    assert "const READS = 'the desk reads it';" in HTML
    assert "if (why === READS) (b === id ? reads : readBy)" in HTML
    assert "'Reads: ' + esc(reads.join(', '))" in HTML and "' Read by: '" in HTML


def test_every_step_in_the_workflows_view_shows_its_number_never_an_icon():
    assert "STEPIC" not in HTML and "stepIcon" not in HTML
    numbered = re.findall(r"<span class=\"si\">' \+ (.+?) \+ '</span>", HTML)
    assert numbered == ["(i + 1)"]
    assert "<span class=\"n\">' + (i + 1) + '</span>" in HTML  # the story cards' steps


def test_every_step_is_one_short_line_with_at_most_one_short_why():
    """A step reads 'what it does|why': at most 12 words, then at most 14. A job's `about`
    line, which says what its steps share, is at most 14 words too."""
    wf = HTML.split("\nconst WF = [\n")[1].split("\n];")[0]
    hosts = re.search(r"\nconst HOSTS = '([^'\\]*)';", HTML).group(1)
    lists = re.findall(r"steps:\[((?:HOSTS|'[^'\\]*'|\s|,)*)\]", wf)
    assert len(lists) == sum(len(jobs) for jobs in map_jobs(HTML).values()) == 48
    steps = [hosts if s == "HOSTS" else s[1:-1] for found in lists
             for s in re.findall(r"HOSTS|'[^']*'", found)]
    assert len(steps) > 100
    for text in steps:
        what, *why = text.split("|")
        assert len(why) <= 1 and 0 < len(what.split()) <= 12, text
        assert all(0 < len(w.split()) <= 14 for w in why), text
    for about in re.findall(r"about:'([^'\\]*)'", wf):
        assert 0 < len(about.split()) <= 14, about
    assert "'<span class=\"why\">'" in HTML


def test_the_tools_view_shows_what_the_nightly_tests_use():
    tools = HTML.split("const TOOLS = [")[1].split("\n];")[0]
    used = HTML.split("const USED = {")[1].split("\n};")[0]
    assert "['shield','macOS Keychain','real secret tests']" in tools
    assert "['shield','GNOME Keyring','real secret tests']" in tools
    assert "'macOS Keychain':['k-nightly']" in used
    assert "'GNOME Keyring':['k-release','k-nightly']" in used
    for tile in ("['Clients watched and tested', [",
                 "['claude','Claude Code','watched, tested nightly']",
                 "['openai','Codex','watched, tested nightly']",
                 "['cursor','Cursor','watched only']"):
        assert tile in tools, tile
    for name in ("Claude Code", "Codex", "pytest", "Node", "Playwright"):
        assert re.search(rf"'{name}':\[[^\]]*'k-nightly'", used), name
    assert "'Cursor':['s-watch']" in used
    assert "'GitHub Actions':'All 22 workflows'" in used and len(map_ids(HTML)) == 22
