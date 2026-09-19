# Signal Design — Draft

Status: NOT YET IMPLEMENTED.

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
Initial candidates:
- Close > EMA20
- EMA20 > EMA50

Thresholds must be backtested, not blindly hard-coded.

### Relative Strength
Compare stock return to VNINDEX over the same lookback.

### Intraday RVOL
Preferred:

RVOL(t) =
CumulativeVolumeToday(t)
/
Average[CumulativeVolumeHistoricalSessions(t)]

This is time-matched RVOL.

Do not replace with current volume / average full-day volume.

### Breakout
Candidate:
price > previous N-day high/resistance,
confirmed by RVOL and market regime.

### Risk
Later define:
- stop logic
- ATR
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
