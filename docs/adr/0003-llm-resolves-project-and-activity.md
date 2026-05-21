# 3. LLM resolves project, activity, and description from the Pattern sentence

Date: 2026-05-21
Status: Accepted

## Context

ADR 0001 established that a single LLM call parses the Pattern sentence into
dated time blocks. The wizard around it still required two interactive
autocomplete inputs (Project, then Activity) plus a free-text Description
prompt before the sentence was even typed. Three of the four inputs the user
provides are picked from prompts; only the sentence itself is free-form.

The user's goal is a true one-liner: type *"jeden Tag im Mai 9–17 Acme
migration, refactoring auth"* and have the tool figure out the project,
activity, and description from the sentence. Interactive prompts should only
appear when the tool genuinely cannot decide.

## Decision

Extend the existing `submit_pattern` LLM call so it resolves the project,
activity, and description in the same round trip that parses the dates. The
LLM receives the full **Catalog** (every visible project + every visible
activity, scoped and global) as compact `id | label` lines in the system
prompt and returns:

- `project_id` (int, nullable) — set when the LLM is confident.
- `project_candidates` (list[int]) — set when the LLM is uncertain.
- `activity_id` (int, nullable) — same semantics, scoped by the chosen project.
- `activity_candidates` (list[int]) — same semantics.
- `description` (string, nullable) — extracted free text, or null.
- `slots`, `force_dates` — unchanged from ADR 0001.

A pure `resolution.py` module post-processes the LLM output against the
fetched catalog:

- Validate IDs exist; demote invalid picks to "ambiguous."
- Enforce activity scope (scoped activities only valid for their project;
  globals always valid).
- Short-circuit degenerate cases (single project on the instance → no
  decision to make; single activity for the chosen project → same).
- Fall back to the user's last-used project/activity from config when the
  sentence mentions neither and they remain valid.

When resolution leaves an ambiguity, the wizard presents a **Disambiguation**
short-list (numbered, single-keystroke). An explicit "none of these" option
falls back to the existing autocomplete picker, which is preserved as the
recovery path. Dates are never re-parsed during recovery.

A `--classic` CLI flag retains the original multi-step wizard as an escape
hatch.

## Alternatives considered

- **Two LLM calls (resolve project/activity first, then parse dates).**
  Doubles latency, and slices the sentence twice — one sentence fragment
  might disambiguate the other (e.g. "Acme Mai-Sprint" relies on context to
  pick between project "Acme" and project "Mai-Sprint"). Rejected.
- **Embedding-based pre-filter on the catalog.** Cheaper tokens, but
  introduces a retrieval step that can hide the correct answer from the LLM
  and adds a maintenance burden (embeddings + a similarity threshold to
  tune). Rejected — the catalog fits comfortably in Haiku's window.
- **Free-text project/activity name extracted by the LLM + fuzzy match in
  code.** Two layers of fuzziness compound: an LLM error and a matcher
  error can both produce silent wrong picks, and debugging gets harder.
  Rejected.
- **Catalog cache between runs.** Sub-100 ms warm starts, but stale projects
  produce silent wrong picks — the LLM picks a plausible-looking ID that
  doesn't exist anymore. Rejected; the three small HTTP calls in parallel
  cost less than the LLM round trip itself.
- **Auto-fall-back to the classic wizard on any LLM error.** Hides real
  configuration problems (e.g. missing API key) and creates two
  always-live code paths to reason about. Rejected; `--classic` is an
  explicit user choice instead.

## Consequences

- The Catalog is fetched on every run (three small HTTP calls in parallel),
  not cached. New projects added in Kimai become available immediately.
- The LLM prompt now carries up to a few thousand tokens of catalog data on
  every invocation. Still ~$0.001/call with Haiku. We will re-evaluate if
  any user has an instance with >500 projects.
- Validation against the catalog is load-bearing: if the LLM hallucinates an
  ID, the resolution module catches it and demotes to ambiguous rather than
  posting wrong entries. The preview-and-confirm gate from ADR 0001 remains
  the final safety net.
- Description is now extracted from the sentence as a nullable field. When
  absent, entries are created without a description (no fallback to
  last-used; descriptions are per-Pattern by nature).
- The classic multi-step wizard remains in the codebase as the `--classic`
  flow and as the recovery path inside Disambiguation. Once the one-liner is
  battle-tested we may remove `--classic` in a future ADR; the recovery
  pickers stay regardless.
- The preview banner now shows **provenance**: when the project/activity
  came from the LLM, from the user's last-used fallback, or from
  disambiguation. This is important because the user no longer chose them
  explicitly.
