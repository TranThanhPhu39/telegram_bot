# Signal Design — Draft

Status: Phase 10 indicators, Phase 11 RVOL, Phase 12 market regime, and Phase 13
Signal Engine V1 implemented.

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
- alert-delivery deduplication

The Phase 13 engine implements a configurable post-EXIT cooldown and suppresses
duplicate observations. An explicit `exit_triggered` input is required because
the concrete stop/exit policy has not yet been selected.

## Signal lifecycle

Implemented transition order:

`WATCH → MONEY_FLOW → BREAKOUT → CONFIRMED → ACTIVE → EXIT`

- `WATCH` opens a new symbol lifecycle.
- `MONEY_FLOW` requires Bull regime, stock trend, Relative Strength, and RVOL.
- `BREAKOUT` requires the explicit prior-resistance breakout feature.
- `CONFIRMED` rechecks breakout and all money-flow confirmations.
- `ACTIVE` requires confirmations to persist for another observation.
- `EXIT` requires an explicit exit condition.

The engine advances at most one state for each observation. After cooldown, a
new observation opens a separate lifecycle at `WATCH`.

## Explainability
Every emitted transition stores:
- positive factors
- negative factors
- missing confirmation
- trigger price/condition

The reason structure is JSON-serializable for database persistence and the future
`/why FPT` command.

## Fundamental context

Phase 17 normalizes EPS, P/E, P/B, ROE, revenue growth, and profit growth from a
controlled CSV snapshot with source provenance and as-of date. Threshold results
are `PASS`, `FAIL`, or `INSUFFICIENT_DATA`. They may narrow the scanner universe
or enrich explanations, but they are deliberately absent from `SignalInputs` and
cannot trigger a lifecycle transition by themselves.
