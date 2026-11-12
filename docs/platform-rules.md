# Platform rules

The rules that each store puts on Kitden's listing: limits, required fields and what must be
disclosed. `scripts/release_check.py` enforces the limits in the first part of each store
below. The release-prep agent checks a release against the rest and reports what breaks
them. Each rule has its source and the date we checked it.

## Claude plugin directory (`plugins/kitden`)

The directory lists the folder that holds `.claude-plugin/plugin.json`. Its listing (name,
short description) comes from `plugin.json` and the README of the version that is live, so a
change to either shows only after a new version is published.
Source: <https://claude.com/docs/plugins/submit>. Checked: 2026-11-12.

- **Name.** Lowercase letters, digits and hyphens, at most 64 characters, starting and ending
  with a letter or digit. Non-ASCII blocks the submission. The name must not be a reserved
  word alone (`claude`, `anthropic`, `official`, `plugin`, `mcp`, `test`), must not look like
  Anthropic's own (`claude-…`, `anthropic-…`) and must not be taken by another organisation.
- **`displayName` and `author.name`.** One writing system, no look-alike letters and no
  invisible characters (blocks). A name that can be mistaken for a known brand or another
  publisher is held for a reviewer.
- **`description`, `author` and `version`.** Set them (a warning otherwise). Raise `version`
  with every release.
- **README.** At least 40 words in the plugin folder, not counting code blocks (blocks). The
  directory shows it as the listing's description.
- **License.** A `LICENSE` file in the plugin folder, or `license` in `plugin.json` (blocks).
- **Listing fields only in `plugin.json`.** `icon` (a path to an image inside the plugin),
  `documentationUrl`, `supportUrl`, `privacyPolicyUrl` and `termsOfServiceUrl` (each
  `https://`). In a marketplace entry they are unknown fields.
- **Files.** No `.DS_Store`, `Thumbs.db`, `desktop.ini` or `__MACOSX` (blocks). Regular files,
  not symbolic links, for anything the plugin loads. Each file that is not an image or font
  under 256 KiB, at most 512 files, and only text, SVG, PNG, JPEG, GIF, WebP and fonts (held
  for a reviewer otherwise). The repository under 50 MiB as GitHub archives it.
- **What it runs.** A package launcher in a hook or server (`uvx`, `npx`, `uv run`) must pin an
  exact version, such as `uvx kitden==X.Y.Z` (blocks), and is still held for a reviewer. A
  script that a `SKILL.md` only tells Claude to run is not part of this check. No real
  credentials in any file, and no reading a token such as `$GITHUB_TOKEN` from the user's
  environment to send it on.
- **Disclosure.** The security scan looks for behaviour the plugin does not disclose, such as
  sending data to an undisclosed destination; a first version that fails is rejected. The
  plugin README must describe everything the plugin runs, sends or fetches.
- **Data handling.** The portal asks whether the plugin reads or stores personal data, sends
  data to services other than its declared connectors, how long it keeps data, and whether it
  is meant for people under 18. The answers live in the portal, not in the repository.
- **Tracked branch or tag.** Changing it cancels a publish request that is still waiting, and
  it cannot change while the plugin is with a reviewer.

Sources: <https://claude.com/docs/plugins/pre-submission-checklist>,
<https://claude.com/docs/plugins/submit> and
<https://code.claude.com/docs/en/plugins-reference> ("name", "Directory listing fields").
Checked: 2026-11-12.

Directory policy ([Anthropic Software Directory Policy](https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy),
checked 2026-11-12):

- A plugin that collects user data or connects to a remote service needs a clear privacy
  policy link (§3A). Kitden's is `privacyPolicyUrl`, which points at `PRIVACY.md`.
- Descriptions must match what the plugin really does and promise nothing it does not
  deliver (§2B).
- Collect only the data the function needs from the user's context (§1E).
- No hidden, obfuscated or encoded instructions (§2G), and no instructions pulled from
  outside sources at run time (§2F).
- MCP tools give every annotation that applies, above all `readOnlyHint`, `destructiveHint`
  and `title` (§5E); tool names are at most 64 characters (§5C).
- Tell Anthropic about material changes; they may trigger a new review (§3H).

Directory policy warnings: owner fills in from the Review tab.

## Official MCP Registry (`server.json`)

- `description`: 1 to 100 characters.
- Source: the schema named in Kitden's `server.json` `$schema`,
  <https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json>
  (`ServerDetail.description`, `maxLength: 100`).
- Checked: 2026-11-12.

Also from that schema (checked 2026-11-12):

- `name`, `description` and `version` are required.
- `name` is 3 to 200 characters, matches `^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$` and has exactly one
  slash. Kitden's is `io.github.KonstantinStarovoytov/kitden`.
- `title`, when set, is 1 to 100 characters. `version` is at most 255 characters.
- `version` and each package `version` must be one exact version. Ranges (`^1.2.3`, `>=1.2.3`,
  `1.x`) are rejected.

From the registry's docs:

- **The version is final.** Each publication needs a new version string, and once published
  the version and the rest of its metadata cannot change.
  Source: <https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/versioning.mdx>.
  Checked: 2026-11-12.
- **PyPI ownership.** The registry checks that the package README on PyPI holds
  `mcp-name: io.github.KonstantinStarovoytov/kitden`. It may sit in an HTML comment, and must
  be followed by a space, a line end, a tag or `-->`, never by a full stop. Kitden keeps
  `<!-- mcp-name: io.github.KonstantinStarovoytov/kitden -->` in `README.md`.
  Source: <https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx>
  ("PyPI Packages"). Checked: 2026-11-12.
- **Moderation.** The registry removes spam, such as a description stuffed with marketing
  copy, and servers that do not work.
  Source: <https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/moderation-policy.mdx>.
  Checked: 2026-11-12.

## Glama (<https://glama.ai/mcp/servers/KonstantinStarovoytov/kitden>)

- **The description comes from the GitHub README**, and the page shows no version
  (observed on Kitden's page, 2026-11-12). So the top of `README.md` is Glama's text, and
  there is no version to check: the release summary lists Glama as "check by hand".
- **`glama.json`** sits at the repository root with `$schema` and `maintainers`, the one
  required field: a list of unique GitHub usernames. After a change to it, the owner runs
  Glama's "Claim ownership" flow again so Glama reads it. A claimed owner can change the name
  and description on Glama.
  Sources: <https://glama.ai/mcp/schemas/server.json> and
  <https://glama.ai/blog/2025-07-08-what-is-glamajson>. Checked: 2026-11-12.
- **Score.** Glama scores each tool from 1 to 5 on purpose clarity, usage guidelines,
  behavioural transparency, parameter semantics, conciseness and contextual completeness, and
  reads the tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`). Scores are worked out again on every new commit. Kitden had A, 4.6 of 5,
  across 4 tools (scored 2026-11-09).
- **Safety.** Glama runs open-source servers in a sandbox. A risky finding shows on the
  listing; a malicious one goes to review and may remove the listing. A server whose build
  fails stays listed but is hidden from search.
  Source: <https://glama.ai/mcp/methodology>. Checked: 2026-11-12.

## PyPI (`project.description` in `pyproject.toml`)

- The summary is one line. It must not hold a line break. The spec sets no character limit.
- Source: the Summary field in the core metadata specification,
  <https://packaging.python.org/en/latest/specifications/core-metadata/#summary>
  ("A one-line summary of what the distribution does").
- Checked: 2026-11-12.

Also from the core metadata specification
(<https://packaging.python.org/en/latest/specifications/core-metadata/>, checked 2026-11-12):

- `Name` and `Version` are required; `Version` follows the version specifiers specification.
- The README is the long description, with `Description-Content-Type: text/markdown` (GitHub
  Flavored Markdown unless set otherwise). It is also the MCP Registry's ownership proof (see
  above).
- A `Project-URL` label is at most 32 characters.
- `License-Expression` is an SPDX expression; `License ::` classifiers are deprecated.

From PyPI itself:

- **A file name is never reused.** A file cannot be uploaded again under the same name, even
  after it is deleted, so a broken release needs a new version.
  Source: <https://pypi.org/help/#file-name-reuse> (now redirects to <https://docs.pypi.org/>).
  Checked: 2026-11-12.
- **Size.** At most 100 MB per file and 10 GB per project.
  Source: <https://docs.pypi.org/project-management/storage-limits/>. Checked: 2026-11-12.
- **Pictures.** PyPI's cleaner keeps `img` and removes `source`, so the README's `<picture>`
  shows its light `img` fallback there, by its full `raw.githubusercontent.com` address.
  Source: <https://github.com/pypa/readme_renderer/blob/main/readme_renderer/clean.py>, as
  Kitden's `docs/readme-media.md` notes (checked 2026-10-28).

## Homebrew (`desc` in the formula, which lives in the tap)

- At most 80 characters. The cop reports a desc only when it is longer than 80.
- No period at the end.
- Must not start with an article ("A", "An", "The").
- Must not start with the formula name. The Formula Cookbook says the name is added
  automatically, so there is no need to repeat it. The release check is stricter: it refuses
  the name ("Kitden", any case) anywhere in the text.
- Source: `brew audit` runs the desc cop,
  <https://github.com/Homebrew/brew/blob/HEAD/Library/Homebrew/rubocops/shared/desc_helper.rb>
  (`MAX_DESC_LENGTH = 80`, the article, name and period checks), and the
  [Formula Cookbook](https://docs.brew.sh/Formula-Cookbook#fill-in-the-desc) and
  [Description Guidelines](https://docs.brew.sh/Description-Guidelines).
- Checked: 2026-11-12.

Also for the formula:

- **`homepage` is required, and `license` is an SPDX identifier** (Kitden's is `Apache-2.0`).
  A `test do` block is expected; `--version` alone is a poor test.
  Source: <https://docs.brew.sh/Formula-Cookbook>. Checked: 2026-11-12.
- **Python dependencies.** Every Python dependency, recursive ones too, is a `resource` with
  its own URL and SHA-256, made with `brew update-python-resources`; the formula installs them
  with `virtualenv_install_with_resources` and depends on a versioned `python@3.y`. Homebrew's
  pip arguments delay packages published within its release cooldown, which is why the bump on
  release day fails when dependencies changed (spec A6).
  Source: <https://docs.brew.sh/Language-Specific-Formulae>. Checked: 2026-11-12.
- **Bottles come only from the tap's `brew pr-pull` workflow**, never from GitHub's Merge
  button (observed on 0.7.0).

## Publishing (`.github/workflows/publish.yml`)

How the publish workflow signs in to each place, and what we checked.

- **MCP Registry through GitHub OIDC.** A job with `id-token: write` (and `contents: read`)
  runs `mcp-publisher login github-oidc`, then `mcp-publisher publish` next to `server.json`.
  No secret is stored. The guide pins an `mcp-publisher` release on purpose instead of the
  moving `releases/latest`, and warns that a token for an organisation namespace can publish
  any server under `io.github.<org>/*`. We pin `v1.8.9` (the latest on 2026-11-12) and check
  the archive's SHA-256 from that release's `registry_1.8.9_checksums.txt`.
  Source: the registry's GitHub Actions guide,
  <https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/github-actions.mdx>.
  Checked: 2026-11-12.
- **The release app's key, an environment secret, in a reusable workflow.** The called job
  must name the environment (`environment: release`); the caller job cannot. The caller still
  passes the secret by name (`release_app_private_key: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}`),
  which works even when the secret exists only in the environment. A secret the caller does not
  pass is an empty string, so the workflow marks it `required: true`. Variables (`vars`) in a
  called workflow come from the caller's repository.
  Sources: <https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows>
  ("Using inputs and secrets in a reusable workflow") and
  <https://docs.github.com/en/actions/reference/workflows-and-actions/variables>.
  Checked: 2026-11-12.
- **The Claude plugin directory has no API.** Its listing comes from `plugin.json` and the
  README of the live version; the data handling answers are given in the developer portal,
  <https://claude.ai/directory/manage> (Submissions, then the plugin). The release summary
  links that page when `listing.toml` or `PRIVACY.md` changed since the last tag.
  Source: <https://claude.com/docs/plugins/submit>. Checked: 2026-11-12.
