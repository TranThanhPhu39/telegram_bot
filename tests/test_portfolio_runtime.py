"""Runtime orchestration over the existing history/cache boundary (fake client, no network)."""

from decimal import Decimal as D

import pytest

from portfolio.models import ConcentrationStatus, PortfolioError
from runtime.views import Freshness
from tests.portfolio_fakes import NOW_SUNDAY, USER, make_runtime, series


def hold(runtime, symbol, quantity, cost):
    return runtime.portfolio.upsert_holding(USER, symbol, quantity, D(cost))


def test_portfolio_orchestration_values_holdings_from_runtime_history() -> None:
    runtime, client = make_runtime()
    hold(runtime, "FPT", 1000, "150000")
    hold(runtime, "ACB", 5000, "22000")
    view = runtime.portfolio.portfolio_view(USER)
    snap = view.snapshot
    assert snap.market_value == D("160000000") + D("120000000")
    assert snap.total_cost == D("260000000") and snap.unrealized_pnl == D("20000000")
    assert {e.label for e in snap.sector_exposure} == {"Technology", "Banking"}
    assert view.data_quality.freshness is Freshness.EOD_TODAY
    assert view.data_quality.session_date == "2026-09-18"
    assert view.data_quality.market_source == "Vietcap historical"
    assert all(len(call) == 1 for call in client.calls)  # only the existing per-symbol boundary


def test_sunday_valuation_is_labelled_eod_not_realtime() -> None:
    runtime, _ = make_runtime(now=NOW_SUNDAY)
    hold(runtime, "FPT", 10, "100000")
    quality = runtime.portfolio.portfolio_view(USER).data_quality
    assert quality.freshness is Freshness.EOD and quality.staleness_days == 2
    assert quality.freshness is not Freshness.REALTIME


def test_cached_market_price_is_used_and_labelled_when_provider_fails() -> None:
    runtime, client = make_runtime(now=NOW_SUNDAY)
    hold(runtime, "FPT", 10, "100000")
    runtime.portfolio.portfolio_view(USER)          # populates SQLite through _history
    client.fail = True
    view = runtime.portfolio.portfolio_view(USER)
    assert view.snapshot.holdings[0].price == D("160000.0")
    assert view.data_quality.market_source == "SQLite cache"
    from telegram_bot.portfolio_formatters import format_portfolio
    assert "Cached EOD" in format_portfolio(view)


def test_missing_price_is_flagged_and_not_treated_as_zero() -> None:
    runtime, _ = make_runtime()
    hold(runtime, "FPT", 1000, "150000")
    runtime.portfolio.repository.upsert_holding(USER, "XYZ", 100, D("10000"))  # bypass validation
    view = runtime.portfolio.portfolio_view(USER)
    assert view.snapshot.unpriced_symbols == ("XYZ",)
    assert view.snapshot.market_value == D("160000000")
    from telegram_bot.portfolio_formatters import format_portfolio
    text = format_portfolio(view)
    assert "Valuation incomplete" in text and "Price: unavailable" in text


def test_unknown_symbol_cannot_be_added_to_watchlist_or_portfolio() -> None:
    runtime, _ = make_runtime()
    with pytest.raises(PortfolioError, match="not found or unavailable"):
        runtime.portfolio.add_watch(USER, "NOPE")
    with pytest.raises(PortfolioError, match="not found or unavailable"):
        hold(runtime, "NOPE", 10, "1000")
    assert runtime.portfolio.repository.list_holdings(USER) == ()


def test_watchlist_orchestration() -> None:
    runtime, _ = make_runtime()
    assert runtime.portfolio.watchlist_view(USER).items == ()
    assert runtime.portfolio.add_watch(USER, "fpt") == ("FPT", True)
    assert runtime.portfolio.add_watch(USER, "FPT") == ("FPT", False)
    view = runtime.portfolio.watchlist_view(USER)
    item = view.items[0]
    assert item.symbol == "FPT" and item.price == D("160000.0")
    assert item.trend is not None and item.strategy_state in {"BUY", "SELL", "WATCH", "BLOCKED"}
    assert view.data_quality.session_date == "2026-09-18"
    assert runtime.portfolio.remove_watch(USER, "FPT") == ("FPT", True)
    assert runtime.portfolio.remove_watch(USER, "FPT") == ("FPT", False)


def test_watchlist_item_without_price_says_unavailable() -> None:
    runtime, _ = make_runtime()
    runtime.portfolio.repository.add_watch(USER, "XYZ")
    view = runtime.portfolio.watchlist_view(USER)
    assert view.items[0].price is None and view.data_quality.freshness is Freshness.UNAVAILABLE
    from telegram_bot.portfolio_formatters import format_watchlist
    assert "Price: unavailable" in format_watchlist(view)


def test_stress_view_from_runtime() -> None:
    runtime, _ = make_runtime()
    hold(runtime, "FPT", 1000, "150000")
    hold(runtime, "ACB", 5000, "22000")
    result = runtime.portfolio.stress_view(USER, D("-10"), "FPT").result
    assert result.target_change == D("-16000000") and result.new_portfolio_value == D("264000000")


def test_risk_view_reports_static_weight_historical_metrics() -> None:
    runtime, _ = make_runtime()
    hold(runtime, "FPT", 1000, "150000")
    hold(runtime, "ACB", 5000, "22000")
    assessment = runtime.portfolio.risk_view(USER).assessment
    assert assessment.overall_concentration is ConcentrationStatus.HIGH
    risk = assessment.historical
    assert risk.sessions == 120
    assert risk.annualized_volatility_pct > 0 and risk.max_drawdown_pct <= 0
    assert risk.beta_vs_vnindex is not None


def test_risk_view_with_insufficient_history_is_unavailable_not_fabricated() -> None:
    runtime, _ = make_runtime(closes={
        "FPT": series(160_000.0, count=30), "ACB": series(24_000.0, count=30),
        "VNINDEX": series(1_300.0, count=30),
    })
    hold(runtime, "FPT", 1000, "150000")
    risk = runtime.portfolio.risk_view(USER).assessment.historical
    assert risk.annualized_volatility_pct is None and risk.beta_vs_vnindex is None
    assert risk.max_drawdown_pct is None
    from telegram_bot.portfolio_formatters import format_risk
    text = format_risk(runtime.portfolio.risk_view(USER))
    assert "Unavailable" in text and "None" not in text and "nan" not in text.lower()


def test_risk_settings_default_and_custom_feed_position_sizing() -> None:
    runtime, _ = make_runtime()
    assert runtime.portfolio.risk_settings(USER).default_risk_pct == D("1")
    assert runtime.portfolio.size(USER, "FPT", D("150000"), D("142000"), D("500000000"), None).shares == 625
    runtime.portfolio.set_default_risk(USER, D("2"))
    settings = runtime.portfolio.risk_settings(USER)
    assert settings.default_risk_pct == D("2") and settings.is_custom
    assert runtime.portfolio.size(USER, "FPT", D("150000"), D("142000"), D("500000000"), None).shares == 1250
    assert runtime.portfolio.size(USER, "FPT", D("150000"), D("142000"), D("500000000"), D("0.5")).shares == 312
    with pytest.raises(PortfolioError):
        runtime.portfolio.set_default_risk(USER, D("5.5"))


def test_alert_preparation_hooks() -> None:
    runtime, _ = make_runtime()
    hold(runtime, "FPT", 1, "1")
    runtime.portfolio.add_watch(USER, "ACB")
    repo = runtime.portfolio.repository
    assert repo.is_held(USER, "FPT") and not repo.is_held(USER, "ACB")
    assert repo.is_watched(USER, "ACB") and not repo.is_watched(USER, "FPT")


# ----------------------------------------------------- portfolio-aware /soi

def test_soi_shows_portfolio_context_for_a_held_symbol() -> None:
    runtime, _ = make_runtime()
    hold(runtime, "FPT", 1000, "150000")
    hold(runtime, "ACB", 5000, "22000")
    text = runtime.symbol_overview("FPT", "CL1", user_id=USER)
    assert "PORTFOLIO CONTEXT" in text and "Holding: Yes" in text
    assert "Quantity: 1,000" in text and "Current weight: 57.1%" in text
    assert "P&L: +6.7%" in text and "Sector exposure: Technology 57.1%" in text
    assert "FPT already represents 57.1% of your current portfolio." in text


def test_soi_context_for_a_symbol_not_held_and_without_user() -> None:
    runtime, _ = make_runtime()
    hold(runtime, "ACB", 5000, "22000")
    assert "Holding: No" in runtime.symbol_overview("FPT", "CL1", user_id=USER)
    assert "PORTFOLIO CONTEXT" not in runtime.symbol_overview("FPT")


def test_portfolio_context_never_changes_strategy_output() -> None:
    runtime, _ = make_runtime()
    plain_view = runtime.stock_analysis("FPT", "CL1")
    plain_asmf = runtime.stock_analysis("FPT", "ASMF")
    plain_text = runtime.symbol_overview("FPT", "CL1")
    hold(runtime, "FPT", 1000, "150000")
    assert runtime.stock_analysis("FPT", "CL1") == plain_view
    assert runtime.stock_analysis("FPT", "ASMF") == plain_asmf
    with_context = runtime.symbol_overview("FPT", "CL1", user_id=USER)
    start = with_context.index("💼 PORTFOLIO CONTEXT")
    end = with_context.index("🕒 DỮ LIỆU")
    assert with_context[:start] + with_context[end:] == plain_text
    assert "BUY" not in with_context[start:end] and "MUA" not in with_context[start:end]


def test_soi_context_failure_never_breaks_the_dashboard() -> None:
    runtime, _ = make_runtime()
    runtime.portfolio.repository.connection.execute("DROP TABLE portfolio_holdings")
    text = runtime.symbol_overview("FPT", "CL1", user_id=USER)
    assert "TỔNG QUAN" in text