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

Response is columnar arrays and must be normalized to bars.

## Quote REST

Observed:

`GET https://trading.vietcap.com.vn/api/price/v1/w/priceboard/ticker/price/{SYMBOL}`

Use for snapshot/fallback/validation, not high-frequency polling.

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
No account credentials are required in project config unless later proven necessary.
Do not persist cookies/tokens captured from the browser.
