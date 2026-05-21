from __future__ import annotations

import json
from datetime import date, time
from typing import Any

from anthropic import Anthropic

from kimai_everyday.types import Activity, DateSlot, ParsedPattern, Project, TimeBlock

MODEL = "claude-haiku-4-5-20251001"

PATTERN_TOOL = {
    "name": "submit_pattern",
    "description": "Submit the parsed Pattern as structured data.",
    "input_schema": {
        "type": "object",
        "required": ["slots", "force_dates"],
        "properties": {
            "slots": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["date", "blocks"],
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "ISO date YYYY-MM-DD",
                        },
                        "blocks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["begin", "end"],
                                "properties": {
                                    "begin": {"type": "string", "description": "HH:MM 24h"},
                                    "end": {"type": "string", "description": "HH:MM 24h"},
                                },
                            },
                        },
                    },
                },
            },
            "force_dates": {
                "type": "array",
                "description": (
                    "Dates (YYYY-MM-DD) that should bypass weekend/holiday filters. "
                    "Only include a date here if the user EXPLICITLY opted it in "
                    "(e.g. 'auch am Samstag', 'auch am Tag der Arbeit')."
                ),
                "items": {"type": "string"},
            },
            "project_id": {
                "type": ["integer", "null"],
                "description": (
                    "The chosen project ID from the catalog. Set ONLY if you are confident the "
                    "sentence unambiguously names one project. Otherwise leave null and populate "
                    "project_candidates instead."
                ),
            },
            "project_candidates": {
                "type": "array",
                "description": (
                    "Project IDs from the catalog that plausibly match the sentence, when no "
                    "single project is clearly the right answer. Order most-likely first. "
                    "Leave empty if the sentence does not name any project."
                ),
                "items": {"type": "integer"},
            },
            "activity_id": {
                "type": ["integer", "null"],
                "description": (
                    "The chosen activity ID from the catalog. Set ONLY if you are confident. "
                    "MUST be either a global activity or one scoped to the chosen project_id. "
                    "Otherwise leave null and populate activity_candidates."
                ),
            },
            "activity_candidates": {
                "type": "array",
                "description": (
                    "Activity IDs (globals or activities scoped to the chosen project) that "
                    "plausibly match the sentence. Order most-likely first. Leave empty if the "
                    "sentence does not name any activity."
                ),
                "items": {"type": "integer"},
            },
            "description": {
                "type": ["string", "null"],
                "description": (
                    "Free-text description extracted from the sentence — text that is neither a "
                    "date/time phrase nor a project/activity reference. Null if no such text "
                    "exists. Do NOT echo the whole sentence here."
                ),
            },
        },
    },
}


def _format_catalog(projects: list[Project], activities: list[Activity]) -> str:
    """Format the catalog as compact `id | label` lines for the system prompt."""
    project_lines = "\n".join(
        f"  {p.id} | {p.label}" for p in sorted(projects, key=lambda p: p.id)
    )
    project_id_by = {p.id: p for p in projects}
    activity_lines: list[str] = []
    for a in sorted(activities, key=lambda a: a.id):
        if a.is_global:
            scope = "(global)"
        else:
            owner = project_id_by.get(a.project_id)  # type: ignore[arg-type]
            scope = f"(project: {owner.label})" if owner else f"(project id: {a.project_id})"
        activity_lines.append(f"  {a.id} | {a.name} {scope}")
    return (
        "PROJECTS (id | Customer / Name):\n"
        f"{project_lines or '  (none)'}\n"
        "\n"
        "ACTIVITIES (id | Name (scope)):\n"
        f"{chr(10).join(activity_lines) or '  (none)'}"
    )


def _system_prompt(
    today: date,
    timezone: str,
    projects: list[Project],
    activities: list[Activity],
) -> str:
    return (
        "You translate a recurrence sentence (German or English) into structured data: "
        "dated time blocks, plus the project, activity, and optional description.\n"
        f"Today is {today.isoformat()} ({today.strftime('%A')}). The user's timezone is {timezone}.\n"
        "\n"
        "DATE RULES:\n"
        "- Output every individual date the sentence covers, even weekends and holidays. "
        "  Downstream code applies the working-day filter; do NOT pre-filter weekends or holidays.\n"
        "- Each date has one or more time blocks (begin/end, 24h HH:MM).\n"
        "- Explicit weekend/holiday opt-ins (e.g. 'auch am Samstag den 17. Mai', 'auch am Tag der Arbeit') "
        "  go in `force_dates`. Never put a date in `force_dates` unless the user explicitly opted in.\n"
        "- Resolve relative phrases ('nächste Woche', 'im Mai') against today's date. Months without a year "
        "  refer to the soonest upcoming occurrence (current month if not past, otherwise next year).\n"
        "- Exclusion ranges like '15. bis 23. Mai' are inclusive on both ends and must be omitted from `slots`.\n"
        "\n"
        "PROJECT & ACTIVITY RULES:\n"
        "- Use the catalog below to resolve project_id and activity_id. Match against the labels.\n"
        "- Set `project_id` ONLY when one project clearly matches. If the sentence is ambiguous, "
        "  put plausible IDs in `project_candidates` and leave `project_id` null.\n"
        "- Same rule for `activity_id` / `activity_candidates`.\n"
        "- A scoped activity (one with `(project: X)` in the catalog) is ONLY valid for project X. "
        "  Globals are valid for any project. If the user names a scoped activity that belongs to "
        "  a different project than the one they named, that's a mismatch — fall back to candidates.\n"
        "- If the sentence does not mention a project or activity at all, leave both IDs null and "
        "  both candidate lists empty. Downstream code will fall back to the user's last-used values.\n"
        "\n"
        "DESCRIPTION RULE:\n"
        "- Extract any free text that isn't a date/time phrase and doesn't match a catalog name "
        "  into `description`. If there's none, leave it null. Do NOT echo the whole sentence.\n"
        "\n"
        "Always call the submit_pattern tool. Do not produce any prose.\n"
        "\n"
        "CATALOG:\n"
        f"{_format_catalog(projects, activities)}\n"
    )


class LLMError(RuntimeError):
    pass


def parse_pattern(
    sentence: str,
    *,
    today: date,
    timezone: str,
    api_key: str,
    projects: list[Project] | None = None,
    activities: list[Activity] | None = None,
) -> ParsedPattern:
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=_system_prompt(today, timezone, projects or [], activities or []),
        tools=[PATTERN_TOOL],
        tool_choice={"type": "tool", "name": "submit_pattern"},
        messages=[{"role": "user", "content": sentence}],
    )

    tool_block = next(
        (block for block in response.content if getattr(block, "type", None) == "tool_use"),
        None,
    )
    if tool_block is None:
        raise LLMError("Model did not call the submit_pattern tool.")
    raw = tool_block.input
    if isinstance(raw, str):
        raw = json.loads(raw)
    return _validate(raw)


def _validate(raw: Any) -> ParsedPattern:
    if not isinstance(raw, dict):
        raise LLMError(f"Tool input was not a JSON object: {type(raw).__name__}")
    raw_slots = raw.get("slots")
    raw_forced = raw.get("force_dates", [])
    if not isinstance(raw_slots, list):
        raise LLMError("`slots` missing or not a list.")
    if not isinstance(raw_forced, list):
        raise LLMError("`force_dates` must be a list.")

    slots: list[DateSlot] = []
    for entry in raw_slots:
        if not isinstance(entry, dict):
            raise LLMError(f"Slot is not an object: {entry!r}")
        raw_date = entry.get("date")
        raw_blocks = entry.get("blocks")
        if not isinstance(raw_date, str) or not isinstance(raw_blocks, list):
            raise LLMError(f"Slot missing date/blocks: {entry!r}")
        try:
            slot_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise LLMError(f"Invalid slot date {raw_date!r}: {exc}") from exc
        if not raw_blocks:
            raise LLMError(f"Slot {raw_date} has no time blocks.")
        blocks: list[TimeBlock] = []
        for blk in raw_blocks:
            if not isinstance(blk, dict):
                raise LLMError(f"Block is not an object: {blk!r}")
            try:
                begin = time.fromisoformat(blk["begin"])
                end = time.fromisoformat(blk["end"])
            except (KeyError, ValueError) as exc:
                raise LLMError(f"Invalid time in block {blk!r}: {exc}") from exc
            if end <= begin:
                raise LLMError(f"Block end must be after begin: {blk!r}")
            blocks.append(TimeBlock(begin=begin, end=end))
        slots.append(DateSlot(date=slot_date, blocks=tuple(blocks)))

    forced: set[date] = set()
    for entry in raw_forced:
        if not isinstance(entry, str):
            raise LLMError(f"force_dates entry is not a string: {entry!r}")
        try:
            forced.add(date.fromisoformat(entry))
        except ValueError as exc:
            raise LLMError(f"Invalid force_dates entry {entry!r}: {exc}") from exc

    project_id = _opt_int(raw, "project_id")
    activity_id = _opt_int(raw, "activity_id")
    project_candidates = _int_list(raw, "project_candidates")
    activity_candidates = _int_list(raw, "activity_candidates")
    description = raw.get("description")
    if description is not None and not isinstance(description, str):
        raise LLMError(f"`description` must be a string or null: {description!r}")
    if isinstance(description, str):
        description = description.strip() or None

    slots.sort(key=lambda s: s.date)
    return ParsedPattern(
        slots=tuple(slots),
        force_dates=frozenset(forced),
        project_id=project_id,
        project_candidates=project_candidates,
        activity_id=activity_id,
        activity_candidates=activity_candidates,
        description=description,
    )


def _opt_int(raw: dict[str, Any], key: str) -> int | None:
    val = raw.get(key)
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        raise LLMError(f"`{key}` must be an integer or null: {val!r}")
    return val


def _int_list(raw: dict[str, Any], key: str) -> tuple[int, ...]:
    val = raw.get(key, [])
    if not isinstance(val, list):
        raise LLMError(f"`{key}` must be a list: {val!r}")
    result: list[int] = []
    for entry in val:
        if isinstance(entry, bool) or not isinstance(entry, int):
            raise LLMError(f"`{key}` entry is not an integer: {entry!r}")
        result.append(entry)
    return tuple(result)
