# Release setup (once, by hand)

You do this once, in GitHub's web pages. Nothing here runs by itself. The names are exact:
copy them. Why each piece exists is in [agents.md](agents.md#the-release-flow).

Kitden is `KonstantinStarovoytov/kitden`. The tap is `KonstantinStarovoytov/homebrew-tap`.

## 0. Merge order

1. Merge the kitden-sdlc pull request first.
2. Merge the tap pull request second.
3. Merge Kitden's pull request last, and only after sections 1 to 6 below are done.

## Already set up for the reviewers: check they are there

The release workflows need these too. If one is missing, release prep and release watch skip
or fail without much noise.

1. Kitden, Settings, Secrets and variables, Actions, Variables: `AGENTS_ENABLED` is `true`.
2. Same page, Secrets: `CLAUDE_CODE_OAUTH_TOKEN` exists (release prep's agent uses it).
3. Same page: variable `AGENTS_APP_CLIENT_ID` and secret `AGENTS_APP_PRIVATE_KEY` exist
   (Lantern, used by release watch).
4. Lantern's app, Permissions: Issues is Read and write, and it is installed on Kitden.
5. PyPI, the `kitden` project, Publishing: the Trusted Publisher names repository `kitden`,
   workflow `release.yml`, environment `pypi`.

## 1. The release GitHub App

Docs: [Registering a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app).

1. Open github.com, your profile picture, Settings, Developer settings, GitHub Apps, New GitHub App.
2. GitHub App name: `kitden-release`.
3. Homepage URL: the Kitden repository's address.
4. Webhook: untick Active.
5. Repository permissions, Contents: Read and write.
6. Repository permissions, Pull requests: Read and write.
7. Leave every other permission at No access.
8. Where can this app be installed: Only on this account.
9. Press Create GitHub App.
10. Copy the Client ID (it starts with `Iv`). You need it in sections 3 and 5.
11. Scroll to Private keys and press Generate a private key. A `.pem` file downloads. Keep it
    until sections 2 and 5 are done, then delete it.
12. Open Install App, then Install on your account.
13. Choose Only select repositories, then pick `kitden` and `homebrew-tap`. Nothing else.
14. The bot login is the app's slug plus `[bot]`: `kitden-release[bot]`. (If GitHub changed the
    slug, use the slug in the app's public page address.)

## 2. Kitden: environments

Docs: [Managing environments](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-deployments/managing-environments-for-deployment).
Go to Kitden, Settings, Environments.

1. New environment, name `release`.
2. Deployment branches and tags, Selected branches and tags.
3. Add deployment branch or tag rule: Branch, `main`.
4. Add another: Tag, `v*`.
5. Environment secrets, Add secret: name `RELEASE_APP_PRIVATE_KEY`, value is the whole `.pem` file.
6. New environment, name `pypi` (open it if it already exists).
7. Deployment branches and tags, Selected branches and tags.
8. Add deployment branch or tag rule: Tag, `v*`. Add no branch rule.

## 3. Kitden: the client id

1. Kitden, Settings, Secrets and variables, Actions, Variables tab.
2. New repository variable: name `RELEASE_APP_CLIENT_ID`, value the Client ID from section 1.

## 4. Kitden: rules for tags and the `release` branch

Docs: [Creating rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository).

First create the branch (the plugin marketplaces read the plugin from it, and Kitden's pull
request moves it from there on):

1. In a clone of Kitden, run `git push origin 'v0.8.0^{commit}:refs/heads/release'`.
   (Or: Kitden, branch menu, type `release`, base it on the `v0.8.0` tag, Create branch.)

Then the tag rule. Kitden, Settings, Rules, Rulesets, New ruleset, New tag ruleset:

1. Ruleset name: `release tags`. Enforcement status: Active.
2. Bypass list, Add bypass: the `kitden-release` app, Always allow.
3. Bypass list, Add bypass: Repository admin (that is you), Always allow. (Only these two
   may create a `v*` tag.)
4. Target tags, Add target, Include by pattern: `v*`.
5. Tick Restrict creations. Tick Restrict updates. Tick Restrict deletions.
6. Create. GitHub lets a bypass actor also move or delete a tag. The workflows never do;
   you should not either.

Then the branch rule. New ruleset, New branch ruleset:

1. Ruleset name: `release branch`. Enforcement status: Active.
2. Bypass list, Add bypass: the `kitden-release` app, Always allow.
3. Target branches, Add target, Include by pattern: `release`.
4. Tick Restrict updates (only the bypass list may push). Tick Restrict deletions.
5. Tick Block force pushes.
6. Create.

Last, Kitden's own `main`. The release app can write Contents on Kitden, so `main` must stop it:

1. Kitden, Settings, Rules, Rulesets (or Branches), open the rule for `main`.
2. Check that it requires a pull request before merging.
3. Check the bypass list does not contain `kitden-release`, Lantern or GitHub Actions.

## 5. The tap

Go to `homebrew-tap`, Settings, Secrets and variables, Actions.

1. Variables tab, New repository variable: `RELEASE_APP_CLIENT_ID`, the same Client ID.
2. Variables tab, New repository variable: `RELEASE_APP_BOT`, value `kitden-release[bot]`
   (exact; the tap only auto-merges pull requests from this login).
3. Secrets tab, New repository secret: `RELEASE_APP_PRIVATE_KEY`, the whole `.pem` file.
4. Delete the `.pem` file from your computer.

## 6. kitden-sdlc: keep `main` locked

The release key trusts code from kitden-sdlc `main`, so `main` there must stay protected.

1. kitden-sdlc, Settings, Rules, Rulesets (or Branches), open the rule for `main`.
2. Check that it requires a pull request and the checks.
3. Check the bypass list is empty: no Lantern, no GitHub Actions, no apps.

## 7. After Kitden's pull request is merged

1. Kitden, the About box (the gear), Description: paste the `short` text from `listing.toml`:
   `See and safely change what Claude Code, Codex and Cursor load: MCP servers, plugins, skills, hooks`
   (Copy it from the file if it has changed since this was written.)
2. Open <https://claude.ai/directory/manage>, then the plugin, then the Review tab. Copy the
   policy warnings into kitden-sdlc `docs/platform-rules.md`, where it says "owner fills in
   from the Review tab".
3. Read the Claude directory section of `docs/platform-rules.md` next to the live pages it
   cites. Fix any line that differs.

## 8. After the first release made by the new flow

Do this only when the first release has gone through the flow, and Anthropic has decided the
publish request that is now waiting. Saving this cancels a waiting request.

1. Open <https://claude.ai/directory/manage>, then the plugin.
2. Settings, Source, Tracked branch or tag: `release`.
3. Save.

## 9. Check that it works

1. Kitden, Actions, Release prep, Run workflow on `main`.
2. Wait. A pull request named `Kitden X.Y.Z` appears, opened by `kitden-release[bot]`.
3. Read it. Merge it with a **merge commit** (not squash, not rebase).
4. Kitden, Actions: the release workflow tags the version, then Publish runs.
5. Open the Publish run: its summary table has one row per place (PyPI, GitHub release,
   `release` branch, MCP Registry, Homebrew). Each should say done.
6. Kitden, Issues: the release-watch issue "Release vX.Y.Z is not everywhere" appears only
   while a store is behind. No such issue after a day means every store is in step.

If it fails, look at the first red job in the run. The usual sign is the "Sign in as the
release app" step saying the key or client id is empty: a secret or variable from sections
2, 3 or 5 is missing or in the wrong place. Copy the red step's message and tell the builder.
