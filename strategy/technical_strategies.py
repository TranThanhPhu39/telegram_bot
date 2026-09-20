"""Pure, provider-independent CL1 and ASMF strategy evaluation.

The functions in this module consume only normalized completed daily bars.  They
are therefore reusable by both the Telegram runtime and a chronological backtest.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import log, sqrt
from statistics import pstdev
from typing import Sequence

from data.indicators import atr, ema, rsi
from data.models import OHLCVBar


class StrategyName(str, Enum):
    CL1 = "CL1"
    ASMF = "ASMF"


class StrategyAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WATCH = "WATCH"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class StrategyResult:
    strategy: StrategyName
    symbol: str
    timestamp: int
    action: StrategyAction
    score: float | None
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    missing: tuple[str, ...]
    stop: float | None = None


def evaluate_cl1(bars: Sequence[OHLCVBar]) -> StrategyResult:
    """Evaluate Trend Rider exactly on the latest completed daily bar."""
    checked = _daily_bars(bars, minimum=200)
    e20, e50 = ema(checked, 20), ema(checked, 50)
    r14, a14, adx14 = rsi(checked, 14), atr(checked, 14), adx(checked, 14)
    ma200 = _sma(checked, 200)
    latest = checked[-1]
    cross_up = _crossed_recently(e20, e50, direction=1, lookback=3)
    cross_down = _crossed_recently(e20, e50, direction=-1, lookback=1)
    volume3 = sum(bar.volume for bar in checked[-3:]) / 3
    volume20 = sum(bar.volume for bar in checked[-20:]) / 20
    chandelier = max(bar.high for bar in checked[-22:]) - 3 * _required(a14[-1])

    checks = (
        (cross_up, "EMA20 cắt lên EMA50 trong 3 phiên", "chưa có giao cắt tăng EMA20/EMA50"),
        (50 < _required(r14[-1]) < 72, f"RSI14={r14[-1]:.2f} trong (50,72)", f"RSI14={r14[-1]:.2f} ngoài (50,72)"),
        (_required(adx14[-1]) > 20, f"ADX14={adx14[-1]:.2f} > 20", f"ADX14={adx14[-1]:.2f} <= 20"),
        (volume3 > volume20, "KLGD TB3 > TB20", "KLGD TB3 chưa vượt TB20"),
        (latest.close > ma200, "giá > MA200", "giá chưa vượt MA200"),
    )
    positive = tuple(good for passed, good, _ in checks if passed)
    negative = tuple(bad for passed, _, bad in checks if not passed)
    if cross_down or latest.close < chandelier:
        reason = "EMA20 cắt xuống EMA50" if cross_down else "giá thủng Chandelier Exit"
        return StrategyResult(StrategyName.CL1, latest.symbol, latest.timestamp,
                              StrategyAction.SELL, None, (), (reason,), (), chandelier)
    action = StrategyAction.BUY if len(positive) == len(checks) else StrategyAction.WATCH
    return StrategyResult(StrategyName.CL1, latest.symbol, latest.timestamp,
                          action, None, positive, negative, (), chandelier)


def evaluate_asmf(
    bars: Sequence[OHLCVBar],
    benchmark: Sequence[OHLCVBar],
    *,
    sector_score: float | None = None,
    fundamental_score: float | None = None,
    institutional_flow_score: float | None = None,
) -> StrategyResult:
    """Evaluate the available ASMF layers without inventing missing inputs.

    A technical score is still useful as WATCH context, but BUY is blocked until
    sector, fundamental and institutional-flow inputs are genuinely supplied.
    """
    stock = _daily_bars(bars, minimum=200)
    index = _daily_bars(benchmark, minimum=200)
    latest = stock[-1]
    hurst = _hurst([bar.close for bar in index[-101:]])
    market_ma200 = _sma(index, 200)
    current_vol = _realized_vol(index[-21:])
    historical_vol = [_realized_vol(index[i - 20:i + 1]) for i in range(20, len(index))]
    percentile = 100 * sum(value <= current_vol for value in historical_vol) / len(historical_vol)
    risk_off = percentile >= 90 and index[-1].close < market_ma200
    regime_score = 0.0 if risk_off else min(100.0, max(0.0, 50 + (hurst - 0.5) * 500))
    smf_score = _smf_price_volume_score(stock, institutional_flow_score)
    atr_values = atr(stock, 14)
    atr_ratios = [_required(atr_values[i]) / stock[i].close for i in range(len(stock) - 5, len(stock))]
    contraction = all(left > right for left, right in zip(atr_ratios, atr_ratios[1:]))
    volume5 = sum(bar.volume for bar in stock[-5:]) / 5
    volume20 = sum(bar.volume for bar in stock[-20:]) / 20
    trend_trigger = (
        hurst > .55 and contraction and volume5 / volume20 < .7
        and latest.close > _sma(stock, 50)
        and latest.close > max(bar.high for bar in stock[-11:-1])
        and latest.volume > 1.5 * volume20 and smf_score >= 60
    )
    mean_reversion_trigger = (
        hurst < .45 and _required(rsi(stock, 2)[-1]) < 10
        and latest.close > _sma(stock, 200) and smf_score >= 55
    )
    trigger = trend_trigger or mean_reversion_trigger

    supplied = (sector_score, fundamental_score)
    available = [regime_score, smf_score, *(value for value in supplied if value is not None)]
    score = sum(available) / len(available)
    missing = []
    if sector_score is None:
        missing.append("sức mạnh ngành/breadth")
    if fundamental_score is None:
        missing.append("chất lượng BCTC theo ngày công bố")
    if institutional_flow_score is None:
        missing.append("dòng tiền khối ngoại/tự doanh")

    positive = [f"Hurst={hurst:.2f}; chế độ {'RISK-OFF' if risk_off else 'hoạt động'}",
                f"SMF giá-khối lượng={smf_score:.1f}/100"]
    if trigger:
        positive.append("trigger Tầng 4 đã kích hoạt")
    negative = []
    if risk_off:
        negative.append("VNINDEX biến động top 10% và dưới MA200")
    action = StrategyAction.BLOCKED if missing or risk_off else (
        StrategyAction.BUY if score >= 60 and trigger else StrategyAction.WATCH
    )
    return StrategyResult(StrategyName.ASMF, latest.symbol, latest.timestamp, action,
                          score, tuple(positive), tuple(negative), tuple(missing))


def adx(bars: Sequence[OHLCVBar], period: int = 14) -> tuple[float | None, ...]:
    """Wilder ADX aligned to input bars."""
    checked = tuple(bars)
    result: list[float | None] = [None] * len(checked)
    if len(checked) < period * 2:
        return tuple(result)
    trs, plus_dm, minus_dm = [], [], []
    for i in range(1, len(checked)):
        up = checked[i].high - checked[i - 1].high
        down = checked[i - 1].low - checked[i].low
        trs.append(max(checked[i].high - checked[i].low,
                       abs(checked[i].high - checked[i - 1].close),
                       abs(checked[i].low - checked[i - 1].close)))
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    tr_sum = sum(trs[:period]); plus_sum = sum(plus_dm[:period]); minus_sum = sum(minus_dm[:period])
    dx: list[float] = []
    for i in range(period - 1, len(trs)):
        if i >= period:
            tr_sum = tr_sum - tr_sum / period + trs[i]
            plus_sum = plus_sum - plus_sum / period + plus_dm[i]
            minus_sum = minus_sum - minus_sum / period + minus_dm[i]
        plus_di = 100 * plus_sum / tr_sum if tr_sum else 0
        minus_di = 100 * minus_sum / tr_sum if tr_sum else 0
        dx.append(100 * abs(plus_di - minus_di) / (plus_di + minus_di) if plus_di + minus_di else 0)
        if len(dx) == period:
            result[i + 1] = sum(dx) / period
        elif len(dx) > period:
            result[i + 1] = ((_required(result[i]) * (period - 1)) + dx[-1]) / period
    return tuple(result)


def _smf_price_volume_score(bars: tuple[OHLCVBar, ...], institutional: float | None) -> float:
    recent = bars[-20:]
    avg_volume = sum(bar.volume for bar in recent) / 20
    accumulation = sum(1 for bar in recent if bar.volume >= 1.5 * avg_volume and
                       (bar.close - bar.low) / max(bar.high - bar.low, 1e-9) >= .66)
    accum_score = min(100.0, accumulation / 8 * 100)
    obv = 0.0
    obv_values = [0.0]
    for previous, current in zip(bars[-21:-1], bars[-20:]):
        obv += current.volume if current.close > previous.close else -current.volume if current.close < previous.close else 0
        obv_values.append(obv)
    obv_score = 75.0 if obv_values[-1] > obv_values[-11] else 25.0
    volumes = [bar.volume for bar in recent]
    deviation = pstdev(volumes)
    zscore = 0.0 if deviation == 0 else (volumes[-1] - sum(volumes) / 20) / deviation
    z_score = min(100.0, max(0.0, 50 + zscore / 3 * 50))
    inst = 50.0 if institutional is None else institutional
    return .35 * accum_score + .25 * obv_score + .20 * z_score + .20 * inst


def _crossed_recently(left: Sequence[float | None], right: Sequence[float | None], *, direction: int, lookback: int) -> bool:
    for i in range(max(1, len(left) - lookback), len(left)):
        if None in (left[i - 1], right[i - 1], left[i], right[i]):
            continue
        before = _required(left[i - 1]) - _required(right[i - 1])
        after = _required(left[i]) - _required(right[i])
        if (direction == 1 and before <= 0 < after) or (direction == -1 and before >= 0 > after):
            return True
    return False


def _sma(bars: Sequence[OHLCVBar], period: int) -> float:
    return sum(bar.close for bar in bars[-period:]) / period


def _realized_vol(bars: Sequence[OHLCVBar]) -> float:
    returns = [log(b.close / a.close) for a, b in zip(bars, bars[1:])]
    return pstdev(returns) * sqrt(252) if len(returns) > 1 else 0.0


def _hurst(closes: Sequence[float]) -> float:
    returns = [log(b / a) for a, b in zip(closes, closes[1:])]
    mean = sum(returns) / len(returns)
    cumulative = []
    value = 0.0
    for item in returns:
        value += item - mean
        cumulative.append(value)
    span = max(cumulative) - min(cumulative)
    deviation = pstdev(returns)
    return 0.5 if span <= 0 or deviation <= 0 else log(span / deviation) / log(len(returns))


def _daily_bars(bars: Sequence[OHLCVBar], *, minimum: int) -> tuple[OHLCVBar, ...]:
    checked = tuple(bars)
    if len(checked) < minimum:
        raise ValueError(f"strategy requires at least {minimum} completed daily bars")
    if any(bar.timeframe != "ONE_DAY" for bar in checked):
        raise ValueError("strategy accepts only ONE_DAY bars")
    return checked


def _required(value: float | None) -> float:
    if value is None:
        raise ValueError("indicator warm-up is incomplete")
    return value
