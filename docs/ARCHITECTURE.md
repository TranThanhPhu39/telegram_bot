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

## V1 database

V1 uses Python's standard-library SQLite driver behind `data.database`.
`DATABASE_URL=sqlite:///stock_bot.db` remains the local default. The connection
boundary enables foreign-key enforcement, a five-second busy timeout, and named
row access. It creates no application tables; schema creation and migrations are
separate Phase 9 tasks. SQLite is appropriate for the initial single-process bot
and can later be replaced behind this boundary if write concurrency grows.

The first incremental schema object is `symbols`, keyed by the normalized symbol.
It stores an optional normalized exchange, a normalized instrument type (default
`STOCK`), and an active flag. Exchange values are not restricted to a hard-coded
venue list so index and future provider metadata can be represented without a
schema migration. Table creation is idempotent and separate from connection setup.

`candles` stores provider-independent OHLCV bars and references `symbols`. Its
composite primary key `(symbol, timeframe, timestamp)` prevents duplicate bars
while allowing multiple intervals. Database constraints require normalized
timeframes, positive integer timestamps, positive OHLC prices, non-negative
volume, and valid high/low relationships. Symbol deletion is restricted while
bars reference it; table creation is idempotent.

`signals` stores one high-level record per signal lifecycle, using an integer
identity so the same symbol/strategy/timeframe may produce later independent
signals. It references `symbols` and stores normalized strategy, timeframe, and
state identifiers, created/updated Unix timestamps, an optional trigger price,
and a valid JSON reason payload. State values are deliberately not hard-coded
before the Phase 13 strategy state machine is implemented. An index supports
recent-signal lookup by symbol.

`signal_events` is the append-oriented audit trail for one signal lifecycle. It
uses a unique `(signal_id, sequence)` pair, records occurrence time, optional
source state, required destination state, optional price, and a valid JSON reason
payload. The first event may have no source state. Signal deletion is restricted
while events exist so lifecycle history cannot disappear accidentally. State
transition rules remain the responsibility of the Phase 13 strategy engine.

`data.migrations.bootstrap_schema` owns ordered, atomic schema startup. Version 1
creates all four application tables and their indexes in dependency order, then
records the migration in `schema_migrations`. Repeated startup is idempotent and
preserves data. A database containing an unknown newer version or a changed
migration identity is rejected instead of being modified blindly.

## Candle and indicator layer

`data.candles.OneMinuteBarBuilder` aggregates normalized `TradeTick` values by
symbol and Unix-minute bucket into immutable `OHLCVBar` values. The caller must
supply the tick's Unix timestamp because Vietcap's exchange-time string remains
unverified. A bar closes when a later minute for that symbol arrives or when the
builder is explicitly flushed. Missing minutes are not synthesized, symbols are
tracked independently, and an out-of-order tick older than the active bucket is
rejected.

`data.indicators` contains provider-independent functions over chronological
`OHLCVBar` sequences:

- EMA20 and EMA50 use an SMA seed followed by the standard EMA recurrence.
- RSI14 and ATR14 use Wilder smoothing.
- daily average volume uses only the preceding completed daily bars and excludes
  the current bar.
- relative strength is the stock percentage return minus VNINDEX percentage
  return over an identical lookback; both series must have exactly aligned
  timestamps.
- breakout resistance/support are the highest high and lowest low of preceding
  completed bars and exclude the current bar.

Indicator series align one-to-one with their inputs and return `None` during
warm-up. These boundaries prevent look-ahead and keep the layer usable by both
future live and backtest paths.

## Intraday RVOL layer

`data.rvol.time_matched_rvol` compares the current session's cumulative volume
at each one-minute bar with the mean cumulative volume of prior sessions at the
same Vietnam-local clock minute:

`RVOL(t) = cumulative_volume_today(t) / mean(prior_session_cumulative_volume(t))`

Historical sessions must have unique local dates strictly earlier than the
current session and must contain the same symbol. Each baseline uses only bars at
or before the target clock minute; a missing historical minute carries forward
that session's latest earlier cumulative value. Full-day volume and later
intraday bars are never used for an earlier RVOL point. A zero historical
baseline yields an unavailable (`None`) ratio rather than infinity. Inputs and
outputs remain provider-independent, so live and backtest paths can share this
implementation.

## Market regime layer

`data.market_regime.classify_vnindex_regime` combines two independent inputs:

- VNINDEX trend is bullish for `value > EMA20 > EMA50`, bearish for
  `value < EMA20 < EMA50`, and mixed or unavailable otherwise.
- breadth score is `(advances - declines) / (advances + declines + unchanged)`.

Ceiling and floor counts do not enter the denominator because they may overlap
with advances and declines. Bull requires both bullish trend and breadth at or
above the configured positive threshold. Bear requires both bearish trend and
breadth at or below its negative counterpart. Every other combination is
Neutral. Missing EMAs or an insufficient breadth population also produce a
conservative Neutral result.

Threshold and minimum breadth population are mandatory configuration, not hidden
strategy constants, so they can be evaluated in Phase 16 backtests. The immutable
assessment carries the trend, breadth score, population, and explanatory reasons
for later signal and Telegram consumers.

## Signal engine

`strategy.signal_engine.SignalEngine` is the provider-independent state machine
shared by future live and backtest paths. Each symbol owns an independent
lifecycle:

`WATCH -> MONEY_FLOW -> BREAKOUT -> CONFIRMED -> ACTIVE -> EXIT`

The first observation opens `WATCH`. Money flow requires Bull market regime,
confirmed stock trend, and configurable minimum Relative Strength and RVOL.
`BREAKOUT` requires an explicit breakout input; `CONFIRMED` rechecks breakout and
all money-flow evidence; `ACTIVE` requires those confirmations to persist.
`EXIT` requires an explicit upstream exit condition, because Phase 13 does not
guess stop-loss or sell rules that have not been designed.

One observation can advance at most one state. Exact repeated observations emit
no duplicate event, out-of-order observations are rejected per symbol, and an
exited lifecycle cannot restart until its configurable cooldown has elapsed. A
restart opens a new lifecycle with sequence one and no source state, matching the
Phase 9 database model.

Every emitted event includes positive factors, negative factors, missing
confirmations, and a trigger description in a JSON-serializable reason payload.
Thresholds and cooldown are explicit configuration for later backtesting.

## Universe

`scanner.universe.daily_prescreen` consumes provider-independent instrument
metadata and normalized completed daily bars. The supported universe is:

- HOSE
- HNX
- UPCoM

Only active `STOCK`/`COMMON_STOCK` instruments are eligible; ETF, CW, fund, bond,
index, inactive, and unsupported-exchange records are excluded. This filtering
depends on upstream instrument metadata; Phase 14 does not invent security types
from ticker names.

The daily pre-screen requires an explicit lookback, minimum average daily volume,
minimum average daily traded value, and `as_of` timestamp. Average traded value is
computed as mean `close * volume` across the latest completed lookback window.
Only bars strictly earlier than `as_of` participate, preventing current/future
data leakage. Symbols without enough completed history fail closed.

`realtime_watch_universe` bounds realtime load by taking the configured number of
most liquid screened symbols, ranked by average daily value, then volume, then
symbol. Both pre-screen and watch-list ordering are deterministic. The scanner
does not fetch a listing catalog; a future provider adapter must supply normalized
metadata and history.

## Telegram layer

`telegram_bot` uses pinned `python-telegram-bot` and reads
`TELEGRAM_BOT_TOKEN` only from local environment configuration. Application
wiring registers `/start`, `/help`, `/soi`, `/scan`, `/market`, and `/why`.
Rendering is separated behind `BotDataService`, so handlers do not call Vietcap
or strategy internals directly and can be connected to the live orchestrator
later. The runnable fallback reports unavailable data instead of fabricating it.

`TelegramAlertPublisher` formats `SignalEvent` transitions and deduplicates by
chat, symbol, lifecycle, and sequence. A delivery is marked sent only after
Telegram accepts it, so a failed attempt remains retryable. `scripts/test_telegram`
performs a bounded `getMe` authentication check without printing the token;
`scripts/run_telegram_bot` starts long polling.

## Backtest and performance layer

`backtest.engine.run_backtest` replays chronological `SignalInputs` through the
same `strategy.signal_engine.SignalEngine` class used by live callers. It opens a
simulated position only on `ACTIVE` and closes only on `EXIT`; it does not place
orders or invent fills outside event prices. Open positions are reported rather
than silently marked to market.

Closed trades produce win rate, arithmetic average trade return, compounded-equity
maximum drawdown, and profit factor. Profit factor is unavailable when there are
no losing trades rather than reported as an artificial infinite number.
`/performance` is exposed through the Telegram data-service boundary.

`scripts/run_preliminary_backtest` is a bounded diagnostic using the latest 120
aligned ACB and VNINDEX daily bars. Its daily volume ratio and trend-only index
regime are clearly marked as preliminary proxies, not final live-strategy
evidence. The accepted sample spans 175 calendar days and produced zero closed
trades. Metrics therefore describe zero activity and make no profitability claim.

## Fundamental context layer

V1 selects controlled UTF-8 CSV snapshots as the fundamental source boundary.
Every row must include a normalized symbol, ISO as-of date, and non-empty source
provenance alongside optional EPS, P/E, P/B, ROE percentage, revenue-growth
percentage, and profit-growth percentage. This avoids coupling core strategy code
to an unstable, undocumented, or unlicensed API; a licensed provider export can be
normalized into the same schema later.

`fundamentals.filter` evaluates explicit thresholds and returns `PASS`, `FAIL`, or
`INSUFFICIENT_DATA` with positive, negative, and missing factors. Missing values do
not silently pass or fail. The result can be applied after the Phase 14 liquidity
screen, with configurable treatment of insufficient data, or exposed purely as
context. It is not imported by `SignalEngine` and cannot directly create a signal.

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
