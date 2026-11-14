import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

import desk_post
from bot_issues import BOT
from desk import Facts, build
from desk_post import LIMIT, TITLE, main, post, render, week_note
from post_findings import one_line
from tests.fakes import FakeIssues, issue
from tests.test_desk import FACTS, NOW, ROSTER

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
    "week": [{"agent": "claude", "name": "Claude reviewer", "runs": 12, "failed": 1, "did": 9,
              "agreed": 3, "disagreed": 1, "no_answer": 2}],
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


def lead(body):
    """The one line under the lights: the first paragraph after the badges."""
    return body.split("\n\n")[1]


def light_line(body, name):
    """The table row of one light: its name, its mark, its reason when it is not green."""
    line, = [x for x in body.split("\n\n")[0].splitlines() if x.startswith(f"| **{name}** |")]
    return line


def test_render_has_the_six_parts_in_order():
    body = render(DESK)
    places = [body.index(f"## {part}") for part in
              ("Health", "Waiting for you", "Links", "This week", "Budget", "How to")]
    assert places == sorted(places) and "no model" in body.splitlines()[-1]
    table = body.split("\n\n")[0].splitlines()  # the bots' one look: a row for each light
    assert table[0].replace("&nbsp;", "") == "| Light | State | Why |" and len(table) == 7
    assert 'alt="not measured">' in light_line(body, "Works")
    assert 'alt="look">' in light_line(body, "Clients")
    assert "🟡" not in body and "🟢" not in body  # the badges say it: no second set of marks


def test_the_small_print_says_who_wrote_it_when_and_from_which_file():
    first = render(DESK).splitlines()[-1]
    assert "script" in first and "no model" in first and "2026-11-16 06:41 UTC" in first
    assert "(https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/numbers/desk.json)" in first


def test_a_light_that_is_not_green_says_why_and_a_green_one_is_only_a_badge():
    body = render(DESK)
    works = light_line(body, "Works")
    assert works.endswith('alt="not measured"> | no check run of main was read. |')
    assert 'alt="look"> | Issue &#35;12' in light_line(body, "Clients")
    assert light_line(body, "Bugs").endswith('alt="ok"> |  |')  # green: the mark says it all
    assert lead(body) == "Something needs a look."
    grey = {**DESK, "lights": [{"id": "works", "name": "Works", "state": "grey", "why": ""}]}
    assert light_line(render(grey), "Works").endswith('alt="not measured"> |  |')


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
        "week": [{**DESK["week"][0], "runs": None, "failed": None, "did": None, "agreed": None,
                  "disagreed": None, "no_answer": None}],
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
    assert "| Agent | Runs | Failed | Did | No answer | You agreed | You disagreed |" in week
    assert "| Claude reviewer | 12 | 1 | 9 | 2 | 3 | 1 |" in week
    assert "4 reviews found nothing" in week and "6 findings were fixed" in week
    assert "1.5 days" in week
    assert "[Issue #81](https://github.com/KonstantinStarovoytov/kitden/issues/81)" in week


def test_a_column_nothing_measured_is_left_out_and_named():
    week = render(DESK).split("## This week")[1].split("## Budget")[0]
    assert "| 2026-11 | 6 | 0 | 4 | 0 |" in week
    assert "Nightly" not in week.split("Not measured yet")[0]
    assert "Not measured yet: Nightly, Tester." in week


def test_release_preps_verdicts_do_not_apply():
    row = {"agent": "release-prep", "name": "Release prep", "runs": 2, "failed": 0, "did": 1,
           "agreed": None, "disagreed": None}
    week = render({**DESK, "week": [*DESK["week"], row]}).split("## This week")[1]
    assert "| Release prep | 2 | 0 | 1 | — | — | — |" in week


def test_a_cell_not_measured_says_so():
    row = {"agent": "watcher", "name": "Client watcher", "runs": 2, "failed": None, "did": 1,
           "agreed": None, "disagreed": 0}
    week = render({**DESK, "week": [*DESK["week"], row]}).split("## This week")[1]
    assert "| Client watcher | 2 | not measured | 1 | — | not measured | 0 |" in week


def test_no_answer_is_a_dash_where_it_does_not_apply_and_left_out_when_unmeasured():
    watcher = {"agent": "watcher", "name": "Client watcher", "runs": 7, "failed": 0, "did": 1,
               "agreed": 1, "disagreed": 0}
    week = render({**DESK, "week": [*DESK["week"], watcher]}).split("## This week")[1]
    assert "| Client watcher | 7 | 0 | 1 | — | 1 | 0 |" in week
    unread = [{**DESK["week"][0], "no_answer": None}, watcher]
    week = render({**DESK, "week": unread}).split("## This week")[1].split("## Budget")[0]
    assert "No answer" not in week.split("Not measured yet")[0]
    assert "Not measured yet: No answer." in week


def test_no_misses_is_said():
    assert "No misses in the last 30 days." in render({**DESK, "misses": []})


def test_the_budget_has_two_tables_and_the_sentence():
    budget = render(DESK).split("## Budget")[1].split("## How to")[0]
    assert "| Claude reviewer | 12 | 20 reviews a day, 5 findings each |" in budget
    assert "OPENAI&#95;API&#95;KEY" in budget and "$5 a month" in budget
    assert "The providers enforce the money caps; no billing key is stored." in budget


def test_the_rosters_usage_pages_are_linked_and_no_other():
    budget = render(DESK).split("## Budget")[1].split("## How to")[0]
    usage = "https://platform.openai.com/usage"  # in config/agents.json
    assert f"[{usage}]({usage})" in budget
    for other in ("https://platform.openai.com/usage/evil", "https://evil.example/usage"):
        keys = [{**DESK["budget"]["keys"][0], "dashboard": other}]
        budget = render({**DESK, "budget": {**DESK["budget"], "keys": keys}}).split("## Budget")[1]
        assert f"`{other}`" in budget and f"]({other})" not in budget


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


# --- The week's note ---


def test_the_weeks_note_names_the_week_the_light_and_what_waits():
    note = week_note(DESK, MONDAY)
    assert note.splitlines()[0] == "Week of 2026-11-16"
    assert "🟡" in note and "1 thing waits for you" in note
    spot = {**DESK, "waiting": [*DESK["waiting"], wait("#70, reviewed with no findings", SPOT,
                                                       "spot-check")]}
    note = week_note(spot, MONDAY + timedelta(days=2))
    assert note.startswith("Week of 2026-11-16\n") and "2 things wait for you" in note
    assert f"]({SPOT})" in note
    assert "not measured" in week_note({**DESK, "waiting": None}, MONDAY)


def test_post_rewrites_the_one_issue_and_comments_once_a_week():
    gh = FakeIssues()
    post(gh, DESK, MONDAY)
    assert gh.created[0][0] == "Kitden desk" and gh.created[0][2] == ["automated", "desk"]
    assert len(gh.commented) == 1
    post(gh, DESK, MONDAY)
    assert len(gh.created) == 1 and len(gh.edited) == 1 and len(gh.commented) == 1
    post(gh, DESK, MONDAY + timedelta(days=1))
    assert len(gh.commented) == 1
    post(gh, DESK, MONDAY + timedelta(days=7))
    assert len(gh.commented) == 2


def test_the_weeks_first_run_comments_whatever_the_day():
    # Monday's run failed or the switch was off: Wednesday's run is the week's first.
    gh = FakeIssues()
    post(gh, DESK, MONDAY + timedelta(days=2))
    assert len(gh.commented) == 1
    assert gh.commented[0][1].startswith("Week of 2026-11-16\n")
    post(gh, DESK, MONDAY + timedelta(days=3))
    assert len(gh.commented) == 1


def test_a_persons_issue_called_kitden_desk_is_left_alone():
    gh = FakeIssues([issue(4, "Kitden desk", login="someone")])
    post(gh, DESK, MONDAY)
    assert gh.edited == [] and len(gh.created) == 1


def test_post_makes_the_labels_first():
    gh = FakeIssues()
    post(gh, DESK, MONDAY + timedelta(days=1))
    assert {"automated", "desk"} <= {name for name, *_ in gh.created_labels}


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


def test_the_week_is_the_week_in_utc():
    gh = FakeIssues()
    sunday_in_utc = datetime(2026, 11, 16, 1, tzinfo=timezone(timedelta(hours=3)))
    post(gh, DESK, sunday_in_utc)
    assert gh.commented[0][1].startswith("Week of 2026-11-09\n")


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
    assert "Week of 2026-11-16" in capsys.readouterr().out


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
    assert "Runs: runs that ended, well or badly" in week and "one per push" in week
    assert "pull requests reviewed" in week


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


def test_all_green_says_all_five_lights_are_green():
    lights = [{"id": i, "name": i.capitalize(), "state": "green", "why": ""}
              for i in ("works", "clients", "bugs", "agents", "queue")]
    body = render({**DESK, "overall": "green", "lights": lights})
    assert lead(body) == "All five lights are green." and "is well" not in body
    parts = body.split("\n\n")
    assert parts[2] == "### Health" and parts[3].startswith("Use: ")


def test_health_and_waiting_stay_the_first_lines_of_the_page():
    parts = render(DESK).split("\n\n")
    assert len(parts[0].splitlines()) == 7  # a table: its two head lines and the five lights
    assert parts[1:3] == ["Something needs a look.", "### Health"]
    assert parts[3].startswith("Use: ") and parts[4] == "### Waiting for you"
    assert parts[5].startswith("- Verdict: ")


def test_all_grey_does_not_say_all_is_well():
    lights = [{"id": "works", "name": "Works", "state": "grey", "why": ""}]
    body = render({**DESK, "overall": "grey", "lights": lights})
    assert "is well" not in body and "none is amber or red" in body


def test_a_lights_address_is_linked_when_it_is_on_github():
    light = {"id": "clients", "name": "Clients", "state": "red", "url": URL,
             "why": "Issue #12 (a confirmed major client change) has been open 8.0 days."}
    body = render({**DESK, "lights": [light]})
    assert light_line(body, "Clients").endswith(f"> | [{one_line(light['why'])}]({URL}) |")
    for url in ("http://evil.example/x", "https://github.com/x) [y](http://evil"):
        body = render({**DESK, "lights": [{**light, "url": url}], "waiting": [], "misses": []})
        assert "evil" not in body and 'alt="wrong"> | Issue &#35;12' in light_line(body, "Clients")


# --- What build writes, rendered ---


def test_the_page_of_what_build_writes_from_every_fact():
    body = render(build(FACTS, ROSTER, NOW))
    assert lead(body) == "All five lights are green."
    assert "None" not in body and "null" not in body
    assert "not measured" not in body.lower().replace("not measured yet: nightly, tester.", "")
    assert "| Claude reviewer | 12 | 1 | 1 | 0 | 0 | 0 |" in body
    assert "| Release prep | 1 | 0 | 1 | — | — | — |" in body
    assert "- Pull request: [p](https://github.com/KonstantinStarovoytov/kitden/pull/79)" in body
    assert "merge it with a merge commit." in body


def test_the_page_of_what_build_writes_from_no_fact():
    body = render(build(Facts(), ROSTER, NOW))
    assert "None" not in body and "null" not in body and "| |" not in body
    assert lead(body) == "Some lights are not measured yet; none is amber or red."
    assert body.count('alt="not measured"> |') == 5
    assert "## Waiting for you\n\nNot measured." in body
    assert "The agents' week: not measured yet." in body
    assert "Reviews: not measured yet." in body and "Misses: not measured yet." in body
