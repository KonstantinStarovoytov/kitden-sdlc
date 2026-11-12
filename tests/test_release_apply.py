import re
from pathlib import Path

import pytest

from release_apply import (
    apply,
    apply_images,
    hand_checks,
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


def test_apply_images_copies_only_scene_files(tmp_path):
    root = make_root(tmp_path)
    images = tmp_path / "images"
    images.mkdir()
    (images / "pick-light.webp").write_bytes(b"new")
    (images / "pick-dark.webp").write_bytes(b"new")
    written = apply_images(root, images, ["pick"])
    assert written == [
        Path("docs/images/readme/pick-dark.webp"),
        Path("docs/images/readme/pick-light.webp"),
    ]
    assert (root / "docs/images/readme/pick-dark.webp").read_bytes() == b"new"


def test_apply_images_refuses_other_files(tmp_path):
    root = make_root(tmp_path)
    images = tmp_path / "images"
    images.mkdir()
    (images / "pick-light.webp").write_bytes(b"new")
    (images / "evil.svg").write_bytes(b"<svg/>")
    with pytest.raises(ValueError, match="evil.svg"):
        apply_images(root, images, ["pick"])
    assert (root / "docs/images/readme/pick-light.webp").read_bytes() == b"old"


def test_apply_images_refuses_an_unlisted_scene(tmp_path):
    root = make_root(tmp_path)
    images = tmp_path / "images"
    images.mkdir()
    (images / "library-light.png").write_bytes(b"new")
    with pytest.raises(ValueError, match="library-light.png"):
        apply_images(root, images, ["pick"])


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


def test_cli_apply_writes_lists(tmp_path):
    root = make_root(tmp_path)
    out = make_out(tmp_path, FULL_OUT)
    images = tmp_path / "images"
    images.mkdir()
    (images / "pick-light.webp").write_bytes(b"new")
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
            "--scenes",
            "pick",
            "--lists",
            str(lists),
        ]
    )
    assert code == 0
    assert (lists / "content.txt").read_text().split() == [
        "docs/releases/v0.9.0.md",
        "README.md",
        "docs/images/readme/pick-light.webp",
    ]
    assert (lists / "policy.txt").read_text().split() == ["PRIVACY.md", "listing.toml"]


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
