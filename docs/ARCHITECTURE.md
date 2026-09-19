# Architecture

## Target

HOSE + HNX + UPCoM realtime analysis and Telegram signal bot.

## Layering

```text
Vietcap / future DNSE
        ↓
MarketDataProvider
        ↓
Decoder / Normalizer
        ↓
Market State
        ↓
Historical + Realtime Candles
        ↓
Feature Engine
        ↓
Market Regime + Stock Features
        ↓
Signal Engine
        ↓
Risk / Alert Manager
        ↓
Telegram
```

## Provider abstraction

Strategy code must never call a Vietcap endpoint directly.

Future interface concept:

```python
class MarketDataProvider:
    async def get_quote(self, symbol): ...
    async def get_history(self, symbol, timeframe, count): ...
    async def subscribe_trades(self, symbols): ...
    async def subscribe_orderbook(self, symbols): ...
    async def subscribe_indices(self, symbols): ...
```

Implement `VietcapProvider` first.
DNSE can be added later without changing strategy.

## Normalized trade data

`data.models.TradeTick` is the provider-independent boundary for decoded trades.
It is immutable so cached market state cannot be changed accidentally. Vietcap
protobuf objects are converted in `data.vietcap.normalizer`; downstream modules
must consume `TradeTick`, not `MatchPriceMessage`.

The provider's exchange time remains an optional string until live frames confirm
its format and timezone. Unset proto3 snapshot fields are normalized to `None`.

## Latest market state

`data.market_state.LatestMarketState` stores one immutable `TradeTick` per
normalized symbol. Updates replace values by arrival order; the cache does not
compare provider time strings until their live format is confirmed. Reads are
thread-safe, and full snapshots are read-only point-in-time copies so callers
cannot mutate shared state.

Vietcap binary match-price events enter through
`data.vietcap.pipeline.MatchPriceStatePipeline`, which performs decode,
validation/normalization, expected-symbol filtering, and cache update in that
order. Malformed or unexpected events are logged and do not alter market state.

## Universe

Data universe:
- HOSE
- HNX
- UPCoM

Strategy scanner should later use:
- common stocks only
- exclude ETF/CW/fund/bond where applicable
- liquidity filter
- daily pre-screen
- smaller realtime watch universe

## Planned V1 signal features
- Market Regime
- Trend
- Relative Strength vs VNINDEX
- time-matched intraday RVOL
- Breakout
- risk levels

No single indicator should directly trigger a final Buy/Sell decision.

## Alert lifecycle
WATCH → MONEY_FLOW → BREAKOUT → CONFIRMED → ACTIVE → EXIT

## News
News is V2/bonus and must not block core bot delivery.
