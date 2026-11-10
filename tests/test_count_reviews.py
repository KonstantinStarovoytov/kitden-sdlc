import json
from datetime import UTC, date, datetime, timedelta

import pytest

import count_reviews
from count_reviews import (
    MAINTAINER,
    Review,
    Stats,
    aggregate,
    collect,
    main,
    render,
)

NOW = datetime(2026, 11, 10, tzinfo=UTC)
BOT = {"login": "github-actions[bot]", "type": "Bot"}


def reaction(content, login=MAINTAINER):
    return {"content": content, "user": {"login": login}}


class FakeApi:
    """Holds pull requests, comments and reactions in memory; never calls gh."""

    def __init__(self):
        self.pulls: list[dict] = []  # newest first
        self.issue_comments: dict[int, list[dict]] = {}
        self.reactions: dict[int, list[dict]] = {}
        self.asked_for_comments: list[int] = []

    def list_pulls(self, repo):
        yield from self.pulls

    def list_issue_comments(self, repo, pr):
        self.asked_for_comments.append(pr)
        return self.issue_comments.get(pr, [])

    def list_issue_comment_reactions(self, repo, comment_id):
        return self.reactions.get(comment_id, [])


def pull(number, updated="2026-11-01T00:00:00Z"):
    return {"number": number, "updated_at": updated}


def comment(id, claude="0", luna="0", both="0", user=BOT):
    marker = f"<!-- kitden-sdlc:review claude={claude} luna={luna} both={both} -->"
    return {"id": id, "user": user, "body": f"Text.\n\n{marker}"}


def counts(claude, luna, both=0):
    return {"claude": claude, "luna": luna, "both": both}


# --- Collecting ---


def test_collect_reads_the_marker_and_the_maintainers_votes():
    api = FakeApi()
    api.pulls = [pull(7)]
    api.issue_comments[7] = [comment(12, claude="2", luna="x", both="1")]
    api.reactions[12] = [reaction("+1"), reaction("-1"), reaction("heart")]
    assert collect(api, "o/r", now=NOW) == [Review(7, counts(2, None, 1), up=1, down=1)]


def test_only_the_maintainers_reactions_count():
    api = FakeApi()
    api.pulls = [pull(1)]
    api.issue_comments[1] = [comment(5)]
    api.reactions[5] = [
        reaction("+1", MAINTAINER),
        reaction("+1", "someone-else"),
        reaction("-1", "another-person"),
        reaction("-1", MAINTAINER.upper()),  # logins are not case sensitive
    ]
    (only,) = collect(api, "o/r", now=NOW)
    assert (only.up, only.down) == (1, 1)
    # A different maintainer can be named.
    (other,) = collect(api, "o/r", maintainer="someone-else", now=NOW)
    assert (other.up, other.down) == (1, 0)


def test_only_bot_comments_with_our_marker_count():
    api = FakeApi()
    api.pulls = [pull(1)]
    person = {"login": "mallory", "type": "User"}
    api.issue_comments[1] = [
        comment(1, user=person),  # a person pasted our marker
        {"id": 2, "user": BOT, "body": "A bot comment with no marker."},
        {"id": 3, "user": BOT, "body": None},
        {"id": 4, "user": None, "body": "Gone user."},
        comment(5, claude="3"),
    ]
    api.reactions[1] = [reaction("+1")]
    assert collect(api, "o/r", now=NOW) == [Review(1, counts(3, 0), 0, 0)]


def test_collect_stops_at_the_cutoff():
    api = FakeApi()
    api.pulls = [
        pull(3, "2026-11-05T00:00:00Z"),
        pull(2, "2026-08-20T00:00:00Z"),  # 82 days old: inside 90 days
        pull(1, "2026-08-01T00:00:00Z"),  # 101 days old: outside
    ]
    for number in (1, 2, 3):
        api.issue_comments[number] = [comment(number)]
    found = collect(api, "o/r", since_days=90, now=NOW)
    assert sorted(r.pr for r in found) == [2, 3]
    assert 1 not in api.asked_for_comments


def test_a_reaction_from_a_deleted_user_is_skipped():
    api = FakeApi()
    api.pulls = [pull(1)]
    api.issue_comments[1] = [comment(5)]
    api.reactions[5] = [{"content": "+1", "user": None}, reaction("+1")]  # account deleted
    (only,) = collect(api, "o/r", now=NOW)
    assert (only.up, only.down) == (1, 0)


# --- Counting ---


def test_aggregate_findings_are_own_plus_both():
    stats = aggregate([Review(1, counts(2, 1, 1), 0, 0), Review(2, counts(0, 3, 0), 0, 0)])
    assert stats["claude"] == Stats(prs=2, findings=3, shared=1)
    assert stats["luna"] == Stats(prs=2, findings=5, shared=1)


def test_a_silent_reviewer_gets_no_pr_counted():
    stats = aggregate([Review(1, counts(1, None, 0), 0, 0), Review(2, counts(None, 2, 1), 0, 0)])
    assert stats["claude"] == Stats(prs=1, findings=1, shared=0)
    assert stats["luna"] == Stats(prs=1, findings=3, shared=1)
    assert aggregate([Review(1, counts(None, None, 0), 0, 0)]) == {}


# --- Writing ---

REVIEWS = {"prs": 3, "up": 2, "down": 2}


def test_render_has_table_and_useful_share():
    text = render({"claude": Stats(prs=3, findings=4, shared=1)}, REVIEWS, date(2026, 11, 10))
    assert "Reviews: 3. 👍 2, 👎 2, useful share 50%." in text
    assert "| Reviewer | Pull requests | Findings | Also found by the other |" in text
    assert "| claude | 3 | 4 | 1 |" in text
    assert "Updated on 2026-11-10" in text


def test_render_without_votes_has_no_share():
    reviews = {"prs": 1, "up": 0, "down": 0}
    text = render({"luna": Stats(prs=1, findings=1, shared=0)}, reviews, date(2026, 11, 10))
    assert "useful share -." in text


def test_render_with_no_reviews():
    text = render({}, {"prs": 0, "up": 0, "down": 0}, date(2026, 11, 10))
    assert "No reviews yet." in text
    assert "| Reviewer" not in text
    assert "Updated on 2026-11-10" in text


def one_review_api():
    api = FakeApi()
    api.pulls = [pull(1)]
    api.issue_comments[1] = [comment(1, claude="1", luna="x")]
    api.reactions[1] = [reaction("+1")]
    return api


def test_main_writes_both_files(tmp_path):
    assert main(["--out", str(tmp_path)], api=one_review_api(), now=NOW) == 0
    data = json.loads((tmp_path / "numbers.json").read_text())
    assert data["updated"] == "2026-11-10"
    assert data["reviews"] == {"prs": 1, "up": 1, "down": 0}
    assert data["reviewers"] == {"claude": {"prs": 1, "findings": 1, "shared": 0}}
    assert "| claude | 1 | 1 | 0 |" in (tmp_path / "numbers.md").read_text()


def test_main_is_quiet_about_nothing_changing(tmp_path):
    # A later day with the same counts leaves both files untouched, so the job commits nothing.
    api = one_review_api()
    main(["--out", str(tmp_path)], api=api, now=NOW)
    first = (tmp_path / "numbers.md").read_bytes(), (tmp_path / "numbers.json").read_bytes()
    main(["--out", str(tmp_path)], api=api, now=NOW + timedelta(days=7))
    second = (tmp_path / "numbers.md").read_bytes(), (tmp_path / "numbers.json").read_bytes()
    assert first == second
    assert json.loads(first[1])["updated"] == "2026-11-10"


def test_main_updates_the_files_when_the_reviews_change(tmp_path):
    api = one_review_api()
    main(["--out", str(tmp_path)], api=api, now=NOW)
    api.reactions[1].append(reaction("-1"))  # only the votes changed
    main(["--out", str(tmp_path)], api=api, now=NOW + timedelta(days=7))
    data = json.loads((tmp_path / "numbers.json").read_text())
    assert data["updated"] == "2026-11-17"
    assert data["reviews"] == {"prs": 1, "up": 1, "down": 1}
    assert "Updated on 2026-11-17" in (tmp_path / "numbers.md").read_text()


def test_main_updates_the_files_when_the_reviewers_change(tmp_path):
    api = one_review_api()
    main(["--out", str(tmp_path)], api=api, now=NOW)
    api.issue_comments[1] = [comment(1, claude="1", luna="2")]
    main(["--out", str(tmp_path)], api=api, now=NOW + timedelta(days=7))
    data = json.loads((tmp_path / "numbers.json").read_text())
    assert set(data["reviewers"]) == {"claude", "luna"}


@pytest.mark.parametrize("saved", [b"{not json", b"", b"[1, 2]", b"\xff\xfe", b'{"reviewers": 3}'])
def test_a_broken_saved_file_is_rewritten(tmp_path, saved):
    (tmp_path / "numbers.json").write_bytes(saved)
    (tmp_path / "numbers.md").write_text("old")
    assert main(["--out", str(tmp_path)], api=FakeApi(), now=NOW) == 0
    assert json.loads((tmp_path / "numbers.json").read_text())["updated"] == "2026-11-10"
    assert "No reviews yet." in (tmp_path / "numbers.md").read_text()


def test_an_old_file_without_the_reviews_key_is_rewritten(tmp_path):
    old = {"updated": "2026-11-01", "days": 90, "reviewers": {}}
    (tmp_path / "numbers.json").write_text(json.dumps(old))
    (tmp_path / "numbers.md").write_text("old")
    main(["--out", str(tmp_path)], api=FakeApi(), now=NOW)
    assert json.loads((tmp_path / "numbers.json").read_text())["reviews"]["prs"] == 0


def test_a_missing_markdown_file_is_rewritten(tmp_path):
    main(["--out", str(tmp_path)], api=FakeApi(), now=NOW)
    (tmp_path / "numbers.md").unlink()
    main(["--out", str(tmp_path)], api=FakeApi(), now=NOW + timedelta(days=7))
    assert "No reviews yet." in (tmp_path / "numbers.md").read_text()


def test_the_script_has_the_default_maintainer():
    assert count_reviews.MAINTAINER == "KonstantinStarovoytov"
