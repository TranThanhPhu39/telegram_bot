"""Quarter-period continuity checks shared by coverage, scoring, and views."""

from __future__ import annotations

from dataclasses import dataclass


def is_quarter_period(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 6
        and value[:4].isdigit()
        and value[4] == "Q"
        and value[5] in "1234"
    )


def previous_quarter(period: str) -> str:
    if not is_quarter_period(period):
        raise ValueError("period must use YYYYQn")
    year = int(period[:4])
    quarter = int(period[5])
    if quarter == 1:
        return f"{year - 1:04d}Q4"
    return f"{year:04d}Q{quarter - 1}"


def quarter_sequence(latest: str, count: int = 8) -> tuple[str, ...]:
    if count <= 0:
        raise ValueError("count must be positive")
    periods = [latest]
    while len(periods) < count:
        periods.append(previous_quarter(periods[-1]))
    return tuple(periods)


@dataclass(frozen=True, slots=True)
class QuarterContinuity:
    latest: str | None
    expected: tuple[str, ...]
    available: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.expected) and not self.missing


def analyze_quarter_continuity(
    periods: object, required: int = 8
) -> QuarterContinuity:
    """Validate the latest ``required`` fiscal quarters without filling gaps."""
    if required <= 0:
        raise ValueError("required must be positive")
    available = tuple(sorted({str(value) for value in periods if is_quarter_period(value)}, reverse=True))
    if not available:
        return QuarterContinuity(None, (), (), ())
    expected = quarter_sequence(available[0], required)
    present = set(available)
    missing = tuple(period for period in expected if period not in present)
    return QuarterContinuity(available[0], expected, available, missing)
