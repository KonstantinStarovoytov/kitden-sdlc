import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

import desk_post
from bot_issues import BOT
from desk_post import LIMIT, TITLE, main, monday_note, post, render
from tests.fakes import FakeIssues, issue

URL = "https://github.com/KonstantinStarovoytov/kitden/issues/12"
SPOT = "https://github.com/KonstantinStarovoytov/kitden/pull/70"
MONDAY = datetime(2026, 11, 16, 7, tzinfo=UTC)
SEARCH = "https://github.com/KonstantinStarovoytov/kitden/"

DESK = {
    "version": 1,
    "updated": "2026-11-16T06:41:00Z",
    "repo": "KonstantinStarovoytov/kitden",
    "overall": "amber",
    "lights": [
        {"id": "works", "name": "Works", "state": "grey",
         "why": "Not measured yet: no check run of main was read."},
        {"id": "clients", "name": "Clients", "state": "amber",
         "why": "Issue #12 (a confirmed major client change) has been open 4.0 days."},
        {"id": "bugs", "name": "Bugs", "state": "green", "why": ""},
        {"id": "agents", "name": "Agents", "state": "green", "why": ""},
        {"id": "queue", "name": "Queue", "state": "green", "why": ""},
    ],
    "use": {"issues_from_others": 0, "pulls_from_others": 1, "stars": 12, "downloads": 340},
    "waiting": [{"kind": "verdict", "title": "Codex: the hooks key was renamed", "url": URL,
                 "do": "Put `confirmed` on it, or close it with `false-alarm`.", "days": 2.0}],
    "week": [{"agent": "claude", "name": "Claude reviewer", "runs": 12, "did": 9, "agreed": 3,
              "disagreed": 1}],
    "review": {"clean": 4, "fixed": 6, "days_to_merge": 1.5},
    "found_by": [{"month": "2026-11", "review": 6, "nightly": None, "tester": None,
                  "watcher": 0, "owner": 4, "others": 0}],
    "misses": [{"issue": 81, "pull": 70,
                "url": "https://github.com/KonstantinStarovoytov/kitden/issues/81"}],
    "budget": {
        "agents": [{"agent": "claude", "runs": 12, "cap": "20 reviews a day, 5 findings each"}],
        "keys": [{"name": "OPENAI_API_KEY", "stored": "Kitden", "used_by": ["luna reviewer"],
                  "money_cap": "$5 a month", "dashboard": "https://platform.openai.com/usage"}],
    },
}


def wait(title="t", url=URL, kind="verdict", days=1.0):
    return {"kind": kind, "title": title, "url": url, "do": "d", "days": days}


# --- The page ---


def test_render_has_the_six_parts_in_order():
    body = render(DESK)
    places = [body.index(f"## {part}") for part in
              ("Health", "Waiting for you", "Links", "This week", "Budget", "How to")]
    assert places == sorted(places) and "no model" in body.splitlines()[0]
    assert "🟡 Clients" in body and "⚪ Works: not measured yet" in body


def test_the_first_line_says_who_wrote_it_when_and_from_which_file():
    first = render(DESK).splitlines()[0]
    assert "script" in first and "no model" in first and "2026-11-16 06:41 UTC" in first
    assert "(https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/numbers/desk.json)" in first


def test_each_light_has_its_mark_and_a_grey_one_says_why():
    body = render(DESK)
    assert "⚪ Works: not measured yet: no check run of main was read." in body
    assert "🟡 Clients: Issue &#35;12" in body
    assert "\n- 🟢 Bugs\n" in body and "🟡" in body.split("## Health")[1].split("\n- ")[0]
    grey = {**DESK, "lights": [{"id": "works", "name": "Works", "state": "grey", "why": ""}]}
    assert "⚪ Works: not measured yet." in render(grey)


def test_the_use_line_counts_and_says_what_was_not_measured():
    body = render(DESK)
    assert "0 issues and 1 pull request from others this month" in body
    assert "12 stars" in body and "340 downloads" in body
    body = render({**DESK, "use": {**DESK["use"], "stars": None}})
    assert "stars: not measured yet" in body


def test_a_strangers_title_cannot_ping_link_or_break_the_page():
    bad = "@admin see #1 [x](http://evil) <!-- | \n## Health"
    desk = {**DESK, "waiting": [{"kind": "verdict", "title": bad, "url": URL, "do": "d",
                                 "days": 1.0}]}
    body = render(desk)
    assert "@admin" not in body and "](http://evil)" not in body and "<!--" not in body
    assert body.count("## Health") == 1 and "#1 " not in body


def test_a_why_goes_through_one_line_too():
    lights = [{"id": "works", "name": "Works", "state": "red", "why": "@admin <b>x</b>\n## Links"}]
    body = render({**DESK, "lights": lights})
    assert "@admin" not in body and "<b>" not in body and body.count("## Links") == 1


@pytest.mark.parametrize("url", ["http://evil.example/x", "javascript:alert(1)",
                                 "https://github.com.evil.example/x",
                                 "https://github.com/x) [y](http://evil"])
def test_only_a_github_address_becomes_a_link(url):
    body = render({**DESK, "waiting": [wait("Odd item", url=url)], "misses": []})
    assert "Odd item" in body and "evil" not in body and "javascript" not in body


def test_waiting_items_show_the_link_what_to_do_and_the_days():
    body = render(DESK)
    assert f"[Codex: the hooks key was renamed]({URL})" in body
    assert "Put `confirmed` on it, or close it with `false-alarm`." in body
    assert "2 days" in body


def test_not_measured_is_said_not_hidden():
    body = render({**DESK, "waiting": None, "use": {**DESK["use"], "downloads": None}})
    assert "Not measured." in body and "None" not in body and "null" not in body


def test_nothing_waiting_says_nothing():
    assert "## Waiting for you\n\nNothing.\n" in render({**DESK, "waiting": []})


def test_none_anywhere_is_never_printed():
    empty = {
        **DESK, "use": dict.fromkeys(DESK["use"]), "waiting": None,
        "week": [{**DESK["week"][0], "runs": None, "did": None, "agreed": None,
                  "disagreed": None}],
        "review": {"clean": None, "fixed": None, "days_to_merge": None},
        "found_by": [dict.fromkeys(DESK["found_by"][0]) | {"month": "2026-11"}],
        "misses": None,
        "budget": {"agents": [{"agent": "claude", "runs": None, "cap": "c"}], "keys": []},
    }
    body = render(empty)
    assert "None" not in body and "null" not in body and "| |" not in body
    assert "Reviews: not measured yet." in body and "Misses: not measured yet." in body


def test_the_links_are_the_four_searches_in_kitden():
    links = render(DESK).split("## Links")[1].split("## ")[0]
    assert links.count(SEARCH) == 4
    for query in ("is%3Aissue+is%3Aopen+-label%3Aautomated",
                  "is%3Aissue+is%3Aopen+label%3Aautomated",
                  "is%3Apr+is%3Aopen+author%3Aapp%2Fkitden-beacon",
                  "is%3Aissue+label%3Aclient-change+label%3Asummary"):
        assert query in links


def test_this_week_says_what_its_numbers_cover():
    week = render(DESK).split("## This week")[1].split("## Budget")[0]
    assert "90 days" in week and "7" in week
    assert "| Claude reviewer | 12 | 9 | 3 | 1 |" in week
    assert "4 reviews found nothing" in week and "6 findings were fixed" in week
    assert "1.5 days" in week
    assert "[Issue #81](https://github.com/KonstantinStarovoytov/kitden/issues/81)" in week


def test_a_column_nothing_measured_is_left_out_and_named():
    week = render(DESK).split("## This week")[1].split("## Budget")[0]
    assert "| 2026-11 | 6 | 0 | 4 | 0 |" in week
    assert "Nightly" not in week.split("Not measured yet")[0]
    assert "Not measured yet: Nightly, Tester." in week


def test_a_cell_not_measured_says_so():
    row = {"agent": "release-prep", "name": "Release prep", "runs": 2, "did": 1,
           "agreed": None, "disagreed": None}
    week = render({**DESK, "week": [*DESK["week"], row]}).split("## This week")[1]
    assert "| Release prep | 2 | 1 | not measured | not measured |" in week


def test_no_misses_is_said():
    assert "No misses in the last 30 days." in render({**DESK, "misses": []})


def test_the_budget_has_two_tables_and_the_sentence():
    budget = render(DESK).split("## Budget")[1].split("## How to")[0]
    assert "| Claude reviewer | 12 | 20 reviews a day, 5 findings each |" in budget
    assert "OPENAI&#95;API&#95;KEY" in budget and "$5 a month" in budget
    assert "`https://platform.openai.com/usage`" in budget  # shown, not linked
    assert "](https://platform" not in budget
    assert "The providers enforce the money caps; no billing key is stored." in budget


def test_how_to_links_the_owners_page():
    how = render(DESK).split("## How to")[1]
    assert "(https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/main/docs/owner.md)" in how


def test_a_page_too_long_for_an_issue_is_cut_not_failed():
    many = [wait("x" * 100 + f" {n}") for n in range(2000)]
    body = render({**DESK, "waiting": many, "misses": DESK["misses"] * 50})
    assert len(body.encode()) < LIMIT
    assert "…and " in body and " more." in body and "## How to" in body
    shown = body.count("x" * 100)
    assert f"…and {2000 - shown} more." in body
    assert body.count("[Issue #81]") == 50  # the shorter list stays whole


# --- The Monday note ---


def test_the_monday_note_names_the_week_the_light_and_what_waits():
    note = monday_note(DESK, MONDAY)
    assert note.splitlines()[0] == "Week of 2026-11-16"
    assert "🟡" in note and "1 thing waits for you" in note
    spot = {**DESK, "waiting": [*DESK["waiting"], wait("#70, reviewed with no findings", SPOT,
                                                       "spot-check")]}
    note = monday_note(spot, MONDAY + timedelta(days=2))
    assert note.startswith("Week of 2026-11-16\n") and "2 things wait for you" in note
    assert f"]({SPOT})" in note
    assert "not measured" in monday_note({**DESK, "waiting": None}, MONDAY)


def test_post_rewrites_the_one_issue_and_comments_once_on_monday():
    gh = FakeIssues()
    post(gh, DESK, MONDAY)
    assert gh.created[0][0] == "Kitden desk" and gh.created[0][2] == ["automated", "desk"]
    assert len(gh.commented) == 1
    post(gh, DESK, MONDAY)
    assert len(gh.created) == 1 and len(gh.edited) == 1 and len(gh.commented) == 1
    post(gh, DESK, MONDAY + timedelta(days=1))
    assert len(gh.commented) == 1


def test_a_persons_issue_called_kitden_desk_is_left_alone():
    gh = FakeIssues([issue(4, "Kitden desk", login="someone")])
    post(gh, DESK, MONDAY)
    assert gh.edited == [] and len(gh.created) == 1


def test_post_makes_the_labels_first():
    gh = FakeIssues()
    post(gh, DESK, MONDAY + timedelta(days=1))
    assert {"automated", "desk"} <= {name for name, *_ in gh.created_labels}
    assert gh.commented == []


def test_a_persons_comment_with_the_weeks_line_does_not_stop_the_note():
    desk_issue = issue(9, TITLE, labels=("automated", "desk"))
    theirs = {"user": {"login": "someone"}, "body": "Week of 2026-11-16\n\nmine"}
    gh = FakeIssues([desk_issue], comments={9: [theirs]})
    post(gh, DESK, MONDAY)
    assert [number for number, _ in gh.commented] == [9]


def test_last_weeks_note_does_not_stop_this_weeks():
    desk_issue = issue(9, TITLE, labels=("automated", "desk"))
    old = {"user": {"login": BOT}, "body": "Week of 2026-11-09\n\n🟢"}
    gh = FakeIssues([desk_issue], comments={9: [old]})
    post(gh, DESK, MONDAY)
    assert len(gh.commented) == 1


def test_monday_is_monday_in_utc():
    gh = FakeIssues()
    sunday_in_utc = datetime(2026, 11, 16, 1, tzinfo=timezone(timedelta(hours=3)))
    post(gh, DESK, sunday_in_utc)
    assert gh.commented == []


# --- The command ---


def write_desk(tmp_path, desk=DESK):
    path = tmp_path / "desk.json"
    path.write_text(json.dumps(desk))
    return path


def test_dry_run_prints_the_page_and_the_note_and_calls_nothing(tmp_path, capsys, monkeypatch):
    def no_github(repo):
        raise AssertionError("a dry run called GitHub")

    monkeypatch.setattr(desk_post, "GhIssues", no_github)
    path = write_desk(tmp_path)
    assert main(["--desk", str(path), "--dry-run"], now=MONDAY) == 0
    out = capsys.readouterr().out
    assert out.startswith(render(DESK)) and "Week of 2026-11-16" in out
    assert main(["--desk", str(path), "--dry-run"], now=MONDAY + timedelta(days=1)) == 0
    assert "Week of" not in capsys.readouterr().out


def test_the_command_posts_to_the_repository_given(tmp_path, monkeypatch):
    made = {}

    def fake(repo):
        made[repo] = FakeIssues()
        return made[repo]

    monkeypatch.setattr(desk_post, "GhIssues", fake)
    path = write_desk(tmp_path)
    assert main(["--desk", str(path), "--repo", "o/kitden"], now=MONDAY) == 0
    assert made["o/kitden"].created[0][0] == TITLE


def test_posting_needs_the_repository(tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        main(["--desk", str(write_desk(tmp_path))], now=MONDAY)
    assert stop.value.code == 2 and "--repo" in capsys.readouterr().err


def test_zero_days_reads_as_under_a_tenth():
    body = render({**DESK, "review": {**DESK["review"], "days_to_merge": 0.0},
                   "waiting": [wait(days=0.0)]})
    assert "took under 0.1 days to merge" in body and "Waiting under 0.1 days." in body
    assert " 0 days" not in body


def test_the_week_table_says_what_its_columns_mean():
    week = render(DESK).split("## This week")[1].split("Reviews:")[0]
    assert "Did:" in week and "👍" in week and "`false-alarm`" in week


def test_a_page_too_long_even_without_its_lists_is_cut_at_a_line():
    lights = [{"id": "works", "name": "Works", "state": "red", "why": "y" * 70_000}]
    body = render({**DESK, "lights": lights})
    assert len(body.encode()) < LIMIT and body.endswith("too long for an issue.\n")


def test_a_table_with_nothing_measured_is_one_sentence():
    nothing = {**DESK, "use": dict.fromkeys(DESK["use"]),
               "week": [dict.fromkeys(DESK["week"][0]) | {"name": "Claude reviewer"}],
               "found_by": [dict.fromkeys(DESK["found_by"][0]) | {"month": "2026-11"}]}
    week = render(nothing).split("## This week")[1].split("## Budget")[0]
    assert "The agents' week: not measured yet." in week and "Did:" not in week
    assert "Who found problems: not measured yet." in week and "| 2026-11" not in week
    assert "Use: not measured yet." in render(nothing)


def test_all_grey_does_not_say_all_is_well():
    lights = [{"id": "works", "name": "Works", "state": "grey", "why": ""}]
    body = render({**DESK, "overall": "grey", "lights": lights})
    assert "is well" not in body and "none is amber or red" in body
