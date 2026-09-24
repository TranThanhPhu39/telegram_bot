"""Provider-independent view models rendered by the Telegram formatter.

These dataclasses carry *already decided* analysis results.  They contain no
I/O and no computation, so a formatter can render them without ever hiding a
missing value behind a fabricated default.  Every optional field means exactly
one thing: the backend could not establish that value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Freshness(str, Enum):
    """How current the market data behind a view actually is."""

    REALTIME = "REALTIME"
    EOD_TODAY = "EOD_TODAY"
    EOD = "EOD"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class LayerStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    SUPPORTIVE = "SUPPORTIVE"
    NEUTRAL = "NEUTRAL"
    RISK = "RISK"


@dataclass(frozen=True, slots=True)
class DataQualityView:
    """Freshness and provenance of every source feeding one response."""

    freshness: Freshness
    session_date: str | None
    staleness_days: int | None
    market_source: str
    fundamental_source: str | None = None
    fundamental_as_of: str | None = None
    news_latest_at: datetime | None = None
    news_source: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PriceView:
    symbol: str
    close: float
    change_percent: float | None
    volume: float
    previous_close: float | None
    session_date: str | None


@dataclass(frozen=True, slots=True)
class LevelView:
    """One support or resistance level plus the evidence that produced it."""

    label: str
    value: float
    reason: str


@dataclass(frozen=True, slots=True)
class TechnicalView:
    trend: str
    ema20: float | None
    ema50: float | None
    ma200: float | None
    rsi14: float | None
    adx14: float | None
    atr14: float | None
    volume_ratio: float | None
    relative_strength: float | None
    resistances: tuple[LevelView, ...] = ()
    supports: tuple[LevelView, ...] = ()
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketContextView:
    symbol: str
    close: float | None
    change_percent: float | None
    trend: str
    regime: str
    regime_reason: str
    ema20: float | None = None
    ema50: float | None = None
    breadth: str | None = None
    liquidity: str | None = None
    foreign_flow: str | None = None
    risk_flags: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()
    hurst: float | None = None
    volatility_percentile: float | None = None
    hurst_lookback: int = 100
    ma50_status: str | None = None
    ma200_status: str | None = None
    trend_stability_reason: str | None = None
    top_sectors: tuple[str, ...] = ()
    weakest_sector: str | None = None
    weakest_sector_score: float | None = None


@dataclass(frozen=True, slots=True)
class StrategyLayerView:
    name: str
    status: LayerStatus
    detail: str = ""


@dataclass(frozen=True, slots=True)
class StrategyView:
    name: str
    state: str
    score: float | None
    positive: tuple[str, ...] = ()
    negative: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    layers: tuple[StrategyLayerView, ...] = ()
    stop: float | None = None
    evidence_covered: int | None = None
    evidence_total: int | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class MetricView:
    label: str
    value: float | None
    unit: str = ""


@dataclass(frozen=True, slots=True)
class FundamentalView:
    status: str
    metrics: tuple[MetricView, ...] = ()
    as_of: str | None = None
    source: str | None = None
    period: str | None = None
    kind: str | None = None
    missing: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SentimentView:
    available: bool
    label: str | None = None
    score: float | None = None
    model_confidence: float | None = None
    article_count: int | None = None
    positive_count: int | None = None
    neutral_count: int | None = None
    negative_count: int | None = None
    top_events: tuple[str, ...] = ()
    latest_at: datetime | None = None
    backends: tuple[str, ...] = ()
    note: str | None = None
    articles: tuple[SentimentArticleView, ...] = ()


@dataclass(frozen=True, slots=True)
class SentimentArticleView:
    title: str
    published_at: datetime
    source: str
    url: str
    event_type: str = "OTHER"
    sentiment_label: str | None = None
    sentiment_score: float | None = None
    model_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class NewsItemView:
    published_at: datetime
    title: str
    source: str
    event_type: str
    sentiment_label: str | None
    url: str = ""


@dataclass(frozen=True, slots=True)
class SectorView:
    sector_code: str | None
    sector_name: str | None
    member_count: int | None
    strength_score: float | None
    breadth_percent: float | None
    relative_strength: float | None
    leaders: tuple[tuple[str, float], ...] = ()
    laggards: tuple[tuple[str, float], ...] = ()
    missing: tuple[str, ...] = ()
    as_of: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class ScanRowView:
    symbol: str
    trend: str
    relative_strength: str
    liquidity: str
    strategy_state: str
    fundamental: str
    strategy_layers: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class StockAnalysisView:
    """Everything `/soi` and its drill-down commands render."""

    symbol: str
    price: PriceView | None
    technical: TechnicalView | None
    market: MarketContextView | None
    strategy: StrategyView | None
    fundamental: FundamentalView | None
    sentiment: SentimentView | None
    data_quality: DataQualityView
    risks: tuple[str, ...] = field(default_factory=tuple)
    watch_items: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ChartRequestView:
    """Outcome of a candlestick chart request: exactly one of the two fields
    below is populated, never both, so callers cannot render a stale image
    next to a fresh error message."""

    symbol: str
    png_bytes: bytes | None
    caption: str
    error: str | None = None
