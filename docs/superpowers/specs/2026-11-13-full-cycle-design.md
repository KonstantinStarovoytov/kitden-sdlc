# Agents for the whole cycle — design

Date: 2026-11-13. Status: draft for the owner's review. The owner's answers are marked
"(owner)" with the date; the writer's choices are marked "(call)". Facts about other projects
come from the research of 2026-11-12; the sources are at the end.

This document fixes the frame that every later agent follows, and describes stage 0 far enough
to plan it. Stages 1 to 4 are described far enough to show that nothing built earlier needs
redoing. Each of them gets its own short design when its turn comes, as the watcher and the
release flow did.

## Why

Kitden has one maintainer. He reviews every change, and he cannot test what he does not have:
Linux, other processor types, every version of Claude Code, Codex and Cursor. Bugs are hard to
find and hard to keep track of (owner, 2026-11-12).

Three parts already work: two reviewers, a client watcher and a release flow
([agents.md](../../agents.md)). The owner wants the rest of the cycle, and he wants it to be a
serious project. He named what that means:

| The owner asked for | This design answers with |
|---|---|
| Everything thought through | one frame for every agent (Part 1) |
| Every part worth having | keep criteria written first, and a monthly keep-or-cut (Part 3) |
| Real use: it saves time, finds problems, holds quality, follows the clients, and does the work of a developer, a tester, a test writer and a manager | the team (Part 4) and the stages (Part 5) |
| Safe | the eight rules and three more (Part 1.7) |
| Clear, documented, good to look at | the desk and the owner's page (Part 2) |
| It keeps getting better | every verdict becomes a test of the agent (Part 3) |
| Every choice has a reason | the table of choices at the end, kept as `docs/decisions.md` |

The research read the vendors' own setups, 19 large open-source projects and 24 similar
repositories. No public repository has all of kitden-sdlc's parts. The leaders (Anthropic,
OpenAI, GitHub, PyTorch, uv, Home Assistant) share one shape, and kitden-sdlc already has it:
the model reads, a job without a model writes, no agent merges, every action has a limit. They
have three things we lack: a limit on where an agent job can connect, one key per workflow, and
numbers that show how often the agents are right. What ends such setups is noise and lost
control: Django switched its automated reviews off, and the first known factory with no people
in it was rolled back after three months.

## The idea in three lines

**Scripts measure. Models propose. The owner decides.**

- A number, a check or a light always comes from a script. No model reports on its own work.
- What a model writes is always a proposal: a comment, an issue or a draft pull request. It
  says that a model wrote it.
- Only the owner merges, releases, confirms, and switches an agent on.

## Goals

1. The owner runs the project from one page and does every action with a normal GitHub click.
2. Kitden is tested where the owner cannot test it: more systems, the newest clients, the page
   in a real browser.
3. Agents take over in this order: finding bugs, writing tests, fixing the bugs the owner marks.
4. Health comes from signals no agent can change. A light with no data is grey, never green.
5. Every agent has limits, a switch, an eval before it goes live, numbers after, and written
   criteria for staying.
6. Nothing built in one stage is thrown away in the next.
7. A stranger reads in a few minutes what runs, why, and how well.

## Non-goals

- Auto-merge, or an agent that approves. No project in the research lets an agent merge.
- An agent that adds features. Agents keep Kitden working; anything new is the owner's.
- An agent that directs other agents. GitHub events, labels and checks do that, as today.
- A bot that answers people. The owner answers people.
- Moving to GitHub Agentic Workflows. We take two of its ideas (staged outputs, a host list).
- A framework for other projects. Others copy the files, as now.
- Windows. It follows the product's roadmap; the test matrix adds it then.
- Telemetry in Kitden. PRINCIPLES.md forbids it.
- Choosing models. That is a separate question (owner, 2026-11-12); each agent's eval picks.
- A dashboard app. The owner wants one later (2026-11-13); the desk keeps its data in a file so
  a dashboard can read it without a rebuild (2.1).

## Anti-goals (owner, 2026-11-12)

| A failure even if it works | Kept out by |
|---|---|
| A pile of bot issues nobody needs | evidence in every issue, weekly caps, pause on noise (1.2, 1.5) |
| A contributor blocked by automation | Part 1.3, checked by a script |
| Kitden gets worse while the automation says all is well | Part 2: scripts measure; grey lights; spot checks; who found each bug |
| A system the owner can no longer follow or steer | Part 1.5: one roster, one switch each, a cap on agents, the owner's pace |

## Part 1 — The frame

This part is meant to stay the same while agents, prompts and models change.

### 1.1 What an agent may put out

Each agent has one kind of output. The kinds are steps of trust, taken in order.

| Step | Output | Who has it | Limit |
|---|---|---|---|
| 1 | a comment on a pull request | the two reviewers (live) | one comment per pull request, 5 findings each |
| 2 | an issue | the watcher (live), the tester (stage 2) | 2 urgent issues a week per agent; a weekly summary is extra |
| 3 | a draft pull request that changes tests only | the test writer (stage 3) | 3 waiting, 2 a day, all agents together |
| 4 | a draft pull request that changes code | the fixer (stage 4) | the same 3 and 2 |
| never | approve, request changes, merge, push to `main`, close or label what a person opened | | |

An agent moves up a step, or from "on the owner's label" to "by itself", only by the owner's
decision on at least 30 days of its numbers.

Release prep is the one exception, and stays as built (call). The owner starts it by hand, so
it has no switch of its own and is outside the cap of 3 and 2. Its pull request is the release
itself, on a `prepare-vX.Y.Z` branch, and it may change the README and the policy files in a
commit of their own. It follows the rules in RULES.md. It has no eval yet, because the owner
reads every line it writes; its number is how much of its draft he changed before merging.

### 1.2 The contract every agent follows

1. **Start.** A GitHub event, a schedule, or a label the owner puts on. Never text from
   another agent.
2. **Input.** A job without a model prepares it in a folder. Text from outside is data.
3. **The model job.** Read only. Tools by exact name. A time limit and a turn limit. Its own
   key. It reaches only the hosts on its list (rule 9).
4. **Output.** One JSON file in a fixed schema.
5. **Posting.** A job without a model checks the file (schema, caps, secrets, repeats) and posts
   it as a bot. The post says it is automated and names the model.
6. **Evidence.** Each finding carries what a person needs to check it: a quote, a line, or a
   script that shows the bug.
7. **Next step.** The post ends with what the owner does, as a GitHub action: merge, close with
   a label, add a label, run a workflow.
8. **Origin and verdict.** A bot issue has the label `automated` and one origin label (1.6).
   An issue a model wrote waits for the owner's verdict. An issue a script wrote is a fact:
   it takes no verdict and closes itself when it no longer holds.
9. **Switch.** `AGENTS_ENABLED` stops everything; an agent that runs by itself also has its
   own switch. An agent the owner starts by hand needs none.
10. **Eval first.** Tasks from real Kitden cases, with clean cases and injection cases. The
    owner reads the table and sets the switch.
11. **Numbers after.** A row in the weekly numbers: what it did, how often the owner agreed,
    what it used.
12. **Keep criteria.** Written before it goes live: the numbers at which it stays, changes or
    goes.
13. **Roster.** One row in [agents.md](../../agents.md).

Steps 2 to 5 are today's rules 1 and 5 to 8. Steps 6 to 13 are what the reviewers and the
watcher already do in their own ways; stage 0 makes them the same for all.

### 1.3 Never in a contributor's way

- No agent job is a required check. A script reads Kitden's branch rules each week and turns
  the Agents light red if one is.
- No agent approves, requests changes, closes, locks or labels an issue or pull request that a
  person opened. A bot closes only its own issues, and knows them by their author, not by
  the title alone.
- When an agent fails or its budget ends, a contributor's pull request shows no red mark from
  it. The failure shows on the desk.
- A new test job runs nightly first. It becomes a check on pull requests only when it has not
  failed by chance for two weeks (call). A test that fails by chance is set aside and listed
  on the desk, not left to fail people.

### 1.4 What an agent can never change

- Anything on kitden-sdlc's `main`. Rules, prompts, skills, schemas and eval tasks change only
  by a person's pull request. No agent opens a pull request there. The `watch` and `numbers`
  branches hold only data, committed by jobs without a model.
- In Kitden: `.github/`, PRINCIPLES.md, the policy files, AGENTS.md, CONTRIBUTING.md, the
  dependency list and the lock file. A job without a model refuses a patch that touches them.
- What PRINCIPLES.md calls new: a route, a command, a setting, a page element, a dependency.
  The reviewers already name these in their summary; the owner merges.
- Its own grade. Facts in an agent's pull request (which files changed, which old tests
  changed, what the checks said) are written by a script, not by the model.

### 1.5 Pace, caps and control

- **The owner's pace.** At most 3 agent pull requests wait and at most 2 open a day (owner,
  2026-11-09). When the queue is full, agents that add to it wait.
- **Pause on noise.** When more than half of an agent's last 10 verdicts are `false-alarm`, its
  posting job opens one issue, "<agent> is paused", with the numbers, and opens nothing else
  while that issue is open. The owner lifts the pause by closing it; the count then starts
  again from issues opened after that day. With fewer than 10 verdicts there is no pause (call).
- **Agents write code only on the owner's label** (owner, 2026-11-12).
- **A cap on agents.** At most 8 agents that run a model (call). Today there are 4; this design
  adds 3. A ninth needs one removed, or a written case.
- **One roster.** Every agent that runs a model is one row in agents.md, with its switch.

### 1.6 Names fixed now

Labels and switches are what the owner uses, so they are hard to rename later. A label is
created in Kitden only when its stage goes live.

| Kind | Name | Meaning | Since |
|---|---|---|---|
| origin | `automated` | a bot opened it | live |
| origin | `client-change` | from the watcher | live |
| origin | `release` | from the release watch | stage 0 |
| origin | `desk` | the desk issue | stage 0 |
| origin | `ci-failure` | a nightly test job is red | stage 1 |
| origin | `qa-finding` | from the tester | stage 2 |
| verdict | `confirmed` | the owner agrees; the issue stays open until the problem is fixed | live; changed in stage 0 |
| verdict | `false-alarm` | the owner disagrees and closes the issue | live |
| command | `no-agent-review` | skip review on this pull request | live |
| command | `agent-test` | write a test for this issue | stage 3 |
| command | `agent-fix` | fix this bug | stage 4 |

An issue without `automated` is from a person. The "is paused" issue carries `automated` and
`desk`. Verdicts are for `client-change` and `qa-finding` issues, not for the watcher's
summary. A verdict is the label, not the closing (owner, 2026-11-13): until now the owner
closed an issue with `confirmed`, and nothing showed whether the problem was fixed.

Switches: `AGENTS_ENABLED` and `WATCH_LIVE` are live; stage 0 adds `REVIEW_LIVE` for the two
reviewers; later come `QA_LIVE`, `TEST_LIVE` and `FIX_LIVE`. A switch lives in the repository
whose workflow starts the agent: the watcher's in kitden-sdlc, the others in Kitden.
`AGENTS_ENABLED` is two variables, one in each repository, and the owner's page says so.

Agent pull requests use branches named `agent/…`. The desk issue is titled "Kitden desk". New
pages: `docs/owner.md`, `docs/decisions.md`.

### 1.7 Three more rules

They join [RULES.md](../../../RULES.md), and the checker enforces 9 and 10.

9. A job that runs a model reaches only the hosts on its written list.
10. A model step never prints its full output or debug logs. In a public repository those logs
    are public.
11. No agent is in anyone's way (the first three points of 1.3). This moves from
    MERGE_POLICY.md and now covers every agent.

MERGE_POLICY.md gains two lines: agents write code only on the owner's label, and agents never
add what PRINCIPLES.md calls new. A fourth rule, "a model never pushes: a job without a model
checks its patch and opens the draft pull request", comes with the stage 3 design.

## Part 2 — The owner's desk

### 2.1 One page

A pinned issue in Kitden, "Kitden desk", for now; a dashboard later (owner, 2026-11-13). A job
without a model works everything out each day and saves it as one data file, `desk.json`, on
the `numbers` branch. The issue is only a view of that file, and a later dashboard reads the
same file. The job rewrites the issue every day and adds one comment on Monday, so the owner
gets one notice a week. Lantern posts it. It shows:

1. **Health:** five lights and the reason for each one that is not green (2.2).
2. **Waiting for you:** agent pull requests, open bot issues without a verdict, a release that
   is due, two spot checks (2.4). Each line is a link and says what to do.
3. **Links:** issues from people; issues from bots; agent pull requests.
4. **This week:** one line per agent (did, agreed, used), and who found each bug (2.3).
5. **Budget:** runs and model calls per agent against its caps, the money cap of each key,
   and links to the two providers' dashboards. The providers enforce the money caps; stage 0
   stores no billing key.
6. **How to:** a link to the owner's page (2.5).

The public numbers page on the `numbers` branch stays, written from the same data, so there
is one truth. The watcher's Monday summary and the two release issues stay as they are; the
desk links to them.

### 2.2 Health: five lights

| Light | Green when | Data from |
|---|---|---|
| Works | `main` is green; from stage 1 also the nightly run on every system, and start-up within its time budget | check runs |
| Clients | no `confirmed` `major` client change is open over 7 days; from stage 1 also the checks against the newest client versions pass | watcher issues, nightly run |
| Bugs | open bugs did not grow three weeks in a row, and no `confirmed` `major` issue is open over 14 days (call) | issues |
| Agents | no agent is paused for noise or over its cap; no agent job is a required check | verdicts, runs, branch rules |
| Queue | nothing has waited for the owner over 7 days (call) | pull requests, issues |

The overall light is the worst one. A light without data is grey and says "not measured yet".
Below the lights, one line that is not a light: issues and pull requests from other people this
month, downloads and stars. Kitden has no telemetry, so use stays a rough signal. Whether Kitden
is pleasant to use no script can tell; that stays the owner's eye, helped by the before-and-after
screenshots every visible change already carries.

### 2.3 Who found each bug

A table by month: caught before merge (review findings whose lines then changed), by a nightly
job, by the tester, by the watcher, by the owner, by other people. It is counted from the
origin labels and the authors. The automation is worth having when the first columns grow and
the last two shrink. A bug a person found in something an agent called fine is a miss, and
becomes a task for that agent's eval (Part 3).

### 2.4 Spot checks

Each Monday the desk names two things the agents called fine, picked by a script (owner,
2026-11-12):

- one merged pull request whose review said "No problems found": the owner looks at the change
  and puts 👍 or 👎 on the review comment, as he already does;
- from stage 2, one area the tester reported clean: the owner tries it for five minutes and
  opens a normal bug if he finds one. The table in 2.3 then counts it as a miss.

No new buttons: the answers arrive through the votes and labels that already exist.

### 2.5 The owner's page

`docs/owner.md`: one table, one row per action, linked from the desk and the README.

| You want to | You do |
|---|---|
| Release | Actions → Release prep → Run workflow; merge "Kitden X.Y.Z" |
| Accept an agent's pull request | review it, press Ready for review, merge |
| Turn one down | close it |
| Say a bot issue is real | put `confirmed` on it; it stays open until fixed |
| Say a bot issue is wrong | close it with `false-alarm` |
| Say a review was useful or wrong | 👍 or 👎 on the "Agent review" comment |
| Ask for a test (stage 3) | put `agent-test` on the issue |
| Ask for a fix (stage 4) | put `agent-fix` on a `bug` issue |
| Skip review on one pull request | put `no-agent-review` on it |
| Start an agent again after a pause | close its "… is paused" issue |
| Stop one agent | set its switch variable to `false` |
| Stop everything | set `AGENTS_ENABLED` to `false` in both repositories |
| Answer a person | write yourself; no bot answers people |

## Part 3 — How it gets better

1. **A verdict becomes a task.** `watch_harvest.py` already turns the watcher's issues into
   eval tasks. Each agent gets the same: a script drafts tasks from the issues that carry a
   verdict label, open or closed, and they reach `main` as a person's pull request.
2. **A miss becomes a task.** When a bug is traced to a pull request the reviewers passed, the
   desk lists it as a review task to add. The bug form has an optional "Caused by" field.
3. **A failure becomes a test or a rule.** Each LOG.md entry ends with what now prevents it.
4. **A prompt or model changes only with its eval table,** before and after, in the same pull
   request.
5. **Keep or cut, monthly.** On the first Monday the desk shows each agent's 30 days against its
   keep criteria. The owner decides: keep, change or off. The decision and its numbers go into
   `docs/decisions.md`.
6. **`docs/decisions.md`:** one table of every standing choice: what, why, seen where, and when
   to look again. Stage 0 fills it from this design and the three earlier ones.

## Part 4 — The team

| Work | Scripts | A model | The owner | State |
|---|---|---|---|---|
| Review | workflow checks | two reviewers | merges | live |
| Release | checks, publishing, release watch | drafts notes and README | merges one pull request | ready |
| Following the clients | fetch, routing, memory | the watcher | closes with a verdict | live |
| Managing | the desk, health, numbers | none | sets priorities, answers people | stage 0 |
| Testing | more systems, newest clients, the page in a browser | the tester explores | closes with a verdict | stages 1, 2 |
| Writing tests | proves a test fails for the stated reason | the test writer | labels, merges | stage 3 |
| Fixing bugs | proves red before and green after | the fixer | labels, merges | stage 4 |
| Features, roadmap, taste | none | none | all of it | stays his |

## Part 5 — The stages

| Stage | What | Model | Mostly in | Starts when | Stays when |
|---|---|---|---|---|---|
| 0 | safety fixes, origin labels, the desk, the owner's page, evals, decisions | no | kitden-sdlc | now | n/a |
| 1 | tests where the owner cannot test | no | kitden | now, beside stage 0 | manual release checks fall from 24 to 5 or fewer (call) |
| 2 | the tester | yes | both | stage 1 runs nightly; rule 9 is enforced | its keep criteria |
| 3 | the test writer | yes | both | stage 2 kept after 30 days | most of its pull requests merge unchanged |
| 4 | the fixer | yes | both | stage 3 kept after 30 days | the same |

### Stage 0 — the base

**0a. Small safety fixes** (kitden-sdlc).

- The checker refuses a model step that prints its full output or sets a debug flag (rule 10).
  The setup page warns that GitHub's debug-logging setting makes the model's output public.
- The secret filter also refuses a long random-looking string that is not in the text the model
  was given. This catches a key with its first characters cut off, and does not refuse honest
  findings that quote Kitden's own code.
- One API key per workflow, each with its own money cap: the owner makes a second OpenAI key
  so that review and the evals stop sharing one. The Max token stays shared by review and
  release prep (call): it is one subscription, and release prep runs only by hand. A table in
  agents.md lists every key, where it is stored, who uses it and its cap.
- The release watch knows its issues by their author and title, not by the title alone, so it
  can never rewrite or close a person's issue. The README's warning about bot titles goes.
- `REVIEW_LIVE` in Kitden switches the two reviewers; the checker's switch test knows it.
- Check, and fix if needed: an agent job that fails shows no red mark on a pull request.
- Dependabot keeps the pinned actions in kitden-sdlc up to date; each bump is a pull request
  for the owner.
- RULES.md, MERGE_POLICY.md and the README take the new rules (1.7). MERGE_POLICY.md also says
  that release prep is started by hand and is outside the cap.

**0b. Origin, the desk and the owner's page** (both repositories).

- One label file and the posting scripts give every bot issue `automated` and one origin label;
  the release watch's issues gain `release`.
- Kitden gets issue forms: a bug (version, system, client and its version, steps, what happened,
  optional "Caused by") and an idea (PRINCIPLES.md asks for an issue first). A plain issue stays
  possible. The forms set `bug` or `enhancement`.
- The desk script and its daily workflow (2.1 to 2.4): `desk.json` first, the issue as a view
  of it, with the stage 0 lights; the rest are grey. It reuses and extends `count_reviews.py`: findings whose lines changed afterwards,
  reviews with no findings, days from open to merge.
- The verdict change (1.6): the README, agents.md, the text of the watcher's issues and
  `watch_harvest.py` say and read "`confirmed` stays open".
- Pause on noise (1.5) in the watcher's posting script, written so the tester can reuse it.
- `docs/owner.md` (2.5). Kitden's AI_POLICY.md names the desk.
- The link `../mcp-gateway` in `docs/watcher-plan.md` becomes `../kitden`.

**0c. The host list** (kitden-sdlc).

- Every job that runs a model starts with a step that limits where it can connect. First it
  only records for a week, then it blocks everything outside the list. The checker requires the
  step (rule 9).

**0d. Evals and decisions** (kitden-sdlc).

- The review tasks gain about 10 clean changes and 4 injection cases (in a title, a comment, a
  file name, the code), so false findings can be counted. Writing them is free; running them
  uses Max and waits for the owner's yes with an estimate.
- Keep criteria for the four live agents, proposed from the first four weeks of numbers and set
  by the owner.
- `docs/decisions.md`, and the LOG.md entries point to what prevents each.

### Stage 1 — tests where the owner cannot test (no model)

Ordinary test work in Kitden, planned there.

- **More systems:** Linux on ARM and an Intel Mac beside today's two, and Python 3.13 beside
  3.14. Pull requests keep a fast set; the full set runs nightly.
- **The newest clients:** each night install the newest Claude Code and Codex, run the contract
  tests that need no sign-in, and compare the files the clients really write with the stored
  fixtures. The watcher reads what the notes say; this sees what the files do.
- **The page in a browser:** the main flows on the sample setup (open, preview, Apply, Undo).
- **The 24 manual checks:** each becomes a test, or is marked as needing a signed-in client
  (stage 2), or stays manual with a reason. "Not run yet" goes away.
- A red nightly job opens one `ci-failure` issue through the desk job; it is rewritten in place
  and closes itself when green, like the release watch's issues.

### Stage 2 — the tester

Twice a week (call) a model explores a fresh install of Kitden with the newest clients, on Linux
and macOS: one area per run from a fixed list, and the manual checks that need a signed-in
client.

- Each finding has a script that shows the bug. A job without a model runs that script twice on
  a clean runner. Only a finding that fails the same way both times can become an issue.
- At most 2 issues a week (owner, 2026-11-12); the rest are counted on the desk.
- Its eval: Kitden built at commits with known real bugs (the review tasks have eight), plus
  clean builds for false findings.
- It reads no text from outside, so its job holds a model key and a shell but nothing an
  attacker can address.

### Stages 3 and 4 — one pipeline, two permissions

The test writer and the fixer are the same pipeline. The first may change only `tests/`; the
second also `src/`. That is why tests come first: a wrong test cannot break Kitden.

- **Start:** the owner's label on an issue (1.6). One try per label.
- **The model job:** a checkout, a shell to run tests, the model key, no GitHub token, the host
  list. The shell must not see the model key.
- **Output:** a patch and a short note.
- **The posting job, without a model:** refuses a patch outside its permission or touching 1.4,
  or over a size cap. For a fix it proves the new test fails on `main` and passes with the
  patch, and the old tests stay green. For a test of an open bug it proves the test fails for
  the stated reason and marks it as expected to fail, with the issue number, so checks stay
  green and the later fix must remove the mark. It writes the facts into the pull request and
  opens it as a draft from an `agent/…` branch, as a fourth bot with no other rights.
- **Review:** both reviewers read agent pull requests; a second vendor reads what the first
  wrote. The rules that skip bots and drafts get one exact exception for this bot.
- **The owner:** merges, edits, or closes. An agent does not answer review comments (call);
  the owner can close and label again.

### Later, when the numbers ask (call)

| What | Starts when |
|---|---|
| Sorting people's issues: suggested labels and repeats, shown on the desk; it labels and closes nothing | 10 or more issues a month from other people |
| Review of pull requests from forks, as its own design | rule 9 is enforced, and 4 or more fork pull requests a month |
| The watcher also reads the notes of the tools this repository runs | the watcher's own eval passes its bar |
| A model's weekly note on the desk | the owner says the numbers are not enough |
| An agent acting without the owner's label | the owner decides on 30 days of numbers |

## Budget

The owner's budget is the Max plan and about $7 on the OpenAI key (owner, 2026-11-12). Today
the reviewer and release prep use the Max token, the watcher uses an Anthropic API key, and Luna
and the watch eval use the OpenAI key. Stage 0 and stage 1 run no new model. Each later stage's
design states what it will use, and the owner says yes before its switch is set. Agents that run
on a schedule run outside the owner's working hours, since Max is shared with his own work.

## What only the owner does

- Makes the second OpenAI key and sets the caps (0a).
- Pins the desk issue once (0b).
- Approves the three new rules and the two policy lines (1.7).
- Sets the keep criteria and makes the monthly decision (Part 3).
- For stage 3: creates the fourth bot and names it.

## Left to the builder

File, job and script names not fixed in 1.6; the look of the desk within 2.1; the exact
thresholds of amber and red; the wording of the issue forms and the owner's page; how the label
file is laid out; which step limits hosts, if the check below fails.

## To check when each stage starts

Not verified on 2026-11-13:

- 0a: which debug inputs the two model actions have today.
- 0b: whether an app can read Kitden's branch rules, and whether it can pin an issue.
- 0c: that StepSecurity's Harden-Runner is free for public repositories, works inside a called
  workflow and blocks by host list on the runners we use.
- Budget: what use the Claude action reports for a run on the Max token.
- Stage 1: the runner names for Linux on ARM and an Intel Mac, and that they are free for a
  public repository; which contract tests need no sign-in; what of Cursor can run without its
  window.
- Stages 3 and 4: how to keep the model key out of the agent's shell; that a ruleset can hold a
  bot to `agent/…` branches.

## What differs from the list the owner approved on 2026-11-12

1. The manager is a page made by a script, not an agent. Sorting people's issues waits for
   numbers, because all 17 issues so far are the owner's.
2. The test writer acts on the owner's label, not on every confirmed bug (owner, 2026-11-13).
   One rule for all code: nothing is written without the label.
3. Review of fork pull requests has a place: later, with its own design.
4. `confirmed` no longer closes an issue (owner, 2026-11-13).

## The main choices and why

| Choice | Why | Seen at | Look again when |
|---|---|---|---|
| Scripts measure, models propose, the owner decides | the owner's worst case is a false "all is well" | PyTorch, uv, GitHub Agentic Workflows: the model reads, a job without a model writes | never |
| No agent merges or is a required check | an injected prompt could block or pass every merge | PyTorch forbids it in the workflow file; Copilot's agent cannot approve or merge | a new design, not a setting |
| Steps of trust: comment, issue, test, code | a mistake at each step costs more than at the one before | Vercel: draft pull requests, a person merges; uv: reproduce before fix | 30 days of numbers per step |
| Tests before fixes; fix only with red-then-green proof | a script can check a proof; it cannot check a claim | uv's chain from triage to a failing test to a fix | never |
| Code only on the owner's label | the owner must not lose control of the cycle | Prow: labels are the commands | the owner asks for more |
| A desk made by a script, not a manager agent; its data in one file | a model's summary of its own team is not evidence; a later dashboard reads the same file | gemini-cli keeps its frequent layer as plain scripts | the owner wants the dashboard |
| Evidence and caps on every issue | noise ends such setups | Django switched automated reviews off | false alarms stay under the bar |
| A host list, one key per workflow, no debug output | the model key is the secret an injected prompt steals | Anthropic's own repository; Microsoft's report; "Comment and Control" | short-lived keys become possible |
| Who found each bug, as the main number | almost nobody publishes how often their agents are right | Zed tracks its duplicate bot; Atlassian measures fixed findings | never |
| Stay on our own workflows | the platform had its own advisory, and our one-comment logic would be rewritten | GitHub Agentic Workflows | it offers what we cannot build |
| At most 8 model agents | every agent is review time and something that can break | the factory rolled back after three months | a written case |

## Sources

Read by the research on 2026-11-12, mostly from the projects' own files.

- PyTorch: [hardened-pr-review.yml](https://github.com/pytorch/pytorch/blob/HEAD/.github/workflows/hardened-pr-review.yml),
  [_claude-code.yml](https://github.com/pytorch/test-infra/blob/HEAD/.github/workflows/_claude-code.yml)
- Anthropic: [workflow-hardening.yml](https://github.com/anthropics/claude-code/blob/main/.github/workflows/workflow-hardening.yml),
  [egress-firewall.yaml](https://github.com/anthropics/claude-code/blob/main/.github/egress-firewall.yaml),
  [the action's security page](https://github.com/anthropics/claude-code-action/blob/main/docs/security.md)
- GitHub: [Agentic Workflows architecture](https://github.github.com/gh-aw/introduction/architecture/),
  [its advisory](https://github.com/github/gh-aw/security/advisories/GHSA-8h78-hpm7-29gg),
  [Copilot agent risks and mitigations](https://docs.github.com/en/copilot/concepts/agents/coding-agent/risks-and-mitigations)
- uv: [its workflows](https://github.com/astral-sh/uv/tree/HEAD/.github/workflows);
  gemini-cli: [its bot](https://github.com/google-gemini/gemini-cli/blob/HEAD/tools/gemini-cli-bot/README.md);
  Zed: [duplicate bot tracking](https://github.com/zed-industries/zed/blob/HEAD/script/github-track-duplicate-bot-effectiveness.py)
- Factories: [Vercel](https://vercel.com/blog/building-a-software-factory-for-ai-sdk),
  [addyosmani/factory](https://github.com/addyosmani/factory),
  [the list that records the rollback](https://github.com/varun1505/awesome-software-factories)
- Incidents and guidance: [Microsoft](https://www.microsoft.com/en-us/security/blog/2026/06/05/securing-ci-cd-in-agentic-world-claude-code-github-action-case/),
  ["Comment and Control"](https://venturebeat.com/security/ai-agent-runtime-security-system-card-audit-comment-and-control-2026),
  [Wiz](https://www.wiz.io/it-it/blog/github-actions-security-ai-powered-actions-vulnerabilities),
  [Meta's Rule of Two](https://ai.meta.com/blog/practical-ai-agent-security/),
  [Harden-Runner](https://www.stepsecurity.io/blog/harden-runner-detection-tj-actions-changed-files-action-is-compromised)
- Noise and policy: [Django](https://forum.djangoproject.com/t/disabled-automated-reviews-in-the-django-repo/44531),
  [LLVM](https://www.llvm.org/docs/AIToolPolicy.html)
- Measuring: [Atlassian, arXiv 2601.01129](https://arxiv.org/html/2601.01129v2),
  [arXiv 2607.21997](https://arxiv.org/html/2607.21997v1)
- Kubernetes Prow (labels as commands) was summarised by the research, not re-read here.
