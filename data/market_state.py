"""Provider-independent in-memory market state."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from types import MappingProxyType

from data.models import IndexSnapshot, OrderBook, TradeTick


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


class LatestIndexState:
    """Thread-safe cache containing the latest snapshot for each index."""

    def __init__(self) -> None:
        self._snapshots: dict[str, IndexSnapshot] = {}
        self._lock = RLock()

    def update(self, snapshot: IndexSnapshot) -> IndexSnapshot | None:
        """Store a normalized index snapshot and return the previous value."""
        if not isinstance(snapshot, IndexSnapshot):
            raise TypeError("LatestIndexState accepts only IndexSnapshot values")
        if (
            not snapshot.symbol
            or snapshot.symbol != snapshot.symbol.strip().upper()
        ):
            raise ValueError(
                "IndexSnapshot symbol must be non-empty and normalized"
            )

        with self._lock:
            previous = self._snapshots.get(snapshot.symbol)
            self._snapshots[snapshot.symbol] = snapshot
            return previous

    def get(self, symbol: str) -> IndexSnapshot | None:
        """Return the latest snapshot for an index, if present."""
        if not isinstance(symbol, str):
            raise TypeError("Symbol must be a string")
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("Symbol must not be empty")

        with self._lock:
            return self._snapshots.get(normalized)

    def snapshot(self) -> Mapping[str, IndexSnapshot]:
        """Return a read-only point-in-time copy of all cached indices."""
        with self._lock:
            return MappingProxyType(self._snapshots.copy())

    def __len__(self) -> int:
        with self._lock:
            return len(self._snapshots)


class LatestOrderBookState:
    """Thread-safe cache containing the latest order book for each symbol."""

    def __init__(self) -> None:
        self._books: dict[str, OrderBook] = {}
        self._lock = RLock()

    def update(self, book: OrderBook) -> OrderBook | None:
        """Store a normalized order book and return the previous value."""
        if not isinstance(book, OrderBook):
            raise TypeError("LatestOrderBookState accepts only OrderBook values")
        if not book.symbol or book.symbol != book.symbol.strip().upper():
            raise ValueError("OrderBook symbol must be non-empty and normalized")

        with self._lock:
            previous = self._books.get(book.symbol)
            self._books[book.symbol] = book
            return previous

    def get(self, symbol: str) -> OrderBook | None:
        """Return the latest order book for a symbol, if present."""
        if not isinstance(symbol, str):
            raise TypeError("Symbol must be a string")
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("Symbol must not be empty")

        with self._lock:
            return self._books.get(normalized)

    def snapshot(self) -> Mapping[str, OrderBook]:
        """Return a read-only point-in-time copy of all cached order books."""
        with self._lock:
            return MappingProxyType(self._books.copy())

    def __len__(self) -> int:
        with self._lock:
            return len(self._books)