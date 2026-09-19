"""Tests for the Phase 14 scanner universe and liquidity pre-screen."""

from dataclasses import replace

import pytest

from data.models import OHLCVBar
from scanner.universe import (
    ScannerConfig,
    ScannerInstrument,
    ScreenedSymbol,
    daily_prescreen,
    realtime_watch_universe,
)


CONFIG = ScannerConfig(
    lookback_days=3,
    minimum_average_daily_volume=100_000.0,
    minimum_average_daily_value=2_000_000_000.0,
    maximum_watch_symbols=2,
)


def instrument(
    symbol: str,
    exchange: str = "HOSE",
    instrument_type: str = "STOCK",
    is_active: bool = True,
) -> ScannerInstrument:
    return ScannerInstrument(symbol, exchange, instrument_type, is_active)


def bars(
    symbol: str,
    volumes: list[float],
    *,
    close: float = 30_000.0,
    start: int = 100,
) -> list[OHLCVBar]:
    return [
        OHLCVBar(
            symbol=symbol,
            timeframe="ONE_DAY",
            timestamp=start + index,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=volume,
        )
        for index, volume in enumerate(volumes)
    ]


def test_prescreen_supports_all_three_exchanges_and_common_stock_aliases() -> None:
    instruments = [
        instrument("FPT", "HOSE", "STOCK"),
        instrument("SHS", "HNX", "COMMON_STOCK"),
        instrument("BSR", "UPCOM", "STOCK"),
    ]
    history = {item.symbol: bars(item.symbol, [100_000.0] * 3) for item in instruments}

    result = daily_prescreen(instruments, history, CONFIG, as_of_timestamp=200)

    assert [(item.symbol, item.exchange) for item in result] == [
        ("BSR", "UPCOM"),
        ("FPT", "HOSE"),
        ("SHS", "HNX"),
    ]


@pytest.mark.parametrize("instrument_type", ["ETF", "CW", "FUND", "BOND", "INDEX"])
def test_prescreen_excludes_non_common_instruments(instrument_type: str) -> None:
    item = instrument("TEST", instrument_type=instrument_type)

    assert daily_prescreen(
        [item], {"TEST": bars("TEST", [1_000_000.0] * 3)}, CONFIG, as_of_timestamp=200
    ) == ()


def test_prescreen_excludes_inactive_and_unsupported_exchange() -> None:
    items = [instrument("AAA", is_active=False), instrument("BBB", "OTC")]
    history = {item.symbol: bars(item.symbol, [1_000_000.0] * 3) for item in items}

    assert daily_prescreen(items, history, CONFIG, as_of_timestamp=200) == ()


def test_liquidity_filter_requires_both_volume_and_value_thresholds() -> None:
    items = [instrument("PASS"), instrument("LOWVOL"), instrument("LOWVAL")]
    history = {
        "PASS": bars("PASS", [100_000.0] * 3, close=30_000.0),
        "LOWVOL": bars("LOWVOL", [99_999.0] * 3, close=100_000.0),
        "LOWVAL": bars("LOWVAL", [100_000.0] * 3, close=19_999.0),
    }

    result = daily_prescreen(items, history, CONFIG, as_of_timestamp=200)

    assert [item.symbol for item in result] == ["PASS"]
    assert result[0].average_daily_volume == 100_000.0
    assert result[0].average_daily_value == 3_000_000_000.0
    assert result[0].sessions_used == 3


def test_prescreen_uses_only_latest_completed_lookback_window() -> None:
    history = bars("FPT", [1.0, 100_000.0, 200_000.0, 300_000.0])

    result = daily_prescreen(
        [instrument("FPT")], {"FPT": history}, CONFIG, as_of_timestamp=200
    )

    assert result[0].average_daily_volume == 200_000.0


def test_as_of_boundary_prevents_lookahead() -> None:
    base = bars("FPT", [100_000.0] * 3)
    future = bars("FPT", [100_000.0] * 3 + [999_999_999.0])

    first = daily_prescreen([instrument("FPT")], {"FPT": base}, CONFIG, as_of_timestamp=103)
    second = daily_prescreen([instrument("FPT")], {"FPT": future}, CONFIG, as_of_timestamp=103)

    assert first == second


def test_insufficient_history_is_not_eligible() -> None:
    assert daily_prescreen(
        [instrument("FPT")], {"FPT": bars("FPT", [1_000_000.0] * 2)}, CONFIG, as_of_timestamp=200
    ) == ()


def test_realtime_watch_universe_ranks_value_then_volume_then_symbol() -> None:
    screened = [
        ScreenedSymbol("AAA", "HOSE", 500.0, 5_000.0, 3),
        ScreenedSymbol("BBB", "HNX", 100.0, 10_000.0, 3),
        ScreenedSymbol("CCC", "UPCOM", 200.0, 10_000.0, 3),
        ScreenedSymbol("DDD", "HOSE", 200.0, 10_000.0, 3),
    ]

    assert realtime_watch_universe(screened, CONFIG) == ("CCC", "DDD")


def test_prescreen_output_is_deterministic_regardless_of_input_order() -> None:
    first = instrument("FPT")
    second = instrument("ACB")
    history = {
        "FPT": bars("FPT", [100_000.0] * 3),
        "ACB": bars("ACB", [100_000.0] * 3),
    }

    assert daily_prescreen([first, second], history, CONFIG, as_of_timestamp=200) == daily_prescreen(
        [second, first], history, CONFIG, as_of_timestamp=200
    )


def test_rejects_duplicate_symbols_and_mismatched_history() -> None:
    with pytest.raises(ValueError, match="duplicate instrument"):
        daily_prescreen(
            [instrument("FPT"), instrument("FPT")], {}, CONFIG, as_of_timestamp=200
        )
    with pytest.raises(ValueError, match="does not match"):
        daily_prescreen(
            [instrument("FPT")], {"FPT": bars("ACB", [100_000.0] * 3)}, CONFIG, as_of_timestamp=200
        )


def test_rejects_non_daily_or_non_chronological_history() -> None:
    invalid = bars("FPT", [100_000.0] * 3)
    invalid[0] = replace(invalid[0], timeframe="ONE_MINUTE")
    with pytest.raises(ValueError, match="ONE_DAY"):
        daily_prescreen([instrument("FPT")], {"FPT": invalid}, CONFIG, as_of_timestamp=200)

    history = bars("FPT", [100_000.0] * 3)
    with pytest.raises(ValueError, match="chronological"):
        daily_prescreen([instrument("FPT")], {"FPT": history[::-1]}, CONFIG, as_of_timestamp=200)


def test_configuration_and_instrument_validation() -> None:
    with pytest.raises(ValueError, match="lookback_days"):
        ScannerConfig(0, 0.0, 0.0, 1)
    with pytest.raises(ValueError, match="minimum_average_daily_value"):
        ScannerConfig(1, 0.0, -1.0, 1)
    with pytest.raises(ValueError, match="normalized"):
        instrument("fpt")
