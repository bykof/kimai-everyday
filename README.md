# kimai-everyday

A small TUI that turns natural-language recurrence sentences into Kimai
timesheet entries.

Type *"jeden Tag von 08:00 bis 12:00 und von 13:00 bis 17:00 im Mai außer vom
15. bis 23. Mai"* — get a preview of every working day with both time blocks —
confirm — done.

See [CONTEXT.md](./CONTEXT.md) for the domain glossary and
[docs/adr/](./docs/adr/) for the recorded architectural decisions.

## Install

```sh
pipx install kimai-everyday
```

Or, if you prefer plain `pip`:

```sh
pip install kimai-everyday
```

Requires Python 3.11+. See the package on [PyPI](https://pypi.org/project/kimai-everyday/).

## First run

```sh
kimai-everyday
```

On first run, the tool prompts for:
- Kimai base URL (e.g. `https://kimai.example.com`)
- Kimai API token
- Anthropic API key (or leave blank to use `$ANTHROPIC_API_KEY`)
- Timezone (defaults to your system timezone)

The token is validated against `GET /api/users/me` before the config is
written. The file is saved to `~/.config/kimai-everyday/config.toml` with
mode 0600.

## Day-to-day

```sh
kimai-everyday              # full wizard
kimai-everyday --dry-run    # show the preview, skip the POST step
kimai-everyday config       # update saved settings (URL, tokens, timezone)
```

The wizard order: Project → Activity → Description → Pattern sentence →
Preview table → confirmation → POST loop with progress bar → summary.

## Patterns

The sentence is parsed by Claude Haiku. It accepts free-form German or English,
including:

German:

- *"jeden Tag im Juni von 09:00 bis 17:00 Uhr"*
- *"Montag bis Donnerstag in der ersten Maiwoche, 08–12 und 13–17"*
- *"die nächsten zwei Wochen, 9–18 Uhr, außer Pfingstmontag"*
- *"jeden Werktag im Mai, auch am Samstag den 17."*

English:

- *"every weekday in June from 09:00 to 17:00"*
- *"Monday through Thursday next week, 08–12 and 13–17"*
- *"the next two weeks, 9 to 6, except the Friday after Easter"*
- *"every workday in May, also Saturday the 17th"*

Weekends and dates returned by Kimai's `/api/public-holidays` are skipped by
default. The user can opt them in with phrases like *"auch am Samstag den 17.
Mai"* or *"also on Labour Day"*.

## Development

Clone the repo and install from source:

```sh
pip install -e ".[dev]"
pytest
```

The pure date-filter logic in `expansion.py` is the only thing worth
unit-testing in depth; the rest is shell around external services.
