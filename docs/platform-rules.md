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
