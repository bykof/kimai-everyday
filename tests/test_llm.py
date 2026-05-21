from datetime import date, time
from types import SimpleNamespace

import pytest

from kimai_everyday import llm
from kimai_everyday.llm import LLMError, _validate


def test_validate_happy_path():
    parsed = _validate(
        {
            "slots": [
                {
                    "date": "2026-05-04",
                    "blocks": [
                        {"begin": "08:00", "end": "12:00"},
                        {"begin": "13:00", "end": "17:00"},
                    ],
                }
            ],
            "force_dates": ["2026-05-17"],
        }
    )
    assert len(parsed.slots) == 1
    assert parsed.slots[0].date == date(2026, 5, 4)
    assert parsed.slots[0].blocks[0].begin == time(8, 0)
    assert parsed.force_dates == frozenset({date(2026, 5, 17)})


def test_validate_sorts_slots_by_date():
    parsed = _validate(
        {
            "slots": [
                {"date": "2026-05-05", "blocks": [{"begin": "08:00", "end": "12:00"}]},
                {"date": "2026-05-04", "blocks": [{"begin": "08:00", "end": "12:00"}]},
            ],
            "force_dates": [],
        }
    )
    assert [s.date for s in parsed.slots] == [date(2026, 5, 4), date(2026, 5, 5)]


def test_validate_rejects_inverted_block():
    with pytest.raises(LLMError, match="end must be after begin"):
        _validate(
            {
                "slots": [
                    {"date": "2026-05-04", "blocks": [{"begin": "12:00", "end": "08:00"}]}
                ],
                "force_dates": [],
            }
        )


def test_validate_rejects_empty_blocks():
    with pytest.raises(LLMError, match="no time blocks"):
        _validate({"slots": [{"date": "2026-05-04", "blocks": []}], "force_dates": []})


def test_validate_rejects_bad_date():
    with pytest.raises(LLMError, match="Invalid slot date"):
        _validate(
            {
                "slots": [{"date": "not-a-date", "blocks": [{"begin": "08:00", "end": "09:00"}]}],
                "force_dates": [],
            }
        )


def test_validate_rejects_non_object_input():
    with pytest.raises(LLMError):
        _validate("nope")


def test_validate_extracts_project_activity_and_description():
    parsed = _validate(
        {
            "slots": [{"date": "2026-05-04", "blocks": [{"begin": "09:00", "end": "17:00"}]}],
            "force_dates": [],
            "project_id": 42,
            "project_candidates": [],
            "activity_id": 7,
            "activity_candidates": [],
            "description": "refactoring auth",
        }
    )
    assert parsed.project_id == 42
    assert parsed.activity_id == 7
    assert parsed.description == "refactoring auth"


def test_validate_keeps_candidates_when_ids_ambiguous():
    parsed = _validate(
        {
            "slots": [{"date": "2026-05-04", "blocks": [{"begin": "09:00", "end": "17:00"}]}],
            "force_dates": [],
            "project_id": None,
            "project_candidates": [1, 2, 3],
            "activity_id": None,
            "activity_candidates": [10, 20],
            "description": None,
        }
    )
    assert parsed.project_id is None
    assert parsed.project_candidates == (1, 2, 3)
    assert parsed.activity_candidates == (10, 20)
    assert parsed.description is None


def test_validate_treats_empty_description_as_none():
    parsed = _validate(
        {
            "slots": [{"date": "2026-05-04", "blocks": [{"begin": "09:00", "end": "17:00"}]}],
            "force_dates": [],
            "description": "   ",
        }
    )
    assert parsed.description is None


def test_validate_rejects_non_integer_project_id():
    with pytest.raises(LLMError, match="project_id"):
        _validate(
            {
                "slots": [{"date": "2026-05-04", "blocks": [{"begin": "09:00", "end": "10:00"}]}],
                "force_dates": [],
                "project_id": "42",
            }
        )


def test_parse_pattern_extracts_tool_input(monkeypatch):
    """Smoke-test the full parse_pattern path with a stubbed Anthropic client."""
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            tool_use = SimpleNamespace(
                type="tool_use",
                input={
                    "slots": [
                        {"date": "2026-05-04", "blocks": [{"begin": "08:00", "end": "12:00"}]}
                    ],
                    "force_dates": [],
                },
            )
            return SimpleNamespace(content=[tool_use])

    class FakeAnthropic:
        def __init__(self, api_key):
            self.api_key = api_key
            self.messages = FakeMessages()

    monkeypatch.setattr(llm, "Anthropic", FakeAnthropic)

    parsed = llm.parse_pattern(
        "jeden Tag von 08 bis 12 am 4. Mai",
        today=date(2026, 5, 1),
        timezone="Europe/Berlin",
        api_key="sk-ant-test",
    )
    assert len(parsed.slots) == 1
    assert parsed.slots[0].date == date(2026, 5, 4)
    # The user's sentence reached the API call.
    assert captured["messages"][0]["content"] == "jeden Tag von 08 bis 12 am 4. Mai"
    # The tool was forced.
    assert captured["tool_choice"] == {"type": "tool", "name": "submit_pattern"}


def test_parse_pattern_raises_when_no_tool_use(monkeypatch):
    class FakeMessages:
        def create(self, **kwargs):
            text_block = SimpleNamespace(type="text", text="Sorry, can't help.")
            return SimpleNamespace(content=[text_block])

    class FakeAnthropic:
        def __init__(self, api_key):
            self.messages = FakeMessages()

    monkeypatch.setattr(llm, "Anthropic", FakeAnthropic)

    with pytest.raises(LLMError, match="did not call"):
        llm.parse_pattern(
            "anything",
            today=date(2026, 5, 1),
            timezone="Europe/Berlin",
            api_key="sk-ant-test",
        )
