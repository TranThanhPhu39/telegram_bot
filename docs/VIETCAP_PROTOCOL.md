# Vietcap Market Data Protocol Notes

> Status: reverse-engineered from the normal Vietcap trading frontend. Treat as unstable/internal implementation detail.

## Realtime transport

Socket.IO / Engine.IO v4.

Observed WebSocket endpoint:

`wss://trading.vietcap.com.vn/ws/price/socket.io/?EIO=4&transport=websocket`

Observed:
- GET
- 101 Switching Protocols

Prefer `python-socketio`.

### Python runtime verification — 2026-09-19

Verified without account credentials using `python-socketio==5.17.0` and
`websocket-client==1.9.2`:

- base URL: `https://trading.vietcap.com.vn`
- `socketio_path`: `ws/price/socket.io`
- requested transport: WebSocket only
- negotiated URL included `transport=websocket&EIO=4`
- connection accepted with `upgrades: []`
- server `pingInterval`: 25,000 ms
- server `pingTimeout`: 20,000 ms
- server `maxPayload`: 1,000,000 bytes
- default Socket.IO namespace connected successfully
- server PING and client PONG observed after approximately 25 seconds
- connection remained stable for a 35-second smoke test
- clean namespace and Engine.IO disconnect completed

The Phase 2 smoke test emitted no market subscription events. Protocol logs
contained only the Socket.IO namespace handshake, Engine.IO heartbeat, and
disconnect packets.

### Phase 7 reconnect handling

The Python client now creates `socketio.Client(reconnection=True)`, enabling the
library's reconnect handling after an established connection is lost. Explicit
parameters are `reconnection_attempts=0`, `reconnection_delay=1`,
`reconnection_delay_max=30`, and `randomization_factor=0.5`. In the pinned
library, zero attempts means no attempt limit; delay doubles up to the cap and
includes jitter. Active subscription markers are cleared on disconnect, while
normalized desired symbol lists are retained. After reconnect the client restores
match-price, index, and bid-ask subscriptions independently. This behavior is
unit-tested. Three simulated reconnect cycles also confirm reconnect does not
register duplicate lifecycle or market-data listeners. These offline tests are not
yet evidence that streams resume after a real interruption.

Malformed binary frames for `w-match-price`, `index`, and `w-bid-ask` are wrapped
as explicit decoder errors and rejected by their pipeline boundaries. Offline
tests confirm a rejected frame does not mutate state or prevent the immediately
following valid frame from being processed. Actual malformed provider frames have
not been observed.

Raw debug mode is opt-in through `VietcapRealtimeClient(raw_debug=True)` or the
`--raw-debug` option on each realtime acceptance script. It records only event
name, payload type, payload size, sequence number, and configured per-event limit;
raw binary content is never logged. The default limit is 20 records per event and
can be changed with `raw_debug_event_limit` or `--raw-debug-event-limit`.

## Proto

Frontend loads:

`/protos/price.proto?v=<APP_VERSION>`

Package:

`pricePackage`

Worker behavior:
- `protobuf.load(protoUrl)`
- `protoRoot.lookupType(...)`
- decode binary via protobuf
- cache/batch before returning decoded events

## Key protobuf schemas

### IndexMessage

```proto
message IndexMessage {
    string code = 1;
    string symbol = 2;
    double price = 3;
    double change = 4;
    double changePercent = 5;
    double totalShares = 6;
    double totalValue = 7;
    double totalStockIncrease = 8;
    double totalStockDecline = 9;
    double totalStockNoChange = 10;
    double totalStockCeiling = 11;
    double totalStockFloor = 12;
    double estimatedChange = 13;
    double estimatedFsp = 14;
    string time = 15;
}
```

### MatchPriceMessage

```proto
message MatchPriceMessage {
    string type = 1;
    string code = 2;
    string symbol = 3;
    double matchPrice = 4;
    double matchVol = 5;
    double highest = 6;
    double lowest = 7;
    double foreignBuyVolume = 8;
    double foreignSellVolume = 9;
    double foreignBuyValue = 10;
    double foreignSellValue = 11;
    string session = 12;
    double referencePrice = 13;
    double ceilingPrice = 14;
    double floorPrice = 15;
    double accumulatedVolume = 16;
    double avgMatchPrice = 17;
    string time = 18;
    double openPrice = 19;
    double totalBuyOrders = 20;
    double totalSellOrders = 21;
    double currentRoom = 22;
    double totalRoom = 23;
    double accumulatedValue = 24;
    string matchType = 25;
    bool isMatchPrice = 26;
    bool isRE = 27;
    double bidCount = 29;
    double askCount = 30;
}
```

### BidAskPrice / BidAskMessage

```proto
message BidAskPrice {
    double price = 1;
    double volume = 2;
}

message BidAskMessage {
    string type = 1;
    string code = 2;
    string symbol = 3;
    repeated BidAskPrice bidPrices = 4;
    repeated BidAskPrice askPrices = 5;
    string session = 6;
    double bidCount = 7;
    double askCount = 8;
}
```

## Event mapping observed

| Socket event | messageKey | Internal key |
|---|---|---|
| `w-bid-ask` | `bidAskMessageProto` | `bidAsk` |
| `w-match-price` | `matchPriceMessageProto` | `matchPrice` |
| `odd-lot-bid-ask` | `oddLotBidAskMessageProto` | `oddLotBidAsk` |
| `odd-lot-match-price` | `oddLotMatchPriceMessageProto` | `oddLotMatchPrice` |
| `index` | `indexMessageProto` | `indexes` |
| `put-through` | `putThroughMessageProto` | `putThrough` |
| `advertise` | `advertiseMessageProto` | `advertise` |
| `batch-job-streaming` | `batchJobStreaming` | `batchJobStreaming` |
| `market-status` | `marketStatus` | `marketStatus` |

## Subscription examples observed

Stock streams use payload shape:

```json
{"symbols":["FPT","ACB"]}
```

Index stream observed symbols:

```json
{
  "symbols": [
    "HNX30",
    "HNXIndex",
    "HNXUpcomIndex",
    "VN30",
    "VNINDEX"
  ]
}
```

Important:
Frontend sends the payload as a JSON string in Socket.IO emit.

### Python FPT subscription attempt — 2026-09-19

Confirmed client emission over the live connection:

```text
event: w-match-price
payload type: JSON string
payload: {"symbols":["FPT"]}
Socket.IO packet: 2["w-match-price","{\"symbols\":[\"FPT\"]}"]
```

Only `FPT` was included. The connection remained healthy through a heartbeat,
but the server sent no `w-match-price` event during the 40-second observation.
The test was run on Saturday, outside the normal trading week, so binary payload
shape and live protobuf mapping are still NOT TESTED. Phase 3 remains open.

### Current frontend contract verification — 2026-09-19

The public price-board bundle was fetched successfully from the import map:

`/trading/main.js?v=49266848e71be948c3ac9a4a547e9ef01717248b`

Observed bundle metadata:

- response size: `1,524,144` bytes
- `CI_COMMIT_SHA`: `49266848e71be948c3ac9a4a547e9ef01717248b`
- `APP_VERSION`: `1789116678129`

The current bundle confirms all Phase 3 client assumptions:

- `MATCH_PRICE` resolves to `w-match-price`
- `subscribeMatchPrice` emits `JSON.stringify({symbols: symbols})`
- the event maps to `matchPriceMessageProto`
- that key maps to `pricePackage.MatchPriceMessage`
- the event listener passes the received payload to the decoder
- the decoder uses `decode(new Uint8Array(payload))`
- the current socket path is `/ws/price/socket.io`
- the frontend requests `transports: ["websocket"]`

This verifies the current frontend contract, but it does not replace the Phase 3
acceptance requirement to receive and decode changing FPT frames in Python.

### Phase 4 offline subscription coverage — 2026-09-19

The client now supports the exact combined payload:

```json
{"symbols":["FPT","ACB"]}
```

Symbols are trimmed, uppercased, and deduplicated while preserving first-seen
order. The client also suppresses a repeated subscription when the normalized
symbol set has not changed, regardless of input order, and clears that local
state after disconnect. These behaviors are unit-tested only; simultaneous live
FPT + ACB delivery remains NOT TESTED while the market is closed.

### Match-price normalization

Validated `MatchPriceMessage` objects are converted to the provider-independent
immutable `TradeTick` model. The mapping preserves the provider's numeric units;
no price scaling is applied. Empty time/session strings and zero-valued optional
snapshot prices are represented as `None`. Exchange time is deliberately not
parsed until its live format and timezone are observed.

### Phase 4 FPT + ACB acceptance harness — 2026-09-19

`scripts/test_realtime_market_state.py` subscribes to FPT and ACB, routes binary
events through decode, normalization, and `LatestMarketState`, and requires two
distinct valid ticks for each symbol before reporting PASS. The handler pipeline
and acceptance counter are covered by deterministic unit tests.

Two live attempts at approximately 14:24 +07:00 failed before Socket.IO
connection/subscription because the WebSocket handshake returned HTTP 503. The
response reported an upstream connection refusal. Consequently, combined event
delivery, binary decoding, and live cache updates remain NOT TESTED.

### Phase 5 index-stream offline coverage — 2026-09-19

Implemented from the vendored `price.proto` and the event table above:

- socket event: `index`
- payload shape: JSON string, same `{"symbols":[...]}` envelope as stock streams
- Phase 5 subscription: `{"symbols":["VNINDEX"]}`
- decoded type: `pricePackage.IndexMessage`

Index identifiers are case-sensitive in the observed frontend payload
(`HNXIndex`, `HNXUpcomIndex`), so index subscription symbols are trimmed and
de-duplicated case-insensitively but keep their first-seen provider casing.
Stock symbols continue to be upper-cased. Normalized `IndexSnapshot` identifiers
are upper-cased for state keying only.

Mapped fields (schema-supported only):

| Proto field | Normalized field |
|---|---|
| `symbol` | `symbol` (upper-cased) |
| `price` | `value` |
| `change` | `change` |
| `changePercent` | `change_percent` |
| `totalShares` | `total_volume` |
| `totalValue` | `total_value` |
| `totalStockIncrease` | `advances` |
| `totalStockDecline` | `declines` |
| `totalStockNoChange` | `unchanged` |
| `totalStockCeiling` | `ceiling_count` |
| `totalStockFloor` | `floor_count` |
| `time` | `exchange_time` (empty string becomes `None`) |

Not mapped: `code`, `estimatedChange`, `estimatedFsp`. Their semantics are not
documented by the schema or by observed protocol evidence.

Breadth validation enforces only schema-supported constraints: each breadth
counter must be finite, non-negative, and a whole stock count. Relationships
between counters — for example whether a ceiling stock is also counted as an
advancing stock — are NOT asserted, because they are undocumented. `change` and
`changePercent` may be negative or zero and are only checked for finiteness.
Provider numeric units are preserved; no scaling is applied.

`scripts/test_realtime_index.py` subscribes to VNINDEX, routes binary events
through decode, normalization, and `LatestIndexState`, and requires two distinct
valid snapshots before reporting PASS. Only its offline logic is tested. Live
VNINDEX delivery, binary payload shape, and `time` format remain NOT TESTED.

### Phase 6 bid-ask offline coverage — 2026-09-19

Implemented from the vendored `price.proto` and the event table above:

- socket event: `w-bid-ask`
- payload shape: JSON string, `{"symbols":["FPT","ACB"]}`
- decoded type: `pricePackage.BidAskMessage`

Stock symbols are upper-cased, de-duplicated, and suppressed when the
normalized set is unchanged, reusing the Phase 4 subscription helper. The
bid-ask subscription state is tracked independently from the match-price and
index subscriptions and is cleared on disconnect.

Mapped fields (schema-supported only):

| Proto field | Normalized field |
|---|---|
| `symbol` | `symbol` (upper-cased) |
| `bidPrices[]` | `bids[]` as `OrderBookLevel(price, volume)` |
| `askPrices[]` | `asks[]` as `OrderBookLevel(price, volume)` |
| `session` | `session` (empty string becomes `None`) |

Not mapped: `type`, `code`, `bidCount`, `askCount`. The two count fields also
appear in `MatchPriceMessage`, but no observed evidence defines whether they
count orders, levels, or something else.

Level validation enforces only schema-supported constraints: every level price
must be finite and positive, every level volume finite and non-negative, and a
side must not repeat the same price. Deliberately NOT asserted:

- level ordering, because the schema documents no sort order; provider order is
  preserved as received
- a non-crossed book, because Vietnamese ATO/ATC auction sessions can
  legitimately produce a crossed book
- a fixed depth, because proto3 permits an empty repeated field; an empty side
  normalizes to an empty tuple

`scripts/test_realtime_bidask.py` subscribes FPT and ACB to `w-bid-ask`, routes
binary events through decode, normalization, and `LatestOrderBookState`, and
requires two distinct valid books per symbol before reporting PASS. Only its
offline logic is tested. Live delivery, real binary payload shape, actual depth,
and level ordering remain NOT TESTED.

## Historical REST

Endpoint:

`POST https://trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart`

Example:

```json
{
  "timeFrame": "ONE_DAY",
  "symbols": ["ACB"],
  "countBack": 1996,
  "to": 1789787719
}
```

Observed timeframes:
- `ONE_MINUTE`
- `ONE_HOUR`
- `ONE_DAY`

The Python boundary exposes these exact values through `VietcapTimeFrame` and
rejects other identifiers before network I/O. This is offline request-contract
support, not evidence that the endpoint currently returns data for each interval.

Response is columnar arrays and must be normalized to bars.

### Authenticated-browser response evidence — 2026-09-19

The user observed HTTP 200 for an authenticated browser request with
`ONE_DAY`, `ACB`, `countBack: 170`, and `to: 1790035200`. The top level was an
array containing one object per symbol. The ACB object contained 170 entries in
each of `o`, `h`, `l`, `c`, `v`, `t`, `accumulatedVolume`, and
`accumulatedValue`. Observed normalized fields are:

| Response key | Meaning |
|---|---|
| `symbol` | stock symbol |
| `t` | Unix timestamp in seconds, encoded as a decimal string |
| `o` | open price |
| `h` | high price |
| `l` | low price |
| `c` | close price |
| `v` | volume |

`accumulatedVolume`, `accumulatedValue`, and `minBatchTruncTime` are preserved
in the provider response but are not part of the minimal `OHLCVBar` model.
The response contained no credential material. Direct Python acquisition with
the browser's authentication context remains NOT TESTED.

### Authenticated Python probe — 2026-09-19

The client sent the user-configured `Authorization` and `device-id` values plus
the observed `Origin` and `Referer`, without logging any secret value. Vietcap
still returned HTTP 400. Therefore authorization plus device ID alone is not
proven sufficient. The browser's `Cookie` header, token freshness, or another
session-bound condition may be required. No cookie was captured automatically.

The client now accepts an optional user-supplied `Cookie` header through local
runtime configuration. It never reads browser storage, logs cookie contents, or
persists them in tracked files. A live replay used authorization, device ID,
cookie, and the exact observed `countBack: 170` / `to: 1790035200` payload, but
still received HTTP 400. Secret-shape checks confirmed a Bearer authorization and
an intact multi-pair cookie without revealing their values. Another browser
header, TLS/browser fingerprint, or session-bound condition remains possible.

### Successful authenticated Python probe — 2026-09-19

After reproducing the observed non-secret browser headers and current request
payload (`ONE_MINUTE`, ACB, `countBack: 121`, `to: 1789830754`), Python received
HTTP 200 and normalized 121 bars. The observed timestamp range was
`1789703880..1789717500`. Authorization, device ID, and cookie came exclusively
from ignored local `.env` values and were not printed. This is runtime evidence
that historical bars can be fetched and normalized outside the browser, while
the internal endpoint and session credentials remain unstable implementation
details.

### Python gap-chart probe — 2026-09-19

An unauthenticated POST for two `ACB` `ONE_DAY` bars, using the documented four
JSON keys, returned HTTP 400 with an empty HTML body. Request construction and
error handling are covered offline, but successful historical retrieval,
timeframe behavior, and response-column semantics remain NOT TESTED.

## Quote REST

Observed:

`GET https://trading.vietcap.com.vn/api/price/v1/w/priceboard/ticker/price/{SYMBOL}`

Use for snapshot/fallback/validation, not high-frequency polling.

### Python quote probe — 2026-09-19

An unauthenticated GET for `FPT` returned HTTP 400 with an empty HTML body. The
client therefore implements the documented request boundary and error handling,
but does not assume any quote response fields. Successful live quote retrieval
and response-field semantics remain NOT TESTED.

## V1 required streams

Implement first:
1. `w-match-price`
2. `index`
3. `market-status` if easy

Then:
4. `w-bid-ask`

Skip initially:
- put-through
- odd-lot
- buy-in
- bonds
- carbon
- advertise

## Security
Historical REST currently requires user-supplied browser-session credentials.
Keep them only in ignored local configuration; never commit, log, or place them
in fixtures. Do not automate username/password login or persist refresh tokens.
