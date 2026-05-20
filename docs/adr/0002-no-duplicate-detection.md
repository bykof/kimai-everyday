# 2. Do not detect or warn about overlapping timesheets

Date: 2026-05-20
Status: Accepted

## Context

A naive bulk-create tool guards against duplicates: re-running the same
pattern twice should not silently double every entry. The obvious
implementation queries `GET /api/timesheets` for the date range before the
POST loop, flags conflicts in the preview, and offers a "skip conflicts"
choice.

## Decision

We do **not** query for existing timesheets and we do **not** warn the user
about overlap.

## Why this is correct for this user

This tool serves a workflow where the same physical hour of work is
intentionally booked against multiple Kimai Projects simultaneously: one hour
of "08:00–09:00" might exist on three different Projects at the same time
because the work is billable to all of them. Treating overlap as a conflict
would be wrong nearly every time it fired.

The same logic applies even within a single Project+Activity scope — the user
considers overlap their own concern, not the tool's.

## Alternatives considered

- **Per-(project, activity) conflict warning.** Would catch accidental
  re-runs without flagging the legitimate multi-Project overlap. Rejected:
  the user explicitly described overlap as a normal pattern and asked for it
  to be allowed; adding a warning here would erode trust in the preview.
- **Full overlap warning.** Would fire on every legitimate parallel booking
  and quickly be muted/ignored.

## Consequences

- Re-running the same Pattern after a successful run silently doubles every
  entry. The user must remember which Patterns they have already run.
- Re-running after a *partial* failure also doubles the entries that did
  succeed the first time. Recovery from partial failures means hand-editing
  the Pattern to cover only the failed dates.
- If the workflow ever changes and overlap becomes an actual error, revisit
  this ADR before adding detection — the user's mental model has to change
  too.
