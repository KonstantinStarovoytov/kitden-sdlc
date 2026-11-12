# Release setup (once, by hand)

You do this once, in GitHub's web pages. Nothing here runs by itself. The names are exact:
copy them. Why each piece exists is in [agents.md](agents.md#the-release-flow).

Kitden is `KonstantinStarovoytov/kitden`. The tap is `KonstantinStarovoytov/homebrew-tap`.

## 0. Merge order

1. Merge the kitden-sdlc pull request first.
2. Merge the tap pull request second.
3. Merge Kitden's pull request last, and only after every check in "Already set up for the
   reviewers" passes and sections 1 to 6 below are done.

## Already set up for the reviewers: check they are there

The release workflows need these too. If one is missing, release prep and release watch skip
or fail without much noise.

1. Kitden, Settings, Secrets and variables, Actions, Variables: `AGENTS_ENABLED` is `true`.
2. Same page, Secrets: `CLAUDE_CODE_OAUTH_TOKEN` exists (release prep's agent uses it).
3. Same page: variable `AGENTS_APP_CLIENT_ID` and secret `AGENTS_APP_PRIVATE_KEY` exist
   (Lantern, used by release watch).
4. kitden-sdlc, Settings, Secrets and variables, Actions: the same variable and secret exist
   there too. Lantern's key also lives in kitden-sdlc, for the client watcher.
5. Lantern's app, Permissions: Issues is Read and write, and it is installed on Kitden.
6. PyPI, the `kitden` project, Publishing: the Trusted Publisher names repository `kitden`,
   workflow `release.yml`, environment `pypi`.

## 1. The release GitHub App

Docs: [Registering a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app).

1. Open github.com, your profile picture, Settings, Developer settings, GitHub Apps, New GitHub App.
2. GitHub App name: `Kitden Beacon` (GitHub makes the slug `kitden-beacon`). Description:
   "Releases Kitden: tags the version and updates every store."
3. Homepage URL: the Kitden repository's address.
4. Webhook: untick Active.
5. Repository permissions, Contents: Read and write.
6. Repository permissions, Pull requests: Read and write.
7. Repository permissions, Workflows: Read and write. GitHub refuses a tag or a move of the
   `release` branch made by an app when the commits since the last release change
   `.github/workflows`, unless the app may write workflows.
8. Leave every other permission at No access.
9. Where can this app be installed: Only on this account.
10. Press Create GitHub App.
11. Copy the Client ID (it starts with `Iv`). You need it in section 3.
12. Scroll to Private keys and press Generate a private key. A `.pem` file downloads. Keep it
    until section 2 is done, then delete it. This key is stored only in Kitden's `release`
    environment, never in the tap: it can tag Kitden, and a tag publishes to PyPI.
13. Display information, Upload a logo: [beacon.png](images/apps/beacon.png); background
    color `#182143`. Its own icon and color keep it apart from Lantern in every timeline.
14. Open Install App, then Install on your account.
15. Choose Only select repositories, then pick `kitden` and `homebrew-tap`. Nothing else.
    (Kitden's publish job opens the formula pull request in the tap with this app.)
16. The bot login is the app's slug plus `[bot]`: `kitden-beacon[bot]`. (If GitHub changed the
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
2. Bypass list, Add bypass: the `kitden-beacon` app, Always allow.
3. Bypass list, Add bypass: Repository admin (that is you), Always allow. (Only these two
   may create a `v*` tag.)
4. Target tags, Add target, Include by pattern: `v*`.
5. Tick Restrict creations. Tick Restrict updates. Tick Restrict deletions.
6. Create. GitHub lets a bypass actor also move or delete a tag. The workflows never do;
   you should not either.

Then the branch rule. New ruleset, New branch ruleset:

1. Ruleset name: `release branch`. Enforcement status: Active.
2. Bypass list, Add bypass: the `kitden-beacon` app, Always allow.
3. Target branches, Add target, Include by pattern: `release`.
4. Tick Restrict updates (only the bypass list may push). Tick Restrict deletions.
5. Tick Block force pushes.
6. Create.

Last, Kitden's own `main`. The release app can write Contents on Kitden, so `main` must stop it:

1. Kitden, Settings, Rules, Rulesets, open the ruleset for `main`.
2. Check its Enforcement status is Active and its target branches include `main`.
3. Check that it requires a pull request before merging.
4. Check the bypass list does not contain `kitden-beacon`, Lantern or GitHub Actions.

## 5. The tap: its own app

The tap's daily autobump runs `brew bump`, which is code from outside the tap, so the tap gets
its own app with a key that can only open pull requests in the tap. The release app's key is
never stored in the tap.

First the tap app. github.com, your profile picture, Settings, Developer settings, GitHub Apps,
New GitHub App:

1. GitHub App name: `Kitden Kettle` (slug `kitden-kettle`). Description: "Bumps the kitden
   formula in the Homebrew tap."
2. Homepage URL: the tap repository's address.
3. Webhook: untick Active.
4. Repository permissions, Contents: Read and write.
5. Repository permissions, Pull requests: Read and write.
6. Leave every other permission at No access.
7. Where can this app be installed: Only on this account.
8. Press Create GitHub App.
9. Copy the Client ID (it starts with `Iv`).
10. Scroll to Private keys and press Generate a private key. A second `.pem` file downloads.
11. Display information, Upload a logo: [kettle.png](images/apps/kettle.png); background
    color `#2B1B23`.
12. Open Install App, then Install on your account, Only select repositories, then pick
    `homebrew-tap`. Nothing else.
13. Its bot login is `kitden-kettle[bot]` (the slug plus `[bot]`, as in section 1).

Then go to `homebrew-tap`, Settings, Secrets and variables, Actions.

1. Variables tab, New repository variable: `TAP_APP_CLIENT_ID`, the tap app's Client ID.
2. Variables tab, New repository variable: `TAP_APP_BOT`, value `kitden-kettle[bot]`.
3. Variables tab, New repository variable: `RELEASE_APP_BOT`, value `kitden-beacon[bot]`.
   (Both exact: the tap only auto-pulls bump pull requests opened by these two logins or by
   `github-actions[bot]`.)
4. Secrets tab, New repository secret: `TAP_APP_PRIVATE_KEY`, the whole tap app `.pem` file.
5. Delete the tap app's `.pem` file from your computer.
6. Check the tap has no `RELEASE_APP_CLIENT_ID` variable and no `RELEASE_APP_PRIVATE_KEY`
   secret. If an earlier setup left them there, delete them.

## 6. kitden-sdlc: keep `main` locked

The release key trusts code from kitden-sdlc `main`, so `main` there must stay protected.

1. kitden-sdlc, Settings, Rules, Rulesets, open the ruleset for `main`.
2. Check its Enforcement status is Active and its target branches include `main`.
3. Check that it requires a pull request and the checks.
4. Check the bypass list is empty: no Lantern, no GitHub Actions, no apps.

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
2. Wait. A pull request named `Kitden X.Y.Z` appears, opened by `kitden-beacon[bot]`.
3. Read it. Merge it with a **merge commit** (not squash, not rebase).
4. Kitden, Actions, Checks and release: the run on `main` tags the version (job `autotag`).
   A second Checks and release run starts on the tag `vX.Y.Z`. kitden-sdlc's publish workflow
   runs inside that tag run, as the jobs `stores / registry`, `stores / release-branch`,
   `stores / homebrew` and `stores / summary`. There is no separate Publish run.
5. Open the tag's run, then the job `stores / summary`. Its table has nine rows: PyPI, GitHub
   release, MCP Registry, Homebrew formula, release branch, Marketplace entry, GitHub
   description, Claude directory and Glama. The status of each is `ok`, `behind` or
   `check by hand`. Expect:
   - Homebrew formula: `behind` until the bottles land, usually the next day. When the
     dependencies changed, the tap's daily autobump opens the formula pull request the next
     day, and the bottles follow it.
   - GitHub description: `behind` until step 1 of section 7 is done.
   - Claude directory and Glama: always `check by hand`.
   - Every other row: `ok`. The job turns red when PyPI, GitHub release, MCP Registry or
     release branch is not.
6. Kitden, Issues: the release-watch issue "Release vX.Y.Z is not everywhere" appears only
   while a store is behind. No such issue after a day means every store is in step.

If it fails, look at the first red job in the run. The usual sign is a red "Sign in as the
release app" or "Sign in as the Lantern app" step, with an error about the private key or the
client id: a secret or variable from sections 2 or 3 (the release app) or from "Already set
up for the reviewers" (Lantern) is missing or in the wrong place. If the tap's `brew bump`
pull requests never start their tests, check section 5. Copy the red step's message and tell
the builder.
