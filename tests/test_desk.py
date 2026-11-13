import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from count_reviews import MAINTAINER, REPO, Review
from desk import (
    Facts,
    build,
    found_by,
    light_agents,
    light_bugs,
    light_clients,
    light_queue,
    light_works,
    misses,
    overall,
    use,
    waiting,
    week,
)
from tests.fakes import issue

ROOT = Path(__file__).resolve().parent.parent
ROSTER = json.loads((ROOT / "config/agents.json").read_text())
NOW = datetime(2026, 11, 16, 7, tzinfo=UTC)  # a Monday


def ago(days, now=NOW):
    return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def bot(number, title="t", **kw):
    return issue(number, title, **kw)


def person(number, title="t", login="someone", **kw):
    return issue(number, title, login=login, **kw)


ONE_DAY_AGO, TWO_DAYS_AGO = ago(1), ago(2)


def pull(number, branch, login="someone", state="open", created=ONE_DAY_AGO):
    return {"number": number, "title": "p", "state": state, "user": {"login": login},
            "head": {"ref": branch}, "created_at": created, "merged_at": None, "draft": False,
            "html_url": f"https://github.com/{REPO}/pull/{number}"}


def counts(claude, luna, both=0):
    return {"claude": claude, "luna": luna, "both": both}


def review(pr, counts, fixed=0, up=0, down=0, merged=None, updated=ONE_DAY_AGO):
    return Review(pr, counts, up, down, fixed=fixed, updated=updated,
                  created="2026-11-01T00:00:00Z", merged=merged)


OK = {"name": "build", "status": "completed", "conclusion": "success"}
MAJOR = ("automated", "client-change", "major", "confirmed")
FRESH = [{"date": "2026-11-16"}]
FACTS = Facts(
    issues=[bot(1, labels=MAJOR, created=ago(2)), person(2, labels=("bug",), created=ago(3))],
    pulls=[pull(79, branch="prepare-v0.9.0", login="kitden-beacon[bot]")],
    reviews=[review(70, counts(0, 0), merged="2026-11-12T10:00:00Z")],
    checks=[OK],
    required=["build (ubuntu-latest)"],
    runs={"claude": 12, "luna": 12, "watcher": 7, "release-prep": 1},
    watch_log=FRESH,
    stars=12,
    downloads=340,
)


def test_works():
    assert light_works(None)["state"] == light_works([])["state"] == "grey"
    assert light_works([OK])["state"] == "green"
    running = {**OK, "status": "in_progress", "conclusion": None}
    assert light_works([OK, running])["state"] == "amber"
    red = light_works([OK, {**OK, "name": "lint", "conclusion": "failure"}])
    assert red["state"] == "red" and "lint" in red["why"]


def test_clients():
    assert light_clients([], None, NOW)["state"] == "grey"
    assert light_clients([], [{"date": "2026-11-13"}], NOW)["state"] == "grey"
    assert light_clients(None, FRESH, NOW)["state"] == "grey"
    assert light_clients([], FRESH, NOW)["state"] == "green"
    assert light_clients([bot(5, labels=MAJOR, created=ago(4))], FRESH, NOW)["state"] == "amber"
    assert light_clients([bot(5, labels=MAJOR, created=ago(8))], FRESH, NOW)["state"] == "red"
    ignored = [bot(1, labels=MAJOR[:3], created=ago(9)), person(2, labels=MAJOR, created=ago(9)),
               bot(3, labels=MAJOR, created=ago(9), state="closed")]
    assert light_clients(ignored, FRESH, NOW)["state"] == "green"


def test_bugs():
    def bugs(*days):
        return [person(n, labels=("bug",), created=ago(d)) for n, d in enumerate(days)]
    assert light_bugs(None, NOW)["state"] == "grey"
    assert light_bugs([], NOW)["state"] == "green"
    assert light_bugs(bugs(25, 18, 11, 4), NOW)["state"] == "red"
    assert light_bugs(bugs(30, 11, 4), NOW)["state"] == "amber"
    assert light_bugs(bugs(30, 29, 28), NOW)["state"] == "green"
    assert light_bugs([bot(9, labels=MAJOR, created=ago(15))], NOW)["state"] == "red"


def test_agents():
    assert light_agents([], None, NOW)["state"] == "grey"
    assert light_agents([], ["build (ubuntu-latest)"], NOW)["state"] == "green"
    assert light_agents([], ["review / claude"], NOW)["state"] == "red"
    paused = bot(7, "The client watcher is paused", labels=("automated", "desk"))
    assert light_agents([paused], [], NOW)["state"] == "amber"
    assert light_agents([person(7, "The client watcher is paused")], [], NOW)["state"] == "green"
    three = [bot(n, labels=("automated", "client-change", "major"), created=ago(0.1))
             for n in (1, 2, 3)]
    assert light_agents(three, [], NOW)["state"] == "red"


def test_queue_and_overall():
    assert light_queue(None)["state"] == "grey" and light_queue([])["state"] == "green"
    assert light_queue([{"days": 4.0}])["state"] == "amber"
    assert light_queue([{"days": 7.5}])["state"] == "red"
    assert overall(["green", "green"]) == "green" and overall(["green", "grey"]) == "grey"
    assert overall(["grey", "amber"]) == "amber" and overall(["amber", "red", "grey"]) == "red"


def test_waiting_is_what_the_owner_must_do_in_order():
    issues = [
        bot(1, "Codex: key renamed", labels=("automated", "client-change", "major"),
            created=ago(2)),
        bot(2, "Client changes, week of 2026-11-09",
            labels=("automated", "client-change", "summary")),
        bot(3, "Time for a release?", labels=("automated", "release")),
        bot(4, labels=MAJOR),
        person(5, "Time for a release?"),
        bot(6, "The client watcher is paused", labels=("automated", "desk")),
    ]
    pulls = [pull(79, branch="prepare-v0.9.0", login="kitden-beacon[bot]"),
             pull(80, branch="agent/x", login=MAINTAINER),
             pull(81, branch="agent/y", state="closed")]
    found = waiting(issues, pulls, [], NOW)
    assert [(w["kind"], w["url"].rsplit("/", 1)[-1]) for w in found] == [
        ("pull", "79"), ("verdict", "1"), ("release", "3"), ("paused", "6")]
    assert found[1]["days"] == 2.0 and "false-alarm" in found[1]["do"]
    assert waiting(None, pulls, [], NOW) is None


def test_spot_check_is_the_last_clean_review_of_the_week_until_a_vote():
    week = [review(70, counts(0, 0), merged="2026-11-12T10:00:00Z"),
            review(71, counts(0, 0), merged="2026-11-14T10:00:00Z"),
            review(72, counts(1, 0), merged="2026-11-15T10:00:00Z"),
            review(73, counts(0, 0), merged="2026-11-16T05:00:00Z")]
    spots = [w for w in waiting([], [], week, NOW) if w["kind"] == "spot-check"]
    assert [w["url"].rsplit("/", 1)[-1] for w in spots] == ["71"]
    week[0].up = 1
    assert not [w for w in waiting([], [], week, NOW) if w["kind"] == "spot-check"]


def test_found_by_counts_each_bug_by_who_found_it():
    day = "2026-11-05T00:00:00Z"
    reviews = [review(70, counts(2, 0), fixed=2, merged="2026-11-12T10:00:00Z")]
    issues = [bot(1, labels=MAJOR, created=day),
              *[person(n, labels=("bug",), login=MAINTAINER, created=day) for n in (2, 3, 4)],
              person(5, labels=("bug",), created=day),
              person(6, labels=("bug",), login="dependabot[bot]", created=day)]
    rows = found_by(reviews, issues, NOW)
    assert [row["month"] for row in rows] == ["2026-11", "2026-10", "2026-09"]
    assert rows[0] == {"month": "2026-11", "review": 2, "nightly": None, "tester": None,
                       "watcher": 1, "owner": 3, "others": 1}


def test_a_bug_caused_by_a_reviewed_pull_request_is_a_miss():
    def bug(number, cause, created=TWO_DAYS_AGO):
        body = f"### Steps\n\nx\n\n### Caused by\n\n{cause}\n"
        return person(number, labels=("bug",), created=created, body=body)
    reviews = [review(70, counts(0, 0))]
    hit = bug(81, "#70")
    assert misses([hit], reviews, NOW) == [{"issue": 81, "pull": 70, "url": hit["html_url"]}]
    by_address = bug(82, "https://github.com/KonstantinStarovoytov/kitden/pull/70")
    assert misses([by_address], reviews, NOW)[0]["pull"] == 70
    none = [bug(83, "_No response_"), bug(84, "#71"), bug(85, "#70", created=ago(31))]
    assert misses(none, reviews, NOW) == []


def test_week_has_a_row_per_agent_and_none_for_what_was_not_read():
    reviews = [review(70, counts(1, 0), up=1, updated=ago(2)),
               review(60, counts(0, None), updated=ago(20))]
    issues = [bot(1, labels=("automated", "client-change", "major"), created=ago(3)),
              bot(2, labels=MAJOR, created=ago(20)),
              bot(3, labels=("automated", "client-change", "false-alarm"), created=ago(40))]
    pulls = [pull(79, branch="prepare-v0.9.0", login="kitden-beacon[bot]", created=ago(2))]
    rows = week(ROSTER, reviews, issues, pulls, {"claude": 12, "watcher": 7}, NOW)
    assert [row["agent"] for row in rows] == ["claude", "luna", "watcher", "release-prep"]
    assert rows[0] == {"agent": "claude", "name": "Claude reviewer", "runs": 12, "did": 1,
                       "agreed": 1, "disagreed": 0}
    assert rows[1]["runs"] is None and rows[1]["did"] == 1
    assert (rows[2]["did"], rows[2]["agreed"], rows[2]["disagreed"]) == (1, 1, 0)
    assert rows[3]["did"] == 1 and rows[3]["agreed"] is None


def test_use_counts_what_other_people_opened_this_month():
    issues = [person(1, created="2026-11-02T00:00:00Z"), bot(3, created="2026-11-02T00:00:00Z"),
              person(2, login=MAINTAINER, created="2026-11-02T00:00:00Z"),
              person(4, created="2026-10-30T00:00:00Z")]
    pulls = [pull(9, branch="fix", created="2026-11-03T00:00:00Z"),
             pull(10, branch="bump", login="dependabot[bot]", created="2026-11-03T00:00:00Z")]
    assert use(issues, pulls, 12, None, NOW) == {
        "issues_from_others": 1, "pulls_from_others": 1, "stars": 12, "downloads": None}
    assert use(None, None, None, None, NOW)["issues_from_others"] is None


def test_build_has_every_part():
    desk = build(FACTS, ROSTER, NOW)
    assert desk["version"] == 1 and desk["updated"] == "2026-11-16T07:00:00Z"
    assert [light["id"] for light in desk["lights"]] == [
        "works", "clients", "bugs", "agents", "queue"]
    assert set(desk) == {"version", "updated", "repo", "overall", "lights", "use", "waiting",
                         "week", "review", "found_by", "misses", "budget"}


def test_build_without_facts_is_grey_never_green():
    desk = build(Facts(), ROSTER, NOW)
    assert desk["overall"] == "grey"
    assert {light["state"] for light in desk["lights"]} == {"grey"}
    assert desk["waiting"] is None and desk["use"]["stars"] is None
    json.dumps(desk)  # it is plain data


# --- Beyond the brief: the edges its rules imply ---

MINUTE = 1 / 1440


def test_clients_turn_amber_past_3_5_days_and_red_past_7():
    def state(days):
        return light_clients([bot(5, labels=MAJOR, created=ago(days))], FRESH, NOW)["state"]
    assert [state(d) for d in (3.5, 3.5 + MINUTE, 7, 7 + MINUTE)] == [
        "green", "amber", "amber", "red"]


def test_the_watch_log_goes_grey_past_2_days():
    midnight = datetime(2026, 11, 16, tzinfo=UTC)
    assert light_clients([], [{"date": "2026-11-14"}], midnight)["state"] == "green"
    assert light_clients([], [{"date": "2026-11-14"}], midnight + timedelta(minutes=1))[
        "state"] == "grey"
    newest = [{"date": "2026-11-16"}, {"date": "2026-11-01"}]
    assert light_clients([], newest, NOW)["state"] == "green"
    assert light_clients([], [], NOW)["state"] == "grey"
    assert light_clients([], [{"pieces": 3}], NOW)["state"] == "grey"
    assert light_clients([], [{"date": "2026-11-13"}, {"date": "2099-01-01"}], NOW)[
        "state"] == "grey"


def test_bugs_turn_amber_past_7_days_and_red_past_14():
    def state(days):
        return light_bugs([bot(9, labels=MAJOR, created=ago(days))], NOW)["state"]
    assert [state(d) for d in (7, 7 + MINUTE, 14, 14 + MINUTE)] == [
        "green", "amber", "amber", "red"]


def test_a_closed_or_unconfirmed_issue_does_not_light_bugs():
    old = ago(20)
    assert light_bugs([bot(9, labels=MAJOR, created=old, state="closed")], NOW)["state"] == "green"
    assert light_bugs([bot(9, labels=MAJOR[:3], created=old)], NOW)["state"] == "green"
    assert light_bugs([person(9, labels=MAJOR, created=old)], NOW)["state"] == "green"


def test_a_bug_closed_before_a_monday_is_not_open_on_it():
    # Open on 11-02, 11-09 and 11-16 with these, it grew on the last three Mondays.
    grew = [person(n, labels=("bug",), created=ago(d)) for n, d in enumerate((25, 18, 11, 4))]
    assert light_bugs(grew, NOW)["state"] == "red"
    # The oldest closes on 11-12: the count on 11-16 is 3, the same as on 11-09.
    grew[0] |= {"state": "closed", "closed_at": "2026-11-12T00:00:00Z"}
    assert light_bugs(grew, NOW)["state"] == "green"


def test_queue_turns_amber_past_3_5_days_and_red_past_7():
    states = [light_queue([{"days": d}])["state"] for d in (3.5, 3.6, 7.0, 7.1)]
    assert states == ["green", "amber", "amber", "red"]
    assert light_queue([{"days": 1.0}, {"days": 8.0}])["state"] == "red"


def test_agents_count_only_this_iso_weeks_findings_by_the_bot():
    labels = ("automated", "client-change", "major")
    monday = NOW.replace(hour=0)
    before = (monday - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    on_monday = monday.strftime("%Y-%m-%dT%H:%M:%SZ")
    two = [bot(n, labels=labels, created=on_monday) for n in (1, 2)]
    assert light_agents(two, [], NOW)["state"] == "green"
    assert light_agents([*two, bot(3, labels=labels, created=before)], [], NOW)["state"] == "green"
    summary = bot(3, labels=("automated", "client-change", "summary"), created=on_monday)
    assert light_agents([*two, summary], [], NOW)["state"] == "green"
    theirs = person(3, labels=labels, created=on_monday)
    assert light_agents([*two, theirs], [], NOW)["state"] == "green"
    closed = bot(3, labels=labels, created=on_monday, state="closed")
    assert light_agents([*two, closed], [], NOW)["state"] == "red"


def test_a_closed_pause_does_not_light_agents():
    paused = bot(7, "The client watcher is paused", labels=("automated", "desk"), state="closed")
    assert light_agents([paused], [], NOW)["state"] == "green"


def test_a_check_with_an_unknown_ending_is_not_green():
    assert light_works([{**OK, "conclusion": "stale"}])["state"] == "amber"
    assert light_works([{**OK, "conclusion": "skipped"}, OK])["state"] == "green"


def test_a_persons_issue_with_the_bots_labels_waits_for_nobody():
    issues = [person(1, labels=("automated", "client-change", "major")),
              person(3, labels=("automated", "release")),
              person(6, "The client watcher is paused", labels=("automated", "desk"))]
    assert waiting(issues, [], [], NOW) == []


def test_a_closed_issue_waits_for_nobody():
    issues = [bot(1, labels=("automated", "client-change", "major"), state="closed"),
              bot(3, labels=("automated", "release"), state="closed")]
    assert waiting(issues, [], [], NOW) == []


def test_waiting_is_oldest_first_inside_each_kind_and_names_no_title():
    issues = [bot(n, f"Secret title {n}", labels=("automated", "release"), created=ago(d))
              for n, d in ((1, 1), (2, 5), (3, 3))]
    found = waiting(issues, [], [], NOW)
    assert [w["url"].rsplit("/", 1)[-1] for w in found] == ["2", "3", "1"]
    assert all("Secret" not in w["title"] for w in found)
    assert set(found[0]) == {"kind", "title", "url", "do", "days"}


def test_waiting_without_reviews_is_not_measured():
    assert waiting([], [], None, NOW) is None


def test_the_spot_check_window_is_the_7_days_before_monday():
    monday = "2026-11-16T00:00:00Z"
    reviews = [review(70, counts(0, 0), merged="2026-11-09T00:00:00Z"),
               review(71, counts(0, 0), merged="2026-11-08T23:59:59Z")]
    spot = [w for w in waiting([], [], reviews, NOW) if w["kind"] == "spot-check"]
    assert len(spot) == 1 and spot[0]["url"] == f"https://github.com/{REPO}/pull/70"
    assert spot[0]["title"] == "#70, reviewed with no findings" and spot[0]["days"] == 0.3
    reviews[0].down = 1
    assert not [w for w in waiting([], [], reviews, NOW) if w["kind"] == "spot-check"]
    late = [review(72, counts(0, 0), merged=monday)]
    assert not [w for w in waiting([], [], late, NOW) if w["kind"] == "spot-check"]


def test_a_persons_issue_with_the_bots_labels_is_not_the_watchers():
    issues = [person(1, labels=MAJOR, created="2026-11-05T00:00:00Z")]
    assert found_by([], issues, NOW)[0]["watcher"] == 0
    assert week(ROSTER, [], issues, [], {}, NOW)[2]["agreed"] == 0


def test_numbers_that_were_not_read_are_none():
    rows = found_by(None, [], NOW)
    assert rows[0]["review"] is None and rows[0]["owner"] == 0
    assert found_by([], None, NOW)[0]["watcher"] is None
    assert misses(None, [], NOW) is None and misses([], None, NOW) is None
    rows = week(ROSTER, None, None, None, {}, NOW)
    assert {value for row in rows for key, value in row.items()
            if key not in ("agent", "name")} == {None}
    assert overall([]) == "grey"


def test_a_light_that_is_not_green_says_why_with_numbers():
    late = light_clients([bot(5, "Codex: key renamed", labels=MAJOR, created=ago(8))], FRESH, NOW)
    assert "#5" in late["why"] and "8.0" in late["why"] and "Codex" not in late["why"]
    assert light_works([OK])["why"] == ""
    assert "not measured" in light_works(None)["why"].lower()


def test_build_reads_the_review_summary_and_the_roster():
    desk = build(FACTS, ROSTER, NOW)
    assert desk["repo"] == REPO and desk["review"]["clean"] == 1
    assert desk["budget"]["keys"] == ROSTER["keys"]
    assert desk["budget"]["agents"][0] == {"agent": "claude", "runs": 12,
                                           "cap": ROSTER["agents"][0]["cap"]}
    assert desk["overall"] == "green", desk["lights"]
    empty = build(Facts(), ROSTER, NOW)
    assert empty["review"] == {"clean": None, "fixed": None, "days_to_merge": None}
    assert empty["misses"] is None and empty["budget"]["agents"][0]["runs"] is None
