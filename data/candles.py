"""Provider-independent one-minute candle construction."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from data.models import OHLCVBar, TradeTick


ONE_MINUTE_SECONDS = 60
ONE_MINUTE_TIMEFRAME = "ONE_MINUTE"


@dataclass(slots=True)
class _MutableBar:
    symbol: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def add(self, price: float, volume: float) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += volume

    def freeze(self) -> OHLCVBar:
        return OHLCVBar(
            symbol=self.symbol,
            timeframe=ONE_MINUTE_TIMEFRAME,
            timestamp=self.timestamp,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


class OneMinuteBarBuilder:
    """Aggregate normalized trades into one-minute OHLCV bars.

    The caller supplies an integer Unix timestamp for each tick because the
    provider's exchange-time string has not yet been proven stable. A bar is
    emitted only when a later minute for the same symbol arrives or on
    :meth:`flush`; missing minutes are not synthesized.
    """

    def __init__(self) -> None:
        self._active: dict[str, _MutableBar] = {}

    def update(self, tick: TradeTick, timestamp: int) -> OHLCVBar | None:
        """Add one tick and return a completed prior-minute bar, if any."""
        if not isinstance(tick, TradeTick):
            raise TypeError("OneMinuteBarBuilder accepts only TradeTick values")
        if not isinstance(timestamp, int) or isinstance(timestamp, bool):
            raise TypeError("timestamp must be an integer Unix-seconds value")
        if timestamp <= 0:
            raise ValueError("timestamp must be positive")
        if not tick.symbol or tick.symbol != tick.symbol.strip().upper():
            raise ValueError("TradeTick symbol must be non-empty and normalized")
        if not isfinite(tick.price) or tick.price <= 0:
            raise ValueError("TradeTick price must be finite and positive")
        if not isfinite(tick.volume) or tick.volume < 0:
            raise ValueError("TradeTick volume must be finite and non-negative")

        bucket = timestamp - timestamp % ONE_MINUTE_SECONDS
        current = self._active.get(tick.symbol)
        if current is None:
            self._active[tick.symbol] = self._new_bar(tick, bucket)
            return None
        if bucket < current.timestamp:
            raise ValueError("out-of-order tick precedes the active minute")
        if bucket == current.timestamp:
            current.add(tick.price, tick.volume)
            return None

        completed = current.freeze()
        self._active[tick.symbol] = self._new_bar(tick, bucket)
        return completed

    def flush(self, symbol: str | None = None) -> tuple[OHLCVBar, ...]:
        """Finalize active bars for one symbol or every symbol."""
        if symbol is not None:
            if not isinstance(symbol, str):
                raise TypeError("symbol must be a string")
            normalized = symbol.strip().upper()
            if not normalized:
                raise ValueError("symbol must not be empty")
            bar = self._active.pop(normalized, None)
            return () if bar is None else (bar.freeze(),)

        bars = tuple(
            self._active[key].freeze()
            for key in sorted(self._active, key=lambda key: (self._active[key].timestamp, key))
        )
        self._active.clear()
        return bars

    @staticmethod
    def _new_bar(tick: TradeTick, timestamp: int) -> _MutableBar:
        return _MutableBar(
            symbol=tick.symbol,
            timestamp=timestamp,
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            volume=tick.volume,
        )
