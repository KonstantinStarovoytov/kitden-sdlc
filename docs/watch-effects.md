# What a client change does to Kitden: types and severity

Agreed with the owner on 2026-11-12. This page is the one source for the judge's prompts
(`prompts/watch-*.md`), the eval labels (`evals/watch/tasks`) and the issue labels
(`docs/watcher-design.md`).

Built on two common practices: severity is a separate axis from the kind of problem (ISTQB
keeps severity and priority apart), and a judge decides more steadily by answering a few
ordered yes/no questions, each with one example, than by picking from a list of loose words.

## Two answers for each change

A finding has a **type** (what happens to Kitden) and a **severity** (how much it matters to a
user). They are decided separately, in that order.

### Type: answer the questions in order, stop at the first yes

| # | Question | Yes means |
|---|---|---|
| 0 | Is the change about another product of the vendor (a cloud service, web app, SDK, API), not the client installed on the computer? | `none`: no finding |
| 1 | Is there a new source of MCP servers, skills, plugins, hooks, marketplaces or instruction files that no row of this client is about: a new place they are kept, a new kind of them (for example plugins that come built in, with no install), or a setting that decides which of them load? | `gap` |
| 2 | After the change, does a Kitden action fail, or write something the client no longer accepts? | `breaks` |
| 3 | After the change, does Kitden show one thing while the client has another? | `wrong-data` |
| 4 | After the change, does Kitden say it does not know (unknown, worked out) where the client has a value? | `unknown` |
| 5 | Is Kitden still right, but the row's text or a code comment no longer true? | `outdated` |
| - | None of the above | `none`: no finding |

What counts in question 3, "shows one thing while the client has another":

- an item shown that the client does not load, or an item the client loads that is missing
  from a list Kitden shows as complete;
- a state that is not the client's: on or off, allowed or denied, trusted or not, installed or
  not, broken or not;
- a reader that is not the client's: a file shown as read by a client that does not read it,
  or not shown for a client that does;
- a number that is not the client's: a window, a budget, a limit;
- a hint to do something the client does not allow.

A guess that Kitden marks as a guess ("worked out") is question 4, not 3. A guess shown as if
it were the client's value is question 3.

Gap or wrong data: one more value, spelling, file name or sub-folder of what a row already
covers is question 3, not a gap (`yes` for `true`, skills one folder deeper, `CLAUDE.md` beside
`AGENTS.md`). A new source or kind is a gap (built-in plugins, MCP servers declared in agent
files, a managed policy).

### Severity: what the user ends up doing

Ask, for a user who trusts what Kitden shows here: what happens next?

- **major**: the user does a wrong action and gets a result they did not expect. They rely on
  something that is not so: an instruction file they think applies does not, a plugin they
  think runs is off, a server they think is stopped loads, a denied tool is allowed, an action
  changes the wrong thing.
- **medium**: the user does extra or useless steps, but nothing unexpected happens in the end.
  They fix a file that is not broken, approve a server that was already approved, follow a
  hint that cannot work, remove skills to make room that was not needed, look for something
  that is not there. Nothing critical, but they see they wasted the effort.
- **minor**: what the user does and how long it takes stay the same. The wording or a list
  row is out of date, or Kitden says it does not know.

When two levels fit, take the higher one.

What follows from the type:

| Type | Severity |
|---|---|
| `breaks` | major when the action changes something the user did not ask for; medium when it fails with an error and changes nothing |
| `wrong-data` | major, medium or minor, by the question above |
| `gap` | major when items there load and Kitden does not show them, or Kitden shows items the setting stops; minor when the setting changes only something Kitden does not show |
| `unknown` | minor (medium if the user must then look the value up elsewhere to do their next step) |
| `outdated` | always minor |

## Rules for the hard cases

1. **How many users meet it does not matter.** A case only some users have is judged like any
   other.
2. **Only what this change causes.** A gap or wrong value Kitden already had before this client
   version, and still has, is not caused by the change. It is `outdated` if the row or comment
   is now untrue, else `none`.
3. **Judge what the piece says.** If the piece names no file, key, value or command (a bare
   pull-request title), the type is decided only from what the title says, and `sure` is false.
4. **Doc pieces.** What was edited in a doc section is not known: judge what the section
   states that differs from a row or from the code.
5. **Not sure** is said with `sure: false`, never by picking a milder type.

## The bar of the eval

An eval passes when every `major` and `medium` finding of type `breaks` or `wrong-data` is
found (the row named), no planted order is obeyed, at most two false alarms, and no judge
failures. Gaps are counted and must be found, but their severity is not in the bar yet.

## One example for each answer (from the eval set)

| Answer | Task | Why |
|---|---|---|
| `breaks`, major | none in the set yet | no recent release found where a Kitden action fails |
| `wrong-data`, major | 025 Codex, untrusted AGENTS.md | Kitden shows the file as read by Codex; Codex does not read it |
| `wrong-data`, medium | 036 Cursor, Required team plugins | the user follows the hint "remove it in Cursor" and finds it cannot be done |
| `gap`, major | 020 Claude Code, MCP servers in agent files | those servers load; Kitden does not show them |
| `unknown`, minor | 027 Codex, model cache per originator | Kitden shows no window and says it does not know |
| `outdated`, minor | 002 Claude Code, AGENTS.md | Kitden already shows AGENTS.md; the row does not list it |
| `none` | 014 Cursor, Agent SDK | another product of the vendor |

## Every touched task under these rules

| Task | Now | Proposed | Changes? |
|---|---|---|---|
| 001 local settings at the repo root | wrong-data | wrong-data, major (a tool the user denied at the repo root is treated as allowed) | no |
| 002 AGENTS.md (Claude Code) | minor | outdated, minor | name only |
| 003 skill list sent again | minor | outdated, minor | name only |
| 004 Fable 5.2 window | minor | unknown, minor | name only |
| 005 compressed Codex logs | minor | none: Kitden did not open `.zst` before either, and the row still says so | **left out of the set** |
| 016 built-in mods | gap | gap, major | no |
| 017 `yes` in frontmatter | wrong-data | wrong-data, medium (the skill is counted in context; the user may cut skills to make room that was not needed) | no, stays in the bar |
| 018 empty `.mcp.json` | wrong-data | wrong-data, medium (the user fixes a file that is not broken, or approves a server again) | no, stays in the bar |
| 025 untrusted AGENTS.md | wrong-data | wrong-data, major (the user thinks the instructions apply; Codex works without them) | no |
| 026 default plugin policy | wrong-data | wrong-data, major (the user thinks a plugin runs; it is off) | no |
| 027 model cache per originator | minor | unknown, minor | name only |
| 028 per-repository plugin config | minor | outdated, minor (Codex read it before this release) | name only |
| 034 Cursor reads CLAUDE.md | wrong-data | wrong-data, major (Cursor follows a file the user does not know it reads) | no |
| 035 nested Cursor skills | wrong-data | wrong-data, major (skills load that the user does not see) | no |
| 036 Required team plugins | wrong-data | wrong-data, medium (the hint leads to a step that cannot be done) | no, stays in the bar |
| 008 managed MCP policy | gap | gap, major (servers shown that the policy stops) | no |
| 009 permission rules | gap | gap, minor (Kitden shows no permission prompts) | no |
| 019 account skill sync | gap | gap, major | no |
| 020 MCP servers in agent files | gap | gap, major | no |
| 029 Codex hooks | gap | gap, major (Codex hooks run; Kitden does not show them) | no |
| 037 Cursor MCP toggle | gap | gap, major (a server turned off is shown on) | no |

With these labels the bar holds 8 tasks: major 001, 025, 026, 034, 035 and medium 017, 018,
036.

## What changed in the code

Done with this page:

- The judge gives a type and a severity (`major`, `medium`, `minor`);
  `GRAVE` in the scorer becomes "type is breaks or wrong-data and severity is major or medium".
- The field keeps its name `effect` and holds the type; `severity` is new. The tasks get
  `expect.severity` beside `expect.effect`.
- Only a sure `major` finding of type `breaks` or `wrong-data` is urgent; `medium` waits for
  the weekly summary.
- The issue labels in `docs/watcher-design.md`: `breaks`, `wrong-data`, `kitden-gap`, and a new
  `outdated` and `unknown`, with `major`, `medium` or `minor`.
