from datetime import date, time

from kimai_everyday.expansion import expand
from kimai_everyday.types import DateSlot, ParsedPattern, PublicHoliday, RowStatus, TimeBlock

BLOCKS = (TimeBlock(begin=time(8, 0), end=time(12, 0)),)


def _pattern(dates: list[date], force: set[date] | None = None) -> ParsedPattern:
    return ParsedPattern(
        slots=tuple(DateSlot(date=d, blocks=BLOCKS) for d in dates),
        force_dates=frozenset(force or set()),
    )


def test_weekday_passes_through():
    # 2026-05-04 is a Monday.
    rows = expand(_pattern([date(2026, 5, 4)]), [])
    assert len(rows) == 1
    assert rows[0].status is RowStatus.OK
    assert rows[0].will_create


def test_saturday_is_skipped_by_default():
    # 2026-05-02 is a Saturday.
    rows = expand(_pattern([date(2026, 5, 2)]), [])
    assert rows[0].status is RowStatus.WEEKEND
    assert not rows[0].will_create
    assert rows[0].reason == "Saturday"


def test_saturday_with_force_date_passes():
    rows = expand(
        _pattern([date(2026, 5, 2)], force={date(2026, 5, 2)}),
        [],
    )
    assert rows[0].status is RowStatus.FORCED
    assert rows[0].will_create
    assert "weekend" in rows[0].reason


def test_holiday_is_skipped():
    rows = expand(
        _pattern([date(2026, 5, 1)]),  # Friday, Tag der Arbeit
        [PublicHoliday(date=date(2026, 5, 1), name="Tag der Arbeit")],
    )
    assert rows[0].status is RowStatus.HOLIDAY
    assert rows[0].reason == "Tag der Arbeit"
    assert not rows[0].will_create


def test_holiday_with_force_date_passes():
    rows = expand(
        _pattern([date(2026, 5, 1)], force={date(2026, 5, 1)}),
        [PublicHoliday(date=date(2026, 5, 1), name="Tag der Arbeit")],
    )
    assert rows[0].status is RowStatus.FORCED
    assert rows[0].will_create
    assert "Tag der Arbeit" in rows[0].reason


def test_holiday_takes_priority_over_weekend_in_message():
    # Holiday that falls on Sunday — reason should be the holiday name, not "Sunday".
    rows = expand(
        _pattern([date(2026, 12, 25)]),  # Friday — pick a Sunday holiday instead
        [PublicHoliday(date=date(2026, 4, 5), name="Easter Sunday")],
    )
    # We didn't include 12-25 as a holiday, so it's just a Friday OK.
    assert rows[0].status is RowStatus.OK

    rows = expand(
        _pattern([date(2026, 4, 5)]),  # Sunday
        [PublicHoliday(date=date(2026, 4, 5), name="Easter Sunday")],
    )
    assert rows[0].status is RowStatus.HOLIDAY
    assert rows[0].reason == "Easter Sunday"


def test_expand_is_pure_and_preserves_order():
    p = _pattern([date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 2)])
    rows_a = expand(p, [])
    rows_b = expand(p, [])
    assert rows_a == rows_b
    assert [r.date for r in rows_a] == [date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 2)]


def test_multiple_blocks_kept_intact():
    blocks = (
        TimeBlock(begin=time(8, 0), end=time(12, 0)),
        TimeBlock(begin=time(13, 0), end=time(17, 0)),
    )
    parsed = ParsedPattern(
        slots=(DateSlot(date=date(2026, 5, 4), blocks=blocks),),
        force_dates=frozenset(),
    )
    rows = expand(parsed, [])
    assert rows[0].blocks == blocks
