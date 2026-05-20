# 1. Use an LLM to parse Pattern sentences

Date: 2026-05-20
Status: Accepted

## Context

The tool's value proposition is that the user types a free-form sentence like
*"jeden Tag von 08:00 bis 12:00 Uhr und von 13:00 bis 17:00 Uhr für den ganzen
Mai außer vom 15. bis 23. Mai"* and gets a list of dated time slots ready to
post to Kimai. We need to convert that sentence into structured data.

## Decision

Send the Pattern sentence to Claude Haiku with a strict JSON-schema response
format. The model returns a list of `(date, begin, end)` triples plus any
explicit working-day overrides. The expanded list is shown to the user as a
preview; nothing is posted to Kimai until the user confirms.

## Alternatives considered

- **Hand-rolled grammar (Lark/PEG).** Deterministic and offline, but each new
  phrasing ("auch am Pfingstmontag", "die erste Woche im Juni") needs grammar
  work. The "type a sentence" UX collapses into "learn a DSL."
- **Structured TUI form.** Zero ambiguity, but contradicts the stated UX of
  sentence-based entry.

## Consequences

- Tool now depends on an Anthropic API key in addition to the Kimai token.
- ~1 s parsing latency and ~$0.0001 per Pattern.
- Hallucination risk is bounded by the mandatory preview-and-confirm step
  before any timesheet is created.
- We can extend the supported phrasings (English input, holiday names, "every
  other Monday") with prompt edits rather than code changes.
