"""Provider-independent in-memory market state."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from types import MappingProxyType

from data.models import TradeTick


class LatestMarketState:
    """Thread-safe cache containing the latest received trade for each symbol."""

    def __init__(self) -> None:
        self._ticks: dict[str, TradeTick] = {}
        self._lock = RLock()

    def update(self, tick: TradeTick) -> TradeTick | None:
        """Store a normalized tick and return the previously cached value."""
        if not isinstance(tick, TradeTick):
            raise TypeError("LatestMarketState accepts only TradeTick values")
        if not tick.symbol or tick.symbol != tick.symbol.strip().upper():
            raise ValueError("TradeTick symbol must be non-empty and normalized")

        with self._lock:
            previous = self._ticks.get(tick.symbol)
            self._ticks[tick.symbol] = tick
            return previous

    def get(self, symbol: str) -> TradeTick | None:
        """Return the latest tick for a symbol, if present."""
        if not isinstance(symbol, str):
            raise TypeError("Symbol must be a string")
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("Symbol must not be empty")

        with self._lock:
            return self._ticks.get(normalized)

    def snapshot(self) -> Mapping[str, TradeTick]:
        """Return a read-only point-in-time copy of all cached ticks."""
        with self._lock:
            return MappingProxyType(self._ticks.copy())

    def __len__(self) -> int:
        with self._lock:
            return len(self._ticks)
