"""Vietcap event pipeline from binary payloads to normalized market state."""

from __future__ import annotations

from collections.abc import Iterable
import logging

from data.market_state import (
    LatestIndexState,
    LatestMarketState,
    LatestOrderBookState,
)
from data.models import IndexSnapshot, OrderBook, TradeTick
from data.vietcap.decoder import (
    decode_bid_ask,
    decode_index,
    decode_match_price,
)
from data.vietcap.normalizer import (
    normalize_bid_ask,
    normalize_index,
    normalize_match_price,
)
from data.vietcap.subscriptions import normalize_index_symbols, normalize_symbols

logger = logging.getLogger(__name__)


class MatchPriceStatePipeline:
    """Decode expected match-price events into the latest market state."""

    def __init__(
        self,
        state: LatestMarketState,
        expected_symbols: Iterable[str],
    ) -> None:
        if not isinstance(state, LatestMarketState):
            raise TypeError("state must be a LatestMarketState")
        self._state = state
        self._expected_symbols = frozenset(normalize_symbols(expected_symbols))

    @property
    def expected_symbols(self) -> frozenset[str]:
        """Return the normalized symbols accepted by this pipeline."""
        return self._expected_symbols

    def handle(self, payload: object) -> TradeTick | None:
        """Decode, normalize, filter, and cache one match-price payload."""
        try:
            message = decode_match_price(payload)  # type: ignore[arg-type]
            tick = normalize_match_price(message)
        except (TypeError, ValueError):
            logger.exception("Rejected Vietcap match-price payload")
            return None

        if tick.symbol not in self._expected_symbols:
            logger.warning(
                "Ignoring unexpected match-price symbol",
                extra={
                    "expected_symbols": sorted(self._expected_symbols),
                    "symbol": tick.symbol,
                },
            )
            return None

        self._state.update(tick)
        return tick


class IndexStatePipeline:
    """Decode expected index events into the latest index state."""

    def __init__(
        self,
        state: LatestIndexState,
        expected_symbols: Iterable[str],
    ) -> None:
        if not isinstance(state, LatestIndexState):
            raise TypeError("state must be a LatestIndexState")
        self._state = state
        self._expected_symbols = frozenset(
            symbol.upper() for symbol in normalize_index_symbols(expected_symbols)
        )

    @property
    def expected_symbols(self) -> frozenset[str]:
        """Return the normalized index identifiers accepted by this pipeline."""
        return self._expected_symbols

    def handle(self, payload: object) -> IndexSnapshot | None:
        """Decode, normalize, filter, and cache one index payload."""
        try:
            message = decode_index(payload)  # type: ignore[arg-type]
            snapshot = normalize_index(message)
        except (TypeError, ValueError):
            logger.exception("Rejected Vietcap index payload")
            return None

        if snapshot.symbol not in self._expected_symbols:
            logger.warning(
                "Ignoring unexpected index symbol",
                extra={
                    "expected_symbols": sorted(self._expected_symbols),
                    "symbol": snapshot.symbol,
                },
            )
            return None

        # Diagnostic only (DEBUG): the raw total_value/total_volume magnitude
        # from the Vietcap feed, kept so a live run with LOG_LEVEL=DEBUG can
        # confirm whether total_value carries a real market-wide matched value
        # (Issue 3 audit trail; see runtime.bot_service._is_plausible_market_liquidity).
        logger.debug(
            "Vietcap index snapshot symbol=%s value=%.2f total_volume=%.2f "
            "total_value=%.2f advances=%.0f declines=%.0f unchanged=%.0f",
            snapshot.symbol, snapshot.value, snapshot.total_volume,
            snapshot.total_value, snapshot.advances, snapshot.declines,
            snapshot.unchanged,
        )

        self._state.update(snapshot)
        return snapshot


class BidAskStatePipeline:
    """Decode expected bid-ask events into the latest order-book state."""

    def __init__(
        self,
        state: LatestOrderBookState,
        expected_symbols: Iterable[str],
    ) -> None:
        if not isinstance(state, LatestOrderBookState):
            raise TypeError("state must be a LatestOrderBookState")
        self._state = state
        self._expected_symbols = frozenset(normalize_symbols(expected_symbols))

    @property
    def expected_symbols(self) -> frozenset[str]:
        """Return the normalized symbols accepted by this pipeline."""
        return self._expected_symbols

    def handle(self, payload: object) -> OrderBook | None:
        """Decode, normalize, filter, and cache one bid-ask payload."""
        try:
            message = decode_bid_ask(payload)  # type: ignore[arg-type]
            book = normalize_bid_ask(message)
        except (TypeError, ValueError):
            logger.exception("Rejected Vietcap bid-ask payload")
            return None

        if book.symbol not in self._expected_symbols:
            logger.warning(
                "Ignoring unexpected bid-ask symbol",
                extra={
                    "expected_symbols": sorted(self._expected_symbols),
                    "symbol": book.symbol,
                },
            )
            return None

        self._state.update(book)
        return book
