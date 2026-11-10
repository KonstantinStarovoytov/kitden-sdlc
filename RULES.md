# Rules for every agent workflow

Every workflow that runs an AI agent must follow these eight rules.

1. No job holds untrusted text, a secret and write permission together. The model reads; a
   step without a model posts, or the action's own comment tool is allowed by its exact name.
   The posting job holds the review app's key but runs no model: the reviewers' text is only
   data there.
2. `pull_request` only, never `pull_request_target`. A job skips when the head is a fork, when
   the actor is a bot, and when the switch is off.
3. `permissions: {}` at the top; each job lists the least it needs.
4. Every action is pinned to a full SHA; a plugin marketplace is pinned to a tag. The caller
   may use `kitden-sdlc`'s own workflows at `main`: that branch is protected, so nothing gets
   there without a pull request.
5. Every agent job has `timeout-minutes`, a turn limit and `concurrency` with one run per pull
   request, where a newer run cancels the older. Codex (Luna) has no turn limit, only the
   15-minute timeout.
6. Tools are allowed by exact name. Reviewers get no Bash, no web tools and no MCP server. They
   read only the checkout (not `.git`, the home folder or `/proc`) and write only the findings
   folder. Their text is refused if it looks like a secret. Codex can run shell commands, but only
   inside a read-only sandbox with no network, and the files it can read are not limited to
   the checkout.
7. A secret reaches a job as a named input and is never printed. The Claude token and the
   OpenAI key are never in the same job.
8. An agent's comment starts with one line saying it is automated and which model wrote it.
