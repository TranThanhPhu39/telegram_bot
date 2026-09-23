"""Refresh one symbol's automated fundamentals/institutional data.

This is the only place that calls a :class:`ProviderChain`. It is deliberately
free of Telegram imports — callers include the Phase 25 coverage worker,
manual admin scripts, and tests. Telegram commands themselves only ever read
what this service already persisted (see ``runtime/bot_service.py``), the
same non-blocking pattern the sector-sync worker established.

``refresh_financials``/``refresh_institutional_flow`` never raise for ordinary
provider conditions: everything becomes a :class:`RefreshOutcome` so a batch
loop can isolate one symbol's failure from the rest, per Phase 25 §23.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from enum import Enum
import sqlite3

from asmf_data.store import upsert_financial_reports, upsert_institutional_flows
from asmf_data.quarters import QuarterContinuity, analyze_quarter_continuity
from fundamentals.adapters import (
    corporate_promotion_gap,
    flow_row_to_institutional_flow,
    promote_corporate_statement,
)
from fundamentals.coverage_store import (
    _COVERAGE_STATUS_FROM_PROVIDER_STATUS,
    CoverageStatus,
    coverage_is_stale,
    load_coverage,
    record_attempt,
    record_coverage,
    upsert_automated_statement,
)
from fundamentals.providers.base import ProviderResult, ProviderStatus, StatementRow
from fundamentals.providers.provider_chain import ProviderChain

DEFAULT_FINANCIALS_REFRESH_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly
DEFAULT_INSTITUTIONAL_REFRESH_INTERVAL_SECONDS = 24 * 3600  # daily


class RefreshResult(str, Enum):
    """What a single refresh call actually did — never a bare bool."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    FAILED = "FAILED"
    SKIPPED_FRESH = "SKIPPED_FRESH"


def _canonical_financial_readiness(
    connection: sqlite3.Connection, symbol: str, as_of: date
) -> QuarterContinuity:
    as_of_str = as_of.isoformat()
    corporate = tuple(row[0] for row in connection.execute(
        "SELECT DISTINCT report_period FROM financial_reports "
        "WHERE symbol=? AND consolidated=1 AND public_date<=? "
        "AND (source NOT LIKE 'yfinance/%' OR source LIKE 'yfinance/%/quarterly')",
        (symbol, as_of_str),
    ).fetchall())
    bank = tuple(row[0] for row in connection.execute(
        "SELECT DISTINCT report_period FROM bank_financial_reports "
        "WHERE symbol=? AND public_date<=?",
        (symbol, as_of_str),
    ).fetchall())
    return analyze_quarter_continuity(bank if bank else corporate, required=8)


def _count_canonical_institutional_flows(
    connection: sqlite3.Connection, symbol: str, as_of: date
) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(DISTINCT trading_date) FROM institutional_flows "
            "WHERE symbol=? AND trading_date<=?",
            (symbol, as_of.isoformat()),
        ).fetchone()[0]
    )


def _point_in_time_gap_reason(
    statements: tuple[StatementRow, ...], promoted_count: int,
    readiness: QuarterContinuity,
) -> str | None:
    """Explain, for coverage visibility, why usable raw statement rows did not
    all reach the point-in-time canonical ``financial_reports`` table.

    Readiness requires the latest eight quarters to be contiguous. A raw count
    cannot distinguish a valid TTM comparison window from a history with gaps.
    """
    gap_counts: dict[str, int] = {}
    for row in statements:
        gap = corporate_promotion_gap(row)
        if gap is not None:
            gap_counts[gap] = gap_counts.get(gap, 0) + 1
    detail = "; ".join(
        f"{reason} ({count} period(s))" for reason, count in sorted(gap_counts.items())
    )
    if not readiness.ready:
        if readiness.expected:
            continuity = "missing contiguous quarters: " + ", ".join(readiness.missing)
        else:
            continuity = "no valid quarterly reports available"
        if detail:
            continuity += f"; {promoted_count}/{len(statements)} raw period(s) promoted - {detail}"
        return continuity
    if detail:
        return (
            "READY FOR ASMF (8 quarters available; contiguous "
            f"{readiness.expected[0]} through {readiness.expected[-1]}); "
            f"{promoted_count}/{len(statements)} raw period(s) promoted - {detail}"
        )
    return None


def _reconcile_yfinance_canonical_snapshot(
    connection: sqlite3.Connection,
    symbol: str,
    staging_source: str,
    canonical_source: str,
    promoted_periods: tuple[str, ...],
) -> None:
    """Remove legacy Yahoo canonical rows absent from the quarterly snapshot.

    Older code stored annual Yahoo frames as Q4 rows. Their frequency cannot be
    reconstructed after persistence, so retaining source-owned rows that the
    corrected quarterly-only fetch no longer supplies would keep contaminated
    ASMF inputs alive. Removing uncertain rows is the fail-closed repair.
    """
    conditions = "symbol=? AND source=?"
    parameters: list[object] = [symbol, canonical_source]
    if promoted_periods:
        placeholders = ",".join("?" for _ in promoted_periods)
        conditions += f" AND report_period NOT IN ({placeholders})"
        parameters.extend(promoted_periods)
    with connection:
        connection.execute(
            "DELETE FROM financial_reports WHERE symbol=? "
            "AND source LIKE 'yfinance/%' AND source<>?",
            (symbol, canonical_source),
        )
        connection.execute(f"DELETE FROM financial_reports WHERE {conditions}", parameters)
        staging_conditions = "symbol=? AND source=?"
        staging_parameters: list[object] = [symbol, staging_source]
        if promoted_periods:
            placeholders = ",".join("?" for _ in promoted_periods)
            staging_conditions += f" AND period NOT IN ({placeholders})"
            staging_parameters.extend(promoted_periods)
        connection.execute(
            "UPDATE automated_financial_statements SET promoted_to_canonical=0 "
            f"WHERE {staging_conditions}",
            staging_parameters,
        )


def _has_preferred_canonical_source(
    connection: sqlite3.Connection, symbol: str, period: str
) -> bool:
    row = connection.execute(
        "SELECT source FROM financial_reports "
        "WHERE symbol=? AND report_period=? AND consolidated=1",
        (symbol, period),
    ).fetchone()
    if row is None:
        return False
    return not str(row["source"]).lower().startswith("yfinance/")


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    symbol: str
    dataset: str
    result: RefreshResult
    provider: str | None = None
    provider_source: str | None = None
    rows_stored: int = 0
    rows_promoted: int = 0
    error_reason: str | None = None
    coverage: CoverageStatus | None = None


def refresh_financials(
    connection: sqlite3.Connection,
    chain: ProviderChain,
    symbol: str,
    *,
    exchange: str | None = None,
    force: bool = False,
    refresh_interval_seconds: float = DEFAULT_FINANCIALS_REFRESH_INTERVAL_SECONDS,
    now: datetime | None = None,
) -> RefreshOutcome:
    """Fetch, stage, and conditionally promote statements for one symbol."""
    symbol = symbol.strip().upper()
    stamp = now or datetime.now(timezone.utc)

    if not force:
        existing = load_coverage(connection, symbol, "FINANCIALS")
        if existing is not None and not coverage_is_stale(
            existing, refresh_interval_seconds, now=stamp
        ):
            return RefreshOutcome(
                symbol=symbol, dataset="FINANCIALS", result=RefreshResult.SKIPPED_FRESH,
                provider=existing.provider, provider_source=existing.provider_source,
                coverage=existing,
            )

    result = chain.fetch_financials(symbol, exchange=exchange)

    if result.status is ProviderStatus.ERROR:
        coverage = record_coverage(connection, symbol, "FINANCIALS", result, now=stamp)
        return RefreshOutcome(
            symbol=symbol, dataset="FINANCIALS", result=RefreshResult.FAILED,
            provider=result.provider, provider_source=result.provider_source,
            error_reason=result.error_reason, coverage=coverage,
        )
    if not result.status.usable:
        coverage = record_coverage(connection, symbol, "FINANCIALS", result, now=stamp)
        return RefreshOutcome(
            symbol=symbol, dataset="FINANCIALS", result=RefreshResult.MISSING,
            provider=result.provider, provider_source=result.provider_source,
            error_reason=result.error_reason, coverage=coverage,
        )

    promoted_reports = []
    canonical_source = (
        f"{result.provenance}/quarterly"
        if result.provider.lower() == "yfinance"
        else result.provenance
    )
    for row in result.statements:
        promotable = promote_corporate_statement(row, source=canonical_source)
        if (
            promotable is not None
            and result.provider.lower() == "yfinance"
            and _has_preferred_canonical_source(connection, row.symbol, row.period)
        ):
            promotable = None
        upsert_automated_statement(
            connection, row, provider=result.provider,
            provider_source=result.provider_source,
            promoted=promotable is not None, now=stamp,
        )
        if promotable is not None:
            promoted_reports.append(promotable)
    if promoted_reports:
        upsert_financial_reports(connection, promoted_reports)
    if result.provider.lower() == "yfinance":
        _reconcile_yfinance_canonical_snapshot(
            connection,
            symbol,
            result.provenance,
            canonical_source,
            tuple(report.report_period for report in promoted_reports),
        )

    readiness = _canonical_financial_readiness(connection, symbol, stamp.date())
    gap_reason = _point_in_time_gap_reason(
        result.statements, len(promoted_reports), readiness
    )

    coverage_status = "READY" if readiness.ready else "PARTIAL"

    error_reason = gap_reason or result.error_reason
    coverage = record_attempt(
        connection, symbol, "FINANCIALS", coverage_status,
        provider=result.provider, provider_source=result.provider_source,
        error_reason=error_reason, now=stamp,
    )

    outcome = (
        RefreshResult.SUCCESS if result.status is ProviderStatus.AVAILABLE
        else RefreshResult.PARTIAL
    )
    return RefreshOutcome(
        symbol=symbol, dataset="FINANCIALS", result=outcome,
        provider=result.provider, provider_source=result.provider_source,
        rows_stored=len(result.statements), rows_promoted=len(promoted_reports),
        error_reason=gap_reason, coverage=coverage,
    )


def refresh_institutional_flow(
    connection: sqlite3.Connection,
    chain: ProviderChain,
    symbol: str,
    *,
    exchange: str | None = None,
    force: bool = False,
    lookback_days: int = 30,
    refresh_interval_seconds: float = DEFAULT_INSTITUTIONAL_REFRESH_INTERVAL_SECONDS,
    now: datetime | None = None,
) -> RefreshOutcome:
    """Fetch and persist foreign/proprietary flow for one symbol."""
    symbol = symbol.strip().upper()
    stamp = now or datetime.now(timezone.utc)

    if not force:
        existing = load_coverage(connection, symbol, "INSTITUTIONAL")
        if existing is not None and not coverage_is_stale(
            existing, refresh_interval_seconds, now=stamp
        ):
            return RefreshOutcome(
                symbol=symbol, dataset="INSTITUTIONAL", result=RefreshResult.SKIPPED_FRESH,
                provider=existing.provider, provider_source=existing.provider_source,
                coverage=existing,
            )

    result = chain.fetch_institutional_flow(symbol, exchange=exchange, lookback_days=lookback_days)

    if result.status is ProviderStatus.ERROR:
        coverage = record_coverage(connection, symbol, "INSTITUTIONAL", result, now=stamp)
        return RefreshOutcome(
            symbol=symbol, dataset="INSTITUTIONAL", result=RefreshResult.FAILED,
            provider=result.provider, provider_source=result.provider_source,
            error_reason=result.error_reason, coverage=coverage,
        )
    if not result.status.usable:
        coverage = record_coverage(connection, symbol, "INSTITUTIONAL", result, now=stamp)
        return RefreshOutcome(
            symbol=symbol, dataset="INSTITUTIONAL", result=RefreshResult.MISSING,
            provider=result.provider, provider_source=result.provider_source,
            error_reason=result.error_reason, coverage=coverage,
        )

    flows = [flow_row_to_institutional_flow(row, source=result.provenance) for row in result.flows]
    if flows:
        upsert_institutional_flows(connection, flows)

    canonical_flow_count = _count_canonical_institutional_flows(connection, symbol, stamp.date())
    # If the database has >= 5 trading sessions, ASMF institutional flow is satisfied (READY).
    if canonical_flow_count >= 5:
        coverage_status = "READY"
    else:
        coverage_status = _COVERAGE_STATUS_FROM_PROVIDER_STATUS[result.status]

    coverage = record_attempt(
        connection, symbol, "INSTITUTIONAL", coverage_status,
        provider=result.provider, provider_source=result.provider_source,
        error_reason=result.error_reason, now=stamp,
    )

    outcome = (
        RefreshResult.SUCCESS if result.status is ProviderStatus.AVAILABLE
        else RefreshResult.PARTIAL
    )
    return RefreshOutcome(
        symbol=symbol, dataset="INSTITUTIONAL", result=outcome,
        provider=result.provider, provider_source=result.provider_source,
        rows_stored=len(flows), rows_promoted=len(flows), coverage=coverage,
    )

