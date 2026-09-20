"""Watchlist and holdings persistence (repository level)."""

from decimal import Decimal

import pytest

from data.database import connect_database
from data.migrations import bootstrap_schema
from portfolio.models import PortfolioError
from portfolio.repository import SQLitePortfolioRepository, normalize_symbol


@pytest.fixture()
def repo():
    connection = connect_database("sqlite:///:memory:")
    bootstrap_schema(connection)
    return SQLitePortfolioRepository(connection, now=lambda: 1_800_000_000)


def test_user_is_created_once_by_telegram_numeric_id(repo) -> None:
    first = repo.ensure_user(42)
    second = repo.ensure_user(42)
    assert first.telegram_user_id == 42 and first == second
    assert first.risk_profile is None and first.default_risk_per_trade_pct is None
    with pytest.raises(PortfolioError):
        repo.ensure_user(0)


def test_add_watch_is_normalized_and_deduplicated(repo) -> None:
    assert repo.add_watch(1, " fpt ") is True
    assert repo.add_watch(1, "FPT") is False
    assert [e.symbol for e in repo.list_watchlist(1)] == ["FPT"]
    assert repo.is_watched(1, "fpt") and not repo.is_watched(2, "FPT")


def test_watchlists_are_per_user(repo) -> None:
    repo.add_watch(1, "FPT")
    repo.add_watch(2, "ACB")
    assert [e.symbol for e in repo.list_watchlist(1)] == ["FPT"]
    assert [e.symbol for e in repo.list_watchlist(2)] == ["ACB"]


def test_remove_watch_and_remove_missing_are_safe(repo) -> None:
    repo.add_watch(1, "FPT")
    assert repo.remove_watch(1, "FPT") is True
    assert repo.remove_watch(1, "FPT") is False
    assert repo.list_watchlist(1) == ()


def test_empty_watchlist_and_empty_portfolio(repo) -> None:
    assert repo.list_watchlist(99) == ()
    assert repo.list_holdings(99) == ()


@pytest.mark.parametrize("raw", ["", "  ", "F T", "FPT!", "1FPT", "A", "TOOLONGSYMBOL", None, 12])
def test_invalid_symbols_are_rejected(repo, raw) -> None:
    with pytest.raises(PortfolioError, match="Invalid symbol"):
        repo.add_watch(1, raw)


def test_indices_are_not_stocks() -> None:
    with pytest.raises(PortfolioError, match="index"):
        normalize_symbol("vnindex")


def test_add_and_update_holding(repo) -> None:
    assert repo.upsert_holding(1, "fpt", 1000, Decimal("150000")) is True
    assert repo.upsert_holding(1, "FPT", 500, Decimal("155000.5")) is False
    holding = repo.get_holding(1, "FPT")
    assert holding.quantity == 500 and holding.average_cost == Decimal("155000.5")
    assert len(repo.list_holdings(1)) == 1
    assert repo.is_held(1, "FPT") and not repo.is_held(1, "ACB")


def test_remove_holding(repo) -> None:
    repo.upsert_holding(1, "FPT", 10, Decimal("100"))
    assert repo.remove_holding(1, "FPT") is True
    assert repo.remove_holding(1, "FPT") is False
    assert repo.get_holding(1, "FPT") is None


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "10"])
def test_invalid_quantity_is_rejected(repo, quantity) -> None:
    with pytest.raises(PortfolioError, match="Quantity"):
        repo.upsert_holding(1, "FPT", quantity, Decimal("100"))


@pytest.mark.parametrize("cost", [Decimal("0"), Decimal("-5"), Decimal("NaN"), Decimal("Infinity"), 100.0])
def test_invalid_average_cost_is_rejected(repo, cost) -> None:
    with pytest.raises(PortfolioError, match="Average cost"):
        repo.upsert_holding(1, "FPT", 10, cost)


def test_default_risk_is_stored_per_user(repo) -> None:
    repo.set_default_risk(1, Decimal("2.5"))
    assert repo.get_user(1).default_risk_per_trade_pct == Decimal("2.5")
    assert repo.get_user(2) is None


def test_data_persists_across_connections(tmp_path) -> None:
    url = f"sqlite:///{(tmp_path / 'p.sqlite3').as_posix()}"
    first = connect_database(url)
    bootstrap_schema(first)
    SQLitePortfolioRepository(first).upsert_holding(9, "ACB", 5, Decimal("22000"))
    first.close()
    second = connect_database(url)
    bootstrap_schema(second)
    assert SQLitePortfolioRepository(second).get_holding(9, "ACB").quantity == 5