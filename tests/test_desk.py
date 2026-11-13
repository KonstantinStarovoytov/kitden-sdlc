import json
from datetime import UTC, datetime, timedelta, timezone
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
FRESH = [{"date": "2026-11-16", "pieces": 5, "judged": 5}]  # ruling 3: a run that judged
FACTS = Facts(
    issues=[bot(1, labels=MAJOR, created=ago(2)), person(2, labels=("bug",), created=ago(3))],
    pulls=[pull(79, branch="prepare-v0.9.0", login="kitden-beacon[bot]")],
    reviews=[review(70, counts(0, 0), merged="2026-11-12T10:00:00Z")],
    checks=[OK],
    required=["build"],
    runs={"claude": 12, "luna": 12, "watcher": 7, "release-prep": 1},
    failed={"claude": 1, "luna": 1, "watcher": 0, "release-prep": 0},
    silent=[],
    watch_log=FRESH,
    stars=12,
    downloads=340,
)


def test_works():
    assert light_works(None)["state"] == light_works([])["state"] == "grey"
    assert light_works([OK], ["build"])["state"] == "green"
    running = {**OK, "name": "lint", "status": "in_progress", "conclusion": None}
    assert light_works([OK, running], ["build"])["state"] == "amber"
    red = light_works([OK, {**OK, "name": "lint", "conclusion": "failure"}], ["lint"])
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
    rows = week(ROSTER, reviews, issues, pulls, {"claude": 12, "watcher": 7}, NOW,
                failed={"claude": 2, "watcher": 0}, silent=[])
    assert [row["agent"] for row in rows] == ["claude", "luna", "watcher", "release-prep"]
    assert rows[0] == {"agent": "claude", "name": "Claude reviewer", "runs": 12, "failed": 2,
                       "did": 1, "agreed": 1, "disagreed": 0, "no_answer": 0}
    assert rows[1]["runs"] is None and rows[1]["failed"] is None and rows[1]["did"] == 1
    assert "no_answer" not in rows[2] and rows[2]["failed"] == 0
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


# --- A list of main's rules that was only partly read ---


def test_a_partial_list_of_rules_still_shows_the_bad_news_it_holds():
    red = light_agents([], ["review / claude"], NOW, partial=True)
    assert red["state"] == "red" and "review / claude" in red["why"]
    assert light_works([OK], ["lint"], partial=True)["state"] == "amber"
    failed = {**OK, "name": "lint", "conclusion": "failure"}
    assert light_works([OK, failed], ["build"], partial=True)["state"] == "red"


def test_a_partial_list_with_nothing_bad_is_grey_and_says_so():
    agents = light_agents([], ["build (ubuntu-latest)"], NOW, partial=True)
    assert agents["state"] == "grey" and "partly" in agents["why"]
    for required in (["build"], []):
        works = light_works([OK], required, partial=True)
        assert works["state"] == "grey" and "partly" in works["why"]
    assert light_agents([], [], NOW, partial=True)["state"] == "grey"


def test_a_list_read_whole_with_nothing_bad_stays_green():
    assert light_agents([], ["build"], NOW, partial=False)["state"] == "green"
    assert light_works([OK], ["build"], partial=False)["state"] == "green"
    assert light_agents([], ["build"], NOW)["state"] == "green"


def test_build_passes_the_partial_flag_to_works_and_agents():
    facts = Facts(issues=[], checks=[OK], required=["build"], required_partial=True)
    states = {light["id"]: light["state"] for light in build(facts, ROSTER, NOW)["lights"]}
    assert states["works"] == states["agents"] == "grey"
    facts = Facts(issues=[], checks=[OK], required=["review / claude"], required_partial=True)
    states = {light["id"]: light["state"] for light in build(facts, ROSTER, NOW)["lights"]}
    assert states["agents"] == "red"
    whole = Facts(issues=[], checks=[OK], required=["build"], runs=FACTS.runs,
                  failed=FACTS.failed, reviews=[], silent=[])
    states = {light["id"]: light["state"] for light in build(whole, ROSTER, NOW)["lights"]}
    assert states["works"] == states["agents"] == "green"
    assert {light["state"] for light in build(Facts(), ROSTER, NOW)["lights"]} == {"grey"}


# --- Beyond the brief: the edges its rules imply ---

MINUTE = 1 / 1440


def test_clients_turn_amber_past_3_5_days_and_red_past_7():
    def state(days):
        return light_clients([bot(5, labels=MAJOR, created=ago(days))], FRESH, NOW)["state"]
    assert [state(d) for d in (3.5, 3.5 + MINUTE, 7, 7 + MINUTE)] == [
        "green", "amber", "amber", "red"]


def run_on(date, pieces=5, judged=5):
    return {"date": date, "pieces": pieces, "judged": judged, "failed": pieces - judged}


def test_the_watch_log_goes_grey_past_2_days():
    midnight = datetime(2026, 11, 16, tzinfo=UTC)
    assert light_clients([], [run_on("2026-11-14")], midnight)["state"] == "green"
    assert light_clients([], [run_on("2026-11-14")], midnight + timedelta(minutes=1))[
        "state"] == "grey"
    newest = [run_on("2026-11-16"), run_on("2026-11-01")]
    assert light_clients([], newest, NOW)["state"] == "green"
    assert light_clients([], [], NOW)["state"] == "grey"
    assert light_clients([], [{"pieces": 3, "judged": 3}], NOW)["state"] == "grey"
    assert light_clients([], [run_on("2026-11-13"), run_on("2099-01-01")], NOW)[
        "state"] == "grey"


def test_a_watcher_run_that_judged_nothing_is_not_a_measurement():
    assert light_clients([], [run_on("2026-11-16", judged=0)], NOW)["state"] == "grey"
    assert light_clients([], [run_on("2026-11-16", pieces=0, judged=0)], NOW)["state"] == "green"
    assert light_clients([], [run_on("2026-11-16", judged=1)], NOW)["state"] == "green"
    assert light_clients([], [{"date": "2026-11-16"}], NOW)["state"] == "grey"
    assert light_clients([], [{"date": "2026-11-16", "pieces": "0"}], NOW)["state"] == "grey"
    fell = [run_on("2026-11-16", judged=0), run_on("2026-11-15")]
    assert light_clients([], fell, NOW)["state"] == "green"
    fell = [run_on("2026-11-16", judged=0), run_on("2026-11-12")]
    assert light_clients([], fell, NOW)["state"] == "grey"


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


def test_a_required_check_must_have_passed_on_mains_newest_commit():
    assert light_works([OK], ["build"])["state"] == "green"
    missing = light_works([OK], ["build", "lint"])
    assert missing["state"] == "amber"
    assert missing["why"] == "lint has not passed on main's newest commit."
    skipped = {**OK, "name": "lint", "conclusion": "skipped"}
    assert light_works([OK, skipped], ["lint"])["state"] == "amber"
    failed = {**OK, "name": "test", "conclusion": "failure"}
    assert light_works([OK, failed], ["lint"])["state"] == "amber"  # main does not require test
    assert light_works([OK, failed], ["test"])["state"] == "red"
    assert light_works([OK], [])["state"] == "green"
    facts = Facts(checks=[OK], required=["lint"])
    assert build(facts, ROSTER, NOW)["lights"][0]["state"] == "amber"


def test_works_without_a_passed_check_is_grey():
    skipped = {**OK, "name": "skip", "conclusion": "skipped"}
    neutral = {**OK, "name": "neutral", "conclusion": "neutral"}
    assert light_works([skipped], [])["state"] == "grey"
    assert light_works([skipped, neutral], [])["state"] == "grey"
    queued = {**OK, "name": "q", "status": "queued", "conclusion": None}
    assert light_works([skipped, queued], [])["state"] == "amber"
    assert light_works([skipped, {**OK, "conclusion": "failure"}])["state"] == "red"


def test_a_check_with_an_unknown_ending_is_not_green():
    assert light_works([{**OK, "conclusion": "stale"}], [])["state"] == "amber"
    assert light_works([{**OK, "name": "skip", "conclusion": "skipped"}, OK], [])[
        "state"] == "green"


def test_a_persons_issue_with_the_bots_labels_waits_for_nobody():
    issues = [person(1, labels=("automated", "client-change", "major")),
              person(3, labels=("automated", "release")),
              person(6, "The client watcher is paused", labels=("automated", "desk"))]
    assert waiting(issues, [], [], NOW) == []


def test_a_closed_issue_waits_for_nobody():
    issues = [bot(1, labels=("automated", "client-change", "major"), state="closed"),
              bot(3, labels=("automated", "release"), state="closed")]
    assert waiting(issues, [], [], NOW) == []


def test_waiting_is_oldest_first_inside_each_kind_with_each_items_title():
    issues = [bot(n, f"Release {n}", labels=("automated", "release"), created=ago(d))
              for n, d in ((1, 1), (2, 5), (3, 3))]
    found = waiting(issues, [pull(79, "agent/x", login="kitden-beacon[bot]")], [], NOW)
    assert [w["url"].rsplit("/", 1)[-1] for w in found] == ["79", "2", "3", "1"]
    assert [w["title"] for w in found] == ["p", "Release 2", "Release 3", "Release 1"]
    assert set(found[0]) == {"kind", "title", "url", "do", "days"}


def test_a_waiting_title_is_one_line_of_at_most_100_characters():
    long = "Codex:  key\nrenamed " + "x" * 150
    found = waiting([bot(1, long, labels=("automated", "release"))], [], [], NOW)
    title = found[0]["title"]
    assert "\n" not in title and "  " not in title and len(title) == 100
    assert title.startswith("Codex: key renamed x")


def test_waiting_without_reviews_has_everything_but_the_spot_check():
    old = pull(79, "agent/x", login="kitden-beacon[bot]", created=ago(20))
    found = waiting([], [old], None, NOW)
    assert [w["kind"] for w in found] == ["pull"]
    assert waiting([], [], None, NOW) == []
    assert waiting([], None, [], NOW) is None


# --- Bad news the read facts prove wins over a fact that was not read ---


def test_a_stale_watch_log_does_not_hide_a_late_client_change():
    stale = [{"date": "2026-11-10", "pieces": 5, "judged": 5}]
    late = [bot(5, labels=MAJOR, created=ago(46))]
    assert light_clients(late, stale, NOW)["state"] == "red"
    assert light_clients(late, None, NOW)["state"] == "red"
    assert light_clients([bot(5, labels=MAJOR, created=ago(4))], None, NOW)["state"] == "amber"
    assert light_clients([bot(5, labels=MAJOR, created=ago(1))], stale, NOW)["state"] == "grey"


def test_one_missing_fact_does_not_hide_bad_news_on_agents():
    paused = bot(7, "The client watcher is paused", labels=("automated", "desk"))
    three = [bot(n, labels=("automated", "client-change", "major"), created=ago(0.1))
             for n in (1, 2, 3)]
    assert light_agents([paused], None, NOW)["state"] == "amber"
    assert light_agents(three, None, NOW)["state"] == "red"
    assert light_agents(None, ["review / claude"], NOW)["state"] == "red"
    assert light_agents(None, ["build"], NOW)["state"] == "grey"
    assert light_agents([], None, NOW)["state"] == "grey"


def test_an_old_pull_request_is_red_on_the_queue_without_reviews():
    old = pull(79, "agent/x", login="kitden-beacon[bot]", created=ago(20))
    assert light_queue(waiting([], [old], None, NOW), complete=False)["state"] == "red"
    assert light_queue([{"days": 4.0}], complete=False)["state"] == "amber"
    assert light_queue([{"days": 1.0}], complete=False)["state"] == "grey"
    assert light_queue([], complete=False)["state"] == "grey"
    lights = build(Facts(issues=[], pulls=[old]), ROSTER, NOW)["lights"]
    assert lights[-1]["state"] == "red"
    assert build(Facts(issues=[], pulls=[]), ROSTER, NOW)["lights"][-1]["state"] == "grey"


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
    assert light_works([OK], ["build"])["why"] == ""
    assert "not measured" in light_works(None)["why"].lower()


def test_build_writes_the_repository_the_facts_were_read_from():
    assert build(Facts(), ROSTER, NOW)["repo"] == REPO
    assert build(Facts(repo="someone/else"), ROSTER, NOW)["repo"] == "someone/else"


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


def test_each_light_keeps_proven_bad_news_when_another_fact_is_missing():
    issues = [bot(5, labels=MAJOR, created=ago(20)),
              bot(7, "The client watcher is paused", labels=("automated", "desk"))]
    old = pull(79, "agent/x", login="kitden-beacon[bot]", created=ago(20))
    facts = Facts(issues=issues, pulls=[old], checks=[{**OK, "conclusion": "failure"}])
    states = {light["id"]: light["state"] for light in build(facts, ROSTER, NOW)["lights"]}
    # Not read: the required checks, the watch log and the reviews.
    assert states == {"works": "red", "clients": "red", "bugs": "red", "agents": "amber",
                      "queue": "red"}


# --- Careful reading: causes, open state, bots, letter case, time ---


def caused(number, text):
    return person(number, labels=("bug",), created=ago(2),
                  body=f"### Steps\n\nx\n\n### Caused by\n\n{text}\n\n### Notes\n\n#72\n")


def test_every_reference_under_caused_by_counts_once():
    reviews = [review(70, counts(0, 0)), review(71, counts(0, 0)), review(72, counts(0, 0))]
    address = f"https://github.com/{REPO}/pull/70"
    found = misses([caused(81, "#71, #70"), caused(82, "PR #70"), caused(83, "`#70`"),
                    caused(84, "70"), caused(85, f"#70 and {address}"),
                    caused(86, f"{address}/files#diff-1"), caused(87, "_No response_")],
                   reviews, NOW)
    assert [(m["issue"], m["pull"]) for m in found] == [
        (81, 70), (81, 71), (82, 70), (83, 70), (85, 70), (86, 70)]
    other = "https://github.com/someone/else/pull/70"
    assert misses([caused(88, other)], reviews, NOW) == []
    assert [m["pull"] for m in misses([caused(89, "PR#70")], reviews, NOW)] == [70]
    assert misses([caused(90, "owner/repo#70 and &#70;")], reviews, NOW) == []


def test_an_open_issue_is_open_whatever_its_closed_at_says():
    grew = [person(n, labels=("bug",), created=ago(d)) for n, d in enumerate((25, 18, 11, 4))]
    grew[0]["closed_at"] = "2026-11-12T00:00:00Z"  # reopened: still "open"
    assert light_bugs(grew, NOW)["state"] == "red"


def test_an_account_of_type_bot_is_a_bot():
    copilot = {**pull(9, "agent/fix"), "user": {"login": "Copilot", "type": "Bot"}}
    assert [w["kind"] for w in waiting([], [copilot], [], NOW)] == ["pull"]
    assert use([], [copilot], None, None, NOW)["pulls_from_others"] == 0
    bug = person(5, labels=("bug",), created="2026-11-05T00:00:00Z")
    bug["user"]["type"] = "Bot"
    assert found_by([], [bug], NOW)[0]["others"] == 0


def test_a_required_review_check_is_red_in_any_letter_case():
    assert light_agents([], ["Review / Claude"], NOW)["state"] == "red"


def test_now_and_timestamps_are_read_in_utc():
    west = timezone(timedelta(hours=-8))
    late_on_the_first = datetime(2026, 12, 1, 3, tzinfo=UTC)
    opened = [person(1, created="2026-12-01T01:00:00Z")]
    assert use(opened, [], None, None, late_on_the_first.astimezone(west))[
        "issues_from_others"] == 1
    assert found_by([], opened, late_on_the_first.astimezone(west))[0]["month"] == "2026-12"
    no_offset = [bot(3, labels=("automated", "release"), created="2026-11-14T07:00:00")]
    assert waiting(no_offset, [], [], NOW)[0]["days"] == 2.0
    assert waiting(no_offset, [], [], NOW.replace(tzinfo=None))[0]["days"] == 2.0
    assert build(FACTS, ROSTER, NOW.astimezone(west))["updated"] == "2026-11-16T07:00:00Z"


def queue_of(facts):
    desk = build(facts, ROSTER, NOW)
    return desk["lights"][-1]["state"], desk["waiting"]


def test_the_queue_is_worked_out_from_every_item_the_read_facts_give():
    old_pull = pull(79, "agent/x", login="kitden-beacon[bot]", created=ago(20))
    old_release = bot(3, labels=("automated", "release"), created=ago(20))
    assert queue_of(Facts(pulls=[old_pull])) == ("red", None)
    assert queue_of(Facts(issues=[old_release], reviews=[])) == ("red", None)
    assert queue_of(Facts(issues=[], pulls=[], reviews=[])) == ("green", [])
    assert queue_of(Facts(issues=[], reviews=[])) == ("grey", None)
    assert queue_of(Facts(pulls=[pull(79, "agent/x", login="kitden-beacon[bot]")])) == (
        "grey", None)


def test_the_roster_gives_who_uses_each_key_as_a_list_of_names():
    for key in ROSTER["keys"]:
        assert isinstance(key["used_by"], list) and key["used_by"], key["name"]
        assert all(isinstance(name, str) and "," not in name for name in key["used_by"])
    assert build(Facts(), ROSTER, NOW)["budget"]["keys"] == ROSTER["keys"]


# --- Works judges main's own newest checks ---

# Shapes as GitHub gave them for Kitden's main on 2026-11-13 (commit 12a94bc): the push to
# main ran "Checks and release"; release prep was started by hand three times on that commit.
PUSH_RUN = "https://github.com/KonstantinStarovoytov/kitden/actions/runs/43513577178/job/1"
PREP_RUN = "https://github.com/KonstantinStarovoytov/kitden/actions/runs/43513690445/job/2"


def check(name, conclusion="success", started="2026-11-13T21:46:00Z", event="push",
          status="completed", url=PUSH_RUN):
    return {"name": name, "status": status, "conclusion": conclusion, "started_at": started,
            "details_url": url, "event": event}


BUILDS = [check("build (ubuntu-latest)"), check("build (macos-latest)")]
REQUIRED = ["build (macos-latest)", "build (ubuntu-latest)"]


def test_a_healthy_main_is_green():
    healthy = [*BUILDS, check("autotag", started="2026-11-13T21:54:05Z"),
               check("publish", "skipped", started="2026-11-13T21:54:00Z")]
    assert light_works(healthy, REQUIRED) == {"id": "works", "name": "Works", "state": "green",
                                              "why": ""}


def test_only_the_newest_run_of_each_check_is_judged():
    # Release prep failed at 10:30 and passed whole at 10:32 on the same commit.
    failed = check("prepare / agent", "failure", started="2026-11-13T10:30:00Z", event=None)
    passed = check("prepare / agent", started="2026-11-13T10:32:00Z", event=None)
    assert light_works([*BUILDS, failed, passed], REQUIRED)["state"] == "green"
    assert light_works([*BUILDS, passed, failed], REQUIRED)["state"] == "green"  # any order
    # The other way round, the newest run failed: that is bad news.
    late = {**failed, "started_at": "2026-11-13T10:34:00Z"}
    assert light_works([*BUILDS, passed, late], REQUIRED)["state"] == "amber"
    assert light_works([*BUILDS, passed, late], None)["state"] == "red"


def test_a_failed_run_started_by_hand_beside_green_builds_is_green():
    prep = [check("prepare / agent", "failure", "2026-11-13T21:47:21Z", "workflow_dispatch",
                  url=PREP_RUN),
            check("prepare / prepare", "failure", "2026-11-13T21:53:43Z", "workflow_dispatch",
                  url=PREP_RUN),
            check("prepare / record", None, "2026-11-13T22:01:48Z", "workflow_dispatch",
                  status="in_progress", url=PREP_RUN)]
    assert light_works([*BUILDS, *prep], REQUIRED)["state"] == "green"
    watch = check("watch", "failure", event="schedule")
    assert light_works([*BUILDS, watch], REQUIRED)["state"] == "green"


def test_a_check_of_unknown_event_is_judged_as_before():
    unknown = check("prepare / agent", "failure", event=None, url="")
    red = light_works([*BUILDS, unknown], None)
    assert red["state"] == "red" and "prepare / agent" in red["why"]
    assert light_works([*BUILDS, unknown], REQUIRED)["state"] == "amber"


def test_a_required_check_counts_whatever_its_event():
    by_hand = check("build (ubuntu-latest)", "failure", "2026-11-13T22:00:00Z",
                    "workflow_dispatch")
    red = light_works([*BUILDS, by_hand], REQUIRED)
    assert red["state"] == "red" and "build (ubuntu-latest)" in red["why"]


def test_a_failed_check_main_does_not_require_is_amber_and_named():
    lint = check("lint", "failure")
    amber = light_works([*BUILDS, lint], REQUIRED)
    assert amber["state"] == "amber"
    assert amber["why"] == "On main, lint failed; main does not require it."


def test_a_failed_required_check_is_red():
    failed = [check("build (ubuntu-latest)", "failure"), check("build (macos-latest)")]
    red = light_works(failed, REQUIRED)
    assert red["state"] == "red" and red["why"].startswith("On main, build (ubuntu-latest) failed")


def test_every_failed_ending_is_red_when_required_and_when_rules_were_not_read():
    for ending in ("failure", "timed_out", "cancelled", "action_required", "startup_failure"):
        assert light_works([check("build (ubuntu-latest)", ending)], REQUIRED)["state"] == "red"
        assert light_works([check("lint", ending), *BUILDS], None)["state"] == "red"


def test_passing_checks_without_mains_rules_are_grey_not_green():
    grey = light_works(BUILDS, None)
    assert grey["state"] == "grey" and "main's rules were not read" in grey["why"]
    assert light_works(BUILDS, [])["state"] == "green"


def test_no_check_run_read_while_main_requires_some_is_amber():
    amber = light_works([], ["build"])
    assert amber["state"] == "amber"
    assert amber["why"] == "build has not run on main's newest commit."
    two = light_works([], REQUIRED)
    assert two["why"] == ("build (macos-latest), build (ubuntu-latest) have not run on main's "
                          "newest commit.")
    assert light_works([], [])["state"] == light_works([], None)["state"] == "grey"
    assert light_works(None, ["build"])["state"] == "grey"


# --- Failed runs and silent reviewers ---


def rows(**changes):
    """The week's rows of a healthy week, with `changes` per agent id."""
    base = {"claude": {"runs": 12, "failed": 1, "did": 9, "no_answer": 1},
            "luna": {"runs": 12, "failed": 1, "did": 9, "no_answer": 1},
            "watcher": {"runs": 7, "failed": 0}, "release-prep": {"runs": 1, "failed": 0}}
    return [{"agent": a["id"], "name": a["name"], "did": None, **base[a["id"]],
             **changes.get(a["id"].replace("-", "_"), {})} for a in ROSTER["agents"]]


def test_a_healthy_week_of_runs_keeps_agents_green():
    assert light_agents([], [], NOW, rows=rows())["state"] == "green"
    # Half failed is not more than half; three failed runs are fewer than four runs.
    assert light_agents([], [], NOW, rows=rows(watcher={"runs": 4, "failed": 2}))[
        "state"] == "green"
    assert light_agents([], [], NOW, rows=rows(release_prep={"runs": 3, "failed": 3}))[
        "state"] == "green"
    assert light_agents([], [], NOW, rows=rows(claude={"did": 1, "no_answer": 2}))[
        "state"] == "green"


def test_an_agent_failing_most_of_its_runs_turns_agents_amber():
    amber = light_agents([], [], NOW, rows=rows(watcher={"runs": 5, "failed": 3}))
    assert amber["state"] == "amber"
    assert amber["why"] == "In the last 7 days, Client watcher failed 3 of its 5 runs."


def test_a_reviewer_mostly_silent_turns_agents_amber():
    amber = light_agents([], [], NOW, rows=rows(luna={"did": 1, "no_answer": 3}))
    assert amber["state"] == "amber"
    assert amber["why"] == "In the last 7 days, Luna reviewer gave no answer in 3 of 4 reviews."


def test_runs_that_were_not_read_leave_agents_grey_not_green():
    grey = light_agents([], [], NOW, rows=rows(claude={"failed": None}, luna={"failed": None}))
    assert grey["state"] == "grey" and "Claude reviewer" in grey["why"]
    grey = light_agents([], [], NOW, rows=rows(claude={"no_answer": None}))
    assert grey["state"] == "grey" and "reviews" in grey["why"]


def test_the_week_counts_failed_runs_and_silent_reviews():
    answered = [review(70, counts(1, None), updated=ago(1)),
                review(71, counts(0, 0), updated=ago(2)),
                review(72, counts(None, 0), updated=ago(20))]  # older than 7 days
    silent = [Review(73, counts(None, None), 0, 0, updated=ago(3), created=ago(4))]
    found = week(ROSTER, answered, [], [], {"claude": 4}, NOW, failed={"claude": 3},
                 silent=silent)
    claude, luna = found[0], found[1]
    assert (claude["runs"], claude["failed"], claude["did"], claude["no_answer"]) == (4, 3, 2, 1)
    assert (luna["did"], luna["no_answer"]) == (1, 2)
    assert week(ROSTER, answered, [], [], {}, NOW, silent=None)[0]["no_answer"] is None
    assert week(ROSTER, None, [], [], {}, NOW, silent=[])[0]["no_answer"] is None


def test_build_lights_agents_from_the_weeks_failed_runs():
    facts = Facts(issues=[], required=[], runs={"claude": 6}, failed={"claude": 4}, reviews=[],
                  silent=[])
    agents = build(facts, ROSTER, NOW)["lights"][3]
    assert agents["state"] == "amber" and "Claude reviewer failed 4 of its 6 runs" in agents["why"]
    desk = build(FACTS, ROSTER, NOW)
    assert desk["lights"][3]["state"] == "green" and desk["week"][0]["failed"] == 1
