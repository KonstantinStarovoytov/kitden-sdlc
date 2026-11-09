import json
from datetime import UTC, date, datetime, timedelta

import count_reviews
from count_reviews import (
    MAINTAINER,
    Comment,
    Stats,
    aggregate,
    collect,
    main,
    parse_marker,
    render,
)
from post_findings import marker

NOW = datetime(2026, 11, 10, tzinfo=UTC)
BOT = {"login": "github-actions[bot]", "type": "Bot"}


def reaction(content, login=MAINTAINER):
    return {"content": content, "user": {"login": login}}


class FakeApi:
    """Holds pull requests, comments and reactions in memory; never calls gh."""

    def __init__(self):
        self.pulls: list[dict] = []  # newest first
        self.review_comments: dict[int, list[dict]] = {}
        self.issue_comments: dict[int, list[dict]] = {}
        self.reactions: dict[tuple[str, int], list[dict]] = {}
        self.asked_for_comments: list[int] = []

    def list_pulls(self, repo):
        yield from self.pulls

    def list_review_comments(self, repo, pr):
        self.asked_for_comments.append(pr)
        return self.review_comments.get(pr, [])

    def list_issue_comments(self, repo, pr):
        return self.issue_comments.get(pr, [])

    def list_review_comment_reactions(self, repo, comment_id):
        return self.reactions.get(("review", comment_id), [])

    def list_issue_comment_reactions(self, repo, comment_id):
        return self.reactions.get(("issue", comment_id), [])


def pull(number, updated="2026-11-01T00:00:00Z"):
    return {"number": number, "updated_at": updated}


def comment(id, reviewer, key, user=BOT):
    return {"id": id, "user": user, "body": f"Text.\n\n{marker(reviewer, key)}"}


# --- Reading markers ---


def test_parse_marker():
    assert parse_marker(f"Hello\n\n{marker('claude', 'a.py:3:bug')}\n") == ("claude", "a.py:3:bug")
    assert parse_marker(f"Hello\n\n{marker('luna', 'summary')}") == ("luna", "summary")
    assert parse_marker("No marker here.") is None
    # Only a marker at the very end counts.
    assert parse_marker(f"{marker('claude', 'summary')}\n\nand then more text") is None


# --- Collecting ---


def test_summary_counts_as_pr_not_finding():
    stats = aggregate(
        [
            Comment("claude", pr=1, is_summary=True, up=0, down=0),
            Comment("claude", pr=1, is_summary=False, up=1, down=0),
        ]
    )
    assert stats == {"claude": Stats(prs=1, findings=1, up=1, down=0)}


def test_aggregate_per_reviewer():
    stats = aggregate(
        [
            Comment("claude", 1, True, 0, 0),
            Comment("claude", 1, False, 2, 0),
            Comment("claude", 2, False, 0, 1),
            Comment("luna", 2, True, 0, 0),
            Comment("luna", 2, False, 0, 3),
        ]
    )
    assert stats["claude"] == Stats(prs=2, findings=2, up=2, down=1)
    assert stats["luna"] == Stats(prs=1, findings=1, up=0, down=3)


def test_collect_reads_both_kinds_of_comment_and_reactions():
    api = FakeApi()
    api.pulls = [pull(7)]
    api.review_comments[7] = [comment(11, "claude", "a.py:3:bug")]
    api.issue_comments[7] = [comment(12, "claude", "summary")]
    api.reactions[("review", 11)] = [reaction("+1"), reaction("-1"), reaction("heart")]
    api.reactions[("issue", 12)] = [reaction("+1")]
    found = collect(api, "o/r", now=NOW)
    assert sorted(found, key=lambda c: c.is_summary) == [
        Comment("claude", 7, False, up=1, down=1),
        Comment("claude", 7, True, up=1, down=0),
    ]


def test_only_the_maintainers_reactions_count():
    api = FakeApi()
    api.pulls = [pull(1)]
    api.review_comments[1] = [comment(5, "claude", "a.py:1:bug")]
    api.reactions[("review", 5)] = [
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
        comment(1, "claude", "summary", user=person),  # a person pasted our marker
        {"id": 2, "user": BOT, "body": "A bot comment with no marker."},
        {"id": 3, "user": BOT, "body": None},
        comment(4, "luna", "summary"),
    ]
    api.reactions[("issue", 1)] = [reaction("+1")]
    assert collect(api, "o/r", now=NOW) == [Comment("luna", 1, True, 0, 0)]


def test_collect_stops_at_the_cutoff():
    api = FakeApi()
    api.pulls = [
        pull(3, "2026-11-05T00:00:00Z"),
        pull(2, "2026-08-20T00:00:00Z"),  # 82 days old: inside 90 days
        pull(1, "2026-08-01T00:00:00Z"),  # 101 days old: outside
    ]
    for number in (1, 2, 3):
        api.issue_comments[number] = [comment(number, "claude", "summary")]
    found = collect(api, "o/r", since_days=90, now=NOW)
    assert sorted(c.pr for c in found) == [2, 3]
    assert 1 not in api.asked_for_comments


# --- Writing ---


def test_render_has_useful_share():
    text = render({"claude": Stats(prs=3, findings=4, up=2, down=2)}, date(2026, 11, 10))
    assert "| Reviewer | Pull requests | Findings | 👍 | 👎 | Useful share |" in text
    assert "| claude | 3 | 4 | 2 | 2 | 50% |" in text
    assert "Updated on 2026-11-10" in text


def test_render_without_votes_has_no_share():
    text = render({"luna": Stats(prs=1, findings=1, up=0, down=0)}, date(2026, 11, 10))
    assert "| luna | 1 | 1 | 0 | 0 | - |" in text


def test_render_with_no_reviews():
    text = render({}, date(2026, 11, 10))
    assert "No reviews yet." in text
    assert "| Reviewer" not in text
    assert "Updated on 2026-11-10" in text


def test_main_writes_both_files(tmp_path):
    api = FakeApi()
    api.pulls = [pull(1)]
    api.issue_comments[1] = [comment(1, "claude", "summary")]
    api.reactions[("issue", 1)] = [reaction("+1")]
    assert main(["--out", str(tmp_path)], api=api, now=NOW) == 0
    data = json.loads((tmp_path / "numbers.json").read_text())
    assert data["updated"] == "2026-11-10"
    assert data["reviewers"] == {"claude": {"prs": 1, "findings": 0, "up": 1, "down": 0}}
    assert "| claude | 1 | 0 | 1 | 0 | 100% |" in (tmp_path / "numbers.md").read_text()


def test_main_is_quiet_about_nothing_changing(tmp_path):
    # A later day with the same counts leaves both files untouched, so the job commits nothing.
    api = FakeApi()
    api.pulls = [pull(1)]
    api.issue_comments[1] = [comment(1, "claude", "summary")]
    main(["--out", str(tmp_path)], api=api, now=NOW)
    first = (tmp_path / "numbers.md").read_bytes(), (tmp_path / "numbers.json").read_bytes()
    main(["--out", str(tmp_path)], api=api, now=NOW + timedelta(days=7))
    second = (tmp_path / "numbers.md").read_bytes(), (tmp_path / "numbers.json").read_bytes()
    assert first == second
    assert json.loads(first[1])["updated"] == "2026-11-10"


def test_main_updates_the_files_when_the_counts_change(tmp_path):
    api = FakeApi()
    api.pulls = [pull(1)]
    api.issue_comments[1] = [comment(1, "claude", "summary")]
    main(["--out", str(tmp_path)], api=api, now=NOW)
    api.issue_comments[1].append(comment(2, "luna", "summary"))
    later = NOW + timedelta(days=7)
    main(["--out", str(tmp_path)], api=api, now=later)
    data = json.loads((tmp_path / "numbers.json").read_text())
    assert data["updated"] == "2026-11-17"
    assert set(data["reviewers"]) == {"claude", "luna"}
    assert "Updated on 2026-11-17" in (tmp_path / "numbers.md").read_text()


def test_a_reaction_from_a_deleted_user_is_skipped():
    api = FakeApi()
    api.pulls = [pull(1)]
    api.review_comments[1] = [comment(5, "claude", "a.py:1:bug")]
    api.reactions[("review", 5)] = [
        {"content": "+1", "user": None},  # the account was deleted
        reaction("+1"),
    ]
    (only,) = collect(api, "o/r", now=NOW)
    assert (only.up, only.down) == (1, 0)


def test_the_script_has_the_default_maintainer():
    assert count_reviews.MAINTAINER == "KonstantinStarovoytov"
