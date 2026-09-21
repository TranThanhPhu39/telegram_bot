"""Human-readable market coverage report, computed from the runtime database.

Counts come from ``symbol_data_coverage`` joined against the *current* market
universe (``symbols`` table); nothing is hard-coded. Statuses are the
*effective* ones: a READY row whose last success is older than the dataset's
refresh interval is reported STALE even if no worker sweep has persisted that
yet, a symbol with no row is NEVER_ATTEMPTED, and an abandoned IN_PROGRESS marker
is reported STALE. The report only reads; it never writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3

from fundamentals.coverage_store import (
    COVERAGE_DATASETS,
    CoverageStatus,
    effective_status,
    load_all_coverage,
)
from runtime.coverage_config import CoverageConfig
from runtime.market_universe import load_market_universe

STATUS_ORDER = (
    "READY", "PARTIAL", "STALE", "MISSING", "ERROR", "IN_PROGRESS", "NEVER_ATTEMPTED",
)

DATASET_TITLES = {
    "FINANCIALS": "Fundamentals",
    "INSTITUTIONAL": "Institutional flow",
    "MARKET_HISTORY": "Market history",
    "SECTOR_HISTORY": "Sector history",
    "NEWS": "News",
}


@dataclass(frozen=True, slots=True)
class CoverageReport:
    generated_at: datetime
    universe_size: int
    #: dataset -> effective status -> symbol count (every status present, zeros included)
    counts: dict[str, dict[str, int]]
    #: dataset -> effective status -> symbols (alphabetical), for drill-down
    members: dict[str, dict[str, tuple[str, ...]]]
    outside_universe: int


def build_coverage_report(
    connection: sqlite3.Connection, config: CoverageConfig | None = None, *,
    now: datetime | None = None, datasets: tuple[str, ...] | None = None,
) -> CoverageReport:
    config = config or CoverageConfig()
    stamp = now or datetime.now(timezone.utc)
    universe = load_market_universe(connection)
    symbols = {item.symbol for item in universe}
    wanted = datasets or COVERAGE_DATASETS
    rows: dict[tuple[str, str], CoverageStatus] = {}
    outside = 0
    for row in load_all_coverage(connection):
        if row.symbol in symbols:
            rows[(row.symbol, row.dataset)] = row
        else:
            outside += 1
    counts: dict[str, dict[str, int]] = {}
    members: dict[str, dict[str, tuple[str, ...]]] = {}
    for dataset in wanted:
        buckets: dict[str, list[str]] = {status: [] for status in STATUS_ORDER}
        interval = config.interval_for(dataset)
        for item in universe:
            status = effective_status(rows.get((item.symbol, dataset)), interval, now=stamp)
            buckets[status].append(item.symbol)
        counts[dataset] = {status: len(buckets[status]) for status in STATUS_ORDER}
        members[dataset] = {status: tuple(buckets[status]) for status in STATUS_ORDER}
    return CoverageReport(stamp, len(universe), counts, members, outside)


def render_report(report: CoverageReport) -> str:
    lines = [
        f"Coverage report - {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"Universe: {report.universe_size}",
    ]
    for dataset, counts in report.counts.items():
        lines.append("")
        lines.append(f"{DATASET_TITLES.get(dataset, dataset)} ({dataset})")
        for status in STATUS_ORDER:
            lines.append(f"  {status:<16}{counts[status]:>7}")
    if report.outside_universe:
        lines.append("")
        lines.append(
            f"Note: {report.outside_universe} coverage row(s) belong to symbols outside "
            "the current universe (inactive, non-stock or unsupported exchange)."
        )
    return "\n".join(lines)


def render_symbol_detail(
    connection: sqlite3.Connection, symbol: str, config: CoverageConfig | None = None, *,
    now: datetime | None = None,
) -> str:
    """Per-dataset row for one symbol: status, provider, attempts, timestamps, reason."""
    config = config or CoverageConfig()
    stamp = now or datetime.now(timezone.utc)
    symbol = symbol.strip().upper()
    stored = {
        row.dataset: row for row in load_all_coverage(connection) if row.symbol == symbol
    }
    universe = {item.symbol for item in load_market_universe(connection)}
    lines = [f"Coverage for {symbol} (in universe: {'yes' if symbol in universe else 'no'})"]
    for dataset in COVERAGE_DATASETS:
        row = stored.get(dataset)
        status = effective_status(row, config.interval_for(dataset), now=stamp)
        if row is None:
            lines.append(f"  {dataset:<15}{status}")
            continue
        provider = row.provider or "-"
        if row.provider_source:
            provider = f"{provider}/{row.provider_source}"
        lines.append(
            f"  {dataset:<15}{status:<16}provider={provider} attempts={row.attempts} "
            f"last_attempt={_fmt(row.last_attempt)} last_success={_fmt(row.last_success)}"
            + (f" reason={row.error_reason}" if row.error_reason else "")
        )
    return "\n".join(lines)


def render_status_listing(
    report: CoverageReport, dataset: str, status: str, limit: int = 50
) -> str:
    symbols = report.members.get(dataset, {}).get(status, ())
    shown = symbols[:limit]
    tail = f" (+{len(symbols) - len(shown)} more)" if len(symbols) > len(shown) else ""
    return f"{dataset} {status}: {len(symbols)} symbol(s)\n  " + (
        " ".join(shown) if shown else "-"
    ) + tail


def _fmt(value: datetime | None) -> str:
    return "-" if value is None else value.strftime("%Y-%m-%d %H:%M")
