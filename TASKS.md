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
Code and offline tests are complete for Phases 24–26. Phase 24 live acceptance
passed on 2026-09-21 after the VNStock 4.0.8/KBS compatibility follow-up. The
following checks still need their external runtime conditions and remain
unchecked; they are NOT TESTED, not PASS:

- Phase 22: `/soi`, `/market`, `/sentiment` during an active trading session,
  `/chart` real Vietcap → PNG → Telegram `send_photo`
  → run `py -3.12 scripts/test_phase26_telegram_live.py --send` during a session
- Phase 25: coverage worker running inside the real bot process against live providers

## ACTIVE IMPLEMENTATION PHASE
**Phase 26 — Live Acceptance, Reliability & Production Hardening — CODE + TESTS COMPLETE — pending external live validation** (Phase 25 — Market Coverage & Refresh Workers — CODE + TESTS COMPLETE; both run in one authorised iteration)
### Documentation follow-up — README operational status (COMPLETE)

- [x] Document installation, configuration and bot startup
- [x] Document Telegram commands and maintenance scripts
- [x] Separate arbitrary-symbol support from actual data coverage
- [x] Record live Phase 3–7 status and remaining live gaps
- [x] Document BCTC, institutional-flow, sector and sentiment boundaries
- [x] STOP and report

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
- [x] Receive binary event
- [x] Decode using MatchPrice protobuf
- [x] Print normalized FPT tick
- [x] Validate price/volume fields
- [x] STOP and report

Acceptance:
- Valid changing FPT realtime ticks observed
  - PASS at 09:42 ICT on 2026-09-21: two distinct 244-byte live frames decoded
    as FPT ticks at 66,300 and 66,400 with positive match/accumulated volumes.

---

## Phase 4 — Realtime ACB + Market State
- [x] Add ACB subscription
- [x] Prevent duplicate symbol subscriptions
- [x] Create normalized `TradeTick`
- [x] Create latest market-state cache
- [x] Test FPT + ACB simultaneously
  - PASS at 09:44 ICT on 2026-09-21: two distinct normalized live ticks were
    observed for each symbol and both `ACB` and `FPT` were present in the cache.
- [x] STOP and report

Acceptance:
- FPT and ACB update correctly in normalized form
  - PASS: `distinct_ticks={'FPT': 2, 'ACB': 2}` and
    `cached_symbols=['ACB', 'FPT']`.

---

## Phase 5 — Index stream
- [x] Subscribe VNINDEX
  - Live subscription emitted `event=index` with the exact
    `{"symbols":["VNINDEX"]}` JSON-string payload.
- [x] Decode `IndexMessage`
  - Live decoding accepted two distinct 148-byte binary frames.
- [x] Normalize `IndexSnapshot`
- [x] Validate breadth fields
- [x] STOP and report

Acceptance:
- VNINDEX realtime state available
  - PASS at 09:47 ICT on 2026-09-21: two distinct live VNINDEX snapshots were
    normalized and cached. Breadth was `132/63/110` (advance/unchanged/decline),
    while total volume and total value changed between snapshots.

---

## Phase 6 — Bid/Ask
- [x] Subscribe FPT + ACB to `w-bid-ask`
  - Live subscription emitted `event=w-bid-ask` with the exact
    `{"symbols":["FPT","ACB"]}` JSON-string payload.
- [x] Decode `BidAskMessage`
  - Live decoding accepted realtime binary order-book frames; the first observed
    frame was 169 bytes.
- [x] Normalize `OrderBook`
- [x] Validate bid/ask levels
- [x] STOP and report

Acceptance:
- Valid order book updates decoded
  - PASS at 09:51 ICT on 2026-09-21: four distinct FPT books and two distinct
    ACB books were normalized and cached; every printed book contained three
    bid levels and three ask levels.

---

## Phase 7 — Reliability
- [x] Reconnect handling
- [x] Exponential/reasonable retry
- [x] Re-subscribe after reconnect
- [x] No duplicate listeners
- [x] Decode error handling
- [x] Raw debug mode
- [x] STOP and report

Acceptance:
- Stream resumes after forced interruption
  - PASS at 10:06 ICT on 2026-09-21: FPT produced a valid tick before the
    forced WebSocket close, Socket.IO reconnected as connection generation 2,
    automatically restored the FPT subscription, and delivered distinct valid
    ticks afterward.

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



### Operational follow-up — notification durability
- [x] Audit và phân loại đúng bản chất ba problem (durability / bug / live gap)
- [x] Tách trạng thái notification vào store có thể thay thế
- [x] Thêm `SQLiteNotificationStore` dùng database runtime hiện có
- [x] Thêm migration v6 `sector_sync_notifications` (additive, không sửa v1–v5)
- [x] Khôi phục registration, incomplete state và pending delivery sau restart
- [x] Không gửi lại READY đã giao sau restart
- [x] Giao hàng at-least-once: send trước, mark delivered sau
- [x] Bỏ head-of-line blocking; retry có ngân sách, có thể cấu hình
- [x] TTL/cleanup registration cũ, có thể cấu hình
- [x] Giữ nguyên ba test notification cũ, không sửa để ép pass
- [x] Thêm 13 deterministic test restart/dedup/retry/migration
- [x] Chạy full regression: 612 passed cục bộ trên `py -3.12`, 2026-09-20
- [x] Chạy `pip check`: chạy xong; 8 conflict đều thuộc gói ngoài
      `requirements.txt` của repo (không do iteration này gây ra)
- [x] Bounded live acceptance `scripts/test_sector_notification_live.py`:
      **PASS** — sector VHM thật (usable 9/123, READY), gửi thành công 1 tin
      nhắn Telegram thật qua `@stock_vinavn_bot`, exit code 0
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

### Operational follow-up — dynamic all-symbol news linking

- [x] Remove the fixed eight-ticker runtime mapping
- [x] Build the ticker universe from active `STOCK`/`COMMON_STOCK` rows in SQLite
- [x] Enrich company-name aliases from the public CafeF listed-company catalog
- [x] Retain all-symbol code matching when the CafeF catalog is unavailable
- [x] Reject an empty universe instead of silently producing unlinked sentiment
- [x] Relink duplicate news rows without reinserting or replacing inference data
- [x] Verify arbitrary symbols outside the old list (`DGC`, `KDH`, `VIX`)
- [x] Verify the Telegram runtime query path with dynamically linked `EVF`
- [x] Run a bounded live CafeF acceptance against in-memory databases
  - PASS: 2,230 listed codes loaded, three RSS items ingested, no production write.
- [x] Run full regression and dependency checks
  - PASS: 642 tests; isolated `pip check` reports no broken requirements.
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

### Operational follow-up — candlestick chart
- [x] Renderer thuần (Pillow, không thêm dependency), không provider/strategy
- [x] Validate nghiêm ngặt: tối thiểu 5 phiên, cùng symbol/timeframe, tuần tự
- [x] EMA20/EMA50 overlay dùng đúng warm-up từ full history
- [x] Panel volume riêng, cùng trục x với nến
- [x] `RuntimeBotDataService.candlestick_chart()` dùng lại `_history()` sẵn có
- [x] `/chart FPT` + nút "📉 Biểu đồ nến" trong keyboard `/soi`
- [x] Lỗi trả về text, không bao giờ gửi ảnh hỏng
- [x] 25 test mới (16 renderer + 5 runtime + 4 Telegram wiring)
- [x] Phát hiện và sửa hard-coded command set trong `test_telegram_bot.py`
- [x] Full regression: 637 passed cục bộ trên `py -3.12`, 2026-09-20
- [x] `pip check`: chạy xong; 8 conflict đều thuộc gói ngoài
      `requirements.txt` của repo (không do follow-up này gây ra)
- [ ] Live acceptance: gửi `/chart` thật qua Telegram với dữ liệu Vietcap thật
  - NOT TESTED. Sandbox không có route tới Vietcap hoặc Telegram.
- [x] STOP and report
## Phase 24 — Automated Fundamentals & Institutional Data

### Provider layer
- [x] `ProviderStatus`/`ProviderResult`/`StatementRow`/`FlowRow` contracts
- [x] `VNStockProvider` — runtime API discovery, verify với vnstock 3.2.6 thật
- [x] `YFinanceProvider` — fallback nghiêm ngặt, verify với yfinance 1.0 thật
- [x] `ProviderChain` — VNStock trước, yfinance chỉ khi MISSING/ERROR
- [x] Provider layer là nơi DUY NHẤT import vnstock/yfinance

### Storage
- [x] Migration v7 `automated_fundamentals_coverage` (additive)
- [x] `automated_financial_statements` — staging, idempotent
- [x] `symbol_data_coverage` — trạng thái theo (symbol, dataset)
- [x] `fundamentals/adapters.py` — promote corporate statement khi đủ evidence
- [x] Bank statement KHÔNG BAO GIỜ tự động promote
- [x] Institutional flow upsert trực tiếp qua model/store CŨ

### Refresh service
- [x] `refresh_financials()`/`refresh_institutional_flow()` — kết quả có cấu trúc
- [x] Freshness policy configurable, `force=True` bypass
- [x] Một symbol lỗi không chặn refresh symbol khác

### Point-in-time
- [x] Report công bố sau ngày phân tích vô hình với phân tích đó
- [x] Thiếu `public_date` → không bao giờ promote
- [x] `period_end_date()` không bao giờ dùng thay `public_date`

### ASMF integration
- [x] `asmf_data/scoring.py` không sửa
- [x] Regression: path cũ vs path mới → cùng điểm 60.0

### Test — chạy thật 2026-09-21
- [x] `tests/test_fundamental_providers.py` — 47 passed
- [x] `tests/test_fundamental_refresh.py` — 20 passed
- [x] `tests/test_point_in_time_safety.py` — 5 passed
- [x] `tests/test_migrations.py`, `test_portfolio_schema.py`,
      `test_sector_notification_persistence.py` — 26 passed (6→7)
- [x] Full regression: **718 passed**, 0 failed, `py -3.12 -m pytest -q`
- [x] `pip check`: chạy xong; 8 conflict đều pre-existing, không do
      vnstock/yfinance

### Config
- [x] `requirements.txt`: `vnstock==3.2.6`, `yfinance==1.0` (version thật đã cài)
- [x] `.env.example` — hoàn tất ở Phase 25 (chỉ các key thật sự được đọc; có test)

### Live acceptance
- [x] VNStock fetch thật qua mạng cho ≥1 symbol
  - PASS 2026-09-21 — VNStock 4.0.8/KBS trả 4 kỳ thật cho FPT; ACB cũng trả
    4 kỳ ở trạng thái PARTIAL.
- [x] yfinance fallback thật
  - PASS 2026-09-21 — FPT.VN trả 9 dòng thật, gồm 2026Q2 đến 2025Q3 trong
    bốn kỳ gần nhất được in bởi harness.

### Chưa bắt đầu
- [ ] Phase 25 — Market Coverage & Refresh Workers
- [ ] Phase 26 — Live Acceptance, Reliability & Production Hardening

## Phase 25 — Market Coverage & Refresh Workers
Authorised to run back-to-back with Phase 26 in a single iteration (no STOP gate between them).

### Universe & coverage model
- [x] Universe đọc từ bảng SQLite `symbols` mỗi chu kỳ (`runtime/market_universe.py`), không hard-code ticker
  - active + `STOCK`/`COMMON_STOCK` + HOSE/HSX/HNX/UPCOM **hoặc exchange NULL** (bảng thật để NULL vì importer sector không ghi exchange)
- [x] Tái sử dụng `symbol_data_coverage` (không tạo bảng thứ hai)
- [x] Migration **v8 `market_coverage_datasets`**: CHECK cũ chỉ cho FINANCIALS/INSTITUTIONAL nên phải rebuild bảng; thêm MARKET_HISTORY/SECTOR_HISTORY/NEWS; copy nguyên hàng cũ
- [x] Migration runner nay mở transaction tường minh trước mỗi migration (trước đó DDL autocommit → rebuild lỗi giữa chừng sẽ bỏ schema nửa vời); test atomic fail khi bỏ dòng này
- [x] Trạng thái: NEVER_ATTEMPTED (không có hàng) / IN_PROGRESS / READY / PARTIAL / MISSING / STALE / ERROR; `attempts`, `last_attempt_at`, `last_success_at`, provider/source, reason đã redact
- [x] `last_success_at` được giữ nguyên sau ERROR/MISSING

### Worker
- [x] `runtime/coverage_worker.py`: `MarketCoverageEngine` (một chu kỳ đồng bộ, có giới hạn) + `MarketCoverageWorker` (1 daemon thread, dừng qua `Event`)
- [x] Ủy quyền, không chứa parsing: FINANCIALS→`refresh_financials`, INSTITUTIONAL→`refresh_institutional_flow`, MARKET_HISTORY→`SectorHistorySynchronizer.refresh_symbol_history`, SECTOR_HISTORY→`SectorHistorySyncWorker` hiện có (chỉ *yêu cầu* + ghi kết quả qua listener), NEWS→`NewsRefreshRunner` bọc pipeline CafeF/PhoBERT hiện có
- [x] Batch giới hạn (`COVERAGE_BATCH_SIZE`), thứ tự xác định: chưa thử trước → thử lâu nhất → theo alphabet
- [x] Bỏ qua dữ liệu còn fresh; `force=True` bỏ qua
- [x] Lỗi 1 symbol/dataset không dừng batch; ghi ERROR; commit từng ghi
- [x] Retry `COVERAGE_MAX_RETRIES` + backoff mũ `COVERAGE_RETRY_BACKOFF`; delay giữa provider call; circuit breaker sau 3 FAILED liên tiếp; phát hiện 429 → không retry
- [x] Cooldown liên chu kỳ: MISSING chờ `min(interval, COVERAGE_MISSING_COOLDOWN)`; ERROR chờ `COVERAGE_ERROR_COOLDOWN`
- [x] IN_PROGRESS có lease 30 phút → restart sau crash tự thu hồi; chạy lại không tạo hàng trùng
- [x] Sector: worker hiện có KHÔNG bị sửa hành vi; tối đa `COVERAGE_SECTOR_REQUESTS_PER_CYCLE` request/chu kỳ, mỗi sector 1 request
- [x] News: lịch `NEWS_REFRESH_INTERVAL` (lưu qua DB nên restart-safe); PhoBERT chỉ nạp một lần/process; không có news ⇒ MISSING, không phải Neutral
- [x] Khởi động không chờ refresh toàn thị trường; dừng sạch trong `finally` của `scripts/run_telegram_bot.py`
- [x] Telegram/`bot_service` không import vnstock/yfinance/worker/news pipeline (test AST)

### Scripts & report
- [x] `scripts/sync_fundamentals.py`, `sync_institutional_flow.py`, `sync_market_coverage.py` (`--symbol --limit --force --dry-run [--datasets]`), một lượt rồi thoát
- [x] `scripts/coverage_report.py` (+ `--symbol`, `--dataset --status`), số liệu từ DB, STALE tính theo tuổi
- [x] `.env.example` cập nhật

### Tests (chạy thật 2026-09-21)
- [x] `test_market_universe.py` 6, `test_coverage_states.py` 14 (gồm migration v8 giữ dữ liệu + atomic), `test_coverage_worker.py` 34, `test_coverage_config_report.py` 16
- [x] Cập nhật cộng thêm: pin schema version 7→8 trong 3 test cũ

### Chưa xác nhận
- [ ] Worker chạy trong tiến trình bot thật với provider thật
  - NOT TESTED — môi trường dev không có mạng tới Telegram/Vietcap/VNStock/Yahoo. Đã smoke thật (thread thật + vnstock 3.2.6 thật, mạng bị chặn) qua `start_coverage_worker_from_env`: 1 chu kỳ, dừng sạch, không crash.

## Phase 26 — Live Acceptance, Reliability & Production Hardening

### Live harness (bounded, DB tạm, không in secret)
- [x] `scripts/test_phase24_live.py` — VNStock + yfinance thật, in provider/source/symbol/status/rows/periods/retrieved_at, kiểm tra không promote khi thiếu `public_date`, bank không auto-promote; verdict PASS/FAIL/NOT TESTED/INCONCLUSIVE, có probe host để phân biệt “bị chặn” với “không có dữ liệu”
- [x] `scripts/test_phase26_telegram_live.py` — `/soi` (CL1+ASMF), `/market`, `/sentiment`, `/chart` qua command service thật trên **bản sao DB tạm**; `--send` gửi qua bot bằng `TEST_TELEGRAM_CHAT_ID` (chỉ từ env); không polling
- [x] Mẫu symbol đa dạng chọn theo metadata (HOSE/HNX/UPCoM, bank, non-bank ngoài `BOT_WATCH_SYMBOLS`, lịch sử ngắn) + FPT/ACB
- [x] Thân script chạy end-to-end offline với Vietcap giả (DB production không bị đổi)

### Hardening (test offline)
- [x] Thiếu/timeout lịch sử → “Chưa có dữ liệu”, không crash; lịch sử ngắn → EMA50/MA200 `N/A` (không 0); thiếu fundamentals → `Fundamental data missing`, ASMF fail-closed; không có news → unavailable, không Neutral
- [x] CafeF timeout, PhoBERT model dựng đúng 1 lần, VNStock/Yahoo lỗi, Vietcap timeout + SQLite cache
- [x] SQLite: 3 writer song song không mất/trùng (integrity_check ok); DB bị khóa → chu kỳ không crash, hồi phục sau khi mở khóa
- [x] Telegram: tham số sai/thiếu/dài, chữ thường + khoảng trắng, chunk 4096, lỗi gửi ảnh → fallback text (trước đây không bắt lỗi), error handler toàn cục, callback rác, private/group (group không có holdings/P&L)
- [x] Bảo mật log: `runtime/redaction.py` (token bot, Bearer, Authorization/Cookie, giá trị env); `configure_logging()` ép httpx/httpcore về WARNING (URL Telegram chứa token); `error_reason` được redact trước khi lưu; test quét mã nguồn
- [x] Strategy regression: không sửa CL1/ASMF/sentiment/bank/point-in-time; không test cũ nào bị đổi expected (chỉ pin version schema)
- [x] Thêm fallback `vnstock.api.financial.Finance` cho vnstock 4.x (additive; requirements vẫn pin 3.2.6, path 3.2.6 không đổi)
- [x] Phase 24 live-provider follow-up: nâng pin lên `vnstock==4.0.8`, ưu tiên
      KBS rồi VCI, chuẩn hóa KBS wide semantic statements, thử nguồn tuần tự để
      nguồn sau timeout không chặn nguồn trước, và sửa verdict refresh SUCCESS
      thành AVAILABLE trong live harness

### Kết quả kiểm thử
- [x] Full regression: **830 passed** (`python -m pytest -q`, Python 3.12.3, venv cách ly, 718 → 830)
- [x] `pip check` trong venv cách ly đó (vnstock==3.2.6, yfinance==1.0, không có torch/transformers): “No broken requirements found”. KHÔNG khẳng định môi trường đầy đủ sạch; conflict cũ ở môi trường chung (Phase 24) chưa đo lại.
- [x] Follow-up VNStock 4.0.8: **833 passed** trên full regression; focused
      Phase 24/26 **91 passed**. `pip check` với dependency VNStock resolve đầy
      đủ không có conflict mới; còn đúng 8 conflict đã biết của môi trường chung.

### Live acceptance
- [x] VNStock fetch thật ≥1 symbol — PASS 2026-09-21, KBS/FPT AVAILABLE 4 kỳ;
      KBS/ACB PARTIAL 4 kỳ
- [x] yfinance fallback thật — PASS 2026-09-21, FPT.VN PARTIAL 9 dòng
- [ ] `/soi` `/market` `/sentiment` trong phiên giao dịch — NOT TESTED
- [ ] `/chart` Vietcap thật → PNG → Telegram `send_photo` — NOT TESTED
- [x] Live promotion-safety với dữ liệu VNStock thật — PASS 2026-09-21 trên
      database tạm; FPT/ACB được stage, thiếu `public_date` không promote và
      bank không được ghi vào `bank_financial_reports`
