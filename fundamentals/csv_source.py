"""Controlled CSV snapshot source for V1 fundamentals."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from fundamentals.models import FundamentalSnapshot


REQUIRED_COLUMNS = (
    "symbol", "as_of_date", "source", "eps", "pe", "pb", "roe_percent",
    "revenue_growth_percent", "profit_growth_percent",
)


def load_fundamental_csv(path: str | Path) -> tuple[FundamentalSnapshot, ...]:
    """Load a UTF-8 CSV export while preserving row-level provenance."""
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or tuple(reader.fieldnames) != REQUIRED_COLUMNS:
            raise ValueError("fundamental CSV columns do not match the V1 schema")
        snapshots: list[FundamentalSnapshot] = []
        seen: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            symbol = row["symbol"].strip().upper()
            if symbol in seen:
                raise ValueError(f"duplicate fundamental symbol at row {row_number}")
            seen.add(symbol)
            try:
                as_of = date.fromisoformat(row["as_of_date"].strip())
            except ValueError as exc:
                raise ValueError(f"invalid as_of_date at row {row_number}") from exc
            snapshots.append(
                FundamentalSnapshot(
                    symbol=symbol,
                    as_of_date=as_of,
                    source=row["source"].strip(),
                    eps=_optional_float(row["eps"], "eps", row_number),
                    pe=_optional_float(row["pe"], "pe", row_number),
                    pb=_optional_float(row["pb"], "pb", row_number),
                    roe_percent=_optional_float(row["roe_percent"], "roe_percent", row_number),
                    revenue_growth_percent=_optional_float(
                        row["revenue_growth_percent"], "revenue_growth_percent", row_number
                    ),
                    profit_growth_percent=_optional_float(
                        row["profit_growth_percent"], "profit_growth_percent", row_number
                    ),
                )
            )
    return tuple(snapshots)


def _optional_float(raw: str, name: str, row: int) -> float | None:
    value = raw.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"invalid {name} at row {row}") from exc
