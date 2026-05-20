from dataclasses import dataclass
from datetime import date, time
from enum import Enum


@dataclass(frozen=True)
class Config:
    kimai_url: str
    kimai_token: str
    anthropic_api_key: str | None
    timezone: str
    last_project_id: int | None = None
    last_activity_id: int | None = None


@dataclass(frozen=True)
class TimeBlock:
    begin: time
    end: time


@dataclass(frozen=True)
class DateSlot:
    date: date
    blocks: tuple[TimeBlock, ...]


@dataclass(frozen=True)
class ParsedPattern:
    slots: tuple[DateSlot, ...]
    force_dates: frozenset[date]


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    customer_name: str

    @property
    def label(self) -> str:
        return f"{self.customer_name} / {self.name}"


@dataclass(frozen=True)
class Activity:
    id: int
    name: str
    project_id: int | None

    @property
    def is_global(self) -> bool:
        return self.project_id is None


@dataclass(frozen=True)
class PublicHoliday:
    date: date
    name: str


class RowStatus(Enum):
    OK = "ok"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"
    FORCED = "forced"


@dataclass(frozen=True)
class PreviewRow:
    date: date
    blocks: tuple[TimeBlock, ...]
    status: RowStatus
    reason: str

    @property
    def will_create(self) -> bool:
        return self.status in (RowStatus.OK, RowStatus.FORCED)
