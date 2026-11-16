# Store rules

A made-up copy for tests, in the shapes `docs/platform-rules.md` uses. Each rule has its
source and the date it was checked.

## Shelf one (`plugins/demo`)

The shelf lists the folder that holds `demo.json`.
Source: <https://shelf.example.com/docs/submit>. Checked: 2026-11-10.

- **Name.** Lowercase letters and digits, at most 30 characters.
- **Icon.** A square picture inside the folder.

Sources: <https://shelf.example.com/docs/checklist>,
<https://shelf.example.com/docs/submit> and
<https://docs.example.org/en/reference#listing> ("name", "Listing fields").
Checked: 2026-11-09.

Shelf policy ([Demo Shelf Policy](https://help.example.com/articles/42-shelf-policy),
checked 2026-11-08):

- Descriptions say only what the plugin does.

## Index (<https://index.example.net/servers/demo>)

- `title`, when set, is 1 to 50 characters.
- Source: the schema named in `demo.json` `$schema`,
  <https://schemas.example.net/2026-01-01/demo.schema.json>
  (`Demo.title`, `maxLength: 50`).
- Checked: 2026-11-07.
- **Words.** No word from the banned list.
- Source: the [Demo Guide](https://docs.example.org/guide#fill-in) and the
  [Word Rules](https://docs.example.org/word-rules).
- Checked: 2026-11-06.

From the index itself:

- **Size.** At most 10 MB a file.
  Source: https://docs.example.org/limits, and https://docs.example.org/sizes. Checked: 2026-11-05.
- **Pictures.** The cleaner keeps `img` and drops `source`.
  Source: <https://code.example.com/cleaner/blob/main/clean.py>, as the notes say
  (checked 2026-10-28).
