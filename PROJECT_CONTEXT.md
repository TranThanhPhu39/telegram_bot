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

Phase 14 — Scanner universe — COMPLETE. Development is stopped before Phase 15. Phases
3–7 remain pending live validation and may not be reported as PASS.

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
- [ ] Binary `w-match-price` event received from Vietcap
- [ ] Realtime FPT message decoded and validated
- [ ] Two distinct valid FPT ticks observed

## 5. Currently Working On

Phase 14 is complete. The scanner filters normalized HOSE/HNX/UPCoM instrument
metadata to active common stocks, applies a completed-history liquidity screen,
and builds a deterministic bounded realtime watch universe. Development stops
until the user explicitly opens Phase 15.
Phases 3–7 retain their pending live-validation status.

## 6. Files Created / Modified

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
Forced-interruption recovery remains NOT TESTED.

### `scripts/inspect_connection.py`

Purpose: human-readable connection smoke test with configurable hold time, timeout, and Engine.IO logs.

Status: direct script entry point verified; 35-second live smoke test passed without subscriptions.

### `scripts/__init__.py`

Purpose: marks the scripts namespace.

Status: created.

### `tests/test_client.py`

Purpose: verifies path normalization, WebSocket-only connection arguments, reconnect configuration, lifecycle handlers, idempotent disconnect, all stream registrations/subscriptions, duplicate suppression, and reset after disconnect without network access.

Status: all client tests pass as part of the 140-test suite.

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

Status: live subscription emission confirmed; Saturday test received zero events and exited incomplete.

### `scripts/test_realtime_market_state.py`

Purpose: bounded Phase 4 acceptance harness for FPT + ACB through the full
decode-to-cache path. Requires two distinct valid ticks per symbol by default.

Status: entry point and acceptance tracker unit-tested. Two live attempts failed
at WebSocket handshake with HTTP 503 before subscription.

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

Await explicit user authorization before opening Phase 15. Do not implement the
Telegram bot automatically.

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
