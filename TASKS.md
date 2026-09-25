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

**VN30 ASMF data-readiness follow-up — SPLIT AT EXTERNAL DATA BOUNDARY**

- [x] Force-refresh FINANCIALS for all 30 current VN30 constituents through the
  production provider chain
- [x] Confirm 30/30 provider outcomes completed without `FAILED`: 14 `SUCCESS`,
  16 `PARTIAL`
- [x] Increase current-date Fundamental availability from 5/30 to 12/30
- [x] Rerun the identical 2026-06-01 through 2026-09-24 ASMF fixed-basket test
- [x] Reduce missing-Fundamental decisions from 1,582 to 1,076 and total BLOCKED
  decisions from 1,852 to 1,827
- [x] Supply effective-dated HOSE VNAllshare sector memberships from 2026-02-02,
  including strict PDF/count validation and the 2026-08-03 rebalance
- [x] Reduce missing-Sector decisions from 1,759 to 26 and total BLOCKED
  decisions from 1,827 to 1,102 in the identical VN30 ASMF test
- [ ] Supply compatible current Fundamental scores for the remaining 18 symbols

The phase is split at a concrete external-data/model boundary. All 30 local
sector memberships now have point-in-time HOSE evidence for the tested period;
the current Vietcap snapshot was not backdated. Current-quarter bank scores
remain absent when CAR is undisclosed, and securities symbols have no compatible
ASMF model. The latest 30-symbol run is persisted honestly with 1,102 BLOCKED
and 770 WATCH decisions; no missing input was neutralized.

### Previous completed phase

**Current VN30 fixed-basket backtest follow-up — COMPLETE (PASS)**

- [x] Verify the 30 constituents against the SSIAM VN30 creation basket dated
  2026-09-22
- [x] Audit local daily-history coverage: all 30 symbols and VNINDEX have at
  least 200 completed daily bars
- [x] Persist CL1 over all 30 symbols for 2026-06-01 through 2026-09-24
- [x] Persist fail-closed ASMF over the identical fixed universe and range
- [x] Verify both `/performance CL1` and `/performance ASMF` render
  `Universe: 30 mã`

CL1 produced 1,872 decisions, eight closed trades and two open positions. ASMF
produced 1,852 BLOCKED and 20 WATCH decisions because historical sector breadth
and point-in-time financial coverage remain incomplete. Both runs are
`IN_SAMPLE_ONLY`. The fixed current basket has survivorship bias and is not a
historical point-in-time VN30-membership backtest.

Stop condition reached: both current-basket runs are persisted and selected by
the Telegram performance command. No strategy rule or missing-data policy was
changed.

### Previous completed phase
**News coverage, freshness and sentiment integrity — COMPLETE (PASS)**

- [x] Confirm production gaps from SQLite: only 29 linked tickers; FPT had two
  articles, SSI one, and ACB/HPG/VIC none
- [x] Replace the on-demand generic-RSS retry with a bounded CafeF tag-page fetch
  for the exact requested ticker
- [x] Refresh non-empty caches on every `/tin`/`/sentiment` request through the
  existing background queue and five-minute cooldown
- [x] Merge four official CafeF RSS channels for the periodic market-wide sweep
- [x] Fail closed from the unvalidated generic-label transformer to conservative
  `financial_rules` v2; fix neutral-label selection
- [x] Weight aggregate sentiment by direct/indirect ticker relevance
- [x] Refresh duplicate metadata/inference and add a bounded reanalysis CLI
- [x] Focused regression — 133 passed
- [x] Full regression — 1007 passed in 40.13s
- [x] Controlled benchmark — 10/10 after the fix versus 4/10 before; this small
  fixture is a regression check, not a general model-accuracy claim
- [x] Live CafeF acceptance — FPT/SSI/ACB/VIC each returned 10 recent tag-page
  articles and HPG returned 3; FPT and SSI coverage became READY
- [x] Persisted repair — 175 existing articles reanalyzed; the FPT profit article
  changed from an incorrect negative label to positive

Stop condition reached: per-ticker coverage, background freshness, conservative
sentiment, persisted reanalysis and live FPT/SSI coverage are verified.

### Previous completed phase

**Vietcap IQ canonical integrity follow-up — COMPLETE (PASS)**

- [x] Correct Vietcap debt semantics: `bsa56` short-term loans and `bsa71`
  long-term loans; keep `bsa55`/`bsa67` for liability identity checks only
- [x] Version corrected canonical provenance as `/borrowings-v2`
- [x] Hide legacy Vietcap canonical rows that stored total liabilities as debt
- [x] Force legacy Vietcap symbols past the fresh-coverage skip on their next cycle
- [x] Add deterministic automated-source precedence so VNStock/TCBS/Yahoo cannot
  downgrade a corrected Vietcap quarter, while Vietcap can upgrade lower sources
- [x] Make Vietcap return `ERROR` when it has zero canonical-complete quarters so
  the provider chain continues to VNStock/TCBS/Yahoo
- [x] Focused regression — 184 passed, then 114 passed after final precedence test
- [x] Full regression — 1001 passed in 32.16s
- [x] Direct FPT live revalidation — PASS: 34 complete quarters, 34 actual
  publication dates, latest 2026Q2
- [x] Forced canonical refresh — PASS: FINANCIALS READY through VietcapIQ in one
  selected attempt
- [x] Persisted verification — PASS: all 34 FPT canonical rows from 2018Q1
  through 2026Q2 carry `/borrowings-v2`; Fundamental score remains 60.0

Stop condition reached: corrected debt semantics, source precedence, fallback,
authenticated live acquisition and canonical persistence are all verified.

**Vietcap IQ authenticated live acceptance — COMPLETE (PASS)**

- [x] User confirmed the successful browser request has Authorization only
- [x] Correct Origin/Referer to the trading.vietcap.com.vn IQ frontend
- [x] Remove Cookie/device-id from the IQ request contract and harness gate
- [x] Re-run focused tests — 87 passed in 1.46s
- [x] Re-run full regression — 997 passed in 31.44s
- [x] Direct FPT live acceptance — PASS with a current locally configured
  Authorization: 34 complete quarters, 34 actual publication dates, latest 2026Q2
- [x] Forced FPT sync — SUCCESS through VietcapIQ with one selected attempt
- [x] Persisted verification — `FINANCIALS READY`, 34 canonical rows from
  2018Q1 through 2026Q2, `fundamental_score=60.0` as of 2026-09-24

Stop condition reached: the browser-observed header contract, authenticated live
fetch, canonical promotion and readiness report all pass. The local Authorization
was removed from the PowerShell environment after the bounded run.

**Vietcap IQ authenticated live acceptance — COMPLETE (superseded NOT TESTED verdict)**

- [x] Add a bounded live harness that never prints or persists session secrets
- [x] Test PASS/NOT TESTED/FAIL verdict semantics offline — 68 passed in 0.27s
- [x] Run one direct FPT IQ fetch without provider fallback
- [x] Authentication unavailable: both sections rejected/unusable with the
  existing local trading-domain session; verdict `NOT TESTED`, no secret output
- [x] Full regression — 997 passed in 30.46s

Stop condition reached: code and redaction semantics pass; a locally valid IQ
session is an unresolved external dependency. Do not mark live acquisition PASS.

**Vietcap IQ financial-statement provider — COMPLETE (live auth NOT TESTED)**

- [x] Capture BALANCE_SHEET and INCOME_STATEMENT response schemas without secrets
- [x] Verify quarterly period and actual `publicDate` fields
- [x] Verify accounting-code mappings through balance/profit identities
- [x] Implement a provider-local Vietcap IQ adapter with fail-closed validation
- [x] Put Vietcap IQ first in the chain only when explicitly enabled
- [x] Add provider, chain, environment and promotion regression tests
- [x] Run focused and full regression tests
  - Focused: 122 passed in 2.39s
  - Full: 994 passed in 31.27s
- [x] Record live authentication as PASS or NOT TESTED without requesting credentials
  - NOT TESTED: anonymous GET is 403 and the existing trading-domain session is
    rejected with 400 by IQ. No browser token/cookie was requested or copied.

**Local backtest evidence follow-up — COMPLETE**

- [x] Audit local SQLite daily bars, sector membership and point-in-time BCTC
- [x] Run and persist CL1 for HPG,VNM,GAS over 2026-06-01 → 2026-09-24
- [x] Run and persist ASMF V2 over the identical universe/range
- [x] Inspect persisted `/performance`, `/performance CL1`, `/performance ASMF`
- [x] Persist and render action counts plus missing-reason counts
- [x] Keep both runs `IN_SAMPLE_ONLY`
- [x] Run focused tests: 26 passed
- [x] Run full regression: `py -3.12 -m pytest -q` — 988 passed in 30.44s
- [x] Audit all locally eligible symbols: 0/97 have a ready Fundamental score
- [x] Align runtime to pinned `vnstock==4.0.8` and `vnai==2.6.1`
- [x] Probe KBS, VCI, MAS, TCBS direct and Yahoo fallback without fabricating rows
- [x] Rerun ASMF after provider refresh: still 188 BLOCKED; missing counts unchanged
- [x] Re-run full regression after dependency alignment: 988 passed in 30.49s
- [x] Supply at least 8 contiguous point-in-time quarters for an eligible ASMF universe
  - HPG 2024Q3–2026Q2 was transcribed from eight verified consolidated Vietstock
    filings using actual publication dates and parent-company NPAT (line 61).
- [x] Supply effective-dated sector membership covering the requested historical range
  - Acceptance range was narrowed to 2026-09-20 → 2026-09-24, matching the
    existing effective start date instead of backdating membership.
- [x] Rerun ASMF until decisions are evaluated without mandatory data layers missing
  - `local-asmf-v2-verified-hpg-20260924`: 3 WATCH decisions,
    `missing_reason_counts={}`, `fundamental_score=80.0`, no trades,
    `IN_SAMPLE_ONLY`.
- [x] Run full regression after verified import: `py -3.12 -m pytest -q` —
  988 passed in 36.58s

Acceptance is limited to data readiness and execution of the shared ASMF path.
The three-session run is too short for performance inference; zero trades leave
return and drawdown unavailable, and no profitability claim is made.

**ASMF V2 — Remove unreliable institutional flow from automatic signals — COMPLETE**

- [x] Remove institutional-flow input from the shared ASMF evaluator
- [x] Normalize SMF weights to Accumulation 43.75%, OBV 31.25%, Volume Z-score 25%
- [x] Remove institutional-flow reads from live runtime, scanner, and historical adapter
- [x] Keep institutional-flow storage/sync/scoring available for experimental lookup only
- [x] Update strategy output/catalog and documentation
- [x] Add regression tests for exact V2 weights and required-layer behavior
- [x] Run focused and full regression tests
  - PASS: 86 focused ASMF/runtime/scanner tests.
  - PASS: `py -3.12 -m pytest -q` — 987 passed in 33.89s.
- [x] STOP and report

**Performance remediation P5 — Execution, costs, settlement, benchmark & metrics — COMPLETE**

- [x] Add configurable T+1 open execution without same-close fills
- [x] Constrain every fill to the observed bar's OHLC range
- [x] Add cash, positions, quantities, fills, fees, sell tax and slippage
- [x] Add explicit equal-weight allocation and configurable lot size
- [x] Add configurable settlement abstraction without inventing T+2/T+2.5
- [x] Build a dated mark-to-market equity curve
- [x] Keep open positions explicit and mark them to market
- [x] Add VNINDEX buy-and-hold over the identical effective range
- [x] Calculate supported net performance/risk/trade metrics with sufficiency rules
- [x] Keep undefined/zero-trade metrics `NULL`/`N/A`
- [x] Persist execution summaries and expose them through `/performance`
- [x] Require caller-supplied settlement sessions in both offline CLIs
- [x] Add chronology, OHLC-fill, cost, settlement, drawdown, profit-factor,
      zero-trade, benchmark-range and advanced-risk-metric tests
  - PASS: 58 focused P2–P5/Telegram tests.
  - PASS: 10 focused execution/analytics tests after final metric coverage.
- [x] Run full regression
  - PASS: `py -3.12 -m pytest -q` — 985 passed in 33.71s after final ASMF limitation hardening.
- [x] Verify CL1 and ASMF CLI entry points and mandatory settlement flag
- [x] Update `README.md`, `docs/ARCHITECTURE.md`, and `PROJECT_CONTEXT.md`
- [x] STOP and report

### Original real-data follow-up status

- [x] Run CL1 and ASMF jobs against the current local SQLite cache
- [x] Inspect persisted `/performance`, `/performance CL1`, `/performance ASMF`
- [x] Keep status `IN_SAMPLE_ONLY` until a separately authorised OOS/walk-forward phase exists
- [ ] Repeat ASMF after the cache becomes production-like for mandatory PIT inputs

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

### Trạng thái tiếp theo

- Phase 25 — CODE + TESTS COMPLETE.
- Phase 26 — CODE + TESTS COMPLETE — pending external live validation.
- Xem các section Phase 25–26 bên dưới để biết bằng chứng và live gaps còn lại.

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


## Operational follow-up — Bot UX, Scanner & Sentiment

### Issue 1 — Latest-five ticker sentiment
- [x] Replace strict 24h ticker sentiment with newest up-to-5 relevant articles — PASS 2026-09-21
- [x] Default maximum article age: 30 days — PASS 2026-09-21
- [x] `/tin`, `/sentiment`, `/soi` share one canonical selection path (`eligible_articles`) — PASS 2026-09-21
- [x] Zero eligible articles remains MISSING, not Neutral — PASS 2026-09-21
- [x] Preserve severe-negative ASMF blocker recency independently (48h) — PASS 2026-09-21
- [x] Add deterministic tests (`test_latest_five_sentiment_and_canonical_selection`) — PASS 2026-09-21

### Issue 2 — Market-wide background scanner
- [x] `/scan` no longer derives universe from `BOT_WATCH_SYMBOLS` — PASS 2026-09-21
- [x] Universe comes from active HOSE/HNX/UPCoM common stocks in SQLite (`load_market_universe`) — PASS 2026-09-21
- [x] Full-market scan runs in background (`MarketScannerWorker`, `run_scan_cycle`), not Telegram command path — PASS 2026-09-21
- [x] Persist scan snapshot in SQLite (`scan_snapshots` table, Migration 9) — PASS 2026-09-21
- [x] `/scan` reads latest snapshot (<10ms) — PASS 2026-09-21
- [x] Add strategy-aware CL1/ASMF views without inventing new strategy rules — PASS 2026-09-21
- [x] Add liquidity configuration and tests (`tests/test_scanner_worker.py`) — PASS 2026-09-21
  - ⚠️ CORRECTION (2026-09-22): code above was complete but never live-validated in the
    real bot process; `MarketScannerWorker` was not started from
    `scripts/run_telegram_bot.py` and `/scan` silently fell back to
    `BOT_WATCH_SYMBOLS` (FPT/ACB only) in production. Fixed and live-validated as
    **Live Acceptance Fix Round — Issue 1** below (2026-09-22).

### Issue 3 — Realtime breadth in Telegram market context
- [x] Connect realtime VNINDEX breadth to `/market` via `index_state` injection — PASS 2026-09-21
- [x] Preserve historical trend-only fallback when realtime breadth is unavailable — PASS 2026-09-21
- [x] Distinguish General Market Context from ASMF Market Filter — PASS 2026-09-21
  - ⚠️ CORRECTION (2026-09-22): the `market_overview()` code path above was correct,
    but `index_state` was never actually constructed/passed by
    `build_runtime_service_from_env()`, and no worker ever populated it — so in
    production `/market` always showed `BREADTH: unavailable`, and `/soi` never
    received breadth/liquidity at all (`stock_analysis()` didn't wire it in either).
    Fixed and live-validated as **Live Acceptance Fix Round — Issue 2** below
    (2026-09-22).

### Issue 4 — `/soi` compact dashboard
- [x] Reduce overview to concise high-value information — PASS 2026-09-21
- [x] Move detailed Technical/Fundamental/ASMF/Why/News/Sentiment/Market behind buttons — PASS 2026-09-21
- [x] Preserve direct text commands — PASS 2026-09-21
- [x] Avoid duplicate content between overview and detail — PASS 2026-09-21

### Issue 5 — Telegram callback UX
- [x] Text callbacks edit/update existing message where technically suitable (`query.edit_message_text`) — PASS 2026-09-21
- [x] Avoid unnecessary new messages — PASS 2026-09-21
- [x] Preserve separate photo behavior for `/chart` — PASS 2026-09-21

### Issue 6 — `/why` deduplication
- [x] Do not render identical data-quality limitations twice (`include_notes=False` in format_why) — PASS 2026-09-21
- [x] Show each missing-data explanation once — PASS 2026-09-21
- [x] Preserve layer status separately from explanatory notes — PASS 2026-09-21

### Issue 7 — ASMF score presentation
- [x] Keep underlying ASMF score unchanged — PASS 2026-09-21
- [x] Label score explicitly as evidence score, not probability/confidence (`Điểm bằng chứng (Evidence score): XX.X/100`) — PASS 2026-09-21
- [x] Show true core-layer coverage separately (`Độ phủ tầng cốt lõi: X/4 tầng`) — PASS 2026-09-21
- [x] Show sentiment as optional context separately (`Lớp bổ trợ (Sentiment context)`) — PASS 2026-09-21

### Issue 8 — General Market vs ASMF Market wording
- [x] Rename to `General Market Context` in market overview / summaries — PASS 2026-09-21
- [x] Rename ASMF layer to `ASMF Market Filter` — PASS 2026-09-21
- [x] Explain that they use different inputs — PASS 2026-09-21

### Live acceptance still pending (Issues 10, 11, 12)
- [ ] `/soi`, `/market`, `/sentiment` during active session — PENDING LIVE VALIDATION (Requires live market hours 09:00-14:45 ICT)
- [ ] `/chart` real Vietcap → PNG → Telegram send_photo — PENDING LIVE VALIDATION (Requires real Telegram Bot Token & chat)
- [ ] Coverage worker inside real bot process with live providers — PENDING LIVE VALIDATION (Requires persistent bot service host)
## Phase 27 — Market Context & Sector Performance Chart (COMPLETE)
- [x] Create charts/sector_chart.py rendering Top % Sector Performance Chart via headless Matplotlib
- [x] Extend MarketContextView in 
untime/views.py with Hurst, Volatility Percentile, MA status, and Sector rankings
- [x] Update 
untime/analysis.py to calculate Hurst exponent on 100 sessions and 20-session rolling realized volatility percentile
- [x] Implement MA50 & MA200 trend stability classification
- [x] Update 
untime/bot_service.py with sector_performance_chart() and integrate sector rankings in market_overview()
- [x] Format /market in 	elegram_bot/formatters.py matching national standard visual layout and disclaimer
- [x] Support /chart MARKET and inline callback soi:mchart:VNINDEX in 	elegram_bot/app.py
- [x] Add unit & integration tests (	ests/test_sector_chart.py, 	ests/test_market_context_advanced.py) — 852/852 tests PASS

## Phase 28 — Live Acceptance Fix Round (2026-09-22)
Fixing remaining live-acceptance gaps found after real bot startup, ONE issue per
iteration, each stopped for explicit live confirmation before the next.

### Issue 1 — `/scan` chỉ scan 2 mã thay vì toàn thị trường (universe=1524)
- [x] Root cause: `MarketScannerWorker` was never started from
      `scripts/run_telegram_bot.py`, so `/scan` had no snapshot and fell back to
      the legacy `BOT_WATCH_SYMBOLS` watch list — PASS 2026-09-22
- [x] `/scan` reads latest persisted full-market snapshot, no longer limited by
      `BOT_WATCH_SYMBOLS` — PASS 2026-09-22
- [x] Live: `universe=1524`, `/scan` no longer shows `2/2` — PASS 2026-09-22 (user-confirmed)

### Issue 2 — Realtime breadth chưa vào `/market` (và `/soi`)
- [x] Root cause #1: `build_runtime_service_from_env()` never passed
      `index_state=` into `RuntimeBotDataService`, so it was always `None` in
      production regardless of the (working, standalone-tested) Vietcap realtime
      index pipeline — PASS 2026-09-22
- [x] Root cause #2: no worker ever started the realtime index socket in the bot
      process (unlike `scanner_worker`/`coverage_worker`) — PASS 2026-09-22
- [x] Root cause #3: `stock_analysis()` (used by `/soi`) built its market view
      without ever passing breadth/liquidity, even when `index_state` was wired —
      so `/soi` could never share `/market`'s breadth — PASS 2026-09-22
- [x] Added `runtime/index_stream_worker.py`: bounded daemon-thread worker
      (`IndexStreamWorker`, `start_index_stream_worker_from_env`), retry/backoff
      on connect failure, never busy-loops, doesn't block Telegram polling;
      `INDEX_STREAM_WORKER_ENABLED` env flag — PASS 2026-09-22
- [x] Shared `RuntimeBotDataService._index_breadth_liquidity()` used by both
      `market_overview()` (`/market`) and `stock_analysis()` (`/soi`) — PASS 2026-09-22
- [x] Tests: `tests/test_index_stream_worker.py` (new, 6 tests), extended
      `tests/test_runtime_bot.py` (+4 tests: breadth unavailable without
      `index_state`, breadth/liquidity populated from a snapshot, `/market` and
      `/soi` share the same breadth string, `/soi` has no breadth when
      `index_state` is absent) — 19/19 passed 2026-09-22
- [x] Full regression: **866 passed** (`python -m pytest tests/ -q`) — no
      regression in `/scan` (Issue 1), `/chart`, market_regime, telegram_bot
- [x] Live: bot startup log shows `Realtime index stream worker started` →
      `Vietcap realtime index stream connected symbols=('VNINDEX',)` — PASS 2026-09-22
- [x] Live: `/market` shows `BREADTH: 143 tăng (3 trần) / 148 giảm (7 sàn) / 64
      tham chiếu` and `Regime: BULL (xu hướng EMA + breadth ...)` instead of
      `unavailable` — PASS 2026-09-22 (user-confirmed)
- [x] Live: `/soi HPG` shows the same live breadth shape in `🌐 THỊ TRƯỜNG` as
      `/market` (values differ slightly because both reads are genuinely realtime,
      taken seconds apart against the same live `index_state`, not a frozen
      duplicate) — PASS 2026-09-22 (user-confirmed)
- [x] Known side effect (not in scope, left for Issue 3): live output showed
      `LIQUIDITY: 0 tỷ (301,778,416 CP)` — volume looks right but the matched
      value renders as 0; suspected unit/field mismatch in the realtime index
      `total_value` field. Noted for Issue 3 audit, not fixed here.

### Issue 3 — Liquidity toàn thị trường unavailable
- [x] Root cause: NOT a missing data source. The Vietcap realtime index
      stream's `totalValue` field is denominated in **triệu đồng** (millions
      of VND), not raw VND as `normalize_index()` assumed. Live evidence:
      `totalValue=9,926,135.61` alongside `totalShares=409,881,936` implies
      ~0.02 VND/share if read as raw VND (impossible), but ~24,220 VND/share
      once scaled by 1e6 — a plausible VN equity price, and ~9,926 tỷ VND
      total turnover consistent with a real mid-afternoon HOSE session. This
      also explains the Issue 2 follow-up note of `LIQUIDITY: 0 tỷ` — PASS
      2026-09-22
- [x] Added `VIETCAP_INDEX_TOTAL_VALUE_UNIT_SCALE = 1_000_000.0` in
      `data/vietcap/normalizer.py`; `normalize_index()` now scales
      `totalValue` to VND on ingestion. `totalShares` is unaffected (no unit
      mismatch observed there). No other consumer of `total_value` needed
      changing (`runtime/bot_service.py`'s plausibility check and `/1e9` "tỷ"
      formatting already assumed VND input and were already correct) — PASS
      2026-09-22
- [x] Did not touch `MIN/MAX_PLAUSIBLE_AVERAGE_PRICE_VND` bounds, the
      plausibility function, or `/chart` — out of scope for this issue
- [x] Tests: updated `tests/test_index_stream.py::test_normalize_index_maps_to_index_snapshot`
      for the new scaled expectation; added
      `test_normalize_index_scales_total_value_from_trieu_dong_to_vnd`
      regression test reproducing the exact live totalValue/totalShares pair
      and asserting the implied average price falls back within plausible
      bounds — full suite still green (870/870, includes the +1 new test) —
      PASS 2026-09-22 (user-confirmed)
- [x] Live: `/market` shows `LIQUIDITY: 11,103 tỷ (458,208,014 CP)` instead of
      `unavailable`/`0 tỷ`, implied average price ≈24,230 VND/share (plausible),
      no more "total_value looks implausible" WARNING in normal conditions —
      PASS 2026-09-22 (user-confirmed)

### Issue 4 — Foreign / proprietary flow unavailable
- [x] Root cause is actually two independent things, audited separately:
      1. **`/market`'s market-wide `DÒNG TIỀN NGOẠI/TỰ DOANH`** — never wired
         (no code ever passed `foreign_flow=` into `build_market_view()`) for
         the honest reason that **no market-wide data source exists**
         anywhere in the repo (Vietcap `IndexMessage` has no such field, no
         aggregate table/query exists). **BLOCKED BY DATA SOURCE** — correctly
         stays "unavailable", not fixable by code alone — PASS 2026-09-22
      2. **Per-symbol `INSTITUTIONAL` coverage** (e.g. ACB showing
         `provider=yfinance reason=no provider in the chain had data`) — a
         real, fixable bug: `ProviderChain._run()`'s all-MISSING fallback
         attributed the result to `self._providers[-1].name` (yfinance),
         falsely implying yfinance was relied upon for VN institutional data,
         when in fact it always honestly declines
         (`YFinanceProvider.fetch_institutional_flow()` never fabricates VN
         flow) and the authoritative source (`VNStockProvider`, already
         trying `trading.foreign_trade`/`trading.prop_trade`/
         `quote.foreign_trade` across VCI/TCBS — correct layer, no new
         implementation needed) was the one that actually had nothing — PASS
         2026-09-22
- [x] Confirmed `FlowRow`/`InstitutionalFlow` already track foreign and
      proprietary legs as fully independent nullable fields; "ownership"
      data has no representation anywhere in the repo — no conflation risk,
      no change needed — PASS 2026-09-22
- [x] Fixed `fundamentals/providers/provider_chain.py`: all-MISSING chain
      result now reports `provider="none"` with
      `error_reason="no provider had data (attempted: ...)"` listing every
      provider actually tried, instead of blaming the last provider in the
      chain — PASS 2026-09-22
- [x] Tests: `tests/test_fundamental_providers.py` — extended
      `test_chain_missing_when_every_provider_is_missing`; added
      `test_chain_missing_institutional_flow_does_not_blame_yfinance` — full
      suite **872/872 passed** — PASS 2026-09-22 (user-confirmed)

### Issue 5 — News ingestion không phủ đủ theo ticker
- [x] Root cause: `NewsIngestionService.run_once()` only ever ingests one generic CafeF market-wide RSS feed, bounded to `NEWS_INGEST_LIMIT` (default 30 items), linking a small fraction of tickers by chance.
- [x] Implemented on-demand per-ticker refresh architecture:
      1. Market-wide sweeps.
      2. Targeted ticker refresh: implemented `CafeFTickerNewsProvider` scraping
         the canonical CafeF corporate events page (`https://s.cafef.vn/tin-doanh-nghiep/{symbol}/Event.chn`).
         Parses `#divEvents`, extracts published date, normalized title, absolute
         URL, filters within 30 days, deduplicates by URL hash, classifies events,
         and persists to `news_items` and `news_tickers` with sentiment analysis.
- [x] Added `refresh_ticker_news(symbol, ...)` and `TargetedNewsWorker` daemon
      with non-blocking queue, deduplication, and cooldown (`runtime/news_refresh.py`).
- [x] Integrated `news_refresh_requester` into `RuntimeBotDataService`
      (`runtime/bot_service.py`) and wired in production `scripts/run_telegram_bot.py`.
      When `/tin` or `/sentiment` queries a symbol with missing news, the symbol is
      queued non-blockingly without delaying Telegram responses.
- [x] Unit tests: `test_cafef_ticker_news_provider_parses_html`,
      `test_refresh_ticker_news_populates_repository_and_sentiment`,
      `test_targeted_news_worker_enqueues_and_processes`,
      `test_latest_news_and_sentiment_trigger_news_refresh_requester` (all passed).
- [x] Live acceptance: verified `HC1` targeted refresh against live CafeF ticker page —
      fetched 3 real September 2026 articles, persisted into repository, and verified
      `latest_news("HC1")` & `ticker_sentiment("HC1")` returned articles and valid sentiment.
- [x] Full test suite regression: **882/882 passed** (0 failures).

### Issue 6 — News freshness đang dùng 7 ngày thay vì 30 ngày
- [x] Root cause: `CoverageConfig.news_window_days` and `NewsRefreshRunner.window_days` were
      hardcoded to default `7` days and excluded from environment overrides, producing reason strings
      such as `no relevant news in last 7d` or `2 article(s) in last 7d`. Furthermore, the coverage
      evaluation treated any ticker with > 0 articles as `READY` and 0 articles as `MISSING`,
      lacking granularity for `PARTIAL` (1-2 articles) and `STALE` (articles exist in DB but >30d).
- [x] Unified canonical news eligibility across `/tin`, `/sentiment`, `/soi`, news pipeline, coverage worker, and reporting:
      - `MAX_NEWS_AGE_DAYS = 30`
      - `MAX_ARTICLES = 5`
- [x] Implemented canonical coverage status classification for `NEWS`:
      - `READY`: >= 3 eligible articles (<= 30 days)
      - `PARTIAL`: 1–2 eligible articles (<= 30 days)
      - `STALE`: 0 eligible articles in last 30 days, but older articles exist in DB (`newest article is older than 30d`)
      - `MISSING`: 0 articles in DB (`no relevant news in last 30d`)
- [x] Updated `runtime/coverage_config.py`: default `news_window_days: int = 30`, supports env `NEWS_WINDOW_DAYS` (validated positive).
- [x] Updated `runtime/news_refresh.py`: default `window_days = 30` in runner and env factory; `NewsRunResult` carries `known_tickers`
      for stale detection; `TargetedNewsWorker` applies the canonical 4-state eligibility rules.
- [x] Updated `runtime/coverage_worker.py`: `_run_news_step` evaluates `READY`, `PARTIAL`, `STALE`, `MISSING`, formats
      canonical reason strings, and computes linked tickers using `SUCCESS_STATES` (`READY` + `PARTIAL`).
- [x] Added `SQLiteNewsRepository.all_tickers_with_articles()` and index on `news_tickers(ticker)` for instantaneous ticker presence queries.
- [x] Updated `.env.example` with `NEWS_WINDOW_DAYS=30`.
- [x] Tests:
      - `tests/test_coverage_worker.py`: added `test_news_canonical_eligibility_statuses_ready_partial_stale_missing` verifying all 4 canonical states.
      - `tests/test_coverage_config_report.py`: tested default `news_window_days == 30`, `NEWS_WINDOW_DAYS` env parsing, and rejection of non-positive values.
      - Full test suite regression: **885/885 passed** (0 failures).
- [x] Live verification: `scripts.coverage_report --symbol HC1` produces:
      `NEWS READY provider=CafeF/ticker_page attempts=1 last_attempt=... last_success=... reason=3 article(s) in last 30d` (formerly `MISSING ... in last 7d`).

### Issue 7 — Sentiment cần article-level output + URL
- [x] Root cause:
      1. `/soi <SYMBOL>` called `_sentiment_block(..., compact=True)` but the formatter ignored `compact=True`, printing verbose confidence, P/N/N, and event details.
      2. `SentimentQueryService.ticker_sentiment()` computed sentiment metrics but discarded the underlying article list (`items`), returning `SentimentAggregate` without articles.
      3. `format_sentiment` only displayed aggregate stats, omitting the numbered list of individual articles, labels, safe markdown/clickable URLs, timestamps, sources, and scores.
- [x] Added `articles: tuple[NewsItem, ...] = ()` to `SentimentAggregate` (`intelligence/news/service.py`) and populated `articles=items` in `ticker_sentiment()`.
- [x] Added `SentimentArticleView` and `articles: tuple[SentimentArticleView, ...] = ()` to `SentimentView` (`runtime/views.py`).
- [x] Mapped articles in `build_sentiment_view` (`runtime/analysis.py`).
- [x] Added `escape_markdown_link(title, url)` to safely handle brackets in titles and parens/spaces in URLs without breaking Telegram formatting.
- [x] Implemented compact sentiment in `_sentiment_block` (`telegram_bot/formatters.py`) for `/soi`:
      ```
      📰 SENTIMENT
      {label} | score {score:+.2f} | {article_count} bài
      Tin mới nhất: {latest_at}
      ```
- [x] Implemented article-level detail in `format_sentiment` (`telegram_bot/formatters.py`) for `/sentiment` & `sent:<SYM>`:
      - Preserved aggregate header at the top.
      - Numbered list (1..N, max 5 articles <= 30 days).
      - Translated labels (`TÍCH CỰC`, `TIÊU CỰC`, `TRUNG LẬP`).
      - Escaped markdown link `[{safe_title}]({safe_url})`.
      - Metadata line: `Thời gian: {time} | Nguồn: {source}` (time converted to `VIETNAM_TIMEZONE`).
      - Metrics line: `Score: {score:+.2f} | Confidence: {confidence}`.
      - Clickable URL line: `Link: {safe_url}`.
- [x] Tests:
      - Added `test_soi_renders_compact_sentiment`, `test_format_sentiment_includes_articles_with_safe_urls_and_metrics`, `test_sentiment_overview_end_to_end` in `tests/test_stock_dashboard.py`.
      - Full test suite regression: **888/888 passed** (100% green).
- [x] Live verification: Ran against real SQLite database with `HC1`, verifying compact `/soi` output and 3 real articles with clickable URLs in `/sentiment`.

### Issue 8 — Xóa wording 24h còn sót lại
- [x] Code audit & remediation:
      - `telegram_bot/commands.py`: Cập nhật `HELP_TEXT` từ `"/sentiment FPT - sentiment tin tức 24 giờ"` sang `"/sentiment FPT - sentiment tin tức gần đây (tối đa 30 ngày)"`.
      - `runtime/analysis.py`: Cập nhật risk flag trong `build_risk_items` từ `"Sentiment tin tức 24h âm ({sentiment.score:+.2f}); đây là context, không phải lệnh bán"` sang `"Sentiment tin tức âm ({sentiment.score:+.2f}); đây là context, không phải lệnh bán"`.
      - `tests/test_telegram_bot.py`: Cập nhật `FakeData` và assertion loại bỏ `"NEWS SENTIMENT 24h"`, đồng thời thêm assert đảm bảo `24h` và `24 giờ` không còn tồn tại trong `commands.help()`.
      - `tests/test_stock_dashboard.py`: Thêm unit test `test_build_risk_items_removes_24h_wording` đảm bảo `build_risk_items` không chứa wording 24h.
- [x] Full test suite regression: **892/892 passed** (100% green).
- [x] Live verification: Ran `scripts/test_issue8_live.py` against real SQLite databases and command handlers, verifying complete absence of "24h"/"24 giờ" in `/help`, `/start`, `/sentiment HC1`, `/sentiment FPT`, and `/soi` negative sentiment risk alerts.


### Issue 9 — Fundamental data PARTIAL/MISSING & ASMF Point-in-Time fallback
- [x] Audit & Root Cause:
      - ASMF Tầng 2 requires point-in-time financial statements to eliminate look-ahead bias (`public_date <= as_of`).
      - Previously, `corporate_promotion_gap` strictly required an actual `public_date` from providers (`if row.public_date is None: return "no public_date established by provider"`), causing all rows from TCBS, KBS wide, or yfinance to remain stuck in `automated_financial_statements` without promotion to `financial_reports`.
      - Strategy specification does NOT require providers to have an actual `public_date`. The original strategy rule is:
        1. Actual `public_date` present → use actual (`public_date_source="actual"`).
        2. Actual `public_date` absent, but valid `report_period` exists → estimate `public_date = period_end_date(report_period) + 45 days` (`public_date_source="estimated_45d"`).
        3. Never use `period_end_date` directly as `public_date` (strict anti-look-ahead).
        4. No fabrication outside the standard +45 days rule.
        5. If neither `public_date` nor `report_period` is establishable → reject record.
        6. Point-in-time query in ASMF remains unchanged: `public_date <= as_of`.
- [x] Implementation:
      - `fundamentals/providers/base.py`:
        - Added `DEFAULT_FS_PUBLISH_LAG_DAYS = 45`.
        - Added `estimate_publication_date(period, lag_days=45) -> date | None` (returns `period_end_date + lag_days`).
        - Added `public_date_source: str | None = None` and property `effective_public_date` to `StatementRow`.
        - Relaxed `StatementRow.__post_init__` period string check so unparsable raw records can enter promotion pipeline and be rejected with proper diagnostic reasons.
      - `asmf_data/models.py`:
        - Added `public_date_source: str = "actual"` to `FinancialReport` dataclass.
      - `fundamentals/adapters.py`:
        - Implemented `resolve_public_date(row, lag_days=45) -> tuple[date | None, str | None]`.
        - Updated `corporate_promotion_gap` and `promote_corporate_statement` to use `resolve_public_date(row)`.
      - `fundamentals/coverage_store.py`:
        - Updated `upsert_automated_statement` to store `effective_date` resolved via `resolve_public_date(row)`.
      - `fundamentals/providers/vnstock_provider.py`:
        - Added `"TCBS"` into `DEFAULT_SOURCE_PREFERENCE = ("KBS", "VCI", "TCBS")` to enable TCBS financial statement retrieval.
- [x] 8-Quarter Requirement Audit in `fundamental_score`:
      - `asmf_data/scoring.py` strictly checks `len(reports) < 8: return None`.
      - With +45d fallback, symbols with 8 quarters of history from TCBS/yfinance are now unblocked and successfully compute scores (verified: score = 80.0–100.0).
      - Symbols with fewer than 8 quarters of history (e.g. newly listed or partial coverage) will continue to return `None` as intended by the strategy design; requirement was kept intact without dilution.
- [x] Tests:
      - Unit test suite (`tests/test_fundamental_refresh.py`):
        - A: `test_issue9_a_actual_public_date` (actual public_date used directly).
        - B: `test_issue9_b_estimated_public_date_from_report_period` (fallback to period_end + 45 days).
        - C: `test_issue9_c_reject_when_neither_available` (both missing -> rejected).
        - D & E: `test_issue9_d_e_point_in_time_boundary` (`as_of < est_date` invisible, `as_of >= est_date` visible).
        - F: `test_issue9_f_eight_quarters_estimated_public_date_enables_score` (8 quarters with estimated_45d enables score).
      - Point-in-time safety suite (`tests/test_point_in_time_safety.py`):
        - Updated to verify anti-look-ahead with 45d lag.
        - Verified `period_end_date` is never used directly as public_date.
      - Acceptance suite (`tests/test_phase26_acceptance.py`):
        - Verified incomplete rows are staged but not promoted.
        - Verified rows with estimated public_date are staged and promoted.
      - Full test suite regression: **899/899 passed** (100% green).
- [x] Live verification:
      - Script `scripts/test_issue9_live.py` verified end-to-end against live database bootstrap, source preference (`KBS`, `VCI`, `TCBS`), 45d lag arithmetic, anti-look-ahead query boundaries, and 8-quarter threshold.

### Issue 10 — Coverage semantics chưa đồng nhất với ASMF readiness
- [x] Audit & Root Cause:
      - `coverage_worker` and `refresh_service` classified `FINANCIALS` and `INSTITUTIONAL` coverage status based purely on raw provider fetch outcomes rather than canonical database readiness for ASMF strategy layers.
      - For example, if a provider fetch returned 9 raw periods and 8 were promoted while 1 was missing revenue, provider status was `PARTIAL`. `refresh_financials` propagated `status="PARTIAL"` and `error_reason="BLOCKED BY DATA SOURCE: ..."` into `symbol_data_coverage`, despite the fact that `financial_reports` already contained $\ge 8$ valid quarters and ASMF Tầng 2 was fully unblocked!
      - For `MARKET_HISTORY`, `_refresh_market_history` used threshold 126 (sector history minimum) instead of 200 daily bars, which is required by ASMF and CL1 strategy execution (`MINIMUM_STRATEGY_HISTORY = 200`).
      - For `INSTITUTIONAL`, if 5 trading sessions already existed canonically in `institutional_flows`, coverage status was still marked `PARTIAL`/`MISSING` if provider returned partial.
- [x] Implementation:
      - `fundamentals/refresh_service.py`:
        - Added `_count_canonical_financial_reports` to count distinct point-in-time quarters across both `financial_reports` and `bank_financial_reports`.
        - Added `_count_canonical_institutional_flows` to count distinct flow trading sessions in `institutional_flows`.
        - Updated `_point_in_time_gap_reason`: when `canonical_count >= 8`, outputs diagnostic `"READY FOR ASMF ({canonical_count} quarters available); {promoted}/{total} raw period(s) promoted - {detail}"` instead of `"BLOCKED BY DATA SOURCE"`.
        - In `refresh_financials`: if `canonical_count >= 8`, marks `coverage_status = "READY"`. If $1 \le canonical\_count \le 7$, marks `PARTIAL` (`BLOCKED BY DATA SOURCE`). If $0$, marks `MISSING`.
        - In `refresh_institutional_flow`: if `canonical_flow_count >= 5`, marks `coverage_status = "READY"`.
      - `runtime/coverage_worker.py`:
        - Added `MINIMUM_STRATEGY_HISTORY = 200`.
        - Added `strategy_minimum_bars: int = MINIMUM_STRATEGY_HISTORY` to `HistoryClient`.
        - Updated `_refresh_market_history` to evaluate against `200` bars and state `"need {minimum} for ASMF/CL1"`.
      - `tests/coverage_fakes.py`:
        - Updated `FakeHistory` with `strategy_minimum_bars = 200`.
        - Preserved default `statement_count = 1` and `flow_count = 1` on `ScriptedProvider` to avoid statement pollution in unrelated tests.
      - `data/database.py` & `tests/test_phase26_hardening.py`:
        - Reinforced SQLite concurrency handling on Windows (`busy_timeout=30000`).
- [x] Tests:
      - `tests/test_coverage_worker.py`: updated `test_market_history_statuses_and_missing_client` for 200 bars requirement.
      - `tests/test_fundamental_refresh.py`:
        - `test_issue10_eight_quarters_yields_ready_even_if_provider_result_partial`
        - `test_issue10_fewer_than_eight_quarters_yields_partial_when_provider_partial`
        - `test_issue10_five_flow_sessions_yields_ready_for_institutional`
      - Full test suite regression: **902/902 passed in 66.69s** (100% green).
- [x] Live verification:
      - `scripts/test_issue10_live.py` verified FPT has 8 canonical quarters, coverage `READY`, reason `READY FOR ASMF (8 quarters available); 8/9 raw period(s) promoted - no usable revenue value (1 period(s))`, ASMF score `60.0`.
      - Verified VIC has canonical quarters and coverage `READY`.
      - CLI report (`scripts/coverage_report.py --symbol FPT`) confirms `FINANCIALS READY`.

### Integrity remediation Issue 1 — Financial Data Integrity & ASMF Readiness
- [x] Audit YFinance acquisition, canonical readiness, ASMF scoring and `/soi` fundamental rendering.
- [x] Restrict YFinance ingestion to quarterly frames; annual statements are never normalized into Q4.
- [x] Reject every non-quarter `report_period` at the canonical promotion boundary, regardless of provider.
- [x] Mark corrected Yahoo canonical provenance as `/quarterly`, hide all unverified legacy Yahoo rows immediately, and reconcile them on refresh.
- [x] Prevent Yahoo fallback rows from overwriting an existing canonical quarter from VNStock/Vietstock or another preferred source.
- [x] Require the latest eight point-in-time quarters to be contiguous before `FINANCIALS READY`.
- [x] Report exact missing quarters in coverage diagnostics.
- [x] Revalidate the same contiguous window inside corporate and bank ASMF scoring.
- [x] Suppress ROE/revenue-growth/profit-growth TTM metrics when the window is discontinuous.
- [x] Render `/soi` Fundamental as `INSUFFICIENT` with the missing-quarter explanation.
- [x] Preserve actual publication dates, the estimated `period_end + 45 days` fallback, and `public_date <= as_of` queries.
- [x] Rebased onto remote `origin/main` at `2b0b3ae`; preserved valuation snapshot and scanner UX changes.
- [x] Focused verification on integrated remote: 201 fundamentals/PIT/runtime/dashboard/valuation tests passed.
- [x] Full regression on integrated remote: 960 tests passed on Python 3.13 with protobuf's temporary version-check override because installed runtime is 6.33.6 while checked-in gencode is 7.35.0.
- [x] Updated schema-migration test to compare against `LATEST_SCHEMA_VERSION` after remote migration v10.
- [x] Live public-provider verification with `yfinance==1.0` for VNM/HAG against temporary SQLite: annual columns excluded, coverage `PARTIAL`, exact gaps reported, `asmf_score=None`, runtime `INSUFFICIENT`, and no TTM growth rendered.
- [ ] Production database refresh and real Telegram delivery after deployment/restart — NOT TESTED because this clone has no `.env`, Vietcap credentials, bot token, or production database.
- [x] STOP before Issue 2.

## Vietcap IQ bank adapter follow-up (2026-09-25)

- [x] Detect bank payloads from verified non-zero `bsb`/`isb` namespaces instead
      of applying the corporate balance identity.
- [x] Map cumulative bank BCTC fields with balance, loan-netting, interest-income
      and profit identity checks; use the later component publication date.
- [x] Promote only versioned `VietcapIQ/.../bank-ytd-v1` rows into
      `bank_financial_reports`; generic bank rows remain staging-only.
- [x] Distinguish harness `AUTH_FAILURE`, `INSUFFICIENT_DATA` and
      `UNSUPPORTED_SCHEMA` without printing session secrets.
- [x] Live acceptance: ACB PASS 34/34 quarters through 2026Q2; TPB PASS 34/34
      quarters through 2026Q2; VIX correctly reports `UNSUPPORTED_SCHEMA`.
- [x] Forced ACB sync persisted 34 canonical bank quarters; coverage is READY.
- [x] Focused regression: 118 passed; full regression: 1015 passed.
- [x] NPL/LLR and sparse quarterly CAR were recovered from the verified IQ
      `statistics-financial` endpoint in the later risk-metrics follow-up.
- [x] Securities adapter completed in the next follow-up below.
- [x] Insurance adapter completed in the later follow-up below.

## Vietcap IQ securities adapter follow-up (2026-09-25)

- [x] Detect populated `bss`/`iss` schema and normalize verified common BCTC
      totals with balance, revenue and borrowing identity checks.
- [x] Preserve total LNST when historical parent-profit allocation cannot be
      reconciled; leave the uncertain parent-profit field null.
- [x] Preserve `statement_schema=securities` through `ProviderChain`.
- [x] Store securities statements in staging only; never promote them into the
      current corporate ASMF model.
- [x] Reconcile legacy misclassified data by deleting only IQ-owned canonical
      rows; manual and other-provider evidence remains untouched.
- [x] Live acceptance: VIX and SSI PASS with 34/34 quarters through 2026Q2.
- [x] Forced sync: VIX and SSI each have 34 staged quarters, zero promoted rows,
      zero IQ-owned canonical rows, and explicit FINANCIALS PARTIAL diagnostics.
- [x] Focused regression: 123 passed; full regression: 1020 passed.
- [x] Insurance adapter completed in the next follow-up below.

## Vietcap IQ insurance adapter follow-up (2026-09-25)

- [x] Detect `bsi`/`isi` schema and normalize net insurance operating revenue,
      total/parent profit, balance totals, equity and borrowings.
- [x] Validate the three-stage insurance premium/revenue identities before
      accepting an income row.
- [x] Support historical insurance balance forms without inventing a missing
      current/non-current liability allocation.
- [x] Preserve `statement_schema=insurance` through the provider chain and keep
      all insurance rows staging-only.
- [x] Live acceptance: BVH and ABI PASS with 34/34 quarters through 2026Q2.
- [x] Forced sync: BVH and ABI each have 34 staged quarters, zero promoted rows,
      zero IQ-owned canonical rows, and explicit FINANCIALS PARTIAL diagnostics.
- [x] Focused regression: 126 passed; full regression: 1023 passed.

## Vietcap IQ bank risk-metrics follow-up (2026-09-25)

- [x] Audit the IQ frontend bundle and verify the exact authenticated
      `/company/{ticker}/statistics-financial` route without guessing fields.
- [x] Map quarter-specific NPL, LLR and CAR; exclude annual `quarter=5`, treat
      zero CAR as missing, and never forward-fill prudential ratios.
- [x] Derive NPL balance only when `reserve / NPL = abs(LLR)` reconciles; reject
      mismatched historical periods fail-closed.
- [x] Version canonical provenance as `/bank-ytd-risk-v2` and preserve actual
      statement publication dates for point-in-time visibility.
- [x] Live acceptance: ACB PASS with 31 NPL/6 CAR quarters; TPB PASS with
      30 NPL/6 CAR quarters; both retain 34 complete BCTC quarters through 2026Q2.
- [x] Forced sync: ACB/TPB each persisted 34 canonical bank rows from the v2
      source and report `FINANCIALS READY`.
- [x] Historical point-in-time ASMF at 2025-09-30: ACB=33.33, TPB=50.0.
      Current 2026Q2 scores correctly remain unavailable because CAR is absent.
- [x] Focused regression: 137 passed; full regression: 1025 passed.
- [x] Guard `scripts/test_soi_asmf_live.py` against import-time execution so
      pytest collection does not require live market credentials.

## Vietcap IQ FPT schema false-positive fix (2026-09-25)

- [x] Reproduce the live payload shape: FPT has valid corporate `bsa`/`isa`
      statements plus isolated non-zero `bsb108` and `bss136` fields.
- [x] Require paired balance+income namespace evidence for bank, securities and
      insurance classification; a lone cross-industry field cannot override a
      valid corporate schema.
- [x] Add a regression fixture for the exact FPT false-positive shape.
- [x] Focused regression: 84 passed; full regression: 1026 passed.
- [x] Live acceptance: FPT=corporate, VIX=securities and ABI=insurance, each
      with 34 complete quarters and 34 actual publication dates through 2026Q2.

## Telegram financial-evidence status follow-up (2026-09-25)
- [x] When no canonical facts exist but automated BCTC rows are staged, `/fundamental` and `/soi` now show PARTIAL/INSUFFICIENT with fetched quarter count, source and reason instead of the generic `Fundamental data missing.`
- [x] When no report evidence exists but a FINANCIALS coverage record does, the commands show its MISSING/ERROR/STALE status and recorded reason.
- [x] Securities BCTC is identified as acquired but staging-only; the ASMF Fundamental layer remains MISSING and BUY remains blocked because no securities ASMF model exists.
- [x] Preserve point-in-time behavior: a staged report published after the analyzed price date is explicitly marked unavailable for that analysis.
- [x] Focused Telegram/dashboard/provider regression: **161 passed**; full `python -m pytest tests/ -q` with the protobuf version-check override: **1035 passed**.
- [ ] No production DB or `.env` is available in this checkout; DCM's live coverage row and SSI's live staging row remain NOT TESTED here.

