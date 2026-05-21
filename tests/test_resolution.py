from kimai_everyday.resolution import (
    activities_for_project,
    resolve_activity,
    resolve_project,
)
from kimai_everyday.types import Activity, ParsedPattern, Project, Provenance


def _parsed(**kwargs) -> ParsedPattern:
    defaults = dict(slots=(), force_dates=frozenset())
    defaults.update(kwargs)
    return ParsedPattern(**defaults)


def _project(pid: int, name: str = "Proj") -> Project:
    return Project(id=pid, name=name, customer_name="ACME")


def _activity(aid: int, project_id: int | None, name: str = "Act") -> Activity:
    return Activity(id=aid, name=name, project_id=project_id)


# -- resolve_project ---------------------------------------------------------


def test_resolve_project_single_project_short_circuits():
    only = _project(1)
    out = resolve_project(_parsed(project_id=999, project_candidates=(42,)), [only], last_project_id=None)
    assert out.resolved == only
    assert out.provenance == Provenance.SINGLE
    assert out.candidates == ()


def test_resolve_project_uses_llm_pick_when_valid():
    a, b = _project(1), _project(2)
    out = resolve_project(_parsed(project_id=2), [a, b], last_project_id=1)
    assert out.resolved == b
    assert out.provenance == Provenance.LLM


def test_resolve_project_demotes_invalid_llm_pick_to_fallback():
    a, b = _project(1), _project(2)
    # LLM picked a non-existent ID and gave no candidates → last-used kicks in.
    out = resolve_project(_parsed(project_id=999), [a, b], last_project_id=1)
    assert out.resolved == a
    assert out.provenance == Provenance.LAST_USED


def test_resolve_project_returns_candidates_when_ambiguous():
    a, b, c = _project(1), _project(2), _project(3)
    out = resolve_project(
        _parsed(project_id=None, project_candidates=(1, 2)),
        [a, b, c],
        last_project_id=3,
    )
    assert out.resolved is None
    assert out.candidates == (a, b)
    assert out.provenance is None


def test_resolve_project_drops_invalid_candidates():
    a, b = _project(1), _project(2)
    out = resolve_project(
        _parsed(project_candidates=(1, 999, 2)),
        [a, b],
        last_project_id=None,
    )
    # 999 dropped, two valid candidates remain → ambiguous.
    assert out.candidates == (a, b)


def test_resolve_project_single_valid_candidate_resolves():
    a, b = _project(1), _project(2)
    out = resolve_project(
        _parsed(project_candidates=(1, 999)),  # only 1 is valid
        [a, b],
        last_project_id=None,
    )
    assert out.resolved == a
    assert out.provenance == Provenance.LLM


def test_resolve_project_no_signal_no_last_used_returns_unresolved():
    a, b = _project(1), _project(2)
    out = resolve_project(_parsed(), [a, b], last_project_id=None)
    assert out.resolved is None
    assert out.candidates == ()
    assert out.provenance is None


def test_resolve_project_last_used_only_when_still_valid():
    a, b = _project(1), _project(2)
    out = resolve_project(_parsed(), [a, b], last_project_id=999)
    # last_used was a since-deleted project → no fallback.
    assert out.resolved is None
    assert out.provenance is None


# -- resolve_activity --------------------------------------------------------


def test_resolve_activity_filters_to_project_scope():
    proj = _project(1)
    g = _activity(10, None, "Meetings")  # global
    a = _activity(20, 1, "Dev on 1")     # scoped to proj 1
    b = _activity(30, 2, "Dev on 2")     # scoped to a different proj
    out = resolve_activity(_parsed(activity_id=30), [g, a, b], proj, last_activity_id=None)
    # 30 is scoped to a different project → invalid for this project.
    assert out.resolved is None
    assert out.candidates == ()


def test_resolve_activity_single_valid_short_circuits():
    proj = _project(1)
    g = _activity(10, None)
    b = _activity(30, 2)  # belongs to a different project; filtered out
    out = resolve_activity(_parsed(activity_id=999), [g, b], proj, last_activity_id=None)
    # After scope filtering, only `g` remains → single, short-circuit.
    assert out.resolved == g
    assert out.provenance == Provenance.SINGLE


def test_resolve_activity_uses_llm_pick_when_global():
    proj = _project(1)
    g = _activity(10, None)
    a = _activity(20, 1)
    out = resolve_activity(_parsed(activity_id=10), [g, a], proj, last_activity_id=None)
    assert out.resolved == g
    assert out.provenance == Provenance.LLM


def test_resolve_activity_last_used_fallback_when_still_valid():
    proj = _project(1)
    g = _activity(10, None)
    a = _activity(20, 1)
    out = resolve_activity(_parsed(), [g, a], proj, last_activity_id=20)
    assert out.resolved == a
    assert out.provenance == Provenance.LAST_USED


def test_resolve_activity_last_used_dropped_when_scoped_elsewhere():
    proj = _project(1)
    g = _activity(10, None)
    a = _activity(20, 1)
    b = _activity(30, 2)  # last-used belonged to a different project
    out = resolve_activity(_parsed(), [g, a, b], proj, last_activity_id=30)
    # 30 is filtered out by scope → last-used dropped, unresolved.
    # `g` and `a` are both valid → not short-circuit → unresolved.
    assert out.resolved is None
    assert out.provenance is None


def test_resolve_activity_candidates_filtered_by_scope():
    proj = _project(1)
    g = _activity(10, None)
    a = _activity(20, 1)
    b = _activity(30, 2)  # not valid for proj 1
    out = resolve_activity(
        _parsed(activity_candidates=(10, 20, 30)),
        [g, a, b],
        proj,
        last_activity_id=None,
    )
    assert out.resolved is None
    assert {c.id for c in out.candidates} == {10, 20}


# -- activities_for_project --------------------------------------------------


def test_activities_for_project_includes_globals_and_scoped():
    proj = _project(1)
    activities = [
        _activity(10, None),
        _activity(20, 1),
        _activity(30, 2),
        _activity(40, None),
    ]
    result = activities_for_project(activities, proj)
    assert {a.id for a in result} == {10, 20, 40}
