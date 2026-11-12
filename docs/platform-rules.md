# Platform rules

The limits that the stores put on Kitden's names and descriptions.
`scripts/release_check.py` enforces the ones below. Each has its source and the date
we checked it.

## Official MCP Registry (`server.json`)

- `description`: 1 to 100 characters.
- Source: the schema named in Kitden's `server.json` `$schema`,
  <https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json>
  (`ServerDetail.description`, `maxLength: 100`).
- Checked: 2026-11-12.

## PyPI (`project.description` in `pyproject.toml`)

- The summary is one line. It must not hold a line break. The spec sets no character limit.
- Source: the Summary field in the core metadata specification,
  <https://packaging.python.org/en/latest/specifications/core-metadata/#summary>
  ("A one-line summary of what the distribution does").
- Checked: 2026-11-12.

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
