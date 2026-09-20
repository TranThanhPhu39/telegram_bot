"""Pure Phase 23 portfolio maths and boundary tests (no SQLite or network)."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from portfolio.config import PortfolioConfig
from portfolio.models import (
    ConcentrationStatus,
    PortfolioError,
    PortfolioHolding,
    PriceQuote,
    SectorInfo,
)
from portfolio.position_sizing import size_position
from portfolio.risk import classify, historical_risk, worst_status
from portfolio.stress import stress_test
from portfolio.valuation import build_snapshot
from runtime.views import Freshness


def holding(symbol="FPT", quantity=1000, cost="100"):
    return PortfolioHolding(1, symbol, quantity, D(cost), 1)


def quote(symbol="FPT", price="120", session="2026-09-18", freshness=Freshness.EOD):
    return PriceQuote(symbol, None if price is None else D(price), session, freshness, "test", 1)


def snapshot(*holdings, quotes=None, sectors=None, config=None):
    holdings = holdings or (holding(),)
    if quotes is None:
        quotes = {item.symbol: quote(item.symbol) for item in holdings}
    if sectors is None:
        sectors = {}
    return build_snapshot(holdings, quotes, sectors, config or PortfolioConfig())


def closes(start, count=70, drift=0.01):
    first = date(2026, 1, 1)
    value = float(start)
    result = {}
    for offset in range(count):
        result[(first + timedelta(days=offset)).isoformat()] = value
        value *= 1.0 + drift + (0.002 if offset % 2 else -0.001)
    return result


def test_config_defaults_are_ordered_and_conservative() -> None:
    config = PortfolioConfig()
    assert config.single_stock_warning_pct < config.single_stock_high_pct
    assert config.sector_warning_pct < config.sector_high_pct
    assert config.default_risk_per_trade_pct <= config.max_risk_per_trade_pct
    assert config.risk_lookback >= config.risk_min_sessions


def test_config_from_env_parses_every_phase_23_setting() -> None:
    config = PortfolioConfig.from_env({
        "PORTFOLIO_SINGLE_STOCK_WARNING_PCT": "20.5",
        "PORTFOLIO_SINGLE_STOCK_HIGH_PCT": "35",
        "PORTFOLIO_SECTOR_WARNING_PCT": "45",
        "PORTFOLIO_SECTOR_HIGH_PCT": "70",
        "DEFAULT_RISK_PER_TRADE_PCT": ".75",
        "MAX_RISK_PER_TRADE_PCT": "3",
        "PORTFOLIO_RISK_LOOKBACK": "100",
        "PORTFOLIO_RISK_MIN_SESSIONS": "50",
    })
    assert config.single_stock_warning_pct == D("20.5")
    assert config.default_risk_per_trade_pct == D(".75")
    assert config.risk_lookback == 100 and config.risk_min_sessions == 50


@pytest.mark.parametrize("env", [
    {"PORTFOLIO_SINGLE_STOCK_WARNING_PCT": "40", "PORTFOLIO_SINGLE_STOCK_HIGH_PCT": "40"},
    {"PORTFOLIO_SECTOR_WARNING_PCT": "0"},
    {"DEFAULT_RISK_PER_TRADE_PCT": "6", "MAX_RISK_PER_TRADE_PCT": "5"},
    {"MAX_RISK_PER_TRADE_PCT": "101"},
    {"PORTFOLIO_RISK_LOOKBACK": "59", "PORTFOLIO_RISK_MIN_SESSIONS": "60"},
    {"PORTFOLIO_RISK_LOOKBACK": "abc"},
    {"DEFAULT_RISK_PER_TRADE_PCT": "NaN"},
])
def test_config_rejects_invalid_values(env) -> None:
    with pytest.raises(ValueError):
        PortfolioConfig.from_env(env)


@pytest.mark.parametrize(("weight", "expected"), [
    ("0", ConcentrationStatus.NORMAL),
    ("24.999", ConcentrationStatus.NORMAL),
    ("25", ConcentrationStatus.WARNING),
    ("39.999", ConcentrationStatus.WARNING),
    ("40", ConcentrationStatus.HIGH),
    ("100", ConcentrationStatus.HIGH),
])
def test_concentration_thresholds_are_inclusive(weight, expected) -> None:
    assert classify(D(weight), D("25"), D("40")) is expected


def test_worst_status_uses_severity_not_input_order() -> None:
    assert worst_status([
        ConcentrationStatus.WARNING, ConcentrationStatus.NORMAL, ConcentrationStatus.HIGH
    ]) is ConcentrationStatus.HIGH
    assert worst_status([]) is ConcentrationStatus.NORMAL


def test_snapshot_values_cost_pnl_weights_and_sectors() -> None:
    fpt = holding("FPT", 1000, "100")
    acb = holding("ACB", 2000, "20")
    result = snapshot(
        fpt, acb,
        quotes={"FPT": quote("FPT", "120"), "ACB": quote("ACB", "25")},
        sectors={
            "FPT": SectorInfo("TECH", "Technology"),
            "ACB": SectorInfo("BANK", "Banking"),
        },
    )
    assert result.total_cost == D("140000")
    assert result.market_value == D("170000")
    assert result.unrealized_pnl == D("30000")
    assert result.unrealized_pnl_pct == D("30000") / D("140000") * 100
    assert sum(item.weight_pct for item in result.priced_holdings) == D("100")
    assert {item.label for item in result.sector_exposure} == {"Technology", "Banking"}


def test_unpriced_holding_is_excluded_and_never_valued_as_zero() -> None:
    result = snapshot(
        holding("FPT", 1, "100"), holding("XYZ", 5, "500"),
        quotes={"FPT": quote("FPT", "120"), "XYZ": quote("XYZ", None, None, Freshness.UNAVAILABLE)},
    )
    assert result.market_value == D("120") and result.total_cost == D("100")
    assert result.unpriced_symbols == ("XYZ",) and not result.complete
    assert result.holdings[1].market_value is None
    assert "excluded from value" in result.notes[0]


def test_missing_quote_mapping_is_unavailable() -> None:
    result = snapshot(holding(), quotes={}, sectors={})
    assert result.priced_holdings == ()
    assert result.freshness is Freshness.UNAVAILABLE
    assert result.market_value == 0


def test_unknown_sector_is_exposure_context_not_a_sector_warning() -> None:
    result = snapshot(holding(), sectors={})
    assert result.sector_exposure[0].label == "Unknown"
    assert result.largest_sector is None
    assert all(item.kind != "SECTOR" for item in result.concentration)


def test_mixed_sessions_and_worst_freshness_are_exposed() -> None:
    result = snapshot(
        holding("FPT"), holding("ACB"),
        quotes={
            "FPT": quote("FPT", "120", "2026-09-18", Freshness.EOD),
            "ACB": quote("ACB", "25", "2026-09-17", Freshness.STALE),
        },
    )
    assert result.session_dates == ("2026-09-17", "2026-09-18")
    assert result.freshness is Freshness.STALE
    assert "different sessions" in result.notes[0]


def test_concentration_warnings_apply_at_exact_boundaries() -> None:
    config = PortfolioConfig(
        single_stock_warning_pct=D("25"), single_stock_high_pct=D("40"),
        sector_warning_pct=D("40"), sector_high_pct=D("60"),
    )
    result = snapshot(
        holding("FPT", 40, "1"), holding("ACB", 60, "1"),
        quotes={"FPT": quote("FPT", "1"), "ACB": quote("ACB", "1")},
        sectors={
            "FPT": SectorInfo("TECH", "Technology"),
            "ACB": SectorInfo("BANK", "Banking"),
        },
        config=config,
    )
    by_subject = {item.subject: item.status for item in result.concentration}
    assert by_subject["FPT"] is ConcentrationStatus.HIGH
    assert by_subject["ACB"] is ConcentrationStatus.HIGH
    assert by_subject["Technology"] is ConcentrationStatus.WARNING
    assert by_subject["Banking"] is ConcentrationStatus.HIGH


def test_position_sizing_matches_fixed_fractional_math() -> None:
    result = size_position("FPT", D("150000"), D("142000"), D("500000000"), D("1"), D("5"))
    assert result.risk_budget == D("5000000")
    assert result.risk_per_share == D("8000")
    assert result.shares == 625 and result.position_value == D("93750000")
    assert result.max_loss == D("5000000") and result.allocation_pct == D("18.75")


def test_position_sizing_caps_at_cash_without_leverage() -> None:
    result = size_position("FPT", D("150"), D("149"), D("1000"), D("5"), D("5"))
    assert result.shares == 6 and result.position_value == D("900")
    assert result.max_loss == D("6")
    assert "Capped by available capital; no leverage is assumed." in result.notes


def test_position_sizing_can_return_zero_shares_honestly() -> None:
    result = size_position("FPT", D("100"), D("50"), D("100"), D("1"), D("5"))
    assert result.shares == 0 and result.position_value == 0 and result.max_loss == 0
    assert any("single share" in note for note in result.notes)


@pytest.mark.parametrize(("entry", "stop", "capital", "risk", "message"), [
    ("0", "1", "100", "1", "Entry"),
    ("100", "0", "100", "1", "Stop"),
    ("100", "90", "0", "1", "Capital"),
    ("100", "100", "100", "1", "Stop must be below"),
    ("100", "101", "100", "1", "Stop must be below"),
    ("100", "90", "100", "0", "Risk %"),
    ("100", "90", "100", "6", "Risk %"),
])
def test_position_sizing_rejects_invalid_inputs(entry, stop, capital, risk, message) -> None:
    with pytest.raises(PortfolioError, match=message):
        size_position("FPT", D(entry), D(stop), D(capital), D(risk), D("5"))


def test_historical_risk_reports_metrics_for_aligned_daily_series() -> None:
    risk = historical_risk(
        {"FPT": D("60"), "ACB": D("40")},
        {"FPT": closes(100, drift=.01), "ACB": closes(50, drift=.005)},
        closes(1000, drift=.007), lookback=60, min_sessions=50,
    )
    assert risk.sessions == 60
    assert risk.annualized_volatility_pct is not None
    assert risk.max_drawdown_pct == pytest.approx(0)
    assert risk.beta_vs_vnindex is not None
    assert risk.unavailable_reason is None


def test_historical_risk_fails_closed_when_history_is_short() -> None:
    risk = historical_risk(
        {"FPT": D("100")}, {"FPT": closes(100, count=20)}, closes(1000, count=20),
        lookback=60, min_sessions=30,
    )
    assert risk.sessions is None and risk.annualized_volatility_pct is None
    assert "need 30" in risk.unavailable_reason


def test_historical_risk_without_priced_holdings_is_unavailable() -> None:
    risk = historical_risk({}, {}, None, lookback=60, min_sessions=30)
    assert risk.unavailable_reason == "No priced holdings."


def test_historical_risk_can_report_portfolio_metrics_without_beta() -> None:
    risk = historical_risk(
        {"FPT": D("100")}, {"FPT": closes(100)}, None,
        lookback=60, min_sessions=50,
    )
    assert risk.sessions == 60 and risk.annualized_volatility_pct is not None
    assert risk.beta_vs_vnindex is None
    assert risk.beta_unavailable_reason == "VNINDEX history unavailable."


def test_historical_beta_rejects_zero_market_variance() -> None:
    market = {key: 1000.0 for key in closes(1000)}
    risk = historical_risk(
        {"FPT": D("100")}, {"FPT": closes(100)}, market,
        lookback=60, min_sessions=50,
    )
    assert risk.beta_vs_vnindex is None
    assert risk.beta_unavailable_reason == "VNINDEX variance is zero over the window."


def test_portfolio_stress_is_deterministic_arithmetic() -> None:
    result = stress_test(snapshot(), D("-10"))
    assert result.scenario == "PORTFOLIO"
    assert result.current_value == D("120000")
    assert result.target_change == D("-12000")
    assert result.new_portfolio_value == D("108000")
    assert result.portfolio_impact_pct == D("-10")


def test_single_symbol_stress_only_changes_that_holding() -> None:
    snap = snapshot(
        holding("FPT", 1000, "100"), holding("ACB", 2000, "20"),
        quotes={"FPT": quote("FPT", "120"), "ACB": quote("ACB", "25")},
    )
    result = stress_test(snap, D("-10"), "fpt")
    assert result.scenario == "SYMBOL" and result.symbol == "FPT"
    assert result.target_change == D("-12000")
    assert result.new_portfolio_value == D("158000")
    assert result.portfolio_impact_pct == D("-12000") / D("170000") * 100


@pytest.mark.parametrize("shock", [D("-100.01"), D("100.01"), D("NaN"), D("Infinity")])
def test_stress_rejects_invalid_shocks(shock) -> None:
    with pytest.raises(PortfolioError, match="between -100 and 100"):
        stress_test(snapshot(), shock)


def test_stress_rejects_empty_or_unpriced_portfolios() -> None:
    empty = build_snapshot((), {}, {}, PortfolioConfig())
    with pytest.raises(PortfolioError, match="empty"):
        stress_test(empty, D("-5"))
    unpriced = snapshot(holding(), quotes={"FPT": quote("FPT", None, None, Freshness.UNAVAILABLE)})
    with pytest.raises(PortfolioError, match="no holding has a usable price"):
        stress_test(unpriced, D("-5"))


def test_stress_rejects_unknown_or_unpriced_target_symbol() -> None:
    snap = snapshot(
        holding("FPT"), holding("XYZ"),
        quotes={"FPT": quote("FPT"), "XYZ": quote("XYZ", None, None, Freshness.UNAVAILABLE)},
    )
    with pytest.raises(PortfolioError, match="do not hold ACB"):
        stress_test(snap, D("-5"), "ACB")
    with pytest.raises(PortfolioError, match="Price unavailable for XYZ"):
        stress_test(snap, D("-5"), "XYZ")
