# Signal Design — Draft

Status: Phase 10 indicators implemented; signal composition remains planned.

## Planned V1

### Market Regime
Use VNINDEX trend + market breadth.

Possible inputs:
- VNINDEX price/trend
- totalStockIncrease
- totalStockDecline
- totalStockNoChange
- totalStockCeiling
- totalStockFloor

### Trend
Implemented inputs:
- Close > EMA20
- EMA20 > EMA50

EMA20 and EMA50 use a simple-moving-average seed and then the standard recursive
EMA formula. Warm-up values are unavailable rather than backfilled.

Thresholds must be backtested, not blindly hard-coded.

### Relative Strength
Compare stock return to VNINDEX over the same lookback.

Implemented as percentage-point excess return with exact timestamp alignment:

`100 * (stock_return - VNINDEX_return)`

### Intraday RVOL
Preferred:

RVOL(t) =
CumulativeVolumeToday(t)
/
Average[CumulativeVolumeHistoricalSessions(t)]

This is time-matched RVOL.

Do not replace with current volume / average full-day volume.

### Breakout
Implemented Phase 10 level:
price > previous N-day high/resistance,
confirmed by RVOL and market regime.

Resistance and support exclude the current bar. RVOL and market-regime
confirmation belong to later phases.

### Risk
Later define:
- stop logic
- ATR-based use in risk logic (ATR14 itself is implemented with Wilder smoothing)
- support
- cooldown
- duplicate alert prevention

## Explainability
Every signal must store:
- positive factors
- negative factors
- missing confirmation
- trigger price/condition

Planned `/why FPT` should expose this.
