from __future__ import annotations

import json
from datetime import date, time
from typing import Any

from anthropic import Anthropic

from kimai_everyday.types import DateSlot, ParsedPattern, TimeBlock

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
        },
    },
}


def _system_prompt(today: date, timezone: str) -> str:
    return (
        "You translate a recurrence sentence (German or English) into a list of dated time blocks.\n"
        f"Today is {today.isoformat()} ({today.strftime('%A')}). The user's timezone is {timezone}.\n"
        "\n"
        "RULES:\n"
        "- Output every individual date that the sentence covers, even weekends and holidays. "
        "  Downstream code applies the working-day filter; you must NOT pre-filter weekends or holidays yourself.\n"
        "- Each date has one or more time blocks (begin/end, 24h HH:MM).\n"
        "- If the sentence has explicit opt-ins for weekends or holidays (e.g. 'auch am Samstag den 17. Mai', "
        "  'auch am Tag der Arbeit'), include those dates in `force_dates`. Never put a date in `force_dates` unless "
        "  the user explicitly opted it in.\n"
        "- Resolve relative phrases ('nächste Woche', 'im Mai') against today's date. Months without a year refer to "
        "  the soonest upcoming occurrence (current month if not past, otherwise next year).\n"
        "- Exclusion ranges like '15. bis 23. Mai' are inclusive on both ends and must be omitted from `slots` entirely.\n"
        "- Always call the submit_pattern tool. Do not produce any prose.\n"
    )


class LLMError(RuntimeError):
    pass


def parse_pattern(
    sentence: str,
    *,
    today: date,
    timezone: str,
    api_key: str,
) -> ParsedPattern:
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=_system_prompt(today, timezone),
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

    slots.sort(key=lambda s: s.date)
    return ParsedPattern(slots=tuple(slots), force_dates=frozenset(forced))
