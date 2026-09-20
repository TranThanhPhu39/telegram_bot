"""Shared deterministic fixtures for the Phase 23 tests (no network)."""

from __future__ import annotations

from datetime import date

from asmf_data.models import SectorMembership
from asmf_data.store import upsert_sector_memberships
from data.database import connect_database
from runtime.bot_service import RuntimeBotDataService
from scanner.universe import ScannerInstrument

END_TS = 1_789_718_400          # Friday 2026-09-18 15:00 +07:00
DAY = 86_400
NOW_SAME_DAY = END_TS + 3_600
NOW_SUNDAY = END_TS + 2 * DAY + 3_600
USER = 555_001


def series(last: float, count: int = 260, drift: float = 0.0) -> list[float]:
    """Deterministic closes ending exactly at ``last``."""
    values = [last]
    for index in range(1, count):
        base = values[-1]
        wobble = 0.01 * (1 if index % 3 else -1) * (1 + (index % 5) / 5)
        values.append(base / (1 + wobble + drift))
    return list(reversed(values))


class FakeClient:
    """Serves `closes[symbol]`; unknown symbols return an empty gap-chart row."""

    def __init__(self, closes: dict[str, list[float]], end_ts: int = END_TS) -> None:
        self.closes = closes
        self.end_ts = end_ts
        self.fail = False
        self.calls: list[tuple[str, ...]] = []

    def get_gap_chart(self, symbols, **kwargs):
        self.calls.append(tuple(symbols))
        if self.fail:
            raise ValueError("offline")
        rows = []
        for symbol in symbols:
            values = self.closes.get(symbol, [])
            count = len(values)
            rows.append({
                "symbol": symbol,
                "t": [str(self.end_ts - (count - 1 - i) * DAY) for i in range(count)],
                "o": values, "h": [v + 1 for v in values], "l": [v - 1 for v in values],
                "c": values, "v": [100_000.0] * count,
            })
        return rows


def default_closes() -> dict[str, list[float]]:
    return {
        "FPT": series(160_000.0), "ACB": series(24_000.0), "HPG": series(30_000.0),
        "VNINDEX": series(1_300.0, drift=0.0005),
    }


def make_runtime(closes=None, now: float = NOW_SAME_DAY, sectors: bool = True):
    client = FakeClient(default_closes() if closes is None else closes)
    runtime = RuntimeBotDataService(
        client, connect_database("sqlite:///:memory:"),
        (ScannerInstrument("FPT", "HOSE", "STOCK"),), now=lambda: now,
    )
    if sectors:
        upsert_sector_memberships(runtime.connection, [
            SectorMembership("FPT", "TECH", "Technology", date(2020, 1, 1), None, "TEST"),
            SectorMembership("ACB", "BANK", "Banking", date(2020, 1, 1), None, "TEST"),
        ])
    return runtime, client