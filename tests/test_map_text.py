"""The map's names, What and Why come from the workflow files, and stay so."""
import re
from pathlib import Path

import yaml

from map_text import differences, header, map_ids, map_jobs, read_block, write_block

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
