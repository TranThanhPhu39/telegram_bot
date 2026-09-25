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
* ``bsa55`` - current liabilities (identity check only)
* ``bsa56`` - short-term loans
* ``bsa67`` - non-current liabilities (identity check only)
* ``bsa71`` - long-term loans
* ``bsa78`` - total equity

The identities ``bsa55 + bsa67 == bsa54`` and
``bsa54 + bsa78 == bsa53`` are revalidated per row.  Rows that fail are not
promoted as complete evidence.

Verified bank mappings use the distinct FiinGroup bank namespaces present in
the same payload: ``isb27`` (net interest income), ``isa22`` (parent profit),
``bsa78`` (equity), ``bsb104`` (gross customer loans), and ``bsb105`` (the
negative loan-loss provision).  Bank income is cumulative year-to-date.

Verified securities mappings retain the common totals but require a populated
``bss``/``iss`` schema: ``isa3`` net operating revenue, ``isa22`` parent profit,
``bsa53`` assets, ``bsa54`` liabilities, ``bsa56``/``bsa71`` borrowings and
``bsa78`` equity. Securities rows are acquisition evidence only; downstream
promotion policy decides whether a strategy model can consume them.
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
STATISTICS_FINANCIAL_PATH = (
    "/api/iq-insight-service/v1/company/{symbol}/statistics-financial"
)
SECTIONS = ("BALANCE_SHEET", "INCOME_STATEMENT")
DEFAULT_TIMEOUT_SECONDS = 15.0
_SYMBOL_PATTERN = re.compile(r"[A-Z0-9]+\Z")

AUTH_FAILURE = "AUTH_FAILURE"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"


class _AuthenticationFailure(RuntimeError):
    pass


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


def _profit_identity_valid(
    total: float | None, parent: float | None, minority: float | None
) -> bool:
    """Fiin payloads vary the minority-interest sign across issuers/periods."""
    return (
        total is None
        or parent is None
        or minority is None
        or _close(abs(total - parent), abs(minority))
    )


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
        if response.status_code in (401, 403):
            raise _AuthenticationFailure(f"HTTP {response.status_code}")
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

    def _fetch_statistics(self, symbol: str) -> list[dict[str, object]]:
        url = VIETCAP_IQ_BASE_URL + STATISTICS_FINANCIAL_PATH.format(symbol=symbol)
        response: _HttpResponse = self._session.get(  # type: ignore[assignment,union-attr]
            url,
            headers=self._headers(),
            timeout=self._timeout_seconds,
        )
        if response.status_code in (401, 403):
            raise _AuthenticationFailure(f"HTTP {response.status_code}")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("Vietcap IQ statistics response must be an object")
        if payload.get("successful") is not True or payload.get("status") != 200:
            raise ValueError("Vietcap IQ statistics wrapper reports failure")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Vietcap IQ statistics response has no data array")
        return [dict(row) for row in data if isinstance(row, Mapping)]

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
        current_liabilities = clean_number(row.get("bsa55"))
        short_term_loans = clean_number(row.get("bsa56"))
        non_current_liabilities = clean_number(row.get("bsa67"))
        long_term_loans = clean_number(row.get("bsa71"))
        equity = clean_number(row.get("bsa78"))
        identities_valid = (
            None not in (
                assets, liabilities, current_liabilities,
                non_current_liabilities, equity,
            )
            and _close(  # type: ignore[operator]
                current_liabilities + non_current_liabilities, liabilities
            )
            and _close(liabilities + equity, assets)  # type: ignore[operator]
        )
        if not identities_valid:
            LOGGER.warning("Rejected Vietcap IQ balance mapping: accounting identity failed")
            return {}
        return {
            "total_assets": assets,
            "total_liabilities": liabilities,
            # The canonical debt ratio means interest-bearing borrowings, not
            # all liabilities.  BSA55/BSA67 remain useful only for validating
            # the balance-sheet identity.
            "short_term_debt": short_term_loans,
            "long_term_debt": long_term_loans,
            "total_equity": equity,
        }

    @staticmethod
    def _income_values(row: Mapping[str, object]) -> dict[str, float | None]:
        revenue = clean_number(row.get("isa3"))
        total_net_income = clean_number(row.get("isa20"))
        parent_net_income = clean_number(row.get("isa22"))
        minority_interest = clean_number(row.get("isa21"))
        if not _profit_identity_valid(
            total_net_income, parent_net_income, minority_interest
        ):
            LOGGER.warning("Rejected Vietcap IQ income mapping: profit identity failed")
            return {}
        return {
            "revenue": revenue,
            "net_income": total_net_income,
            "net_income_parent": parent_net_income,
        }

    @staticmethod
    def _bank_balance_values(row: Mapping[str, object]) -> dict[str, float | None]:
        assets = clean_number(row.get("bsa53"))
        liabilities = clean_number(row.get("bsa54"))
        equity = clean_number(row.get("bsa78"))
        net_loans = clean_number(row.get("bsb103"))
        gross_loans = clean_number(row.get("bsb104"))
        provision = clean_number(row.get("bsb105"))
        valid = (
            None not in (assets, liabilities, equity, net_loans, gross_loans, provision)
            and _close(liabilities + equity, assets)  # type: ignore[operator]
            and _close(gross_loans + provision, net_loans)  # type: ignore[operator]
            and gross_loans > 0  # type: ignore[operator]
            and provision <= 0  # type: ignore[operator]
        )
        if not valid:
            LOGGER.warning("Rejected Vietcap IQ bank balance mapping: accounting identity failed")
            return {}
        return {
            "equity": equity,
            "gross_loans": gross_loans,
            "loan_loss_reserve": abs(provision),  # type: ignore[arg-type]
        }

    @staticmethod
    def _bank_income_values(row: Mapping[str, object]) -> dict[str, float | None]:
        interest_income = clean_number(row.get("isb25"))
        interest_expense = clean_number(row.get("isb26"))
        net_interest_income = clean_number(row.get("isb27"))
        total_net_income = clean_number(row.get("isa20"))
        minority_interest = clean_number(row.get("isa21"))
        parent_net_income = clean_number(row.get("isa22"))
        valid = (
            None not in (interest_income, interest_expense, net_interest_income)
            and _close(interest_income + interest_expense, net_interest_income)  # type: ignore[operator]
            and parent_net_income is not None
            and _profit_identity_valid(
                total_net_income, parent_net_income, minority_interest
            )
        )
        if not valid:
            LOGGER.warning("Rejected Vietcap IQ bank income mapping: accounting identity failed")
            return {}
        return {
            "net_interest_income": net_interest_income,
            "net_profit": parent_net_income,
        }

    @staticmethod
    def _bank_risk_ratios(
        rows: list[dict[str, object]],
    ) -> dict[str, dict[str, float | None]]:
        """Return only quarter-specific ratios with verified frontend semantics.

        ``quarter=5`` is Vietcap's annual series and is deliberately excluded;
        annual CAR must not masquerade as a Q4 disclosure. Zero CAR is the
        frontend's missing-value sentinel for quarters where it was not
        reported, so it remains ``None`` rather than becoming a real 0% ratio.
        """
        ratios: dict[str, dict[str, float | None]] = {}
        for row in rows:
            if str(row.get("ratioType") or "").upper() != "RATIO_TTM":
                continue
            year = clean_number(row.get("yearReport"))
            quarter = clean_number(row.get("quarter"))
            if (
                year is None or quarter is None
                or not year.is_integer() or not quarter.is_integer()
                or int(quarter) not in range(1, 5)
            ):
                continue
            period = normalize_period((year, quarter))
            if period is None:
                continue
            npl_ratio = clean_number(row.get("npl"))
            coverage_ratio = clean_number(row.get("loansLossReservesToNPLs"))
            car_ratio = clean_number(row.get("car"))
            ratios[period] = {
                "npl_ratio": (
                    npl_ratio if npl_ratio is not None and 0 <= npl_ratio <= 1 else None
                ),
                "coverage_ratio": (
                    abs(coverage_ratio)
                    if coverage_ratio is not None and coverage_ratio != 0
                    else None
                ),
                "car_percent": (
                    car_ratio * 100
                    if car_ratio is not None and 0 < car_ratio <= 1
                    else None
                ),
            }
        return ratios

    @staticmethod
    def _merge_bank_risk_values(
        period: str,
        values: dict[str, object],
        ratios: Mapping[str, Mapping[str, float | None]],
    ) -> None:
        risk = ratios.get(period)
        if risk is None:
            return
        gross_loans = clean_number(values.get("gross_loans"))
        reserve = clean_number(values.get("loan_loss_reserve"))
        npl_ratio = risk.get("npl_ratio")
        coverage_ratio = risk.get("coverage_ratio")
        if (
            gross_loans is not None and gross_loans > 0
            and reserve is not None and reserve >= 0
            and npl_ratio is not None and npl_ratio > 0
            and coverage_ratio is not None
        ):
            nonperforming_loans = gross_loans * npl_ratio
            computed_coverage = reserve / nonperforming_loans
            if math.isclose(
                computed_coverage, coverage_ratio, rel_tol=1e-6, abs_tol=1e-6
            ):
                values["nonperforming_loans"] = nonperforming_loans
            else:
                LOGGER.warning(
                    "Rejected Vietcap IQ bank NPL mapping for %s: coverage identity failed",
                    period,
                )
        car_percent = risk.get("car_percent")
        if car_percent is not None:
            values["car_percent"] = car_percent

    @classmethod
    def _securities_balance_values(
        cls, row: Mapping[str, object]
    ) -> dict[str, float | None]:
        values = cls._balance_values(row)
        if not values:
            return {}
        short_detail = clean_number(row.get("bss238"))
        long_detail = clean_number(row.get("bss247"))
        if (
            short_detail is not None
            and values["short_term_debt"] is not None
            and not _close(short_detail, values["short_term_debt"])
        ) or (
            long_detail is not None
            and values["long_term_debt"] is not None
            and not _close(long_detail, values["long_term_debt"])
        ):
            LOGGER.warning("Rejected Vietcap IQ securities borrowings mapping: identity failed")
            return {}
        return values

    @classmethod
    def _securities_income_values(
        cls, row: Mapping[str, object]
    ) -> dict[str, float | None]:
        revenue = clean_number(row.get("isa1"))
        deductions = clean_number(row.get("isa2"))
        net_revenue = clean_number(row.get("isa3"))
        if (
            None not in (revenue, deductions, net_revenue)
            and not _close(revenue + deductions, net_revenue)  # type: ignore[operator]
        ):
            LOGGER.warning("Rejected Vietcap IQ securities revenue mapping: identity failed")
            return {}
        total_net_income = clean_number(row.get("isa20"))
        minority_interest = clean_number(row.get("isa21"))
        parent_net_income = clean_number(row.get("isa22"))
        if not _profit_identity_valid(
            total_net_income, parent_net_income, minority_interest
        ):
            LOGGER.warning(
                "Vietcap IQ securities parent-profit allocation failed identity; "
                "keeping total profit only"
            )
            parent_net_income = None
        return {
            "revenue": net_revenue,
            "net_income": total_net_income,
            "net_income_parent": parent_net_income,
        }

    @classmethod
    def _insurance_balance_values(
        cls, row: Mapping[str, object]
    ) -> dict[str, float | None]:
        assets = clean_number(row.get("bsa53"))
        liabilities = clean_number(row.get("bsa54"))
        equity = clean_number(row.get("bsa78"))
        total_resources = clean_number(row.get("bsa96"))
        short_term_loans = clean_number(row.get("bsa56"))
        long_term_loans = clean_number(row.get("bsa71"))
        valid = (
            None not in (assets, liabilities, equity, short_term_loans, long_term_loans)
            and _close(liabilities + equity, assets)  # type: ignore[operator]
            and (total_resources is None or _close(total_resources, assets))
        )
        if not valid:
            LOGGER.warning("Rejected Vietcap IQ insurance balance mapping: identity failed")
            return {}
        return {
            "total_assets": assets,
            "total_liabilities": liabilities,
            "short_term_debt": short_term_loans,
            "long_term_debt": long_term_loans,
            "total_equity": equity,
        }

    @staticmethod
    def _insurance_income_values(row: Mapping[str, object]) -> dict[str, float | None]:
        gross_written = clean_number(row.get("isi51"))
        assumed = clean_number(row.get("isi52"))
        reserve_change = clean_number(row.get("isi104"))
        premium_revenue = clean_number(row.get("isi103"))
        deductions = clean_number(row.get("isi53"))
        net_premium_revenue = clean_number(row.get("isi105"))
        legacy_reserve_change = clean_number(row.get("isi58"))
        commission_and_other = clean_number(row.get("isi106"))
        net_insurance_revenue = clean_number(row.get("isi64"))
        identities_valid = (
            None not in (gross_written, assumed, reserve_change, premium_revenue)
            and _close(  # type: ignore[operator]
                gross_written + assumed + reserve_change, premium_revenue
            )
            and None not in (deductions, net_premium_revenue)
            and _close(premium_revenue + deductions, net_premium_revenue)  # type: ignore[operator]
            and None not in (
                legacy_reserve_change, commission_and_other, net_insurance_revenue,
            )
            and _close(  # type: ignore[operator]
                net_premium_revenue + legacy_reserve_change + commission_and_other,
                net_insurance_revenue,
            )
        )
        if not identities_valid:
            LOGGER.warning("Rejected Vietcap IQ insurance revenue mapping: identity failed")
            return {}
        total_net_income = clean_number(row.get("isa20"))
        minority_interest = clean_number(row.get("isa21"))
        parent_net_income = clean_number(row.get("isa22"))
        if not _profit_identity_valid(
            total_net_income, parent_net_income, minority_interest
        ):
            LOGGER.warning(
                "Vietcap IQ insurance parent-profit allocation failed identity; "
                "keeping total profit only"
            )
            parent_net_income = None
        return {
            "revenue": net_insurance_revenue,
            "net_income": total_net_income,
            "net_income_parent": parent_net_income,
        }

    @staticmethod
    def _has_nonzero(rows: list[dict[str, object]], prefix: str) -> bool:
        return any(
            key.lower().startswith(prefix)
            and (value := clean_number(raw)) is not None
            and value != 0
            for row in rows
            for key, raw in row.items()
        )

    @classmethod
    def _schema_kind(cls, sections: Mapping[str, list[dict[str, object]]]) -> str:
        balance = sections.get("BALANCE_SHEET", [])
        income = sections.get("INCOME_STATEMENT", [])
        if cls._has_nonzero(balance, "bsb") and cls._has_nonzero(income, "isb"):
            return "bank"
        if cls._has_nonzero(balance, "bss") or cls._has_nonzero(income, "iss"):
            return "securities"
        if cls._has_nonzero(balance, "bsi") or cls._has_nonzero(income, "isi"):
            return "insurance"
        if cls._has_nonzero(balance, "bsa") and cls._has_nonzero(income, "isa"):
            return "corporate"
        return "unknown"

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
        authentication_failed = False
        for section in SECTIONS:
            try:
                sections[section] = self._fetch_section(symbol, section)
            except _AuthenticationFailure:
                authentication_failed = True
                attempted.append(f"{section}:{AUTH_FAILURE}")
                LOGGER.warning("Vietcap IQ authentication failed for %s", symbol)
            except Exception as error:
                attempted.append(f"{section}:{type(error).__name__}")
                LOGGER.warning(
                    "Vietcap IQ %s failed for %s: %s",
                    section, symbol, type(error).__name__,
                )
            else:
                attempted.append(f"{section}:ok")

        if authentication_failed:
            return ProviderResult.failed(
                symbol, "FINANCIALS", self.name,
                "Vietcap IQ authorization was rejected",
                attempted=tuple(attempted), diagnostic_code=AUTH_FAILURE,
            )

        if not sections:
            return ProviderResult.failed(
                symbol, "FINANCIALS", self.name,
                "Vietcap IQ statement endpoints failed",
                attempted=tuple(attempted),
            )

        schema_kind = self._schema_kind(sections)
        if schema_kind == "unknown":
            return ProviderResult.failed(
                symbol, "FINANCIALS", self.name,
                f"Vietcap IQ {schema_kind} statement schema is not supported",
                attempted=tuple(attempted), diagnostic_code=UNSUPPORTED_SCHEMA,
            )

        bank_risk_ratios: dict[str, dict[str, float | None]] = {}
        statistics_loaded = False
        if schema_kind == "bank":
            try:
                statistics = self._fetch_statistics(symbol)
            except _AuthenticationFailure:
                attempted.append(f"STATISTICS_FINANCIAL:{AUTH_FAILURE}")
                LOGGER.warning(
                    "Vietcap IQ statistics authentication failed for %s", symbol
                )
            except Exception as error:
                attempted.append(f"STATISTICS_FINANCIAL:{type(error).__name__}")
                LOGGER.warning(
                    "Vietcap IQ statistics failed for %s: %s",
                    symbol, type(error).__name__,
                )
            else:
                attempted.append("STATISTICS_FINANCIAL:ok")
                bank_risk_ratios = self._bank_risk_ratios(statistics)
                statistics_loaded = True

        merged: dict[str, dict[str, object]] = {}
        public_dates: dict[str, list[date]] = {}
        for section, rows in sections.items():
            for raw in rows:
                period = self._period(raw)
                if period is None:
                    continue
                values = (
                    self._bank_balance_values(raw)
                    if schema_kind == "bank" and section == "BALANCE_SHEET"
                    else self._bank_income_values(raw)
                    if schema_kind == "bank"
                    else self._securities_balance_values(raw)
                    if schema_kind == "securities" and section == "BALANCE_SHEET"
                    else self._securities_income_values(raw)
                    if schema_kind == "securities"
                    else self._insurance_balance_values(raw)
                    if schema_kind == "insurance" and section == "BALANCE_SHEET"
                    else self._insurance_income_values(raw)
                    if schema_kind == "insurance"
                    else self._balance_values(raw)
                    if section == "BALANCE_SHEET"
                    else self._income_values(raw)
                )
                if values:
                    merged.setdefault(period, {}).update(values)
                public_date = _parse_public_date(raw.get("publicDate"))
                if public_date is not None:
                    public_dates.setdefault(period, []).append(public_date)

        if schema_kind == "bank":
            for period, values in merged.items():
                self._merge_bank_risk_values(period, values, bank_risk_ratios)

        statements = tuple(
            StatementRow(
                symbol=symbol,
                period=period,
                # A combined row becomes point-in-time usable only after both
                # component statements are public, so the later date is safe.
                public_date=max(public_dates.get(period, []), default=None),
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
                attempted=tuple(attempted), diagnostic_code=INSUFFICIENT_DATA,
            )
        required_fields = (
            ("net_interest_income", "net_profit", "equity", "gross_loans", "loan_loss_reserve")
            if schema_kind == "bank"
            else ("revenue", "net_income", "total_equity", "short_term_debt", "long_term_debt")
            if schema_kind in {"securities", "insurance"}
            else ("revenue", "net_income_parent", "total_equity", "short_term_debt", "long_term_debt")
        )
        complete_rows = tuple(
            row for row in statements
            if row.public_date is not None
            and all(row.get(field) is not None for field in required_fields)
        )
        if not complete_rows:
            return ProviderResult.failed(
                symbol, "FINANCIALS", self.name,
                "Vietcap IQ returned no canonical-complete quarterly rows",
                attempted=tuple(attempted), diagnostic_code=INSUFFICIENT_DATA,
            )
        complete = all(
            row.public_date is not None
            and all(row.get(field) is not None for field in required_fields)
            for row in statements
        )
        bank_risk_complete = schema_kind != "bank" or all(
            row.get("nonperforming_loans") is not None and row.get("car_percent") is not None
            for row in complete_rows
        )
        return ProviderResult(
            symbol=symbol,
            dataset="FINANCIALS",
            provider=self.name,
            provider_source=(
                "IQ/financial-statement+statistics-financial"
                if schema_kind == "bank" and statistics_loaded
                else "IQ/financial-statement"
            ),
            status=(
                ProviderStatus.AVAILABLE
                if complete and bank_risk_complete
                else ProviderStatus.PARTIAL
            ),
            retrieved_at=datetime.now(timezone.utc),
            statements=statements,
            attempted=tuple(attempted),
            statement_schema=schema_kind,
            error_reason=(
                "bank BCTC available; NPL or CAR is absent for one or more quarters"
                if schema_kind == "bank" and not bank_risk_complete else None
            ),
        )

    def fetch_institutional_flow(
        self, symbol: str, *, exchange: str | None = None, lookback_days: int = 30
    ) -> ProviderResult:
        return ProviderResult.missing(
            symbol.strip().upper(), "INSTITUTIONAL", self.name,
            reason="Vietcap IQ adapter is scoped to FINANCIALS only",
        )
