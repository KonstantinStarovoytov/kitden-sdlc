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
    summary,
)
from post_findings import Earlier, Finding, Item, state_line

NOW = datetime(2026, 11, 10, tzinfo=UTC)
BOT = {"login": "github-actions[bot]", "type": "Bot"}
A, B = "a" * 40, "b" * 40


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
    return {"number": number, "updated_at": updated, "created_at": "2026-10-28T00:00:00Z"}


def comment(id, claude="0", luna="0", both="0", user=BOT):
    marker = f"<!-- kitden-sdlc:review claude={claude} luna={luna} both={both} -->"
    return {
        "id": id,
        "user": user,
        "body": f"Text.\n\n{marker}",
        "updated_at": "2026-11-02T00:00:00Z",
    }


def counts(claude, luna, both=0):
    return {"claude": claude, "luna": luna, "both": both}


# --- Collecting ---


def test_collect_reads_the_marker_and_the_maintainers_votes():
    api = FakeApi()
    api.pulls = [pull(7)]
    api.issue_comments[7] = [comment(12, claude="2", luna="x", both="1")]
    api.reactions[12] = [reaction("+1"), reaction("-1"), reaction("heart")]
    assert collect(api, "o/r", now=NOW) == [
        Review(
            7,
            counts(2, None, 1),
            up=1,
            down=1,
            updated="2026-11-02T00:00:00Z",
            created="2026-10-28T00:00:00Z",
            merged=None,
        )
    ]


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
    (only,) = collect(api, "o/r", now=NOW)
    assert (only.pr, only.counts, only.up, only.down) == (1, counts(3, 0), 0, 0)


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


def test_collect_reads_fixed_findings_and_the_pull_requests_dates():
    api = FakeApi()
    api.pulls = [
        {**pull(3), "created_at": "2026-10-30T00:00:00Z", "merged_at": "2026-11-01T00:00:00Z"}
    ]
    state = state_line(
        Earlier(
            A,
            ["claude"],
            [
                Item(Finding("a.py", 1, "bug", "x"), ["claude"], A, A, B),
                Item(Finding("b.py", 2, "bug", "y"), ["claude"], A, A, ""),
            ],
            {"claude": 0, "luna": 0, "both": 0},
        )
    )
    item = comment(1, claude="2")
    marker = item["body"].splitlines()[-1]
    api.issue_comments[3] = [{**item, "body": f"Text.\n\n{state}\n{marker}"}]
    (found,) = collect(api, "o/r", now=NOW)
    assert (found.fixed, found.merged, found.clean) == (1, "2026-11-01T00:00:00Z", False)


def test_a_comment_without_a_state_line_has_nothing_fixed():
    api = FakeApi()
    api.pulls = [pull(3)]
    api.issue_comments[3] = [comment(1)]
    (found,) = collect(api, "o/r", now=NOW)
    assert (found.fixed, found.merged, found.clean) == (0, None, True)


def test_a_comment_where_neither_reviewer_answered_is_not_a_review():
    api = FakeApi()
    api.pulls = [pull(1), pull(2)]
    api.issue_comments[1] = [comment(1, claude="x", luna="x", both="0")]
    api.issue_comments[2] = [comment(2, claude="x", luna="1")]  # one answer is a review
    api.reactions[1] = [reaction("+1")]
    found = collect(api, "o/r", now=NOW)
    assert [r.pr for r in found] == [2]
    assert Review(1, counts(None, None), 0, 0).clean is False


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


def review(pr, c, fixed=0, days=None):
    """A Review merged `days` after it opened; not merged when `days` is None."""
    merged = NOW.isoformat() if days is not None else None
    created = (NOW - timedelta(days=days or 0)).isoformat()
    return Review(pr, c, 0, 0, fixed=fixed, updated=NOW.isoformat(), created=created, merged=merged)


def test_clean_needs_every_count_zero_or_missing_and_one_answer():
    assert review(1, counts(0, 0)).clean
    assert review(1, counts(0, None)).clean
    assert not review(1, counts(0, 0, both=1)).clean
    assert not review(1, counts(None, 2)).clean
    assert not review(1, counts(None, None)).clean


def test_summary_counts_clean_reviews_fixed_findings_and_days_to_merge():
    reviews = [
        review(1, counts(0, 0), days=1),
        review(2, counts(2, 0), fixed=2, days=3),
        review(3, counts(0, None)),
        review(4, counts(1, 0), fixed=5),  # not merged: its fixed findings are left out
    ]
    assert summary(reviews) == {"clean": 2, "fixed": 2, "days_to_merge": 2.0}
    assert summary([]) == {"clean": 0, "fixed": 0, "days_to_merge": None}


def test_days_to_merge_is_the_median_to_one_decimal():
    reviews = [review(n, counts(0, 0), days=d) for n, d in enumerate((1, 2, 4, 9.26), start=1)]
    assert summary(reviews)["days_to_merge"] == 3.0
    assert summary([review(1, counts(0, 0), days=1.26)])["days_to_merge"] == 1.3


def test_days_to_merge_counts_each_pull_request_once():
    reviews = [
        review(1, counts(0, 0), days=1),
        review(1, counts(1, 0), days=1),
        review(2, counts(0, 0), days=5),
    ]
    assert summary(reviews)["days_to_merge"] == 3.0


# --- Writing ---

REVIEWS = {"prs": 3, "up": 2, "down": 2}
SUMMARY = {"clean": 1, "fixed": 2, "days_to_merge": 1.5}


def test_render_has_table_and_useful_share():
    text = render(
        {"claude": Stats(prs=3, findings=4, shared=1)}, REVIEWS, SUMMARY, date(2026, 11, 10)
    )
    assert "Reviews: 3. 👍 2, 👎 2, useful share 50%." in text
    assert "| Reviewer | Pull requests | Findings | Also found by the other |" in text
    assert "| claude | 3 | 4 | 1 |" in text
    assert (
        "No findings: 1. Findings fixed before the merge: 2. Median days from open to merge: 1.5."
        in text
    )
    assert "Updated on 2026-11-10" in text


def test_render_without_votes_has_no_share():
    reviews = {"prs": 1, "up": 0, "down": 0}
    text = render(
        {"luna": Stats(prs=1, findings=1, shared=0)}, reviews, SUMMARY, date(2026, 11, 10)
    )
    assert "useful share -." in text
    assert "Median days from open to merge: 1.5." in text


def test_render_without_a_merged_pull_request_has_no_days():
    none = {"clean": 0, "fixed": 0, "days_to_merge": None}
    text = render({}, {"prs": 1, "up": 0, "down": 0}, none, date(2026, 11, 10))
    assert "Median days from open to merge: -." in text


def test_render_with_no_reviews():
    none = {"clean": 0, "fixed": 0, "days_to_merge": None}
    text = render({}, {"prs": 0, "up": 0, "down": 0}, none, date(2026, 11, 10))
    assert "No reviews yet." in text
    assert "Median days" not in text
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


def test_numbers_files_carry_the_summary(tmp_path):
    assert main(["--out", str(tmp_path)], api=one_review_api(), now=NOW) == 0
    assert json.loads((tmp_path / "numbers.json").read_text())["summary"] == {
        "clean": 0,
        "fixed": 0,
        "days_to_merge": None,
    }
    assert "Median days from open to merge" in (tmp_path / "numbers.md").read_text()


def test_a_comment_nobody_answered_is_left_out_of_the_numbers(tmp_path):
    api = one_review_api()
    api.pulls.append(pull(2))
    api.issue_comments[2] = [comment(2, claude="x", luna="x")]
    api.reactions[2] = [reaction("+1")]
    main(["--out", str(tmp_path)], api=api, now=NOW)
    data = json.loads((tmp_path / "numbers.json").read_text())
    assert data["reviews"] == {"prs": 1, "up": 1, "down": 0}
    assert data["summary"]["clean"] == 0


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


def test_an_old_file_without_the_summary_is_rewritten(tmp_path):
    api = one_review_api()
    main(["--out", str(tmp_path)], api=api, now=NOW)
    data = json.loads((tmp_path / "numbers.json").read_text())
    del data["summary"]
    (tmp_path / "numbers.json").write_text(json.dumps(data))
    main(["--out", str(tmp_path)], api=api, now=NOW + timedelta(days=7))
    assert "summary" in json.loads((tmp_path / "numbers.json").read_text())


def test_a_missing_markdown_file_is_rewritten(tmp_path):
    main(["--out", str(tmp_path)], api=FakeApi(), now=NOW)
    (tmp_path / "numbers.md").unlink()
    main(["--out", str(tmp_path)], api=FakeApi(), now=NOW + timedelta(days=7))
    assert "No reviews yet." in (tmp_path / "numbers.md").read_text()


def test_the_script_has_the_default_maintainer():
    assert count_reviews.MAINTAINER == "KonstantinStarovoytov"
