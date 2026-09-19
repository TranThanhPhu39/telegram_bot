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

## Normalized index data

`data.models.IndexSnapshot` is the provider-independent boundary for decoded
index updates. It is a separate immutable model from `TradeTick` because index
semantics differ from stock trade semantics: an index carries breadth counters
and no per-trade volume. The two models are deliberately not merged.

`estimatedChange` and `estimatedFsp` exist in the Vietcap schema but are not
normalized, because their meaning is undocumented.

## Latest index state

`data.market_state.LatestIndexState` stores one immutable `IndexSnapshot` per
normalized index identifier, mirroring `LatestMarketState` for stocks but
without sharing storage or accepting the other model's type. Index identifiers
are case-sensitive on the Vietcap wire (`HNXIndex`), so subscription payloads
preserve provider casing while normalized state keys are upper-cased.

Vietcap binary `index` events enter through
`data.vietcap.pipeline.IndexStatePipeline`, which performs decode,
validation/normalization, expected-index filtering, and cache update in that
order. Malformed, invalid, or unexpected index events are logged and do not
alter index state.

## Normalized order-book data

`data.models.OrderBook` is the provider-independent boundary for decoded
bid-ask events, built from immutable `OrderBookLevel` values held in tuples so
cached depth cannot be mutated. Levels keep the order the provider sent them,
because the schema does not document a sort order. `bidCount` and `askCount`
exist in the Vietcap schema but are not normalized, because their meaning is
undocumented.

`data.market_state.LatestOrderBookState` stores one `OrderBook` per normalized
symbol, alongside but separate from `LatestMarketState` and `LatestIndexState`;
none of the three accepts another's model type. Vietcap binary `w-bid-ask`
events enter through `data.vietcap.pipeline.BidAskStatePipeline`, which
performs decode, validation/normalization, expected-symbol filtering, and cache
update in that order.

## Realtime reliability

`VietcapRealtimeClient` enables the reconnect mechanism provided by
`python-socketio`. Retry delay starts at one second, doubles after each failed
attempt, caps at 30 seconds, and applies a 0.5 jitter factor. Attempts continue
until success or an explicit client stop. Desired match-price, index, and bid-ask
subscriptions persist separately from active connection state and are restored in
that order after reconnect. Failure to restore one stream is logged and does not
prevent restoration attempts for the remaining streams. Lifecycle listeners are
registered once during client construction, while market listeners are registered
only through the explicit `on_*` methods; reconnect restores subscriptions without
registering another listener. Each realtime pipeline catches expected payload type,
protobuf decode, and validation errors at its boundary, logs the rejected event,
leaves market state unchanged, and remains available for the next valid frame.
An opt-in raw debug wrapper can log event name, payload runtime type, and byte
length before handler dispatch. It is disabled by default, never logs payload
content, and caps records per event with thread-safe counters while continuing to
deliver every payload to the handler.

## Historical REST acquisition

`data.vietcap.rest.VietcapRestClient` owns provider-specific HTTP acquisition.
Calls use explicit timeouts and convert network, HTTP, JSON, and top-level shape
failures to `VietcapRestError`. Stock symbols are restricted to normalized ASCII
letters and digits before URL construction. Quote responses remain detached,
provider-native mappings until successful runtime evidence defines their fields;
downstream strategy code must not consume these mappings directly.
The same client constructs the provider-native `gap-chart` POST body and validates
transport-level inputs and failures. Timeframe support and conversion from
columnar arrays to normalized bars remain separate layers. Supported request
timeframes are represented by a closed string enum containing only `ONE_MINUTE`,
`ONE_HOUR`, and `ONE_DAY`; arbitrary interval strings are rejected before I/O.

`data.models.OHLCVBar` defines the immutable provider-independent destination
for historical bars. `data.vietcap.historical.normalize_gap_chart` validates the
observed columnar `t/o/h/l/c/v` arrays and converts them to these bars. Provider
timestamps arrive as decimal Unix-seconds strings and normalize to integers.
Acquisition remains separate: the REST client returns deeply detached provider
rows, while malformed columns, non-finite values, invalid OHLC relationships,
and negative volume are rejected at the normalization boundary.
Authenticated acquisition accepts authorization, device ID, and cookie only as
runtime inputs. The provider also required the observed same-origin browser
request headers during live verification; no credential value is logged or
stored in tracked files.

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
