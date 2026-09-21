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

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import sqlite3

from asmf_data.store import upsert_financial_reports, upsert_institutional_flows
from fundamentals.adapters import flow_row_to_institutional_flow, promote_corporate_statement
from fundamentals.coverage_store import (
    CoverageStatus,
    coverage_is_stale,
    load_coverage,
    record_coverage,
    upsert_automated_statement,
)
from fundamentals.providers.base import ProviderResult, ProviderStatus
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
    coverage = record_coverage(connection, symbol, "FINANCIALS", result, now=stamp)

    if result.status is ProviderStatus.ERROR:
        return RefreshOutcome(
            symbol=symbol, dataset="FINANCIALS", result=RefreshResult.FAILED,
            provider=result.provider, provider_source=result.provider_source,
            error_reason=result.error_reason, coverage=coverage,
        )
    if not result.status.usable:
        return RefreshOutcome(
            symbol=symbol, dataset="FINANCIALS", result=RefreshResult.MISSING,
            provider=result.provider, provider_source=result.provider_source,
            error_reason=result.error_reason, coverage=coverage,
        )

    promoted_reports = []
    for row in result.statements:
        promotable = promote_corporate_statement(row, source=result.provenance)
        upsert_automated_statement(
            connection, row, provider=result.provider,
            provider_source=result.provider_source,
            promoted=promotable is not None, now=stamp,
        )
        if promotable is not None:
            promoted_reports.append(promotable)
    if promoted_reports:
        upsert_financial_reports(connection, promoted_reports)

    outcome = (
        RefreshResult.SUCCESS if result.status is ProviderStatus.AVAILABLE
        else RefreshResult.PARTIAL
    )
    return RefreshOutcome(
        symbol=symbol, dataset="FINANCIALS", result=outcome,
        provider=result.provider, provider_source=result.provider_source,
        rows_stored=len(result.statements), rows_promoted=len(promoted_reports),
        coverage=coverage,
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
    coverage = record_coverage(connection, symbol, "INSTITUTIONAL", result, now=stamp)

    if result.status is ProviderStatus.ERROR:
        return RefreshOutcome(
            symbol=symbol, dataset="INSTITUTIONAL", result=RefreshResult.FAILED,
            provider=result.provider, provider_source=result.provider_source,
            error_reason=result.error_reason, coverage=coverage,
        )
    if not result.status.usable:
        return RefreshOutcome(
            symbol=symbol, dataset="INSTITUTIONAL", result=RefreshResult.MISSING,
            provider=result.provider, provider_source=result.provider_source,
            error_reason=result.error_reason, coverage=coverage,
        )

    flows = [flow_row_to_institutional_flow(row, source=result.provenance) for row in result.flows]
    if flows:
        upsert_institutional_flows(connection, flows)

    outcome = (
        RefreshResult.SUCCESS if result.status is ProviderStatus.AVAILABLE
        else RefreshResult.PARTIAL
    )
    return RefreshOutcome(
        symbol=symbol, dataset="INSTITUTIONAL", result=outcome,
        provider=result.provider, provider_source=result.provider_source,
        rows_stored=len(flows), rows_promoted=len(flows), coverage=coverage,
    )
