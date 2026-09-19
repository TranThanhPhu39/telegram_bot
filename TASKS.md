# TASKS.md

> Rule: Codex must work inside the ACTIVE IMPLEMENTATION PHASE.
> By default, Codex must implement and verify that whole phase in one iteration.
> Split it into smaller task groups only after a concrete failure, blocker,
> unresolved external dependency, or material technical/safety risk is encountered;
> record the reason in `PROJECT_CONTEXT.md`.
> A previous phase may remain under PENDING LIVE VALIDATION when its only blocker
> is an unavailable external runtime condition and the user explicitly authorizes
> offline development of the next phase.
> Pending live checks must remain unchecked and must not be reported as PASS.

## PENDING LIVE VALIDATION
**Phase 3 — Realtime Match Price: FPT only**

Reason: market closed on Saturday 2026-09-19. Live receive/decode/validation
must be rerun during an active Vietnamese market session.

**Phase 4 — Realtime ACB + Market State**

Reason: live attempts on 2026-09-19 failed at the WebSocket handshake with
HTTP 503 before subscription. Simultaneous live FPT + ACB delivery must be
rerun during an active Vietnamese market session.

**Phase 5 — Index stream**

Reason: offline implementation and tests are complete, but VNINDEX realtime
acceptance remains NOT TESTED. `scripts/test_realtime_index.py` must report
`[PASS]` during an active Vietnamese market session.

**Phase 6 — Bid/Ask**

Reason: offline implementation and tests are complete, but realtime order-book
acceptance remains NOT TESTED. `scripts/test_realtime_bidask.py` must report
`[PASS]` during an active Vietnamese market session.

**Phase 7 — Reliability**

Reason: offline implementation is complete, but acceptance requires a real
market stream to resume after a forced transport interruption. This remains
NOT TESTED until an active Vietnamese market session.

## ACTIVE IMPLEMENTATION PHASE
**Phase 15 — Telegram Bot (COMPLETE; stopped before Phase 16)**
---

## Phase 0 — Repository bootstrap & planning
- [x] Inspect repository structure
- [x] Inspect Python version and dependencies
- [x] Create missing package folders without overbuilding
- [x] Create/update `PROJECT_CONTEXT.md`
- [x] Create/update `.env.example`
- [x] Create/update `.gitignore`
- [x] Confirm safe integration point for Vietcap provider
- [x] Write implementation plan for Phase 1
- [x] STOP and report

Acceptance:
- Repository understood
- No large feature code written
- Context/docs updated

---

## Phase 1 — Vietcap protocol assets & protobuf
- [x] Add/fetch `price.proto`
- [x] Verify package `pricePackage`
- [x] Verify `MatchPriceMessage`
- [x] Verify `BidAskMessage`
- [x] Verify `IndexMessage`
- [x] Generate/load Python protobuf classes
- [x] Add unit test for protobuf imports/instantiation
- [x] STOP and report

Acceptance:
- Protobuf types load without runtime/import errors

---

## Phase 2 — Vietcap Socket.IO connection only
- [x] Connect to Vietcap Socket.IO
- [x] Log connect/disconnect
- [x] Confirm Engine.IO v4 / Socket.IO client compatibility
- [x] No market subscriptions yet
- [x] Add connection smoke test
- [x] STOP and report

Acceptance:
- Stable connection can be established

---

## Phase 3 — Realtime Match Price: FPT only
- [x] Subscribe only FPT to `w-match-price`
- [ ] Receive binary event
- [ ] Decode using MatchPrice protobuf
- [ ] Print normalized FPT tick
- [ ] Validate price/volume fields
- [ ] STOP and report

Acceptance:
- Valid changing FPT realtime ticks observed

---

## Phase 4 — Realtime ACB + Market State
- [x] Add ACB subscription
- [x] Prevent duplicate symbol subscriptions
- [x] Create normalized `TradeTick`
- [x] Create latest market-state cache
- [ ] Test FPT + ACB simultaneously
  - Offline harness and handler tests PASS; live attempts on 2026-09-19 failed
    at WebSocket handshake with HTTP 503 before subscription.
- [ ] STOP and report

Acceptance:
- FPT and ACB update correctly in normalized form

---

## Phase 5 — Index stream
- [x] Subscribe VNINDEX
  - Offline only: `index` event registration and the exact
    `{"symbols":["VNINDEX"]}` JSON-string emission are unit-tested. Live
    emission over a real session is NOT TESTED.
- [x] Decode `IndexMessage`
  - Offline only: binary decode and malformed-payload rejection are
    unit-tested against the vendored schema. Live frames are NOT TESTED.
- [x] Normalize `IndexSnapshot`
- [x] Validate breadth fields
- [ ] STOP and report

Acceptance:
- VNINDEX realtime state available
  - NOT TESTED. Requires `scripts/test_realtime_index.py` to report `[PASS]`
    during an active Vietnamese market session.

---

## Phase 6 — Bid/Ask
- [x] Subscribe FPT + ACB to `w-bid-ask`
  - Offline only: `w-bid-ask` listener registration and the exact
    `{"symbols":["FPT","ACB"]}` JSON-string emission are unit-tested. Live
    emission over a real session is NOT TESTED.
- [x] Decode `BidAskMessage`
  - Offline only: binary decode and malformed-payload rejection are
    unit-tested against the vendored schema. Live frames are NOT TESTED.
- [x] Normalize `OrderBook`
- [x] Validate bid/ask levels
- [ ] STOP and report

Acceptance:
- Valid order book updates decoded
  - NOT TESTED. Requires `scripts/test_realtime_bidask.py` to report `[PASS]`
    during an active Vietnamese market session.

---

## Phase 7 — Reliability
- [x] Reconnect handling
- [x] Exponential/reasonable retry
- [x] Re-subscribe after reconnect
- [x] No duplicate listeners
- [x] Decode error handling
- [x] Raw debug mode
- [ ] STOP and report

Acceptance:
- Stream resumes after forced interruption

---

## Phase 8 — Historical REST
- [x] Implement quote endpoint
- [x] Implement OHLC `gap-chart`
- [x] Support ONE_MINUTE
- [x] Support ONE_HOUR
- [x] Support ONE_DAY
- [x] Normalize OHLCV
  - Verified from an authenticated-browser HTTP 200 response: `t/o/h/l/c/v`
    arrays normalize to immutable `OHLCVBar` values.
- [x] Add fixtures/tests
- [x] STOP and report

Acceptance:
- Historical bars can be fetched and normalized
  - PASS: authenticated Python fetched and normalized 121 ACB `ONE_MINUTE`
    bars using the exact observed browser request contract.

---

## Phase 9 — Database
- [x] Choose SQLite for V1 unless repo already uses another DB
- [x] Create symbols table
- [x] Create candles table
- [x] Create signals table
- [x] Create signal_events table
- [x] Add migrations/schema bootstrap
- [x] STOP and report

---

## Phase 10 — Candle & indicators
- [x] 1-minute bar builder
- [x] EMA20
- [x] EMA50
- [x] RSI14
- [x] ATR14
- [x] daily average volume
- [x] Relative Strength vs VNINDEX
- [x] Breakout levels
- [x] STOP and report

---

## Phase 11 — Intraday RVOL
- [x] Define time-matched RVOL
- [x] Historical baseline by same intraday time
- [x] Validate no look-ahead
- [x] Unit tests
- [x] STOP and report

---

## Phase 12 — Market Regime
- [x] VNINDEX trend
- [x] Breadth using advance/decline
- [x] Bull/Neutral/Bear states
- [x] Tests
- [x] STOP and report

---

## Phase 13 — Signal Engine V1
- [x] WATCH state
- [x] MONEY_FLOW state
- [x] BREAKOUT state
- [x] CONFIRMED state
- [x] ACTIVE state
- [x] EXIT state
- [x] Reason/explanation payload
- [x] Cooldown/dedup
- [x] STOP and report

---

## Phase 14 — Scanner universe
- [x] Universe HOSE + HNX + UPCoM
- [x] Common stocks only
- [x] Liquidity filter
- [x] Daily pre-screen
- [x] Realtime watch universe
- [x] STOP and report

---

## Phase 15 — Telegram Bot
- [x] BotFather token via `.env`
- [x] `/start`
- [x] `/help`
- [x] `/soi FPT`
- [x] `/scan`
- [x] `/market`
- [x] `/why FPT`
- [x] auto alerts
- [x] STOP and report

---

## Phase 16 — Backtest & performance
- [ ] Shared live/backtest strategy code
- [ ] 3–6 month preliminary backtest
- [ ] Win rate
- [ ] Average return
- [ ] Max drawdown
- [ ] Profit factor
- [ ] `/performance`
- [ ] STOP and report

---

## Phase 17 — Fundamental filter
- [ ] Select data source
- [ ] EPS
- [ ] P/E
- [ ] P/B
- [ ] ROE
- [ ] revenue/profit growth
- [ ] Integrate as filter/context, not uncontrolled signal
- [ ] STOP and report

---

## Phase 18 — News V1 (optional / bonus)
- [ ] News collector
- [ ] Deduplication
- [ ] ticker/entity mapping
- [ ] sentiment/event classification
- [ ] Telegram news alert
- [ ] STOP and report

## Explicitly out of V1
- Real order placement
- Automated brokerage execution
- ML price prediction
- Full news intelligence before core bot works
