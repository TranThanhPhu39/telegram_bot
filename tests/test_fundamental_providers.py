"""Provider layer: contracts, VNStock discovery, yfinance fallback, chain."""

from __future__ import annotations

from datetime import date
import types

import pytest

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
from fundamentals.providers.provider_chain import ProviderChain
from fundamentals.providers.vnstock_provider import VNStockProvider
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
    # Only TCBS is registered; VCI (tried first) is simply absent from this release.
    provider = VNStockProvider(module=_vnstock_module({"TCBS": stock}))
    result = provider.fetch_financials("FPT")
    assert result.provider_source == "TCBS"


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


def test_vnstock_not_installed_returns_missing_without_raising() -> None:
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


def test_chain_survives_an_adapter_that_raises() -> None:
    primary = _StubProvider("VNStock", ProviderStatus.MISSING, raises=True)
    fallback = _StubProvider("yfinance", ProviderStatus.AVAILABLE)
    result = ProviderChain([primary, fallback]).fetch_financials("FPT")
    assert result.provider == "yfinance"


def test_chain_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError, match="at least one provider"):
        ProviderChain([])


def test_vnstock_4_api_financial_finance_is_used_when_legacy_entry_points_are_absent(monkeypatch) -> None:
    """Phase 26 live finding: vnstock 4.x has no top-level Vnstock()/Finance."""
    import importlib
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
