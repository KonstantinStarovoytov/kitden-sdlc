import json
import re
import subprocess
from pathlib import Path

import pytest

from release_apply import (
    all_scenes,
    apply,
    apply_images,
    hand_checks,
    is_stale,
    main,
    pr_body,
    scenes,
    target_for,
)


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "kitden"
    (root / "docs/releases").mkdir(parents=True)
    (root / "docs/images/readme").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "kitden"\nversion = "0.9.0"\n')
    (root / "README.md").write_text("old readme\n")
    (root / "PRIVACY.md").write_text("old privacy\n")
    (root / "SECURITY.md").write_text("security\n")
    (root / "listing.toml").write_text('short = "old"\n')
    for name in ("library-light.png", "library-dark.png", "pick-light.webp", "pick-dark.webp"):
        (root / "docs/images/readme" / name).write_bytes(b"old")
    return root


def make_out(tmp_path: Path, files: dict[str, str]) -> Path:
    out = tmp_path / "out"
    for name, text in files.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return out


FULL_OUT = {
    "notes.md": "# Kitden 0.9.0 — a theme\n",
    "README.md": "new readme\n",
    "policy/PRIVACY.md": "new privacy\n",
    "policy/listing.toml": 'short = "new"\n',
    "findings.md": "## Release notes\n\nA finding.\n",
    "version.txt": "0.9.0\n",
    "scenes.txt": "pick\n",
}


def test_apply_splits_policy_commit(tmp_path):
    root = make_root(tmp_path)
    out = make_out(tmp_path, FULL_OUT)

    content, policy = apply(root, out)

    assert content == [Path("docs/releases/v0.9.0.md"), Path("README.md")]
    assert policy == [Path("PRIVACY.md"), Path("listing.toml")]
    assert (root / "docs/releases/v0.9.0.md").read_text() == "# Kitden 0.9.0 — a theme\n"
    assert (root / "README.md").read_text() == "new readme\n"
    assert (root / "PRIVACY.md").read_text() == "new privacy\n"
    assert (root / "listing.toml").read_text() == 'short = "new"\n'
    assert (root / "SECURITY.md").read_text() == "security\n"
    # findings, version and scenes are read by the workflow, never written into Kitden.
    assert not (root / "findings.md").exists()
    assert not (root / "version.txt").exists()


def test_apply_leaves_out_unchanged_files(tmp_path):
    root = make_root(tmp_path)
    out = make_out(
        tmp_path,
        {"notes.md": "# n\n", "README.md": "old readme\n", "policy/SECURITY.md": "security\n"},
    )
    content, policy = apply(root, out, version="0.9.0")
    assert content == [Path("docs/releases/v0.9.0.md")]
    assert policy == []


@pytest.mark.parametrize(
    "name",
    [
        ".github/workflows/x.yml",
        "policy/CHANGELOG.md",
        "policy/sub/PRIVACY.md",
        "ROADMAP.md",
        "src/kitden/__init__.py",
        "docs/releases/v0.9.0.md",
        "AGENTS.md",
    ],
)
def test_apply_refuses_other_paths(tmp_path, name):
    root = make_root(tmp_path)
    out = make_out(tmp_path, {"README.md": "new readme\n", name: "anything\n"})
    with pytest.raises(ValueError, match="not allowed"):
        apply(root, out)
    # Nothing is written when one file is refused.
    assert (root / "README.md").read_text() == "old readme\n"
    assert not (root / ".github").exists()


def test_apply_refuses_a_link_in_out(tmp_path):
    root = make_root(tmp_path)
    out = make_out(tmp_path, {})
    out.mkdir(exist_ok=True)
    (out / "README.md").symlink_to(tmp_path / "secret.txt")
    (tmp_path / "secret.txt").write_text("secret\n")
    with pytest.raises(ValueError, match="link"):
        apply(root, out)
    assert (root / "README.md").read_text() == "old readme\n"


def test_apply_refuses_a_linked_policy_folder(tmp_path):
    root = make_root(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "PRIVACY.md").write_text("x\n")
    out = make_out(tmp_path, {})
    out.mkdir(exist_ok=True)
    (out / "policy").symlink_to(elsewhere)
    with pytest.raises(ValueError, match="link"):
        apply(root, out)


def test_apply_refuses_to_write_through_a_link_in_kitden(tmp_path):
    root = make_root(tmp_path)
    (root / "README.md").unlink()
    (root / "README.md").symlink_to(tmp_path / "outside.md")
    out = make_out(tmp_path, {"README.md": "new\n"})
    with pytest.raises(ValueError, match="link"):
        apply(root, out)
    assert not (tmp_path / "outside.md").exists()


def test_apply_refuses_a_bad_version(tmp_path):
    root = make_root(tmp_path)
    out = make_out(tmp_path, {"notes.md": "# n\n"})
    with pytest.raises(ValueError, match="version"):
        apply(root, out, version="../../x")


def test_apply_refuses_a_huge_file(tmp_path):
    root = make_root(tmp_path)
    out = make_out(tmp_path, {"README.md": "x" * 600_000})
    with pytest.raises(ValueError, match="large"):
        apply(root, out)


@pytest.mark.parametrize(
    "name", ["../README.md", "/etc/passwd", "policy/../README.md", "./README.md", "policy/"]
)
def test_target_for_refuses_odd_names(name):
    with pytest.raises(ValueError):
        target_for(name, "0.9.0")


def test_target_for_maps_out_to_kitden():
    assert target_for("notes.md", "0.9.0") == (Path("docs/releases/v0.9.0.md"), "content")
    assert target_for("README.md", "0.9.0") == (Path("README.md"), "content")
    assert target_for("policy/AI_POLICY.md", "0.9.0") == (Path("AI_POLICY.md"), "policy")
    assert target_for("findings.md", "0.9.0") is None
    assert target_for("scenes.txt", "0.9.0") is None
    assert target_for("version.txt", "0.9.0") is None


def test_scenes_keeps_known_names(tmp_path):
    root = make_root(tmp_path)
    text = "pick\n\nlibrary\npick\nnew-scene\n../x\n$(id)\n"
    assert scenes(text, root / "docs/images/readme") == ["pick", "library"]


def make_images(tmp_path: Path, files: dict[str, bytes | str]) -> Path:
    images = tmp_path / "images"
    images.mkdir()
    for name, data in files.items():
        (images / name).write_bytes(data if isinstance(data, bytes) else data.encode())
    return images


def test_all_scenes_lists_what_has_pictures(tmp_path):
    root = make_root(tmp_path)
    assert all_scenes(root / "docs/images/readme") == ["library", "pick"]
    assert all_scenes(tmp_path / "none") == []


def test_a_still_goes_in_only_when_its_bytes_differ(tmp_path):
    root = make_root(tmp_path)
    images = make_images(
        tmp_path, {"library-light.png": b"new", "library-dark.png": b"old", "results.json": "{}"}
    )
    paths, states = apply_images(root, images, {"library": "", "pick": ""})
    assert paths == [
        Path("docs/images/readme/library-light.png"),
        Path("docs/images/readme/library-dark.png"),
    ]
    assert states["library"] == "changed"
    assert (root / "docs/images/readme/library-light.png").read_bytes() == b"new"
    assert (root / "docs/images/readme/library-dark.png").read_bytes() == b"old"


def test_a_still_with_the_same_bytes_is_the_same(tmp_path):
    root = make_root(tmp_path)
    images = make_images(tmp_path, {"library-light.png": b"old", "library-dark.png": b"old"})
    paths, states = apply_images(root, images, {"library": "", "pick": ""})
    assert paths == [] and states["library"] == "the same"


def test_an_animation_goes_in_only_when_stale(tmp_path):
    root = make_root(tmp_path)
    images = make_images(tmp_path, {"pick-light.webp": b"new", "pick-dark.webp": b"new"})
    results = {"library": "", "pick": ""}
    paths, states = apply_images(root, images, results, stale=lambda picture: False)
    assert paths == [] and states["pick"] == "not needed"
    assert (root / "docs/images/readme/pick-light.webp").read_bytes() == b"old"

    seen = []

    def stale(picture):
        seen.append(picture)
        return True

    paths, states = apply_images(root, images, results, stale=stale)
    assert states["pick"] == "changed"
    assert paths == [
        Path("docs/images/readme/pick-light.webp"),
        Path("docs/images/readme/pick-dark.webp"),
    ]
    assert seen == [root / "docs/images/readme/pick-light.webp"]
    assert (root / "docs/images/readme/pick-dark.webp").read_bytes() == b"new"


def test_a_scene_the_job_could_not_make_is_failed(tmp_path):
    root = make_root(tmp_path)
    images = make_images(
        tmp_path,
        {
            "library-light.png": b"new",
            "library-dark.png": b"new",
            "pick-light.webp": b"new",
            "pick-dark.webp": b"new",
        },
    )
    paths, states = apply_images(
        root, images, {"library": "", "pick": "TimeoutError"}, stale=lambda picture: True
    )
    assert states == {"library": "changed", "pick": "failed"}
    assert (root / "docs/images/readme/pick-light.webp").read_bytes() == b"old"
    assert all("pick" not in str(path) for path in paths)
    # A scene missing from the results failed too.
    _, states = apply_images(root, images, {"library": ""}, stale=lambda picture: True)
    assert states["pick"] == "failed"


def test_no_result_file_fails_every_scene(tmp_path):
    root = make_root(tmp_path)
    paths, states = apply_images(root, tmp_path / "none", None)
    assert paths == [] and set(states.values()) == {"failed"}
    assert set(states) == {"library", "pick"}
    images = make_images(tmp_path, {"library-light.png": b"new"})
    paths, states = apply_images(root, images, None)
    assert paths == [] and set(states.values()) == {"failed"}
    assert (root / "docs/images/readme/library-light.png").read_bytes() == b"old"


def test_an_unknown_file_among_the_pictures_is_refused(tmp_path):
    root = make_root(tmp_path)
    images = make_images(
        tmp_path, {"pick-light.webp": b"new", "evil.svg": b"<svg/>", "results.json": "{}"}
    )
    with pytest.raises(ValueError, match="evil.svg"):
        apply_images(root, images, {"library": "", "pick": ""}, stale=lambda picture: True)
    assert (root / "docs/images/readme/pick-light.webp").read_bytes() == b"old"


def test_a_picture_of_an_unknown_scene_is_refused(tmp_path):
    root = make_root(tmp_path)
    images = make_images(tmp_path, {"brand-new-light.png": b"new"})
    with pytest.raises(ValueError, match="brand-new-light.png"):
        apply_images(root, images, {"library": ""})


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def commit(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text)
    git(root, "add", name)
    git(root, "commit", "-m", f"add {name}")


def test_is_stale_looks_at_commits_after_the_picture(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    picture = root / "docs/images/readme/pick-light.webp"
    commit(root, "README.md", "text")
    assert is_stale(root, picture)  # never committed

    commit(root, "docs/images/readme/pick-light.webp", "v1")
    assert not is_stale(root, picture)
    commit(root, "docs/x.md", "text")
    assert not is_stale(root, picture)
    commit(root, "src/kitden/web/x.js", "code")
    assert is_stale(root, picture)
    commit(root, "docs/images/readme/pick-light.webp", "v2")
    assert not is_stale(root, picture)
    commit(root, "scripts/record_scenes.py", "code")
    assert is_stale(root, picture)


DEVELOPMENT = """# Development

## Check before a release

The tests use fake servers. Before a release that touches the Kitden gateway, check it once by
hand in each of Claude Code, Codex and Cursor.

1. Move a server into the gateway.
2. Turn one tool off.

Not run yet for steps 1 to 2.

Before a release that adds, removes or puts back items, also check these once by hand:

3. Remove a plugin.

Before a release that touches secrets, also check the Keychain once by hand:

4. Move the server into the gateway. A Keychain item appears.

Before a release that touches the weather, also check this:

5. Look outside.

## Release

1. Not a check.
"""


def test_hand_checks_pick_the_areas_touched():
    picked = "\n".join(hand_checks(DEVELOPMENT, ["src/kitden/local_gateway/proxy.py", "README.md"]))
    assert "1. Move a server into the gateway." in picked
    assert "Not run yet for steps 1 to 2." in picked
    assert "3. Remove a plugin." not in picked
    assert "Keychain" not in picked
    # An area this script does not know is always listed: the owner decides.
    assert "5. Look outside." in picked
    assert "Not a check" not in picked


def test_hand_checks_secrets_and_items():
    picked = "\n".join(
        hand_checks(
            DEVELOPMENT, ["src/kitden/local_gateway/keychain.py", "src/kitden/changes/engine.py"]
        )
    )
    assert "4. Move the server into the gateway." in picked
    assert "3. Remove a plugin." in picked


def test_hand_checks_ignore_docs_only():
    picked = "\n".join(hand_checks(DEVELOPMENT, ["docs/gateway.md", "tests/unit/test_keychain.py"]))
    assert "Move a server" not in picked
    assert "Remove a plugin" not in picked
    assert "Look outside" in picked


def test_hand_checks_without_the_section():
    assert hand_checks("# Development\n", ["src/kitden/cli.py"]) == []


def test_pr_body_has_findings_checks_and_merge_note():
    body = pr_body(
        findings="## Release notes\n\nThanks @someone.\n",
        checks=["Before a release that touches X:\n\n1. Do it."],
        unrecorded=["pick"],
    )
    assert "> #### Release notes" in body
    assert "@\u2060someone" in body
    assert "1. Do it." in body
    assert "`pick`" in body and "record" in body
    assert "merge commit" in body and "not squash" in body


def test_findings_close_no_issue():
    """A closing keyword in the findings would close that issue when the PR merges."""
    for text in (
        "Fixes #12",
        "fixed: #12",
        "This closes owner/repo#3.",
        "RESOLVES   #7",
        "Resolved https://github.com/o/r/issues/4",
        "close #1",
    ):
        body = pr_body(findings=text, checks=[], unrecorded=[])
        assert not re.search(
            r"(?i)\b(close[sd]?|fix(e[sd])?|resolve[sd]?)[ \t]*:?[ \t]*([\w.-]+/[\w.-]+)?#\d", body
        ), text
        assert not re.search(
            r"(?i)\b(close[sd]?|fix(e[sd])?|resolve[sd]?)[ \t]*:?[ \t]*https://", body
        )
        assert "\u2060" in body
    # Words that only start the same way, or have no issue after them, stay as they are.
    body = pr_body(
        findings="The fix is small. Fixes the README. Closest #1st", checks=[], unrecorded=[]
    )
    assert "\u2060" not in body


def test_findings_cannot_pass_for_the_scripted_sections():
    findings = "# Hand checks\n\nNone needed.\n\n## Merge\n\nSquash it.\n\n###### Small\n#5 is fine"
    body = pr_body(findings=findings, checks=[], unrecorded=[])
    assert body.count("\n## Hand checks\n") == 1
    assert body.count("\n## Merge\n") == 1
    assert "> #### Hand checks" in body and "> #### Merge" in body
    assert "> ###### Small" in body
    assert "> #5 is fine" in body  # not a heading: no space after the #
    # Every line of the findings is inside the quote.
    section = body.split("## Findings\n\n")[1].split("\n\n## Hand checks")[0]
    assert all(line.startswith(">") for line in section.splitlines())


def test_pr_body_without_findings_or_checks():
    body = pr_body(findings="", checks=[], unrecorded=[])
    assert "No findings" in body
    assert "No real-client check" in body
    assert "record" not in body


def test_pr_body_refuses_secret_like_text():
    with pytest.raises(ValueError, match="secret"):
        pr_body(findings="ghp_" + "a" * 36, checks=[], unrecorded=[])


def test_pr_body_cuts_long_findings():
    body = pr_body(findings="x" * 100_000, checks=[], unrecorded=[])
    assert len(body) < 65_000


def test_cli_apply_writes_lists_and_pictures(tmp_path):
    root = make_root(tmp_path)
    out = make_out(tmp_path, FULL_OUT)
    images = make_images(
        tmp_path,
        {
            "library-light.png": b"new",
            "library-dark.png": b"old",
            "results.json": json.dumps({"library": "", "pick": "TimeoutError"}),
        },
    )
    lists = tmp_path / "lists"
    code = main(
        [
            "apply",
            str(root),
            str(out),
            "--version",
            "0.9.0",
            "--images",
            str(images),
            "--results",
            str(images / "results.json"),
            "--lists",
            str(lists),
        ]
    )
    assert code == 0
    assert (lists / "content.txt").read_text().split() == [
        "docs/releases/v0.9.0.md",
        "README.md",
        "docs/images/readme/library-light.png",
        "docs/images/readme/library-dark.png",
    ]
    assert (lists / "policy.txt").read_text().split() == ["PRIVACY.md", "listing.toml"]
    assert json.loads((lists / "pictures.json").read_text()) == {
        "library": "changed",
        "pick": "failed",
    }


def test_cli_apply_without_results_fails_every_scene(tmp_path):
    root = make_root(tmp_path)
    out = make_out(tmp_path, {})
    images = make_images(tmp_path, {"library-light.png": b"new"})
    lists = tmp_path / "lists"
    args = ["apply", str(root), str(out), "--version", "0.9.0", "--lists", str(lists)]
    assert main([*args, "--images", str(images), "--results", str(images / "results.json")]) == 0
    assert json.loads((lists / "pictures.json").read_text()) == {
        "library": "failed",
        "pick": "failed",
    }
    assert (root / "docs/images/readme/library-light.png").read_bytes() == b"old"


def test_cli_apply_without_images_writes_empty_pictures(tmp_path):
    root = make_root(tmp_path)
    out = make_out(tmp_path, {})
    lists = tmp_path / "lists"
    code = main(["apply", str(root), str(out), "--version", "0.9.0", "--lists", str(lists)])
    assert code == 0
    assert json.loads((lists / "pictures.json").read_text()) == {}


def test_a_recorded_scene_without_its_pictures_is_failed(tmp_path):
    root = make_root(tmp_path)
    images = make_images(tmp_path, {"library-light.png": b"new"})  # no dark one
    paths, states = apply_images(root, images, {"library": "", "pick": ""})
    assert paths == [] and states == {"library": "failed", "pick": "failed"}


def test_cli_all_scenes(tmp_path, capsys):
    root = make_root(tmp_path)
    assert main(["all-scenes", str(root / "docs/images/readme")]) == 0
    assert capsys.readouterr().out.strip() == "library pick"


def test_cli_apply_refusal_exits_1(tmp_path, capsys):
    root = make_root(tmp_path)
    out = make_out(tmp_path, {".github/workflows/x.yml": "x"})
    code = main(["apply", str(root), str(out), "--version", "0.9.0", "--lists", str(tmp_path)])
    assert code == 1
    assert "not allowed" in capsys.readouterr().out


def test_cli_scenes(tmp_path, capsys):
    root = make_root(tmp_path)
    (tmp_path / "scenes.txt").write_text("pick\nnope\n")
    assert main(["scenes", str(tmp_path / "scenes.txt"), str(root / "docs/images/readme")]) == 0
    assert capsys.readouterr().out.strip() == "pick"
    assert main(["scenes", str(tmp_path / "missing.txt"), str(root / "docs/images/readme")]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_cli_body(tmp_path):
    (tmp_path / "findings.md").write_text("## README\n\nCut a line.\n")
    (tmp_path / "development.md").write_text(DEVELOPMENT)
    (tmp_path / "changed.txt").write_text("src/kitden/gateways.py\n")
    code = main(
        [
            "body",
            "--findings",
            str(tmp_path / "findings.md"),
            "--development",
            str(tmp_path / "development.md"),
            "--changed",
            str(tmp_path / "changed.txt"),
            "--unrecorded",
            "",
            "--out",
            str(tmp_path / "body.md"),
        ]
    )
    assert code == 0
    body = (tmp_path / "body.md").read_text()
    assert "Cut a line." in body and "Move a server" in body


def test_cli_body_with_missing_findings(tmp_path):
    (tmp_path / "development.md").write_text(DEVELOPMENT)
    (tmp_path / "changed.txt").write_text("")
    code = main(
        [
            "body",
            "--findings",
            str(tmp_path / "none.md"),
            "--development",
            str(tmp_path / "development.md"),
            "--changed",
            str(tmp_path / "changed.txt"),
            "--out",
            str(tmp_path / "body.md"),
        ]
    )
    assert code == 0
    assert "No findings" in (tmp_path / "body.md").read_text()


def test_apply_refuses_secret_like_text(tmp_path):
    root = make_root(tmp_path)
    out = make_out(tmp_path, {"notes.md": "# n\n", "README.md": "token ghp_" + "a" * 36 + "\n"})
    with pytest.raises(ValueError, match="secret"):
        apply(root, out)
    assert not (root / "docs/releases/v0.9.0.md").exists()


def test_guide_and_plugin_readme_go_to_their_places(tmp_path):
    root = make_root(tmp_path)
    out = make_out(tmp_path, {"guide.md": "new guide\n", "plugin/README.md": "new plugin\n"})
    content, policy = apply(root, out, "0.9.1")
    assert content == [Path("docs/guide.md")]
    assert policy == [Path("plugins/kitden/README.md")]
    assert (root / "plugins/kitden/README.md").read_text() == "new plugin\n"


GATEWAY_DEVELOPMENT = """# Development

## Check before a release

Before a release that touches the Kitden gateway. Check it once by hand.

1. Move a server into the gateway.

Before a release that touches the Gateway map. Also check the map once by hand:

2. Drag a node.
"""


def test_the_gateway_page_is_not_the_gateway():
    doc = GATEWAY_DEVELOPMENT
    page = ["src/kitden/web/static/js/gateway.js", "src/kitden/web/static/js/map-view.js"]
    picked = hand_checks(doc, page)
    assert [p.split(".")[0] for p in picked] == ["Before a release that touches the Gateway map"]
    assert hand_checks(doc, ["src/kitden/web/static/js/library-map.js"]) == []
    server = hand_checks(doc, ["src/kitden/local_gateway/proxy.py"])
    assert any("the Kitden gateway" in p for p in server)
