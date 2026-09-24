"""Vietcap IQ quarterly financial-statement adapter.

The endpoint is an observed Vietcap IQ frontend interface, not a documented
public API.  Keep every provider-specific code in this module and fail closed
when the wrapper or accounting identities no longer match the observed schema.

Verified non-bank mappings from the BALANCE_SHEET and INCOME_STATEMENT payloads:

* ``isa3``  - net revenue
* ``isa20`` - total profit after tax
* ``isa22`` - profit after tax attributable to parent shareholders
* ``bsa53`` - total assets
* ``bsa54`` - total liabilities
* ``bsa55`` - current liabilities
* ``bsa67`` - non-current liabilities
* ``bsa78`` - total equity

The identities ``bsa55 + bsa67 == bsa54`` and
``bsa54 + bsa78 == bsa53`` are revalidated per row.  Rows that fail are not
promoted as complete evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import logging
import math
import re
from typing import Any

import requests

from fundamentals.providers.base import (
    FundamentalProvider,
    ProviderResult,
    ProviderStatus,
    StatementRow,
    clean_number,
    normalize_period,
)

LOGGER = logging.getLogger(__name__)

VIETCAP_IQ_BASE_URL = "https://iq.vietcap.com.vn"
VIETCAP_IQ_FRONTEND_URL = "https://trading.vietcap.com.vn"
FINANCIAL_STATEMENT_PATH = (
    "/api/iq-insight-service/v1/company/{symbol}/financial-statement"
)
SECTIONS = ("BALANCE_SHEET", "INCOME_STATEMENT")
DEFAULT_TIMEOUT_SECONDS = 15.0
_SYMBOL_PATTERN = re.compile(r"[A-Z0-9]+\Z")


class _HttpResponse:
    status_code: int

    def raise_for_status(self) -> None: ...
    def json(self) -> Any: ...


def _parse_public_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1.0)


class VietcapIQFinancialProvider(FundamentalProvider):
    """Acquire verified non-bank quarterly statements from Vietcap IQ."""

    name = "VietcapIQ"

    def __init__(
        self,
        *,
        session: object | None = None,
        enabled: bool = True,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        authorization: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._session = session if session is not None else requests.Session()
        self._enabled = enabled
        self._timeout_seconds = timeout_seconds
        self._authorization = (authorization or "").strip()

    def available(self) -> bool:
        return self._enabled

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Origin": VIETCAP_IQ_FRONTEND_URL,
            "Referer": f"{VIETCAP_IQ_FRONTEND_URL}/iq/",
            "User-Agent": "Mozilla/5.0",
        }
        if self._authorization:
            headers["Authorization"] = self._authorization
        return headers

    def _fetch_section(self, symbol: str, section: str) -> list[dict[str, object]]:
        url = VIETCAP_IQ_BASE_URL + FINANCIAL_STATEMENT_PATH.format(symbol=symbol)
        response: _HttpResponse = self._session.get(  # type: ignore[assignment,union-attr]
            url,
            params={"section": section},
            headers=self._headers(),
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("Vietcap IQ response must be an object")
        if payload.get("successful") is not True or payload.get("status") != 200:
            raise ValueError("Vietcap IQ response wrapper reports failure")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise ValueError("Vietcap IQ response has no data object")
        quarters = data.get("quarters")
        if not isinstance(quarters, list):
            raise ValueError("Vietcap IQ response has no quarters array")
        return [dict(row) for row in quarters if isinstance(row, Mapping)]

    @staticmethod
    def _period(row: Mapping[str, object]) -> str | None:
        year = clean_number(row.get("yearReport"))
        quarter = clean_number(row.get("lengthReport"))
        if year is None or quarter is None:
            return None
        return normalize_period((year, quarter))

    @staticmethod
    def _balance_values(row: Mapping[str, object]) -> dict[str, float | None]:
        assets = clean_number(row.get("bsa53"))
        liabilities = clean_number(row.get("bsa54"))
        current = clean_number(row.get("bsa55"))
        non_current = clean_number(row.get("bsa67"))
        equity = clean_number(row.get("bsa78"))
        identities_valid = (
            None not in (assets, liabilities, current, non_current, equity)
            and _close(current + non_current, liabilities)  # type: ignore[operator]
            and _close(liabilities + equity, assets)  # type: ignore[operator]
        )
        if not identities_valid:
            LOGGER.warning("Rejected Vietcap IQ balance mapping: accounting identity failed")
            return {}
        return {
            "total_assets": assets,
            "total_liabilities": liabilities,
            "short_term_debt": current,
            "long_term_debt": non_current,
            "total_equity": equity,
        }

    @staticmethod
    def _income_values(row: Mapping[str, object]) -> dict[str, float | None]:
        revenue = clean_number(row.get("isa3"))
        total_net_income = clean_number(row.get("isa20"))
        parent_net_income = clean_number(row.get("isa22"))
        minority_interest = clean_number(row.get("isa21"))
        if (
            total_net_income is not None
            and parent_net_income is not None
            and minority_interest is not None
            and not _close(parent_net_income + minority_interest, total_net_income)
        ):
            LOGGER.warning("Rejected Vietcap IQ income mapping: profit identity failed")
            return {}
        return {
            "revenue": revenue,
            "net_income": total_net_income,
            "net_income_parent": parent_net_income,
        }

    def fetch_financials(
        self, symbol: str, *, exchange: str | None = None
    ) -> ProviderResult:
        symbol = symbol.strip().upper()
        if not self._enabled:
            return ProviderResult.missing(
                symbol, "FINANCIALS", self.name,
                reason="Vietcap IQ financial provider disabled",
            )
        if not symbol or _SYMBOL_PATTERN.fullmatch(symbol) is None:
            return ProviderResult.missing(
                symbol, "FINANCIALS", self.name, reason="invalid stock symbol"
            )

        attempted: list[str] = []
        sections: dict[str, list[dict[str, object]]] = {}
        for section in SECTIONS:
            try:
                sections[section] = self._fetch_section(symbol, section)
            except Exception as error:
                attempted.append(f"{section}:{type(error).__name__}")
                LOGGER.warning(
                    "Vietcap IQ %s failed for %s: %s",
                    section, symbol, type(error).__name__,
                )
            else:
                attempted.append(f"{section}:ok")

        if not sections:
            return ProviderResult.failed(
                symbol, "FINANCIALS", self.name,
                "Vietcap IQ statement endpoints failed",
                attempted=tuple(attempted),
            )

        merged: dict[str, dict[str, object]] = {}
        public_dates: dict[str, date] = {}
        for section, rows in sections.items():
            for raw in rows:
                period = self._period(raw)
                if period is None:
                    continue
                values = (
                    self._balance_values(raw)
                    if section == "BALANCE_SHEET"
                    else self._income_values(raw)
                )
                if values:
                    merged.setdefault(period, {}).update(values)
                public_date = _parse_public_date(raw.get("publicDate"))
                if public_date is not None:
                    existing = public_dates.get(period)
                    if existing is not None and existing != public_date:
                        LOGGER.warning(
                            "Vietcap IQ publicDate mismatch for %s %s", symbol, period
                        )
                        merged.pop(period, None)
                        public_dates.pop(period, None)
                        continue
                    public_dates[period] = public_date

        statements = tuple(
            StatementRow(
                symbol=symbol,
                period=period,
                public_date=public_dates.get(period),
                consolidated=True,
                values={name: clean_number(value) for name, value in merged[period].items()},
                public_date_source="actual" if period in public_dates else None,
            )
            for period in sorted(merged)
            if merged[period]
        )
        if not statements:
            return ProviderResult.missing(
                symbol, "FINANCIALS", self.name,
                reason="Vietcap IQ returned no verified quarterly rows",
                attempted=tuple(attempted),
            )
        complete = all(
            row.get("revenue") is not None
            and row.get("net_income_parent") is not None
            and row.get("total_equity") is not None
            and row.get("short_term_debt") is not None
            and row.get("long_term_debt") is not None
            for row in statements
        )
        return ProviderResult(
            symbol=symbol,
            dataset="FINANCIALS",
            provider=self.name,
            provider_source="IQ/financial-statement",
            status=ProviderStatus.AVAILABLE if complete else ProviderStatus.PARTIAL,
            retrieved_at=datetime.now(timezone.utc),
            statements=statements,
            attempted=tuple(attempted),
        )

    def fetch_institutional_flow(
        self, symbol: str, *, exchange: str | None = None, lookback_days: int = 30
    ) -> ProviderResult:
        return ProviderResult.missing(
            symbol.strip().upper(), "INSTITUTIONAL", self.name,
            reason="Vietcap IQ adapter is scoped to FINANCIALS only",
        )
