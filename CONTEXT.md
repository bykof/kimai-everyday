# Context

A small TUI for creating recurring time-tracking entries ("patterns") in Kimai
via its REST API.

## Glossary

### Pattern
A free-form natural-language sentence (German or English) that describes one or
more recurring **time blocks** over a **date range**, with optional **exclusions**.

Example: *"jeden Tag von 08:00 bis 12:00 Uhr und von 13:00 bis 17:00 Uhr für den
ganzen Mai außer vom 15. bis 23. Mai."*

A Pattern is parsed into a list of **Slots** (one POST per Slot to
`/api/timesheets`). The parsing step is non-deterministic (LLM) — the user
always confirms the expanded preview before any Slot is created.

### Slot
A single `(date, begin_time, end_time, project, activity)` tuple that becomes
exactly one Kimai timesheet entry. Slots inherit `project` and `activity` from
the Pattern; the LLM only produces dates and time ranges.

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
