"""Pure resolution of the LLM's project/activity picks against the Kimai catalog.

No I/O, no interaction. Given the LLM output and the fetched catalog, decides
whether each axis (project, activity) is `resolved`, `ambiguous` (with a
candidate short-list), or `unresolved` (nothing to go on, caller must prompt).
The wizard wraps this in the disambiguation UI.
"""
from __future__ import annotations

from dataclasses import dataclass

from kimai_everyday.types import Activity, ParsedPattern, Project, Provenance


@dataclass(frozen=True)
class ProjectOutcome:
    resolved: Project | None
    candidates: tuple[Project, ...]  # non-empty when ambiguous
    provenance: Provenance | None    # set only when resolved without prompting


@dataclass(frozen=True)
class ActivityOutcome:
    resolved: Activity | None
    candidates: tuple[Activity, ...]
    provenance: Provenance | None


def resolve_project(
    parsed: ParsedPattern,
    projects: list[Project],
    last_project_id: int | None,
) -> ProjectOutcome:
    """Validate the LLM's project pick against the catalog.

    Order of precedence:
      1. Single project on the instance — short-circuit, no decision.
      2. LLM picked a valid project_id — use it.
      3. LLM gave candidates — return the valid subset as ambiguous.
      4. Sentence said nothing AND last-used is still valid — use it silently.
      5. Otherwise unresolved (caller decides: prompt or autocomplete).
    """
    by_id = {p.id: p for p in projects}

    if len(projects) == 1:
        return ProjectOutcome(projects[0], (), Provenance.SINGLE)

    pick = by_id.get(parsed.project_id) if parsed.project_id is not None else None
    if pick is not None:
        return ProjectOutcome(pick, (), Provenance.LLM)

    valid_candidates = tuple(
        by_id[cid] for cid in parsed.project_candidates if cid in by_id
    )
    if len(valid_candidates) == 1:
        # Only one candidate survived validation → treat as resolved.
        return ProjectOutcome(valid_candidates[0], (), Provenance.LLM)
    if valid_candidates:
        return ProjectOutcome(None, valid_candidates, None)

    # LLM had nothing usable. Fall back to last-used if still valid.
    if last_project_id is not None and last_project_id in by_id:
        return ProjectOutcome(by_id[last_project_id], (), Provenance.LAST_USED)

    return ProjectOutcome(None, (), None)


def resolve_activity(
    parsed: ParsedPattern,
    activities: list[Activity],
    project: Project,
    last_activity_id: int | None,
) -> ActivityOutcome:
    """Validate the LLM's activity pick against the catalog, scoped to `project`.

    A scoped activity is only valid for its own project. Globals are valid for any.
    """
    valid = [a for a in activities if a.is_global or a.project_id == project.id]
    by_id = {a.id: a for a in valid}

    if len(valid) == 1:
        return ActivityOutcome(valid[0], (), Provenance.SINGLE)

    pick = by_id.get(parsed.activity_id) if parsed.activity_id is not None else None
    if pick is not None:
        return ActivityOutcome(pick, (), Provenance.LLM)

    valid_candidates = tuple(
        by_id[cid] for cid in parsed.activity_candidates if cid in by_id
    )
    if len(valid_candidates) == 1:
        return ActivityOutcome(valid_candidates[0], (), Provenance.LLM)
    if valid_candidates:
        return ActivityOutcome(None, valid_candidates, None)

    if last_activity_id is not None and last_activity_id in by_id:
        return ActivityOutcome(by_id[last_activity_id], (), Provenance.LAST_USED)

    return ActivityOutcome(None, (), None)


def activities_for_project(activities: list[Activity], project: Project) -> list[Activity]:
    """Filter to the activities valid for one project (globals + that project's scoped)."""
    return [a for a in activities if a.is_global or a.project_id == project.id]
