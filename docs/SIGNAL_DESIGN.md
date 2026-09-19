# Signal Design — Draft

Status: Phase 10 indicators, Phase 11 RVOL, and Phase 12 market regime implemented;
signal-state composition remains planned.

## Planned V1

### Market Regime
Implemented using VNINDEX trend plus market breadth.

Inputs:
- VNINDEX price/trend
- totalStockIncrease
- totalStockDecline
- totalStockNoChange
- totalStockCeiling
- totalStockFloor

Trend is bullish when `VNINDEX > EMA20 > EMA50` and bearish when
`VNINDEX < EMA20 < EMA50`. Breadth is:

`(advances - declines) / (advances + declines + unchanged)`

Bull or Bear requires trend and breadth to confirm in the same direction.
Conflicting, missing, or insufficient evidence returns Neutral. Ceiling/floor
counts remain available context but are excluded from the denominator because
they may overlap advance/decline groups. Breadth threshold and minimum population
are explicit configuration intended for backtesting rather than fixed assumptions.

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
Implemented in Phase 11:

RVOL(t) =
CumulativeVolumeToday(t)
/
Average[CumulativeVolumeHistoricalSessions(t)]

This is time-matched RVOL.

Do not replace with current volume / average full-day volume.

The baseline uses prior sessions only, aligned by Vietnam-local clock minute.
For a historical minute without a trade bar, its latest cumulative volume at or
before that time is carried forward. Historical dates equal to or later than the
current session are rejected, and later bars within any session cannot affect an
earlier RVOL point. A zero baseline produces an unavailable ratio.

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
