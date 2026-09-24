# Vietnamese Stock Signal Telegram Bot

Bot Telegram phân tích cổ phiếu Việt Nam, cung cấp dữ liệu thị trường, phân tích
kỹ thuật, chiến lược CL1/ASMF, tin tức và sentiment, biểu đồ nến, danh mục đầu
tư và quản trị rủi ro. Bot chỉ cung cấp thông tin hỗ trợ quyết định, không đặt
lệnh và không kết nối Trading API.

## Trạng thái hiện tại

Tính đến ngày 2026-09-21:

- Các luồng realtime Phase 3–7 đã có bằng chứng live: giá khớp FPT/ACB, VNINDEX,
  bid/ask và tự phục hồi sau khi WebSocket bị ngắt.
- Telegram, chiến lược, scanner, news/sentiment, portfolio và risk đã được triển
  khai và có test tự động.
- Phase 23 portfolio/risk đã PASS live bằng database tạm và dữ liệu Vietcap EOD.
- Liên kết news/sentiment dùng danh mục mã động, không còn giới hạn ở một nhóm
  ticker hard-code.
- Biểu đồ nến đã hoàn thành code và test offline; gửi ảnh `/chart` thật qua
  Telegram với dữ liệu Vietcap thật vẫn chưa được xác nhận live.

Bot chấp nhận mã cổ phiếu hợp lệ ngoài `BOT_WATCH_SYMBOLS`, nhưng điều này không
đồng nghĩa mọi mã luôn có đầy đủ mọi lớp dữ liệu.

| Chức năng | Phạm vi hiện tại |
|---|---|
| Giá và lịch sử | Hoạt động khi Vietcap có dữ liệu cho mã |
| Kỹ thuật và CL1 | Cần đủ số phiên lịch sử; mã mới có thể báo thiếu dữ liệu |
| ASMF | Cần đồng thời dữ liệu ngành, BCTC và dòng tiền tổ chức |
| News/sentiment | Mọi mã trong universe đều có thể được liên kết; chỉ có kết quả khi đã ingest tin liên quan |
| Biểu đồ nến | Dùng lịch sử Vietcap hoặc SQLite fallback; cần tối thiểu 5 phiên |
| Portfolio/risk | Hoạt động với mã có lịch sử giá; định giá hiện dùng historical/EOD |

Telegram runtime hiện đi theo hướng historical-first: `/soi`, `/chart` và định
giá danh mục lấy lịch sử Vietcap trước, sau đó mới dùng SQLite cache khi provider
lỗi. Các luồng WebSocket realtime đã được kiểm thử độc lập, nhưng không phải mọi
phản hồi Telegram đều lấy trực tiếp từ WebSocket.

## Giới hạn dữ liệu cần biết

- BCTC và các chỉ số cơ bản như EPS, P/E, P/B, ROE, tăng trưởng doanh thu/lợi
  nhuận chưa được tự động phủ toàn thị trường. Runtime đọc dữ liệu point-in-time
  đã import vào SQLite và/hoặc file CSV cấu hình.
- Kho dữ liệu dòng tiền khối ngoại/tự doanh và logic chấm điểm đã có, nhưng dữ
  liệu thực tế chưa được tự động cập nhật đầy đủ cho mọi mã.
- ASMF fail closed: thiếu ngành, BCTC hoặc dòng tiền tổ chức thì lớp tương ứng là
  `MISSING` và bot không tạo tín hiệu `BUY` từ dữ liệu chưa đủ.
- Dữ liệu ngành của mã chưa cache được đồng bộ nền. Lệnh không chờ network và bot
  sẽ thông báo khi batch đồng bộ hoàn tất hoặc vẫn chưa đủ peer history.
- Sentiment cần một lượt ingest CafeF và một bài viết có thể liên kết với ticker
  hoặc tên doanh nghiệp. Không có kết quả sentiment không đồng nghĩa mã bị lỗi.
- Mã không hợp lệ, ngừng niêm yết, mới niêm yết hoặc thiếu lịch sử sẽ trả thông
  báo thiếu dữ liệu thay vì tạo kết quả giả.

## Lệnh Telegram

Phân tích thị trường và cổ phiếu:

```text
/soi FPT [CL1|ASMF]
/why FPT
/technical FPT
/fundamental FPT
/sentiment FPT
/tin FPT
/sector FPT
/chart FPT
/market
/scan
/chienluoc
/performance
/performance CL1
/performance ASMF
```

Chạy backtest từ dữ liệu ngày đã cache trong SQLite. Settlement là số phiên giao
dịch do người chạy chọn; repo không tự giả định T+2 hay T+2.5. Mặc định job dùng
phí 0.15% mỗi chiều, thuế bán 0.10%, slippage 0.20%, lô 100 cổ phiếu và vốn
500 triệu VND; tất cả đều có thể đổi bằng CLI flags:

```powershell
py -3.12 -m scripts.run_cl1_backtest --symbols FPT,ACB --start-date 2025-01-01 --end-date 2026-09-23 --settlement-sessions 2
py -3.12 -m scripts.run_asmf_backtest --symbols FPT,ACB --start-date 2025-01-01 --end-date 2026-09-23 --settlement-sessions 2
```

Danh mục và rủi ro, chỉ dùng trong private chat:

```text
/watchlist
/addwatch FPT
/removewatch FPT
/portfolio
/addholding FPT 1000 150000
/removeholding FPT
/risk
/size FPT 150000 142000 500000000 [risk_pct]
/stress portfolio -5
/stress FPT -10
/setrisk 1
/risksettings
```

`/addholding` là upsert: nếu vị thế đã tồn tại, số lượng và giá vốn trung bình sẽ
được thay thế. P&L là unrealized và chưa bao gồm phí hoặc thuế. V1 chưa có sổ
giao dịch và realized P&L.

## Cài đặt

Yêu cầu Python 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3.12 -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Cấu hình tối thiểu trong `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=
DATABASE_URL=sqlite:///stock_bot.db
BOT_WATCH_SYMBOLS=FPT:HOSE,ACB:HOSE
```

Các endpoint Vietcap có thể cần `VIETCAP_AUTHORIZATION`, `VIETCAP_DEVICE_ID` và
`VIETCAP_COOKIE` tùy trạng thái giao diện phía provider. Không commit `.env` và
không ghi token/cookie vào log.

## Chạy bot

```powershell
py -3.12 -m scripts.run_telegram_bot
```

Tiến trình này khởi tạo runtime, SQLite migrations, Telegram polling, sector
history worker, coverage worker (Phase 25) và notification dispatcher. Dừng
bằng `Ctrl+C`.

### Coverage worker và script quản trị (Phase 25)

Worker nền làm mới fundamentals, institutional flow, lịch sử giá, sector history
và news theo từng batch nhỏ cho các mã trong bảng `symbols`. Lệnh Telegram chỉ
đọc dữ liệu đã lưu, không gọi VNStock/Yahoo/CafeF. Cấu hình ở `.env.example`
(`COVERAGE_*`, `*_REFRESH_INTERVAL`; tắt bằng `COVERAGE_WORKER_ENABLED=false`).

```powershell
py -3.12 scripts\sync_fundamentals.py --symbol FPT --force
py -3.12 scripts\sync_institutional_flow.py --limit 10
py -3.12 scripts\sync_market_coverage.py --dry-run
py -3.12 scripts\coverage_report.py
```

## Nạp news và sentiment

Telegram chỉ đọc news database, không gọi CafeF ngay trong command path. Chạy
một batch ingest có giới hạn:

```powershell
py -3.12 scripts\run_news_once.py --limit 20
```

Backend mặc định là `FiinGroup/phobert-finetuned`; có thể cấu hình fallback qua
các biến `SENTIMENT_*` trong `.env.example`.

## Nạp dữ liệu ASMF

Import các CSV đã chuẩn hóa:

```powershell
py -3.12 scripts\import_asmf_eod.py --sectors sectors.csv
py -3.12 scripts\import_asmf_eod.py --financials financials.csv
py -3.12 scripts\import_asmf_eod.py --bank-financials bank_financials.csv
py -3.12 scripts\import_asmf_eod.py --flows institutional_flows.csv
```

Mỗi dòng dữ liệu phải có nguồn và mốc thời gian/as-of phù hợp. BCTC sử dụng ngày
công bố thật để tránh look-ahead trong phân tích và backtest.

## Kiểm thử

Toàn bộ test suite:

```powershell
py -3.12 -m pytest -q
```

Các harness live chính:

```powershell
py -3.12 scripts\test_realtime.py --hold-seconds 45 --min-updates 2 --raw-debug
py -3.12 scripts\test_realtime_market_state.py --hold-seconds 45 --min-updates-per-symbol 2 --raw-debug
py -3.12 scripts\test_realtime_index.py --hold-seconds 45 --min-updates-per-symbol 2 --raw-debug
py -3.12 scripts\test_realtime_bidask.py --hold-seconds 45 --min-updates-per-symbol 2 --raw-debug
py -3.12 scripts\test_realtime_reconnect.py --stage-timeout 45 --raw-debug
```

Acceptance có giới hạn của Phase 24/26 (dùng DB tạm, không polling, kết quả
`PASS`/`FAIL`/`NOT TESTED`; `--send` cần `TELEGRAM_BOT_TOKEN` và
`TEST_TELEGRAM_CHAT_ID`):

```powershell
py -3.12 scripts\test_phase24_live.py
py -3.12 scripts\test_phase26_telegram_live.py --send
```

Chỉ chạy các harness thị trường trong phiên giao dịch nếu muốn kiểm tra dữ liệu
thay đổi. Không xem một kết quả zero-event ngoài phiên là bằng chứng PASS.

## Cấu trúc chính

```text
data/           acquisition, protobuf, normalization, market state, SQLite
runtime/        orchestration cho Telegram và background workers
strategy/       CL1, ASMF và signal engine dùng chung
scanner/        universe và liquidity pre-screen
fundamentals/   mô hình, CSV boundary và fundamental context
asmf_data/      sector, BCTC, institutional flow và scoring
intelligence/   news ingestion và sentiment
portfolio/      holdings, valuation, risk, sizing và stress test
charts/         candlestick renderer
telegram_bot/   commands, formatters, handlers và alerts
scripts/        entry points, import tools và live acceptance harnesses
tests/          unit/integration regression suite
```

Tài liệu chi tiết:

- [`TASKS.md`](TASKS.md): phase gates và acceptance evidence.
- [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md): trạng thái kỹ thuật và lịch sử thay đổi.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): kiến trúc và ranh giới dữ liệu.
- [`docs/VIETCAP_PROTOCOL.md`](docs/VIETCAP_PROTOCOL.md): giao thức Vietcap đã quan sát.
- [`docs/SIGNAL_DESIGN.md`](docs/SIGNAL_DESIGN.md): thiết kế tín hiệu.

## Không thuộc V1

- Đặt lệnh thật hoặc tự động giao dịch.
- Trading API của công ty chứng khoán.
- Cam kết lợi nhuận hoặc dự báo giá bằng ML.
- Tín hiệu ASMF được suy diễn khi thiếu dữ liệu đầu vào.
