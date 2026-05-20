from __future__ import annotations

from collections.abc import Iterable

from kimai_everyday.types import ParsedPattern, PreviewRow, PublicHoliday, RowStatus


def expand(
    parsed: ParsedPattern,
    holidays: Iterable[PublicHoliday],
) -> list[PreviewRow]:
    """Apply the Mon–Fri + holiday filter to the LLM's date list.

    Pure function: no I/O, no clock. Given the same inputs, always returns the same rows.
    Returns every date the LLM produced, annotated with status. Skipped rows are kept in
    the result so the preview can show them.
    """
    holiday_by_date = {h.date: h.name for h in holidays}
    rows: list[PreviewRow] = []
    for slot in parsed.slots:
        forced = slot.date in parsed.force_dates
        holiday_name = holiday_by_date.get(slot.date)
        is_weekend = slot.date.weekday() >= 5  # Saturday=5, Sunday=6

        if forced:
            status = RowStatus.FORCED
            if holiday_name:
                reason = f"forced (would skip: {holiday_name})"
            elif is_weekend:
                reason = "forced (would skip: weekend)"
            else:
                reason = "forced"
        elif holiday_name is not None:
            status = RowStatus.HOLIDAY
            reason = holiday_name
        elif is_weekend:
            status = RowStatus.WEEKEND
            reason = slot.date.strftime("%A")
        else:
            status = RowStatus.OK
            reason = ""

        rows.append(
            PreviewRow(
                date=slot.date,
                blocks=slot.blocks,
                status=status,
                reason=reason,
            )
        )
    return rows
