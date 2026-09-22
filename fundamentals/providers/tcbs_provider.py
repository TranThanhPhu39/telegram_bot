"""TCBS adapter — third source for Vietnamese financial statements.

Hits TCBS's public "TCAnalysis" statement endpoints directly over HTTP,
independent of the ``vnstock`` package (see ``vnstock_provider.py``, which
already tried VNStock's VCI/KBS backends and is the primary source). This
adapter exists because that primary chain plus the yfinance fallback were
both found to return raw/unusable data for a meaningful share of tickers
(Issue 9); TCBS's own analysis endpoint gives a third, independently-sourced
read on the same statements.

Endpoint schema notes / honesty boundaries (read before changing aliases):
  * The endpoint returns one JSON array per statement type, one row per
    fiscal quarter, with plain ``year``/``quarter`` integer fields and no
    announcement/publication date. Exactly like ``yfinance_provider.py``,
    every row therefore has ``public_date=None`` — callers must treat that
    as "unavailable", never substitute the period end, or point-in-time
    reads would silently gain look-ahead.
  * The income-statement field names below (``revenue``, ``grossProfit``,
    ``operationProfit``, ``postTaxProfit``, ``shareHolderIncome``) and the
    balance-sheet ``cash`` field are well attested across public examples of
    this endpoint and are mapped with confidence.
  * The remaining balance-sheet totals (``asset``/``debt``/``equity`` and
    their short/long splits) are mapped from the most common shape observed
    for non-bank issuers, but TCBS does not publish a schema reference, so
    the labels are probed as best-effort aliases rather than assumed exact.
  * The cash-flow endpoint on this source only exposes coarse buckets
    (``investCost``, ``fromInvest``, ``fromFinancial``, ``fromSale``,
    ``freeCashFlow``) with no documented definition tying them to
    ``operating_cash_flow`` or ``capex`` as this project defines them.
    Guessing that mapping risks silently mislabeling cash-flow rows, so
    ``operating_cash_flow`` and ``capex`` are deliberately left unmapped
    here — the same "unmapped beats guessed" rule ``vnstock_provider.py``
    applies to NPL/CAR. Live acceptance should confirm whether the balance
    -sheet totals resolve correctly for a sample of real tickers; anything
    that does not match should be moved from "best-effort" to "unmapped"
    the same way, rather than patched into matching.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import logging

import requests

from fundamentals.providers.base import (
    STATEMENT_FIELDS,
    FundamentalProvider,
    ProviderResult,
    ProviderStatus,
    StatementRow,
    clean_number,
    normalize_period,
)

LOGGER = logging.getLogger(__name__)

TCBS_BASE_URL = "https://apipubaws.tcbs.com.vn/tcanalysis/v1/finance"
DEFAULT_TIMEOUT_SECONDS = 10.0

#: (report_type, query yearly=0 -> quarterly)
REPORT_TYPES: tuple[str, ...] = ("incomestatement", "balancesheet", "cashflow")

#: High-confidence income-statement fields, attested across public samples
#: of this endpoint.
INCOME_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue",),
    "gross_profit": ("grossprofit",),
    "operating_profit": ("operationprofit",),
    "net_income": ("posttaxprofit",),
    "net_income_parent": ("shareholderincome",),
}

#: Best-effort balance-sheet totals — see module docstring. ``cash`` is
#: high-confidence; the rest are probed aliases pending live confirmation.
BALANCE_ALIASES: dict[str, tuple[str, ...]] = {
    "cash": ("cash",),
    "total_assets": ("asset", "totalasset"),
    "total_equity": ("equity", "totalequity", "ownersequity"),
    "total_liabilities": ("debt", "totalliabilities", "totaldebt"),
    "short_term_debt": ("shortdebt", "shorttermdebt"),
    "long_term_debt": ("longdebt", "longtermdebt"),
}

#: Deliberately empty: see "cash-flow endpoint" note in the module docstring.
#: operating_cash_flow and capex are NOT mapped from this source.
CASHFLOW_ALIASES: dict[str, tuple[str, ...]] = {}


def _normalize_label(label: object) -> str:
    return "".join(character for character in str(label).strip().lower() if character.isalnum())


def _match_field(row: Mapping[str, object], aliases: Sequence[str]) -> object | None:
    normalized = {_normalize_label(key): value for key, value in row.items()}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


class TCBSProvider(FundamentalProvider):
    """Third source for FINANCIALS, tried after VNStock and before yfinance.

    Never consulted for INSTITUTIONAL flow: this adapter is scoped to
    financial statements only (Issue 9's ask), so it honestly reports
    MISSING for that dataset rather than reaching into unrelated TCBS
    endpoints outside its reviewed scope.
    """

    name = "TCBS"

    def __init__(
        self,
        *,
        session: object | None = None,
        enabled: bool = True,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._session = session if session is not None else requests
        self._enabled = enabled
        self._timeout_seconds = timeout_seconds

    def available(self) -> bool:
        return self._enabled

    def _fetch_report(self, symbol: str, report_type: str) -> list[dict[str, object]]:
        """One statement endpoint, quarterly. Raises on any transport error."""
        url = f"{TCBS_BASE_URL}/{symbol}/{report_type}"
        response = self._session.get(
            url,
            params={"yearly": 0, "isAll": "true"},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"unexpected {report_type} payload shape: {type(payload).__name__}")
        return [row for row in payload if isinstance(row, dict)]

    def fetch_financials(self, symbol: str, *, exchange: str | None = None) -> ProviderResult:
        symbol = symbol.strip().upper()
        if not self._enabled:
            return ProviderResult.missing(
                symbol, "FINANCIALS", self.name,
                reason="TCBS provider disabled", attempted=(),
            )

        merged: dict[str, dict[str, float | None]] = {}
        attempted: list[str] = []
        errors: list[str] = []

        for report_type, aliases in (
            ("incomestatement", INCOME_ALIASES),
            ("balancesheet", BALANCE_ALIASES),
            ("cashflow", CASHFLOW_ALIASES),
        ):
            try:
                rows = self._fetch_report(symbol, report_type)
            except Exception as error:  # a bad ticker/endpoint must not abort the batch
                message = f"{report_type}:{type(error).__name__}"
                attempted.append(message)
                errors.append(message)
                LOGGER.debug("TCBS %s failed for %s: %s", report_type, symbol, error)
                continue
            attempted.append(f"{report_type}:ok")
            if not aliases:
                continue
            for row in rows:
                year = clean_number(_match_field(row, ("year",)))
                quarter = clean_number(_match_field(row, ("quarter",)))
                if year is None or not quarter:  # quarter 0 rows are annual roll-ups; skip
                    continue
                period = normalize_period((year, quarter))
                if period is None:
                    continue
                bucket = merged.setdefault(period, {})
                for field_name, field_aliases in aliases.items():
                    if bucket.get(field_name) is not None:
                        continue
                    value = clean_number(_match_field(row, field_aliases))
                    if value is not None:
                        bucket[field_name] = value

        if len(errors) == len(REPORT_TYPES):
            return ProviderResult.failed(
                symbol, "FINANCIALS", self.name,
                "all TCBS statement endpoints failed: " + "; ".join(errors),
                attempted=tuple(attempted),
            )

        rows = self._build_rows(symbol, merged)
        if not rows:
            return ProviderResult.missing(
                symbol, "FINANCIALS", self.name,
                reason="TCBS returned no usable statement rows",
                attempted=tuple(attempted),
            )
        complete = all(
            row.get("revenue") is not None and row.get("total_equity") is not None
            for row in rows
        )
        return ProviderResult(
            symbol=symbol, dataset="FINANCIALS", provider=self.name,
            status=ProviderStatus.AVAILABLE if complete else ProviderStatus.PARTIAL,
            provider_source="TCAnalysis", retrieved_at=datetime.now(timezone.utc),
            statements=rows, attempted=tuple(attempted),
        )

    def _build_rows(
        self, symbol: str, merged: dict[str, dict[str, float | None]]
    ) -> tuple[StatementRow, ...]:
        rows: list[StatementRow] = []
        for period in sorted(merged):
            values = {
                name: value for name, value in merged[period].items()
                if name in STATEMENT_FIELDS
            }
            if not any(value is not None for value in values.values()):
                continue
            try:
                # TCBS's public endpoint carries no announcement date.
                rows.append(StatementRow(
                    symbol=symbol, period=period, public_date=None,
                    consolidated=True, values=values,
                ))
            except (ValueError, TypeError) as error:
                LOGGER.debug("rejected TCBS row %s %s: %s", symbol, period, error)
        return tuple(rows)

    def fetch_institutional_flow(
        self, symbol: str, *, exchange: str | None = None, lookback_days: int = 30
    ) -> ProviderResult:
        """Out of scope: this adapter only covers financial statements."""
        return ProviderResult.missing(
            symbol.strip().upper(), "INSTITUTIONAL", self.name,
            reason="TCBS adapter is scoped to FINANCIALS only",
        )
