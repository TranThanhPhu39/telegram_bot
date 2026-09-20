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
**Phase 20 operational follow-up — sector-sync completion notifications (COMPLETE)**
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
- [x] Shared live/backtest strategy code
- [x] 3–6 month preliminary backtest
- [x] Win rate
- [x] Average return
- [x] Max drawdown
- [x] Profit factor
- [x] `/performance`
- [x] STOP and report

Preliminary evidence: separate authenticated ACB and VNINDEX `ONE_DAY` requests
returned 170 aligned bars. The latest 120 aligned sessions span 175 calendar
days. The explicitly limited daily-proxy run produced zero closed trades, 0%
win rate/average return/max drawdown, and undefined profit factor. This is valid
zero-activity evidence, not a profitability claim or final live-strategy result.

---

## Phase 17 — Fundamental filter
- [x] Select data source
- [x] EPS
- [x] P/E
- [x] P/B
- [x] ROE
- [x] revenue/profit growth
- [x] Integrate as filter/context, not uncontrolled signal
- [x] STOP and report

V1 source decision: controlled UTF-8 CSV snapshots with mandatory per-row source
provenance and as-of date. No unstable or unlicensed fundamentals API is assumed.

---

## Phase 18 — Runtime bot integration
- [x] Connect Telegram commands to Vietcap historical REST
- [x] Persist and read normalized daily bars through SQLite
- [x] Use latest completed session when market is closed
- [x] Connect indicators and scanner to command responses
- [x] Preserve honest unavailable/partial-data messages
- [x] Live Sunday smoke test for `/soi` and `/market`
- [x] STOP and report

Acceptance evidence: on Sunday 2026-09-20, the runtime returned ACB and VNINDEX
data for the latest completed session, Friday 2026-09-18. ACB included close,
volume, EMA20, EMA50, and RSI14; VNINDEX included close and EMA trend. Breadth
was explicitly reported unavailable rather than inferred.

---

## Phase 19 — Selectable CL1 + ASMF strategies
- [x] Keep CL1 and ASMF as independent selectable strategies
- [x] Implement CL1 EMA/RSI/ADX/volume/MA200 entry conditions
- [x] Implement CL1 EMA cross-down and Chandelier exit conditions
- [x] Implement ASMF market-regime and price-volume footprint layers
- [x] Block ASMF BUY when sector/fundamental/institutional data is missing
- [x] Reuse pure strategy functions for runtime and future backtests
- [x] Add `/chienluoc` and `/soi <MÃ> [CL1|ASMF]`
- [x] Verify CL1 and ASMF against live ACB/VNINDEX history
- [x] STOP and report

Acceptance evidence: 385 offline tests passed. Live Vietcap history for ACB and
VNINDEX dated 2026-09-18 produced an explainable CL1 WATCH and an ASMF
CHƯA ĐỦ ĐIỀU KIỆN response listing the three missing data layers. No ASMF BUY
was fabricated from incomplete inputs.

---

## Phase 20 — ASMF EOD data integration
- [x] Add point-in-time sector membership storage
- [x] Add consolidated quarterly financial-report storage with `public_date`
- [x] Add foreign/proprietary daily-flow storage
- [x] Add strict normalized CSV import boundary
- [x] Add sector, fundamental, and institutional-flow scoring
- [x] Connect stored scores to the shared ASMF runtime
- [x] Add schema migration and no-look-ahead tests
- [x] Add automatic Vietstock document discovery adapter
  - Live verified for ACB: runtime CSRF/cookie acquisition and page-1 JSON list.
- [x] Normalize Vietstock document metadata and filter consolidated reports
- [x] Add bank-specific point-in-time financial schema and CSV import
- [x] Add bank-specific ASMF score (ROE/NII/profit/NPL/coverage/CAR)
- [x] Prevent industrial debt/equity rules from being applied to banks
  - Incomplete bank rows remain unavailable and cannot fall back to the
    industrial-company score.
- [x] Add bounded, streamed Vietstock PDF/ZIP download validation
  - Uses an atomic `.part` file, a 100 MiB limit, signature checks, and ZIP path
    safety checks; malformed responses are not retained.
- [x] Classify downloaded PDF/ZIP reports before extraction
  - Real ACB H1 2026 PDF: 96 pages, zero text characters, 96 embedded images;
    correctly routed to `ocr_required` rather than parsed as text.
- [x] Acquire and validate real sector membership data
  - Vietcap `getAll` snapshot on 2026-09-20 normalized 1,523 ICB2 memberships
    and was imported into runtime SQLite. ACB has code 8300 with 28 members.
- [x] Connect sector-member daily price histories to the ASMF Telegram runtime
  - A background synchronizer fetches one member at a time with exponential
    retry/backoff and persists every successful history immediately.
  - `/soi ... ASMF` reads peer histories only from SQLite and never waits for
    sector-member network calls. The bot starts a six-hour periodic sync worker.
  - Live acceptance: NOT TESTED successfully on 2026-09-20 because Vietcap
    `gap-chart` timed out after 20 seconds; offline integration tests pass.
- [x] Extract normalized financial statement values from PDF/ZIP contents
  - Tesseract `vie+eng` extracts verified ACB B02a/B03a values and NPL as the
    checked sum of groups 3–5. CAR is not present in this report and remains NULL.
- [x] Validate a real imported dataset
  - ACB 2026Q2 OCR fixture imports into SQLite and reads back six verified
    values without fabricating unavailable CAR.
- [x] STOP and report

### Operational follow-up — arbitrary symbols
- [x] Queue sector-history synchronization when `/soi <symbol> ASMF` requests a
      valid symbol outside `BOT_WATCH_SYMBOLS`
- [x] Queue the same non-blocking synchronization from `/sector <symbol>`
- [x] Deduplicate in-flight requests and apply an on-demand cooldown
- [x] Bound each worker pass to eight uncached members by default
- [x] Show cached-sector progress and queue state without changing ASMF scoring
- [x] Verify that an arbitrary symbol clears structural `Sector=MISSING` after
      at least five real peer histories are cached
- [x] Run focused and full regression tests
  - Focused runtime/worker/Telegram regression: 54 passed.
  - Full isolated-dependency regression: 594 passed.
  - Isolated dependency check: `No broken requirements found`.
- [x] STOP and report

### Operational follow-up — Telegram completion notifications
- [x] Register the requesting chat before `/soi ... ASMF`, `/sector`, or the
      ASMF inline callback starts sector synchronization
- [x] Publish worker results without coupling the worker to Telegram
- [x] Notify once when a batch remains incomplete and once when it becomes ready
- [x] Retain the latest incomplete result so late subscribers are not left silent
- [x] Add a `Xem lại ASMF` callback button instead of replaying stale analysis
- [x] Requeue failed Telegram deliveries and deduplicate per chat/symbol
- [x] Start and stop the async notification dispatcher with the Telegram app
- [x] Run focused and full regression tests
  - Focused notification/worker/Telegram regression: 59 passed.
  - Full isolated-dependency regression: 599 passed.
- [x] STOP and report

---

## Phase 21 — News & Transformer Sentiment Integration
- [x] Audit current bot and supplied News/Sentiment ZIP
  - ZIP baseline: 68 tests passed on Python 3.12.
- [x] Create an integration map and dependency/model decision
  - Selected default candidate: `FiinGroup/phobert-finetuned`; its model card
    states 3-class training on about 15,000 Vietnamese financial-news records.
- [x] Restructure/import provider-independent news core
- [x] Preserve/migrate all relevant legacy tests
- [x] Introduce pluggable `SentimentModel` interface
- [x] Preserve lexicon backend and explicit fallback
- [x] Add configurable PhoBERT backend with probability metadata
- [x] Add backward-compatible news SQLite migration
  - Separate news DB retains legacy rows and adds probabilities, backend/model
    metadata, analysis timestamp, calibration slot, and ticker relevance.
- [x] Preserve event classifier, ticker relevance, dedup, and time decay
- [x] Wire `SentimentQueryService` into `RuntimeBotDataService`
- [x] Add `/tin <MÃ>` and `/sentiment <MÃ>`
- [x] Add optional sentiment sections to `/soi` and `/market`
- [x] Add ASMF context and configurable severe-negative-event blocker
- [x] Route news alerts through the existing alert boundary
- [x] Add bounded one-shot ingestion and benchmark framework
- [x] Install/check transformer dependencies and validate model loading
  - Clean `.venv-phase21`: `pip check` PASS; real CPU inference loaded
    `FiinGroup/phobert-finetuned`, returned three probabilities summing to 1.
- [x] Run focused, legacy, full-regression, and `pip check`
- [x] Run bounded live CafeF/model acceptance or mark NOT TESTED
- [x] STOP and report

## Explicitly out of V1
- Real order placement
- Automated brokerage execution
- ML price prediction
- Full news intelligence before core bot works

---

## Phase 22 — Investor dashboard, explainability & data provenance
- [x] Introduce a presentation-free view-model layer (`runtime/views.py`)
- [x] Add pure analysis builders (`runtime/analysis.py`)
- [x] Move all Telegram rendering into `telegram_bot/formatters.py`
- [x] Rebuild `/soi` as a compact dashboard with price, technical, market,
      strategy, fundamental, news and data-quality sections
- [x] Expose support/resistance levels with their reasons
- [x] Rebuild `/why` as indicator → meaning → implication with triggers and
      data limitations
- [x] Rebuild `/market` with explicit unavailable breadth/liquidity/flow
- [x] Show freshness, session date, staleness and source on every response
- [x] Label SQLite fallback as cached/EOD
- [x] Expose point-in-time fundamentals with as-of date and source
- [x] Add `/technical`, `/fundamental`, `/sector`
- [x] Expose ASMF layer status (PASS/FAIL/MISSING) plus a sentiment context layer
- [x] Explain scanner results instead of returning a bare ticker list
- [x] Separate ENGINE TEST from STRATEGY VALIDATION in `/performance`
- [x] Add an inline keyboard for `/soi` without bypassing any text command
- [x] Add evidence to signal alerts while preserving dedup
- [x] Keep all pre-existing tests passing and add new coverage
  - Offline: 459 passed on Python 3.12 (422 pre-existing + 37 new).
- [ ] Live acceptance of `/soi`, `/market`, `/sentiment` during a session
  - NOT TESTED. The build environment has no route to Vietcap, CafeF or
    Telegram. Must be rerun locally with real credentials during an active
    Vietnamese market session.


---

## Phase 23 — Portfolio, Risk & Watchlist
- [x] Add user persistence (`users`, keyed by Telegram numeric id)
- [x] Add portfolio schema migrations
  - v4 `portfolio_watchlist_holdings`: users, watchlist and holdings.
  - v5 `portfolio_exact_decimals`: additive exact Decimal text with v4 backfill.
- [x] Add persistent watchlist
- [x] Add portfolio holdings storage (long, whole shares, VND; no ledger — deferred)
- [x] Add holdings CRUD (`/addholding` is an upsert that replaces quantity and average cost)
- [x] Add portfolio valuation (via the existing history/cache boundary; no new provider call)
- [x] Add unrealized P&L (labelled UNREALIZED; excludes fees/taxes)
- [x] Add stock exposure
- [x] Add sector exposure (existing effective-dated memberships; missing → "Unknown")
- [x] Add concentration warnings (config thresholds; NORMAL/WARNING/HIGH)
- [x] Add position sizing
  - Bounded by both the risk budget and available capital; V1 never assumes leverage.
- [x] Add user risk settings (`/setrisk`, `/risksettings`)
- [x] Add deterministic stress testing (portfolio and single symbol)
- [x] Add portfolio risk view (concentration + static-weight volatility, beta, max drawdown)
  - Historical metrics are a static-weight proxy; "Unavailable" with a reason when history is short.
- [x] Add portfolio context to `/soi` (informational only)
- [x] Keep personal portfolio/risk commands and `/soi` portfolio context private-chat only
- [x] Add `/watchlist`
- [x] Add `/addwatch`
- [x] Add `/removewatch`
- [x] Add `/portfolio`
- [x] Add `/addholding`
- [x] Add `/removeholding`
- [x] Add `/risk`
- [x] Add `/size`
- [x] Add `/stress`
- [x] Update `/help`
- [x] Preserve CL1/ASMF behavior (test asserts identical strategy views with and without holdings)
- [x] Run focused tests
  - Python 3.12.10: 130 Phase 23-specific tests collected and passed.
  - Focused Phase 23 plus migration/Telegram regression: 145 passed.
- [x] Run full regression
  - Python 3.12.10, isolated `.venv-phase21` dependency set: 589 passed.
- [x] Run pip check
  - Isolated `.venv-phase21` dependency set: `No broken requirements found`.
  - The Microsoft Store launcher for the workspace `.venv` remains unusable; tests used the same
    isolated site-packages through `PYTHONNOUSERSITE`/`PYTHONPATH`, not global packages.
- [x] Run bounded live acceptance
  - `scripts/test_portfolio_live.py`: PASS against live Vietcap EOD history using a temporary database
    and synthetic holdings; every Phase 23 command path succeeded without persisting real holdings.
  - `scripts/test_telegram.py`: PASS, Telegram authenticated `@stock_vinavn_bot` via `getMe`.
- [x] Update PROJECT_CONTEXT.md
- [x] STOP and report

Deferred: portfolio alerts, transaction ledger / realized P&L, beta-based VNINDEX stress, realtime
pricing for valuation, Phase 24 valuation. Pending Phase 3–7 live validations remain PENDING.
