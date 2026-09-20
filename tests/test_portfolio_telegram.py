"""Telegram command layer, handlers and formatters for Phase 23."""

import asyncio
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from portfolio.models import PositionSizingResult
from runtime.portfolio_views import PortfolioContextView, WatchlistItemView, WatchlistView
from runtime.views import Freshness
from telegram_bot.app import build_application, build_symbol_keyboard, render_callback
from telegram_bot.commands import HELP_TEXT, TelegramCommandService, UnavailableBotDataService
from telegram_bot.portfolio_commands import PORTFOLIO_UNSUPPORTED
from telegram_bot.portfolio_formatters import (
    format_portfolio_context,
    format_position_size,
    format_watchlist,
    money,
    pct,
    price,
)
from tests.portfolio_fakes import USER, make_runtime


@pytest.fixture()
def bot():
    runtime, client = make_runtime()
    commands = TelegramCommandService(runtime)
    run = lambda name, *args, user=USER: commands.portfolio_command(name, user, list(args))  # noqa: E731
    return commands, run, runtime


def test_watchlist_commands(bot) -> None:
    _, run, _ = bot
    assert "empty" in run("watchlist") and "/addwatch FPT" in run("watchlist")
    assert run("addwatch", "fpt") == "⭐ FPT added to your watchlist."
    assert run("addwatch", "FPT") == "FPT is already on your watchlist."
    run("addwatch", "ACB")
    text = run("watchlist")
    assert text.startswith("⭐ WATCHLIST") and "FPT\n   Price: 160,000" in text and "ACB\n   Price: 24,000" in text
    assert "Price: 160,000" in text and "Trend:" in text and "Strategy:" in text
    assert "Session: 2026-09-18" in text
    assert run("removewatch", "FPT") == "FPT removed from your watchlist."
    assert run("removewatch", "FPT") == "FPT is not on your watchlist."


def test_holding_commands_and_portfolio_output(bot) -> None:
    _, run, _ = bot
    assert "No holdings" in run("portfolio")
    assert run("addholding", "FPT", "1000", "150000") == "💼 FPT: 1,000 shares @ 150,000 added."
    assert "updated" in run("addholding", "FPT", "1000", "150000")
    run("addholding", "ACB", "5000", "22000")
    text = run("portfolio")
    for expected in ("💼 MY PORTFOLIO", "Market value:\n280.0M VND", "Cost:\n260.0M VND",
                     "UNREALIZED P&L:\n+20.0M (+7.7%)", "Holdings:\n2", "1. ACB", "2. FPT",
                     "Weight: 57.1%", "SECTOR EXPOSURE", "Technology: 57.1%", "Banking: 42.9%",
                     "Largest position:\nFPT 57.1%", "⚠ CONCENTRATION", "DATA", "Source: Vietcap historical"):
        assert expected in text, expected
    assert run("removeholding", "ACB") == "ACB removed from your portfolio."
    assert run("removeholding", "ACB") == "You do not hold ACB."


def test_users_are_isolated(bot) -> None:
    _, run, _ = bot
    run("addholding", "FPT", "10", "100000")
    assert "No holdings" in run("portfolio", user=USER + 1)


def test_risk_command(bot) -> None:
    _, run, _ = bot
    assert "No holdings" in run("risk")
    run("addholding", "FPT", "1000", "150000")
    run("addholding", "ACB", "5000", "22000")
    text = run("risk")
    for expected in ("⚠ PORTFOLIO RISK", "Value:\n280.0M", "Holdings:\n2", "Largest position:\nFPT 57.1%",
                     "Largest sector:\nTechnology 57.1%", "Concentration:\nHIGH",
                     "static-weight proxy", "Volatility (annualized):", "Beta vs VNINDEX:", "Max drawdown:"):
        assert expected in text, expected
    assert "Unavailable" not in text  # 260 synthetic sessions are enough


def test_size_command_matches_specification(bot) -> None:
    _, run, _ = bot
    text = run("size", "FPT", "150000", "142000", "500000000", "1")
    for expected in ("📐 POSITION SIZE", "Capital:\n500.0M", "Risk budget:\n1.0%", "Entry:\n150,000",
                     "Stop:\n142,000", "Risk/share:\n8,000", "Max risk:\n5.0M",
                     "Position size under this risk budget:\n625 shares", "Position value:\n93.75M",
                     "Portfolio allocation:\n18.75%", "Risk calculation only; not an execution instruction."):
        assert expected in text, expected
    assert "should buy" not in text.lower()
    assert "Risk budget:\n1.0%" in run("size", "FPT", "150000", "142000", "500000000")  # configured default


def test_size_errors_are_clean(bot) -> None:
    _, run, _ = bot
    assert run("size", "FPT", "150000", "150000", "500000000") == "Stop must be below entry for a long position."
    assert "Risk %" in run("size", "FPT", "150000", "142000", "500000000", "9")
    assert "Capital" in run("size", "FPT", "150000", "142000", "0")
    assert run("size", "FPT", "150000").startswith("Usage:\n/size")


def test_stress_commands(bot) -> None:
    _, run, _ = bot
    run("addholding", "FPT", "1000", "150000")
    run("addholding", "ACB", "5000", "22000")
    portfolio = run("stress", "portfolio", "-5")
    for expected in ("🧪 STRESS TEST", "All holdings -5%", "Current value:\n280.0M", "Estimated loss:\n-14.0M",
                     "Estimated value:\n266.0M", "Impact:\n-5.0%", "not a forecast"):
        assert expected in portfolio, expected
    single = run("stress", "FPT", "-10")
    for expected in ("FPT -10%", "FPT current value:\n160.0M", "Estimated impact:\n-16.0M",
                     "Portfolio impact:\n-5.71%", "New portfolio value:\n264.0M"):
        assert expected in single, expected
    assert run("stress", "HPG", "-10") == "You do not hold HPG."
    assert run("stress", "portfolio", "abc").startswith("Usage:")
    assert "Shock" in run("stress", "portfolio", "-150")


def test_risk_settings_commands(bot) -> None:
    _, run, _ = bot
    assert "1% (configured default)" in run("risksettings") and "Maximum allowed:\n5%" in run("risksettings")
    assert "2% (set by you)" in run("setrisk", "2")
    assert "2% (set by you)" in run("risksettings")
    assert "Risk %" in run("setrisk", "0")
    assert "Risk %" in run("setrisk", "6")
    assert run("setrisk").startswith("Usage:\n/setrisk 1")


@pytest.mark.parametrize("name,args,usage", [
    ("addwatch", [], "/addwatch FPT"), ("addwatch", ["A", "B"], "/addwatch FPT"),
    ("removewatch", [], "/removewatch FPT"),
    ("addholding", ["FPT", "abc", "150000"], "/addholding FPT 1000 150000"),
    ("addholding", ["FPT", "10.5", "150000"], "/addholding FPT 1000 150000"),
    ("addholding", ["FPT", "-5", "150000"], "/addholding FPT 1000 150000"),
    ("addholding", ["FPT", "10", "1e5"], "/addholding FPT 1000 150000"),
    ("addholding", ["FPT", "10"], "/addholding FPT 1000 150000"),
    ("removeholding", [], "/removeholding FPT"),
    ("stress", ["FPT"], "/stress portfolio -5"),
    ("size", ["FPT", "x", "1", "1"], "/size FPT"),
])
def test_malformed_arguments_return_usage_not_exceptions(bot, name, args, usage) -> None:
    _, run, _ = bot
    result = run(name, *args)
    assert result.startswith("Usage:") and usage in result
    assert "Error" not in result and "Traceback" not in result


def test_domain_validation_messages(bot) -> None:
    _, run, _ = bot
    assert "Quantity" in run("addholding", "FPT", "0", "150000")
    assert "Average cost" in run("addholding", "FPT", "10", "0")
    assert "Invalid symbol" in run("addwatch", "F$T")
    assert run("addholding", "NOPE", "10", "1000") == "Symbol not found or unavailable."


def test_unsupported_runtime_and_unknown_user() -> None:
    commands = TelegramCommandService(UnavailableBotDataService())
    assert commands.portfolio_command("portfolio", USER, []) == PORTFOLIO_UNSUPPORTED
    runtime, _ = make_runtime()
    assert "identify" in TelegramCommandService(runtime).portfolio_command("portfolio", None, [])


def test_storage_failure_returns_clean_message(bot) -> None:
    _, run, runtime = bot
    runtime.connection.execute("DROP TABLE watchlist")
    assert run("watchlist") == "Data unavailable."


def test_help_lists_new_commands_and_keeps_old_ones() -> None:
    for command in ("/watchlist", "/addwatch", "/removewatch", "/portfolio", "/addholding",
                    "/removeholding", "/risk", "/size", "/stress", "/setrisk", "/risksettings",
                    "/soi", "/why", "/technical", "/fundamental", "/sector", "/scan", "/market",
                    "/chienluoc", "/performance", "/tin", "/sentiment"):
        assert command in HELP_TEXT


def test_soi_command_passes_user_id_and_stays_backward_compatible(bot) -> None:
    commands, run, _ = bot
    run("addholding", "FPT", "1000", "150000")
    assert "Holding: Yes" in commands.soi(["FPT"], USER)
    assert "PORTFOLIO CONTEXT" not in commands.soi(["FPT"])
    assert render_callback(commands, "asmf", "FPT", USER).count("Holding: Yes") == 1
    assert len(build_symbol_keyboard("FPT").inline_keyboard) == 4  # inline keyboard unchanged


def test_registered_handlers_call_the_service_with_the_telegram_user_id(bot) -> None:
    commands, _, _ = bot
    application = build_application("123456:TEST_TOKEN", commands)
    handlers = {
        name: handler for handler in application.handlers[0]
        for name in getattr(handler, "commands", ())
    }
    replies: list[str] = []

    async def reply_text(text, reply_markup=None):
        replies.append(text)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=USER),
                             effective_message=SimpleNamespace(reply_text=reply_text))

    def call(name, *args):
        asyncio.run(handlers[name].callback(update, SimpleNamespace(args=list(args))))
        return replies[-1]

    assert "added to your watchlist" in call("addwatch", "FPT")
    assert "WATCHLIST" in call("watchlist")
    call("addholding", "FPT", "1000", "150000")
    assert "MY PORTFOLIO" in call("portfolio")
    assert "PORTFOLIO RISK" in call("risk")
    assert "POSITION SIZE" in call("size", "FPT", "150000", "142000", "500000000", "1")
    assert "STRESS TEST" in call("stress", "FPT", "-10")
    assert "Usage:" in call("addholding", "FPT")
    assert commands.portfolio.execute("portfolio", USER + 5, []).startswith("💼 MY PORTFOLIO\n\nNo holdings")


# ------------------------------------------------------------- formatters

def test_number_helpers_never_print_none_nan_or_inf() -> None:
    for value in (None, float("nan"), float("inf"), D("NaN"), D("-Infinity")):
        assert money(value) == "unavailable" and price(value) == "unavailable"
        assert pct(value) == "unavailable"
    assert money(D("535000000")) == "535.0M" and money(D("93750000")) == "93.75M"
    assert money(D("-26750000"), signed=True) == "-26.75M" and money(D("35000000"), signed=True) == "+35.0M"
    assert money(D("1250000000")) == "1.25B" and money(D("950000")) == "950,000"
    assert price(D("160000")) == "160,000" and price(D("22050.5")) == "22,050.50"


def test_watchlist_formatter_handles_missing_values() -> None:
    view = WatchlistView((
        WatchlistItemView("FPT", D("160000"), None, None, "2026-09-18", Freshness.EOD),
        WatchlistItemView("XYZ", None, None, None, None, Freshness.UNAVAILABLE),
    ), None)
    text = format_watchlist(view)
    assert "Trend: unavailable" in text and "Strategy: unavailable" in text
    assert "2. XYZ\n   Price: unavailable" in text
    assert "None" not in text and "nan" not in text.lower()


def test_context_formatter_handles_missing_values() -> None:
    assert format_portfolio_context(None) == ""
    text = format_portfolio_context(PortfolioContextView("FPT", True, 10, None, None, None, None, None,
                                                         "Price unavailable; weight and P&L cannot be computed."))
    assert "Current weight: unavailable" in text and "P&L: unavailable" in text and "None" not in text
    assert format_portfolio_context(PortfolioContextView("FPT", False)).endswith("Holding: No")


def test_position_size_formatter_zero_shares() -> None:
    result = PositionSizingResult("FPT", D("500000"), D("1"), D("150000"), D("142000"), D("5000"),
                                  D("8000"), 0, D("0"), D("0"), D("0"), ("Risk budget is smaller than the risk on a single share.",))
    text = format_position_size(result)
    assert "0 shares" in text and "smaller than the risk" in text