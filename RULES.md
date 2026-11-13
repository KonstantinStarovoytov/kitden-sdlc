# Rules for every agent workflow

Every workflow that runs an AI agent must follow these eleven rules.

1. No job holds untrusted text, a secret and write permission together. The model reads; a
   step without a model posts, or the action's own comment tool is allowed by its exact name.
   The posting job holds the review app's key but runs no model: the reviewers' text is only
   data there. A job in the `release` environment never runs a model and never runs on
   `pull_request_target` or `issue_comment`.
2. `pull_request` only, never `pull_request_target`. A job skips when the head is a fork, when
   the actor is a bot, and when the switch is off; a review caller also carries `REVIEW_LIVE`.
   A scheduled agent runs on `schedule` and `workflow_dispatch` only, and every job of it
   carries the switch.
3. `permissions: {}` at the top; each job lists the least it needs.
4. Every action is pinned to a full SHA; a plugin marketplace is pinned to a tag. The caller
   may use `kitden-sdlc`'s own workflows at `main`: that branch is protected, so nothing gets
   there without a pull request.
5. Every agent job has `timeout-minutes`, a turn limit and `concurrency` with one run per pull
   request, where a newer run cancels the older. Codex (Luna) has no turn limit, only its
   step's 12-minute timeout. An agent that is a script, not an action, gets its turn limit as
   `MAX_MODEL_CALLS`, and one run at a time.
6. Tools are allowed by exact name. Reviewers get no Bash, no web tools and no MCP server. They
   read only the checkout (not `.git`, the home folder or `/proc`) and write only the findings
   folder. Their text is refused if it looks like a secret, or holds a long random string that
   is not in what the model was given. Release prep's files and its pull request body go
   through the same two checks before anything is committed or posted, a draft too. Before
   those checks run, the model's output is kept as a run artifact for a day, and anyone signed
   in to GitHub can download a public repository's artifacts. Codex can run shell commands,
   but only inside a read-only sandbox with no network, and the files it can read are not
   limited to the checkout.
7. A secret reaches a job as a named input and is never printed. The Claude token and the
   OpenAI key are never in the same job.
8. An agent's comment starts with one line saying it is automated and which model wrote it.
9. A job that runs a model reaches only the hosts on its written list. Its first step is
   Harden-Runner. This is not in force yet: for the first week the step only records the
   hosts; the list is written after that, and then it is a limit.
10. A model step never prints its full output or debug logs: in a public repository those logs
    are public. The checker refuses `show_full_output`, `display_report`, debug flags and
    debug variables.
11. No agent is in anyone's way. No agent job is a required check. No agent approves or
    requests changes. A failed reviewer leaves no red mark on a pull request: if one fails
    the comment names it, if both fail the comment says so. A refusal to post secret-like
    text does turn the job red, and so does a failure of the workflow's own steps (checkout,
    the prepare script, the cap, GitHub's API).
