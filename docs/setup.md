# Copy this to your project

The files in [examples/](../examples/) are Kitden's own workflow callers; the `uses` pins are
bumped at each release. Put them in your `.github/workflows/`:

- review and the workflow check: [agents-review.yml](../examples/agents-review.yml),
  [agents-check.yml](../examples/agents-check.yml);
- the release flow: [release.yml](../examples/release.yml),
  [release-watch.yml](../examples/release-watch.yml),
  [release-prep.yml](../examples/release-prep.yml).

Before you start:

- `kitden-sdlc`, or your copy of it, must be public: another repository's `uses` cannot
  reach a private one.
- The review skill, the Luna prompt and `count_reviews.py` (`REPO`, `MAINTAINER`) are about
  Kitden, and so are the release skills, `release_check.py` and
  [platform-rules.md](platform-rules.md). Rewrite them for your project.
- The model and the `uses` pins in the caller files are Kitden's choices. Change them to yours.

## Review and the client watcher, once

1. Create the repository `kitden-sdlc` (or your copy) on GitHub.
2. Run `claude setup-token` and save the result as the secret `CLAUDE_CODE_OAUTH_TOKEN`.
3. Make an OpenAI project key with a monthly budget; save it as `OPENAI_API_KEY`. For the
   client watcher, make an Anthropic API key with a monthly limit; save it as `ANTHROPIC_API_KEY`.
4. Set the variable `AGENTS_ENABLED` to `true`; it switches review, the watcher, release prep
   and release watch. Set `REVIEW_LIVE` to `true` to let the two reviewers run. For the
   client watcher, set `WATCH_LIVE` to `true` only after the eval has passed.
5. Create a GitHub App, install it on the repository, and save its client id as the variable
   `AGENTS_APP_CLIENT_ID` and its private key as the secret `AGENTS_APP_PRIVATE_KEY`. Kitden's
   app is called Lantern. For the review it is optional: it posts the comment under the bot's
   own name (write access to pull requests), and without it the comment comes from
   `github-actions`. Release watch and the client watcher need it, with write access to
   issues. With your own app, put its bot name into `BOTS` in `post_findings.py`.

Never use GitHub's "Enable debug logging" on a re-run of an agent workflow, and never set the
variable `ACTIONS_STEP_DEBUG`: they make a model's output public.

## The release flow, once

The release flow needs two more GitHub Apps (one for the release, one for the Homebrew tap),
the environments `release` and `pypi`, and a few rules. Every step, with exact names:
[release-setup.md](release-setup.md).

Never reuse the review app for releases, and never store the release app's key in the tap:
the review app's key lives in kitden-sdlc, and the tap's daily `brew bump` runs code from
outside it.
