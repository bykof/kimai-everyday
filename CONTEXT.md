# Context

A small TUI for creating recurring time-tracking entries ("patterns") in Kimai
via its REST API.

## Glossary

### Pattern
A free-form natural-language sentence (German or English) that describes one or
more recurring **time blocks** over a **date range**, with optional
**exclusions**, **project**, **activity**, and **description**.

Example: *"jeden Tag von 08:00 bis 12:00 Uhr und von 13:00 bis 17:00 Uhr für den
ganzen Mai außer vom 15. bis 23. Mai, Acme Migration, Development, refactoring
auth."*

A Pattern is parsed into a list of **Slots** (one POST per Slot to
`/api/timesheets`). Parsing is non-deterministic (LLM): one combined call
extracts dates, times, project, activity, and description from the sentence,
using the fetched **Catalog** as the source of valid project/activity IDs. The
user always confirms the expanded preview before any Slot is created.

### Slot
A single `(date, begin_time, end_time, project, activity, description)` tuple
that becomes exactly one Kimai timesheet entry. The LLM resolves `project` and
`activity` from the Pattern sentence against the Catalog; all Slots produced
from one Pattern share the same project, activity, and description.

### Catalog
The full list of visible Kimai projects and activities (both project-scoped and
global) fetched at startup. Sent to the LLM as compact `id | label` lines so it
can resolve `project` and `activity` directly to IDs. Not cached between runs
— freshness over speed.

### Disambiguation
When the LLM is not confident which project or activity the sentence refers
to, it returns a short candidate list instead of a single ID. The user
resolves it with a single keystroke (numbered short-list prompt). If the LLM
is wrong entirely, the user escapes to the full autocomplete picker.
Disambiguation never re-parses the dates — they're sticky once parsed.

### Working day
By default: Monday – Friday, **excluding** any date returned by Kimai's
`/api/public-holidays` for the active group. Weekend and holiday dates are
skipped during Pattern expansion **unless** the Pattern sentence explicitly
opts a specific date in (e.g. "auch am Samstag den 17. Mai", "auch am Tag der
Arbeit").

Opt-in is expressed via the LLM's `force_dates` field — explicit ISO dates that
bypass every skip rule. The Mon–Fri and holiday filters are applied
deterministically in our code after the LLM responds; the LLM is never
responsible for the calendar logic itself.

### Public holiday
A date returned by `GET /api/public-holidays` for the configured group.
Kimai is the single source of truth — we never hard-code holiday calendars
or rely on the LLM to remember them.

### Overlapping timesheets (intentional)
Booking the same time block on multiple Projects is a normal user workflow,
not an error: a single hour of work may be billable to several Projects
simultaneously. The tool does **not** query existing timesheets for conflicts
and does **not** warn about overlap.

Consequence: re-running the same Pattern with the same Project+Activity
produces duplicate entries. The user is responsible for not re-running. There
is no built-in idempotency check.
