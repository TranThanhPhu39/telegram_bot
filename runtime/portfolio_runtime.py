"""Runtime orchestration for Phase 23.

Prices come exclusively through the bot's existing history boundary
(``RuntimeBotDataService._history``: Vietcap historical first, SQLite cache
second), so no second data pipeline exists.  A realtime market-state feed is
not wired into the runtime service today; when it is, it belongs behind
``RuntimeMarketPort.quote``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3
import logging

from asmf_data.store import active_sector
from data.models import OHLCVBar
from data.vietcap.rest import VietcapRestError
from portfolio.config import PortfolioConfig
from portfolio.models import (
    ConcentrationStatus,
    PortfolioError,
    PortfolioSnapshot,
    PriceQuote,
    SectorInfo,
)
from portfolio.repository import SQLitePortfolioRepository, normalize_symbol
from portfolio.risk import classify_stock
from portfolio.service import PortfolioService, RiskSettings
from runtime.analysis import build_technical_view, describe_freshness, session_date
from runtime.portfolio_views import (
    PortfolioContextView,
    PortfolioRiskView,
    PortfolioView,
    StressTestView,
    WatchlistItemView,
    WatchlistView,
)
from runtime.views import DataQualityView, Freshness
from strategy.technical_strategies import evaluate_cl1

LOGGER = logging.getLogger(__name__)
VIETNAM_TIMEZONE = timezone(timedelta(hours=7))
HistoryLoader = Callable[[str], "tuple[tuple[OHLCVBar, ...], str]"]
_FAILURES = (VietcapRestError, ValueError, sqlite3.Error, OSError)


class RuntimeMarketPort:
    """`MarketDataPort` backed by the runtime history loader, memoised per request."""

    def __init__(
        self, history: HistoryLoader, connection: sqlite3.Connection, now: Callable[[], float]
    ) -> None:
        self.history = history
        self.connection = connection
        self.now = now
        self._cache: dict[str, tuple[tuple[OHLCVBar, ...], str]] = {}

    def reset(self) -> None:
        self._cache.clear()

    def bars(self, symbol: str) -> tuple[tuple[OHLCVBar, ...], str]:
        symbol = symbol.strip().upper()
        if symbol not in self._cache:
            try:
                self._cache[symbol] = self.history(symbol)
            except _FAILURES:
                LOGGER.warning("History unavailable for %s", symbol, exc_info=True)
                self._cache[symbol] = ((), "unavailable")
        return self._cache[symbol]

    def quote(self, symbol: str) -> PriceQuote:
        bars, source = self.bars(symbol)
        if not bars:
            return PriceQuote(symbol, None, None, Freshness.UNAVAILABLE, source)
        latest = bars[-1]
        freshness, staleness = describe_freshness(
            latest.timestamp, self.now(), cached=source.startswith("SQLite")
        )
        return PriceQuote(
            symbol, Decimal(str(latest.close)), session_date(latest.timestamp),
            freshness, source, staleness,
        )

    def closes(self, symbol: str) -> Mapping[str, float]:
        bars, _ = self.bars(symbol)
        return {session_date(bar.timestamp): bar.close for bar in bars}

    def sector(self, symbol: str) -> SectorInfo | None:
        as_of = datetime.fromtimestamp(self.now(), VIETNAM_TIMEZONE).date()
        try:
            row = active_sector(self.connection, symbol, as_of)
        except sqlite3.Error:
            return None
        if row is None:
            return None
        return SectorInfo(row["sector_code"], row["sector_name"], row["source"])


class PortfolioRuntime:
    """Builds portfolio views for one Telegram user id; holds no presentation."""

    def __init__(
        self, connection: sqlite3.Connection, history: HistoryLoader,
        now: Callable[[], float], config: PortfolioConfig | None = None,
    ) -> None:
        self.config = config or PortfolioConfig()
        self.repository = SQLitePortfolioRepository(connection, now)
        self.market = RuntimeMarketPort(history, connection, now)
        self.service = PortfolioService(self.repository, self.market, self.config)

    # ------------------------------------------------------------- watchlist

    def add_watch(self, user_id: int, symbol: str) -> tuple[str, bool]:
        self.market.reset()
        symbol = normalize_symbol(symbol)
        return symbol, self.service.add_watch(user_id, symbol)

    def remove_watch(self, user_id: int, symbol: str) -> tuple[str, bool]:
        symbol = normalize_symbol(symbol)
        return symbol, self.service.remove_watch(user_id, symbol)

    def watchlist_view(self, user_id: int) -> WatchlistView:
        self.market.reset()
        entries = self.service.watchlist(user_id)
        if not entries:
            return WatchlistView((), None)
        benchmark, _ = self.market.bars("VNINDEX")
        items: list[WatchlistItemView] = []
        quotes: list[PriceQuote] = []
        for entry in entries:
            quote = self.market.quote(entry.symbol)
            quotes.append(quote)
            bars, _ = self.market.bars(entry.symbol)
            trend = state = None
            if bars:
                technical = build_technical_view(bars, benchmark)
                trend = None if technical is None else technical.trend
                try:
                    state = evaluate_cl1(bars).action.value
                except ValueError:
                    state = None
            items.append(WatchlistItemView(
                entry.symbol, quote.price, trend, state, quote.session_date, quote.freshness,
            ))
        return WatchlistView(tuple(items), aggregate_quality(quotes))

    # -------------------------------------------------------------- holdings

    def upsert_holding(self, user_id: int, symbol: str, quantity: int, average_cost: Decimal):
        self.market.reset()
        symbol = normalize_symbol(symbol)
        return symbol, self.service.upsert_holding(user_id, symbol, quantity, average_cost)

    def remove_holding(self, user_id: int, symbol: str) -> tuple[str, bool]:
        symbol = normalize_symbol(symbol)
        return symbol, self.service.remove_holding(user_id, symbol)

    def portfolio_view(self, user_id: int) -> PortfolioView:
        self.market.reset()
        snapshot = self.service.snapshot(user_id)
        return PortfolioView(snapshot, snapshot_quality(snapshot))

    def risk_view(self, user_id: int) -> PortfolioRiskView:
        self.market.reset()
        assessment = self.service.risk(user_id)
        return PortfolioRiskView(assessment, snapshot_quality(assessment.snapshot))

    def stress_view(self, user_id: int, shock_pct: Decimal, symbol: str | None) -> StressTestView:
        self.market.reset()
        snapshot = self.service.snapshot(user_id)
        result = self.service.stress(user_id, shock_pct, symbol, snapshot=snapshot)
        return StressTestView(result, snapshot_quality(snapshot))

    # ---------------------------------------------------------- risk settings

    def risk_settings(self, user_id: int) -> RiskSettings:
        return self.service.risk_settings(user_id)

    def set_default_risk(self, user_id: int, risk_pct: Decimal) -> RiskSettings:
        return self.service.set_default_risk(user_id, risk_pct)

    def size(self, user_id, symbol, entry, stop, capital, risk_pct):
        return self.service.size(user_id, symbol, entry, stop, capital, risk_pct)

    # ------------------------------------------------------- `/soi` context

    def context_for(self, user_id: int | None, symbol: str) -> PortfolioContextView | None:
        """Informational only: never changes CL1/ASMF output; failures return None."""
        if user_id is None:
            return None
        symbol = symbol.strip().upper()
        try:
            if not self.repository.is_held(user_id, symbol):
                return PortfolioContextView(symbol, held=False)
            self.market.reset()
            snapshot = self.service.snapshot(user_id)
        except (PortfolioError, sqlite3.Error):
            LOGGER.warning("Portfolio context unavailable", exc_info=True)
            return None
        return build_context(symbol, snapshot, self.config)


def build_context(
    symbol: str, snapshot: PortfolioSnapshot, config: PortfolioConfig
) -> PortfolioContextView:
    holding = next((h for h in snapshot.holdings if h.symbol == symbol), None)
    if holding is None:
        return PortfolioContextView(symbol, held=False)
    if holding.market_value is None:
        return PortfolioContextView(
            symbol, True, holding.quantity,
            valuation_note="Price unavailable; weight and P&L cannot be computed.",
        )
    exposure = next(
        (e for e in snapshot.sector_exposure if e.sector_code == holding.sector_code), None
    )
    note = None
    if holding.weight_pct is not None \
            and classify_stock(holding.weight_pct, config) is ConcentrationStatus.HIGH:
        note = (
            f"{symbol} already represents {holding.weight_pct:.1f}% of your current portfolio."
        )
    valuation = None if snapshot.complete else "Portfolio valuation incomplete; weights use priced holdings only."
    return PortfolioContextView(
        symbol, True, holding.quantity, holding.weight_pct, holding.unrealized_pnl_pct,
        None if exposure is None else exposure.label,
        None if exposure is None else exposure.weight_pct, note, valuation,
    )


_RANK = {
    Freshness.REALTIME: 0, Freshness.EOD_TODAY: 1, Freshness.EOD: 2,
    Freshness.STALE: 3, Freshness.UNAVAILABLE: 4,
}


def aggregate_quality(quotes: Sequence[PriceQuote], notes: Sequence[str] = ()) -> DataQualityView:
    """Worst freshness, oldest session and every distinct source across quotes."""
    priced = [q for q in quotes if q.price is not None]
    if not priced:
        return DataQualityView(Freshness.UNAVAILABLE, None, None, "unavailable", notes=tuple(notes))
    dates = sorted({q.session_date for q in priced if q.session_date})
    staleness = [q.staleness_days for q in priced if q.staleness_days is not None]
    extra = list(notes)
    if len(dates) > 1 and not any("different sessions" in n for n in extra):
        extra.append(f"Symbols use different sessions ({dates[0]} to {dates[-1]}).")
    return DataQualityView(
        freshness=max((q.freshness for q in priced), key=_RANK.__getitem__),
        session_date=dates[0] if dates else None,
        staleness_days=max(staleness) if staleness else None,
        market_source=", ".join(dict.fromkeys(q.source for q in priced)),
        notes=tuple(extra),
    )


def snapshot_quality(snapshot: PortfolioSnapshot) -> DataQualityView:
    return aggregate_quality([h.quote for h in snapshot.priced_holdings], snapshot.notes)