"""Daily liquidity pre-screen and bounded realtime watch universe."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Sequence

from data.models import OHLCVBar


SUPPORTED_EXCHANGES = frozenset({"HOSE", "HNX", "UPCOM"})
COMMON_STOCK_TYPES = frozenset({"STOCK", "COMMON_STOCK"})


@dataclass(frozen=True, slots=True)
class ScannerInstrument:
    symbol: str
    exchange: str
    instrument_type: str
    is_active: bool = True

    def __post_init__(self) -> None:
        for name in ("symbol", "exchange", "instrument_type"):
            value = getattr(self, name)
            if not value or value != value.strip().upper():
                raise ValueError(f"{name} must be non-empty and normalized")
        if not isinstance(self.is_active, bool):
            raise TypeError("is_active must be a bool")


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    lookback_days: int
    minimum_average_daily_volume: float
    minimum_average_daily_value: float
    maximum_watch_symbols: int

    def __post_init__(self) -> None:
        for name in ("lookback_days", "maximum_watch_symbols"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        for name in (
            "minimum_average_daily_volume",
            "minimum_average_daily_value",
        ):
            value = getattr(self, name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class ScreenedSymbol:
    symbol: str
    exchange: str
    average_daily_volume: float
    average_daily_value: float
    sessions_used: int


def daily_prescreen(
    instruments: Sequence[ScannerInstrument],
    daily_history: Mapping[str, Sequence[OHLCVBar]],
    config: ScannerConfig,
    *,
    as_of_timestamp: int,
) -> tuple[ScreenedSymbol, ...]:
    """Select liquid common stocks using completed daily bars before ``as_of``."""
    if not isinstance(config, ScannerConfig):
        raise TypeError("config must be a ScannerConfig")
    if not isinstance(as_of_timestamp, int) or isinstance(as_of_timestamp, bool):
        raise TypeError("as_of_timestamp must be an integer")
    if as_of_timestamp <= 0:
        raise ValueError("as_of_timestamp must be positive")

    seen: set[str] = set()
    selected: list[ScreenedSymbol] = []
    for instrument in instruments:
        if not isinstance(instrument, ScannerInstrument):
            raise TypeError("instruments must contain ScannerInstrument values")
        if instrument.symbol in seen:
            raise ValueError(f"duplicate instrument symbol: {instrument.symbol}")
        seen.add(instrument.symbol)
        if (
            not instrument.is_active
            or instrument.exchange not in SUPPORTED_EXCHANGES
            or instrument.instrument_type not in COMMON_STOCK_TYPES
        ):
            continue

        bars = _validate_history(instrument.symbol, daily_history.get(instrument.symbol, ()))
        completed = tuple(bar for bar in bars if bar.timestamp < as_of_timestamp)
        if len(completed) < config.lookback_days:
            continue
        window = completed[-config.lookback_days :]
        average_volume = sum(bar.volume for bar in window) / config.lookback_days
        average_value = (
            sum(bar.close * bar.volume for bar in window) / config.lookback_days
        )
        if (
            average_volume < config.minimum_average_daily_volume
            or average_value < config.minimum_average_daily_value
        ):
            continue
        selected.append(
            ScreenedSymbol(
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                average_daily_volume=average_volume,
                average_daily_value=average_value,
                sessions_used=config.lookback_days,
            )
        )

    return tuple(sorted(selected, key=lambda item: item.symbol))


def realtime_watch_universe(
    screened: Sequence[ScreenedSymbol], config: ScannerConfig
) -> tuple[str, ...]:
    """Return the most liquid bounded watch list with deterministic ordering."""
    if not isinstance(config, ScannerConfig):
        raise TypeError("config must be a ScannerConfig")
    checked: list[ScreenedSymbol] = []
    seen: set[str] = set()
    for item in screened:
        if not isinstance(item, ScreenedSymbol):
            raise TypeError("screened must contain ScreenedSymbol values")
        if item.symbol in seen:
            raise ValueError(f"duplicate screened symbol: {item.symbol}")
        seen.add(item.symbol)
        checked.append(item)
    ranked = sorted(
        checked,
        key=lambda item: (
            -item.average_daily_value,
            -item.average_daily_volume,
            item.symbol,
        ),
    )
    return tuple(item.symbol for item in ranked[: config.maximum_watch_symbols])


def _validate_history(
    symbol: str, bars: Sequence[OHLCVBar]
) -> tuple[OHLCVBar, ...]:
    checked = tuple(bars)
    previous_timestamp: int | None = None
    for bar in checked:
        if not isinstance(bar, OHLCVBar):
            raise TypeError("daily history must contain OHLCVBar values")
        if bar.symbol != symbol:
            raise ValueError("daily history symbol does not match instrument")
        if bar.timeframe != "ONE_DAY":
            raise ValueError("scanner liquidity history requires ONE_DAY bars")
        if previous_timestamp is not None and bar.timestamp <= previous_timestamp:
            raise ValueError("daily history must be strictly chronological")
        values = (bar.close, bar.volume)
        if not all(isfinite(value) for value in values):
            raise ValueError("daily liquidity values must be finite")
        if bar.close <= 0 or bar.volume < 0:
            raise ValueError("daily close must be positive and volume non-negative")
        previous_timestamp = bar.timestamp
    return checked
