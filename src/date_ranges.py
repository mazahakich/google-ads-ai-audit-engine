from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta


EVIDENCE_PERIOD_DAYS = (30, 60, 90, 180)


@dataclass(frozen=True)
class DateRange:
    period_label: str
    start_date: str
    end_date: str
    days: int

    def to_dict(self) -> dict:
        return asdict(self)


def complete_day_range(days: int, today: date | None = None) -> DateRange:
    """Return a complete-day range ending yesterday."""
    if days <= 0:
        raise ValueError("days must be greater than zero")

    current_date = today or date.today()
    end_date = current_date - timedelta(days=1)
    start_date = current_date - timedelta(days=days)

    return DateRange(
        period_label=f"last_{days}_days",
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        days=days,
    )


def evidence_date_ranges(today: date | None = None) -> list[DateRange]:
    return [complete_day_range(days, today=today) for days in EVIDENCE_PERIOD_DAYS]
