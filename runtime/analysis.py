"""Pure builders that turn normalized bars and scores into view models.

Nothing here performs I/O.  Every function returns ``None`` or an explicit
``missing`` entry instead of guessing an unavailable value.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import log
from statistics import pstdev
from typing import Sequence

from data.indicators import (
    atr,
    breakout_levels,
    daily_average_volume,
    ema,
    relative_strength_vs_benchmark,
    rsi,
)
from data.models import OHLCVBar
from runtime.views import (
    Freshness,
    LayerStatus,
    LevelView,
    MarketContextView,
    MetricView,
    PriceView,
    ScanRowView,
    SentimentView,
    StrategyLayerView,
    StrategyView,
    TechnicalView,
)
from strategy.technical_strategies import StrategyAction, StrategyResult, adx

VIETNAM_TIMEZONE = timezone(timedelta(hours=7))

STATE_LABELS = {
    StrategyAction.BUY: "MUA",
    StrategyAction.SELL: "BÁN/THOÁT",
    StrategyAction.WATCH: "THEO DÕI",
    StrategyAction.BLOCKED: "CHƯA ĐỦ ĐIỀU KIỆN",
}


def session_date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE).strftime("%Y-%m-%d")


def describe_freshness(
    latest_timestamp: int | None, now_timestamp: float, *, cached: bool
) -> tuple[Freshness, int | None]:
    """Classify data age without ever presenting an old session as current."""
    if latest_timestamp is None:
        return Freshness.UNAVAILABLE, None
    session = datetime.fromtimestamp(latest_timestamp, VIETNAM_TIMEZONE).date()
    today = datetime.fromtimestamp(now_timestamp, VIETNAM_TIMEZONE).date()
    staleness = (today - session).days
    if staleness <= 0:
        return Freshness.EOD_TODAY, 0
    if staleness > 5 or (cached and staleness > 4):
        return Freshness.STALE, staleness
    return Freshness.EOD, staleness


def build_price_view(bars: Sequence[OHLCVBar]) -> PriceView | None:
    if not bars:
        return None
    latest = bars[-1]
    previous = bars[-2].close if len(bars) > 1 else None
    change = None if previous in (None, 0) else (latest.close / previous - 1.0) * 100.0
    return PriceView(
        symbol=latest.symbol,
        close=latest.close,
        change_percent=change,
        volume=latest.volume,
        previous_close=previous,
        session_date=session_date(latest.timestamp),
    )


def align_histories(
    stock: Sequence[OHLCVBar], benchmark: Sequence[OHLCVBar]
) -> tuple[tuple[OHLCVBar, ...], tuple[OHLCVBar, ...]]:
    """Keep only sessions present in both series, preserving chronology."""
    benchmark_by_timestamp = {bar.timestamp: bar for bar in benchmark}
    pairs = [
        (bar, benchmark_by_timestamp[bar.timestamp])
        for bar in stock
        if bar.timestamp in benchmark_by_timestamp
    ]
    if not pairs:
        return (), ()
    return tuple(item[0] for item in pairs), tuple(item[1] for item in pairs)


def _trend_label(
    close: float, ema20_value: float | None, ema50_value: float | None,
    ma200_value: float | None,
) -> str:
    if ema20_value is None or ema50_value is None:
        return "CHƯA ĐỦ DỮ LIỆU"
    if close > ema20_value > ema50_value:
        return "TĂNG" if ma200_value is None or close > ma200_value else "TĂNG NGẮN HẠN"
    if close < ema20_value < ema50_value:
        return "GIẢM"
    return "TRUNG TÍNH"


def _sma_close(bars: Sequence[OHLCVBar], period: int) -> float | None:
    if len(bars) < period:
        return None
    return sum(bar.close for bar in bars[-period:]) / period


def build_technical_view(
    bars: Sequence[OHLCVBar], benchmark: Sequence[OHLCVBar] = ()
) -> TechnicalView | None:
    """Compute only the indicators the repository already owns."""
    if not bars:
        return None
    latest = bars[-1]
    missing: list[str] = []
    ema20_value = ema(bars, 20)[-1]
    ema50_value = ema(bars, 50)[-1]
    ma200_value = _sma_close(bars, 200)
    rsi_value = rsi(bars, 14)[-1]
    atr_value = atr(bars, 14)[-1]
    adx_value = adx(bars, 14)[-1]
    if ma200_value is None:
        missing.append("MA200 (cần 200 phiên)")
    if adx_value is None:
        missing.append("ADX14 (cần 28 phiên)")

    average_volume = daily_average_volume(bars, 20)[-1] if bars[-1].timeframe == "ONE_DAY" else None
    volume_ratio = (
        None if not average_volume else latest.volume / average_volume
    )
    if volume_ratio is None:
        missing.append("RVOL ngày (cần 20 phiên)")

    relative = None
    aligned_stock, aligned_benchmark = align_histories(bars, benchmark)
    if len(aligned_stock) > 20:
        relative = relative_strength_vs_benchmark(
            aligned_stock, aligned_benchmark, 20
        )[-1]
    else:
        missing.append("Relative Strength vs VNINDEX")

    resistances: list[LevelView] = []
    supports: list[LevelView] = []
    level20 = breakout_levels(bars, 20)[-1]
    if level20 is not None:
        resistances.append(LevelView("R1", level20.resistance, "đỉnh 20 phiên trước đó"))
        supports.append(LevelView("S1", level20.support, "đáy 20 phiên trước đó"))
    if len(bars) > 60:
        level60 = breakout_levels(bars, 60)[-1]
        if level60 is not None:
            resistances.append(LevelView("R2", level60.resistance, "đỉnh 60 phiên trước đó"))
            supports.append(LevelView("S2", level60.support, "đáy 60 phiên trước đó"))
    if ema50_value is not None and ema50_value < latest.close:
        supports.append(LevelView("S-EMA50", ema50_value, "EMA50 đang nằm dưới giá"))
    if ma200_value is not None and ma200_value < latest.close:
        supports.append(LevelView("S-MA200", ma200_value, "MA200 đang nằm dưới giá"))
    if ma200_value is not None and ma200_value > latest.close:
        resistances.append(LevelView("R-MA200", ma200_value, "MA200 đang nằm trên giá"))
    if not resistances:
        missing.append("kháng cự (chưa đủ lịch sử)")
    if not supports:
        missing.append("hỗ trợ (chưa đủ lịch sử)")

    resistances = _distinct_levels(resistances)
    supports = _distinct_levels(supports)

    return TechnicalView(
        trend=_trend_label(latest.close, ema20_value, ema50_value, ma200_value),
        ema20=ema20_value,
        ema50=ema50_value,
        ma200=ma200_value,
        rsi14=rsi_value,
        adx14=adx_value,
        atr14=atr_value,
        volume_ratio=volume_ratio,
        relative_strength=relative,
        resistances=tuple(resistances[:3]),
        supports=tuple(supports[:3]),
        missing=tuple(missing),
    )


def _distinct_levels(levels: list[LevelView]) -> list[LevelView]:
    """Drop levels that repeat an earlier price; duplicates add no information."""
    result: list[LevelView] = []
    for level in levels:
        if any(abs(level.value - kept.value) <= 1e-6 for kept in result):
            continue
        result.append(level)
    return result


def _calculate_hurst(closes: Sequence[float]) -> float | None:
    """Calculate the rescaled range (R/S) Hurst exponent."""
    if len(closes) < 20:
        return None
    returns = [log(b / a) for a, b in zip(closes, closes[1:])]
    mean = sum(returns) / len(returns)
    cumulative = []
    val = 0.0
    for item in returns:
        val += item - mean
        cumulative.append(val)
    span = max(cumulative) - min(cumulative)
    dev = pstdev(returns)
    if span <= 0 or dev <= 0 or len(returns) <= 1:
        return 0.5
    h = log(span / dev) / log(len(returns))
    return min(1.0, max(0.0, h))


def _calculate_volatility_percentile(
    bars: Sequence[OHLCVBar],
    window: int = 20,
    lookback: int = 100,
) -> float | None:
    """Calculate rolling 20-session realized vol percentile over lookback sessions."""
    if len(bars) < window + 2:
        return None
    closes = [b.close for b in bars]
    log_returns = [log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    if len(log_returns) < window:
        return None

    current_std = pstdev(log_returns[-window:])
    start_idx = max(0, len(log_returns) - lookback)
    rolling_vols = [
        pstdev(log_returns[i : i + window])
        for i in range(start_idx, len(log_returns) - window + 1)
    ]
    if not rolling_vols:
        return None

    count_le = sum(1 for v in rolling_vols if v <= current_std)
    return (count_le / len(rolling_vols)) * 100.0


def build_market_view(
    bars: Sequence[OHLCVBar],
    *,
    breadth: str | None = None,
    liquidity: str | None = None,
    foreign_flow: str | None = None,
    top_sectors: Sequence[str] = (),
    weakest_sector: str | None = None,
    weakest_sector_score: float | None = None,
) -> MarketContextView | None:
    """Classify VNINDEX with trend and advanced quantitative context."""
    if not bars:
        return None
    latest = bars[-1]
    previous = bars[-2].close if len(bars) > 1 else None
    change = None if previous in (None, 0) else (latest.close / previous - 1.0) * 100.0
    ema20_value = ema(bars, 20)[-1]
    ema50_value = ema(bars, 50)[-1]
    ma50_value = _sma_close(bars, 50)
    ma200_value = _sma_close(bars, 200)
    trend = _trend_label(latest.close, ema20_value, ema50_value, ma200_value)

    # Quantitative Hurst exponent & Realized Volatility Percentile
    hurst_lookback = 100
    closes = [b.close for b in bars]
    hurst = None
    if len(closes) >= 20:
        sample = closes[-(hurst_lookback + 1):]
        hurst = _calculate_hurst(sample)

    volatility_percentile = _calculate_volatility_percentile(bars, window=20, lookback=100)

    ma50_status = None
    ma200_status = None
    trend_stability_reason = None
    if ma50_value is not None and ma200_value is not None:
        ma50_status = "TRÊN MA50" if latest.close >= ma50_value else "DƯỚI MA50"
        ma200_status = "TRÊN MA200" if latest.close >= ma200_value else "DƯỚI MA200"
        if latest.close >= ma50_value and latest.close >= ma200_value:
            trend_stability_reason = "Chỉ số đứng vững trên cả MA50 và MA200 -> xu hướng tăng bền vững."
        elif latest.close < ma50_value and latest.close < ma200_value:
            trend_stability_reason = "Chỉ số nằm dưới cả MA50 và MA200 -> xu hướng giảm chiếm ưu thế."
        else:
            trend_stability_reason = "Chỉ số chưa đứng vững trên cả MA50 và MA200 -> xu hướng chưa chắc chắn."
    elif ma50_value is not None:
        ma50_status = "TRÊN MA50" if latest.close >= ma50_value else "DƯỚI MA50"
        trend_stability_reason = "Chỉ số chưa đứng vững trên cả MA50 và MA200 -> xu hướng chưa chắc chắn."

    unavailable: list[str] = []
    if breadth is None:
        unavailable.append("Breadth (advance/decline) cần realtime")
    if liquidity is None:
        unavailable.append("Liquidity (giá trị khớp lệnh toàn thị trường)")
    if foreign_flow is None:
        unavailable.append("Dòng tiền khối ngoại/tự doanh toàn thị trường")

    if breadth is None:
        regime = "BULL" if trend == "TĂNG" else "BEAR" if trend == "GIẢM" else "NEUTRAL"
        reason = "chỉ dựa trên xu hướng EMA; chưa có breadth nên chưa phải regime đầy đủ"
    else:
        regime = "BULL" if trend == "TĂNG" else "BEAR" if trend == "GIẢM" else "NEUTRAL"
        reason = f"xu hướng EMA + breadth {breadth}"

    risk_flags: list[str] = []
    if ma200_value is not None and latest.close < ma200_value:
        risk_flags.append("VNINDEX dưới MA200")
    if change is not None and change <= -2.0:
        risk_flags.append(f"phiên gần nhất giảm {change:.2f}%")

    return MarketContextView(
        symbol=latest.symbol,
        close=latest.close,
        change_percent=change,
        trend=trend,
        regime=regime,
        regime_reason=reason,
        ema20=ema20_value,
        ema50=ema50_value,
        breadth=breadth,
        liquidity=liquidity,
        foreign_flow=foreign_flow,
        risk_flags=tuple(risk_flags),
        unavailable=tuple(unavailable),
        hurst=hurst,
        volatility_percentile=volatility_percentile,
        hurst_lookback=hurst_lookback,
        ma50_status=ma50_status,
        ma200_status=ma200_status,
        trend_stability_reason=trend_stability_reason,
        top_sectors=tuple(top_sectors),
        weakest_sector=weakest_sector,
        weakest_sector_score=weakest_sector_score,
    )


def build_strategy_view(
    result: StrategyResult, *, note: str | None = None
) -> StrategyView:
    """Render a strategy result without adding any confidence the engine lacks."""
    covered = len(result.positive)
    total = covered + len(result.negative) + len(result.missing)
    layers = tuple(
        StrategyLayerView(item.name, LayerStatus(item.status), item.detail)
        for item in result.layers
    )
    return StrategyView(
        name=result.strategy.value,
        state=STATE_LABELS[result.action],
        score=result.score,
        positive=result.positive,
        negative=result.negative,
        missing=result.missing,
        layers=layers,
        stop=result.stop,
        evidence_covered=covered if total else None,
        evidence_total=total or None,
        note=note,
    )


def build_sentiment_view(aggregate) -> SentimentView:
    """Convert a SentimentAggregate; a missing aggregate is stated, not filled."""
    if aggregate is None:
        return SentimentView(available=False, note="Không có tin trong cửa sổ theo dõi.")
    score = aggregate.score
    label = "Positive" if score >= 0.15 else "Negative" if score <= -0.15 else "Neutral"
    return SentimentView(
        available=True,
        label=label,
        score=score,
        model_confidence=aggregate.model_confidence,
        article_count=aggregate.article_count,
        positive_count=aggregate.positive_count,
        neutral_count=aggregate.neutral_count,
        negative_count=aggregate.negative_count,
        top_events=tuple(aggregate.top_events),
        latest_at=aggregate.latest_at,
        backends=tuple(aggregate.backends),
    )


def build_metrics(values: dict[str, tuple[float | None, str]]) -> tuple[MetricView, ...]:
    return tuple(
        MetricView(label, value, unit) for label, (value, unit) in values.items()
    )


def build_risk_items(
    technical: TechnicalView | None,
    market: MarketContextView | None,
    strategy: StrategyView | None,
    sentiment: SentimentView | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (risks, watch_items) derived only from established evidence."""
    risks: list[str] = []
    watch: list[str] = []
    if technical is not None:
        if technical.rsi14 is not None and technical.rsi14 >= 75:
            risks.append(f"RSI14={technical.rsi14:.1f} ở vùng quá mua, rủi ro điều chỉnh ngắn hạn")
        if technical.rsi14 is not None and technical.rsi14 <= 30:
            risks.append(f"RSI14={technical.rsi14:.1f} ở vùng quá bán, xu hướng đang yếu")
        if technical.adx14 is not None and technical.adx14 < 20:
            watch.append(f"ADX14={technical.adx14:.1f} < 20: xu hướng chưa đủ mạnh, chờ xác nhận")
        if technical.volume_ratio is not None and technical.volume_ratio < 0.7:
            watch.append("Khối lượng dưới 70% trung bình 20 phiên: thiếu dòng tiền xác nhận")
        for level in technical.resistances[:1]:
            watch.append(f"Vượt và giữ trên {level.label}={level.value:g} ({level.reason})")
        for level in technical.supports[:1]:
            watch.append(f"Mất {level.label}={level.value:g} là tín hiệu suy yếu")
    if market is not None:
        risks.extend(market.risk_flags)
    if strategy is not None:
        if strategy.stop is not None:
            watch.append(f"Ngưỡng thoát kỹ thuật (Chandelier Exit): {strategy.stop:g}")
        for item in strategy.missing:
            watch.append(f"Bổ sung dữ liệu thiếu: {item}")
    if sentiment is not None and sentiment.available and sentiment.label == "Negative":
        risks.append(
            f"Sentiment tin tức 24h âm ({sentiment.score:+.2f}); đây là context, không phải lệnh bán"
        )
    return tuple(dict.fromkeys(risks)), tuple(dict.fromkeys(watch))


def build_scan_row(
    symbol: str,
    technical: TechnicalView | None,
    strategy: StrategyView | None,
    liquidity_pass: bool,
    fundamental_status: str | None,
) -> ScanRowView:
    """Explain *why* a symbol survived the screen instead of listing a ticker."""
    if technical is None:
        trend = "KHÔNG CÓ DỮ LIỆU"
        relative = "N/A"
    else:
        trend = technical.trend
        relative = (
            "N/A" if technical.relative_strength is None
            else f"{technical.relative_strength:+.2f}% vs VNINDEX"
        )
    return ScanRowView(
        symbol=symbol,
        trend=trend,
        relative_strength=relative,
        liquidity="PASS" if liquidity_pass else "FAIL",
        strategy_state="N/A" if strategy is None else strategy.state,
        fundamental=fundamental_status or "INSUFFICIENT",
    )


def interpret_indicators(technical: TechnicalView | None) -> tuple[str, ...]:
    """Indicator → meaning → implication, never a bare indicator dump."""
    if technical is None:
        return ()
    lines: list[str] = []
    if technical.rsi14 is not None:
        value = technical.rsi14
        meaning = (
            "động lượng mạnh" if value >= 60 else
            "động lượng trung tính" if value >= 45 else
            "động lượng yếu"
        )
        implication = (
            "không tự động đồng nghĩa với BÁN" if value >= 70 else
            "không tự động đồng nghĩa với MUA" if value <= 30 else
            "chưa đủ để kết luận vào/ra lệnh"
        )
        lines.append(f"RSI14 {value:.1f} → {meaning} → {implication}")
    if technical.adx14 is not None:
        value = technical.adx14
        meaning = "xu hướng có định hướng rõ" if value > 20 else "thị trường đi ngang/nhiễu"
        implication = (
            "chiến lược bám xu hướng có cơ sở hơn" if value > 20
            else "tín hiệu breakout dễ thất bại hơn"
        )
        lines.append(f"ADX14 {value:.1f} → {meaning} → {implication}")
    if technical.volume_ratio is not None:
        value = technical.volume_ratio
        meaning = "khối lượng vượt trung bình 20 phiên" if value >= 1.2 else (
            "khối lượng quanh trung bình" if value >= 0.8 else "khối lượng cạn kiệt"
        )
        implication = (
            "dòng tiền đang xác nhận biến động giá" if value >= 1.2
            else "biến động giá thiếu xác nhận dòng tiền"
        )
        lines.append(f"Khối lượng {value:.2f}x TB20 → {meaning} → {implication}")
    if technical.relative_strength is not None:
        value = technical.relative_strength
        meaning = "khỏe hơn VNINDEX 20 phiên" if value > 0 else "yếu hơn VNINDEX 20 phiên"
        implication = (
            "ưu tiên trong cùng bối cảnh thị trường" if value > 0
            else "cần lý do riêng để ưu tiên mã này"
        )
        lines.append(f"RS {value:+.2f}% → {meaning} → {implication}")
    if technical.ema20 is not None and technical.ema50 is not None:
        lines.append(
            f"EMA20 {technical.ema20:.2f} / EMA50 {technical.ema50:.2f} → cấu trúc "
            f"{technical.trend.lower()} → quyết định khung thời gian nắm giữ"
        )
    return tuple(lines)
