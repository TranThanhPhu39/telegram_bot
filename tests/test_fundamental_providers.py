"""Provider layer: contracts, VNStock discovery, yfinance fallback, chain."""

from __future__ import annotations

from datetime import date
import importlib
import types

import pytest

from fundamentals.adapters import promote_corporate_statement
from fundamentals.providers.base import (
    FlowRow,
    FundamentalProvider,
    ProviderResult,
    ProviderStatus,
    StatementRow,
    clean_number,
    normalize_period,
    period_end_date,
)
from fundamentals.providers.provider_chain import ProviderChain, build_default_chain
from fundamentals.providers.tcbs_provider import REPORT_TYPES, TCBSProvider
from fundamentals.providers.vietcap_iq_provider import VietcapIQFinancialProvider
from fundamentals.providers.vnstock_provider import DEFAULT_SOURCE_PREFERENCE, VNStockProvider
from fundamentals.providers.yfinance_provider import YFinanceProvider, candidate_tickers


# --------------------------------------------------------------- base module
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026Q2", "2026Q2"), ("2026-Q2", "2026Q2"), ("Q22026", "2026Q2"),
        ("2026", "2026"), ("garbage", None), ("", None), (None, None),
    ],
)
def test_normalize_period_accepts_common_shapes_and_rejects_garbage(raw, expected) -> None:
    assert normalize_period(raw) == expected


def test_normalize_period_accepts_year_quarter_pair_and_rejects_bad_quarter() -> None:
    assert normalize_period((2026, 3)) == "2026Q3"
    assert normalize_period((2026, 7)) is None


def test_period_end_date_computes_calendar_end() -> None:
    assert period_end_date("2026Q2") == date(2026, 6, 30)
    assert period_end_date("2026") == date(2026, 12, 31)
    assert period_end_date("not-a-period") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,234.5", 1234.5), ("nan", None), (True, None), (float("inf"), None), (None, None), (0, 0.0)],
)
def test_clean_number_rejects_non_finite_and_non_numeric_values(raw, expected) -> None:
    assert clean_number(raw) == expected


def test_statement_row_rejects_unknown_field_names() -> None:
    with pytest.raises(ValueError, match="unknown statement fields"):
        StatementRow("FPT", "2026Q2", None, values={"bogus_field": 1.0})


def test_statement_row_established_fields_excludes_none_values() -> None:
    row = StatementRow("FPT", "2026Q2", None, values={"revenue": 1.0, "net_income": None})
    assert row.established_fields == ("revenue",)
    assert row.has_publication_date is False


def test_flow_row_tracks_foreign_and_proprietary_independently() -> None:
    foreign_only = FlowRow("FPT", date(2026, 9, 1), foreign_buy_value=10.0)
    assert foreign_only.has_foreign and not foreign_only.has_proprietary and not foreign_only.is_empty

    empty = FlowRow("FPT", date(2026, 9, 1))
    assert empty.is_empty


def test_flow_row_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        FlowRow("FPT", date(2026, 9, 1), foreign_buy_value=-1.0)


def test_provider_status_usable_and_fallback_flags() -> None:
    assert ProviderStatus.AVAILABLE.usable and not ProviderStatus.AVAILABLE.should_try_fallback
    assert ProviderStatus.PARTIAL.usable
    assert not ProviderStatus.MISSING.usable and ProviderStatus.MISSING.should_try_fallback
    assert not ProviderStatus.ERROR.usable and ProviderStatus.ERROR.should_try_fallback


def test_provider_result_error_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="ERROR results must carry"):
        ProviderResult(symbol="FPT", dataset="FINANCIALS", provider="X", status=ProviderStatus.ERROR)


def test_provider_result_usable_requires_at_least_one_row() -> None:
    with pytest.raises(ValueError, match="usable results must carry"):
        ProviderResult(symbol="FPT", dataset="FINANCIALS", provider="X", status=ProviderStatus.AVAILABLE)


def test_provider_result_provenance_combines_provider_and_source() -> None:
    result = ProviderResult.missing("FPT", "FINANCIALS", "VNStock", provider_source="VCI")
    assert result.provenance == "VNStock/VCI"
    assert ProviderResult.missing("FPT", "FINANCIALS", "VNStock").provenance == "VNStock"


# ---------------------------------------------------------------- VNStock
def _finance(income=None, balance=None, cashflow=None, error: bool = False):
    class Finance:
        def income_statement(self, period=None, lang=None):
            if error:
                raise RuntimeError("no data")
            return income

        def balance_sheet(self, period=None, lang=None):
            return balance

        def cash_flow(self, period=None, lang=None):
            return cashflow

    return Finance()


def _vnstock_module(mapping: dict[str, object]) -> object:
    class Factory:
        def __call__(self):
            return self

        def stock(self, symbol=None, source=None):
            if source not in mapping:
                raise ValueError("unsupported source")
            return mapping[source]

    return types.SimpleNamespace(Vnstock=Factory())


def test_vnstock_fetches_and_normalizes_a_full_statement() -> None:
    stock = types.SimpleNamespace(finance=_finance(
        income=[{"yearReport": 2026, "lengthReport": 2, "Revenue": 1000.0,
                 "Net Income": 120.0, "publicDate": "2026-08-15"}],
        balance=[{"yearReport": 2026, "lengthReport": 2, "Total Assets": 5000.0,
                  "Owner's Equity": 2000.0}],
    ))
    provider = VNStockProvider(module=_vnstock_module({"VCI": stock}))
    result = provider.fetch_financials("fpt")

    assert result.status is ProviderStatus.AVAILABLE
    assert result.provider_source == "VCI"
    assert len(result.statements) == 1
    row = result.statements[0]
    assert row.period == "2026Q2"
    assert row.public_date == date(2026, 8, 15)
    assert row.get("revenue") == 1000.0 and row.get("total_equity") == 2000.0


def test_vnstock_falls_through_source_preference_when_one_source_is_unsupported() -> None:
    stock = types.SimpleNamespace(finance=_finance(
        income=[{"yearReport": 2026, "lengthReport": 2, "Revenue": 1.0, "Net Income": 1.0}],
    ))
    # Only VCI is registered; KBS (tried first) is simply absent from this release.
    provider = VNStockProvider(module=_vnstock_module({"VCI": stock}))
    result = provider.fetch_financials("FPT")
    assert result.provider_source == "VCI"


def test_vnstock_default_sources_match_supported_v4_finance_backends() -> None:
    assert DEFAULT_SOURCE_PREFERENCE == ("KBS", "VCI", "TCBS")


def test_vnstock_normalizes_v4_kbs_wide_semantic_statements() -> None:
    stock = types.SimpleNamespace(finance=_finance(
        income=[
            {"item": "Doanh thu thuần", "item_id": "revenue",
             "2026-Q2": 1000.0, "2026-Q1": 900.0},
            {"item": "Lợi nhuận sau thuế", "item_id": "net_profit",
             "2026-Q2": 120.0, "2026-Q1": 100.0},
            {"item": "Lợi nhuận thuộc công ty mẹ",
             "item_id": "profit_after_tax_for_shareholders_of_parent_company",
             "2026-Q2": 110.0, "2026-Q1": 95.0},
        ],
        balance=[
            # KBS can include empty group headings with the same semantic ID.
            {"item": "Tài sản", "item_id": "total_assets",
             "2026-Q2": None, "2026-Q1": None},
            {"item": "Tổng cộng tài sản", "item_id": "total_assets",
             "2026-Q2": 5000.0, "2026-Q1": 4800.0},
            {"item": "Vốn chủ sở hữu", "item_id": "owners_equity_2",
             "2026-Q2": 2000.0, "2026-Q1": 1900.0},
            {"item": "Vay ngắn hạn",
             "item_id": "short_term_borrowings_and_financial_leases",
             "2026-Q2": 300.0, "2026-Q1": 280.0},
            {"item": "Vay dài hạn",
             "item_id": "long_term_borrowings_and_financial_leases",
             "2026-Q2": 400.0, "2026-Q1": 390.0},
        ],
    ))
    provider = VNStockProvider(
        module=_vnstock_module({"KBS": stock}), source_preference=("KBS", "VCI")
    )

    result = provider.fetch_financials("FPT")

    assert result.status is ProviderStatus.AVAILABLE
    assert result.provider_source == "KBS"
    assert [row.period for row in result.statements] == ["2026Q1", "2026Q2"]
    latest = result.statements[-1]
    assert latest.get("revenue") == 1000.0
    assert latest.get("net_income") == 120.0
    assert latest.get("net_income_parent") == 110.0
    assert latest.get("total_assets") == 5000.0
    assert latest.get("total_equity") == 2000.0
    assert latest.get("short_term_debt") == 300.0
    assert latest.public_date is None


def test_vnstock_does_not_construct_later_source_after_first_source_succeeds() -> None:
    calls = []
    stock = types.SimpleNamespace(finance=_finance(
        income=[{"yearReport": 2026, "lengthReport": 2, "Revenue": 1.0}],
    ))

    class Factory:
        def stock(self, symbol=None, source=None):
            calls.append(source)
            if source == "VCI":
                raise AssertionError("later source must remain lazy")
            return stock

    provider = VNStockProvider(
        module=types.SimpleNamespace(Vnstock=Factory), source_preference=("KBS", "VCI")
    )
    result = provider.fetch_financials("FPT")

    assert result.provider_source == "KBS"
    assert calls == ["KBS"]


def test_vnstock_missing_when_endpoint_raises_for_every_source() -> None:
    stock = types.SimpleNamespace(finance=_finance(error=True))
    provider = VNStockProvider(module=_vnstock_module({"VCI": stock}))
    result = provider.fetch_financials("FPT")
    assert result.status is ProviderStatus.MISSING
    assert result.attempted  # diagnostics retained even though nothing succeeded


def test_vnstock_missing_when_frames_are_empty() -> None:
    stock = types.SimpleNamespace(finance=_finance(income=[], balance=[]))
    provider = VNStockProvider(module=_vnstock_module({"VCI": stock}))
    assert provider.fetch_financials("FPT").status is ProviderStatus.MISSING


def test_vnstock_malformed_rows_do_not_crash_and_yield_missing() -> None:
    stock = types.SimpleNamespace(finance=_finance(income=[{"unrelated_column": "x"}]))
    provider = VNStockProvider(module=_vnstock_module({"VCI": stock}))
    result = provider.fetch_financials("FPT")
    assert result.status is ProviderStatus.MISSING


def test_vnstock_partial_when_required_canonical_fields_are_missing() -> None:
    stock = types.SimpleNamespace(finance=_finance(
        income=[{"yearReport": 2026, "lengthReport": 2, "Net Income": 5.0}],
    ))
    provider = VNStockProvider(module=_vnstock_module({"VCI": stock}))
    result = provider.fetch_financials("FPT")
    assert result.status is ProviderStatus.PARTIAL


def test_vnstock_not_installed_returns_missing_without_raising(monkeypatch) -> None:
    real_import = importlib.import_module

    def unavailable(name, *args, **kwargs):
        if name == "vnstock":
            raise ModuleNotFoundError("vnstock")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", unavailable)
    provider = VNStockProvider(module=None)
    result = provider.fetch_financials("FPT")
    assert result.status is ProviderStatus.MISSING
    assert "vnstock" in (result.error_reason or "").lower()


def test_vnstock_institutional_flow_deduplicates_by_date_and_ignores_bad_dates() -> None:
    class Trading:
        def foreign_trade(self):
            return [
                {"tradingDate": "2026-09-01", "foreignBuyValue": 100.0, "foreignSellValue": 50.0},
                {"tradingDate": "2026-09-01", "foreignBuyValue": 999.0},  # duplicate date ignored
                {"tradingDate": "not-a-date", "foreignBuyValue": 1.0},
            ]

    stock = types.SimpleNamespace(finance=_finance(), trading=Trading())
    provider = VNStockProvider(module=_vnstock_module({"VCI": stock}))
    result = provider.fetch_institutional_flow("FPT")

    assert len(result.flows) == 1
    assert result.flows[0].trading_date == date(2026, 9, 1)
    assert result.flows[0].has_foreign
    assert result.flows[0].proprietary_buy_value is None  # never coerced to 0


def test_vnstock_institutional_flow_missing_when_no_endpoint_exists() -> None:
    stock = types.SimpleNamespace(finance=_finance())
    provider = VNStockProvider(module=_vnstock_module({"VCI": stock}))
    assert provider.fetch_institutional_flow("FPT").status is ProviderStatus.MISSING


# ---------------------------------------------------------------- yfinance
@pytest.mark.parametrize(
    ("exchange", "expected"),
    [("HOSE", ("FPT.VN",)), ("HNX", ("SHS.HN", "SHS.VN")), (None, ("ABC.VN", "ABC.HN"))],
)
def test_candidate_tickers_derive_from_exchange_not_a_fixed_suffix(exchange, expected) -> None:
    symbol = "FPT" if exchange == "HOSE" else ("SHS" if exchange == "HNX" else "ABC")
    assert candidate_tickers(symbol, exchange) == expected


def test_candidate_tickers_refuses_to_guess_for_an_unmapped_known_exchange() -> None:
    assert candidate_tickers("ABC", "NASDAQ") == ()


class _FakeYahooTicker:
    def __init__(self, frames: dict[str, dict]) -> None:
        for name, frame in frames.items():
            setattr(self, name, types.SimpleNamespace(to_dict=lambda f=frame: f))


def test_yfinance_normalizes_a_quarterly_frame() -> None:
    frames = {
        "quarterly_financials": {
            date(2026, 6, 30): {"Total Revenue": 500.0, "Net Income": 40.0},
        },
        "quarterly_balance_sheet": {
            date(2026, 6, 30): {"Total Assets": 900.0, "Stockholders Equity": 300.0},
        },
    }
    module = types.SimpleNamespace(Ticker=lambda ticker: _FakeYahooTicker(frames))
    provider = YFinanceProvider(module=module)
    result = provider.fetch_financials("FPT", exchange="HOSE")

    assert result.status is ProviderStatus.AVAILABLE
    assert result.provider_source == "FPT.VN"
    row = result.statements[0]
    assert row.period == "2026Q2"
    assert row.public_date is None  # Yahoo never carries a VN announcement date
    assert row.get("revenue") == 500.0


def test_yfinance_never_reads_annual_frames_as_q4_quarters() -> None:
    frames = {
        "quarterly_financials": {
            date(2024, 12, 31): {"Total Revenue": 16_000.0, "Net Income": 2_000.0},
        },
        "quarterly_balance_sheet": {
            date(2024, 12, 31): {"Stockholders Equity": 30_000.0},
        },
        "financials": {
            date(2024, 12, 31): {"Total Revenue": 61_000.0, "Net Income": 9_000.0},
            date(2023, 12, 31): {"Total Revenue": 60_000.0, "Net Income": 8_000.0},
        },
        "balance_sheet": {
            date(2023, 12, 31): {"Stockholders Equity": 29_000.0},
        },
    }
    module = types.SimpleNamespace(Ticker=lambda ticker: _FakeYahooTicker(frames))

    result = YFinanceProvider(module=module).fetch_financials("VNM", exchange="HOSE")

    assert [row.period for row in result.statements] == ["2024Q4"]
    assert result.statements[0].get("revenue") == 16_000.0
    assert all(row.period != "2023Q4" for row in result.statements)


def test_yfinance_disabled_is_missing_without_importing_anything() -> None:
    provider = YFinanceProvider(module=None, enabled=False)
    assert provider.fetch_financials("FPT", exchange="HOSE").status is ProviderStatus.MISSING


def test_yfinance_unmapped_exchange_is_missing_not_a_wrong_guess() -> None:
    provider = YFinanceProvider(module=types.SimpleNamespace(Ticker=lambda t: _FakeYahooTicker({})))
    result = provider.fetch_financials("FPT", exchange="NASDAQ")
    assert result.status is ProviderStatus.MISSING
    assert result.attempted == ()


def test_yfinance_ticker_exception_becomes_error_not_a_crash() -> None:
    def boom(ticker):
        raise ConnectionError("network down")

    provider = YFinanceProvider(module=types.SimpleNamespace(Ticker=boom))
    result = provider.fetch_financials("FPT", exchange="HOSE")
    assert result.status is ProviderStatus.ERROR
    assert "ConnectionError" in (result.error_reason or "")


def test_yfinance_never_supplies_institutional_flow() -> None:
    provider = YFinanceProvider(module=types.SimpleNamespace())
    result = provider.fetch_institutional_flow("FPT")
    assert result.status is ProviderStatus.MISSING


# ------------------------------------------------------------------- TCBS
class _FakeTCBSResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _FakeTCBSSession:
    """Maps report_type (parsed from the URL) to a canned payload or error."""

    def __init__(self, payloads: dict[str, object], *, raise_for: frozenset[str] = frozenset()) -> None:
        self._payloads = payloads
        self._raise_for = raise_for
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: object) -> _FakeTCBSResponse:
        report_type = url.rsplit("/", 1)[-1]
        self.calls.append(report_type)
        if report_type in self._raise_for:
            raise ConnectionError(f"{report_type} unreachable")
        return _FakeTCBSResponse(self._payloads.get(report_type, []))


def test_tcbs_normalizes_a_quarterly_statement_set() -> None:
    session = _FakeTCBSSession({
        "incomestatement": [
            {"year": 2026, "quarter": 2, "revenue": 500.0, "grossProfit": 120.0,
             "operationProfit": 80.0, "postTaxProfit": 60.0, "shareHolderIncome": 58.0},
        ],
        "balancesheet": [
            {"year": 2026, "quarter": 2, "cash": 40.0, "asset": 900.0, "equity": 300.0},
        ],
        "cashflow": [
            {"year": 2026, "quarter": 2, "fromSale": 70.0},
        ],
    })
    provider = TCBSProvider(session=session)
    result = provider.fetch_financials("FPT")

    assert result.status is ProviderStatus.AVAILABLE
    assert result.provider_source == "TCAnalysis"
    row = result.statements[0]
    assert row.period == "2026Q2"
    assert row.public_date is None  # TCBS never carries a VN announcement date
    assert row.get("revenue") == 500.0
    assert row.get("net_income_parent") == 58.0
    assert row.get("total_equity") == 300.0
    # cashflow endpoint's buckets are deliberately unmapped (see module docstring)
    assert row.get("operating_cash_flow") is None
    assert row.get("capex") is None


def test_tcbs_disabled_is_missing_without_a_network_call() -> None:
    session = _FakeTCBSSession({})
    provider = TCBSProvider(session=session, enabled=False)
    result = provider.fetch_financials("FPT")
    assert result.status is ProviderStatus.MISSING
    assert session.calls == []


def test_tcbs_partial_when_one_endpoint_fails_but_others_answer() -> None:
    session = _FakeTCBSSession(
        {"incomestatement": [{"year": 2026, "quarter": 2, "revenue": 500.0}]},
        raise_for=frozenset({"balancesheet", "cashflow"}),
    )
    provider = TCBSProvider(session=session)
    result = provider.fetch_financials("FPT")
    assert result.status is ProviderStatus.PARTIAL  # total_equity never established
    assert result.statements[0].get("revenue") == 500.0
    assert "balancesheet:ConnectionError" in result.attempted
    assert "cashflow:ConnectionError" in result.attempted


def test_tcbs_error_when_every_endpoint_fails() -> None:
    session = _FakeTCBSSession({}, raise_for=frozenset(REPORT_TYPES))
    provider = TCBSProvider(session=session)
    result = provider.fetch_financials("FPT")
    assert result.status is ProviderStatus.ERROR
    assert "incomestatement" in (result.error_reason or "")


def test_tcbs_annual_rollup_rows_are_skipped_in_quarterly_mode() -> None:
    # yearly=0 responses may still include a quarter=0 annual roll-up row;
    # only quarter 1-4 rows are genuine quarterly periods.
    session = _FakeTCBSSession({
        "incomestatement": [
            {"year": 2026, "quarter": 0, "revenue": 2000.0},
            {"year": 2026, "quarter": 2, "revenue": 500.0},
        ],
    })
    provider = TCBSProvider(session=session)
    result = provider.fetch_financials("FPT")
    assert [row.period for row in result.statements] == ["2026Q2"]


def test_tcbs_never_supplies_institutional_flow() -> None:
    provider = TCBSProvider(session=_FakeTCBSSession({}))
    result = provider.fetch_institutional_flow("FPT")
    assert result.status is ProviderStatus.MISSING


def test_build_default_chain_tries_tcbs_between_vnstock_and_yfinance() -> None:
    chain = build_default_chain(
        vnstock_module=types.SimpleNamespace(),
        yfinance_module=types.SimpleNamespace(),
        tcbs_session=_FakeTCBSSession({}),
    )
    assert [provider.name for provider in chain.providers] == ["VNStock", "TCBS", "yfinance"]


# ------------------------------------------------------------ Vietcap IQ
class _FakeIQResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise ConnectionError(f"HTTP {self.status_code}")

    def json(self) -> object:
        return self._payload


class _FakeIQSession:
    def __init__(self, sections: dict[str, object], status_code: int = 200) -> None:
        self.sections = sections
        self.status_code = status_code
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> _FakeIQResponse:
        if url.endswith("/statistics-financial"):
            self.calls.append(("STATISTICS_FINANCIAL", kwargs))
            payload = self.sections.get("STATISTICS_FINANCIAL", {})
            return _FakeIQResponse(payload, self.status_code)
        params = kwargs.get("params")
        assert isinstance(params, dict)
        section = str(params["section"])
        self.calls.append((section, kwargs))
        payload = self.sections.get(section, {})
        return _FakeIQResponse(payload, self.status_code)


def _iq_payload(row: dict[str, object]) -> dict[str, object]:
    return {
        "status": 200,
        "successful": True,
        "data": {"years": [], "quarters": [row]},
    }


def _iq_statistics(*rows: dict[str, object]) -> dict[str, object]:
    return {"status": 200, "successful": True, "data": list(rows)}


def _iq_balance(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "organCode": "FPT", "yearReport": 2026, "lengthReport": 2,
        "publicDate": "2026-08-22T00:00:00",
        "bsa53": 1000.0, "bsa54": 600.0, "bsa55": 400.0,
        "bsa56": 125.0, "bsa67": 200.0, "bsa71": 75.0,
        "bsa78": 400.0,
    }
    row.update(overrides)
    return row


def _iq_income(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "organCode": "FPT", "yearReport": 2026, "lengthReport": 2,
        "publicDate": "2026-08-22T00:00:00",
        "isa3": 500.0, "isa20": 60.0, "isa21": 2.0, "isa22": 58.0,
    }
    row.update(overrides)
    return row


def test_vietcap_iq_normalizes_verified_quarter_and_actual_public_date() -> None:
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(_iq_balance()),
        "INCOME_STATEMENT": _iq_payload(_iq_income()),
    })

    result = VietcapIQFinancialProvider(session=session).fetch_financials("fpt")

    assert result.status is ProviderStatus.AVAILABLE
    assert result.provider_source == "IQ/financial-statement"
    assert [name for name, _ in session.calls] == ["BALANCE_SHEET", "INCOME_STATEMENT"]
    request_headers = session.calls[0][1]["headers"]
    assert request_headers["Origin"] == "https://trading.vietcap.com.vn"
    assert request_headers["Referer"] == "https://trading.vietcap.com.vn/iq/"
    assert "Cookie" not in request_headers and "device-id" not in request_headers
    row = result.statements[0]
    assert row.period == "2026Q2"
    assert row.public_date == date(2026, 8, 22)
    assert row.public_date_source == "actual"
    assert row.get("revenue") == 500.0
    assert row.get("net_income") == 60.0
    assert row.get("net_income_parent") == 58.0
    assert row.get("total_assets") == 1000.0
    assert row.get("total_liabilities") == 600.0
    assert row.get("short_term_debt") == 125.0
    assert row.get("long_term_debt") == 75.0
    assert row.get("total_equity") == 400.0
    canonical = promote_corporate_statement(row, source=result.provenance)
    assert canonical is not None
    assert canonical.net_profit == 58.0
    assert canonical.total_debt == 200.0
    assert canonical.public_date == date(2026, 8, 22)


def test_vietcap_iq_fails_closed_when_accounting_identity_changes() -> None:
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(_iq_balance(bsa78=999.0)),
        "INCOME_STATEMENT": _iq_payload(_iq_income()),
    })

    result = VietcapIQFinancialProvider(session=session).fetch_financials("FPT")

    assert result.status is ProviderStatus.ERROR
    assert "no canonical-complete" in result.error_reason


def test_vietcap_iq_unusable_partial_allows_provider_chain_fallback() -> None:
    iq = VietcapIQFinancialProvider(session=_FakeIQSession({
        "BALANCE_SHEET": _iq_payload(_iq_balance(bsa78=999.0)),
        "INCOME_STATEMENT": _iq_payload(_iq_income()),
    }))
    fallback = _StubProvider("VNStock", ProviderStatus.AVAILABLE)

    result = ProviderChain([iq, fallback]).fetch_financials("FPT")

    assert result.provider == "VNStock"
    assert result.attempted == ("VietcapIQ:ERROR", "VNStock:AVAILABLE")


def test_vietcap_iq_uses_later_component_public_date_without_lookahead() -> None:
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(_iq_balance()),
        "INCOME_STATEMENT": _iq_payload(_iq_income(publicDate="2026-08-23T00:00:00")),
    })
    result = VietcapIQFinancialProvider(session=session).fetch_financials("FPT")
    assert result.status is ProviderStatus.AVAILABLE
    assert result.statements[0].public_date == date(2026, 8, 23)


def test_vietcap_iq_http_failure_becomes_error_and_never_crashes_chain() -> None:
    session = _FakeIQSession({}, status_code=403)
    result = VietcapIQFinancialProvider(session=session).fetch_financials("FPT")
    assert result.status is ProviderStatus.ERROR
    assert result.attempted == (
        "BALANCE_SHEET:AUTH_FAILURE", "INCOME_STATEMENT:AUTH_FAILURE"
    )
    assert result.diagnostic_code == "AUTH_FAILURE"


def test_vietcap_iq_maps_verified_bank_schema_and_rejects_corporate_mapping() -> None:
    balance = _iq_balance(
        organCode="ACB", bsa53=1000.0, bsa54=900.0, bsa55=0.0,
        bsa56=0.0, bsa67=0.0, bsa71=0.0, bsa78=100.0,
        bsb103=780.0, bsb104=800.0, bsb105=-20.0,
    )
    income = _iq_income(
        organCode="ACB", isa3=0.0, isa20=10.0, isa21=-1.0, isa22=9.0,
        isb25=80.0, isb26=-30.0, isb27=50.0,
    )
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(balance),
        "INCOME_STATEMENT": _iq_payload(income),
    })

    result = VietcapIQFinancialProvider(session=session).fetch_financials("ACB")

    assert result.status is ProviderStatus.PARTIAL
    row = result.statements[0]
    assert row.get("net_interest_income") == 50.0
    assert row.get("net_profit") == 9.0
    assert row.get("equity") == 100.0
    assert row.get("gross_loans") == 800.0
    assert row.get("loan_loss_reserve") == 20.0
    assert row.get("nonperforming_loans") is None
    assert row.get("car_percent") is None
    assert row.get("revenue") is None
    assert "NPL or CAR" in result.error_reason


def test_vietcap_iq_maps_bank_npl_and_car_from_verified_quarterly_ratios() -> None:
    balance = _iq_balance(
        organCode="ACB", bsa53=1000.0, bsa54=900.0, bsa55=0.0,
        bsa56=0.0, bsa67=0.0, bsa71=0.0, bsa78=100.0,
        bsb103=780.0, bsb104=800.0, bsb105=-20.0,
    )
    income = _iq_income(
        organCode="ACB", isa3=0.0, isa20=10.0, isa21=-1.0, isa22=9.0,
        isb25=80.0, isb26=-30.0, isb27=50.0,
    )
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(balance),
        "INCOME_STATEMENT": _iq_payload(income),
        "STATISTICS_FINANCIAL": _iq_statistics({
            "yearReport": 2026, "quarter": 2, "ratioType": "RATIO_TTM",
            "npl": 0.025, "loansLossReservesToNPLs": -1.0, "car": 0.10,
        }),
    })

    result = VietcapIQFinancialProvider(session=session).fetch_financials("ACB")

    assert result.status is ProviderStatus.AVAILABLE
    assert result.provider_source == "IQ/financial-statement+statistics-financial"
    assert [name for name, _ in session.calls] == [
        "BALANCE_SHEET", "INCOME_STATEMENT", "STATISTICS_FINANCIAL",
    ]
    row = result.statements[0]
    assert row.get("nonperforming_loans") == 20.0
    assert row.get("loan_loss_reserve") == 20.0
    assert row.get("car_percent") == 10.0


def test_vietcap_iq_bank_ratios_fail_closed_on_coverage_mismatch_and_zero_car() -> None:
    balance = _iq_balance(
        organCode="ACB", bsa53=1000.0, bsa54=900.0, bsa55=0.0,
        bsa56=0.0, bsa67=0.0, bsa71=0.0, bsa78=100.0,
        bsb103=780.0, bsb104=800.0, bsb105=-20.0,
    )
    income = _iq_income(
        organCode="ACB", isa3=0.0, isa20=10.0, isa21=-1.0, isa22=9.0,
        isb25=80.0, isb26=-30.0, isb27=50.0,
    )
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(balance),
        "INCOME_STATEMENT": _iq_payload(income),
        "STATISTICS_FINANCIAL": _iq_statistics(
            {
                "yearReport": 2026, "quarter": 2, "ratioType": "RATIO_TTM",
                "npl": 0.025, "loansLossReservesToNPLs": -9.0, "car": 0.0,
            },
            {
                "yearReport": 2026, "quarter": 5, "ratioType": "RATIO_YEAR",
                "npl": 0.025, "loansLossReservesToNPLs": -1.0, "car": 0.12,
            },
        ),
    })

    result = VietcapIQFinancialProvider(session=session).fetch_financials("ACB")

    assert result.status is ProviderStatus.PARTIAL
    row = result.statements[0]
    assert row.get("nonperforming_loans") is None
    assert row.get("car_percent") is None


def test_vietcap_iq_maps_verified_securities_schema() -> None:
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(_iq_balance(bss216=10.0, bss238=125.0, bss247=75.0)),
        "INCOME_STATEMENT": _iq_payload(_iq_income(isa1=500.0, isa2=0.0, iss42=5.0)),
    })
    result = VietcapIQFinancialProvider(session=session).fetch_financials("VIX")
    assert result.status is ProviderStatus.AVAILABLE
    assert result.statement_schema == "securities"
    row = result.statements[0]
    assert row.get("revenue") == 500.0
    assert row.get("net_income_parent") == 58.0
    assert row.get("total_equity") == 400.0
    assert row.get("short_term_debt") == 125.0
    assert row.get("long_term_debt") == 75.0


def test_vietcap_iq_rejects_securities_borrowings_identity_change() -> None:
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(_iq_balance(bss216=10.0, bss238=999.0, bss247=75.0)),
        "INCOME_STATEMENT": _iq_payload(_iq_income(isa1=500.0, isa2=0.0, iss42=5.0)),
    })
    result = VietcapIQFinancialProvider(session=session).fetch_financials("VIX")
    assert result.status is ProviderStatus.ERROR
    assert result.diagnostic_code == "INSUFFICIENT_DATA"


def test_vietcap_iq_securities_keeps_total_profit_when_parent_allocation_is_invalid() -> None:
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(_iq_balance(bss216=10.0, bss238=125.0, bss247=75.0)),
        "INCOME_STATEMENT": _iq_payload(_iq_income(
            isa1=500.0, isa2=0.0, isa20=60.0, isa21=2.0, isa22=10.0, iss42=5.0,
        )),
    })
    result = VietcapIQFinancialProvider(session=session).fetch_financials("SSI")
    assert result.status is ProviderStatus.AVAILABLE
    assert result.statements[0].get("net_income") == 60.0
    assert result.statements[0].get("net_income_parent") is None


def test_vietcap_iq_maps_verified_insurance_schema() -> None:
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(_iq_balance(
            bsa55=0.0, bsa67=0.0, bsa96=1000.0, bsi139=10.0,
        )),
        "INCOME_STATEMENT": _iq_payload(_iq_income(
            isa20=10.0, isa21=0.0, isa22=10.0,
            isi51=100.0, isi52=5.0, isi104=-10.0, isi103=95.0,
            isi53=-15.0, isi105=80.0, isi58=0.0, isi106=5.0, isi64=85.0,
        )),
    })
    result = VietcapIQFinancialProvider(session=session).fetch_financials("ABI")
    assert result.status is ProviderStatus.AVAILABLE
    assert result.statement_schema == "insurance"
    assert result.statements[0].get("revenue") == 85.0
    assert result.statements[0].get("net_income") == 10.0


def test_vietcap_iq_rejects_insurance_revenue_identity_change() -> None:
    session = _FakeIQSession({
        "BALANCE_SHEET": _iq_payload(_iq_balance(bsi139=10.0)),
        "INCOME_STATEMENT": _iq_payload(_iq_income(
            isi51=100.0, isi52=5.0, isi104=-10.0, isi103=999.0,
            isi53=-15.0, isi105=80.0, isi58=0.0, isi106=5.0, isi64=85.0,
        )),
    })
    result = VietcapIQFinancialProvider(session=session).fetch_financials("ABI")
    assert result.status is ProviderStatus.ERROR
    assert result.diagnostic_code == "INSUFFICIENT_DATA"


def test_vietcap_iq_is_first_only_when_explicitly_enabled() -> None:
    disabled = build_default_chain(
        vnstock_module=types.SimpleNamespace(), yfinance_module=types.SimpleNamespace(),
        tcbs_session=_FakeTCBSSession({}),
    )
    enabled = build_default_chain(
        vietcap_iq_enabled=True, vietcap_iq_session=_FakeIQSession({}),
        vnstock_module=types.SimpleNamespace(), yfinance_module=types.SimpleNamespace(),
        tcbs_session=_FakeTCBSSession({}),
    )
    assert [provider.name for provider in disabled.providers] == [
        "VNStock", "TCBS", "yfinance"
    ]
    assert [provider.name for provider in enabled.providers] == [
        "VietcapIQ", "VNStock", "TCBS", "yfinance"
    ]


# ------------------------------------------------------------- provider chain
class _StubProvider(FundamentalProvider):
    def __init__(self, name: str, status: ProviderStatus, *, raises: bool = False) -> None:
        self.name = name
        self._status = status
        self._raises = raises
        self.calls = 0

    def available(self) -> bool:
        return True

    def fetch_financials(self, symbol: str, *, exchange: str | None = None) -> ProviderResult:
        self.calls += 1
        if self._raises:
            raise RuntimeError("adapter exploded")
        if self._status.usable:
            row = StatementRow(symbol, "2026Q2", None, values={"revenue": 1.0})
            return ProviderResult(
                symbol=symbol, dataset="FINANCIALS", provider=self.name,
                status=self._status, provider_source="X", statements=(row,),
            )
        if self._status is ProviderStatus.ERROR:
            return ProviderResult.failed(symbol, "FINANCIALS", self.name, "upstream 500")
        return ProviderResult.missing(symbol, "FINANCIALS", self.name)

    def fetch_institutional_flow(self, symbol, *, exchange=None, lookback_days=30):
        return ProviderResult.missing(symbol, "INSTITUTIONAL", self.name)


def test_chain_stops_at_the_first_usable_provider_and_never_calls_the_next() -> None:
    primary = _StubProvider("VNStock", ProviderStatus.AVAILABLE)
    fallback = _StubProvider("yfinance", ProviderStatus.AVAILABLE)
    result = ProviderChain([primary, fallback]).fetch_financials("FPT")
    assert result.provider == "VNStock"
    assert fallback.calls == 0


def test_chain_tries_fallback_when_primary_is_missing() -> None:
    primary = _StubProvider("VNStock", ProviderStatus.MISSING)
    fallback = _StubProvider("yfinance", ProviderStatus.AVAILABLE)
    result = ProviderChain([primary, fallback]).fetch_financials("FPT")
    assert result.provider == "yfinance" and fallback.calls == 1


def test_chain_tries_fallback_when_primary_errors() -> None:
    primary = _StubProvider("VNStock", ProviderStatus.ERROR)
    fallback = _StubProvider("yfinance", ProviderStatus.AVAILABLE)
    result = ProviderChain([primary, fallback]).fetch_financials("FPT")
    assert result.provider == "yfinance"
    assert result.attempted == ("VNStock:ERROR", "yfinance:AVAILABLE")


def test_chain_missing_when_every_provider_is_missing() -> None:
    result = ProviderChain([
        _StubProvider("VNStock", ProviderStatus.MISSING),
        _StubProvider("yfinance", ProviderStatus.MISSING),
    ]).fetch_financials("FPT")
    assert result.status is ProviderStatus.MISSING
    assert result.attempted == ("VNStock:MISSING", "yfinance:MISSING")
    # Issue 4: must not attribute an all-MISSING chain to the last provider
    # tried (e.g. "yfinance") as if it were the authoritative/relied-upon
    # source -- that misleads readers into thinking yfinance was a valid
    # source for this dataset. "none" plus an honest attempted-list reason
    # makes clear no provider in the chain had data.
    assert result.provider == "none"
    assert "VNStock" in result.error_reason
    assert "yfinance" in result.error_reason


def test_chain_missing_institutional_flow_does_not_blame_yfinance() -> None:
    # Issue 4 live evidence: ACB coverage showed
    # "provider=yfinance reason=no provider in the chain had data" for
    # INSTITUTIONAL, implying yfinance was the relied-upon source, when in
    # fact yfinance never claims to carry Vietnamese foreign/proprietary
    # flow and VNStock (the authoritative source) was the one that actually
    # had nothing for this symbol.
    result = ProviderChain([
        _StubProvider("VNStock", ProviderStatus.MISSING),
        _StubProvider("yfinance", ProviderStatus.MISSING),
    ]).fetch_institutional_flow("ACB")
    assert result.status is ProviderStatus.MISSING
    assert result.provider == "none"
    assert result.provider != "yfinance"


def test_chain_survives_an_adapter_that_raises() -> None:
    primary = _StubProvider("VNStock", ProviderStatus.MISSING, raises=True)
    fallback = _StubProvider("yfinance", ProviderStatus.AVAILABLE)
    result = ProviderChain([primary, fallback]).fetch_financials("FPT")
    assert result.provider == "yfinance"


def test_chain_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError, match="at least one provider"):
        ProviderChain([])


def test_vnstock_4_api_financial_finance_is_used_when_legacy_entry_points_are_absent(monkeypatch) -> None:
    """Support vnstock builds that expose Finance only under vnstock.api."""
    from types import SimpleNamespace

    built = []

    class Finance:
        def __init__(self, source, symbol, period="quarter", get_all=True, show_log=False):
            built.append((source, symbol, period))

        def income_statement(self, **kwargs):
            return []

    fake_api = SimpleNamespace(Finance=Finance)
    real = importlib.import_module
    monkeypatch.setattr(importlib, "import_module",
                        lambda name, *a, **k: fake_api if name == "vnstock.api.financial" else real(name, *a, **k))
    provider = VNStockProvider(module=SimpleNamespace(), source_preference=("VCI",))
    handles = provider._finance_handles("FPT")
    assert [label for label, _ in handles] == ["VCI"]
    assert built == [("vci", "FPT", "quarter")]
