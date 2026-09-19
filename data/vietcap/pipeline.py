"""Vietcap event pipeline from binary payloads to normalized market state."""

from __future__ import annotations

from collections.abc import Iterable
import logging

from data.market_state import LatestIndexState, LatestMarketState
from data.models import IndexSnapshot, TradeTick
from data.vietcap.decoder import decode_index, decode_match_price
from data.vietcap.normalizer import normalize_index, normalize_match_price
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

        self._state.update(snapshot)
        return snapshot
