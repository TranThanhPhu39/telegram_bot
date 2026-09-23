"""yfinance adapter — fallback only, never the default for Vietnamese equities.

Yahoo's coverage of HOSE/HNX/UPCoM is incomplete and its suffix convention is
not uniform, so this adapter derives candidate tickers from the exchange
recorded in the ``symbols`` table rather than assuming ``SYMBOL.VN`` always
exists. When no candidate resolves it returns MISSING: no crash, no retry loop,
no fabricated values, and no silent mapping onto the wrong exchange.

Yahoo never supplies Vietnamese announcement dates, so every row produced here
has ``public_date=None``. The shared point-in-time adapter applies only the
documented ``period_end + 45 days`` estimate; it never exposes the period end
itself as a publication date.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone
import importlib
import logging

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

#: Yahoo suffixes by the exchange codes this project stores.
EXCHANGE_SUFFIXES: dict[str, tuple[str, ...]] = {
    "HOSE": (".VN",),
    "HSX": (".VN",),
    "HNX": (".HN", ".VN"),
    "UPCOM": (".VN",),
    "UPCOM2": (".VN",),
}
#: Used only when the database has no exchange for the symbol.
UNKNOWN_EXCHANGE_SUFFIXES = (".VN", ".HN")

#: Yahoo statement row labels mapped onto canonical fields.
YAHOO_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("totalrevenue", "operatingrevenue"),
    "gross_profit": ("grossprofit",),
    "operating_profit": ("operatingincome", "ebit"),
    "net_income": ("netincome", "netincomecommonstockholders"),
    "net_income_parent": ("netincomecommonstockholders",),
    "total_assets": ("totalassets",),
    "total_equity": ("stockholdersequity", "totalequitygrossminorityinterest"),
    "total_liabilities": ("totalliabilitiesnetminorityinterest", "totalliabilities"),
    "cash": ("cashandcashequivalents", "cashcashequivalentsandshortterminvestments"),
    "short_term_debt": ("currentdebt", "shorttermdebt"),
    "long_term_debt": ("longtermdebt",),
    "operating_cash_flow": ("operatingcashflow", "cashflowfromcontinuingoperatingactivities"),
    "capex": ("capitalexpenditure",),
}


def _normalize_label(label: object) -> str:
    return "".join(ch for ch in str(label).strip().lower() if ch.isalnum())


def candidate_tickers(symbol: str, exchange: str | None) -> tuple[str, ...]:
    """Return Yahoo ticker candidates for a symbol, most likely first."""
    symbol = symbol.strip().upper()
    if not symbol:
        return ()
    key = (exchange or "").strip().upper()
    suffixes = EXCHANGE_SUFFIXES.get(key, UNKNOWN_EXCHANGE_SUFFIXES if not key else ())
    if not suffixes:
        # A known-but-unmapped exchange must not be guessed onto ".VN".
        LOGGER.info("no Yahoo suffix mapping for exchange %s", key)
        return ()
    return tuple(f"{symbol}{suffix}" for suffix in suffixes)


class YFinanceProvider(FundamentalProvider):
    """Fallback provider. Only consulted after the primary chain gives up."""

    name = "yfinance"

    def __init__(self, *, module: object | None = None, enabled: bool = True) -> None:
        self._module = module
        self._module_loaded = module is not None
        self._enabled = enabled

    def _load_module(self) -> object | None:
        if not self._enabled:
            return None
        if not self._module_loaded:
            self._module_loaded = True
            try:
                self._module = importlib.import_module("yfinance")
            except Exception as error:  # pragma: no cover - depends on install
                LOGGER.info("yfinance unavailable: %s", type(error).__name__)
                self._module = None
        return self._module

    def available(self) -> bool:
        return self._load_module() is not None

    def fetch_financials(self, symbol: str, *, exchange: str | None = None) -> ProviderResult:
        symbol = symbol.strip().upper()
        module = self._load_module()
        if module is None:
            return ProviderResult.missing(
                symbol, "FINANCIALS", self.name,
                reason="yfinance is disabled or not installed",
                attempted=("import yfinance",),
            )
        tickers = candidate_tickers(symbol, exchange)
        if not tickers:
            return ProviderResult.missing(
                symbol, "FINANCIALS", self.name,
                reason=f"no Yahoo ticker mapping for exchange {exchange or 'UNKNOWN'}",
            )
        attempted: list[str] = []
        last_error: str | None = None
        for ticker in tickers:
            attempted.append(ticker)
            try:
                handle = module.Ticker(ticker)  # type: ignore[attr-defined]
                merged = self._collect(handle)
            except Exception as error:
                last_error = f"{type(error).__name__} for {ticker}"
                LOGGER.debug("yfinance failed: %s", last_error)
                continue
            rows = self._build_rows(symbol, merged)
            if rows:
                complete = all(
                    row.get("revenue") is not None and row.get("total_equity") is not None
                    for row in rows
                )
                return ProviderResult(
                    symbol=symbol, dataset="FINANCIALS", provider=self.name,
                    status=ProviderStatus.AVAILABLE if complete else ProviderStatus.PARTIAL,
                    provider_source=ticker, retrieved_at=datetime.now(timezone.utc),
                    statements=rows, attempted=tuple(attempted),
                )
        if last_error is not None:
            return ProviderResult.failed(
                symbol, "FINANCIALS", self.name, last_error, attempted=tuple(attempted),
            )
        return ProviderResult.missing(
            symbol, "FINANCIALS", self.name,
            reason="Yahoo returned no financial statements",
            attempted=tuple(attempted),
        )

    def _collect(self, handle: object) -> dict[str, dict[str, float | None]]:
        """Merge only Yahoo quarterly frames into period-keyed buckets.

        Annual frames use year-end dates that are indistinguishable from Q4
        after date-to-quarter normalization. Reading ``financials`` or
        ``balance_sheet`` here would therefore contaminate quarterly ASMF data.
        """
        merged: dict[str, dict[str, float | None]] = {}
        for attribute in (
            "quarterly_financials", "quarterly_balance_sheet", "quarterly_cashflow",
            "quarterly_income_stmt",
        ):
            frame = getattr(handle, attribute, None)
            if frame is None:
                continue
            records = getattr(frame, "to_dict", None)
            data = frame.to_dict() if callable(records) else frame
            if not isinstance(data, dict):
                continue
            for column, series in data.items():
                period = _period_from_column(column)
                if period is None or not isinstance(series, dict):
                    continue
                bucket = merged.setdefault(period, {})
                labels = {_normalize_label(key): key for key in series}
                for field_name, aliases in YAHOO_ALIASES.items():
                    if bucket.get(field_name) is not None:
                        continue
                    for alias in aliases:
                        if alias in labels:
                            value = clean_number(series.get(labels[alias]))
                            if value is not None:
                                bucket[field_name] = value
                            break
        return merged

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
                # Yahoo never carries a Vietnamese announcement date.
                rows.append(StatementRow(
                    symbol=symbol, period=period, public_date=None,
                    consolidated=True, values=values,
                ))
            except (ValueError, TypeError) as error:
                LOGGER.debug("rejected Yahoo row %s %s: %s", symbol, period, error)
        return tuple(rows)

    def fetch_institutional_flow(
        self, symbol: str, *, exchange: str | None = None, lookback_days: int = 30
    ) -> ProviderResult:
        """Yahoo publishes no Vietnamese foreign/proprietary desk flow."""
        return ProviderResult.missing(
            symbol.strip().upper(), "INSTITUTIONAL", self.name,
            reason="Yahoo does not publish Vietnamese institutional flow",
        )


def _period_from_column(column: object) -> str | None:
    if isinstance(column, datetime):
        column = column.date()
    if isinstance(column, date):
        return f"{column.year:04d}Q{(column.month - 1) // 3 + 1}"
    text = str(column).strip()
    if len(text) >= 10:
        try:
            parsed = date.fromisoformat(text[:10])
        except ValueError:
            return normalize_period(text)
        return f"{parsed.year:04d}Q{(parsed.month - 1) // 3 + 1}"
    return normalize_period(text)
