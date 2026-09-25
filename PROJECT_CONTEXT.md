# PROJECT CONTEXT

## 1. Project Goal

Build a modular realtime Vietnamese stock signal bot for HOSE, HNX, and UPCoM, eventually exposed through Telegram. The current milestone is a reliable, verified Vietcap market-data layer. Brokerage trading and real order execution are explicitly out of scope.

## 2. Current Architecture

Implemented foundation:

```text
data.models.TradeTick              provider-independent immutable trade model
data.models.OHLCVBar               provider-independent immutable historical bar
data.market_state.LatestMarketState thread-safe latest-tick cache by symbol
data.vietcap
    -> proto/price.proto          vendored, minimally normalized schema
    -> proto/price_pb2.py         generated Python protobuf binding
    -> tests/test_proto.py        protobuf contract and round-trip tests
    -> constants.py               Vietcap connection defaults
    -> client.py                  Socket.IO lifecycle and deduplicated subscriptions
    -> subscriptions.py           normalized FPT + ACB payload construction
    -> decoder.py                 binary MatchPrice protobuf decoding
    -> validation.py              decoded match-price quality checks
    -> normalizer.py              MatchPriceMessage -> TradeTick conversion
    -> pipeline.py                binary event -> normalized latest state
scripts/inspect_connection.py     live connection smoke test, no subscriptions
scripts/test_realtime.py          Phase 3 live FPT-only acceptance test
scripts/test_realtime_market_state.py Phase 4 FPT + ACB acceptance harness
tests/test_client.py              deterministic connection configuration tests
```

Planned layering:

```text
Vietcap realtime/historical (future alternative: DNSE)
    -> provider acquisition and protobuf decoding
    -> provider-independent normalized market data
    -> market state
    -> indicators and market regime
    -> shared live/backtest signal engine
    -> alert manager
    -> Telegram
```

Vietcap-specific transport, event names, protobuf classes, and decoding remain under `data.vietcap`. Strategy code must not call Vietcap endpoints or consume Vietcap protobuf objects directly.

## 3. Current Development Phase

Phase 26 remains open only for its remaining external live checks. The Phase 24
provider follow-up is complete: VNStock 4.0.8/KBS, yfinance fallback, and live
promotion safety all passed on 2026-09-21. Phase 22 active-session acceptance and
the Phase 25 worker-in-real-bot check remain NOT TESTED.

## Current Operational Status (Updated 2026-09-22)

All 8 post-Phase-26 operational/UX issues were code-complete, tested, and integrated as of
2026-09-21. Live testing on 2026-09-22 found items 2 and 4 below were not actually wired
into the production process despite being marked Resolved; see the corrections inline and
`## 2026-09-22 — Live Acceptance Fix Round (Phase 28), Issues 1–4` at the end of this file:

1. **Latest-five ticker sentiment (Resolved):**
   - Migrated from strict 24h query window to canonical `eligible_articles(ticker, limit=5, max_age_days=30)`.
   - Unified selection path across `/tin`, `/sentiment`, and `/soi`. Zero eligible articles correctly reports `MISSING` (never fake Neutral).
   - Preserved 48-hour severe-negative ASMF blocker recency independently.

2. **Full-market scanner & universe (Code Resolved 2026-09-21; ⚠️ live testing on 2026-09-22 found `/scan` still returned only `2/2` mã in the real bot process — fixed separately as Phase 28 Issue 1, see below):**
   - Removed reliance of `/scan` on `BOT_WATCH_SYMBOLS`. Universe is dynamically loaded from active HOSE/HNX/UPCoM common stocks in SQLite via `load_market_universe()`.
   - Live-confirmed working 2026-09-22 after the Phase 28 Issue 1 fix: `universe=1524`, `/scan` no longer shows `2/2`.

3. **Background scanner worker & SQLite snapshot persistence (Resolved):**
   - Created `runtime/scanner_worker.py` with `MarketScannerWorker` daemon thread and `run_scan_cycle()`.
   - Created Migration 9 (`scan_snapshots` table and index) to persist full-market scans.
   - `/scan` reads latest snapshot from SQLite cache in <10ms with strategy support (CL1 and ASMF) and fallback.

4. **Realtime breadth in Telegram market context (Code Resolved 2026-09-21; ⚠️ was dead code in production — fixed & live-validated 2026-09-22, see Phase 28 Issue 2):**
   - `market_overview()` was written to read `index_state`, displaying advances/declines/ceiling/floor and liquidity, with a historical trend-only fallback when unavailable — but `build_runtime_service_from_env()` never constructed or passed an `index_state`, and no worker ever populated one, so `/market` always showed `BREADTH: unavailable` in the real bot. `stock_analysis()` (`/soi`) never read breadth at all, wired or not.
   - Fixed 2026-09-22: added `runtime/index_stream_worker.py` (bounded daemon-thread worker over the existing, previously standalone-only, Vietcap realtime index socket pipeline), wired `index_state` into `build_runtime_service_from_env()`, and shared the breadth/liquidity lookup between `market_overview()` and `stock_analysis()` via `RuntimeBotDataService._index_breadth_liquidity()`.
   - Live-confirmed 2026-09-22: `/market` and `/soi` both show live breadth (e.g. `143 tăng (3 trần) / 148 giảm (7 sàn) / 64 tham chiếu`) and `Regime: BULL (xu hướng EMA + breadth ...)`.
   - Known follow-up: live output showed `LIQUIDITY: 0 tỷ` despite a plausible non-zero traded volume — suspected unit/field issue in the realtime index `total_value` field. Root-caused and fixed 2026-09-22 as Phase 28 Issue 3, see below.

4b. **Market-wide liquidity unavailable (Fixed & live-validated 2026-09-22, see Phase 28 Issue 3):**
   - Root cause was a unit mismatch, not a missing data source: the Vietcap realtime index stream's `totalValue` field is in triệu đồng (millions of VND), not raw VND as `normalize_index()` assumed, so the existing plausibility guard (correctly) rejected the tiny implied average price and reported `unavailable`.
   - Fixed by scaling `totalValue` to VND at the normalization boundary (`data/vietcap/normalizer.py`); no change needed to `runtime/bot_service.py`'s plausibility check or "tỷ" formatting, which already assumed VND input.
   - Live-confirmed 2026-09-22: `/market` shows `LIQUIDITY: 11,103 tỷ (458,208,014 CP)` with a plausible implied average price (~24,230 VND/share).

4c. **Foreign/proprietary flow unavailable (Root cause fixed & live-validated 2026-09-22, see Phase 28 Issue 4):**
   - Two independent things, audited separately: the market-wide `/market` field has no data source anywhere in the repo (stays honestly "unavailable" — BLOCKED BY DATA SOURCE, not a bug); the per-symbol `INSTITUTIONAL` coverage chain had a real mislabeling bug where an all-MISSING result was attributed to `yfinance` (the last provider tried) instead of honestly reflecting that no provider, including the authoritative VNStock/Vietcap one, had data.
   - Fixed by changing `ProviderChain._run()`'s all-MISSING fallback to report `provider="none"` with an honest `error_reason` listing every provider attempted.
   - Live-confirmed 2026-09-22: `ACB` coverage now shows `provider=none reason=no provider had data (attempted: VNStock:MISSING, yfinance:MISSING)` instead of `provider=yfinance`.
   - Confirmed `foreign_buy/sell_value` and `proprietary_buy/sell_value` are already tracked as fully independent nullable fields in `FlowRow`/`InstitutionalFlow`; "ownership" data has no representation anywhere in the repo, so there is no conflation risk to fix.
   - Researched (not implemented): DNSE OpenAPI's official SDK documents a `foreign_investor` WebSocket topic (realtime, per-instrument foreign trading data) as a possible future foreign-flow source, but no proprietary/tự doanh equivalent was found in the same docs. Integrating it would be a new provider (API key/secret, adapter, auth) — out of scope here, needs its own issue if pursued.

5. **Compact `/soi` dashboard (Resolved):**
   - Overview condensed into concise high-value summary; detailed technical levels, fundamentals, and strategy conditions are accessible via inline buttons and direct commands.

6. **Telegram callback message editing (Resolved):**
   - Text callback actions edit and update the existing message via `query.edit_message_text()` instead of spamming new messages.
   - Preserved `reply_photo` for chart PNG rendering.

7. **`/why` data quality deduplication (Resolved):**
   - Prevented double printing of `data_quality.notes` in `format_why()` by passing `include_notes=False`.

8. **ASMF score & market presentation (Resolved):**
   - Explicitly labelled ASMF score as `Điểm bằng chứng (Evidence score): XX.X/100 (tổng hợp điểm, không phải xác suất)`.
   - Separated core layer coverage (`Độ phủ tầng cốt lõi: X/4 tầng`) from Sentiment context.
   - Differentiated `General Market Context` from `ASMF Market Filter`.

External live validations still pending (requiring live market session and external bot host):
- active-session `/soi`, `/market`, `/sentiment` (Market hours 09:00 - 14:45 ICT);
- real Vietcap → PNG → Telegram `/chart` (Requires live Telegram bot token);
- Phase 25 coverage worker inside the production bot process.

## 4. Completed

- [x] Phase 0 repository bootstrap and planning
- [x] Python 3.12.10 runtime verified
- [x] Minimal `data` and `data.vietcap` packages created
- [x] Vietcap `price.proto` retrieved and vendored
- [x] Upstream schema provenance and SHA-256 recorded
- [x] Package `pricePackage` verified
- [x] `MatchPriceMessage` verified
- [x] `BidAskMessage` and `BidAskPrice` verified
- [x] `IndexMessage` verified
- [x] Python protobuf classes generated
- [x] Required messages instantiated, serialized, and decoded in unit tests
- [x] Project-local dependency environment validated
- [x] Socket.IO and Engine.IO v4 compatibility tested
- [x] Direct WebSocket connection established without credentials
- [x] Connect, disconnect, error, and protocol metadata logging added
- [x] 35-second live connection survived a PING/PONG heartbeat
- [x] Phase 2 emitted no market subscription events
- [x] `w-match-price` handler and FPT-only JSON-string subscription implemented
- [x] Live client emission confirmed as `{"symbols":["FPT"]}`
- [x] MatchPrice decoder and field validation unit-tested
- [x] FPT + ACB subscription payload implemented and unit-tested
- [x] Duplicate symbols and unchanged subscription sets suppressed
- [x] Provider-independent immutable `TradeTick` model implemented
- [x] Validated `MatchPriceMessage` to `TradeTick` conversion unit-tested
- [x] Thread-safe latest market-state cache implemented and unit-tested
- [x] FPT + ACB decode-to-cache pipeline and bounded acceptance harness implemented
- [x] Socket.IO automatic reconnect handling enabled and unit-tested
- [x] Explicit exponential reconnect backoff configured and unit-tested
- [x] Desired subscriptions restored automatically after reconnect in unit tests
- [x] Listener registration remains single across repeated reconnect cycles in unit tests
- [x] Decode failures are isolated and all three realtime pipelines recover in unit tests
- [x] Bounded metadata-only raw debug mode implemented and unit-tested
- [x] Vietcap quote REST acquisition implemented and unit-tested
- [x] Vietcap OHLC gap-chart request contract implemented and unit-tested
- [x] ONE_MINUTE, ONE_HOUR, and ONE_DAY request semantics implemented and unit-tested
- [x] Evidence-backed gap-chart OHLCV normalization and fixture tests implemented
- [x] Authenticated Python historical fetch and normalization verified live
- [x] SQLite selected for V1 and connection boundary unit-tested
- [x] Normalized SQLite `symbols` table implemented and unit-tested
- [x] Provider-independent SQLite `candles` table implemented and unit-tested
- [x] High-level SQLite `signals` table implemented and unit-tested
- [x] Ordered SQLite `signal_events` audit table implemented and unit-tested
- [x] Versioned SQLite schema bootstrap implemented and file-tested
- [x] Provider-independent one-minute candle builder implemented and unit-tested
- [x] EMA20, EMA50, RSI14, and ATR14 implemented and unit-tested
- [x] Prior-completed-bar daily average volume implemented and unit-tested
- [x] Timestamp-aligned Relative Strength versus VNINDEX implemented and unit-tested
- [x] Prior-period breakout resistance/support implemented and unit-tested
- [x] Time-matched intraday RVOL implemented and unit-tested without look-ahead
- [x] Explainable VNINDEX trend-and-breadth market regime implemented and unit-tested
- [x] Provider-independent V1 signal lifecycle with cooldown/dedup implemented and unit-tested
- [x] HOSE/HNX/UPCoM common-stock liquidity scanner and bounded watch universe implemented
- [x] Telegram commands, live token authentication, and deduplicated signal alerts implemented
- [x] Shared SignalEngine backtest adapter and performance metrics implemented and unit-tested
- [x] Preliminary 120-session ACB/VNINDEX backtest executed with explicit proxy limitations
- [x] Provider-independent fundamental CSV source and explainable scanner context implemented
- [x] Telegram runtime connected to Vietcap history, SQLite, indicators, and scanner
- [x] Sunday fallback verified against Friday 2026-09-18 ACB and VNINDEX data
- [x] Selectable CL1 and honest partial-data ASMF strategy runtime implemented
- [x] Point-in-time ASMF sector/BCTC/institutional-flow foundation implemented
- [x] Bank-specific financial schema and ASMF quality score implemented
- [x] Binary `w-match-price` event received from Vietcap
- [x] Realtime FPT message decoded and validated
- [x] Two distinct valid FPT ticks observed
- [x] Simultaneous FPT + ACB live ticks normalized into latest market state
- [x] Two distinct VNINDEX snapshots with breadth and liquidity cached live
- [x] Distinct FPT + ACB bid/ask books normalized and cached live
- [x] Forced WebSocket interruption recovered with automatic FPT resubscription

## 5. Currently Working On

The Phase 24 live-provider compatibility follow-up is complete. The project now
pins VNStock 4.0.8, reads its real KBS wide semantic financial statements, keeps
yfinance as the strict fallback, and retains all point-in-time/bank promotion
safety rules. No later phase was started.

## 6. Files Created / Modified

### `runtime/bot_service.py`

Purpose: concrete Telegram data service joining Vietcap daily history, SQLite
cache, indicators, scanner configuration, and closed-market responses.

Status: provider success, empty response, network failure, SQLite fallback, command
rendering, indicator context, scanning, and performance output are covered offline;
Sunday live fallback also passed.

### `scripts/test_runtime_bot_live.py`

Purpose: bounded live acceptance for `/soi ACB` and `/market` equivalent runtime
responses without starting indefinite Telegram polling.

Status: PASS on 2026-09-20; both responses used session 2026-09-18.

### `fundamentals/models.py`, `fundamentals/csv_source.py`, `fundamentals/filter.py`

Purpose: normalized point-in-time fundamentals, strict provenance-bearing CSV
ingestion, explainable threshold assessment, and optional scanner filtering.

Status: all six requested metrics, missing data, provenance, schema validation,
threshold failures, and scanner integration are covered by thirteen focused tests.

### `tests/test_fundamentals.py`

Purpose: deterministic Phase 17 source, normalization, assessment, and integration
acceptance coverage.

Status: thirteen focused tests pass; the full suite passes with 378 tests.

### `backtest/engine.py`

Purpose: replay chronological observations through the production SignalEngine,
record ACTIVE-to-EXIT trades, and calculate deterministic performance metrics.

Status: shared-engine lifecycle, win rate, average return, compounded max drawdown,
profit factor, empty results, open positions, formatting, and ordering are covered
by five focused tests.

### `scripts/run_preliminary_backtest.py`

Purpose: bounded authenticated 140-session FPT/VNINDEX preliminary backtest probe.

Status: PASS as a preliminary runtime diagnostic. Separate ACB and VNINDEX
requests produced 170 aligned bars; the latest 120 sessions span 175 calendar
days. The run emitted zero trades and clearly labels its daily proxies.

### `tests/test_backtest.py`

Purpose: deterministic offline acceptance for the backtest and metric layer.

Status: five focused tests pass; the full suite passes with 365 tests.

### `telegram_bot/commands.py`, `telegram_bot/app.py`, `telegram_bot/alerts.py`

Purpose: pure command rendering, python-telegram-bot handler wiring, environment
token loading, and deduplicated SignalEvent alert delivery.

Status: all required commands, safe unavailable-data fallback, handler registry,
formatting, successful deduplication, and failed-send retry behavior are unit-tested.

### `scripts/run_telegram_bot.py` and `scripts/test_telegram.py`

Purpose: long-polling entry point and bounded live token authentication check.

Status: Telegram `getMe` returned PASS for the configured bot without exposing the
token. The polling process itself was not left running during acceptance.

### `tests/test_telegram_bot.py`

Purpose: deterministic Phase 15 command and alert acceptance coverage.

Status: eight focused tests pass; the full suite passes with 360 tests.

### `scanner/universe.py`

Purpose: provider-independent exchange/type filtering, daily liquidity pre-screen,
and bounded deterministic realtime watch-universe selection.

Status: three-exchange coverage, exclusions, liquidity thresholds, completed-bar
lookback, no-look-ahead boundary, ranking, and validation are covered by sixteen
focused tests.

### `scanner/__init__.py` and `tests/test_scanner_universe.py`

Purpose: scanner package boundary and deterministic Phase 14 acceptance suite.

Status: sixteen focused tests pass; the full suite passes with 352 tests.

### `strategy/signal_engine.py`

Purpose: provider-independent, deterministic V1 signal state machine intended for
both live and backtest callers.

Status: all six states, transition gates, independent symbols, explanations,
deduplication, ordering, cooldown, lifecycle restart, and validation are covered
by sixteen focused tests.

### `strategy/__init__.py` and `tests/test_signal_engine.py`

Purpose: strategy package boundary and deterministic Phase 13 acceptance suite.

Status: sixteen focused tests pass; the full suite passes with 336 tests.

### `data/market_regime.py`

Purpose: combines normalized VNINDEX trend and breadth into an immutable,
explainable Bull/Neutral/Bear assessment using explicit configuration.

Status: classification, boundary, missing/conflicting evidence, input validation,
and configuration behavior are covered by fifteen focused tests.

### `tests/test_market_regime.py`

Purpose: deterministic Phase 12 acceptance coverage without provider or network
dependencies.

Status: fifteen focused tests pass; the full suite passes with 320 tests.

### `data/rvol.py`

Purpose: calculates provider-independent time-matched intraday RVOL from one
current one-minute session and one or more earlier historical sessions.

Status: same-clock-time baselines, missing minutes, zero baselines, input
validation, and no-look-ahead boundaries are covered by eight focused tests.

### `tests/test_rvol.py`

Purpose: deterministic Phase 11 acceptance coverage using explicit Vietnam-local
session timestamps and synthetic normalized bars.

Status: eight focused tests pass; the full suite passes with 305 tests.

### `data/candles.py`

Purpose: aggregates normalized trades into independent per-symbol one-minute
OHLCV bars using explicit Unix timestamps.

Status: minute rollover, OHLCV aggregation, gaps, multiple symbols, flush, and
invalid/out-of-order input are covered by three focused tests.

### `data/indicators.py`

Purpose: provides provider-independent EMA, RSI, ATR, daily average volume,
relative strength, and breakout-level calculations over normalized bars.

Status: warm-up, Wilder/SMA-seeded formulas, input alignment, validation, and
no-look-ahead boundaries are covered by nine focused tests.

### `tests/test_candles.py` and `tests/test_indicators.py`

Purpose: deterministic Phase 10 acceptance coverage without network or market
session dependencies.

Status: twelve focused tests pass; the full suite passes with 297 tests.

### `data/database.py`

Purpose: validates V1 SQLite URLs and opens consistently configured connections.

Status: unit-tested with in-memory and temporary file databases. It intentionally
creates no application tables yet.

### `tests/test_database.py`

Purpose: verifies URL rejection, connection pragmas, empty initial schema, and
file-backed persistence without touching the configured production database.

Status: nine focused tests pass.

### `data/schema.py`

Purpose: contains incremental, provider-independent SQLite table definitions.

Status: creates all four planned application tables while preserving existing
rows when individual table functions are invoked repeatedly.

### `tests/test_schema_symbols.py`

Purpose: verifies columns, defaults, accepted stock/index rows, normalization
constraints, primary-key uniqueness, and idempotent table creation.

Status: twelve focused tests pass.

### `tests/test_schema_candles.py`

Purpose: verifies candle columns and composite identity, OHLCV constraints,
symbol foreign keys, deletion protection, and idempotent table creation.

Status: seventeen focused tests pass.

### `tests/test_schema_signals.py`

Purpose: verifies signal identity, normalized metadata, timestamps, optional
trigger price, JSON reason payload, symbol foreign key, lookup index, and
idempotent table creation.

Status: nineteen focused tests pass.

### `tests/test_schema_signal_events.py`

Purpose: verifies ordered transition identity, initial and later transitions,
signal foreign keys, audit deletion protection, normalized states, timestamps,
optional price, JSON reasons, lookup index, and idempotent creation.

Status: twenty focused tests pass.

### `data/migrations.py`

Purpose: applies ordered SQLite schema migrations atomically and records their
version/name identity in `schema_migrations`.

Status: version 1 creates the complete Phase 9 schema; repeat startup, file
reopen, future-version rejection, and identity mismatch are unit-tested.

### `tests/test_migrations.py`

Purpose: verifies complete file bootstrap, migration persistence, idempotency,
data preservation, and safe rejection of incompatible database versions.

Status: six focused tests pass.

### `requirements.txt`

Purpose: reproducible protobuf, test, Socket.IO, and WebSocket dependencies.

Direct dependencies: `protobuf==7.36.2`, `grpcio-tools==1.82.2`, `pytest==9.1.1`, `python-socketio[client]==5.17.0`, `websocket-client==1.9.2`, and `requests==2.34.2`.

Status: installed into the ignored project-local `.venv`; `pip check` passes.

### `data/vietcap/proto/price.proto`

Purpose: vendored Vietcap frontend protobuf schema.

Main messages in current scope: `MatchPriceMessage`, `BidAskPrice`, `BidAskMessage`, `IndexMessage`.

Dependencies: standard protobuf compiler/runtime.

Status: retrieved and verified. It differs from the 6,319-byte upstream response only by moving `syntax = "proto3";` before `package pricePackage;`, which is required by standard `protoc`.

### `data/vietcap/proto/price_pb2.py`

Purpose: generated Python classes for `price.proto`.

Main classes in current scope: `MatchPriceMessage`, `BidAskPrice`, `BidAskMessage`, `IndexMessage`.

Dependencies: `protobuf` runtime.

Status: generated by `grpcio-tools==1.82.2`; import and round-trip tests pass. Do not hand-edit.

### `data/vietcap/proto/__init__.py`

Purpose: exposes the generated protobuf directory as a Python package.

Status: created and import-tested.

### `data/vietcap/proto/README.md`

Purpose: schema source, retrieval evidence, normalization note, and regeneration instructions.

Status: updated.

### `tests/__init__.py`

Purpose: marks the test namespace.

Status: created.

### `tests/test_proto.py`

Purpose: verifies the protobuf package, required full message names, and serialize/decode round trips for the three required message types.

Status: four tests pass.

### `data/vietcap/constants.py`

Purpose: centralizes the default Socket.IO URL, path, timeout, reconnect/backoff settings, and WebSocket-only transport selection.

Status: reconnect and explicit backoff defaults are covered by client tests.

### `data/vietcap/client.py`

Purpose: manages connection/reconnection, disconnect, heartbeat-friendly sleep, lifecycle logging, and the three scoped market subscriptions.

Main classes/functions: `VietcapRealtimeClient`, `ConnectionInfo`, `normalize_socketio_path`.

Dependencies: `python-socketio` and its synchronous client transport stack.

Status: automatic reconnect, explicit backoff, restoration of desired subscriptions,
single listener registration, and bounded raw debug metadata are unit-tested.
Forced WebSocket interruption and automatic FPT stream recovery passed live at
10:06 ICT on 2026-09-21. Namespace readiness during the library's reconnect
callback ordering is handled explicitly.

### `scripts/inspect_connection.py`

Purpose: human-readable connection smoke test with configurable hold time, timeout, and Engine.IO logs.

Status: direct script entry point verified; 35-second live smoke test passed without subscriptions.

### `scripts/test_realtime_reconnect.py`

Purpose: bounded Phase 7 harness that requires a valid FPT tick before an
intentional WebSocket interruption, a new Socket.IO connection generation, and
a valid FPT tick after automatic subscription restoration.

Status: live acceptance PASS at 10:06 ICT on 2026-09-21.

### `scripts/__init__.py`

Purpose: marks the scripts namespace.

Status: created.

### `tests/test_client.py`

Purpose: verifies path normalization, WebSocket-only connection arguments, reconnect configuration, lifecycle handlers, idempotent disconnect, all stream registrations/subscriptions, duplicate suppression, and reset after disconnect without network access.

Status: all 34 client tests pass; the complete regression suite passes with
646 tests.

Raw debug behavior: disabled by default. When enabled, it logs only event name,
payload type, payload size, sequence number, limit, and whether the limit was
reached. It never logs payload content and defaults to 20 records per event.

### `data/vietcap/subscriptions.py`

Purpose: normalizes symbols, removes duplicates while preserving order, and constructs compact JSON-string subscription payloads without network behavior.

Main functions: `normalize_symbols`, `build_symbol_subscription`.

Status: unit-tested with exact FPT and FPT + ACB payloads, including case/whitespace normalization and duplicate removal.

### `data/vietcap/decoder.py`

Purpose: converts bytes-like payloads into `MatchPriceMessage` objects and logs malformed protobuf data.

Main function/class: `decode_match_price`, `VietcapDecodeError`.

Status: match-price, index, and bid-ask decoders reject non-binary and malformed
payloads with explicit errors. Pipeline recovery after each decode failure is
unit-tested; no decoder has yet processed a live Vietcap market frame.

### `tests/test_decode_reliability.py`

Purpose: verifies a malformed protobuf frame is logged and isolated for each of
the three realtime pipelines, and that the next valid frame is still normalized
and stored.

Status: three recovery tests pass as part of the 140-test suite.

### `data/vietcap/rest.py`

Purpose: performs bounded, unauthenticated Vietcap REST acquisition without
leaking provider response fields into normalized models.

Main classes/functions: `VietcapRestClient`, `VietcapRestError`,
`VietcapTimeFrame`, `normalize_stock_symbol`, `normalize_time_frame`, `get_quote`,
`get_gap_chart`.

Status: quote GET behavior, symbol safety, timeout, response-shape enforcement,
gap-chart POST body construction, and error wrapping are unit-tested. Both live
REST probes returned HTTP 400 during 2026-09-19, so successful live quote and
direct Python historical retrieval remain NOT TESTED. A later authenticated
browser request returned a gap-chart array with HTTP 200. Only `ONE_MINUTE`,
`ONE_HOUR`, and `ONE_DAY` are accepted before network I/O.

### `tests/test_rest.py`

Purpose: deterministic tests for Vietcap REST request construction and failure
handling without network access.

Status: 40 tests pass as part of the 180-test suite.

### `data/vietcap/validation.py`

Purpose: validates required price, volume, range, and ceiling/reference/floor relationships after decoding.

Main function: `validate_match_price`.

Status: created and unit-tested; live FPT fields are not yet verified.

### `data/models.py`

Purpose: defines provider-independent normalized market-data models.

Main classes include immutable, slotted `TradeTick`, `IndexSnapshot`,
`OrderBook`, and `OHLCVBar`.

Status: unit-tested for exact values and immutability. `OHLCVBar.timestamp` is
an integer normalized from the observed Unix-seconds decimal string.

### `data/vietcap/normalizer.py`

Purpose: validates `MatchPriceMessage` and converts it to `TradeTick` without
leaking protobuf types downstream.

Main function: `normalize_match_price`.

Status: unit-tested for complete field mapping, proto3 defaults, symbol
normalization, and invalid-message rejection; live frames remain NOT TESTED.

### `data/market_state.py`

Purpose: stores the latest normalized trade tick for each symbol without provider
dependencies.

Main class: `LatestMarketState`.

Status: unit-tested for FPT + ACB storage, replacement by arrival order,
normalized lookups, runtime type/symbol checks, and read-only point-in-time
snapshots. Live integration remains NOT TESTED.

### `data/vietcap/pipeline.py`

Purpose: routes one Vietcap match-price payload through decoding, validation,
normalization, expected-symbol filtering, and latest-state update.

Main class: `MatchPriceStatePipeline`.

Status: deterministically unit-tested for FPT + ACB, replacement, malformed
payloads, invalid trades, and unexpected symbols; live invocation remains NOT TESTED.

### `scripts/test_realtime.py`

Purpose: subscribes only FPT to `w-match-price`, records first-event metadata, decodes and validates messages, prints normalized field labels, and requires two distinct valid ticks for success.

Status: PASS live at 09:42 ICT on 2026-09-21. Two distinct 244-byte FPT frames
were decoded and validated; the observed prices changed from 66,300 to 66,400.

### `scripts/test_realtime_market_state.py`

Purpose: bounded Phase 4 acceptance harness for FPT + ACB through the full
decode-to-cache path. Requires two distinct valid ticks per symbol by default.

Status: PASS live at 09:44 ICT on 2026-09-21. The harness observed two distinct
normalized ticks for both FPT and ACB and cached both symbols concurrently.

### `tests/test_decoder.py`

Purpose: tests MatchPrice decoding from `bytes`, `bytearray`, and `memoryview`, plus invalid type/wire payload handling.

Status: five tests pass.

### `tests/test_subscriptions.py`

Purpose: verifies exact FPT and FPT + ACB JSON-string payloads, ordered deduplication, and rejection of empty symbol lists.

Status: five tests pass.

### `tests/test_validation.py`

Purpose: verifies valid and invalid MatchPrice field relationships.

Status: two tests pass.

### `tests/test_normalizer.py`

Purpose: verifies provider-independent MatchPrice normalization, optional-field
handling, immutability, and rejection of invalid messages.

Status: four tests pass.

### `tests/test_market_state.py`

Purpose: verifies per-symbol latest values, replacement behavior, immutable
snapshots, normalized lookup, and rejection of invalid cache inputs.

Status: nine tests pass.

### `tests/test_pipeline.py`

Purpose: verifies the decode-to-cache pipeline and ensures acceptance requires
distinct updates for both FPT and ACB.

Status: seven tests pass.

### `docs/VIETCAP_PROTOCOL.md`

Purpose: protocol notes and confirmed runtime evidence.

Status: updated with Engine.IO v4 evidence, Phase 4 pipeline/harness behavior,
and both failed HTTP 503 live attempts.

### `docs/ARCHITECTURE.md`

Purpose: records the provider boundary and downstream layering.

Status: updated to document the immutable tick, thread-safe latest-state, and
Vietcap decode-to-cache pipeline boundaries.

### `TASKS.md`

Purpose: phase gate and acceptance checklist.

Status: Phase 4 is the active offline implementation phase. Its subscription,
deduplication, `TradeTick`, and cache items are checked; live items remain pending.

### `PROJECT_CONTEXT.md`

Purpose: persistent development record.

Status: updated with the Phase 4 acceptance harness, deterministic tests, and
HTTP 503 live evidence while retaining unresolved live-validation blockers.

## 7. Important Technical Discoveries

### Schema retrieval

- URL: `https://trading.vietcap.com.vn/protos/price.proto`
- Retrieval date: 2026-09-19
- Authentication supplied: none
- HTTP status: `200`
- Content type: `application/octet-stream`
- Content length: `6319` bytes
- Upstream SHA-256: `e548eca5699fec2af3e49dca32366d9db231b06db3d99521a70aaba27aca3b4c`
- Normalized local SHA-256: `b3205c76d35724da6e716e5c6c89c5bc53a03fdf6ac69f733c5edcecd36dbc0c`

### Upstream compatibility quirk

The live upstream file starts with:

```proto
package pricePackage;
syntax = "proto3";
```

The frontend's `protobuf.js` loader accepts this. Standard `protoc` rejects it because the syntax declaration must precede package declarations. The vendored file swaps only these two lines. An in-memory comparison of normalized upstream content against the local file returned `True`; message and field definitions are otherwise unchanged.

### Verified required protobuf mapping

- `pricePackage.MatchPriceMessage`
- `pricePackage.BidAskMessage`
- `pricePackage.IndexMessage`
- `pricePackage.BidAskPrice`, referenced by the repeated bid/ask fields

### Toolchain

- Python: 3.12.10, 64-bit
- `protobuf`: 7.36.2
- `grpcio-tools`: 1.82.2
- generated-code protobuf version marker: 7.35.0
- `pytest`: 9.1.1

The dependencies are isolated in `.venv`, which is excluded by `.gitignore`.

### Verified Socket.IO runtime

Live connection command:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_connection.py --hold-seconds 35 --connect-timeout 20 --engineio-logs
```

Observed on 2026-09-19:

- `python-socketio==5.17.0` initiated `wss://trading.vietcap.com.vn/ws/price/socket.io/?transport=websocket&EIO=4`.
- The server accepted the WebSocket without supplied credentials.
- Engine.IO handshake fields: `upgrades=[]`, `pingInterval=25000`, `pingTimeout=20000`, and `maxPayload=1000000`.
- The default Socket.IO namespace connected successfully.
- The client remained connected for 35 seconds.
- A server PING and client PONG were observed at approximately 25 seconds.
- The client sent a clean Socket.IO namespace disconnect and Engine.IO close.
- Protocol logs showed no application event packets or market subscription emits.

The Engine.IO session ID and Socket.IO namespace ID are different values, as expected. Session IDs are runtime diagnostics and are not persisted as credentials.

### Phase 3 FPT subscription evidence

Live command on Saturday 2026-09-19:

```powershell
.\.venv\Scripts\python.exe scripts\test_realtime.py --hold-seconds 40 --min-updates 2 --engineio-logs
```

Confirmed outgoing Socket.IO packet:

```text
2["w-match-price","{\"symbols\":[\"FPT\"]}"]
```

This confirms the client emitted event `w-match-price` with a JSON string containing only `FPT`. The connection remained healthy through one Engine.IO PING/PONG cycle. No `w-match-price` event arrived during 40 seconds, so incoming payload type, payload size, protobuf mapping, and live field values remain unconfirmed. The script correctly returned an incomplete result instead of treating connection/subscription success as market-data success.

### Current frontend contract verification

The public price-board bundle referenced by the 2026-09-19 import map was fetched from:

`https://trading.vietcap.com.vn/trading/main.js?v=49266848e71be948c3ac9a4a547e9ef01717248b`

Observed:

- HTTP 200 and 1,524,144 response bytes
- `CI_COMMIT_SHA=49266848e71be948c3ac9a4a547e9ef01717248b`
- `APP_VERSION=1789116678129`
- current `MATCH_PRICE` constant equals `w-match-price`
- `subscribeMatchPrice` emits `JSON.stringify({symbols: t})`
- current event mapping is `w-match-price` -> `matchPriceMessageProto`
- current proto lookup is `pricePackage.MatchPriceMessage`
- current decoder calls `decode(new Uint8Array(payload))`
- current socket path is `/ws/price/socket.io`
- current frontend transport list is `["websocket"]`

Therefore the implemented Phase 3 event name, JSON-string payload, transport, path, and target protobuf type match the current public frontend bundle. This evidence narrows the Saturday no-event result to runtime delivery/market inactivity rather than a known client contract mismatch.

### Previously observed realtime protocol information

- Socket.IO endpoint: `wss://trading.vietcap.com.vn/ws/price/socket.io/?EIO=4&transport=websocket`.
- The observed transport is Engine.IO v4 over WebSocket.
- Observed initial event names include `w-match-price`, `w-bid-ask`, and `index`.
- Observed subscription payload shape is a JSON string containing `{"symbols":[...]}`.

The endpoint, Engine.IO version, path, direct WebSocket transport, heartbeat behavior, and client-side `w-match-price` emit format are reproduced by Python. Server event delivery and protobuf mapping against a real market frame remain unverified.

## 8. Confirmed Facts vs Assumptions

### Confirmed

- Python 3.12.10 executes locally.
- The live proto URL responded without supplied credentials on 2026-09-19.
- The fetched schema has package `pricePackage` and contains all three required message types.
- Standard `protoc` rejects the upstream declaration order and accepts the two-line reordered local schema.
- The local schema matches normalized upstream content exactly.
- Generated Python classes import, instantiate, serialize, and decode successfully.
- Four protobuf tests pass and the project-local dependency set has no broken requirements.
- `python-socketio` 5.17.0 connects to the Vietcap endpoint using Engine.IO v4 over direct WebSocket.
- The server advertises a 25-second ping interval and 20-second ping timeout.
- A 35-second connection survived one observed PING/PONG cycle and disconnected cleanly.
- No account credentials, cookies, auth payload, or market subscription events were supplied during the Phase 2 smoke test.
- The Python client emits `w-match-price` with the JSON string `{"symbols":["FPT"]}` and no other symbol.
- The Phase 3 acceptance script requires at least two distinct valid ticks and will not pass on connection or subscription evidence alone.
- The current public frontend bundle uses the same `w-match-price` event, JSON-string symbol payload, WebSocket transport, socket path, and `MatchPriceMessage` decoder mapping as the Python implementation.
- Vietcap interfaces are unofficial/internal frontend details and remain isolated.

### Assumptions

- The server will deliver `w-match-price` events to this unauthenticated Python connection during an active session.
- Incoming Python payloads will be bytes-like in the same way the browser payload is accepted by `new Uint8Array(payload)`.
- Realtime market data remains accessible without an authenticated session.
- The observed event-to-message mappings match actual incoming binary frames.

## 9. Tests Performed

### 2026-09-19 12:35 +07:00 — Existing toolchain inspection

Command: `protoc --version` lookup and `py -3.12 -m pip show protobuf grpcio-tools pytest`.

Expected: determine whether a compiler and test/runtime dependencies already exist.

Actual: standalone `protoc` and `grpcio-tools` were absent; user-level `protobuf==5.29.5` and `pytest==8.4.2` existed.

Result: PASS.

### 2026-09-19 12:36 +07:00 — Schema retrieval

Command: unauthenticated `Invoke-WebRequest` to the recorded Vietcap proto URL.

Expected: HTTP 200 with a parseable protobuf schema containing the required package/messages.

Actual: HTTP 200, `application/octet-stream`, 6,319 bytes; package and messages present.

Result: PASS.

### 2026-09-19 12:39 +07:00 — Initial standard compiler run

Command: `.\.venv\Scripts\python.exe -m grpc_tools.protoc -I. --python_out=. data/vietcap/proto/price.proto` using the upstream declaration order.

Expected: generate Python protobuf bindings.

Actual: compiler rejected line 2 because the upstream file placed `package` before `syntax`; subsequent fields were interpreted as proto2 and produced cascading errors.

Result: FAIL (confirmed upstream compatibility quirk).

### 2026-09-19 12:39 +07:00 — Compiler rerun after declaration reorder

Command: `.\.venv\Scripts\python.exe -m grpc_tools.protoc -I. --python_out=. data/vietcap/proto/price.proto`.

Expected: generate `price_pb2.py` without compiler errors.

Actual: generated `data/vietcap/proto/price_pb2.py` successfully.

Result: PASS.

### 2026-09-19 12:39 +07:00 — Protobuf unit tests

Command: `.\.venv\Scripts\python.exe -m pytest -q`.

Expected: verify the package/full names and required message round trips.

Actual: initial run `4 passed in 0.29s`; final post-documentation rerun `4 passed in 0.11s`.

Result: PASS.

### 2026-09-19 12:40 +07:00 — Upstream/local schema equivalence

Command: fetch upstream bytes, normalize only the first two declarations in memory, compare to local content, and compute SHA-256 hashes.

Expected: local schema differs only by the documented declaration reorder.

Actual: upstream and local lengths are both 6,319 bytes; `NORMALIZED_CONTENT_MATCH=True`.

Result: PASS.

### 2026-09-19 12:40 +07:00 — Dependency consistency

Command: `.\.venv\Scripts\python.exe -m pip check`.

Expected: no incompatible or missing installed requirements.

Actual: `No broken requirements found.`

Result: PASS.

### 2026-09-19 12:41 +07:00 — Phase gate audit

Command: assert Phase 1 is active and fully checked, verify all later phases remain unchecked, and verify required Phase 1 artifacts exist.

Expected: Phase 1 acceptance evidence is complete without advancing into Phase 2.

Actual: `Phase 1 gate audit: PASS`.

Result: PASS.

### 2026-09-19 12:50 +07:00 — Phase 2 dependency installation

Command: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

Expected: install the pinned synchronous Socket.IO/WebSocket client stack without breaking Phase 1 dependencies.

Actual: installed `python-socketio==5.17.0`, `python-engineio==4.14.0`, `websocket-client==1.9.2`, and required transitive packages successfully.

Result: PASS.

### 2026-09-19 12:53 +07:00 — Client unit tests

Command: `.\.venv\Scripts\python.exe -m pytest -q`.

Expected: preserve protobuf tests and verify connection configuration/lifecycle without network access.

Actual: initial run `10 passed in 0.36s`; final rerun `10 passed in 0.35s`.

Result: PASS.

### 2026-09-19 12:54 +07:00 — Smoke-script entry point

Command: `.\.venv\Scripts\python.exe scripts\inspect_connection.py --help`.

Expected: direct script execution resolves project imports and exposes bounded connection-only options.

Actual: help displayed successfully with hold time, connection timeout, and Engine.IO logging options.

Result: PASS.

### 2026-09-19 12:55 +07:00 — Live Socket.IO connection smoke test

Command: `.\.venv\Scripts\python.exe scripts\inspect_connection.py --hold-seconds 35 --connect-timeout 20 --engineio-logs`.

Expected: connect directly via WebSocket/Engine.IO v4, connect the default Socket.IO namespace, survive at least one heartbeat, send no market subscription, and disconnect cleanly.

Actual: WebSocket accepted; default namespace connected; server PING/client PONG observed; `[STABLE] connected for 35.0s`; clean close completed. No application event/subscription packet appeared in protocol logs.

Result: PASS.

### 2026-09-19 12:58 +07:00 — Final Phase 2 dependency and gate audit

Commands: `.\.venv\Scripts\python.exe -m pip check` and read-only Phase 2 checklist/artifact/application-emit assertions.

Expected: consistent dependencies, complete Phase 2 evidence, no later-phase checkbox changes, all expected artifacts present, and zero application `.emit(...)` calls.

Actual: `No broken requirements found.`; `Phase 2 gate audit: PASS`; `Application Socket.IO emit calls: 0`.

Result: PASS.

### 2026-09-19 13:03 +07:00 — Phase 3 unit tests

Command: `.\.venv\Scripts\python.exe -m pytest -q`.

Expected: preserve existing behavior and verify exact FPT subscription payload, event registration, binary decoding, decode errors, and price/volume validation.

Actual: initial run `23 passed in 0.35s`; subsequent reruns passed in `0.36s` and `0.28s`.

Result: PASS.

### 2026-09-19 13:04 +07:00 — Live FPT-only subscription attempt

Command: `.\.venv\Scripts\python.exe scripts\test_realtime.py --hold-seconds 40 --min-updates 2 --engineio-logs`.

Expected: emit only FPT to `w-match-price`, receive binary events, decode and validate at least two distinct FPT ticks, and print normalized tick labels.

Actual: connection and heartbeat remained healthy; exact FPT-only emit was observed; zero match-price events arrived; script reported `[INCOMPLETE] received 0 distinct valid FPT tick(s); required 2` and exited with its incomplete status.

Result: FAIL for Phase 3 acceptance. Subscription emission passed, but receive/decode/live validation are NOT TESTED because no event arrived.

### 2026-09-19 13:07 +07:00 — Phase 3 partial gate audit

Command: assert Phase 3 is active, only the evidence-backed FPT subscription item is checked, later phases remain untouched, and production/live-test code contains no ACB, VNINDEX, bid/ask, or index scope.

Expected: preserve the incomplete Phase 3 gate without overstating live success.

Actual: `Phase 3 partial gate audit: PASS`; only the FPT subscription item is checked; later-phase checked items: zero.

Result: PASS.

### 2026-09-19 13:22 +07:00 — Current frontend contract verification

Command: fetch the current public price-board bundle and assert the expected event name, subscription implementation, message-key mapping, binary decoder call, socket path, and WebSocket transport strings.

Expected: determine whether the zero-event Saturday result was caused by stale Phase 3 protocol assumptions.

Actual: HTTP 200; all six contract assertions passed against bundle commit `49266848e71be948c3ac9a4a547e9ef01717248b`.

Result: PASS. No current frontend contract mismatch was found; live Python event delivery remains NOT TESTED.

### 2026-09-19 13:23 +07:00 — Phase 3 continuation audit

Command: verify only the evidence-backed subscription item is checked, Phase 4+ remains untouched, and frontend contract findings are recorded without claiming live delivery.

Expected: Phase 3 stays open and accurately documented.

Actual: `Phase 3 continuation audit: PASS`; later-phase checked items: zero.

Result: PASS.

### 2026-09-19 — Phase 4 FPT + ACB subscription unit tests

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Expected: preserve all earlier behavior; produce the exact combined FPT + ACB
payload; remove repeated symbols; suppress an unchanged symbol set; and permit
the same subscription again after disconnect.

Actual: `26 passed in 0.24s`; `No broken requirements found.` The project
`.venv` required execution outside the restricted sandbox because its Python
Store base interpreter path is not accessible inside that sandbox.

Result: PASS for the offline Phase 4 subscription task group. Simultaneous live
FPT + ACB event delivery remains NOT TESTED because the market is closed.

### 2026-09-19 — Phase 4 TradeTick normalization unit tests

Command: `.\.venv\Scripts\python.exe -m pytest -q`.

Expected: preserve existing behavior and verify exact MatchPrice-to-TradeTick
mapping, immutable normalized ticks, optional proto3 default handling, and
rejection of invalid trade messages.

Actual: `30 passed in 0.33s`.

Result: PASS for the offline `TradeTick` task. Conversion from an actual live
binary message remains NOT TESTED because no live frame has arrived.

### 2026-09-19 — Phase 4 latest market-state cache unit tests

Command: `.\.venv\Scripts\python.exe -m pytest -q`.

Expected: preserve existing behavior and verify independent FPT + ACB state,
replacement by arrival order, normalized lookups, input enforcement, and
read-only point-in-time snapshots.

Actual: `39 passed in 0.32s`.

Result: PASS for the offline latest-state cache task. Population from real
Socket.IO events remains NOT TESTED because the market is closed.

### 2026-09-19 — Phase 4 FPT + ACB acceptance harness

Offline commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\test_realtime_market_state.py --help
```

Expected: verify the full decode-to-cache handler, reject bad/unexpected events,
and require two distinct normalized ticks for both FPT and ACB.

Actual: `46 passed in 2.65s`; the script entry point displayed its bounded live
test options successfully.

Result: PASS for the offline pipeline and acceptance logic.

Live commands attempted:

```powershell
.\.venv\Scripts\python.exe scripts\test_realtime_market_state.py --hold-seconds 40 --min-updates-per-symbol 2 --engineio-logs
.\.venv\Scripts\python.exe scripts\test_realtime_market_state.py --hold-seconds 15 --min-updates-per-symbol 2
```

Expected: connect, subscribe with `{"symbols":["FPT","ACB"]}`, then observe at
least two distinct valid normalized ticks for each symbol.

Actual: both attempts received HTTP 503 during the WebSocket handshake. Vietcap's
response reported an upstream connection refusal. Neither attempt reached the
subscription or event-receive stage.

Result: FAIL for live connectivity; FPT + ACB simultaneous delivery remains NOT TESTED.

### 2026-09-19 — Phase 7 reconnect handling unit tests

Commands:

```powershell
.\.venv\Scripts\python.exe -c "import inspect, socketio; print(inspect.signature(socketio.Client))"
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: confirm the pinned client supports reconnect configuration, enable it
for the default production client, and preserve all Phase 1–6 behavior.

Actual: the installed `python-socketio==5.17.0` exposes `reconnection=True` and
related retry parameters; the full suite returned `126 passed in 1.80s`.

Result: PASS for offline reconnect handling. Forced interruption and stream
recovery remain NOT TESTED.

### 2026-09-19 — Phase 7 retry/backoff configuration

Commands:

```powershell
.\.venv\Scripts\python.exe -c "import inspect, socketio; print(inspect.getsource(socketio.Client._handle_reconnect))"
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: verify the pinned library's retry algorithm, pass explicit bounded-delay
parameters to the production client, and preserve all existing behavior.

Actual: source inspection confirmed delay doubling, maximum-delay capping, jitter,
and zero meaning unlimited attempts. Constructor coverage verified attempts `0`,
initial delay `1.0`, maximum delay `30.0`, and randomization factor `0.5`. The full
suite returned `126 passed in 0.45s`.

Result: PASS for offline retry/backoff configuration. Actual reconnect timing
under a forced network interruption remains NOT TESTED.

### 2026-09-19 — Phase 7 automatic resubscription

Command: `.\.venv\Scripts\python.exe -m pytest -q`.

Expected: preserve desired symbols across disconnect, clear only active connection
markers, and restore match-price, index, and bid-ask subscriptions after reconnect.
Failure in one restoration must not prevent attempts for the other streams.

Actual: deterministic disconnect/connect simulation restored all three exact
payloads. A simulated match-price emit failure was logged while index and bid-ask
restoration continued. The full suite returned `128 passed in 0.42s`.

Result: PASS for offline automatic resubscription. Recovery after an actual
transport interruption remains NOT TESTED.

### 2026-09-19 — Phase 7 listener deduplication

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_client.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Expected: lifecycle and market-data listeners are each registered once, repeated
disconnect/connect cycles do not call `.on(...)` again, and one simulated payload
per stream produces exactly one handler invocation per cycle.

Actual: after three simulated reconnect cycles, the three lifecycle listeners and
three market-data listeners each had one registration. Each stream handler ran
exactly three times for three simulated payloads. Client tests returned
`22 passed in 0.28s`; the full suite returned `129 passed in 0.49s`; dependency
validation reported `No broken requirements found.`

Result: PASS for offline listener deduplication. Actual forced-interruption stream
recovery remains NOT TESTED.

### 2026-09-19 — Phase 7 decode error handling

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_decode_reliability.py tests\test_decoder.py tests\test_index_stream.py tests\test_bid_ask_stream.py tests\test_pipeline.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Expected: malformed match-price, index, and bid-ask protobuf frames are logged,
return no normalized object, do not mutate state, and do not prevent the next
valid frame from being processed.

Actual: all three pipelines rejected a malformed frame and then normalized and
stored the next valid frame. The focused decode/pipeline group returned
`81 passed in 0.39s`; the full suite returned `132 passed in 0.43s`; dependency
validation reported `No broken requirements found.`

Result: PASS for offline decode error isolation and recovery. Behavior against
actual malformed provider frames remains NOT TESTED.

### 2026-09-19 — Phase 7 bounded raw debug mode

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_client.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
# Each realtime acceptance script was also run with --help and audited for:
# --raw-debug and --raw-debug-event-limit
```

Expected: raw debug is disabled by default; when enabled it logs bounded metadata
for all three market events without logging binary content, continues delivering
every payload to the registered handler, and exposes validated CLI controls in all
four realtime acceptance scripts.

Actual: client tests returned `30 passed in 0.25s`. Metadata logging stopped after
the configured per-event limit while the handler still received all payloads.
All three streams reported event/type/size metadata without payload content. All
four script help audits passed. The final full suite returned `140 passed in 0.42s`;
dependency validation reported `No broken requirements found.`

Result: PASS for offline bounded raw debug mode. Live raw-event metadata remains
NOT TESTED because no market event was received during this task.

### 2026-09-19 — Phase 8 quote endpoint

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_rest.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Expected: normalize and validate one ticker, issue the documented quote GET with
an explicit timeout and JSON Accept header, accept only a JSON object, and convert
network, HTTP, and invalid-JSON failures to a provider-specific exception.

Actual: final focused tests returned `16 passed in 0.12s`; the final full suite
returned `156 passed in 0.41s`; dependency validation reported no broken requirements.
A direct unauthenticated FPT probe returned HTTP 400 with an empty HTML body.

Result: PASS for offline quote acquisition. Successful live response and its
field contract remain NOT TESTED; no response fields were guessed.

### 2026-09-19 — Phase 8 OHLC gap-chart request contract

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_rest.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Expected: send the documented POST path and exact `timeFrame`, `symbols`,
`countBack`, and `to` JSON keys; normalize and deduplicate ticker inputs; require
positive integer bounds; enforce timeout and JSON-object response; and wrap
network, HTTP, and JSON failures.

Actual: REST tests returned `32 passed in 0.14s`; the full suite returned
`172 passed in 0.49s`; dependency validation reported no broken requirements.
A direct `ACB`/`ONE_DAY`/two-bar unauthenticated probe returned HTTP 400 with an
empty HTML body.

Result: PASS for the offline gap-chart acquisition contract. Successful live
historical retrieval, live timeframe behavior, and response columns remain NOT
TESTED.

### 2026-09-19 — Phase 8 supported timeframes

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_rest.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Expected: represent the three observed timeframe identifiers as a closed enum,
accept either enum members or normalized strings, emit the exact provider value,
and reject every unsupported value before performing network I/O.

Actual: REST tests returned `40 passed in 0.17s`; all three exact timeframe
values were emitted in deterministic POST tests; the full suite returned
`180 passed in 0.52s`; dependency validation reported no broken requirements.

Result: PASS for offline request semantics of `ONE_MINUTE`, `ONE_HOUR`, and
`ONE_DAY`. Live retrieval for all three timeframes remains NOT TESTED because the
endpoint probe returned HTTP 400.

## 10. Known Problems

- The upstream schema is not directly compilable by standard `protoc` without reordering its first two declarations.
- The directory is not a Git repository, so changes cannot currently be reviewed through Git status/diff/history.
- The generated binding validates against protobuf generated-code version 7.35.0, while the installed runtime is 7.36.2; runtime validation and all tests pass.
- No real binary market frame has been decoded; tests currently use valid locally constructed protobuf messages.
- Only one 35-second live connection has been observed; extended uptime and forced interruption are deferred to Phase 7 reliability work.
- Automatic transport reconnect, backoff, and resubscription pass offline tests,
  but have not been observed after a real transport interruption.
- No FPT event arrived during the Saturday Phase 3 test, so the exact server event delivery and live protobuf mapping remain unverified.
- Phase 3 cannot be marked complete until at least two distinct valid FPT ticks are observed during an active session.
- The current frontend contract matches the implementation, but static bundle evidence cannot prove that this Python connection will receive data during the next active session.
- FPT + ACB subscription behavior is covered offline, but simultaneous live delivery remains unverified.
- The two Phase 4 live attempts at approximately 14:24 +07:00 received HTTP 503
  before Socket.IO connected; this is newer runtime evidence than the earlier
  successful Phase 2 connection and may be transient endpoint unavailability.
- The documented FPT quote URL returned HTTP 400 with an empty HTML body on
  2026-09-19. Successful unauthenticated quote retrieval remains NOT TESTED.
- The documented gap-chart POST also returned HTTP 400 with an empty HTML body
  for an ACB `ONE_DAY` two-bar request on 2026-09-19. Historical retrieval and
  response-column semantics remain NOT TESTED.

## 11. Next Steps

Core implementation phases are complete. Optional Phase 19 News must not start
without explicit user authorization. Pending Phase 3–7 live checks should still
be rerun during an active Vietnamese market session.

## 12. How To Run

Create/install the isolated environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Regenerate the binding:

```powershell
.\.venv\Scripts\python.exe -m grpc_tools.protoc -I. --python_out=. data/vietcap/proto/price.proto
```

Run all current tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run the connection-only smoke test:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_connection.py --hold-seconds 35 --engineio-logs
```

This script connects and observes the heartbeat only. It does not subscribe to or decode market data.

Run the Phase 3 FPT-only acceptance test during market hours:

```powershell
.\.venv\Scripts\python.exe scripts\test_realtime.py --hold-seconds 60 --min-updates 2
```

Exit status `0` means at least two distinct valid FPT ticks were decoded. Exit status `2` means the test completed without enough valid changing ticks and Phase 3 remains incomplete.

Run the Phase 4 FPT + ACB normalized-state acceptance test during market hours:

```powershell
.\.venv\Scripts\python.exe scripts\test_realtime_market_state.py --hold-seconds 60 --min-updates-per-symbol 2
```

Exit status `0` requires both symbols to have at least two distinct normalized
ticks in the latest-state pipeline. Exit status `2` means the connection ran but
insufficient updates arrived; exit status `1` means connection or runtime failure.

## 13. Architecture Decisions

### Decision: isolate provider code under `data/vietcap/`

Reason: the Vietcap endpoint and schema are frontend/internal details that may change independently of downstream market logic.

### Decision: vendor the complete observed schema

Reason: using the actual frontend schema avoids guessing fields and preserves compatibility with future message types, while current tests and implementation remain scoped to three required messages.

### Decision: normalize only declaration order

Reason: standard `protoc` requires `syntax` before `package`. The one reorder is mechanically verified against upstream content and changes no package, message, field name, field number, or wire type.

### Decision: commit generated Python bindings

Reason: runtime code can import the schema without requiring a compiler in production. The compiler remains pinned for deterministic regeneration and tests protect required contracts.

### Decision: use an isolated project environment

Reason: Phase 1 requires protobuf 7.x through the selected `grpcio-tools` release, while the user-level environment contains protobuf 5.x. `.venv` prevents unrelated package disruption.

### Decision: use the synchronous `python-socketio` client for protocol validation

Reason: Phase 2 needs one bounded connection and no concurrent market processing. The synchronous client minimizes moving parts while retaining the mature Engine.IO implementation required by project rules.

### Decision: force direct WebSocket transport

Reason: the observed frontend endpoint explicitly uses `transport=websocket`. Forcing that transport verifies the known path and avoids conflating a polling fallback with WebSocket success.

### Decision: disable reconnection in Phase 2

Reason: reconnect and resubscription behavior belongs to Phase 7. This keeps the current acceptance test limited to initial connection stability and makes unexpected disconnects visible.

### Decision: expose no subscription API in the Phase 2 client

Reason: Phase 2 is connection-only. Market events and payload handling must be added incrementally with Phase 3 evidence.

### Decision: Phase 3 subscription is scoped to FPT and `w-match-price`

Reason: one symbol and one event minimize ambiguity while the exact runtime payload and protobuf mapping are being verified. ACB and indices remain explicitly out of scope.

### Decision: keep acquisition, subscription construction, decoding, and validation separate

Reason: Socket.IO lifecycle stays in `client.py`, JSON payload construction in `subscriptions.py`, protobuf parsing in `decoder.py`, and data-quality rules in `validation.py`. This prevents transport details from leaking into future normalized market state.

### Decision: require two distinct valid ticks for Phase 3 acceptance

Reason: a single cached/static snapshot would not prove the required changing realtime stream. The acceptance script uses exchange time, price, match volume, accumulated volume, and accumulated value as the tick identity.

### Decision: retain provider-independent downstream boundaries

Reason: normalization and market-state code must eventually consume generic models, not Vietcap protobuf field names. Live signals and backtests must eventually share strategy logic without coupling to acquisition.

### Decision: deduplicate subscriptions without assuming server replacement semantics

Reason: repeated symbols are removed from each outgoing payload and an identical
normalized symbol set is not emitted twice on the same connection. A changed set
is still emitted in full because the unofficial server's append-versus-replace
behavior has not been established. Disconnect clears the local suppression state.

### Decision: keep TradeTick immutable and provider-independent

Reason: downstream market state, indicators, and strategy must not depend on
Vietcap protobuf classes. Immutability prevents an already-cached observation
from being mutated in place. The provider time stays as an optional string until
live evidence establishes its exact format and timezone; no price-unit conversion
is guessed.

### Decision: define latest by arrival order until live time semantics are known

Reason: `LatestMarketState` replaces the cached value for a symbol whenever a new
normalized tick arrives. It does not compare `exchange_time`, because the live
format, timezone, and ordering guarantees have not yet been observed. The cache
uses a lock for callback/read concurrency and returns detached read-only snapshots.

### Decision: require changing updates from both symbols for Phase 4 acceptance

Reason: one cached snapshot per symbol would not demonstrate an updating realtime
market state. The acceptance harness requires at least two distinct identities for
both FPT and ACB, based on normalized time, price, last volume, accumulated volume,
and accumulated value. Invalid and unexpected events never enter the cache.

### Decision: use python-socketio reconnect handling

Reason: the mature Socket.IO client already implements reconnection after an
established transport is interrupted. Phase 7 enables that mechanism instead of
adding a handwritten loop. Explicit parameters use unlimited attempts with a
one-second initial delay, exponential doubling, a 30-second cap, and jitter to
avoid synchronized retry bursts.

### Decision: separate desired subscriptions from active connection state

Reason: active subscription markers are scoped to one connection and are cleared
on disconnect, while the desired normalized symbol tuples persist. After reconnect,
each stream is restored independently so one failed subscription does not prevent
the remaining streams from being restored. This keeps desired configuration
separate from connection-scoped state.

### Decision: register listeners outside reconnect handling

Reason: lifecycle listeners are installed once when the client is constructed,
and market-data listeners are installed only through the explicit `on_*` methods.
Reconnect handling restores subscriptions but never registers listeners, preventing
callback multiplication across repeated reconnect cycles.

### Decision: isolate expected payload failures at the pipeline boundary

Reason: decoders raise explicit type or protobuf decode errors, while each
realtime pipeline logs and converts expected decode/validation failures to `None`.
Malformed frames therefore do not mutate market state or terminate the event
callback, and later valid frames can still be processed.

### Decision: raw debug logs metadata, never payload content

Reason: raw protobuf bytes may be large or unexpectedly sensitive. Debugging only
requires the event name, runtime type, and byte length at this stage. The mode is
off by default, caps records independently per event, uses a lock for counters,
and does not stop handler delivery after the logging limit is reached.

### Decision: keep REST acquisition provider-native before normalization

Reason: the live quote endpoint did not return a successful body during this
task, so response field semantics cannot be confirmed. The REST client validates
transport and top-level JSON shape but returns a detached provider-native mapping;
normalized quote or OHLC models must be added only with evidence-backed fields.

### Decision: validate gap-chart transport fields before timeframe semantics

Reason: the request boundary can safely enforce ticker collections, positive
integer `countBack`/`to`, and top-level JSON shape without claiming that any
specific timeframe works live. Explicit supported-timeframe semantics remain a
separate task because the current endpoint probe returned HTTP 400.

### Decision: represent supported timeframes as a closed string enum

Reason: an enum preserves the exact provider wire values while preventing typos
and undocumented intervals from reaching the endpoint. String inputs remain
accepted at the public boundary for convenience but normalize to one of exactly
three observed values before request construction.

## 14. Change Log

### 2026-09-19 12:29 +07:00 — Phase 0

- Inspected repository files, runtime, configuration, and documentation.
- Added minimal import package markers for `data` and `data.vietcap`.
- Confirmed `data/vietcap/` as the provider isolation boundary.
- Passed bootstrap assertions and Python import smoke test.

### 2026-09-19 12:40 +07:00 — Phase 1

- Advanced the active phase after explicit user authorization.
- Retrieved the live Vietcap schema and recorded provenance/hashes.
- Identified and documented the upstream declaration-order incompatibility.
- Vendored the semantically equivalent, compiler-compatible schema.
- Added pinned Phase 1 dependencies in a project-local environment.
- Generated `price_pb2.py` using `grpcio-tools`.
- Added package, descriptor, instantiation, serialization, and decode tests.
- Passed 4 tests twice, upstream equivalence verification, dependency consistency check, and the Phase 1 gate audit.
- Marked Phase 1 complete and stopped before Phase 2.

### 2026-09-19 12:55 +07:00 — Phase 2

- Advanced the active phase after explicit user authorization.
- Added pinned `python-socketio` and `websocket-client` dependencies.
- Added centralized connection constants and a connection-only lifecycle client.
- Added connect, disconnect, error, session, and transport logging.
- Added deterministic unit tests and a human-readable live inspection script.
- Passed ten unit tests twice and direct script-entry validation.
- Established a live Engine.IO v4 WebSocket connection without credentials.
- Observed a successful heartbeat and stable 35-second connection.
- Verified no market subscription events were emitted.
- Updated protocol documentation with runtime evidence.
- Passed final dependency consistency and phase-gate audits.
- Marked Phase 2 complete and stopped before Phase 3.

### 2026-09-19 13:04 +07:00 — Phase 3 partial

- Advanced the active phase after explicit user authorization.
- Added the `w-match-price` constant and exact JSON-string subscription builder.
- Added binary MatchPrice decoding with explicit error logging.
- Added live field validation and the FPT-only acceptance script.
- Added subscription, decoder, validation, and client lifecycle tests.
- Passed 23 unit tests twice.
- Confirmed the live client emitted only `FPT` to `w-match-price`.
- Received zero market events during a 40-second Saturday observation.
- Left receive/decode/print/validation checklist items unchecked and Phase 3 incomplete.
- Passed the partial phase-gate audit without claiming live data success.
- Did not add ACB or VNINDEX.

### 2026-09-19 13:22 +07:00 — Phase 3 contract follow-up

- Inspected the current public Vietcap price-board bundle referenced by the live import map.
- Confirmed the active bundle's event name, JSON-string subscription, message mapping, protobuf lookup, binary decode path, socket path, and WebSocket transport all match the implementation.
- Updated protocol and project context documentation with bundle provenance and bounded findings.
- Passed the full 23-test regression suite and continuation phase-gate audit.
- Kept Phase 3 open because current frontend code is not a substitute for receiving changing live FPT frames.

### 2026-09-19 — Phase 4 subscription task group

- Began Phase 4 offline implementation under the user-authorized closed-market exception.
- Added normalization and ordered duplicate removal for stock symbols.
- Added exact combined `{"symbols":["FPT","ACB"]}` subscription coverage.
- Suppressed repeated emissions for an unchanged normalized symbol set.
- Reset duplicate-suppression state on disconnect so a later connection can subscribe again.
- Passed all 26 unit tests and the project-local dependency consistency check.
- Kept Phase 3 live checks and Phase 4 simultaneous live delivery unchecked.

### 2026-09-19 — Phase 4 TradeTick task group

- Added the immutable, slotted, provider-independent `TradeTick` model.
- Added validated conversion from Vietcap `MatchPriceMessage`.
- Normalized symbol casing and represented unset optional snapshot fields as `None`.
- Preserved raw provider numeric units and exchange-time text without guessing transformations.
- Added four normalization tests; the full suite passed with 30 tests.
- Left the market-state cache and all live-delivery checklist items unchecked.

### 2026-09-19 — Phase 4 latest market-state task group

- Added thread-safe `LatestMarketState`, keyed by normalized symbol.
- Restricted updates to normalized `TradeTick` instances.
- Added case-insensitive lookup and replacement-by-arrival behavior.
- Added detached, read-only point-in-time snapshots.
- Added nine cache tests; the full suite passed with 39 tests.
- Left simultaneous live FPT + ACB delivery and Phase 3 live checks unchecked.

### 2026-09-19 — Phase 4 acceptance-harness task group

- Added `MatchPriceStatePipeline` for decode, validation/normalization, filtering,
  and latest-state update.
- Added a bounded FPT + ACB script requiring two distinct ticks per symbol.
- Added deterministic tests for valid dual-symbol flow, replacement, malformed
  payloads, invalid trades, unexpected symbols, and distinct-update acceptance.
- Passed the full 46-test suite and verified the script entry point.
- Attempted live execution twice; both WebSocket handshakes returned HTTP 503
  before subscription, so the Phase 4 live checkbox remains unchecked.

### 2026-09-19 — Phase 5 index-stream offline task group

- Began Phase 5 offline implementation under the user-authorized closed-market
  exception; Phase 3 and Phase 4 live checks were left unchecked.
- Added the `index` event constant and a case-preserving index subscription
  builder, because Vietcap index identifiers are case-sensitive (`HNXIndex`).
- Added `decode_index` for binary `IndexMessage` payloads with the same error
  wrapping used by match-price decoding.
- Added the immutable, provider-independent `IndexSnapshot` model as a separate
  type from `TradeTick`, since index and stock semantics differ.
- Added `validate_index` with breadth-counter validation limited to
  schema-supported constraints; counter relationships were not asserted.
- Left `code`, `estimatedChange`, and `estimatedFsp` unmapped as undocumented.
- Added `LatestIndexState` and `IndexStatePipeline` mirroring the Phase 4
  pipeline without sharing stock storage or accepting `TradeTick`.
- Added `scripts/test_realtime_index.py`, a bounded VNINDEX acceptance harness
  requiring two distinct valid snapshots.
- Passed the full suite twice: 89 tests, up from 46.
- Did not attempt live VNINDEX validation; Phase 5 acceptance stays NOT TESTED.
- Did not implement Phase 6 bid/ask, reconnect, REST, database, indicators,
  signals, or Telegram.

### 2026-09-21 — Phase 5 index-stream live acceptance

- Ran `py -3.12 scripts\test_realtime_index.py --hold-seconds 45
  --min-updates-per-symbol 2 --raw-debug` during the active market session.
- Connected and emitted `event=index` with
  `payload={"symbols":["VNINDEX"]}`.
- Received and decoded two distinct 148-byte binary frames.
- Snapshot 1: `VNINDEX=1811.06`, change `-4.60` (`-0.25%`), total volume
  `83,738,115`, total value `2,193,652`, breadth `132/63/110`, ceiling `1`,
  floor `3`.
- Snapshot 2 retained the same index and breadth values while total volume rose
  to `83,978,523` and total value rose to `2,200,332`.
- Harness reported `[PASS] distinct_snapshots={'VNINDEX': 2}
  cached_indices=['VNINDEX']` and exited with code `0`.
- Phase 5 acceptance is PASS. Phase 6 remains the next pending live validation.

### 2026-09-19 — Phase 6 bid-ask offline task group

- Began Phase 6 offline implementation under explicit user authorization while
  Phase 3, Phase 4, and Phase 5 live checks stayed unchecked.
- Added the `w-bid-ask` event constant and a bid-ask subscription that reuses
  the stock symbol helper but tracks its own duplicate-suppression state.
- Added `decode_bid_ask` with the same error wrapping as the other decoders.
- Added immutable `OrderBookLevel` and `OrderBook` models using tuples so
  cached depth cannot be mutated.
- Added `validate_bid_ask` limited to schema-supported level constraints;
  ordering, non-crossing, and fixed depth were deliberately not asserted.
- Left `type`, `code`, `bidCount`, and `askCount` unmapped as undocumented.
- Added `LatestOrderBookState` and `BidAskStatePipeline` as separate types from
  the trade and index equivalents.
- Added `scripts/test_realtime_bidask.py` requiring two distinct valid books
  per symbol.
- Passed the full suite twice: 125 tests, up from 89.
- Did not attempt live bid-ask validation; Phase 6 acceptance stays NOT TESTED.
- Did not implement Phase 7 reconnect, REST, database, indicators, signals,
  or Telegram.

### 2026-09-21 — Phase 6 bid-ask live acceptance

- Ran `py -3.12 scripts\test_realtime_bidask.py --hold-seconds 45
  --min-updates-per-symbol 2 --raw-debug` during the active market session.
- Connected and emitted `event=w-bid-ask` with
  `payload={"symbols":["FPT","ACB"]}`.
- Received realtime binary order-book events; the first observed frame was
  169 bytes.
- Normalized four distinct FPT books and two distinct ACB books. Every printed
  book contained three bid levels and three ask levels.
- Representative best quotes were FPT `66,000 x 55,700` bid and
  `66,100 x 55,700` ask; ACB `22,200 x 700` bid and `22,250 x 46,500` ask.
- Harness reported `[PASS] distinct_books={'FPT': 4, 'ACB': 2}
  cached_symbols=['ACB', 'FPT']` and exited with code `0`.
- Phase 6 acceptance is PASS. Phase 7 remains the next pending live validation.

### 2026-09-19 — Phase 7 reconnect-handling task group

- Moved Phase 6 to pending live validation without changing its unchecked live acceptance.
- Opened Phase 7 offline implementation by explicit user instruction.
- Enabled the reconnect mechanism built into `python-socketio`.
- Added deterministic coverage for the production client constructor setting.
- Passed the full 126-test suite.
- Did not tune retry parameters or implement automatic resubscription.

### 2026-09-19 — Phase 7 retry/backoff task group

- Inspected the pinned `python-socketio` reconnect algorithm from the installed package.
- Configured unlimited reconnect attempts with a one-second initial delay.
- Configured exponential doubling with a 30-second maximum and 0.5 jitter factor.
- Extended deterministic constructor-option coverage.
- Passed the full 126-test suite.
- Did not implement automatic resubscription or forced-interruption acceptance.

### 2026-09-19 — Phase 7 automatic-resubscription task group

- Preserved desired normalized symbols separately from active subscription markers.
- Restored match-price, index, and bid-ask subscriptions in order after reconnect.
- Isolated restoration failures per stream so one error does not block the others.
- Added deterministic reconnect simulation tests.
- Passed the full 128-test suite.
- Did not address listener deduplication or forced-interruption acceptance.

### 2026-09-19 — Phase 7 listener-deduplication task group

- Instrumented the fake Socket.IO client to record every listener registration.
- Simulated three disconnect/connect cycles with all three market streams active.
- Verified lifecycle and market listeners remained registered exactly once.
- Verified one incoming payload caused one handler invocation per stream per cycle.
- Passed the focused 22-test client suite and full 129-test regression suite.
- Did not address decode error handling, raw debug mode, or forced-interruption acceptance.

### 2026-09-19 — Phase 7 decode-error-handling task group

- Audited existing type, protobuf decode, validation, and pipeline error boundaries.
- Added one malformed-frame recovery test for each realtime stream.
- Verified bad frames are logged, ignored, and never update market state.
- Verified the next valid frame is processed normally for every stream.
- Passed 81 focused tests and the full 132-test regression suite.
- Did not add raw debug mode or claim forced-interruption acceptance.

### 2026-09-19 — Phase 7 bounded-raw-debug task group

- Added an opt-in raw debug wrapper for all three market events.
- Logged only bounded event/type/size metadata and never raw payload content.
- Added thread-safe per-event counters with a default limit of 20 records.
- Exposed validated raw-debug flags in all four realtime acceptance scripts.
- Passed 30 client tests, all four CLI help audits, and 140 total tests.
- Left Phase 7 acceptance open because forced-interruption stream recovery is NOT TESTED.

### 2026-09-21 — Phase 7 forced-interruption live acceptance

- Added read-only connection-generation and disconnect counters plus a bounded
  `interrupt_transport` diagnostic operation to the Vietcap realtime client.
- Added `scripts/test_realtime_reconnect.py` to require a valid FPT tick before
  interruption, a completed reconnect, automatic subscription restoration, and
  a valid FPT tick afterward.
- The first live run reproduced a race: `python-socketio` invoked the namespace
  `connect` callback before setting its coarse `connected` flag, so the existing
  subscription guard rejected restoration.
- Updated namespace readiness detection to accept `/` in the Socket.IO namespace
  map during the callback and added a regression test for the real library order.
- Passed 34 focused client tests and the complete 646-test regression suite.
- Final live run received FPT at connection generation 1, forced one WebSocket
  interruption, reconnected as generation 2, automatically emitted the FPT
  subscription again, and received distinct valid FPT ticks afterward.
- Harness reported `[PASS] stream_resumed=True subscription_restored=True
  connections=2 disconnects=1 cached_symbols=['FPT']
  before_after_distinct=True` and exited with code `0`.
- Phase 7 acceptance is PASS; Phases 3–7 have no remaining live-validation gate.

### 2026-09-19 — Phase 8 quote-endpoint task group

- Moved Phase 7 to pending live validation by explicit user authorization.
- Added a pinned direct Requests dependency and bounded REST client.
- Added safe ticker normalization and exact quote URL construction.
- Added explicit timeout, HTTP/JSON error wrapping, and JSON-object enforcement.
- Added 16 deterministic tests; the full 156-test suite passed.
- Recorded the live HTTP 400 result without guessing response fields.
- Did not implement `gap-chart`, timeframes, or OHLCV normalization.

### 2026-09-19 — Phase 8 gap-chart-contract task group

- Added the documented gap-chart POST path and provider-native response method.
- Added exact request-body construction with normalized, deduplicated symbols.
- Added validation for non-empty timeframe token and positive integer bounds.
- Added HTTP, JSON, and top-level response-shape error handling.
- Added 16 tests, bringing REST coverage to 32 and the full suite to 172 tests.
- Recorded the live HTTP 400 probe without claiming historical retrieval success.
- Did not mark any timeframe or OHLCV normalization checklist item complete.

### 2026-09-19 — Phase 8 supported-timeframes task group

- Added `VietcapTimeFrame` as a closed `StrEnum` for the three observed values.
- Added case/whitespace normalization for string inputs.
- Rejected unsupported timeframe values before any HTTP request.
- Verified exact POST emission for `ONE_MINUTE`, `ONE_HOUR`, and `ONE_DAY`.
- Added eight tests, bringing REST coverage to 40 and the full suite to 180 tests.
- Did not implement OHLCV normalization or fixtures.

### 2026-09-19 — Phase 8 OHLCV model task group

- Added immutable, slotted, provider-independent `OHLCVBar`.
- Kept timestamp data as an integer because epoch unit and timezone semantics
  have not been established by a successful Vietcap response.
- Added exact-value, immutability, and slots tests.
- Passed the focused 2-test model suite and the full 182-test regression suite.
- Could not inspect the normal frontend because no browser surface was available;
  direct frontend and bundle requests still returned HTTP 400.
- Left OHLCV normalization unchecked because Vietcap column names remain
  unconfirmed and must not be guessed.

### 2026-09-19 — Phase 8 historical normalization task group

- Recorded the user's authenticated-browser HTTP 200 evidence for ACB daily
  history: a top-level array with 170 aligned column values.
- Corrected REST acquisition to accept and deeply detach an array of symbol
  objects instead of the previously assumed top-level object.
- Added evidence-backed normalization for `t/o/h/l/c/v` into immutable
  `OHLCVBar` values, including shape, numeric, OHLC, and volume validation.
- Added a credential-free three-bar fixture excerpted from the observed response.
- Passed 58 focused Phase 8 tests and the full 198-test regression suite.
- Marked normalization and fixtures/tests complete. Direct authenticated Python
  acquisition remains NOT TESTED, so Phase 8 STOP remains unchecked.

### 2026-09-19 — Phase 8 authorization probe task group

- Added optional authorization and device-ID headers without logging secrets.
- Added a bounded live historical probe that loads ignored local `.env` values
  and prints only bar metadata on success.
- Confirmed `.env` is ignored and inspected only variable names, never values.
- Passed 59 focused REST/historical tests and the full 201-test suite.
- Live Python request returned HTTP 400, so authorization and device ID alone
  are not proven sufficient; Phase 8 remains open.

### 2026-09-19 — Phase 8 cookie configuration task group

- Added optional `Cookie` header support without logging or persisting its value.
- Added the blank `VIETCAP_COOKIE` placeholder to `.env.example`; real values
  remain only in the ignored local `.env`.
- Updated the bounded live probe to require authorization, device ID, and cookie
  from the same user-managed browser session.
- Cookie-backed authentication support was ready for the subsequent live probe.

### 2026-09-19 — Phase 8 cookie live probe

- Confirmed local authorization, device ID, and cookie were present and
  structurally intact without printing their values.
- Replayed the exact browser-success request boundary (`countBack: 170`,
  `to: 1790035200`) with all three user-supplied values.
- Vietcap still returned HTTP 400; direct Python acquisition remains FAIL.
- Did not guess or add further browser headers. A controlled Copy-as-cURL test is
  the next diagnostic boundary.

### 2026-09-19 — Phase 8 successful historical acceptance

- Reproduced the observed safe browser headers and current ACB `ONE_MINUTE`
  request boundary without embedding credentials in source code.
- Received HTTP 200 directly in Python and normalized 121 historical bars.
- Observed normalized timestamp range `1789703880..1789717500`.
- Kept authorization, device ID, and cookie only in ignored local `.env` and
  never printed their values.
- Marked Phase 8 acceptance and STOP complete; did not start Phase 9.

### 2026-09-19 — Phase 9 SQLite foundation

- Opened Phase 9 by explicit user instruction and selected SQLite for V1.
- Added a standard-library connection boundary for `sqlite:///` URLs.
- Enabled foreign-key enforcement, a five-second busy timeout, and named rows.
- Verified both in-memory isolation and temporary file persistence in nine tests.
- Created no application tables and did not start the schema bootstrap task.

### 2026-09-19 — Phase 9 symbols table

- Added an idempotent provider-independent `symbols` table definition.
- Used normalized symbol as the primary key, with optional exchange,
  instrument type, and active-state fields.
- Enforced uppercase ASCII identifiers, valid active flags, and duplicate
  rejection while allowing both stocks and indices.
- Passed 21 focused database/schema tests.
- Did not create candles, signal tables, or the migration runner.

### 2026-09-19 — Phase 9 candles table

- Added an idempotent `candles` table linked to the normalized symbol catalog.
- Used `(symbol, timeframe, timestamp)` as the composite primary key.
- Enforced normalized timeframe, positive timestamp/prices, non-negative volume,
  valid OHLC relationships, and known-symbol references.
- Restricted deletion of symbols that still own candle history.
- Passed 38 focused database/schema tests.
- Did not create signal tables or the migration runner.

### 2026-09-19 — Phase 9 signals table

- Added an idempotent high-level `signals` table linked to `symbols`.
- Used an integer signal identity so repeated lifecycles remain distinct.
- Stored normalized strategy/timeframe/state identifiers, lifecycle timestamps,
  optional trigger price, and a JSON-validated reason payload.
- Kept strategy states open rather than hard-coding Phase 13 behavior early.
- Added a symbol/time lookup index and passed 57 focused schema tests.
- Did not create `signal_events` or the migration runner.

### 2026-09-19 — Phase 9 signal-events table

- Added an idempotent `signal_events` audit table linked to `signals`.
- Used a unique per-signal sequence and recorded from/to state, occurrence time,
  optional price, and JSON-validated reason details.
- Allowed a null source state for the initial event and kept transition rules out
  of the database until the Phase 13 strategy engine exists.
- Restricted deletion of signals that own event history.
- Passed 77 focused database/schema tests.
- Did not implement the migration/schema bootstrap runner.

### 2026-09-19 — Phase 9 migration bootstrap and completion

- Added a versioned, atomic schema bootstrap with migration identity tracking.
- Version 1 creates `symbols`, `candles`, `signals`, `signal_events`, and indexes
  in dependency order before recording success.
- Verified fresh temporary-file creation, reopen persistence, repeat-startup data
  preservation, and rejection of newer/changed migration metadata.
- Passed 83 focused database/schema/migration tests.
- Marked Phase 9 complete and stopped before Phase 10.

### 2026-09-19 — Development workflow rule update

- Changed the default unit of implementation from one small task group to one
  complete active phase per coding iteration.
- A phase may be split only after a concrete failure, blocker, unresolved external
  dependency, or material technical/safety risk prevents safe completion.
- Any split must be recorded here with its reason and remaining follow-up.
- Preserved phase gates, evidence-based checkboxes, mandatory testing, pending live
  validation, and the rule against automatically starting the next phase.
- Made no feature-code changes, opened no new phase, and changed no phase checkbox.

### 2026-09-19 — Phase 10 candle and indicators

- Opened and completed Phase 10 after explicit user authorization.
- Added a multi-symbol one-minute bar builder using caller-supplied Unix seconds;
  it emits completed OHLCV bars without synthesizing missing minutes and rejects
  ticks older than the active symbol bucket.
- Added SMA-seeded EMA20/EMA50, Wilder RSI14/ATR14, preceding-day average volume,
  timestamp-aligned excess return versus VNINDEX, and prior-period breakout
  resistance/support.
- All indicator outputs align with their input series and expose `None` during
  warm-up. Daily average volume and breakout levels exclude the current bar.
- Added deterministic validation and no-look-ahead tests. The complete suite
  passed with 297 tests.
- Marked Phase 10 complete and stopped before Phase 11. Phases 3–7 remain pending
  live validation.

### 2026-09-19 — Phase 11 time-matched intraday RVOL

- Opened and completed Phase 11 after explicit user authorization.
- Added immutable RVOL observations containing current cumulative volume,
  historical average cumulative volume, historical-session count, and ratio.
- Matched every baseline by Vietnam-local clock minute across unique prior
  sessions; missing historical minutes carry the latest earlier cumulative value.
- Rejected same-day/future baselines, duplicate historical dates, mixed symbols,
  mixed dates, non-minute bars, unaligned timestamps, and non-chronological data.
- Verified that later current or historical bars cannot change an earlier RVOL
  observation and that a zero historical baseline returns no ratio.
- Passed eight focused tests and the complete 305-test suite.
- Marked Phase 11 complete and stopped before Phase 12. Phases 3–7 remain pending
  live validation.

### 2026-09-19 — Phase 12 market regime

- Opened and completed Phase 12 after explicit user authorization.
- Added explicit Bull, Neutral, Bear and VNINDEX trend states plus immutable,
  explainable assessment and configuration models.
- Defined bullish trend as `VNINDEX > EMA20 > EMA50` and bearish trend as the
  symmetric ordering; mixed or unavailable EMA evidence cannot confirm a regime.
- Defined breadth from advances, declines, and unchanged issues. Ceiling/floor
  counts are excluded to avoid potentially double-counting overlapping groups.
- Required configurable breadth threshold and minimum population so strategy
  assumptions can be evaluated rather than hidden in implementation constants.
- Verified bullish/bearish confirmation, neutral fallbacks, inclusive thresholds,
  insufficient populations, conflicting inputs, and validation boundaries.
- Passed fifteen focused tests and the complete 320-test suite.
- Marked Phase 12 complete and stopped before Phase 13. Phases 3–7 remain pending
  live validation.

### 2026-09-19 — Phase 13 Signal Engine V1

- Opened and completed Phase 13 after explicit user authorization.
- Added the provider-independent `WATCH -> MONEY_FLOW -> BREAKOUT -> CONFIRMED ->
  ACTIVE -> EXIT` lifecycle with independent state per normalized symbol.
- Required Bull regime, stock trend, Relative Strength, and RVOL for money-flow
  confirmation; breakout and confirmation stages use explicit feature inputs.
- Required an explicit exit condition rather than inventing an unapproved stop or
  sell policy.
- Limited every observation to at most one transition, rejected out-of-order
  inputs, and suppressed exact duplicate observations.
- Added configurable post-exit cooldown; restart creates a new lifecycle with its
  event sequence reset to one.
- Added immutable transition events and JSON-serializable explanations containing
  positive, negative, missing, and trigger fields.
- Passed sixteen focused tests and the complete 336-test suite.
- Marked Phase 13 complete and stopped before Phase 14. Phases 3–7 remain pending
  live validation.

### 2026-09-19 — Phase 14 scanner universe

- Opened and completed Phase 14 after explicit user authorization.
- Added normalized instrument metadata and explicit scanner configuration models.
- Limited eligibility to active common-stock metadata on HOSE, HNX, and UPCoM;
  non-stock types and unsupported venues are excluded without ticker-name guesses.
- Added a daily liquidity pre-screen requiring configurable average volume and
  average traded-value thresholds over a complete lookback window.
- Enforced an explicit `as_of` boundary so only earlier completed daily bars enter
  the screen; insufficient history fails closed.
- Added deterministic bounded watch-list ranking by average traded value, average
  volume, and symbol.
- Passed sixteen focused tests and the complete 352-test suite.
- Marked Phase 14 complete and stopped before Phase 15. Phases 3–7 remain pending
  live validation.

### 2026-09-19 — Phase 15 Telegram Bot

- Opened and completed Phase 15 after explicit user authorization and confirmation
  that `TELEGRAM_BOT_TOKEN` was present in ignored local `.env`.
- Pinned and installed `python-telegram-bot==22.8` from the stable library line.
- Added `/start`, `/help`, `/soi`, `/scan`, `/market`, and `/why` through an
  injected data-service boundary with deterministic usage/missing-data responses.
- Added a safe runnable fallback that never fabricates unavailable market or signal
  data, plus a long-polling entry point.
- Added automatic SignalEvent alerts deduplicated by recipient, symbol, lifecycle,
  and event sequence; failed sends remain retryable.
- Verified the user-supplied token with Telegram `getMe`; authentication PASS for
  `@stock_vinavn_bot` without printing or logging the token.
- Passed eight focused tests and the complete 360-test suite.
- Marked Phase 15 complete and stopped before Phase 16. Phases 3–7 remain pending
  live validation.

### 2026-09-19 — Phase 16 backtest and performance (partial)

- Opened Phase 16 after explicit user authorization.
- Added a backtest adapter that reuses the production `SignalEngine` unchanged,
  opens on ACTIVE, closes on EXIT, and reports unclosed positions explicitly.
- Added win rate, average trade return, compounded-equity maximum drawdown, and
  profit factor; a no-loss sample reports profit factor as unavailable.
- Added formatted performance output and the Telegram `/performance` command.
- Added a bounded 140-session FPT/VNINDEX preliminary runner with explicit daily
  proxy limitations and no secret logging.
- Ran the authenticated request twice. Both returned HTTP success but zero FPT and
  zero VNINDEX `ONE_DAY` bars, including at the browser-confirmed timestamp
  boundary `1790035200`.
- Passed five focused tests and the complete 365-test suite.
- Split Phase 16 due to the concrete external historical-data blocker. The 3–6
  month preliminary backtest and Phase STOP remain unchecked and NOT TESTED.

### 2026-09-19 — Phase 16 historical-data resolution and completion

- Changed the preliminary acquisition from a combined FPT/VNINDEX request to
  separate ACB and VNINDEX requests matching the proven single-symbol contract.
- Received and aligned 170 real `ONE_DAY` bars for each series.
- Limited acceptance to the latest 120 aligned sessions, spanning 175 calendar
  days, to satisfy the requested 3–6 month preliminary window.
- Ran the shared SignalEngine with the documented daily volume and trend-only
  regime proxies. It produced zero closed trades and zero open positions.
- Reported 0% win rate, 0% average return, 0% maximum drawdown, and unavailable
  profit factor. These are zero-activity metrics, not a profitability claim.
- Preserved thresholds and did not tune the strategy merely to manufacture trades.
- Marked Phase 16 complete and stopped before Phase 17.

### 2026-09-19 — Phase 17 fundamental filter

- Opened and completed Phase 17 after explicit user authorization.
- Selected controlled UTF-8 CSV snapshots as the V1 source boundary, requiring an
  ISO as-of date and non-empty per-row provenance rather than assuming an unstable
  or unlicensed remote fundamentals API.
- Added immutable normalized EPS, P/E, P/B, ROE, revenue-growth, and profit-growth
  fields with explicit missing-value support.
- Added configurable, explainable PASS/FAIL/INSUFFICIENT_DATA assessments.
- Integrated assessments as an optional post-liquidity scanner filter with
  configurable handling of insufficient data.
- Kept fundamentals out of `SignalInputs` and `SignalEngine`, preventing any
  uncontrolled direct Buy/Sell transition.
- Passed thirteen focused tests and the complete 378-test suite.
- Marked Phase 17 complete and stopped before runtime integration.

### 2026-09-20 — Phase 18 runtime bot integration

- Added a concrete historical-first Telegram data service joining authenticated
  Vietcap daily REST, normalization, SQLite schema/cache, indicators, scanner, and
  the existing command layer.
- Replaced the unavailable-data fallback in `scripts/run_telegram_bot` with the
  real runtime service built from ignored `.env` configuration.
- Added `BOT_WATCH_SYMBOLS` configuration with FPT/ACB defaults.
- Made closed-market behavior explicit: refresh from Vietcap when possible, then
  fall back to the latest persisted daily bars on provider failure or empty data.
- Added real `/soi`, `/market`, `/why`, `/scan`, and `/performance` data paths while
  keeping missing breadth and intraday evidence clearly labeled.
- Passed the Sunday live smoke test: ACB and VNINDEX both returned the latest
  completed session dated Friday 2026-09-18. ACB close was 21,900 with EMA20,
  EMA50, and RSI14; VNINDEX close was 1,815.66 with increasing EMA trend.
- Kept breadth unavailable outside the live index stream instead of fabricating a
  full Market Regime.
- Marked runtime integration complete and moved optional News to Phase 19.

### 2026-09-20 — Phase 19 selectable CL1 + ASMF strategies

- Chose independent selectable strategies instead of blending incompatible entry
  rules into one opaque signal.
- Added pure provider-independent CL1 evaluation with EMA20/EMA50 cross timing,
  RSI14, ADX14, volume confirmation, MA200, and Chandelier Exit.
- Added ASMF market-regime, technical trigger, and price-volume footprint
  evaluation while keeping sector, point-in-time fundamentals, and institutional
  flow as explicit required inputs.
- Prevented incomplete ASMF evidence from producing BUY; missing layers are shown
  directly in the Telegram response.
- Added `/chienluoc` and optional strategy selection to `/soi`.
- Increased runtime daily history to 260 bars for MA200 and regime warm-up.
- Passed 385 offline tests plus live CL1 and ASMF evaluation using ACB/VNINDEX
  history for the completed 2026-09-18 session.
- Marked Phase 19 complete and moved optional News to Phase 20.

### 2026-09-20 — Phase 20 ASMF EOD foundation (partial)

- Added schema migration v2 for effective-dated sector membership, consolidated
  quarterly financial reports with actual publication dates, and daily foreign/
  proprietary trading values.
- Added validated provider-independent records, idempotent SQLite upserts, strict
  UTF-8 CSV loaders, templates, and a command-line import script.
- Added point-in-time fundamental scoring including ROE, TTM growth, earnings
  acceleration, and debt/equity; institutional net-flow scoring; and sector RS/
  breadth scoring requiring at least five members.
- Connected available persisted scores to the existing shared ASMF evaluator.
- Confirmed that foreign-only flow remains usable when proprietary data is absent.
- Added a Vietstock client from the observed `getdocument` contract. It acquires
  CSRF/cookies at runtime, normalizes report metadata, filters consolidated files,
  validates download hosts, and never persists session secrets.
- Live discovery passed for ACB page 1 and returned ten consolidated reports from
  2024–2026. Full PDF download did not complete within the bounded runner and is
  NOT TESTED; no partial file was retained.
- Phase 20 remains partial because PDF/ZIP content extraction and real normalized
  value import are not implemented yet.
- Added schema migration v3 and a bank-specific cumulative-report model. Quarterly
  NII/profit are derived from successive cumulative periods without look-ahead.
- Added bank scoring based on ROE, NII growth, profit growth, NPL ratio, loan-loss
  coverage, and CAR. The industrial-company debt/equity rule is never applied to
  rows in the bank table, and missing asset-quality/CAR inputs keep the score
  unavailable rather than silently passing.
- Added an ACB H1 2026 normalized CSV template containing only values confirmed
  from the reviewed consolidated report; NPL, reserve, and CAR remain blank.
- Real sector membership has not been acquired yet. Only the effective-dated
  schema, importer, and sector RS/breadth calculation currently exist.

### 2026-09-20 — Phase 20 safe report-file boundary (partial)

- Fixed bank dispatch so the existence of bank-specific rows selects the bank
  scoring branch even when CAR/NPL/coverage data is incomplete. It can no longer
  fall through to the industrial debt/equity formula.
- Changed Vietstock report downloads to bounded streaming through an atomic
  `.part` file, capped at 100 MiB. PDF signatures and ZIP integrity/path safety
  are validated before a file is accepted.
- Passed the complete 396-test suite.
- Direct HEAD requests to the Q1 ZIP and Q2 PDF did not respond inside two
  consecutive 30-second windows and were stopped. Live file download therefore
  remains NOT TESTED in this iteration; no partial file was retained.
- Phase 20 remains partial. The next task is to obtain one real ZIP/PDF through
  the bounded downloader, inspect its contents, and implement only the verified
  bank-field extraction path.

### 2026-09-20 — Phase 20 real ACB container inspection (partial)

- Added a provider-independent report inspector and CLI that classifies PDF and
  ZIP inputs before extraction. ZIPs containing XLS/XLSX/CSV/XML/XBRL are routed
  to a structured-data branch; PDFs with images but no text are routed to OCR.
- Verified the user's real consolidated ACB H1 2026 report: 96 pages, zero
  extractable text characters, and 96 embedded images. The correct branch is
  `ocr_required`.
- `tesseract`, `pdftoppm`, and `pdfinfo` are not installed. A package-manager
  availability check did not complete in two bounded waits and was terminated.
  Automatic numeric extraction from this scan is therefore blocked rather than
  guessed. OCR extraction remains NOT TESTED.
- The CLI is verified when invoked as
  `py -3.12 -m scripts.inspect_financial_report <path>`. Direct invocation as a
  file failed because Python used `scripts/` rather than the repository root as
  its import path; this matches the project's module-based script convention.
- Added three offline tests and passed the complete 399-test suite.
- Phase 20 stays partial. The next required input is either a Vietnamese-capable
  Tesseract installation (`vie` language data included) or a Vietstock ZIP that
  contains structured XLS/XLSX/CSV/XML/XBRL data.

### 2026-09-20 — Phase 20 OCR installation attempt (blocked)

- Winget resolved `tesseract-ocr.tesseract` version 5.5.3 and downloaded the
  upstream Windows installer, but no Tesseract executable appeared under either
  Program Files location.
- Follow-up installer and process checks hung in bounded command windows. The
  available Windows UI automation service was not configured, so the interactive
  installer/UAC step could not be completed safely by the agent.
- No extraction code or report values were changed. OCR remains NOT TESTED and
  the financial extraction checkbox remains open.
- Required follow-up: the user completes Tesseract installation interactively,
  including Vietnamese (`vie`) language data, then asks to rerun Phase 20.

### 2026-09-20 — Phase 20 real ACB OCR and import (partial)

- The user installed Tesseract 5.5.3 with `eng`, `osd`, and `vie` language data.
- Added local OCR for selected image-only PDF pages. It rotates the verified ACB
  scan by 180 degrees, normalizes contrast, doubles resolution, and invokes
  Tesseract with `vie+eng`; source PDFs are never modified.
- Added a fail-closed B02a/B03a parser. It requires the loan identity (gross loans
  minus loan-loss reserve equals net loans) and the interest identity (interest
  income minus interest expense equals net interest income). A small OCR digit
  mismatch can be reconciled only from an exact identity and within 0.2%; larger
  mismatches are rejected.
- Live OCR of pages 7, 8, and 10 produced a normalized ACB 2026Q2 row with public
  date 2026-08-15: cumulative NII 14,773,853; net profit 8,612,866; equity
  99,314,518; gross loans 745,759,303; loan-loss reserve 8,065,344 (million VND).
- Added that real row as a regression fixture and verified CSV loading, SQLite
  insertion, and read-back. The complete suite passes with 403 tests.
- NPL amount and CAR are not yet verified from the supplied report and remain
  NULL. Consequently the bank ASMF score correctly remains unavailable.
- OCR searches of pages 25–40 found no reliable NPL label. A second bounded
  search attempt was interrupted by the execution approval service; NPL/CAR
  extraction remains NOT TESTED beyond those pages.
- Real sector membership is still unavailable, so Phase 20 remains partial.

### 2026-09-20 — Phase 20 ACB NPL extraction (partial)

- Extracted and locally cached all 84 note pages from the supplied image-only
  ACB report, then OCRed them with `vie+eng` without modifying the source PDF.
- Located note 9.3 on PDF page 49 and visually verified the 30 June 2026 loan
  quality values: group 3 = 1,350,279; group 4 = 1,339,763; group 5 = 4,967,367
  million VND. Normalized NPL is their exact sum, 7,657,409 million VND.
- The quality table reconciles: groups 1–5 plus margin lending equal gross loans
  of 745,759,303 million VND.
- Extended the OCR parser and CLI with an optional loan-quality page. NPL remains
  nullable for reports without that page; invalid or impossible group sums fail.
- No CAR disclosure was found across the 84 note pages. CAR remains NULL and the
  bank score remains unavailable, as designed.
- The real ACB regression fixture now includes NPL. Live OCR generated a matching
  CSV with NPL, and the complete suite passes with 404 tests.
- Financial PDF extraction is now checked complete for values actually disclosed
  by this report. Phase 20 still remains partial solely within its current task
  list because real sector membership has not been acquired and validated.

### 2026-09-20 — Phase 20 real sector snapshot (complete)

- Confirmed from the installed vnstock VCI adapter source that the observed
  Vietcap catalog endpoint is `/api/price/symbols/getAll` and `icbCode2` is its
  industry grouping field. The legacy GraphQL request returned HTTP 200 with an
  empty object and was not used.
- Added an authenticated Vietcap sector client and CLI. It filters STOCK records
  to HSX/HOSE, HNX, and UPCOM; validates symbol/code shape; rejects conflicting
  classifications; and records the observation date rather than backdating.
- Runtime evidence corrected an initial assumption: Vietcap uses `HSX` for HOSE
  rows. A regression test now covers the real ACB shape.
- A live 2026-09-20 snapshot normalized 1,523 ICB2 memberships and imported all
  of them into runtime SQLite. Read-back confirmed ACB has ICB2 code 8300,
  effective from 2026-09-20, with 28 members in that group.
- The snapshot deliberately does not apply to the completed 2026-09-18 session;
  doing so would backdate knowledge and introduce look-ahead. It becomes usable
  from its observed date onward.
- The CafeF workbook supplied earlier contains one six-row financial-report sheet
  and no industry field; it was not used as a sector source.
- Added three offline adapter tests. The complete suite passes with 407 tests.
- All Phase 20 checklist items now have runtime or test evidence. Phase 20 is
  complete; Phase 21 has not been started.

### 2026-09-20 — ASMF sector-price runtime connection

- Closed the runtime gap between stored ICB2 membership and sector scoring.
  `/soi <symbol> ASMF` now loads cached daily histories for sector peers and
  fetches all missing peers in one bounded Vietcap `gap-chart` request.
- The Telegram path is capped at nine total sector members so the first command
  remains bounded. Up to eight peer histories are fetched concurrently using
  the confirmed single-symbol request shape, normalized, persisted to SQLite,
  and reused later. The scorer still requires at least five usable histories.
- Live evidence showed that both 27-peer and four-peer Vietcap requests exceed
  the 20-second HTTP timeout. A single-symbol request can also occasionally
  time out, so peer calls run concurrently and one failure does not block the
  other histories.
- Current sector classification is evaluated at command time, while financial
  reports and institutional flows remain evaluated at the latest price-bar date.
  This lets the 2026-09-20 observed membership classify the last completed
  2026-09-18 market session without backdating the stored snapshot.
- Added runtime regression coverage for bounded peer acquisition, SQLite reuse,
  and removal of the missing-sector flag. Full suite: 409 passed.
- Live acceptance is NOT TESTED successfully: repeated 2026-09-20 ACB smoke
  runs reached Vietcap's 20-second read timeout. This is an external provider
  runtime condition; the bot keeps any successful peer histories and continues
  to report the sector layer as missing until at least five histories exist.
- Phase 20 remains complete. Phase 21 has not been started.

### 2026-09-20 — Non-blocking sector-history synchronization

- Runtime evidence showed that fetching sector peers inside `/soi ... ASMF`
  makes Telegram depend on repeated 20-second Vietcap read timeouts. The task was
  therefore split at the acquisition/runtime boundary already required by the
  architecture.
- Added `SectorHistorySynchronizer`: it processes one member at a time, retries
  each failure with exponential backoff, stores each successful 260-bar history
  immediately, skips members already holding at least 126 daily bars, and avoids
  synchronizing the same sector twice in one watchlist run.
- `scripts/run_telegram_bot` now starts the synchronizer in a separate daemon
  thread with its own Vietcap client and SQLite connection. Default interval is
  six hours. Retry count, backoff, and interval are configurable in `.env`.
- `/soi ... ASMF` now performs no network requests for sector peers. It reads all
  usable peer histories from SQLite and honestly retains the missing-sector flag
  until five histories are available.
- Added `scripts/sync_sector_history.py` for an explicit manual preload.
- Focused tests: 7 passed. Complete suite: 411 passed.
- Live sync remains NOT TESTED successfully because Vietcap was still timing out
  on 2026-09-20. No live success has been claimed.

### 2026-09-20 — Phase 21 News/Sentiment ZIP audit and integration map

- Audited the supplied `vn-stock-sentiment-bot` ZIP as input material, not as a
  second application. Its 68 legacy tests pass on Python 3.12. The ZIP contains
  a CafeF RSS provider, normalizer, bounded fingerprint dedup, title-weighted
  ticker linker, priority event classifier, lexicon sentiment, time-decay
  aggregation, SQLite repository/query service, and a separate Telegram bot.
- REUSE: CafeF provider contract, normalization, deduplication, ticker relevance,
  event classification, time-decay aggregation, repository/query concepts,
  bounded live runner, fixtures, and relevant tests.
- MOVE/RENAME: provider-independent code will enter a top-level `intelligence`
  package aligned with this repository; ZIP `src.news` and `src.storage`
  namespaces will not be copied mechanically.
- MODIFY: sentiment output must retain positive/neutral/negative probabilities,
  model confidence (explicitly uncalibrated), backend/name/version and analysis
  timestamp. SQLite changes must be additive and preserve existing rows.
- ADAPTER: `SentimentQueryService` will be injected into `RuntimeBotDataService`;
  Telegram and ASMF will depend only on that boundary.
- DO NOT IMPORT: the ZIP Telegram polling application, token handling, independent
  alert cooldown/manager, infinite runtime loop, Docker/build artifacts, caches,
  bytecode, or bundled runtime database.
- NEW FILES PLANNED: news domain/provider/repository/service package, transformer
  and lexicon model backends, ingestion runner, query/Telegram adapters, benchmark
  fixture/runner, migrations, and focused integration tests.
- DATABASE: keep `news_sentiment.db` separate initially. Add probability/model
  columns and primary-ticker relevance without dropping the legacy schema.
- Model decision: `FiinGroup/phobert-finetuned` is the preferred default candidate
  because its public model card describes three-class PhoBERT training on roughly
  15,000 Vietnamese financial-news records (labels 0 negative, 1 neutral,
  2 positive). This is provenance evidence, not an independent quality claim.
- Concrete phase-split blocker: the environment has no `torch`, `transformers`,
  `tokenizers`, or model weights, and the ZIP contains only lexicon code. Actual
  transformer loading, CPU inference, dependency compatibility, and fallback
  acceptance cannot be truthfully validated until pinned heavy dependencies and
  the external model artifact are installed/downloaded. Phase 21 is PARTIAL;
  no production code has been imported yet and Phase 22 has not started.

### 2026-09-20 — Phase 21 transformer runtime unblocked

- Pinned `pydantic==2.11.10`, `transformers==4.57.6`, `torch==2.9.1`, and
  `safetensors==0.7.0`. Because the user-level Python environment already had
  unrelated dependency conflicts, installation was isolated in the ignored
  `.venv-phase21` environment instead of mutating those packages further.
- `.venv-phase21` passes `pip check`; the complete existing bot suite passes
  there with 411 tests.
- Downloaded the public 540,026,460-byte safetensors checkpoint into the ignored,
  configurable model cache. A bounded CPU smoke test loaded
  `FiinGroup/phobert-finetuned` and produced three probabilities
  `[0.12003749, 0.61362219, 0.26634035]`, sum `1.00000002`.
- Runtime config exposes backend, model, CPU device, cache, lexicon fallback,
  half-life, and severe-negative blocker thresholds. No secrets are involved.
- The checkpoint config exposes generic `LABEL_0/1/2`; Phase 21 must map these
  explicitly according to the model card (negative/neutral/positive) and retain
  that mapping in tests. Transformer integration is now unblocked, but the news
  core/import, schema migration, commands, and ASMF wiring remain incomplete.

### 2026-09-20 — Phase 21 sentiment model boundary

- Added the provider-independent `intelligence.news` domain with immutable news
  and inference records. Inference retains all three probabilities, an explicitly
  uncalibrated `model_confidence`, backend/name/version, analysis timestamp, and
  a future calibration-version slot. Score is derived as `P(pos)-P(neg)`.
- Added load-once `PhoBERTSentimentModel` with deterministic 256-token truncation
  and explicit FiinGroup `LABEL_0/1/2` mapping to negative/neutral/positive.
- Preserved a financial lexicon backend. Transformer failures are logged and
  return `backend=lexicon_fallback`; fallback is never silent.
- Focused tests prove normalized probabilities, label mapping, load-once behavior,
  and explicit fallback. Focused: 2 passed; full suite: 413 passed.
- This safe task boundary does not yet claim the ZIP provider/repository import.
  SQLite migration is the next Phase 21 task group.

### 2026-09-20 — Phase 21 news SQLite migration

- Added a separate `SQLiteNewsRepository`; the main market database remains
  untouched. Startup creates a new normalized schema or inspects a legacy ZIP
  `news_items` table and additively introduces missing fields with `ALTER TABLE`.
- Stored inference fields include label, derived score, all three probabilities,
  model confidence, backend/name/version, analyzed timestamp, and nullable
  calibration version. Ticker links preserve primary status and relevance.
- Inserts are URL/idempotent and atomic with ticker links. Reads reconstruct the
  immutable domain model; ticker queries remain behind the repository boundary.
- Regression proves a pre-existing legacy row survives migration unchanged.
  Focused sentiment/repository tests: 4 passed; full suite: 415 passed.
- Provider, normalizer, dedup, entity/event layers remain the next task group;
  Phase 21 stays PARTIAL and Phase 22 has not started.

### 2026-09-20 — Phase 21 News & Transformer Sentiment complete

- Added the provider-independent CafeF RSS ingestion path with normalized text,
  stable URL deduplication, priority event classification, title-first ticker
  relevance, and bounded one-shot execution. It writes only to the separate news
  SQLite database and does not start a second Telegram application.
- Added time-decayed ticker aggregation and wired it into the existing runtime.
  `/tin <MÃ>` and `/sentiment <MÃ>` are registered; `/soi` includes optional
  company sentiment. `/market` reports insufficient news coverage instead of
  fabricating a market-wide score from company-only links.
- Added a configurable, fail-closed ASMF news overlay. It can only turn an
  already-produced ASMF BUY into BLOCKED for a recent, primary-ticker, severe
  negative configured event with adequate confidence. Positive news cannot
  create a BUY, and stale/low-confidence/irrelevant news cannot block.
- Extended the existing Telegram alert publisher with idempotent news delivery;
  no independent alert manager, polling bot, or token path was introduced.
- Added a checked-in 10-case Vietnamese benchmark and metric runner (accuracy,
  macro F1, confusion matrix). Results are computed at runtime, not hard-coded.
- Live CafeF/PhoBERT acceptance exposed a real `transformers` output-shape
  difference. The first three items safely fell back to the explicitly labelled
  lexicon backend. After fixing and regression-testing both supported shapes, a
  bounded rerun inferred without fallback and persisted two new PhoBERT items
  (`inserted=2 duplicates=3`).
- Evidence: focused Phase 21 suite 23 passed before the live fix; output-shape
  regression 6 passed; final full regression 422 passed; isolated transformer
  environment `pip check` reports no broken requirements.
- Phase 21 is complete. No Phase 22 work has started.

### 2026-09-20 — Phase 22 Investment Intelligence Dashboard

Goal of this phase: move `/soi` from a price-and-signal reply toward a compact
investment dashboard, and make every displayed number traceable to a source and
a session date. No architecture was replaced and no provider contract changed.

#### Capabilities added

- **View-model layer.** `runtime/views.py` holds immutable, presentation-free
  dataclasses (`StockAnalysisView`, `TechnicalView`, `MarketContextView`,
  `StrategyView`, `FundamentalView`, `SentimentView`, `SectorView`,
  `DataQualityView`). Every optional field means exactly one thing: the backend
  could not establish that value.
- **Pure analysis builders.** `runtime/analysis.py` converts bars, scores and
  aggregates into views. It computes only indicators the repository already
  owns (EMA20/50, MA200, RSI14, ATR14, ADX14, 20-session volume ratio, relative
  strength vs VNINDEX, 20/60-session breakout levels). No new indicator family
  was introduced.
- **Formatter boundary.** `telegram_bot/formatters.py` renders views and does no
  computation or data access. Unavailable values render as an explicit marker,
  never as `None`, `NaN` or a silent omission.
- **Support/resistance exposure.** R1/R2 come from prior 20/60-session highs,
  S1/S2 from the matching lows, plus EMA50/MA200 when they sit on the correct
  side of price. Each level carries its reason. Duplicate levels are dropped.
- **Fundamental exposure.** `fundamentals/repository.py` reads point-in-time
  facts from the consolidated quarterly reports already stored for ASMF, with a
  separate bank branch (ROE, TTM profit growth, NPL, coverage, CAR) that never
  falls through to industrial leverage rules. P/E, P/B and EPS cannot be derived
  from stored data (no share count) and stay unavailable unless a controlled CSV
  snapshot is supplied through `FUNDAMENTALS_CSV_PATH`.
- **ASMF layer status.** `StrategyResult` gained a `layers` tuple. ASMF now
  reports Market / Sector / Fundamental / Institutional / Technical explicitly as
  PASS / FAIL / MISSING, and the runtime appends a Sentiment layer as
  SUPPORTIVE / NEUTRAL / RISK / MISSING. A MISSING layer still blocks BUY; a
  SUPPORTIVE sentiment layer can never unlock one.
- **Explainability.** `/why` renders state, evidence coverage, layer status,
  indicator interpretation in `indicator → meaning → implication` form, next
  triggers to watch, market context, news context and data limitations.
- **Data quality on every response.** Freshness is derived from the session date
  against the current date (EOD_TODAY / EOD / STALE / UNAVAILABLE) with the
  staleness in days, the session date, the market source, the fundamental source
  with as-of date, and the news backend with its latest article time. A SQLite
  fallback is always labelled as cached.
- **Scanner explanations.** `/scan` now reports trend, relative strength,
  liquidity, fundamental status and CL1 state per symbol. `scan_results()` still
  returns the original ticker tuple, so existing callers are unaffected.
- **New commands.** `/technical`, `/fundamental`, `/sector`. `/chienluoc` now
  documents CL1 entry/exit conditions and the ASMF layers with the data each
  needs. `/performance` separates ENGINE TEST from STRATEGY VALIDATION and states
  plainly that a zero-trade sample establishes nothing about profitability.
- **Telegram UX.** `/soi` attaches an inline keyboard (Technical, Fundamental,
  ASMF, Why, Tin, Sentiment, Market). Every button maps to an existing text
  command, so the keyboard is additive. Long replies are chunked on paragraph
  boundaries below the Telegram length limit.
- **Smart alerts.** Signal alerts now carry positive, negative and missing
  evidence plus the event timestamp. Dedup and the single alert boundary are
  unchanged.

#### Files changed

Added: `runtime/views.py`, `runtime/analysis.py`, `fundamentals/repository.py`,
`telegram_bot/formatters.py`, `tests/test_stock_dashboard.py`,
`tests/test_fundamental_repository.py`.

Replaced: `runtime/bot_service.py`, `telegram_bot/commands.py`,
`telegram_bot/app.py`.

Modified: `strategy/technical_strategies.py` (added `StrategyLayer` and the
`layers` field; ASMF layer population; no decision rule changed),
`telegram_bot/alerts.py` (richer alert body), `tests/test_telegram_bot.py`
(registered-command set now includes the three new commands, and the assertion
ignores non-command handlers).

#### Architecture

    Vietcap REST / SQLite / news DB
      → repositories & stores (asmf_data, fundamentals, intelligence.news)
      → analysis engines (data.indicators, strategy.technical_strategies,
                          asmf_data.scoring)
      → runtime.analysis (pure view builders)
      → RuntimeBotDataService (orchestration only)
      → telegram_bot.formatters (rendering only)
      → telegram_bot.commands / app (argument parsing and delivery)

Strategies still never call a provider, and the Telegram layer still never calls
a provider or the news database directly.

#### Tests

459 passed offline on Python 3.12 (422 pre-existing plus 37 new). New coverage:
complete `/soi`, `/soi` without fundamentals, `/soi` without a sentiment module,
`/soi` with an empty news window, provider failure with SQLite fallback
labelling, missing history, `/why` interpretation shape, RSI interpretation not
becoming an order, `/market` regime and unavailable sections, freshness
classification by age, cached labelling, fundamental as-of and period display,
strategy evidence coverage, ASMF missing-layer blocking, positive sentiment not
producing BUY, technical levels with reasons, scan explanations, preserved
`scan_results()` contract, sector missing-data honesty, legacy data-service
compatibility, usage-error handling, formatter safety on a fully empty view, and
short-history degradation.

#### Live evidence

NOT TESTED. The development sandbox has no route to Vietcap, CafeF or the
Telegram API (outbound requests to `mt.vietcap.com.vn` return no response), so
`/soi`, `/market` and `/sentiment` were validated offline only. Live acceptance
must be rerun locally with real credentials.

#### Limitations

- Market breadth, market-wide liquidity and market-wide foreign flow remain
  unavailable outside a live session and are printed as `unavailable`.
- Regime is trend-only until breadth is live; the response says so on every
  `/market` reply.
- No calibrated strategy confidence exists. Only evidence coverage (`n/m`) and
  the sentiment classifier's own model confidence are shown.
- P/E, P/B and EPS require the optional CSV snapshot.
- `/sector` leaders and laggards appear only when at least five members have 126
  cached sessions; otherwise the shortfall is reported.

#### Deferred

Portfolio management, DCF/fair value, price forecasting and ML prediction,
social-media sentiment, watchlist persistence (no user-persistence layer exists
yet), and Sharpe/Sortino metrics.

### Phase 23 — Portfolio, Risk & Watchlist

#### Goal
Evolve the bot from a stock-analysis bot toward an investment assistant: per-user watchlist and holdings,
valuation, unrealized P&L, exposure, concentration, position sizing and deterministic stress tests.
No forecast/ML, no DCF/fair value (Phase 24), no execution, no optimization.

#### Architecture
SQLite → `portfolio.repository` → `portfolio.service` (+ pure `valuation`, `risk`, `position_sizing`,
`stress`) → `runtime.portfolio_runtime.PortfolioRuntime` (view models in `runtime.portfolio_views`) →
`telegram_bot.portfolio_formatters` → `telegram_bot.portfolio_commands` → thin handlers in
`telegram_bot.portfolio_handlers`. Prices come only through `RuntimeBotDataService._history`
(Vietcap historical, SQLite cache fallback); no second data pipeline exists. Identity is the Telegram
numeric user id. Money arithmetic uses `Decimal`; canonical decimal text is persisted exactly alongside
the legacy v4 REAL compatibility columns. VND only, long equity only.

#### Schema migration
Version 4 `portfolio_watchlist_holdings`: `users`, `watchlist`, `portfolio_holdings` (+ symbol indexes).
Version 5 `portfolio_exact_decimals` additively adds exact decimal-text columns and backfills v4 rows;
the repository writes both representations and reads the exact one. FKs to `users` (cascade delete)
and `symbols`. Atomic via `bootstrap_schema`; migrations 1–4 remain immutable.

#### Files added
`portfolio/{__init__,config,models,repository,risk,valuation,position_sizing,stress,service}.py`,
`runtime/portfolio_views.py`, `runtime/portfolio_runtime.py`,
`telegram_bot/portfolio_{commands,formatters,handlers}.py`,
`scripts/test_portfolio_live.py`, `tests/portfolio_fakes.py`,
`tests/test_portfolio_{schema,repository,domain,runtime,telegram}.py`.

#### Files modified
`data/schema.py` (v4 tables plus v5 exact-decimal columns), `data/migrations.py`,
`runtime/bot_service.py` (`self.portfolio`,
`symbol_overview(..., user_id=None)`), `telegram_bot/app.py`, `telegram_bot/commands.py`
(help, `portfolio_command`, `soi(..., user_id=None)`), `telegram_bot/formatters.py`
(`extra_blocks`), `.env.example`, `tests/test_migrations.py` and `tests/test_telegram_bot.py`
(schema version 5 / extended command set). `telegram_bot/portfolio_handlers.py` and
`telegram_bot/app.py` enforce the private-chat boundary for personal data.

#### Commands
`/watchlist`, `/addwatch S`, `/removewatch S`, `/portfolio`, `/addholding S QTY AVG_COST` (upsert:
replaces quantity and average cost), `/removeholding S`, `/risk`, `/size S ENTRY STOP CAPITAL [RISK_PCT]`,
`/stress portfolio PCT`, `/stress S PCT`, `/setrisk PCT`, `/risksettings`; `/soi` gains a portfolio-context block.

#### Formulas
cost = qty × avg cost; value = qty × price; unrealized P&L = value − cost; P&L % = P&L / cost × 100;
weight = value / Σ priced value; sector weight = Σ member value / Σ priced value.
Sizing: risk budget = capital × risk% / 100; risk/share = entry − stop;
shares = min(floor(budget / risk per share), floor(capital / entry)); value = shares × entry;
allocation = value / capital; max loss = shares × risk/share. V1 never assumes leverage.
Stress: change = value × shock% (whole portfolio or one symbol); impact = change / current portfolio value.

#### Risk assumptions
Concentration uses `>=` thresholds from `.env` (stock 25/40, sector 40/60, no opaque score); "Unknown" sector
is missing data, not a sector. Historical volatility, beta vs VNINDEX and max drawdown use aligned DAILY simple
returns of current weights held constant (static-weight proxy), lookback 120, minimum 60 sessions; holdings that
skipped different sessions are not mixed. Otherwise the metric prints "Unavailable — reason".

#### Price-source behavior
Latest close from `_history`; freshness from `describe_freshness`; fallback labelled "Cached EOD". Realtime state is
not wired into the runtime service, so valuation is never labelled Realtime. Mixed sessions produce a warning.
A holding without a price is excluded from value, weights, exposure and stress and flagged
("Valuation incomplete"); it is never valued at zero. Unknown symbols cannot be added.

#### P&L meaning
UNREALIZED only. Average cost is user-supplied; fees, taxes and slippage are excluded. No realized P&L / ledger.

#### Stress methodology
Deterministic arithmetic, not a forecast. Shock range −100..+100. No VNINDEX/beta stress.

#### Tests
Python 3.12.10: 130 Phase 23-specific tests pass. The focused Phase 23 plus migration/Telegram regression
command passes 145 tests. The complete isolated-dependency regression passes 589 tests; CL1/ASMF behavior
remains unchanged. `pip check` reports no broken requirements for the `.venv-phase21` site-packages with
user-level packages excluded. The Microsoft Store workspace `.venv` launcher itself remains unusable, so
the verified isolated packages were supplied through `PYTHONNOUSERSITE` and `PYTHONPATH` to `py -3.12`.

#### Live evidence
PASS on 2026-09-20. `scripts/test_portfolio_live.py` used the configured live Vietcap EOD endpoint,
synthetic ACB watch/holding data and a temporary SQLite database. Live EOD valuation and every Phase 23
command path passed; no real holdings were read or persisted. `scripts/test_telegram.py` authenticated
`@stock_vinavn_bot` through Telegram `getMe` without printing the token. This does not close the separate
Phase 3–7 realtime-stream validations, which remain PENDING.

#### Privacy
Portfolio/risk commands are refused outside a private Telegram chat. `/soi` and its ASMF callback omit
portfolio context outside private chat, preventing holdings/P&L from being echoed into group conversations.

#### Limitations
No transaction ledger or realized P&L; long-only; no fees; whole shares, not rounded to lot size; no realtime
valuation; one history request per holding per command (`/portfolio`, `/risk`, `/stress`, and `/soi` for held
symbols); historical metrics need ≥60 aligned sessions; corporate-action adjustment of provider closes is not
yet established, so historical risk remains a labelled proxy; new portfolio output is English while the rest
of the bot is Vietnamese; invalid Phase 23 `.env` values fail at startup.

#### Deferred
Portfolio-aware alerts (hooks `is_held` / `is_watched` exist), beta-based VNINDEX stress, transaction ledger,
realtime pricing, Phase 24 valuation, forecasting, optimization, brokerage execution. No investment execution exists.

### 2026-09-20 — Phase 20 arbitrary-symbol sector-sync follow-up

- Replaced the fixed-watchlist-only sector daemon loop with a reusable background
  worker that accepts arbitrary normalized ticker requests while retaining the
  configured watch symbols for periodic synchronization.
- `/soi <symbol> ASMF` and `/sector <symbol>` now enqueue missing sector history
  without performing provider I/O on the Telegram command path. Responses expose
  current usable/total member counts and whether a request was queued or already
  protected by in-flight/cooldown deduplication.
- Added a 15-minute default on-demand cooldown and an eight-uncached-member
  default batch limit. Large sectors such as VHM's 123-member ICB2 group therefore
  cannot hold the worker indefinitely in one pass; successful histories persist
  and later periodic passes expand coverage.
- Preserved ASMF fail-closed behavior. The queue does not fabricate a sector
  score, and missing BCTC or institutional flow remains `MISSING` until real
  point-in-time records exist.
- Acceptance coverage uses a symbol outside the configured watchlist and proves
  the sequence `Sector=MISSING` → background SQLite population → sector layer
  available once five member histories exist.
- Focused runtime/worker/dashboard/Telegram regression: 54 passed. Full isolated
  dependency regression: 594 passed in 4.76 seconds.
- Isolated `.venv-phase21` dependency check: `No broken requirements found`.
- Live Vietcap population for VHM is NOT TESTED in this coding iteration; provider
  timeout and data availability remain external runtime conditions.

### 2026-09-20 — Phase 20 sector-sync notification follow-up

- Added a worker completion-listener boundary. `SectorHistorySyncWorker` publishes
  normalized `SectorSyncResult` values after each expected sync pass and remains
  independent of Telegram APIs.
- Added a thread-safe Telegram broker keyed by chat and symbol. It emits at most
  one incomplete notification while keeping the chat subscribed, then one READY
  notification when at least five sector histories are usable. The most recent
  incomplete result is retained for chats that register after a fast worker pass.
- Telegram registers the chat before executing `/soi <symbol> ASMF`, `/sector
  <symbol>`, or the ASMF inline callback, preventing a completion race. A local
  readiness check removes registrations immediately when no sync is needed.
- Notifications contain a `Xem lại ASMF` callback. The bot never pushes an old
  analysis automatically; clicking the button recomputes it from current data.
- Failed Telegram sends are returned to the broker queue and are not treated as
  delivered. The async dispatcher starts/stops with the polling application.
- Focused notification/worker/runtime/Telegram regression: 59 passed. Full
  isolated-dependency regression: 599 passed in 5.01 seconds.
- Live Telegram delivery after a real VHM Vietcap sync is NOT TESTED; it requires
  a successful external provider batch while the polling bot is running.
- BCTC/institutional-flow acquisition and candlestick charts were not mixed into
  this phase and remain the next two explicit user-requested follow-ups.

### 2026-09-20 — Phase 20 sector-sync notification durability follow-up

Audit xác nhận đúng một vấn đề durability và hai bug vận hành thực sự trong
đường notification; không có bug nào trong CL1/ASMF, BCTC, institutional flow
hay OCR.

#### Vấn đề đã xác nhận

- DURABILITY LIMITATION (thật): `SectorSyncNotificationBroker` giữ toàn bộ
  `_watchers`, `_latest`, `_pending` trong RAM; `scripts/run_telegram_bot.py`
  tạo broker mới mỗi lần khởi động. Một lần restart làm mất registration, kết
  quả incomplete được retain, và cả notification đã queue nhưng chưa gửi.
- BUG (thật): `deliver_sector_notifications` raise ngay ở lần gửi hỏng đầu
  tiên và requeue phần còn lại vào đầu hàng đợi — một chat bị chặn/lỗi sẽ chặn
  vĩnh viễn toàn bộ hàng đợi (head-of-line blocking) và retry vô hạn mỗi giây.
- BUG (thật): không có TTL. `_watchers`/`_latest` sống đến khi process chết,
  nên một sector không bao giờ đủ dữ liệu để lại registration sống mãi.

#### Kiến trúc sau thay đổi

    SectorHistorySyncWorker (không import Telegram)
      -> SectorSyncResult
      -> completion listener
      -> SectorSyncNotificationBroker
           -> NotificationStore  (InMemory hoặc SQLite)
      -> async dispatcher (post_init task của polling app, app.py không đổi)
      -> Telegram sendMessage + nút "Xem lại ASMF"

Broker giữ nguyên toàn bộ public API cũ (`watch`, `unwatch`, `is_watching`,
`publish`, `drain`, `requeue`) và thêm `mark_delivered`, `pending_count`,
`purge_stale`, `maintain`. Trạng thái được đẩy xuống một store có thể thay
thế: `InMemoryNotificationStore` giữ nguyên hành vi RAM cũ (mặc định, dùng
cho test), `SQLiteNotificationStore` ghi vào chính database runtime hiện có.
Không có database thứ hai, không có alert manager thứ hai, không có bot
Telegram thứ hai, worker vẫn không biết gì về Telegram.

#### Schema migration

Version 6 `sector_sync_notifications`, additive, không sửa/không drop bất kỳ
migration 1–5 nào (xác định từ `data/migrations.py` thật, migration mới nhất
trước đó là v5 `portfolio_exact_decimals`):

- `sector_sync_watchers(chat_id, symbol, incomplete_sent, closed, pending_kind,
  pending_text, pending_attempts, created_at, updated_at)`, khoá chính
  `(chat_id, symbol)`, index theo `symbol` và theo `pending_kind`.
- `sector_sync_results(symbol, sector_code, members, usable, failed, ready,
  fingerprint, updated_at)` giữ kết quả worker gần nhất cho subscriber đến
  muộn.

Có chủ ý không đặt foreign key tới `symbols`: một chat có thể hỏi mã chưa
từng tải lịch sử thành công, trong khi `symbols` chỉ được ghi sau khi worker
tải thành công — FK sẽ khiến notification fail-closed sai.

#### Ngữ nghĩa giao hàng

At-least-once. Gửi Telegram trước, chỉ đánh dấu delivered sau khi gửi thành
công; process chết giữa hai bước có thể lặp một thông báo nhưng không bao giờ
mất im lặng. `drain()` claim theo process nên sau restart mọi dòng pending
còn lại được giao lại.

Một chat lỗi không còn chặn hàng đợi: mỗi notification thử riêng,
`pending_attempts` tăng dần và bị loại sau `SECTOR_NOTIFICATION_MAX_ATTEMPTS`
(mặc định 5). Registration/retained result quá
`SECTOR_NOTIFICATION_TTL_SECONDS` (mặc định 86400) bị dọn định kỳ mỗi
`SECTOR_NOTIFICATION_PURGE_INTERVAL_SECONDS` (mặc định 300).

Đúng một process bot sở hữu hai bảng này; broker serialise mọi thao tác bằng
một `threading.RLock`, mỗi thao tác store chạy trong transaction SQLite
riêng qua connection ngắn hạn.

#### Hành vi được giữ nguyên

ASMF fail closed, ngưỡng năm peer history, worker độc lập Telegram, command
path không chờ network, failed send vẫn retry được, "Xem lại ASMF" vẫn
recompute bằng dữ liệu hiện tại, ranh giới private-chat của portfolio, ngữ
nghĩa CL1/ASMF, news blocker, nhãn SQLite fallback. Ba test notification cũ
(`tests/test_sector_notifications.py`) pass nguyên văn, không sửa một dòng.

#### Test — bằng chứng thật, chạy cục bộ 2026-09-20

Máy: Windows, `py -3.12`, `.venv` của repo.
py -3.12 -m pytest -q tests/test_sector_notification_persistence.py tests/test_sector_notifications.py 17 passed in 5.59s

py -3.12 -m pytest -q tests/test_migrations.py tests/test_portfolio_schema.py tests/test_sector_history_sync.py tests/test_telegram_bot.py 28 passed in 2.03s

py -3.12 -m pytest -q 612 passed in 11.32s


612 = 599 (regression trước iteration này) + 13 test mới trong
`tests/test_sector_notification_persistence.py`. Không có test nào bị sửa để
ép pass; không portfolio test nào fail; CL1/ASMF decision behavior không đổi.
py -3.12 -m pip check


Không sạch, nhưng cả 8 conflict đều thuộc các gói **không nằm trong
`requirements.txt` của repo này** (`googleapis-common-protos`,
`google-ai-generativelanguage`, `google-api-core`, `grpcio-status`,
`proto-plus`, `pyppeteer`, `streamlit`) — các công cụ khác được cài chung vào
cùng `.venv`. Iteration này không thêm bất kỳ dependency mới nào và không
gây ra các conflict trên. Đây là tình trạng môi trường có từ trước; các
phase trước (Phase 21+) từng phải tách `.venv-phase21` riêng vì cùng lý do.
Khuyến nghị: chạy `pip check` trong một virtualenv chỉ chứa
`requirements.txt` của repo để có kết quả sạch, chứ không kết luận đây là
lỗi do thay đổi lần này.

#### Live evidence — PASS, chạy cục bộ 2026-09-20

Bước 1 — bounded dry-run (không gửi Telegram), xác nhận sync thật với
Vietcap:

py -3.12 scripts/test_sector_notification_live.py --symbol VHM --dry-run [INFO] sector=8600 members=123 usable=9 downloaded=8 failed=0 elapsed=2.2s [INFO] dry run queued 1 notification(s) ✅ Dữ liệu ngành VHM đã sẵn sàng: 9/123 mã đủ lịch sử. Bấm "Xem lại ASMF" để cập nhật phân tích.


Bước 2 — sau khi cấu hình `TELEGRAM_CHAT_ID` trong `.env`, chạy end-to-end
thật, có gửi Telegram:

py -3.12 scripts/test_sector_notification_live.py --symbol VHM [INFO] sector=8600 members=123 usable=9 downloaded=8 failed=0 elapsed=1.7s [INFO] Telegram authenticated as @stock_vinavn_bot [PASS] delivered 1 real Telegram notification(s)


Exit code `0`. Chuỗi thật đã được xác nhận: real Vietcap sector sync
(`sector=8600`, `usable=9/123 ≥ 5` → READY) → worker completion → broker
publish → Telegram `getMe` authenticate cho `@stock_vinavn_bot` → thật sự
gửi 1 tin nhắn qua Telegram Bot API kèm nút "Xem lại ASMF". Không dùng
holding/portfolio thật; chạy trên bản sao tạm của database
(`copy_runtime_database`), không ghi vào database sản xuất thật; không log
token/cookie/chat id.

**LIVE ACCEPTANCE: PASS**

#### Ngoài phạm vi

Thu thập BCTC/institutional flow thật và candlestick chart vẫn là hai
follow-up riêng, không bị trộn vào iteration này. Phase 3–7 giữ nguyên
PENDING.

### 2026-09-21 08:25 +07:00 — Phase 3 pre-open live retry

- Command: `py -3.12 scripts\test_realtime.py --hold-seconds 60 --min-updates 2 --raw-debug`.
- The real Vietcap WebSocket connected (`transport=websocket`) and the client
  emitted the exact FPT-only `w-match-price` subscription.
- The 60-second observation received zero FPT events. The machine clock was
  08:25 ICT, before the 09:00 matching-session open, so receive, protobuf decode,
  normalized output, and changing-field validation remain NOT TESTED.
- Phase 3 remains PENDING and its unchecked acceptance items stay unchanged.
  Per the one-phase gate, Phase 4–7 live harnesses were not run from this
  pre-open attempt; they require an active stream and remain PENDING.

### 2026-09-20 — Candlestick chart follow-up

Follow-up riêng, tách khỏi Phase 20 notification durability, đúng như đã ghi
trong entry "Phase 20 sector-sync notification follow-up": "Candlestick charts
... remain the next two explicit user-requested follow-ups."

#### Kiến trúc

    RuntimeBotDataService._history()  (đã có sẵn, dùng lại nguyên vẹn)
      -> charts.candlestick.render_candlestick()  (không provider, không SQLite,
         không strategy — chỉ nhận OHLCVBar + data.indicators.ema)
      -> RuntimeBotDataService.candlestick_chart()  (acquisition boundary mới)
      -> TelegramCommandService.chart()
      -> telegram_bot/app.py: lệnh /chart + nút "📉 Biểu đồ nến"
      -> Bot.send_photo (PNG bytes qua BytesIO, không lưu file tạm trên đĩa)

`charts/candlestick.py` dùng Pillow (đã là dependency có sẵn cho OCR, không
thêm thư viện mới — không dùng matplotlib/mplfinance) với font bitmap mặc định
của Pillow để không phụ thuộc font hệ thống, đảm bảo output tái lập được trên
mọi máy.

#### Thiết kế renderer

- Input: toàn bộ lịch sử hiện có (để EMA20/EMA50 có đủ warm-up), chỉ vẽ
  `visible_count` phiên gần nhất (mặc định 90).
- Validate nghiêm ngặt trước khi vẽ: tối thiểu 5 phiên, cùng symbol, cùng
  timeframe, timestamp tăng nghiêm ngặt (strictly chronological), kích thước
  ảnh hợp lệ, chu kỳ EMA dương. Vi phạm bất kỳ điều nào ném
  `ChartRenderError` thay vì âm thầm vẽ sai.
- Panel giá (nến + EMA20/EMA50) phía trên, panel volume phía dưới, cùng trục
  x. Nến xanh/đỏ theo close so với open; wick riêng màu nhạt hơn thân nến.
- `_visible_bars()` và `_validate_bars()` là hàm thuần (pure), test độc lập
  không cần render ảnh.

#### Acquisition boundary

`RuntimeBotDataService.candlestick_chart(symbol)` dùng lại đúng `_history()`
đã có (Vietcap trước, SQLite cache sau khi provider fail) — không tạo đường
lấy dữ liệu thứ hai. Trả về `ChartRequestView` với đúng một trong hai trường
`png_bytes` hoặc `error` được điền, không bao giờ cả hai, để caller không thể
vô tình gửi ảnh cũ kèm thông báo lỗi mới.

#### Telegram

- `/chart FPT` gửi ảnh PNG kèm caption (symbol, timeframe, số phiên, giá đóng
  cửa gần nhất, nguồn dữ liệu, độ mới).
- Nút "📉 Biểu đồ nến" thêm vào keyboard hiện có của `/soi`, dùng chung
  callback prefix `soi:chart:<symbol>`.
- Lỗi (không đủ dữ liệu, chưa có lịch sử) trả về text thường, không bao giờ
  gửi ảnh hỏng.
- Không đổi ASMF/CL1, không đổi sector notification, không đổi portfolio.

#### Test — bằng chứng thật

Chạy trong sandbox không có `pytest`/`python-telegram-bot` thật (không có
mạng), dùng harness tối giản tự viết để verify logic, kèm stub `telegram`
đầy đủ cho riêng phần wiring app.py:

- `tests/test_candlestick_chart.py`: 16 passed (render hợp lệ, kích thước
  đúng yêu cầu, trim visible window đúng, EMA warm-up dùng full history, từ
  chối <5 phiên, symbol/timeframe lẫn lộn, timestamp không tuần tự, trùng
  timestamp, input rỗng, chu kỳ EMA không dương, kích thước quá nhỏ,
  visible_count dưới ngưỡng, dải giá phẳng vẫn render được).
- `tests/test_candlestick_runtime.py`: 5 passed (PNG hợp lệ + caption, lỗi
  trung thực khi không có lịch sử, lỗi trung thực khi lịch sử quá ngắn,
  fallback SQLite sau khi provider fail, không gọi provider thừa).
- `tests/test_chart_command.py`: 4 passed (`/chart` trả ảnh chứ không phải
  text, lỗi trả về text thay vì ảnh hỏng, nút inline "📉 Biểu đồ nến" hoạt
  động, nút nằm đúng trong keyboard `/soi`).
- Phát hiện và sửa: thêm `CommandHandler("chart", ...)` làm
  `tests/test_telegram_bot.py::test_application_registers_all_required_commands`
  fail vì tập lệnh kỳ vọng thiếu `"chart"`. Đã cập nhật assertion để bao gồm
  lệnh mới (bảo vệ đúng hành vi thật, không phải sửa để né lỗi) — 9 passed
  sau khi sửa.

Ảnh mẫu render từ 200 phiên dữ liệu tổng hợp (không phải dữ liệu Vietcap
thật) đã được xem trực quan để xác nhận layout đúng trước khi viết test.

#### Test — bằng chứng thật, chạy cục bộ 2026-09-20

py -3.12 -m pytest -q tests/test_candlestick_chart.py tests/test_candlestick_runtime.py tests/test_chart_command.py 25 passed in 4.87s

py -3.12 -m pytest -q tests/test_telegram_bot.py 9 passed in 1.22s

py -3.12 -m pytest -q 637 passed in 10.43s


637 = 612 (baseline trước follow-up này) + 25 test mới. Không có test nào bị
sửa để ép pass ngoài 1 assertion đã ghi ở trên (thêm "chart" vào expected
command set — bảo vệ đúng hành vi mới, không phải né lỗi).

py -3.12 -m pip check


Cùng 8 conflict pre-existing đã ghi ở entry notification durability phía
trên (`googleapis-common-protos`, `google-ai-generativelanguage`,
`google-api-core`, `grpcio-status`, `proto-plus`, `pyppeteer`, `streamlit`),
không liên quan `requirements.txt` của repo, không do follow-up này gây ra.

#### Live evidence

NOT TESTED. `/chart` chưa từng gửi ảnh thật qua Telegram Bot API; renderer đã
verify bằng dữ liệu tổng hợp, chưa verify bằng lịch sử Vietcap thật.

#### Ngoài phạm vi

BCTC/institutional flow thu thập thật vẫn là follow-up riêng, chưa đụng tới.

### 2026-09-21 — Phase 21 dynamic all-symbol news-linking follow-up

#### Problem confirmed

`TickerLinker` contained a fixed mapping for only ACB, FPT, HPG, VCB, VHM,
MWG, SSI and VND. `/sentiment` for any other ticker could not see a CafeF item
even when the article explicitly contained that ticker. This was an acquisition/
entity-linking limitation, not a PhoBERT limitation.

#### Implementation

- Replaced the fixed runtime mapping with a validated universe supplied to
  `TickerLinker`. The production ingestion command loads every active
  `STOCK`/`COMMON_STOCK` row from the main SQLite `symbols` table.
- Added `CafeFCompanyCatalogProvider` for the public
  `https://cafefnew.mediacdn.vn/Search/company.json` catalog. Only HOSE, HASTC
  (HNX), and UPCOM company paths are accepted. Full company names and safely
  simplified corporate names enrich the local ticker universe.
- Uppercase ticker codes are case-sensitive and require explicit context: start
  of a field, `mã`/`cổ phiếu`/`CP`, parentheses/hashtag, or `MÃ:`. This was
  tightened from boundary-only matching after a real batch showed false links
  for the valid tickers `USD` (currency amounts) and `CEO` (job title).
  Catalog-derived company-name aliases remain case-insensitive. Title relevance
  stays 1.0 and summary/content relevance stays 0.4.
- CafeF catalog failure falls back to code matching for the complete SQLite
  universe. An empty local and remote universe raises a clear error rather than
  silently reverting to eight symbols or ingesting unlinked sentiment.
- Duplicate URL/id rows now atomically refresh `news_tickers` links while
  preserving the existing news and inference record. This lets current RSS
  duplicates acquire mappings introduced by the new universe.
- Fixed the direct-script import boundary in `scripts/run_news_once.py`; the
  documented `py -3.12 scripts\run_news_once.py` form now adds the project root
  consistently with the other executable scripts.
- Added `NEWS_COMPANY_CATALOG_URL` to `.env.example`; the existing HTTP timeout
  applies to RSS and catalog acquisition.

#### Tests and runtime evidence

- Focused News/Sentiment suite after false-positive regression coverage:
  `13 passed in 0.67s`.
- Full isolated regression: `642 passed in 9.69s`.
- Isolated dependency check: `No broken requirements found`.
- Read-only live catalog plus the real runtime SQLite universe built a linker
  with 1,524 symbols and linked the previously unsupported `DGC` from the company
  name `Hóa chất Đức Giang`.
- End-to-end live acceptance used `DATABASE_URL=sqlite:///:memory:`,
  `NEWS_DATABASE_PATH=:memory:` and the lexicon backend to avoid production
  writes and a heavy model load. It fetched the real CafeF catalog/RSS and
  reported `ticker_universe=2230 inserted=3 duplicates=0`, exit code 0.
- A bounded production batch loaded the 1,524-symbol runtime universe and wrote
  15 new items while relinking five duplicates. The stricter rerun then relinked
  all 20 duplicates: final links were `EVF`, `FPT`, `SRF`, and `VHM`; false
  `USD`/`CEO` links were removed. The database now contains 20 items, 17 using
  PhoBERT and three retained explicit lexicon fallbacks.
- The real runtime query path for `EVF`, a symbol outside the former eight-code
  list, returned a one-article 24-hour Neutral sentiment view with explicit
  `lexicon_fallback` provenance. No Vietcap request or credential output was
  involved in that query.

#### Honest boundary

All symbols in the bot universe are now eligible for sentiment; this does not
guarantee a sentiment result for every `/sentiment <MÃ>` call. A result still
requires a CafeF RSS item that mentions the ticker or a catalog-derived company
name and a completed ingestion run. The command path remains network-free.

### 2026-09-21 — Phase 24: Automated Fundamentals & Institutional Data

#### Vấn đề giải quyết

Trước Phase 24, `financial_reports`/`bank_financial_reports`/`institutional_flows`
chỉ có dữ liệu qua nhập tay hoặc OCR thử nghiệm (ACB), không có acquisition tự
động phủ market universe. Phase 24 thêm một pipeline lấy dữ liệu tự động,
provider-independent, ghi vào đúng bảng canonical cũ — không tạo schema tài
chính song song, không tạo scoring engine thứ hai, không sửa `strategy/` hay
`asmf_data/scoring.py`.

#### Kiến trúc

    VNStockProvider ──┐
                       ├─→ ProviderChain (VNStock trước, yfinance chỉ là fallback)
    YFinanceProvider ──┘        │
                                 ▼
                     ProviderResult (AVAILABLE/PARTIAL/MISSING/STALE/ERROR
                                      + provenance + attempted[])
                                 │
                                 ▼
              refresh_financials() / refresh_institutional_flow()
                     (fundamentals/refresh_service.py)
                    ┌────────────┴────────────┐
                    ▼                          ▼
     automated_financial_statements   institutional_flows (canonical CŨ,
     (staging mới, migration v7,      qua InstitutionalFlow + upsert
      idempotent theo symbol+         cũ — không cần staging vì mỗi
      period+source)                  field đã nullable sẵn, và
                    │                  trading_date không có rủi ro
                    ▼                  look-ahead)
       [chỉ khi đủ evidence + có
        public_date thật]
       fundamentals/adapters.py
       promote_corporate_statement()
                    │
                    ▼
       financial_reports (canonical CŨ, model FinancialReport CŨ,
                           upsert_financial_reports CŨ — không đổi)
                    │
                    ▼
       asmf_data/scoring.py (KHÔNG SỬA — tự động nhận dữ liệu mới
                              vì đọc thẳng financial_reports/
                              bank_financial_reports như trước giờ)

Provider layer (`fundamentals/providers/`) là package DUY NHẤT được phép
import `vnstock`/`yfinance`. `strategy/` và `telegram_bot/` không đụng tới
2 thư viện này ở bất kỳ đâu.

#### VNStock — discovery thay vì giả định API

Sandbox lúc viết code không có mạng nên không inspect được vnstock thật lúc
đó; `VNStockProvider` được thiết kế **dò tìm API tại runtime** thay vì
hard-code một call path: thử `Vnstock().stock(symbol, source).finance.*`
với `source` lần lượt trong `("VCI", "TCBS", "MAS")`, gọi
`income_statement/balance_sheet/cash_flow` với `period=`/`lang=` rồi
fallback không tham số nếu `TypeError`, match tên cột qua bảng alias đã
normalize (tiếng Anh + tiếng Việt). Nguồn nào trả dữ liệu thật thì thắng và
được ghi lại thành `provider_source`.

**Đã xác nhận với vnstock thật, cài ở máy người dùng:**

Name: vnstock Version: 3.2.6


pytest cảnh báo có bản 4.0.8 mới hơn — **cố tình chưa nâng cấp**, vì §4.1
cấm code dựa trên API chưa inspect; giữ nguyên bản đã cài và đã chạy test
qua. Nâng lên 4.0.8 là quyết định riêng, cần inspect API mới trước khi đổi.

#### yfinance — fallback nghiêm ngặt, không đoán exchange

`candidate_tickers()` chỉ derive suffix Yahoo (`.VN`, `.HN`) từ cột
`exchange` trong bảng `symbols`. Exchange đã biết nhưng không có mapping →
trả `()` rỗng, không đoán `.VN`. Yahoo không bao giờ cung cấp `public_date`
tiếng Việt nên mọi statement từ yfinance có `public_date=None` — không được
promote vào bảng canonical. yfinance không có endpoint institutional flow
của Việt Nam → luôn trả `MISSING` cho dataset này.

**Đã xác nhận version thật:**

Name: yfinance Version: 1.0


#### Quyết định bảo thủ nhất: KHÔNG BAO GIỜ tự động promote statement ngân hàng

`fundamentals/repository.py::_standalone_quarters` de-cumulate báo cáo ngân
hàng theo quy ước **year-to-date cộng dồn** (Q2 = Q1+Q2 gộp) — đúng quy ước
Vietstock/OCR đã verify. Chưa xác nhận được vnstock trả bank data theo dạng
cộng dồn hay standalone (như Yahoo), nên `promote_bank_statement()` **luôn
trả `None`, vô điều kiện**, kể cả khi statement có đủ cả 4 field bắt buộc.
Field ngân hàng từ provider vẫn được lưu vào staging
(`automated_financial_statements`) để hiển thị coverage/provenance, nhưng
`bank_financial_reports` — và do đó điểm ASMF ngân hàng — tiếp tục chỉ đến
từ pipeline OCR/Vietstock cũ. Verify bằng test
`test_bank_score_still_comes_only_from_the_ocr_vietstock_path_never_from_
automated_staging`.

#### Point-in-time safety

- Corporate statement chỉ được promote vào `financial_reports` khi có cả 5
  điều kiện: `public_date` thật, `revenue >= 0`, `net_income_parent` hoặc
  `net_income`, `total_equity > 0`, và cả hai chân nợ ngắn/dài hạn đều có
  giá trị (thiếu một chân → không promote, không đoán bằng 0).
- `period_end_date()` tồn tại nhưng không bao giờ dùng thay `public_date` —
  khoá bằng test riêng.
- Report công bố sau ngày phân tích thì vô hình với phân tích đó.

#### Idempotency & freshness

`automated_financial_statements` PK `(symbol, period, source)`, upsert
không tạo trùng. `institutional_flows` tái dùng PK `(symbol, trading_date)`
cũ. `refresh_financials`/`refresh_institutional_flow` đọc
`symbol_data_coverage` trước khi gọi provider: nếu còn trong khoảng
`FUNDAMENTAL_REFRESH_INTERVAL`/`INSTITUTIONAL_REFRESH_INTERVAL` (mặc định 7
ngày / 1 ngày) thì `SKIPPED_FRESH`, không gọi provider. `force=True` bỏ
qua freshness check.

#### Schema — migration v7 `automated_fundamentals_coverage`

Additive, không sửa/không drop migration 1–6. `automated_financial_statements`
(staging, mọi field nullable) và `symbol_data_coverage` (trạng thái theo
symbol+dataset, `attempts` cộng dồn, `last_success_at` giữ nguyên qua các
lần lỗi sau đó). Cả hai FK tới `symbols(symbol)`; `refresh_service` tự
insert symbol mới nếu chưa có — bug thật tự phát hiện và sửa khi test với
symbol chưa từng thấy, đúng kịch bản §21 (dynamic universe).

#### ASMF regression — bằng chứng §18 quan trọng nhất

Test `test_asmf_score_is_identical_whether_data_arrives_manually_or_via_
automated_refresh`: 8 quý số liệu giống hệt nhau, path cũ (`upsert_
financial_reports` thủ công) vs path mới (`refresh_financials()`):

A manual path score: 60.0 B automated path score: 60.0


Giống hệt nhau. `asmf_data/scoring.py` không bị sửa một dòng nào.

#### Test — bằng chứng thật, chạy cục bộ 2026-09-21

Máy: Windows, `py -3.12`, `.venv` của repo, vnstock 3.2.6 + yfinance 1.0
cài thật.

py -3.12 -m pytest -q tests/test_fundamental_providers.py 47 passed, 2 warnings in 25.51s

py -3.12 -m pytest -q tests/test_fundamental_refresh.py 20 passed in 0.97s

py -3.12 -m pytest -q tests/test_point_in_time_safety.py 5 passed in 0.29s

py -3.12 -m pytest -q tests/test_migrations.py tests/test_portfolio_schema.py tests/test_sector_notification_persistence.py 26 passed in 3.44s

py -3.12 -m pytest -q 718 passed, 2 warnings in 22.57s


718 = 599 (baseline trước Phase 20) + 13 (sector notification persistence)
+ 25 (candlestick) + 98 (Phase 24: 47+20+5 file mới, cộng phần chênh từ
việc 3 file test cũ được sửa 6→7 không đổi tổng số test, chỉ đổi giá trị
assertion) — không có test nào fail, không có test nào bị sửa để né lỗi
ngoài việc bump version schema 6→7 đã ghi ở entry trước.

2 warning duy nhất: vnstock/vnai có bản mới hơn bản đang pin — không phải
lỗi, không ảnh hưởng kết quả test.

py -3.12 -m pip check


8 conflict — **giống hệt** danh sách đã ghi nhận ở entry Phase 20/candlestick
trước đó (`googleapis-common-protos`, `google-ai-generativelanguage`,
`google-api-core`, `grpcio-status`, `proto-plus`, `pyppeteer`, `streamlit`
với protobuf/urllib3/websockets). **vnstock và yfinance không phát sinh
conflict mới nào.**

#### Cấu hình

`requirements.txt` đã pin đúng version thật đã cài và test qua:

vnstock==3.2.6 yfinance==1.0


Historical note: at Phase 24 completion these keys were still deferred.
They were subsequently added/validated during Phase 25.

#### Live evidence

NOT TESTED. Toàn bộ 718 test pass đều dùng module vnstock/yfinance **giả
lập** (fake `Vnstock`/`Ticker` object trong test) để đảm bảo tính
deterministic — đây là thực hành chuẩn cho unit test, không phải hạn chế.
Nhưng **chưa có lần gọi thật nào** tới API vnstock/Yahoo qua mạng thật để
xác nhận `VNStockProvider`/`YFinanceProvider` hoạt động đúng với response
thật (cấu trúc cột, tên field thật của vnstock 3.2.6 có khớp với bảng
alias đã viết hay không). Cần một live acceptance script
(`scripts/test_phase24_live.py`, thuộc Phase 26) chạy thật với 1 symbol
thật để đóng gap này.

#### Historical state at Phase 24 completion

At the time this Phase 24 entry was written, Phase 25 and Phase 26 had not yet started.
This statement is historical only. Both phases were subsequently implemented;
see `Phase 25 & 26 — Coverage Workers, Live Acceptance & Hardening` below.

---

## Phase 25 & 26 — Coverage Workers, Live Acceptance & Hardening (2026-09-21)

Chạy liền một iteration theo uỷ quyền tường minh của người dùng (không có STOP
gate giữa hai phase). Trạng thái: **CODE + TESTS COMPLETE — chờ live validation
bên ngoài**. Lịch sử các phase trước không đổi.

### Phase 25 — kiến trúc

- `runtime/market_universe.py`: universe từ SQLite `symbols` (active, `STOCK`/`COMMON_STOCK`,
  HOSE/HSX/HNX/UPCOM hoặc exchange NULL). Lý do cho NULL: `asmf_data/vietcap_sectors.py` và cache
  lịch sử chèn `symbols` không kèm exchange, nên loại NULL sẽ làm universe rỗng trên DB thật.
  HSX được đổi thành HOSE khi gửi cho provider.
- **Migration v8 `market_coverage_datasets`**: v7 chặn `symbol_data_coverage.dataset` bằng CHECK
  (FINANCIALS/INSTITUTIONAL) mà SQLite không ALTER được → rebuild (tạo bảng mới, copy, drop, rename,
  index lại). Đây là trường hợp “schema không đủ biểu diễn” mà đề bài cho phép. v1–v7 không bị sửa.
- **Sửa runner**: `bootstrap_schema` nay chạy `BEGIN` tường minh trước mỗi migration. Trước đó DDL
  autocommit từng câu, nên migration nhiều bước lỗi giữa chừng sẽ để schema nửa vời. Đã kiểm chứng
  bằng đột biến: bỏ dòng này thì `test_v8_is_atomic_when_a_step_fails` fail.
- `fundamentals/coverage_store.py` mở rộng (additive): `record_attempt` (đường ghi duy nhất, redact
  reason), `record_attempts_bulk`, `mark_in_progress[_bulk]`, `mark_stale`, `effective_status`,
  `coverage_counts`. `record_coverage` giữ nguyên chữ ký, uỷ quyền cho `record_attempt`.
- `runtime/coverage_worker.py`: engine + worker (xem docstring đầu file). Chỉ điều phối; mọi dataset
  đi qua thành phần đã sở hữu nó. `SectorHistorySynchronizer` được thêm 2 phương thức công khai
  (`fetch_history`, `refresh_symbol_history`); `_fetch_with_retry` giữ hành vi cũ (6 test sector pass).
- `runtime/news_refresh.py` + `SQLiteNewsRepository.ticker_article_counts`: news chạy định kỳ, model
  sentiment dựng đúng 1 lần/process, kết nối SQLite tạo trong thread worker (sqlite3 gắn với thread).
- `runtime/coverage_config.py` (validate env), `coverage_factory.py` (dựng từ env, gắn listener sector),
  `coverage_report.py`, `redaction.py`, `acceptance.py`.
- Cấu hình thật sự được đọc: `COVERAGE_WORKER_ENABLED, COVERAGE_DATASETS, COVERAGE_BATCH_SIZE (20),
  COVERAGE_WORKER_INTERVAL (600), COVERAGE_STARTUP_DELAY, COVERAGE_REQUEST_DELAY, COVERAGE_MAX_RETRIES,
  COVERAGE_RETRY_BACKOFF, COVERAGE_ERROR_COOLDOWN, COVERAGE_MISSING_COOLDOWN, COVERAGE_SECTOR_REQUESTS_PER_CYCLE,
  FUNDAMENTAL_REFRESH_INTERVAL, INSTITUTIONAL_REFRESH_INTERVAL, MARKET_HISTORY_REFRESH_INTERVAL,
  NEWS_REFRESH_INTERVAL, NEWS_INGEST_LIMIT, VNSTOCK_SOURCE_PREFERENCE, YFINANCE_ENABLED`
  (`FUNDAMENTAL_PRIMARY_PROVIDER` không được thêm vì không có mã nào đọc nó). Test đảm bảo mọi key
  trong `.env.example` đều được đọc. Mặc định 20 mã/600s ≈ 2.900 lượt/ngày, đủ giữ ~1.500 mã fresh.
- Vòng đời: `scripts/run_telegram_bot.py` gọi `start_coverage_worker_from_env(sector_worker)` (chỉ spawn
  thread, chu kỳ đầu sau `COVERAGE_STARTUP_DELAY`), và dừng worker trong `finally`.
- Rate limit/backoff: delay giữa call, backoff mũ khi ERROR, dừng retry khi thấy 429, circuit breaker
  3 lỗi liên tiếp/dataset/chu kỳ, cooldown MISSING/ERROR liên chu kỳ.
- **Phát hiện live**: `vnstock` 3.2.6 nuốt lỗi mạng (log ERROR rồi trả rỗng) nên adapter trả MISSING
  khi mạng bị chặn. Vì vậy cooldown MISSING mặc định chỉ 3 ngày (cấu hình được) thay vì cả 7 ngày,
  để sự cố ngắn không thành mất dữ liệu cả tuần.
- Scripts: `sync_fundamentals.py`, `sync_institutional_flow.py`, `sync_market_coverage.py`,
  `coverage_report.py`, dùng chung `scripts/coverage_cli.py` → cùng engine với worker.

  ### Scanner architecture gap

Current Phase 25 coverage orchestration maintains dataset coverage.
It does not make `/scan` a full-market asynchronous scanner.

Target:

SQLite symbol universe
→ background history/liquidity pre-screen
→ CL1/ASMF evaluation
→ persisted scan snapshot
→ `/scan` reads snapshot only

### Phase 26 — hardening

- `telegram_bot/app.py`: lỗi `reply_photo` nay có fallback text (trước đó không bắt); error handler
  toàn cục; tất cả log qua `redact_secrets`. `configure_logging()` ép `httpx`/`httpcore` về WARNING
  (URL Telegram chứa token) và gắn `SecretRedactingFilter`; bot trước đó không cấu hình logging.
- Điều chưa đổi (ghi nhận): `/soi`, `/chart` vẫn gọi Vietcap đồng bộ qua `_history()` — hành vi cũ,
  không nằm trong danh sách cấm (VNStock/Yahoo/CafeF/full-market).
- `fundamentals/providers/vnstock_provider.py`: thêm fallback `vnstock.api.financial.Finance` cho
  vnstock 4.x (phát hiện khi cài 4.0.8: không còn `Vnstock`/`Finance` cấp cao). Path 3.2.6 (pin trong
  requirements) không đổi. Parse dữ liệu thật của 4.x chưa xác minh.
- Live harness: `scripts/test_phase24_live.py`, `scripts/test_phase26_telegram_live.py`; logic ở
  `runtime/acceptance.py` (test offline). Probe host để phân biệt bị chặn với không có dữ liệu.

### Bằng chứng kiểm thử (chạy thật)

- Full regression: **830 passed** (`python -m pytest -q`, Python 3.12.3, venv cách ly). Baseline 718.
  File mới: universe 6, coverage states 14, coverage worker 34, config/report/CLI 16, phase26 hardening 26,
  phase26 acceptance 15, +1 test vnstock 4.x trong `test_fundamental_providers.py`.
- Test cũ không bị sửa expected; chỉ 3 test pin schema version 7→8 (`test_migrations.py`,
  `test_portfolio_schema.py`, `test_sector_notification_persistence.py`) và thêm tên migration v8.
- `pip check` (venv cách ly, vnstock==3.2.6, yfinance==1.0, không có torch/transformers): “No broken
  requirements found”. Đây KHÔNG phải môi trường đầy đủ của dự án; không kết luận gì về 8 conflict cũ
  của môi trường chung.
- Môi trường dev mô phỏng bị chặn egress: `x-deny-reason: host_not_allowed` cho Yahoo, Vietcap, CafeF.

### Live results

| Check | Kết quả |
|---|---|
| VNStock fetch thật | NOT TESTED (host bị chặn; vnstock 3.2.6 trả rỗng) |
| yfinance fallback thật | NOT TESTED |
| Live promotion-safety | NOT TESTED |
| `/soi` `/market` `/sentiment` trong phiên | NOT TESTED (cũng cần phiên giao dịch mở) |
| `/chart` Vietcap → PNG → Telegram | NOT TESTED |
| Worker thread thật + vnstock thật, mạng chặn | Smoke: 1 chu kỳ, MISSING, dừng sạch, không crash |

### Blocker còn lại

Chỉ là blocker bên ngoài: cần mạng tới VNStock/Yahoo/Vietcap/CafeF/Telegram, credential Vietcap,
`TEST_TELEGRAM_CHAT_ID`, và phiên giao dịch mở cho acceptance của Phase 22. Chạy
`scripts/test_phase24_live.py` và `scripts/test_phase26_telegram_live.py --send` trên máy có mạng.

---

## 2026-09-21 — Phase 24 live-provider compatibility follow-up

### Confirmed failure

- The installed `vnstock==3.2.6` VCI financial path timed out after 30 seconds
  against `trading.vietcap.com.vn`; its TCBS financial endpoints returned HTTP
  404 for FPT and ACB. The old adapter therefore returned MISSING.
- yfinance remained healthy and returned real FPT.VN rows, but that could not
  satisfy the separate VNStock acceptance criterion.
- VNStock 4.0.8 changed the usable community-edition source set to KBS/VCI and
  KBS returned real data in a semantic wide layout: `item`, `item_id`, then
  columns such as `2026-Q2`, `2026-Q1`, `2025-Q4`, and `2025-Q3`.

### Implementation

- `requirements.txt` now pins `vnstock==4.0.8`.
- `VNStockProvider` defaults to `KBS,VCI`, tries one source end-to-end before
  constructing the next source, and prefers the non-deprecated top-level
  `Finance` adapter when available.
- Added an evidence-backed semantic-ID map for the canonical statement fields
  and a wide-to-period normalizer. Unknown IDs remain ignored; no Vietnamese
  label is guessed.
- Importing VNStock now defaults `VNSTOCK_DISABLE_AGENT_SETUP=1` so a data
  provider cannot write project/global assistant configuration as a side effect.
- Provider diagnostics retain source/operation/exception type without exposing
  request payloads or secrets.
- The live promotion harness now maps refresh `SUCCESS` to provider
  `AVAILABLE`; previously a successful staged refresh was mislabeled
  INCONCLUSIVE even when rows existed and safety checks had no violations.
- `.env.example` now documents `VNSTOCK_SOURCE_PREFERENCE=KBS,VCI`.

### Verification

- Focused Phase 24/26 tests: `91 passed`.
- Full regression with VNStock 4.0.8, vnai 2.6.0 and resolved transitive
  dependencies on Python 3.12: `833 passed`.
- `pip check` after resolving the VNStock dependency set showed no new VNStock
  conflict. The same eight pre-existing shared-environment conflicts remain
  (protobuf consumers, pyppeteer urllib3/websockets, and streamlit protobuf).
- Bounded live acceptance on a temporary SQLite database:
  - VNStock/KBS FPT: AVAILABLE, 4 rows, 2026Q2 through 2025Q3.
  - VNStock/KBS ACB: PARTIAL, 4 rows, 2026Q2 through 2025Q3.
  - yfinance FPT.VN: PARTIAL, 9 rows.
  - Promotion safety: PASS; rows without `public_date` were staged but not
    promoted, and the bank canonical table remained untouched.
  - Final harness verdict: `Phase 24 live acceptance: PASS`.

### Remaining external validation

Phase 24 is closed. Phase 22 active-session Telegram commands and the Phase 25
coverage worker inside the real bot process remain NOT TESTED; this follow-up did
not broaden into either task.
### Ticker sentiment target semantics

Ticker sentiment should no longer be defined by a strict 24-hour window.

Target:
- select the newest up-to-5 relevant articles;
- exclude articles older than `SENTIMENT_MAX_AGE_DAYS` (default 30);
- then apply the existing relevance/time-decay aggregation;
- `/tin`, `/sentiment`, `/soi` should use the same selected set;
- zero eligible articles = MISSING, never synthetic Neutral;
- severe-negative ASMF blocker retains its own stricter recency requirement.
### Market Context & Sector Performance Chart (Bối cảnh thị trường nâng cao)

Matching the team leader's specification and visual dashboard:

1. **Text Market Overview (/market)**:
   - Header: 🌐 BỐI CẢNH THỊ TRƯỜNG
   - VN-Index score, percentage change, and trend direction icon (📈 TĂNG / 📉 GIẢM / ➡️ ĐI NGANG).
   - Quantitative Metrics:
     - **Số mũ Hurst (H)**: calculated on the last 100 sessions (<= 101 closes) using standard rescaled range analysis (H > 0.55: quán tính xu hướng, H < 0.45: hồi quy trung bình, 0.45 <= H <= 0.55: dao động ngẫu nhiên).
     - **Phân vị biến động (Volatility Percentile %)**: 20-session rolling realized volatility ranked against past 100 sessions.
     - **Trạng thái MA50 & MA200**: Evaluates whether index stands above MA50 and MA200 ('Chỉ số chưa đứng vững trên cả MA50 và MA200 -> xu hướng chưa chắc chắn.').
   - Sector Performance Ranking:
     - Top 3 strongest sectors and weakest sector with score.
   - Preserves REGIME:, BREADTH:, LIQUIDITY:, and data quality sections for complete test compatibility.
   - Interactive navigation prompt: 👉 Chọn một mục bên dưới để xem chi tiết: with inline button 📊 Top % biến động ngành.

2. **Top % Sector Performance Chart (charts/sector_chart.py / /chart MARKET / callback soi:mchart:VNINDEX)**:
   - Title: TOP % BIẾN ĐỘNG NGÀNH with subtitle NGÀY: DD-MM-YYYY HH:MM.
   - Y-axis: BIẾN ĐỘNG LŨY KẾ (%), X-axis: 20 phiên gần nhất with DD/MM date ticks.
   - Dotted zero baseline.
   - Equal-weight sector index across members: cumulative % return from T0.
   - Legend formatted with sector name, latest session turnover in billion VND, and cumulative return (+X.XX%).
   - Rendered using headless Matplotlib (Agg), verified PNG magic bytes.


---

## 2026-09-22 — Live Acceptance Fix Round (Phase 28), Issues 1–4

### Context

Live testing of the real bot process (`py -3.12 -m scripts.run_telegram_bot`)
found that several items previously logged as "Resolved" in the 2026-09-21
Current Operational Status section were code-complete but had never actually
been exercised end-to-end in production, and in fact did not work live. This
round fixes issues one at a time, stopping for explicit live confirmation
after each before starting the next (see `TASKS.md` Phase 28 for the full
issue list and status).

### Issue 1 — `/scan` returned 2/2 instead of the full market

- Confirmed live: `/scan` returned only FPT/ACB (`2/2`) while the coverage
  worker log showed `universe=1524`.
- Fixed and live-confirmed 2026-09-22: `/scan` now reflects the full
  HOSE/HNX/UPCoM universe (`universe=1524`), no longer limited to
  `BOT_WATCH_SYMBOLS`.

### Issue 2 — Realtime breadth missing from `/market` and `/soi`

**Root cause (three independent gaps, all in production wiring, not in the
already-correct breadth-computation logic):**

1. `runtime.bot_service.build_runtime_service_from_env()` — the factory used
   by `scripts/run_telegram_bot.py` — never passed `index_state=` into
   `RuntimeBotDataService`, so `self.index_state` was always `None` regardless
   of anything else.
2. The Vietcap realtime index socket pipeline (`VietcapRealtimeClient` +
   `IndexStatePipeline` + `LatestIndexState`, from `data/vietcap/`) worked
   correctly but had only ever been exercised standalone by
   `scripts/test_realtime_index.py`; no background worker started it inside
   `scripts/run_telegram_bot.py`, unlike the scanner/coverage workers.
3. `RuntimeBotDataService.stock_analysis()` (backing `/soi`) called
   `build_market_view(benchmark)` without ever passing `breadth`/`liquidity`,
   even where `market_overview()` (`/market`) already had that logic — so
   `/soi` structurally could not share `/market`'s breadth state.

**Implementation:**

- Added `runtime/index_stream_worker.py`: `IndexStreamWorker`, a bounded
  daemon-thread worker following the same start/stop pattern as
  `MarketScannerWorker`/`MarketCoverageWorker`. Connects via
  `VietcapRealtimeClient`, subscribes VNINDEX, feeds a shared
  `LatestIndexState` through `IndexStatePipeline`. Retries the initial connect
  with exponential backoff (capped) on failure without busy-looping or
  blocking Telegram polling; `VietcapRealtimeClient`'s own bounded Socket.IO
  reconnection policy handles drops within an established session.
  `INDEX_STREAM_WORKER_ENABLED` env flag to disable (offline/dev).
- `build_runtime_service_from_env()` now constructs a `LatestIndexState()` and
  passes it as `index_state=`.
- `scripts/run_telegram_bot.py` starts/stops `index_stream_worker` alongside
  the scanner/coverage/sector workers.
- Extracted `RuntimeBotDataService._index_breadth_liquidity()` and reused it in
  both `market_overview()` and `stock_analysis()`, so `/market` and `/soi` now
  read the same live breadth/liquidity state.
- When the feed is down or hasn't produced a VNINDEX snapshot yet, both
  commands fall back to the existing "unavailable"/EMA-only presentation — no
  EOD data is ever mislabeled as realtime.

**Verification:**

- New `tests/test_index_stream_worker.py` (6 tests): first-connect population,
  retry after failed initial connect, no busy-loop on repeated failures,
  `stop()` before `start()` is a no-op, `INDEX_STREAM_WORKER_ENABLED=false`
  disables the worker, rejects a non-`LatestIndexState` state.
- Extended `tests/test_runtime_bot.py` (+4 tests): `/market` reports
  unavailable breadth without `index_state`; `/market` renders breadth and
  liquidity strings correctly from a fake snapshot; `/soi`'s
  `StockAnalysisView.market.breadth` matches what `/market` renders from the
  same state; `/soi` has no breadth when `index_state` is absent.
- Full regression: **866 passed** (`python -m pytest tests/ -q`), no
  regressions in Issue 1 (`/scan`), `/chart`, market regime, or Telegram
  command tests.
- Live (2026-09-22, trading session): bot log showed
  `Realtime index stream worker started` →
  `Vietcap realtime index stream connected symbols=('VNINDEX',)`. `/market`
  showed `BREADTH: 143 tăng (3 trần) / 148 giảm (7 sàn) / 64 tham chiếu` and
  `Regime: BULL (xu hướng EMA + breadth ...)`. `/soi HPG`, read seconds later,
  showed the same live breadth shape (`141 tăng (3 trần) / 149 giảm (7 sàn) /
  65 tham chiếu` — the small drift between the two reads is expected: both are
  genuinely realtime against the same shared, continuously-updating
  `index_state`, not a frozen duplicate).

**Known follow-up (out of scope for Issue 2, left for Issue 3):** live output
showed `LIQUIDITY: 0 tỷ (301,778,416 CP)` — the traded volume looks
plausible but the traded value renders as zero. Suspected unit or field
mismatch in the realtime index event's `total_value` field. Not investigated
or changed as part of Issue 2; flagged for the Issue 3 (market-wide liquidity)
audit.

### Issue 3 — Market-wide liquidity unavailable

**Root cause:** not a missing data source (the plausibility guard added
alongside Issue 2 was working correctly and flagging a real problem). The
Vietcap realtime index stream's `totalValue` field is denominated in
**triệu đồng** (millions of VND), not raw VND as `normalize_index()` assumed.
Live evidence (debug capture, same session as Issue 2): a snapshot reported
`totalValue=9,926,135.61` alongside `totalShares=409,881,936`. Read as raw
VND this implies an average matched price of ~0.02 VND/share (impossible for
any VN equity), which is exactly why
`runtime.bot_service._is_plausible_market_liquidity()` rejected it and
rendered `LIQUIDITY: unavailable` (and, right after Issue 2 landed,
`LIQUIDITY: 0 tỷ` for a near-zero `total_value`). Scaled by 1e6 the same
numbers imply ~24,220 VND/share (a plausible VN equity price) and ~9,926 tỷ
VND total market turnover — consistent with a real mid-afternoon HOSE
session before ATC. `totalShares` has no equivalent mismatch (409M matched
shares is plausible on its own), so only `totalValue` needed scaling.

**Implementation:**

- Added `VIETCAP_INDEX_TOTAL_VALUE_UNIT_SCALE = 1_000_000.0` in
  `data/vietcap/normalizer.py`; `normalize_index()` now multiplies the wire
  `totalValue` by this constant when building `IndexSnapshot.total_value`,
  so every downstream consumer sees VND consistently.
- No change to `runtime/bot_service.py`: its plausibility bounds
  (`MIN/MAX_PLAUSIBLE_AVERAGE_PRICE_VND`) and the `/1e9` "tỷ" formatting
  already assumed VND input and were already correct once the input is
  actually VND. Confirmed by grep that `runtime/bot_service.py` is the only
  non-test consumer of `IndexSnapshot.total_value`, so there was no
  double-scaling risk elsewhere.
- Did not touch `/chart`, the plausibility bounds themselves, or ASMF/CL1
  scoring — out of scope for this issue.

**Verification:**

- Updated `tests/test_index_stream.py::test_normalize_index_maps_to_index_snapshot`
  for the new scaled expectation.
- Added `test_normalize_index_scales_total_value_from_trieu_dong_to_vnd`:
  reproduces the exact live `totalValue`/`totalShares` pair from the debug
  capture and asserts the resulting implied average price falls back within
  `_is_plausible_market_liquidity()`'s bounds.
- Full regression: **870/870 passed** (`python -m pytest -q`, user-run) —
  no regressions in Issue 1 (`/scan`), Issue 2 (breadth), `/chart`, or market
  regime tests.
- Live (2026-09-22): `/market` showed
  `LIQUIDITY: 11,103 tỷ (458,208,014 CP)` — implied average price ≈24,230
  VND/share (plausible), no more `unavailable`/`0 tỷ`, and the "Chưa khả
  dụng" list no longer includes liquidity. No more "total_value looks
  implausible" WARNING under normal market conditions.

### Issue 4 — Foreign/proprietary flow unavailable

**Root cause (two independent things, not one):**

1. `/market`'s market-wide `DÒNG TIỀN NGOẠI/TỰ DOANH` was always
   "unavailable" because nothing ever passed `foreign_flow=` into
   `build_market_view()` — but unlike Issues 2/3, this is not dead wiring:
   there is genuinely **no market-wide data source anywhere in the repo**.
   Vietcap's `IndexMessage` wire schema has no foreign/proprietary field
   (only `MatchPriceMessage`, at per-symbol level, has
   `foreignBuyValue`/`foreignSellValue`), and no aggregate table or query
   exists. This is **BLOCKED BY DATA SOURCE**, not a bug — "unavailable"
   stays, correctly.
2. Per-symbol `INSTITUTIONAL` coverage (e.g. ACB) showed
   `provider=yfinance reason=no provider in the chain had data`, which
   falsely implied yfinance was relied upon for Vietnamese institutional
   flow. Audited: `YFinanceProvider.fetch_institutional_flow()` already
   honestly declines with `"Yahoo does not publish Vietnamese institutional
   flow"` and never fabricates data; `VNStockProvider.fetch_institutional_flow()`
   is already the correct layer (tries `trading.foreign_trade`,
   `trading.prop_trade`, `quote.foreign_trade` across VCI/TCBS sources) and
   needed no new implementation. The actual bug was in
   `ProviderChain._run()`: when every provider in the chain returned
   MISSING, it attributed the result to `self._providers[-1].name`
   (yfinance) instead of honestly reflecting that no provider — including
   the authoritative one — had data.

**Implementation:**

- Fixed `fundamentals/providers/provider_chain.py`: the all-MISSING fallback
  now returns `provider="none"` with
  `error_reason="no provider had data (attempted: ...)"`, listing every
  provider actually tried. Shared by `FINANCIALS` and `INSTITUTIONAL`
  (same underlying `_run()`), but only this specific mislabeling branch
  changed — no other behavior touched.
- Confirmed (no change needed): `FlowRow`/`InstitutionalFlow` already track
  `foreign_buy_value`/`foreign_sell_value` and
  `proprietary_buy_value`/`proprietary_sell_value` as fully independent
  nullable fields (`has_foreign`/`has_proprietary` properties keep "no
  proprietary desk data" from collapsing into "proprietary flow was zero").
  "Ownership" data has no representation anywhere in the repo, so there was
  no three-way conflation to fix.

**Verification:**

- Extended `tests/test_fundamental_providers.py::test_chain_missing_when_every_provider_is_missing`
  and added `test_chain_missing_institutional_flow_does_not_blame_yfinance`,
  reproducing the exact ACB scenario.
- Full regression: **872/872 passed** (`python -m pytest tests/ -q`,
  user-run).
- Live (2026-09-22): `py -3.12 -m scripts.sync_institutional_flow --symbol
  ACB --force` → `provider=none status=MISSING reason=no provider had data
  (attempted: VNStock:MISSING, yfinance:MISSING)`;
  `py -3.12 -m scripts.coverage_report --symbol ACB` confirms the same
  corrected labeling persisted. This live run also confirms VNStock 3.2.6
  genuinely has no institutional-flow data for ACB right now — the chain is
  now honest about it, but the symbol is still functionally MISSING (a data
  availability fact, not a code defect).

**Researched, not implemented:** DNSE OpenAPI (`dnse-sdk-openapi`,
`openapi.dnse.com.vn`) documents a `foreign_investor` WebSocket topic
(realtime, per-instrument foreign investor trading data) as a possible
future additional source for the foreign leg. No equivalent
proprietary/tự doanh topic was found in the same official SDK docs.
Integrating a new provider (API key/secret registration, adapter, request
signing) is a materially larger scope than this issue and was not started;
would need its own issue/phase if pursued. DNSE's older "LightSpeed API"
docs (hdsd.dnse.com.vn) list a narrower topic set with no foreign-investor
topic visible in what was checked — the two DNSE doc surfaces were not
fully reconciled; confirm directly with DNSE before integrating.

### Issue 5 — News ingestion không phủ đủ theo ticker

**Root cause:** `NewsIngestionService.run_once()` (the only ingestion path
that existed) samples a single generic CafeF market-wide RSS feed, bounded
to `NEWS_INGEST_LIMIT` (default 30 items), on the periodic coverage
worker's cadence. Against a ~1,524-symbol universe that sweep only links a
handful of tickers by chance (live evidence: `linked_tickers=12`), which is
why most symbols (HC1, VIC, ACB, ...) showed `NEWS MISSING` even when CafeF
had a relevant article somewhere on the site: there was no on-demand,
per-ticker refresh path for `/tin`/`/sentiment` to fall back on.

**Implementation (hybrid A + B, as specified):**

- **A. Generic ingestion** — unchanged: the existing periodic
  `NewsRefreshRunner`/coverage-worker sweep.
- **B. Targeted on-demand refresh** — new
  `runtime/news_refresh.py::TargetedNewsRefreshWorker`, mirroring
  `SectorHistorySyncWorker`'s already-proven shape: one bounded daemon
  thread, an in-process queue, and per-symbol in-flight/cooldown dedup
  (`request(symbol) -> bool`, never blocks, never raises for a normal
  duplicate call). It reuses the existing CafeF RSS → ticker-link (ticker
  code + company name + aliases, via the existing `build_ticker_linker`) →
  sentiment → SQLite pipeline with a larger, bounded on-demand fetch limit
  (`NEWS_TARGETED_FETCH_LIMIT`, default 60) rather than a new provider.
  `NEWS_TARGETED_COOLDOWN_SECONDS` (default 300) bounds re-fetch rate per
  symbol so repeated/concurrent Telegram queries for the same under-covered
  ticker do not pile up duplicate CafeF fetches.
- Wired into `RuntimeBotDataService` as `news_refresh_requester` /
  `set_news_refresh_requester()` (mirrors `sector_history_requester`).
  `latest_news()` (`/tin`) and `_sentiment_view()` (`/soi`, `/sentiment`)
  enqueue a refresh, non-blocking, only when the ticker currently has zero
  eligible articles; the existing MISSING/unavailable message is still
  shown honestly, with a short queued/cooldown note appended — this never
  claims news exists before it actually does. `market_overview()`'s
  internal `VNINDEX` sentiment lookup is excluded (not a listed ticker).
- Started/stopped in `scripts/run_telegram_bot.py` alongside the sector,
  coverage, scanner, and index-stream workers.
- **Regression caught before shipping:** a second, independently threaded
  runner would otherwise have loaded a second PhoBERT model into memory.
  Added `intelligence/news/sentiment.py::get_shared_sentiment_model()` (a
  process-wide singleton) and switched `build_news_runner_from_env()`'s
  `sentiment_factory` to it, so the periodic and the new on-demand runner
  now share one model instance instead of two.
- **Not implemented:** the "CafeF ticker-page fallback" mentioned in the
  original ask. No existing, verified per-ticker CafeF search/page endpoint
  was found in this repo, and this environment has no live network access
  to verify one safely — an unverified scraper risks silently returning
  wrong data or breaking on the next CafeF markup change, which is worse
  than the current honest MISSING. Reported as researched-not-implemented,
  consistent with how Issues 3 and 4 treated an unavailable/unverifiable
  data source.

**Verification:**

- New `tests/test_news_refresh_worker.py` (8 tests): invalid
  `fetch_limit`/`cooldown_seconds` rejected, `stop()` before `start()` is a
  no-op, `request()` after `stop()` is rejected, blank symbol rejected,
  in-flight/cooldown dedup (mirrors the sector-worker blocking test),
  refresh persists via the existing pipeline and reports
  `articles_found`/`inserted`, the configured `fetch_limit` reaches the
  provider, and the sentiment model is built at most once across two
  different symbols' refreshes.
- New test in `tests/test_news_pipeline_service.py` for the shared-model
  singleton contract.
- Extended `tests/test_runtime_bot.py` (+8 tests): `/tin` enqueues on
  MISSING and reports the queued note; cooldown reported without
  re-enqueuing; no enqueue when articles already exist; `/sentiment`
  enqueues on MISSING; `VNINDEX` (market-wide) never enqueues; a requester
  exception is reported in the message instead of raising;
  `set_news_refresh_requester()` attaches correctly after construction.
- This sandbox has no `pytest`, `transformers`, or live network access, so
  the new/extended tests above (17 total) plus every pre-existing test in
  `tests/test_runtime_bot.py` (24) and `tests/test_sector_history_sync.py`
  (6) — the two suites most exposed to this change — were run with a small
  ad-hoc runner reproducing pytest's `tmp_path`/`monkeypatch`/
  `pytest.raises` fixtures: **47/47 passed**, no regressions. The full
  `python -m pytest tests/ -q` still needs to be run by the user in their
  actual environment, as with every prior Phase 28 issue, before this is
  marked PASS.
- Live acceptance (pending): `/tin HC1` and `/sentiment HC1` (or another
  currently-MISSING symbol) should show the existing MISSING message plus a
  "Đã xếp HC1 vào hàng đợi làm mới tin nền." note on first ask, the bot log
  should show `targeted news refresh finished symbol=HC1 ...`, and a
  second `/tin HC1` a few seconds later should show the same MISSING
  message (not a false "cooldown" bug) unless CafeF's current front feed
  actually carried an HC1-relevant article in that window — this is
  expected: the on-demand refresh widens the sampled window, it does not
  guarantee an article exists right now.

### Issue 9 — Fundamental data PARTIAL/MISSING & ASMF Point-in-Time fallback

**Problem:**
ASMF Tầng 2 requires financial statements to be queryable point-in-time (`public_date <= as_of`) to prevent look-ahead bias. The implementation in Phase 26 introduced a hard rejection in `corporate_promotion_gap` for any provider statement lacking an actual `public_date` (`if row.public_date is None: return "no public_date established by provider"`). As a consequence, providers without formal announcement dates (e.g. TCBS, VNStock wide format, and yfinance) had all their financial statements trapped in staging table `automated_financial_statements` without promotion to `financial_reports`, leaving ASMF fundamental scoring BLOCKED.

**Strategy Resolution:**
The strategy document does NOT mandate an actual provider `public_date`. The canonical rule is:
1. Actual `public_date` present -> use actual (`public_date_source="actual"`).
2. Actual `public_date` absent but valid `report_period` exists -> estimate `public_date = period_end_date(report_period) + 45 days` (`public_date_source="estimated_45d"`).
3. Strictly forbid using `period_end_date` directly as `public_date` (avoids look-ahead bias).
4. Forbid date fabrication outside the defined +45 days rule.
5. If neither `public_date` nor `report_period` can be established -> reject statement record.
6. ASMF query constraint remains untouched: `public_date <= as_of`.
7. Tertiary source preference extended to include TCBS: `DEFAULT_SOURCE_PREFERENCE = ("KBS", "VCI", "TCBS")`.

**Implementation:**
- `fundamentals/providers/base.py`:
  - Defined `DEFAULT_FS_PUBLISH_LAG_DAYS = 45`.
  - Added `estimate_publication_date(period, lag_days=45)`.
  - Added `public_date_source: str | None = None` and property `effective_public_date` to `StatementRow`.
  - Relaxed `StatementRow.__post_init__` period string check to allow unparsable rows to reach promotion gap checks.
- `asmf_data/models.py`:
  - Added `public_date_source: str = "actual"` to `FinancialReport`.
- `fundamentals/adapters.py`:
  - Implemented `resolve_public_date(row, lag_days=45)`.
  - Updated `corporate_promotion_gap` and `promote_corporate_statement` to resolve effective publication date and reject only if neither actual nor period-derived date is available.
- `fundamentals/coverage_store.py`:
  - Staged statements record `effective_date` in `public_date`.
- `fundamentals/providers/vnstock_provider.py`:
  - Added `"TCBS"` to `DEFAULT_SOURCE_PREFERENCE = ("KBS", "VCI", "TCBS")`.

**8-Quarter Requirement Audit:**
- `fundamental_score` in `asmf_data/scoring.py` strictly requires at least 8 quarters of point-in-time financial reports (`len(reports) < 8: return None`) to calculate YoY growth metrics (4 quarters current vs 4 quarters previous year).
- With the +45d fallback, symbols with 8 quarters available from TCBS/yfinance are now fully unblocked (verified score = 80.0-100.0).
- Symbols with fewer than 8 quarters will still return `None` as intended by strategy design (not diluted).

**Verification:**
- Full unit test suite covering requirements A through F:
  - A: Actual `public_date` preserved.
  - B: Missing actual date -> fallback to `period_end_date + 45 days`.
  - C: Neither available -> rejected.
  - D & E: Strict point-in-time boundaries: invisible prior to `period_end_date + 45d`, visible on/after.
  - F: 8 quarters from TCBS enables fundamental score calculation.
- Live verification script `scripts/test_issue9_live.py` passed 100%.
- Full regression suite: **899/899 passed**.

### Issue 10 — Coverage semantics chưa đồng nhất với ASMF readiness

**Problem:**
Coverage tracking (`symbol_data_coverage`) was reporting `PARTIAL` with diagnostic `BLOCKED BY DATA SOURCE` even when the canonical SQLite tables (`financial_reports` or `bank_financial_reports`) held $\ge 8$ point-in-time quarters. This occurred because `refresh_financials` and `refresh_institutional_flow` mirrored the ephemeral raw provider outcome (e.g. 8 of 9 periods promoted, 1 period discarded due to missing revenue) instead of assessing actual data readiness for strategy layers. Consequently, ASMF Tầng 2 was fully operational and computing scores, but operational tooling and `/coverage` falsely reported the stock as data-blocked. Similarly, `_refresh_market_history` evaluated daily history against 126 bars (sector requirement) instead of 200 bars (`MINIMUM_STRATEGY_HISTORY`), which is required for ASMF and CL1 strategy execution.

**Strategy Resolution:**
1. **FINANCIALS**: If canonical `financial_reports` (or `bank_financial_reports`) contains $\ge 8$ point-in-time quarters (`public_date <= as_of`), the dataset coverage status is marked `READY`. The reason string accurately documents strategy readiness: `"READY FOR ASMF ({canonical_count} quarters available); {promoted}/{total} raw period(s) promoted..."` instead of `"BLOCKED BY DATA SOURCE"`. If canonical quarters are between 1 and 7, coverage is `PARTIAL` (`BLOCKED BY DATA SOURCE`). If 0, coverage is `MISSING`.
2. **MARKET_HISTORY**: Defined `MINIMUM_STRATEGY_HISTORY = 200` bars. When bars are below 200, reason explicitly states: `"short history: {count} of {minimum} daily bars; need {minimum} for ASMF/CL1"`.
3. **INSTITUTIONAL**: If canonical `institutional_flows` contains $\ge 5$ trading sessions, coverage status is `READY`.
4. The strict 8-quarter requirement in `fundamental_score` and 200-bar history requirement for strategy execution are preserved without dilution.

**Implementation:**
- `fundamentals/refresh_service.py`:
  - Added `_count_canonical_financial_reports` and `_count_canonical_institutional_flows`.
  - Added `_point_in_time_gap_reason` helper to emit `"READY FOR ASMF ({count} quarters available)..."` when canonical requirements are met.
  - Reconciled `refresh_financials` and `refresh_institutional_flow` status determination with canonical readiness.
- `runtime/coverage_worker.py`:
  - Defined `MINIMUM_STRATEGY_HISTORY = 200`.
  - Added `strategy_minimum_bars: int = MINIMUM_STRATEGY_HISTORY` to `HistoryClient`.
  - Updated `_refresh_market_history` threshold and reason message.
- `tests/coverage_fakes.py`:
  - Updated `FakeHistory` with `strategy_minimum_bars = 200`.
- `data/database.py` & `tests/test_phase26_hardening.py`:
  - Improved SQLite busy timeout handling for high-concurrency test environments on Windows.

**Verification:**
- Unit tests:
  - `tests/test_fundamental_refresh.py`: verified 8 quarters yields `READY` despite provider partial result; fewer than 8 quarters yields `PARTIAL`; 5 flow sessions yields `READY`.
  - `tests/test_coverage_worker.py`: verified market history 200-bar threshold and reason string.
- Full regression: **902/902 passed in 66.69s** (100% green).
- Live verification:
  - Ran `scripts/test_issue10_live.py` against live database with FPT and VIC. FPT has 8 canonical quarters, coverage `READY`, reason `READY FOR ASMF (8 quarters available); 8/9 raw period(s) promoted - no usable revenue value (1 period(s))`, ASMF score `60.0`.
  - Verified `scripts/coverage_report.py --symbol FPT` outputs `FINANCIALS READY`.

### 2026-09-23 — Financial Data Integrity & ASMF Readiness (Issue 1)

**Root causes confirmed:**

1. `YFinanceProvider._collect()` merged annual `financials`, `balance_sheet`, and
   `cashflow` frames with quarterly frames. A 31 December annual column was
   normalized to `YYYYQ4`, so annual revenue could overwrite or masquerade as a
   quarterly result.
2. `refresh_financials()` treated `COUNT(DISTINCT report_period) >= 8` as ASMF
   readiness. Eight rows with a missing quarter were incorrectly `READY`.
3. `fundamental_score()` and `fundamentals.repository._corporate_facts()` split
   `reports[:8]` into current/previous groups without checking quarter arithmetic.
4. `/soi` could therefore display TTM growth from a discontinuous window even
   when the values did not represent two comparable four-quarter periods.

**Implementation:**

- Added `asmf_data/quarters.py` as the shared quarter-arithmetic boundary.
  Coverage, scoring and presentation now use the same expected latest-eight
  sequence and exact missing-period list.
- YFinance now reads only `quarterly_financials`,
  `quarterly_income_stmt`, `quarterly_balance_sheet`, and
  `quarterly_cashflow`. Annual frames are never visited.
- The canonical promotion boundary now rejects every non-`YYYYQn` period from
  every provider. An annual `YYYY` row may remain in staging for diagnostics,
  but it cannot enter `financial_reports` or ASMF.
- Corrected YFinance canonical rows carry explicit `/quarterly` provenance.
  Point-in-time readers immediately exclude every unverified legacy Yahoo row,
  even before the first post-deployment refresh. A successful refresh then
  reconciles that source against the newly promoted quarterly snapshot, removes
  legacy/absent periods from `financial_reports`, and marks absent periods
  unpromoted in staging. This intentionally fails closed because their original
  annual/quarterly frequency cannot be recovered after persistence.
- Yahoo remains a fallback in storage as well as acquisition: a corrected Yahoo
  quarter cannot overwrite an existing canonical quarter from VNStock,
  Vietstock, or another non-Yahoo source. It may only fill an absent period or
  replace an older Yahoo-owned period.
- `FINANCIALS READY` now requires eight contiguous point-in-time quarters. A
  gap produces `PARTIAL` and a diagnostic such as
  `missing contiguous quarters: 2025Q3`.
- Corporate and bank scoring independently repeat the continuity check before
  any TTM/YoY calculation. Existing score thresholds were not changed.
- Fundamental facts with a broken window retain safe point-in-time fields such
  as Debt/Equity but suppress ROE and TTM growth. `/soi` renders
  `INSUFFICIENT` plus `Chưa đủ 8 quý liên tục để tính TTM`.
- The existing anti-look-ahead contract is unchanged: actual `public_date` is
  preferred, missing dates use only `period_end + 45 days`, and readers still
  enforce `public_date <= as_of`.

**Verification:**

- Integrated on top of `origin/main` at `2b0b3ae`; the valuation snapshot and
  scanner UX changes from the two newer remote commits are preserved.
- Focused fundamentals/PIT/runtime/dashboard/valuation: **201 passed**.
- Full `tests/` regression on the integrated remote: **960 passed**. One old
  schema test was updated to follow `LATEST_SCHEMA_VERSION` after migration v10.
  The Python 3.13 host has protobuf
  runtime 6.33.6 while the checked-in generated code requires 7.35.0, so this
  run used protobuf's documented temporary version-check override. No protobuf
  source was changed.
- All changed Python files compile successfully with the project's target
  CPython 3.12.13. A separate Python 3.12 focused pytest environment could not
  be provisioned because PyPI reset the `curl-cffi` download after three
  retries; no unrun 3.12 test was reported as PASS.
- `python -m pip check` completed with 10 pre-existing conflicts in unrelated
  global packages; none concerns the Issue 1 code path.
- Live public-provider deep audit with `yfinance==1.0` passed for VNM and HAG:
  - VNM annual revenue included 2024 `61,782,609,528,445`, while quarterly
    revenue observations were approximately 12.96–18.85 trillion. The adapter
    excluded annual-only 2021Q4–2024Q4 and never stored those annual values.
  - VNM and HAG each produced six quarterly rows; 2025Q3 lacked revenue, so only
    five rows promoted. Both coverage records were `PARTIAL` with exact missing
    periods `2025Q3, 2024Q4, 2024Q3`; both ASMF scores were `None`.
  - Runtime views built from the live Yahoo result rendered `CƠ BẢN:
    INSUFFICIENT`, retained safe Debt/Equity context, named the missing periods,
    and emitted no ROE/revenue-growth/profit-growth TTM metrics.
  - Anti-look-ahead remained exact: 2026Q2 was invisible on 2026-08-13 and
    became visible on the estimated publication date 2026-08-14.
  - An adversarial temporary database containing eight contiguous legacy
    `yfinance/VNM.VN` rows retained eight raw records for audit but exposed zero
    rows to point-in-time readers and produced no ASMF score.
- Production database refresh and real Telegram delivery remain **NOT TESTED**:
  this clone has no `.env`, Vietcap credentials, Telegram token, or production
  database. All live probes used temporary SQLite files and made no production
  writes.

### Remaining

The newly supplied remediation plan supersedes the earlier blanket completion
statement. Issue 1 is implemented and verified offline. Issues 2, 3 and 5 remain
untouched. Issue 4 is the only other issue already repaired under that plan.

### 2026-09-24 — `/performance` remediation P1 audit and architecture

Scope was deliberately limited to audit and design. No production Python code,
schema, or existing test expectation was changed in P1.

#### Confirmed current flow

- Telegram registers `/performance` in `telegram_bot/app.py`. The handler ignores
  `context.args` and calls `TelegramCommandService.performance()` with no input.
- `TelegramCommandService.performance()` delegates to
  `BotDataService.performance_overview()` with no strategy selector.
- `RuntimeBotDataService.performance_overview()` returns a hard-coded ACB/VNINDEX
  120-session ENGINE TEST paragraph. It performs no database read and cannot
  distinguish CL1 from ASMF.
- `scripts/run_preliminary_backtest.py` independently fetches one configured stock
  (default ACB) plus VNINDEX, aligns the latest 120 daily bars, constructs proxy
  `SignalInputs`, and replays the generic `SignalEngine`.
- `backtest.engine.run_backtest()` opens/closes at the same `SignalEvent.price`
  emitted from close-based observations. It has no pending-order chronology,
  cash, quantity, costs, sellability date, portfolio equity curve, or benchmark.
- `calculate_performance()` compounds sequential trade percentages rather than a
  dated portfolio equity curve. Its drawdown is therefore not portfolio max
  drawdown. Zero trades return zero average return and drawdown; profit factor is
  unavailable. CAGR, Sharpe, Sortino and exposure do not exist.
- There is no `backtest_runs` storage, repository, migration, structured JSON
  result, or completed-run status boundary. Existing `signals`/`signal_events`
  describe signal lifecycles, not reproducible strategy-backtest results and not
  live execution history.

#### Strategy and point-in-time findings

- Real CL1 logic lives only in `strategy.technical_strategies.evaluate_cl1()` and
  requires at least 200 completed daily bars. It owns EMA20/EMA50 crossing, RSI14,
  ADX14, volume 3/20, MA200, EMA cross-down and Chandelier exit logic. The current
  preliminary runner does not call it.
- Real ASMF logic lives in `evaluate_asmf()`. Runtime supplies its Sector,
  Fundamental and Institutional scores through `asmf_data.scoring`; missing
  mandatory layers correctly produce BLOCKED. The preliminary runner does not
  call it.
- Financial and bank readers already enforce `public_date <= as_of`; flow readers
  enforce `trading_date <= as_of`; sector membership readers enforce effective
  dates. A historical ASMF adapter can reuse these boundaries.
- Runtime `_evaluate_asmf()` is not itself safe to reuse as a historical adapter:
  it resolves sector membership at `now()` rather than the historical bar date
  and can apply current severe-news context. P4 must build historical inputs using
  the bar's `as_of=T`, then call the shared pure `evaluate_asmf()` directly.
- Sector histories passed to `sector_strength_score()` are not internally sliced
  to `<= as_of`. The P4 adapter must provide pre-sliced histories and aligned
  VNINDEX bars; a defensive check/slice should be considered at that boundary.

#### Settlement, execution and live-performance findings

- No T+2 or T+2.5 convention is specified anywhere in repository code or project
  documentation. Portfolio V1 explicitly has no realized-P&L ledger and excludes
  fees, taxes and slippage. P5 must add a configurable settlement abstraction and
  must not claim a specific Vietnamese convention until the user/project supplies
  one. The default/result must identify the configured value explicitly.
- No persisted brokerage execution history exists. `signal_events` alone cannot
  establish fills, quantities, costs, realized P&L, or live equity. LIVE
  PERFORMANCE must therefore render NOT AVAILABLE rather than infer results.

#### Approved architecture for later phases

Keep `backtest.engine` legacy APIs for the ENGINE VALIDATION diagnostic. Add the
strategy-backtest path as separate, provider-independent modules:

- `backtest/models.py`: immutable enums/models for strategy, validation status,
  run status, execution config, orders/fills, positions, trades, equity points,
  benchmark and metrics. Optional metrics use `None`, never fabricated zero.
- `backtest/adapters.py`: `CL1HistoricalAdapter` and `ASMFHistoricalAdapter`.
  Each evaluates only completed bars `<= T` and calls the imported production
  evaluator. Adapters must expose/inject that callable so tests can prove reuse.
- `backtest/execution.py`: chronological pending-order simulator. A signal based
  on close T queues an order for open T+1 by default. Fill prices are constrained
  to the next bar's OHLC and configured slippage. Exit follows the same chronology;
  settlement gates sellability. Config owns entry mode, fees, sell tax, slippage,
  lot size, settlement sessions, initial capital, allocation mode and allocation.
- `backtest/portfolio.py`: cash, open/pending/closed positions, quantities, fees,
  realized P&L and dated mark-to-market equity curve. Initial P2 persistence may
  store summary/config only; full execution artifacts arrive with P5.
- `backtest/analytics.py`: metrics calculated from actual net equity and closed
  trades, with explicit data-sufficiency rules. Benchmark is VNINDEX buy-and-hold
  over the same effective date range; raw difference is named Excess Return.
- `backtest/runner.py`: proposed API
  `run_strategy_backtest(strategy, symbols, start_date, end_date, config, data_port, asmf_port=None)`.
  It remains multi-symbol and does not hard-code ACB.
- `backtest/repository.py`: SQLite access for persisted completed runs. Telegram
  reads only the latest `SUCCESS` run for the exact requested strategy; failed or
  partial jobs never replace a valid displayed result.
- `telegram_bot/performance_formatters.py` (or the existing formatter module):
  pure rendering of summaries/detail. Command execution remains read-only and
  never launches a heavy backtest.

#### Proposed additive P2 schema

Migration 11 should create `backtest_runs` with at least: `run_id` text primary
key, `strategy` constrained to CL1/ASMF, `run_kind`, `validation_status`, `status`,
`started_at`, nullable `completed_at`, `start_date`, `end_date`, `universe_size`,
`symbols_json`, `initial_capital`, nullable `final_equity`, `trade_count`,
nullable `open_position_count`, nullable summary metrics (`total_return_percent`,
`cagr_percent`, `max_drawdown_percent`, `sharpe_ratio`, `sortino_ratio`,
`profit_factor`, `benchmark_return_percent`, `benchmark_max_drawdown_percent`,
`excess_return_percent`), `config_json`, `warnings_json`, and `created_at`.
JSON columns require `json_valid`; numeric values must be finite before insert.
Indexes should support `(strategy, status, completed_at DESC)` and latest-success
summary queries. Store percentages in one documented unit consistently.

P2 may legitimately persist fields as NULL until P3/P5 can calculate them from a
real strategy execution/equity curve. Schema evolution should be additive; avoid
inventing zeros. Store versioned `config_json` so later walk-forward/OOS metadata
can be added without redefining the result identity.

#### Phase boundaries and risks

- P2: storage/repository, dynamic Telegram parser/formatter, unavailable states,
  ENGINE VALIDATION naming, and LIVE PERFORMANCE NOT AVAILABLE. No heavy job in
  a Telegram request and no fabricated strategy run.
- P3: CL1 adapter/runner reusing `evaluate_cl1`; multi-symbol signal generation.
- P4: ASMF adapter with every layer evaluated point-in-time and missing layers
  BLOCKED exactly as live.
- P5: execution simulator, costs, configurable settlement, cash/positions/equity,
  benchmark and advanced metrics. This ordering means P3/P4 can first verify
  shared signal semantics; their outputs must not be published as valid net
  performance until P5 supplies execution accounting.
- Material risks: SQLite migration compatibility; accidental future-bar leakage
  in sector histories; treating BLOCKED as WATCH; ambiguous simultaneous
  multi-symbol capital allocation; non-trading-session settlement arithmetic;
  and reporting statistically undefined metrics. Each must fail closed and be
  covered before a run can reach `SUCCESS`.

#### Verification

- Full baseline: `py -3.12 -m pytest -q` — **960 passed in 39.80s**.
- P1 added no code tests because it intentionally made no production change.
- Existing pending live acceptance remains NOT TESTED and unchanged.

Next: Performance remediation P2 only. Stop before CL1 implementation.

### 2026-09-24 — `/performance` remediation P2 complete

#### Implementation

- Added `backtest.models.BacktestRun` with explicit run status and validation
  status. Strategy results are limited to CL1/ASMF, undefined metrics remain
  nullable, and non-finite numeric values are rejected before persistence.
- Added migration 11, `backtest_run_results`. The new `backtest_runs` table
  stores strategy/run identity, date range, universe, capital, nullable summary
  metrics, benchmark fields, versionable configuration JSON and warning JSON.
  Its index supports latest successful results by strategy and completion time.
- Added `backtest.repository` with upsert and exact-strategy latest-success
  queries. RUNNING/FAILED runs never replace the result displayed by Telegram.
- Replaced the hard-coded ACB 120-session runtime output. `/performance` now
  summarizes the latest saved CL1 and ASMF runs, while `/performance CL1` and
  `/performance ASMF` load only their respective latest successful run.
- Added a pure Telegram formatter. Missing runs report `Chưa có backtest ... hợp
  lệ`; missing metrics render `N/A`; ENGINE VALIDATION is kept distinct; LIVE
  PERFORMANCE is explicitly NOT AVAILABLE because no execution ledger exists.
- Telegram request handling remains read-only and does not start a backtest job.
  Invalid or extra arguments return `/performance [CL1|ASMF]` usage.
- Renamed the preliminary script's success label to `BACKTEST ENGINE VALIDATION`
  and states `ENGINE ONLY`; its calculation was preserved as an internal
  diagnostic and was not relabelled as CL1/ASMF.
- Updated README command examples and the architecture document. No CL1 adapter,
  ASMF adapter, execution simulator, costs, settlement or advanced metric
  calculation was implemented in P2.

#### Tests and evidence

- Added repository/formatter tests for model round-trip, nullable data,
  latest-success ordering, failure exclusion, exact CL1/ASMF isolation,
  unavailable output, dynamic runtime summary, saved assumptions and the live
  performance boundary.
- Updated migration tests for schema version 11 and replaced stale schema-version
  assertions in coverage/portfolio tests with the current version boundary.
- First full run: 960 passed, 6 failed. All six failures were old tests asserting
  schema version 10 after migration 11; no runtime or data failure occurred.
- Focused follow-up: 33 passed.
- Final full regression: `py -3.12 -m pytest -q` — **966 passed in 35.00s**.
- Live Telegram delivery and real stored CL1/ASMF runs are **NOT TESTED** because
  P2 creates the read/storage boundary only; no real strategy backtest job exists
  before P3/P4/P5.

Next: Performance remediation P3 only — real historical CL1 adapter reusing
`evaluate_cl1`. Stop before ASMF and execution-cost work.

### 2026-09-24 — `/performance` remediation P3 complete

#### Implementation

- Added `backtest.adapters.CL1HistoricalAdapter`. It validates a single-symbol,
  strictly chronological `ONE_DAY` series and requires the same 200-bar warm-up
  as production CL1. For each requested session T it calls the production
  `strategy.technical_strategies.evaluate_cl1` with only `bars[:T+1]`.
- The adapter verifies that every evaluator result matches the current symbol and
  completed-bar timestamp. Empty requested ranges, short histories, mixed symbols,
  non-daily bars and non-chronological inputs fail closed.
- Added `backtest.runner.run_strategy_backtest(...)` with caller-supplied strategy,
  symbols, start/end date, historical data port and SQLite connection. P3 accepts
  CL1 only and rejects ASMF until its point-in-time adapter exists in P4.
- Multi-symbol histories are evaluated independently. The run persists the exact
  universe, decision count and BUY/WATCH/SELL action counts through the P2
  repository with `validation_status=IN_SAMPLE_ONLY`.
- P3 deliberately does not create fills or trades before P5. Persisted config is
  `execution_mode=SIGNALS_ONLY`; `final_equity` and every return/risk/benchmark
  metric remain NULL. Warnings explicitly list execution, costs, settlement,
  portfolio equity and benchmark as unavailable.
- Updated the Telegram formatter so a signal-only run is labelled `HISTORICAL
  SIGNAL EVALUATION`. It displays decision count and `Giao dịch đóng: N/A — chưa
  mô phỏng execution`, never the storage placeholder `trade_count=0` as evidence.
- Added `backtest.data.SQLiteDailyBarData`, a read-only chronological adapter over
  cached normalized daily candles.
- Added `scripts.run_cl1_backtest`, an offline SQLite job requiring explicit
  `--symbols`, `--start-date` and `--end-date`. It is not invoked from Telegram
  and does not fetch a provider or expose secrets.

#### Tests and evidence

- A monkeypatched production-module evaluator received prefixes of lengths 200,
  201 and 202 for three consecutive decisions, proving the adapter resolves and
  reuses `strategy.technical_strategies.evaluate_cl1` rather than a second CL1.
- A no-look-ahead spy confirmed the maximum timestamp visible on every evaluator
  call equals the decision timestamp and precedes the next future bar.
- A two-symbol run produced ten chronological decisions, persisted as the latest
  successful CL1 record, retained all performance metrics as NULL, and rendered
  no fabricated zero-trade/zero-return claim.
- Short histories, duplicate symbols and an ASMF request all fail closed.
- SQLite daily-bar loading was verified chronological.
- Focused P3/backtest/strategy suite: **15 passed**.
- Full regression: `py -3.12 -m pytest -q` — **971 passed in 30.90s**.
- CLI boundary: `py -3.12 -m scripts.run_cl1_backtest --help` — **PASS**.
- A real production-database CL1 evaluation is **NOT TESTED** in this clone; no
  assumption is made that its SQLite cache contains 200 bars for requested
  symbols. No live or profitability claim is made.

Next: Performance remediation P4 only — ASMF historical adapter with every
required layer resolved point-in-time at T. Stop before P5 execution work.

### 2026-09-24 — `/performance` remediation P4 complete

#### Implementation

- Added `ASMFHistoricalAdapter` beside the CL1 adapter. It resolves the
  production `strategy.technical_strategies.evaluate_asmf` callable rather than
  implementing a second ASMF formula.
- For each completed stock session T after the 200-bar warm-up, the adapter uses
  the stock prefix ending at T and a VNINDEX prefix whose last timestamp is no
  later than T. A missing or short VNINDEX prefix fails closed.
- Sector membership and members are queried using the historical stock date T.
  Full peer histories may be cached for efficiency, but every series passed to
  `sector_strength_score` is sliced to timestamps `<= T`. Current membership or
  future peer bars cannot leak into the layer.
- Fundamental scoring uses the existing point-in-time store with
  `public_date <= T`; institutional scoring uses `trading_date <= T`. Market
  regime and technical/SMF price-volume evidence are calculated by the shared
  evaluator from the T-bounded price prefixes.
- No sentiment/news layer is applied because runtime news is not historical
  ASMF evidence. Missing sector, fundamental or institutional layers remain
  `BLOCKED` exactly as in the pure production evaluator.
- Extended `run_strategy_backtest` to accept ASMF and persist exact-strategy
  decision/action counts through the P2 repository. Both CL1 and ASMF remain
  `SIGNALS_ONLY`; performance metrics remain NULL and Telegram renders them as
  historical signal evaluations rather than simulated trades.
- Added `scripts.run_asmf_backtest`, an explicit offline SQLite job. It never
  performs provider acquisition or runs inside a Telegram request.

#### Tests and evidence

- A monkeypatched production-module evaluator confirmed the adapter calls
  `evaluate_asmf` with stock/benchmark prefixes ending at T and all three supplied
  score keyword arguments.
- A sector-score spy confirmed all five effective-dated member histories and the
  VNINDEX series end at or before the current decision timestamp.
- An integration test stored eight visible contiguous quarters plus a deliberately
  adverse 2026Q1 report published after T. Historical fundamental score remained
  the expected 100.0, proving the future report was excluded.
- With no sector, financial or flow evidence, the real production evaluator
  returned `BLOCKED` and listed all three mandatory missing layers.
- An ASMF runner result persisted under the ASMF key, retained all performance
  metrics as NULL and rendered `Giao dịch đóng: N/A`.
- Focused ASMF/PIT/backtest suite: **31 passed**.
- Full regression: `py -3.12 -m pytest -q` — **975 passed in 33.33s**.
- CLI boundary: `py -3.12 -m scripts.run_asmf_backtest --help` — **PASS**.
- A real production-database ASMF evaluation is **NOT TESTED** in this clone.
  It requires adequate cached VNINDEX/sector histories and real point-in-time
  ASMF inputs; no completeness or profitability claim is made.

Next: Performance remediation P5 only — execution chronology, costs, configurable
settlement, portfolio equity, benchmark and supported analytics.

### 2026-09-24 — `/performance` remediation P5 complete

#### Execution and portfolio accounting

- Added `BacktestExecutionConfig`. Entry mode is explicitly `OPEN_T_PLUS_1` and
  allocation is explicitly `EQUAL_WEIGHT`. Commission, sell tax, slippage, lot
  size and initial capital are configurable. Settlement sessions have no default
  and must be supplied by the caller; the repo still makes no claim whether the
  applicable market convention should be described as T+2 or T+2.5.
- A decision created from close T only schedules an order. It cannot fill at the
  same close and fills no earlier than the next available open for that symbol.
  Exit orders follow the same chronology and cannot fill before the configured
  sellable session index.
- Adverse slippage is applied to the next open and clamped into that bar's
  observed low/high range. No synthetic out-of-range fill is possible.
- Added whole-lot quantity sizing, cash debits/credits, entry and exit commissions,
  sell tax, realized P&L, explicit open positions, closed trades and pending-order
  accounting. Equal-weight budget is bounded by available cash and includes the
  entry commission; no leverage is assumed.
- Added a dated mark-to-market equity curve containing cash, market value, total
  equity and exposure. End-of-test positions are not force-closed; they remain
  explicit and have not incurred hypothetical exit costs.

#### Benchmark and analytics

- Added VNINDEX buy-and-hold using exactly the strategy equity curve's effective
  first and last timestamps. Strategy minus benchmark is labelled Excess Return,
  not alpha. Both strategy and benchmark drawdown come from dated value curves.
- Added net total return, CAGR, max drawdown, Sharpe, Sortino, Calmar, win rate,
  average net trade, profit factor, expectancy, average win/loss, payoff,
  best/worst trade, average holding sessions, longest losing streak, average
  exposure and trades/year.
- Risk ratios require at least 30 equity-return observations and a valid
  denominator. Undefined values remain NULL/N/A. A zero-trade run reports win
  rate 0 but leaves total return, CAGR, Sharpe, profit factor and trade-return
  metrics unavailable, avoiding the false claim that no trades means 0% strategy
  performance.
- `run_strategy_backtest` now optionally executes either the CL1 or point-in-time
  ASMF decision stream, persists final equity, open/closed counts, net analytics,
  benchmark results, costs and exact assumptions through the P2 repository.
- `/performance` labels executed results `NET SAU CHI PHÍ`, displays final equity,
  benchmark drawdown and the supported advanced metrics, and retains the
  `IN-SAMPLE-ONLY` warning. LIVE PERFORMANCE remains NOT AVAILABLE because this
  is offline simulation, not broker execution history.
- Both offline CLIs now require `--settlement-sessions`; their default assumptions
  are commission 0.15% each side, sell tax 0.10%, slippage 0.20%, lot 100 and
  initial capital 500 million VND. Every assumption can be overridden.
- Confirmed limitation: the production `evaluate_asmf` currently emits BUY,
  WATCH or BLOCKED but never SELL. The simulator deliberately does not reinterpret
  WATCH/BLOCKED as an exit because that would create a second ASMF strategy.
  Executed ASMF runs therefore warn that positions may remain open and closed-
  trade performance may stay unavailable until a shared ASMF exit rule is
  separately specified.

#### Tests and evidence

- Verified close-T BUY fills at open T+1, SELL follows the same chronology, and
  even extreme slippage remains within observed OHLC.
- Verified configured costs make net return lower than gross return and reduce
  final equity.
- Verified a two-session settlement delay prevents a SELL until the correct
  symbol-session index.
- Verified equity `[100, 120, 90, 95]` produces -25% maximum drawdown.
- Verified realized gains 100 and losses 50 produce profit factor 2.0, with
  correct win rate, payoff and losing streak.
- Verified zero trades leave return/risk/trade metrics unavailable rather than 0.
- Verified VNINDEX ignores bars outside the equity curve and uses the exact same
  first/last timestamps.
- Verified 32 equity observations with real variation enable CAGR, Sharpe,
  Sortino and Calmar, while shorter/degenerate inputs remain unavailable.
- Verified an executed CL1 result round-trips through SQLite and `/performance`
  renders saved costs, settlement and NET status.
- Initial focused execution run found one artificial sub-day CAGR overflow. The
  analytics boundary was hardened to require an effective span of at least one
  day; the repeated focused suite passed.
- Focused P2–P5/Telegram suite: **58 passed**.
- Final focused execution/analytics suite: **10 passed**.
- Final ASMF/backtest follow-up: **25 passed**.
- Final full regression: `py -3.12 -m pytest -q` — **985 passed in 33.71s**.
- CL1 and ASMF `--help` commands both pass and show the required settlement flag.
- Real production-like backtest runs and Telegram delivery are **NOT TESTED** in
  this clone because cache completeness and local credentials/data are not
  available. No profitability or out-of-sample validation claim is made.

Next: run the two offline jobs against an adequately populated local SQLite
cache, then inspect the persisted Telegram output. This requires real local data
and remains a follow-up, not a new automatically started phase.

### 2026-09-24 — ASMF V2 institutional-flow removal complete

#### Decision and implementation

- The user confirmed that reliable Vietnamese foreign/proprietary trading-flow
  data is not available. ASMF V2 therefore no longer uses this dataset in an
  automatic score, trigger, or missing-data gate.
- Removed `institutional_flow_score` from the shared `evaluate_asmf` contract.
  Missing flow data can no longer make an otherwise valid result `BLOCKED`, and
  the rendered layer list no longer reports an Institutional layer.
- Reweighted the price-volume-only SMF score exactly as specified:
  Accumulation 43.75%, OBV trend 31.25%, Volume Z-score 25%.
- Removed institutional-flow queries from the Telegram runtime, persisted market
  scanner, and point-in-time historical ASMF adapter. Live and backtest paths
  continue to share the same production evaluator.
- Kept the existing institutional-flow schema, acquisition, refresh, scoring,
  import and reporting code intact as an experimental research/lookup facility.
  It is not evidence for ASMF V2 and cannot create or block an automatic signal.
- Sector and point-in-time Fundamental remain mandatory external ASMF layers.
  Market RISK-OFF and the existing severe-negative-news overlay retain their
  established blocking behavior. No ASMF SELL rule was invented.
- Updated the Telegram strategy catalog, README, architecture documentation and
  regression expectations to describe the V2 contract.

#### Tests and evidence

- Added a deterministic component test: with Accumulation=0, OBV=75 and volume
  Z-score=50, SMF equals `0.4375*0 + 0.3125*75 + 0.25*50`.
- Added a contract test that the removed `institutional_flow_score` evaluator
  argument is rejected, preventing accidental reintroduction at a call site.
- Historical adapter tests now prove only Sector and Fundamental scores are
  supplied, and missing flow is absent from both missing reasons and UI layers.
- Focused ASMF/runtime/scanner regression: **86 passed in 3.97s**.
- Full regression: `py -3.12 -m pytest -q` — **987 passed in 33.89s**.
- Live Telegram delivery and production-like ASMF backtest remain **NOT TESTED**;
  this change required no network data and makes no profitability claim.

Next: run the ASMF offline job against a populated local SQLite cache and inspect
the persisted `/performance ASMF` output when suitable real local data exists.

### 2026-09-24 — Local backtest evidence follow-up split at data-readiness boundary

#### Local data audit

- Confirmed `stock_bot.db` exists locally (about 23.5 MiB) and contains 263–264
  daily bars for many symbols through 2026-09-24, including VNINDEX.
- Selected HPG, VNM and GAS because all three have at least 260 daily bars, a
  current sector membership, and eight stored corporate report rows.
- Their sectors have ample cached peer histories: 101/103 usable members for
  HPG's sector 1700, 141/143 for VNM's sector 3500, and 140/141 for GAS's
  sector 7500.
- The stored sector memberships are not historical for the whole test: each
  begins on 2026-09-20. Earlier decisions must therefore report the Sector
  layer missing instead of backdating current membership.
- The eight BCTC rows per selected symbol are not eight contiguous quarters.
  They include annual gaps such as 2022Q4, 2023Q4 and 2024Q4 and omit required
  quarters such as Q3. `analyze_quarter_continuity(required=8)` correctly keeps
  the Fundamental score unavailable. The rows carry yfinance provenance and
  are not treated as adequate point-in-time ASMF evidence.

#### Persisted local runs

- Ran CL1 using HPG,VNM,GAS from 2026-06-01 through 2026-09-24 with the README's
  explicit two-session settlement choice and default costs. Persisted run
  `local-cl1-20260924` produced 188 decisions (5 BUY, 67 SELL, 116 WATCH), one
  closed trade and one open mark-to-market position. Net total return was
  +1.19%, maximum drawdown -2.56%, and VNINDEX return -4.95%. These are
  `IN_SAMPLE_ONLY` local simulation results, not a profitability claim.
- Ran ASMF V2 over the identical universe/range and persisted
  `local-asmf-v2-20260924`. It produced 188 BLOCKED decisions and no trades.
  The missing-reason audit counted Fundamental on all 188 decisions and Sector
  on 179 decisions. Institutional flow was absent from the reasons, confirming
  the ASMF V2 removal works on the real local path.
- Rendered the same repository records used by Telegram for `/performance`,
  `/performance CL1` and `/performance ASMF`. Both strategies remained
  `IN_SAMPLE_ONLY`; ASMF return/risk/trade metrics remained N/A rather than
  fabricating 0% performance.

#### Observability hardening

- `backtest.runner` now persists `missing_reason_counts` beside action counts for
  both signal-only and executed runs.
- `/performance <strategy>` now includes a `TÍN HIỆU` block showing action
  counts and each persisted missing reason. The saved ASMF output explicitly
  renders `BLOCKED=188`, Fundamental=188 and Sector=179.
- Added formatter/repository and ASMF-runner regression coverage.
- Focused backtest suite: **26 passed in 1.16s**.
- Full regression: `py -3.12 -m pytest -q` — **988 passed in 30.44s**.
- `git diff --check` — **PASS** (line-ending conversion warnings only).

#### Split reason and remaining acceptance

The execution and Telegram-read follow-up is verified, but an ASMF performance
run with complete mandatory evidence cannot be produced honestly from this
cache. Completion requires real effective-dated membership covering the chosen
historical dates plus at least eight contiguous point-in-time quarters for an
eligible non-bank universe. No synthetic rows or backdated memberships were
inserted. Rerun ASMF after those inputs exist; it must then demonstrate decisions
without mandatory missing layers while remaining `IN_SAMPLE_ONLY`.

Next: populate valid historical sector membership and eight contiguous published
quarters for the ASMF universe, then rerun and inspect `/performance ASMF`.

### 2026-09-24 — ASMF data-readiness provider exhaustion confirmed

#### Exhaustive local and provider checks

- Scanned every symbol having at least 200 daily bars, a current sector
  membership and canonical corporate reports. There were 97 candidates and
  **zero** returned a non-NULL `fundamental_score` on 2026-09-24. Switching the
  backtest universe therefore cannot resolve the blocker.
- Found environment drift: `requirements.txt` pins `vnstock==4.0.8`, while the
  active `py -3.12` installation was 3.2.6 with `vnai==2.1.9`. Installed the
  tracked requirements successfully; the active versions are now VNStock 4.0.8
  and VNAI 2.6.1.
- Retried HPG, VNM and GAS with the default KBS-first VNStock path. VNStock became
  the selected provider instead of Yahoo, but the result for every symbol still
  lacked 2024Q3 and 2024Q4, so the eight-quarter continuity rule remained unmet.
- Tried VCI first for HPG. It returned four raw periods but all lacked usable
  revenue for canonical promotion; readiness did not improve.
- Tried MAS for HPG. The installed community package exposed no usable MAS
  result through the adapter, so the chain continued to incomplete Yahoo data.
- Tried the independent TCBS adapter directly through the same refresh/promotion
  boundary. TCBS returned MISSING and stored/promoted no rows.
- This matches current official VNStock documentation: KBS is explicitly not
  recommended for this use because its source limits the number of report
  periods; VCI is recommended, but the observed local payload was not promotable
  by the repository's required-field boundary.
- No CSV, report date, quarter, sector history or financial value was invented.
  Resolving readiness now requires a trustworthy external export/document set
  containing the missing contiguous quarters and historical memberships.

#### Revalidation

- Re-ran `local-asmf-v2-20260924` after all provider attempts. It remained 188
  BLOCKED decisions, with Fundamental missing 188 times and Sector missing 179
  times. Institutional flow remained absent from all blockers.
- Full regression under VNStock 4.0.8/VNAI 2.6.1:
  `py -3.12 -m pytest -q` — **988 passed in 30.49s**.
- `pip check` is **FAIL** in the shared user Python environment because unrelated
  installed Google/Streamlit packages require older protobuf, and pyppeteer
  requires older urllib3/websockets. The repo itself pins protobuf 7.36.2,
  urllib3 transitively, and websockets-compatible dependencies; do not mutate
  project pins to repair unrelated global packages. README already recommends a
  project virtual environment.

Next: obtain a licensed/controlled export or verified report documents for at
least eight contiguous quarters plus historical sector membership, import them
through the existing strict boundary, then rerun ASMF. Until those external
inputs exist, the phase remains PARTIAL rather than fabricating acceptance.

### 2026-09-24 — Verified HPG filings close ASMF data-readiness follow-up

#### Controlled financial evidence

- Downloaded and visually inspected eight HPG consolidated quarterly filings
  published through Vietstock: 2024Q3, 2024Q4, 2025Q1, 2025Q2, 2025Q3,
  2025Q4, 2026Q1 and 2026Q2.
- Transcribed net revenue (income-statement line 10), parent-company NPAT
  (line 61), equity (line 400/410) and liabilities (line 300). This corrects the
  earlier provider ambiguity between total NPAT (line 60) and parent-company
  NPAT, and replaces the suspicious KBS 2025Q4 row that nearly duplicated
  2025Q1.
- Used the actual Vietstock publication dates 2024-11-01, 2025-02-03,
  2025-04-30, 2025-07-31, 2025-11-01, 2026-01-30, 2026-05-04 and 2026-07-31.
  No estimated dates, synthetic quarters or backdated sector memberships were
  introduced.
- Imported the eight records through the existing strict CSV boundary. A
  read-only database verification returned exactly eight contiguous HPG rows
  for 2024Q3–2026Q2 and `fundamental_score(HPG, 2026-09-24) = 80.0`.

#### Acceptance run

- Preserved the existing HPG sector membership effective date of 2026-09-20 and
  narrowed the acceptance interval to 2026-09-20 → 2026-09-24 rather than
  pretending that current membership was historical.
- Persisted `local-asmf-v2-verified-hpg-20260924` with the shared production
  evaluator and explicit two-session settlement convention.
- Result: `SUCCESS`, `IN_SAMPLE_ONLY`, 3 decisions, all WATCH, no trades, and
  `missing_reason_counts={}`. Fundamental and Sector are therefore both present;
  institutional flow is neither queried nor used as a gate in ASMF V2.
- Zero trades leave total return and maximum drawdown NULL/N/A by design. The
  three-session window proves readiness only and is not performance evidence.

#### Verification

- `py -3.12 -m scripts.import_asmf_eod --financials tmp\\hpg_financials_verified.csv`
  — PASS, 8 records upserted.
- Read-only database verification — PASS, 8 contiguous rows and Fundamental 80.0.
- `py -3.12 -m scripts.run_asmf_backtest --symbols HPG --start-date 2026-09-20
  --end-date 2026-09-24 --settlement-sessions 2
  --run-id local-asmf-v2-verified-hpg-20260924` — PASS, 3 WATCH decisions.
- Persisted config verification — PASS, `missing_reason_counts={}`.
- `py -3.12 -m pytest -q` — PASS, 988 tests in 36.58s.

The local backtest evidence follow-up is COMPLETE. The next phase is not started
automatically; remaining production Telegram/live-session checks stay NOT TESTED.

### 2026-09-24 — Vietcap IQ financial provider

#### Observed contract

- User-supplied Vietcap IQ responses establish an authenticated frontend GET:
  `/api/iq-insight-service/v1/company/{symbol}/financial-statement`, with
  `section=BALANCE_SHEET` and `section=INCOME_STATEMENT`.
- Both responses contain `data.years` and `data.quarters`; the FPT samples have
  34 quarterly rows and carry actual `publicDate` values.
- Verified mappings are `isa3` net revenue, `isa20` total NPAT, `isa22` parent-
  company NPAT, `bsa53` total assets, `bsa54` total liabilities, `bsa55`
  current liabilities, `bsa67` non-current liabilities and `bsa78` equity.
- The provider revalidates `bsa55+bsa67=bsa54`, `bsa54+bsa78=bsa53`, and, when
  all profit components exist, `isa21+isa22=isa20`. A failed identity removes
  that section's evidence rather than guessing a changed field meaning.
- Comparing the 2025 annual and 2025Q4 income rows confirms the quarterly array
  contains standalone Q4 values, not duplicated annual cumulative values.

#### Implementation

- Added `fundamentals.providers.vietcap_iq_provider` with bounded GETs, strict
  response-wrapper validation, quarterly normalization, actual publication
  dates, safe provenance and no institutional-flow scope.
- Vietcap IQ is first in the provider chain only when
  `VIETCAP_IQ_FINANCIALS_ENABLED=true`; the default remains disabled. Existing
  environment-managed Vietcap values can be passed without being printed or
  persisted by the adapter. No new credential or token variable was added.
- HTTP/authentication failure remains an ERROR at the adapter boundary and the
  chain proceeds to VNStock, TCBS and Yahoo. Partial statement evidence stays
  staged and cannot bypass the canonical promotion checks.
- Anonymous live GET returned HTTP 403. The existing trading-domain Vietcap
  environment session returned HTTP 400 against IQ, confirming it is not valid
  evidence of IQ authentication. Authenticated live acquisition is NOT TESTED;
  no credentials were requested or copied from browser DevTools.

#### Verification

- Focused provider/chain/config/promotion regression:
  `py -3.12 -m pytest -q tests\\test_fundamental_providers.py
  tests\\test_coverage_config_report.py tests\\test_fundamental_refresh.py`
  — 122 passed in 2.39s after the final canonical-promotion assertion.
- Full regression: `py -3.12 -m pytest -q` — 994 passed in 31.27s.

The Vietcap IQ provider phase is COMPLETE at the code/offline-contract boundary.
Live authenticated IQ fetch remains NOT TESTED and must be rerun only with a
locally valid session; this does not justify requesting or persisting browser
credentials. Stop before the next phase.

### 2026-09-24 — Vietcap IQ authenticated live-acceptance follow-up

- Added `scripts.test_vietcap_iq_live`, which calls the IQ provider directly so
  no VNStock/TCBS/Yahoo fallback can create a false PASS. It reports only symbol,
  complete-quarter count, actual-public-date count and latest period on success.
- PASS requires at least eight complete quarters. An authentication/transport
  failure is `NOT TESTED`; an authenticated but structurally incomplete answer
  is FAIL. No configured secret value or upstream response body is printed.
- Offline verdict/redaction and provider regression:
  `py -3.12 -m pytest -q tests\\test_vietcap_iq_live_script.py
  tests\\test_fundamental_providers.py` — 68 passed in 0.27s.
- Direct bounded run:
  `py -3.12 -m scripts.test_vietcap_iq_live --symbol FPT` — NOT TESTED. Both
  BALANCE_SHEET and INCOME_STATEMENT were rejected or unusable with the existing
  local trading-domain session. No fallback ran and no secret was emitted.
- Full regression: `py -3.12 -m pytest -q` — 997 passed in 30.46s.

The follow-up is complete with an honest NOT TESTED live verdict. The concrete
external blocker is a locally valid Vietcap IQ session; do not request or copy
browser access tokens/cookies. Rerun the harness only after the user configures
the session locally, then stop.

### 2026-09-24 — Vietcap IQ header-contract correction

- Browser evidence confirmed the successful IQ financial-statement request has
  an `Authorization` header but no `Cookie` and no `device-id`.
- The browser page is hosted at `trading.vietcap.com.vn/iq/...`; therefore the
  correct request context is Origin `https://trading.vietcap.com.vn` and Referer
  `https://trading.vietcap.com.vn/iq/`, while the API host remains
  `https://iq.vietcap.com.vn`.
- Removed Cookie/device-id from the IQ provider and live harness. The market-
  data clients keep their existing credential contract unchanged.
- Added regression assertions proving IQ requests omit Cookie/device-id and use
  the observed Origin/Referer.
- Focused tests: 87 passed in 1.46s. Full regression: 997 passed in 31.44s.
- Direct FPT harness after the correction remains NOT TESTED: the currently
  configured Authorization was rejected or returned unusable content. This now
  isolates the external blocker to the Authorization value itself; none was
  printed, persisted or requested in chat.

The correction follow-up is COMPLETE. Live IQ acquisition remains NOT TESTED
until the user supplies a current Authorization locally and reruns the harness.

### 2026-09-24 — Vietcap IQ authenticated live acceptance PASS

- The user configured the current IQ `Authorization` only in the local
  PowerShell process and ran the direct, no-fallback harness for FPT.
- Harness result: PASS with 34 complete quarters, 34 actual publication dates
  and latest period 2026Q2.
- With `VIETCAP_IQ_FINANCIALS_ENABLED=true`, forced FPT synchronization completed
  through provider `VietcapIQ` in one selected attempt. Coverage became
  `FINANCIALS READY` with provenance `VietcapIQ/IQ/financial-statement`.
- Independent read-only verification confirmed 34 canonical FPT rows spanning
  2018Q1 through 2026Q2 and `fundamental_score(FPT, 2026-09-24) = 60.0`.
- The PowerShell environment variables were removed by the user after the run.
  No Authorization value was sent to chat, logged by the harness or persisted
  in repository files.
- `INSTITUTIONAL MISSING` remains visible in coverage as experimental lookup
  state only; ASMF V2 does not score or gate on institutional flow.
- `MARKET_HISTORY STALE` and `NEWS PARTIAL` are separate dataset freshness
  states and do not invalidate the financial-statement acceptance result.

The Vietcap IQ authenticated live-acceptance phase is COMPLETE. Stop before any
new phase; production bot-process coverage validation remains separately pending.

### 2026-09-24 — Vietcap IQ canonical integrity follow-up

**Root cause:** the initial IQ adapter correctly identified `bsa55` as current
liabilities and `bsa67` as non-current liabilities, but then normalized those
aggregate liability totals into canonical `short_term_debt`/`long_term_debt`.
The BSA schema and the supplied payload establish `bsa56` as short-term loans
and `bsa71` as long-term loans. This made Vietcap Debt/Equity semantically
different from VNStock/KBS, which already uses borrowings and finance leases.

Two related provider-integrity gaps were also confirmed. Canonical upsert was
unconditional except for a Yahoo-only guard, so a later VNStock/TCBS fallback
could overwrite an IQ quarter. In addition, an IQ `PARTIAL` result with zero
promotable rows stopped `ProviderChain`, preventing a healthy fallback.

**Implementation:**

- IQ now maps `bsa56` + `bsa71` as interest-bearing debt while retaining
  `bsa55+bsa67=bsa54` and `bsa54+bsa78=bsa53` as validation identities.
- Corrected canonical source names end in `/borrowings-v2`. Readers and
  readiness queries hide older IQ rows fail-closed, and the freshness shortcut
  is bypassed while a symbol still contains legacy IQ rows.
- Automated source precedence is now VietcapIQ v2 > VNStock > TCBS > Yahoo.
  Unknown/manual sources are never overwritten by the automated refresh path;
  legacy IQ rows have priority zero so a validated fallback can recover them.
- IQ returns `ERROR` when no returned quarter is canonical-complete. The chain
  can then continue to VNStock, TCBS and Yahoo instead of stopping on unusable
  partial evidence.

**Verification:** focused financial/provider/PIT/runtime/valuation regression
passed with 184 tests; the final source-upgrade/downgrade subset passed with
114 tests. Full regression passed with 1001 tests in 32.16s. Direct FPT live
revalidation is **NOT TESTED**: both IQ sections were
rejected/unusable with the current local `.env` session. The harness emitted no
secret. A valid local Authorization is required before forced sync can replace
the legacy FPT rows and before this phase can be marked complete.

This concrete external blocker splits the phase at a safe boundary. Stop before
bank fundamentals, scanner consistency or sentiment work.

### 2026-09-24 — Vietcap IQ canonical integrity live revalidation PASS

- The user renewed `VIETCAP_AUTHORIZATION` locally and ran the direct no-fallback
  FPT harness. It passed with 34 canonical-complete quarters, 34 actual
  publication dates and latest period 2026Q2.
- The forced financial refresh completed through VietcapIQ in one selected
  attempt and coverage reported `FINANCIALS READY`.
- A read-only SQLite verification found 34 FPT canonical rows spanning 2018Q1
  through 2026Q2. Every row carries corrected provenance
  `VietcapIQ/IQ/financial-statement/borrowings-v2`; the point-in-time Fundamental
  score remains 60.0.
- `coverage_report` intentionally renders the acquisition provider and
  `provider_source` (`VietcapIQ/IQ/financial-statement`), not the canonical row
  `source`. Its shorter display therefore does not indicate a legacy row.
- `INSTITUTIONAL MISSING` is experimental lookup state and does not participate
  in ASMF V2 scoring or gating. The CafeF `NEWS ERROR` was a separate DNS
  resolution failure and does not invalidate financial-statement acceptance.

The Vietcap IQ canonical integrity follow-up is COMPLETE. Stop before starting
another phase.

### 2026-09-25 — News coverage, freshness and sentiment integrity PASS

#### Confirmed root causes

- The periodic and on-demand production paths both reread one generic market RSS
  feed. Increasing the on-demand limit did not target the requested symbol, so
  a roughly 1,500-symbol universe had only 29 linked tickers in the local news DB.
- The alternative `s.cafef.vn/tin-doanh-nghiep/.../Event.chn` parser represented
  corporate events rather than CafeF's current editorial news and was not wired
  into the bot builder. FPT and SSI therefore retained old RSS-only caches.
- Persisted evidence showed the obvious positive headline “FPT lãi ròng gần 30
  tỷ đồng mỗi ngày” labeled negative. The configured
  `FiinGroup/phobert-finetuned` checkpoint classified the controlled 10-case
  benchmark at 4/10 under the assumed generic-label mapping and assigned clear
  positive and negative probes to the same raw `LABEL_0`. Its current config/card
  does not encode semantic names for `LABEL_0/1/2`.
- The lexicon path also selected labels by comparing only positive versus
  negative probabilities, ignoring a larger neutral probability for mixed news.

#### Implementation

- The scheduled runner now merges CafeF's official Chứng khoán, Doanh nghiệp,
  Tài chính-Ngân hàng and Smart Money RSS feeds with URL deduplication and
  partial-feed failure isolation.
- The production on-demand builder now fetches the exact lowercase CafeF tag
  page `/{symbol}/trang-1.html`, parses current timestamps/title/sapo, and runs
  outside the Telegram request path. `/tin` and `/sentiment` always queue a
  cooldown-protected refresh, even when cached articles exist; the current cache
  is still returned immediately.
- Tag articles that mention the ticker directly receive relevance 1.0 and may be
  primary; indirect tag articles receive relevance 0.4 and no primary ticker.
  Aggregate sentiment now includes this relevance weight. This prevents a broad
  market article from counting like a company-specific article or becoming a
  severe-negative company blocker.
- `financial_rules` v2 is the conservative production default. Explicit
  directional Vietnamese financial evidence is positive/negative; unknown or
  balanced evidence is neutral. An unvalidated transformer is disabled unless
  `SENTIMENT_ALLOW_UNVALIDATED_TRANSFORMER=true` is explicitly set.
- Duplicate URLs now refresh metadata, ticker links and inference instead of
  retaining stale labels. `scripts.reanalyze_news` versions existing inference;
  `scripts.sync_ticker_news` performs bounded per-symbol sync and records NEWS
  coverage as `CafeF/ticker_tag`.

#### Verification and live evidence

- Focused news/sentiment/runtime/coverage/dashboard regression: 133 passed.
- Full regression: 1007 passed in 40.13s.
- Controlled benchmark after the change: 10/10, macro-F1 1.0, versus 4/10 and
  macro-F1 0.1905 before. The fixture has only ten high-signal cases and is a
  regression gate, not evidence of general production accuracy.
- Live read-only tag-page probes returned current/recent results for all sampled
  symbols. The persisted bounded sync fetched FPT=10, SSI=10, ACB=10, HPG=3 and
  VIC=10 articles within 30 days.
- Reanalyzed 175 stored articles. FPT's profit headline is now positive with
  `backend=financial_rules`; SSI's promotional “treo thưởng” headline is neutral
  instead of negative.
- Coverage now reports `NEWS READY provider=CafeF/ticker_tag` with 10 articles
  for both FPT and SSI. A recoverable pre-migration copy remains at
  `tmp/news_sentiment.before-news-fix-20260925.db`.

Freshness is near-real-time on access, not a push-news guarantee: Telegram returns
cache immediately while the background fetch completes, and the next request
sees the update. The periodic market-wide RSS cadence remains configurable
(default 30 minutes). The phase is COMPLETE; stop before another phase.

### 2026-09-25 — Vietcap IQ bank BCTC adapter PASS

The ACB failure was schema selection, not authentication. Live IQ payloads carry
all industry namespaces in one object: corporate totals use `bsa`/`isa`, while
actual bank detail is non-zero under `bsb`/`isb`. Securities use `bss`/`iss` and
insurance uses `bsi`/`isi`; those are not interchangeable with a bank model.

The provider now detects the populated namespace before mapping. Verified bank
normalization uses cumulative `isb27` net interest income, `isa22` parent profit,
`bsa78` equity, `bsb104` gross customer loans and the absolute value of negative
`bsb105` loan-loss provision. Each row must satisfy total assets = liabilities +
equity, net loans = gross loans + signed provision, and net interest income =
interest income + signed interest expense. Minority-interest magnitude is
validated independently of its issuer-specific sign convention. When balance
and income sections have different publication dates, the later date is used so
the combined row cannot become visible early.

Only source `VietcapIQ/IQ/financial-statement/bank-ytd-v1` can be promoted into
`bank_financial_reports`; unknown/manual bank rows are never overwritten and
generic automated bank conventions remain staging-only. The direct harness now
emits distinct `AUTH_FAILURE`, `INSUFFICIENT_DATA`, or `UNSUPPORTED_SCHEMA`
verdicts. Authenticated securities/insurance payloads fail closed rather than
being mislabeled as authorization failures or corporate data.

Focused regression passed 118 tests; full regression passed 1015 tests in
51.68s. Live direct acceptance passed ACB and TPB
with 34 complete quarters, 34 actual publication dates and latest 2026Q2. VIX
returned the intended `UNSUPPORTED_SCHEMA`. Forced ACB refresh persisted 34 bank
quarters and coverage reports `FINANCIALS READY` with VietcapIQ provenance.

The IQ statement endpoint does not provide NPL or CAR. Those nullable prudential
inputs remain missing, so ASMF bank fundamental scoring stays unavailable rather
than fabricating neutral values. Securities and insurance need their own mapping
and strategy semantics in later, separate work. This bank-adapter follow-up is
complete; stop before those adapters.

### 2026-09-25 — Vietcap IQ securities BCTC adapter PASS

Live VIX evidence established 34 quarterly balance and income rows through
2026Q2. The populated securities namespaces are `bss`/`iss`, while the common
summary still provides valid `bsa`/`isa` totals. The adapter now maps net
operating revenue, total/parent profit, assets, liabilities, equity and
short/long borrowings. It validates assets = liabilities + equity, current plus
non-current liabilities, net revenue, and duplicated securities borrowing
fields before accepting a row.

SSI exposed four historical periods where `isa22` parent profit did not
reconcile with `isa20` total profit and minority interest. The adapter retains
the independently reported total profit but leaves parent profit null for those
periods. It does not invent an allocation or discard the complete BCTC period.

`ProviderResult.statement_schema` now survives `ProviderChain`. Refresh treats
`securities` as staging-only, records an explicit coverage diagnostic, and never
promotes it into the corporate ASMF model. A regression test caught that losing
this metadata would promote eight securities rows. Reconciliation now removes
only old `VietcapIQ/%` canonical rows for a confirmed securities symbol while
preserving manual or other-provider evidence.

Focused regression passed 123 tests; full regression passed 1020 tests in
36.76s. Direct live harnesses passed VIX and SSI
with 34 complete quarters, 34 actual publication dates and latest 2026Q2. Forced
sync stored 34 staging rows for each symbol with `promoted_to_canonical=0`.
Read-only SQLite verification confirmed zero IQ-owned canonical rows for both.
Coverage is intentionally `FINANCIALS PARTIAL` with reason `securities BCTC
staged; no compatible ASMF model is implemented`.

The acquisition adapter is complete. A securities-specific ASMF model is not
part of the current strategy design, so these statements remain contextual data
rather than a signal input. Insurance is the next separate adapter phase.

### 2026-09-25 — Vietcap IQ insurance BCTC adapter PASS

Live BVH and ABI payloads established a common 34-quarter insurance schema using
`bsi`/`isi`. The adapter maps `isi64` net insurance operating revenue plus
`isa20` total and `isa22` parent profit. It validates premium revenue in three
steps: gross written premium + assumed premium + reserve change = premium
revenue; premium revenue + deductions = net premium revenue; and net premium
revenue + legacy reserve change + commission/other income = net insurance
operating revenue.

The first BVH run produced only 20 complete quarters because 14 historical
forms did not split total liabilities into corporate-style current and
non-current totals. Runtime evidence showed the total balance still reconciled.
The insurance adapter therefore validates assets = liabilities + equity and,
when present, total resources = assets, while retaining explicit short/long loan
fields. It does not infer the missing liability allocation. After this change,
both BVH and ABI passed with 34 complete quarters, 34 actual publication dates
and latest period 2026Q2.

Insurance schema metadata follows the same fail-closed route as securities:
rows are stored in staging, never promoted into corporate/bank ASMF, and a
refresh removes only legacy IQ-owned canonical misclassifications. Forced sync
stored 34 rows each for BVH and ABI with `promoted_to_canonical=0`; SQLite
verification found zero IQ-owned canonical rows for both. Coverage intentionally
reports `FINANCIALS PARTIAL` because no insurance-specific ASMF model exists.

Verification completed with `126 passed` in the focused provider/refresh/live-
harness suite and `1023 passed in 31.24s` in the full repository suite.

The insurance acquisition adapter is complete. Building new industry-specific
fundamental scoring would be a separate strategy-design phase, not an extension
of data acquisition.

### 2026-09-25 — Vietcap IQ bank risk metrics PASS

The earlier bank adapter inspected only `financial-statement`, where NPL and
CAR were not available as normalized ratios. Audit of the current IQ frontend
bundle established the exact additional route
`/api/iq-insight-service/v1/company/{ticker}/statistics-financial`. Its
quarterly `RATIO_TTM` rows expose `npl`, `loansLossReservesToNPLs` and sparse
`car`; the separate `/financial-statement/metrics` route is only a statement
field dictionary and is not itself risk data.

The adapter now joins risk rows by exact year/quarter. It reconstructs the NPL
balance as `gross_loans * npl_ratio` only when the independently reported
coverage ratio reconciles with `abs(bsb105) / NPL`. CAR is accepted only when it
is a non-zero decimal ratio and is converted to percent. IQ annual
`quarter=5` rows are excluded, zero CAR is treated as missing, and neither CAR
nor any other prudential value is forward-filled. Combined canonical rows use
the versioned source
`VietcapIQ/IQ/financial-statement+statistics-financial/bank-ytd-risk-v2` and
retain the actual statement `publicDate` boundary.

Live ACB returned 34 complete statement quarters, 31 reconciled NPL quarters
and 6 disclosed CAR quarters. TPB returned 34, 30 and 6 respectively. Two
historical periods failed the LLR identity and stayed null. Forced sync stored
34 v2 canonical rows for each bank; coverage is `FINANCIALS READY`. Read-only
verification produced historical point-in-time ASMF scores at 2025-09-30 of
33.33 for ACB and 50.0 for TPB. The current 2026Q2 score remains `None` for both
because that quarter has no disclosed CAR; this is intended fail-closed
behavior, not an acquisition failure.

Focused provider/refresh/scoring/harness regression passed 137 tests. The full
repository suite initially failed during collection because the tracked manual
script `scripts/test_soi_asmf_live.py` built a credentialed runtime at import
time. Wrapping that behavior in `main()` preserved direct execution while
making pytest collection side-effect free. The final full suite passed 1025
tests in 49.56s.

The bank risk-metrics phase is complete. Current-quarter ASMF must remain
unavailable until Vietcap publishes a non-zero CAR for that quarter; using a
stale CAR would change strategy semantics and was not implemented.

### 2026-09-25 — FPT Vietcap IQ schema false-positive PASS

Live FPT began failing with 34 securities-borrowing identity warnings because
the IQ payload contains isolated non-zero `bsb108` and `bss136` fields alongside
its complete corporate `bsa`/`isa` statements. `_schema_kind()` previously used
`any bss OR any iss` for securities (and the same OR rule for insurance), so the
single `bss136` value won before the corporate branch. The securities mapper
then correctly rejected every FPT quarter because its `bss238`/`bss247` identity
was not a securities statement.

Industry detection now requires paired non-zero balance and income namespaces:
`bsb`+`isb` for banks, `bss`+`iss` for securities and `bsi`+`isi` for insurance.
This preserves fail-closed behavior when a section is missing and prevents a
lone cross-industry field from overriding valid corporate evidence. A regression
fixture reproduces the exact FPT `bsb108`/`bss136` payload shape.

Focused provider/harness regression passed 84 tests. The full repository suite
passed 1026 tests in 49.50s. Direct authenticated live checks passed FPT as
`schema=corporate`, VIX as `schema=securities`, and ABI as `schema=insurance`;
all three returned 34 complete quarters, 34 actual publication dates and latest
period 2026Q2. The false-positive fix is complete.

### 2026-09-25 — Current VN30 fixed-basket backtest PASS

The user requested VN30 backtests after `/performance` still showed the earlier
three-symbol CL1 run and one-symbol ASMF readiness run. The repository does not
store effective-dated VN30 membership, so the current basket was verified from
the SSIAM VN30 creation basket dated 2026-09-22 and used as an explicit fixed
30-symbol universe: ACB, BID, BSR, CTG, FPT, GAS, GVR, HDB, HPG, LPB, MBB, MCH,
MSN, MWG, SAB, SHB, SSB, SSI, STB, TCB, TCX, VCB, VHM, VIB, VIC, VJC, VNM, VPB,
VPL and VRE.

A read-only audit confirmed every constituent and VNINDEX has at least 200
completed local daily bars. Both strategies were run over 2026-06-01 through
2026-09-24 with the existing explicit two-trading-session settlement choice and
default costs.

- `vn30-current-cl1-20260925`: 1,872 decisions (21 BUY, 602 SELL, 1,249 WATCH),
  eight closed trades, two open positions, net total return -1.13%, maximum
  drawdown -1.29%, and VNINDEX return -4.95%.
- `vn30-current-asmf-20260925`: 1,872 decisions (1,852 BLOCKED, 20 WATCH), no
  trades, 1,582 decisions missing point-in-time financial quality and 1,759
  missing sector breadth. Return and drawdown remain NULL/N/A by design.

Repository and Telegram-formatter verification passed for both latest records;
`/performance CL1` and `/performance ASMF` now render `Universe: 30 mã`. Both
runs remain `IN_SAMPLE_ONLY`. The result is a current-constituent fixed-basket
test and therefore has survivorship bias; it must not be described as a
historically reconstituted VN30 backtest. No strategy code or fail-closed rule
was changed.

### 2026-09-25 — VN30 ASMF data-readiness follow-up split at external boundary

Forced FINANCIALS refresh completed for all 30 current VN30 constituents through
the production provider chain with 14 `SUCCESS`, 16 `PARTIAL`, and zero
`FAILED` outcomes. Corporate canonical data improved materially. Bank payloads
were retained when valid, but current scores still fail closed when Vietcap does
not disclose a usable current CAR or a risk identity fails. SSI and TCX remain
securities staging data because no securities-specific ASMF model exists.

At 2026-09-24, current Fundamental availability increased from 5/30 to 12/30:
FPT, GAS, GVR, HPG, MCH, MSN, MWG, SAB, VHM, VJC, VNM and VRE. The identical
fixed-basket ASMF backtest was rerun as
`vn30-current-asmf-refreshed-20260925`. It produced 1,872 decisions: 1,827
BLOCKED and 45 WATCH, with no trades. Missing Fundamental decisions fell from
1,582 to 1,076. Missing Sector decisions stayed at 1,759.

The unchanged Sector count is explained by verified effective dates rather than
download failure: all 30 VN30 symbols have membership rows, but every row begins
on the real observation date 2026-09-20. The Vietcap `getAll` catalog is a
current snapshot and has no observed historical-date parameter. Assigning that
snapshot to 2026-06-01 would violate the point-in-time ASMF contract and create
look-ahead bias, so it was not done.

This follow-up stops at a safe external-data/model boundary. Completion requires
a verified effective-dated historical sector source plus compatible Fundamental
semantics for the remaining symbols; missing values must not be converted to
neutral scores. The latest Telegram ASMF performance record remains the honest
30-symbol refreshed run and `IN_SAMPLE_ONLY`.

### 2026-09-25 — HOSE historical sector memberships imported; ASMF sector blocker largely cleared

The historical sector follow-up used HOSE VNAllshare Sector component
publications rather than backdating the current Vietcap classification snapshot.
The January 2026 publication is effective from 2026-02-02 and contains eight
sector tables directly. Its PDF omits the Real Estate and Utilities pages, so
those two tables were reconstructed by intersecting the July 2026 GICS sector
tables with the January 2026 VNAllshare eligibility table. The resulting 43
Real Estate and 13 Utilities constituents match the official April/May 2026
HOSE sector factsheet counts. The July 2026 publication supplies all ten sector
tables effective from 2026-08-03. The reconstruction is explicitly labelled
`HOSE/HOSE-Index/2026-01/derived-missing-pages`; it is not represented as a
directly printed January table.

Added `asmf_data.hose_sector_pdf` and
`scripts.import_hose_sector_pdf`. The parser recognizes the ten HOSE GICS sector
indices, handles continuation pages, excludes the separate "new industry, no
index" table, can filter against a VNAllshare eligibility PDF, validates
requested sector counts, and supports dry-run before database writes. Imported
243 direct January rows, 56 derived missing-page rows, and 312 July rows.

The identical current-constituent VN30 ASMF test (2026-06-01 through
2026-09-24) was persisted as `vn30-current-asmf-hose-sector-20260925`. It has
1,872 decisions: 1,102 BLOCKED and 770 WATCH, no trades. Missing Sector fell
from 1,759 to 26 decisions; missing Fundamental remains 1,076. Therefore the
historical sector work is accepted, while the active phase remains split solely
on compatible Fundamental semantics for the remaining 18 symbols. The run is
still `IN_SAMPLE_ONLY`, uses a fixed current VN30 basket, and retains
survivorship bias.

Verification:

- `py -3.12 -m pytest -q tests\\test_hose_sector_pdf.py tests\\test_asmf_data.py tests\\test_asmf_historical_adapter.py tests\\test_backtest_repository.py tests\\test_backtest_execution.py` — 35 passed.
- `py -3.12 -m pytest -q` — 1,031 passed.

