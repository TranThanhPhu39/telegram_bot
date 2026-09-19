"""Tests for the provider-independent latest market-state cache."""

from dataclasses import replace

import pytest

from data.market_state import LatestMarketState
from data.models import TradeTick


def make_tick(symbol: str, price: float) -> TradeTick:
    return TradeTick(
        symbol=symbol,
        price=price,
        volume=1_000.0,
        accumulated_volume=10_000.0,
        accumulated_value=1_000_000.0,
        high_price=price,
        low_price=price,
        open_price=price,
        average_price=price,
        reference_price=price,
        ceiling_price=None,
        floor_price=None,
        exchange_time="10:15:30",
        session="CONTINUOUS",
    )


def test_market_state_stores_fpt_and_acb_by_symbol() -> None:
    state = LatestMarketState()
    fpt = make_tick("FPT", 103.2)
    acb = make_tick("ACB", 25.5)

    assert state.update(fpt) is None
    assert state.update(acb) is None

    assert state.get(" fpt ") is fpt
    assert state.get("acb") is acb
    assert len(state) == 2


def test_market_state_replaces_latest_tick_and_returns_previous() -> None:
    state = LatestMarketState()
    first = make_tick("FPT", 103.2)
    latest = replace(first, price=103.5, exchange_time="10:15:31")

    state.update(first)
    previous = state.update(latest)

    assert previous is first
    assert state.get("FPT") is latest
    assert len(state) == 1


def test_market_state_snapshot_is_read_only_and_point_in_time() -> None:
    state = LatestMarketState()
    fpt = make_tick("FPT", 103.2)
    state.update(fpt)
    snapshot = state.snapshot()

    with pytest.raises(TypeError):
        snapshot["ACB"] = make_tick("ACB", 25.5)  # type: ignore[index]

    state.update(make_tick("ACB", 25.5))

    assert snapshot == {"FPT": fpt}
    assert set(state.snapshot()) == {"FPT", "ACB"}


def test_market_state_rejects_non_trade_tick_values() -> None:
    state = LatestMarketState()

    with pytest.raises(TypeError, match="only TradeTick"):
        state.update(object())  # type: ignore[arg-type]


@pytest.mark.parametrize("symbol", ["", " fpt ", "fpt"])
def test_market_state_rejects_non_normalized_tick_symbols(symbol: str) -> None:
    state = LatestMarketState()

    with pytest.raises(ValueError, match="symbol must be non-empty and normalized"):
        state.update(make_tick(symbol, 103.2))


@pytest.mark.parametrize("symbol", ["", "   "])
def test_market_state_rejects_empty_lookup_symbol(symbol: str) -> None:
    state = LatestMarketState()

    with pytest.raises(ValueError, match="must not be empty"):
        state.get(symbol)
