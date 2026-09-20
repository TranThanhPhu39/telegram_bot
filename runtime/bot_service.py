"""Historical-first runtime service backing Telegram commands.

The service orchestrates the existing domain modules (history provider, SQLite
cache, indicators, strategies, ASMF stores, fundamentals and news) into view
models.  Rendering belongs to ``telegram_bot.formatters``; no presentation
string is built here beyond short operational messages.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import os
import sqlite3
import time
from collections.abc import Callable
from typing import Protocol, Sequence

from dotenv import load_dotenv

from asmf_data.scoring import fundamental_score, institutional_flow_score, sector_strength_score
from asmf_data.store import active_sector, sector_members
from data.database import connect_database
from data.indicators import ema20, ema50, rsi14
from data.migrations import bootstrap_schema
from data.models import OHLCVBar
from data.vietcap.historical import normalize_gap_chart
from data.vietcap.rest import VietcapRestClient, VietcapRestError, VietcapTimeFrame
from fundamentals.repository import FundamentalFacts, load_fundamental_facts
from runtime.analysis import (
    build_market_view,
    build_price_view,
    build_risk_items,
    build_scan_row,
    build_sentiment_view,
    build_strategy_view,
    build_technical_view,
    describe_freshness,
    interpret_indicators,
    session_date,
)
from portfolio.config import PortfolioConfig
from runtime.portfolio_runtime import PortfolioRuntime
from runtime.views import (
    DataQualityView,
    Freshness,
    FundamentalView,
    MetricView,
    NewsItemView,
    SectorView,
    SentimentView,
    StockAnalysisView,
)
from scanner.universe import ScannerConfig, ScannerInstrument, daily_prescreen, realtime_watch_universe
from strategy.technical_strategies import (
    StrategyAction,
    StrategyLayer,
    evaluate_asmf,
    evaluate_cl1,
)
from telegram_bot.portfolio_formatters import format_portfolio_context
from telegram_bot.formatters import (
    format_data_quality,
    format_fundamental,
    format_market,
    format_news,
    format_scan,
    format_sector,
    format_sentiment,
    format_stock_overview,
    format_technical,
    format_why,
)


VIETNAM_TIMEZONE = timezone(timedelta(hours=7))
NEWS_UNAVAILABLE = "News sentiment unavailable."
MINIMUM_SECTOR_HISTORY = 126


class HistoricalClient(Protocol):
    def get_gap_chart(self, symbols: tuple[str, ...], *, time_frame: object, count_back: int, to_timestamp: int) -> list[dict[str, object]]: ...


class NewsService(Protocol):
    def latest_news(self, ticker: str, limit: int = 5): ...
    def ticker_sentiment(self, ticker: str, hours: int = 24): ...
    def severe_negative(self, ticker: str, **kwargs): ...


class RuntimeBotDataService:
    """Connect REST history, SQLite cache, indicators, scanner, and Telegram."""

    def __init__(
        self,
        client: HistoricalClient,
        connection: sqlite3.Connection,
        instruments: tuple[ScannerInstrument, ...],
        *,
        history_count: int = 260,
        news_service: NewsService | None = None,
        now: Callable[[], float] = time.time,
        fundamentals_csv_path: str | None = None,
    ) -> None:
        self.client = client
        self.connection = connection
        self.instruments = instruments
        self.history_count = history_count
        self.news_service = news_service
        self.now = now
        self.fundamentals_csv_path = fundamentals_csv_path
        bootstrap_schema(connection)
        self.portfolio = PortfolioRuntime(
           connection, self._history, lambda: self.now(), PortfolioConfig.from_env() 
        )
    # ---------------------------------------------------------------- views

    def stock_analysis(self, symbol: str, strategy: str = "CL1") -> StockAnalysisView:
        """Build one complete view; a failing section never removes the others."""
        symbol = symbol.strip().upper()
        bars, source = self._history(symbol)
        if not bars:
            return StockAnalysisView(
                symbol=symbol, price=None, technical=None, market=None,
                strategy=None, fundamental=None, sentiment=None,
                data_quality=self._data_quality(None, source),
                error=f"Chưa có dữ liệu lịch sử cho {symbol}. Nguồn: {source}",
            )
        benchmark, benchmark_source = self._history("VNINDEX")
        price = build_price_view(bars)
        technical = build_technical_view(bars, benchmark)
        market = build_market_view(benchmark)
        sentiment = self._sentiment_view(symbol)
        facts = self._fundamental_facts(symbol, bars[-1].timestamp)
        strategy_view = self._strategy_view(strategy, bars, benchmark, sentiment)
        fundamental = self._fundamental_view(symbol, facts, bars[-1].timestamp)
        risks, watch = build_risk_items(technical, market, strategy_view, sentiment)
        notes: list[str] = []
        if not benchmark:
            notes.append(
                f"VNINDEX không khả dụng ({benchmark_source}); bối cảnh thị trường bị giới hạn."
            )
        if facts is None:
            notes.append("Chưa có dữ liệu cơ bản point-in-time cho mã này.")
        return StockAnalysisView(
            symbol=symbol,
            price=price,
            technical=technical,
            market=market,
            strategy=strategy_view,
            fundamental=fundamental,
            sentiment=sentiment,
            data_quality=self._data_quality(
                bars[-1].timestamp, source, facts=facts, sentiment=sentiment,
                notes=tuple(notes),
            ),
            risks=risks,
            watch_items=watch,
        )

    # ------------------------------------------------------------- commands

    def symbol_overview(
            self, symbol: str, strategy: str = "CL1", user_id: int | None = None
    ) -> str:
        view = self.stock_analysis(symbol, strategy)
        extra: tuple[str, ...] = ()
        if user_id is not None and not view.error:
            extra = (format_portfolio_context(self.portfolio.context_for(user_id, symbol)),)
        return format_stock_overview(view, extra)        

    def technical_overview(self, symbol: str) -> str:
        return format_technical(self.stock_analysis(symbol))

    def fundamental_overview(self, symbol: str) -> str:
        return format_fundamental(self.stock_analysis(symbol))

    def signal_explanation(self, symbol: str) -> str:
        view = self.stock_analysis(symbol)
        if view.error:
            return view.error
        return format_why(view, interpret_indicators(view.technical))

    def market_overview(self) -> str:
        bars, source = self._history("VNINDEX")
        market = build_market_view(bars)
        if market is None:
            return f"Chưa có dữ liệu lịch sử VNINDEX. Nguồn: {source}"
        quality = self._data_quality(bars[-1].timestamp, source)
        return format_market(
            market, self._sentiment_view("VNINDEX"), format_data_quality(quality)
        )

    def sentiment_overview(self, symbol: str) -> str:
        return format_sentiment(symbol.strip().upper(), self._sentiment_view(symbol))

    def latest_news(self, symbol: str) -> str:
        if self.news_service is None:
            return NEWS_UNAVAILABLE
        try:
            items = self.news_service.latest_news(symbol, 5)
        except Exception:
            return NEWS_UNAVAILABLE
        return format_news(symbol.strip().upper(), tuple(
            NewsItemView(
                published_at=item.published_at, title=item.title, source=item.source,
                event_type=item.event_type,
                sentiment_label=item.sentiment.label.value if item.sentiment else None,
            )
            for item in items
        ))

    def scan_results(self) -> tuple[str, ...]:
        """Preserved contract: ordered ticker tuple for backward compatibility."""
        histories = {item.symbol: self._history(item.symbol)[0] for item in self.instruments}
        config = ScannerConfig(20, 0.0, 0.0, min(20, len(self.instruments)) or 1)
        screened = daily_prescreen(
            self.instruments, histories, config, as_of_timestamp=int(self.now()) + 1
        )
        return realtime_watch_universe(screened, config)

    def scan_overview(self) -> str:
        """Explain why each screened symbol is on the watch list."""
        symbols = self.scan_results()
        if not symbols:
            return "Chưa có mã đạt bộ lọc."
        benchmark = self._load("VNINDEX")
        rows = []
        for symbol in symbols:
            bars = self._load(symbol)
            technical = build_technical_view(bars, benchmark) if bars else None
            strategy_view = None
            status = None
            if bars:
                try:
                    strategy_view = build_strategy_view(evaluate_cl1(bars))
                except ValueError:
                    strategy_view = None
                status = self._fundamental_status(symbol, bars[-1].timestamp)
            rows.append(build_scan_row(symbol, technical, strategy_view, True, status))
        return format_scan(tuple(rows))

    def sector_overview(self, name: str) -> str:
        return format_sector(self.sector_view(name))

    def strategy_catalog(self) -> str:
        return (
            "Chiến lược khả dụng:\n\n"
            "• CL1 — Trend Rider\n"
            "  Mục tiêu: bám xu hướng trung hạn đã xác nhận.\n"
            "  Điều kiện vào: EMA20 cắt lên EMA50 (≤3 phiên), RSI14 trong (50,72),\n"
            "  ADX14 > 20, KLGD TB3 > TB20, giá > MA200.\n"
            "  Điều kiện thoát: EMA20 cắt xuống EMA50 hoặc thủng Chandelier Exit\n"
            "  (đỉnh 22 phiên − 3×ATR14).\n"
            "  Dữ liệu cần: ≥200 phiên OHLCV ngày.\n\n"
            "• ASMF — nhiều tầng độc lập\n"
            "  Tầng: Market regime, Sector, Fundamental, Institutional flow,\n"
            "  Technical, và Sentiment (chỉ là context).\n"
            "  Chỉ phát MUA khi không tầng nào thiếu dữ liệu và thị trường không RISK-OFF.\n"
            "  Dữ liệu cần: lịch sử ngành, BCTC theo public_date, dòng tiền tổ chức.\n\n"
            "CL1 và ASMF được giữ độc lập, không gộp thành một điểm số chung.\n"
            "Không tầng nào là 'AI prediction'.\n"
            "Dùng: /soi ACB CL1 hoặc /soi ACB ASMF"
        )

    def performance_overview(self) -> str:
        return (
            "📉 HIỆU NĂNG\n\n"
            "ENGINE TEST (kiểm thử cơ chế, KHÔNG phải kiểm định chiến lược)\n"
            "Mẫu: 120 phiên ACB/VNINDEX (175 ngày lịch)\n"
            "Giao dịch: 0 | Win rate: 0.00% | Lợi nhuận TB: 0.00%\n"
            "Max drawdown: 0.00% | Profit factor: N/A\n\n"
            "STRATEGY VALIDATION\n"
            "Chưa thực hiện. No trades generated in this sample; metrics do not "
            "establish strategy profitability.\n"
            "Cần backtest nhiều mã, nhiều chu kỳ và out-of-sample trước khi kết luận."
        )

    # ------------------------------------------------------------- internals

    def sector_view(self, name: str) -> SectorView | None:
        """Resolve a ticker or a sector code using stored evidence only."""
        key = name.strip().upper()
        as_of = datetime.fromtimestamp(self.now(), VIETNAM_TIMEZONE).date()
        membership = active_sector(self.connection, key, as_of)
        if membership is not None:
            code = membership["sector_code"]
            label = membership["sector_name"]
            source = membership["source"]
        else:
            row = self.connection.execute(
                "SELECT sector_name, source FROM sector_memberships WHERE sector_code=? LIMIT 1",
                (key,),
            ).fetchone()
            if row is None:
                return None
            code, label, source = key, row["sector_name"], row["source"]
        members = sector_members(self.connection, code, as_of)
        if not members:
            return SectorView(
                code, label, 0, None, None, None, missing=("thành viên ngành",),
                as_of=as_of.isoformat(), source=source,
            )
        benchmark = self._load("VNINDEX")
        usable = {
            symbol: bars for symbol, bars in
            ((item, self._load(item)) for item in members)
            if len(bars) >= MINIMUM_SECTOR_HISTORY
        }
        missing: list[str] = []
        strength = breadth = relative = None
        leaders: tuple[tuple[str, float], ...] = ()
        laggards: tuple[tuple[str, float], ...] = ()
        if len(usable) < 5:
            missing.append(f"chỉ có {len(usable)}/{len(members)} mã đủ 126 phiên trong SQLite")
        if len(benchmark) < MINIMUM_SECTOR_HISTORY:
            missing.append("lịch sử VNINDEX chưa đủ 126 phiên")
        if len(usable) >= 5 and len(benchmark) >= MINIMUM_SECTOR_HISTORY:
            strength = sector_strength_score(
                self.connection, members[0], as_of, usable, benchmark
            )
            breadth = 100.0 * sum(
                bars[-1].close > sum(item.close for item in bars[-50:]) / 50
                for bars in usable.values()
            ) / len(usable)
            returns = {
                symbol: (bars[-1].close / bars[-22].close - 1.0) * 100.0
                for symbol, bars in usable.items()
            }
            benchmark_return = (benchmark[-1].close / benchmark[-22].close - 1.0) * 100.0
            relative = sum(returns.values()) / len(returns) - benchmark_return
            ordered = sorted(returns.items(), key=lambda item: item[1], reverse=True)
            leaders, laggards = tuple(ordered[:3]), tuple(ordered[-3:][::-1])
        return SectorView(
            sector_code=code, sector_name=label, member_count=len(members),
            strength_score=strength, breadth_percent=breadth, relative_strength=relative,
            leaders=leaders, laggards=laggards, missing=tuple(missing),
            as_of=as_of.isoformat(), source=source,
        )

    def _strategy_view(self, strategy, bars, benchmark, sentiment):
        name = strategy.strip().upper() if isinstance(strategy, str) else "CL1"
        if name not in {"CL1", "ASMF"}:
            name = "CL1"
        try:
            result = evaluate_cl1(bars) if name == "CL1" else self._evaluate_asmf(bars, benchmark)
        except ValueError as error:
            return build_strategy_view(
                _insufficient_result(name, bars, str(error)),
                note=f"Chưa đủ dữ liệu: {error}",
            )
        if name == "ASMF":
            result = replace(result, layers=result.layers + (_sentiment_layer(sentiment),))
        return build_strategy_view(result)

    def _evaluate_asmf(self, bars, benchmark):
        as_of = datetime.fromtimestamp(bars[-1].timestamp, VIETNAM_TIMEZONE).date()
        symbol = bars[-1].symbol
        fundamental = fundamental_score(self.connection, symbol, as_of)
        flow = institutional_flow_score(self.connection, symbol, as_of)
        # The membership snapshot is knowledge available at runtime; financial
        # and flow inputs remain point-in-time at the last completed bar.
        membership_as_of = datetime.fromtimestamp(self.now(), VIETNAM_TIMEZONE).date()
        histories = self._sector_histories(symbol, bars, membership_as_of)
        sector = sector_strength_score(
            self.connection, symbol, membership_as_of, histories, benchmark
        )
        result = evaluate_asmf(
            bars, benchmark, sector_score=sector,
            fundamental_score=fundamental, institutional_flow_score=flow,
        )
        if result.action == StrategyAction.BUY and self._severe_negative_news(symbol) is not None:
            result = replace(
                result,
                action=StrategyAction.BLOCKED,
                negative=result.negative + ("tin phap ly tieu cuc nghiem trong con hieu luc",),
            )
        return result

    def _sentiment_view(self, symbol: str) -> SentimentView:
        if self.news_service is None:
            return SentimentView(available=False, note=NEWS_UNAVAILABLE)
        try:
            aggregate = self.news_service.ticker_sentiment(symbol.strip().upper(), 24)
        except Exception:
            return SentimentView(available=False, note=NEWS_UNAVAILABLE)
        return build_sentiment_view(aggregate)

    def _fundamental_facts(self, symbol: str, timestamp: int) -> FundamentalFacts | None:
        as_of = datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE).date()
        try:
            return load_fundamental_facts(
                self.connection, symbol, as_of, csv_path=self.fundamentals_csv_path
            )
        except (sqlite3.Error, OSError, ValueError):
            return None

    def _fundamental_status(self, symbol: str, timestamp: int) -> str:
        as_of = datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE).date()
        try:
            score = fundamental_score(self.connection, symbol, as_of)
        except (sqlite3.Error, ValueError, ZeroDivisionError):
            return "INSUFFICIENT"
        if score is None:
            return "INSUFFICIENT"
        return "PASS" if score >= 60 else "FAIL"

    def _fundamental_view(
        self, symbol: str, facts: FundamentalFacts | None, timestamp: int
    ) -> FundamentalView | None:
        if facts is None:
            return None
        if facts.kind == "BANK":
            metrics = (
                MetricView("ROE (TTM)", facts.roe_percent, "%"),
                MetricView("Tăng trưởng LNST (TTM)", facts.profit_growth_percent, "%"),
                MetricView("NPL", facts.npl_percent, "%"),
                MetricView("Bao phủ nợ xấu", facts.coverage_percent, "%"),
                MetricView("CAR", facts.car_percent, "%"),
                MetricView("P/E", facts.pe, ""),
                MetricView("P/B", facts.pb, ""),
                MetricView("EPS", facts.eps, ""),
            )
        else:
            metrics = (
                MetricView("P/E", facts.pe, ""),
                MetricView("P/B", facts.pb, ""),
                MetricView("ROE (TTM)", facts.roe_percent, "%"),
                MetricView("Tăng trưởng doanh thu (TTM)", facts.revenue_growth_percent, "%"),
                MetricView("Tăng trưởng LNST (TTM)", facts.profit_growth_percent, "%"),
                MetricView("Debt/Equity", facts.debt_to_equity, ""),
                MetricView("EPS", facts.eps, ""),
            )
        return FundamentalView(
            status=self._fundamental_status(symbol, timestamp),
            metrics=metrics,
            as_of=facts.as_of,
            source=facts.source,
            period=facts.period,
            kind=facts.kind,
            missing=facts.missing_fields,
            note="P/E, P/B chỉ hiển thị khi có snapshot cung cấp; bot không tự tính fair value.",
        )

    def _data_quality(
        self,
        latest_timestamp: int | None,
        source: str,
        *,
        facts: FundamentalFacts | None = None,
        sentiment: SentimentView | None = None,
        notes: tuple[str, ...] = (),
    ) -> DataQualityView:
        cached = source.startswith("SQLite")
        freshness, staleness = describe_freshness(latest_timestamp, self.now(), cached=cached)
        extra = list(notes)
        if cached:
            extra.append("Provider không phản hồi; đang dùng bản lưu SQLite (cached/EOD).")
        if freshness is Freshness.STALE:
            extra.append("Dữ liệu đã cũ; hãy làm mới trước khi ra quyết định.")
        return DataQualityView(
            freshness=freshness,
            session_date=None if latest_timestamp is None else session_date(latest_timestamp),
            staleness_days=staleness,
            market_source=source,
            fundamental_source=None if facts is None else facts.source,
            fundamental_as_of=None if facts is None else facts.as_of,
            news_latest_at=None if sentiment is None else sentiment.latest_at,
            news_source=(
                None if sentiment is None or not sentiment.available
                else (", ".join(sentiment.backends) or "news module")
            ),
            notes=tuple(dict.fromkeys(extra)),
        )

    def _severe_negative_news(self, symbol: str):
        if self.news_service is None or os.getenv(
            "ASMF_NEWS_BLOCKER_ENABLED", "true"
        ).lower() != "true":
            return None
        try:
            events = tuple(filter(None, (
                value.strip().upper() for value in os.getenv(
                    "ASMF_NEWS_BLOCKER_EVENTS", "LEGAL"
                ).split(",")
            )))
            return self.news_service.severe_negative(
                symbol, events=events,
                negative_threshold=float(os.getenv("ASMF_NEWS_NEGATIVE_THRESHOLD", ".75")),
                confidence_threshold=float(os.getenv("ASMF_NEWS_CONFIDENCE_THRESHOLD", ".70")),
                max_age_hours=float(os.getenv("ASMF_NEWS_MAX_AGE_HOURS", "48")),
            )
        except (OSError, ValueError, sqlite3.Error):
            return None

    def _history(self, symbol: str) -> tuple[tuple[OHLCVBar, ...], str]:
        symbol = symbol.strip().upper()
        try:
            payload = self.client.get_gap_chart(
                (symbol,), time_frame=VietcapTimeFrame.ONE_DAY,
                count_back=self.history_count, to_timestamp=int(self.now()),
            )
            bars = tuple(
                bar for bar in normalize_gap_chart(payload, time_frame=VietcapTimeFrame.ONE_DAY)
                if bar.symbol == symbol
            )
            if bars:
                self._store(symbol, bars)
                return bars, "Vietcap historical"
        except (VietcapRestError, ValueError):
            pass
        cached = self._load(symbol)
        return cached, "SQLite cache" if cached else "Vietcap/SQLite đều không có dữ liệu"

    def _sector_histories(
        self, symbol: str, bars: tuple[OHLCVBar, ...], membership_as_of: date,
    ) -> dict[str, tuple[OHLCVBar, ...]]:
        """Load sector histories from SQLite without blocking Telegram on I/O."""
        histories = {symbol: bars}
        membership = active_sector(self.connection, symbol, membership_as_of)
        if membership is None:
            return histories
        for member in sector_members(self.connection, membership["sector_code"], membership_as_of):
            if member == symbol:
                continue
            cached = self._load(member)
            if len(cached) >= MINIMUM_SECTOR_HISTORY:
                histories[member] = cached
        return histories

    def _store(self, symbol: str, bars: tuple[OHLCVBar, ...]) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO symbols(symbol, instrument_type) VALUES (?, 'STOCK') "
                "ON CONFLICT(symbol) DO NOTHING", (symbol,),
            )
            self.connection.executemany(
                "INSERT INTO candles(symbol,timeframe,timestamp,open,high,low,close,volume) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(symbol,timeframe,timestamp) DO UPDATE SET "
                "open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume",
                [(bar.symbol, bar.timeframe, bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in bars],
            )

    def _load(self, symbol: str) -> tuple[OHLCVBar, ...]:
        rows = self.connection.execute(
            "SELECT * FROM candles WHERE symbol=? AND timeframe='ONE_DAY' ORDER BY timestamp DESC LIMIT ?",
            (symbol, self.history_count),
        ).fetchall()
        return tuple(
            OHLCVBar(row["symbol"], row["timeframe"], row["timestamp"], row["open"], row["high"], row["low"], row["close"], row["volume"])
            for row in reversed(rows)
        )


def _sentiment_layer(sentiment: SentimentView | None) -> StrategyLayer:
    """Sentiment is context only; it never becomes a PASS that unlocks BUY."""
    if sentiment is None or not sentiment.available:
        return StrategyLayer("Sentiment", "MISSING", "chưa có tin trong cửa sổ theo dõi")
    if sentiment.label == "Negative":
        return StrategyLayer("Sentiment", "RISK", f"score {sentiment.score:+.2f}")
    if sentiment.label == "Positive":
        return StrategyLayer("Sentiment", "SUPPORTIVE", f"score {sentiment.score:+.2f} (context)")
    return StrategyLayer("Sentiment", "NEUTRAL", f"score {sentiment.score:+.2f}")


def _insufficient_result(name: str, bars: Sequence[OHLCVBar], reason: str):
    from strategy.technical_strategies import StrategyName, StrategyResult

    latest = bars[-1]
    return StrategyResult(
        StrategyName(name), latest.symbol, latest.timestamp,
        StrategyAction.BLOCKED, None, (), (), (reason,),
    )


def build_runtime_service_from_env() -> RuntimeBotDataService:
    load_dotenv()
    required = {name: os.getenv(name, "").strip() for name in (
        "VIETCAP_AUTHORIZATION", "VIETCAP_DEVICE_ID", "VIETCAP_COOKIE"
    )}
    if not all(required.values()):
        raise RuntimeError("Vietcap historical credentials are missing from .env")
    client = VietcapRestClient(
        authorization=required["VIETCAP_AUTHORIZATION"],
        device_id=required["VIETCAP_DEVICE_ID"], cookie=required["VIETCAP_COOKIE"],
    )
    connection = connect_database(os.getenv("DATABASE_URL", "sqlite:///stock_bot.db"))
    instruments = _instruments(os.getenv("BOT_WATCH_SYMBOLS", "FPT:HOSE,ACB:HOSE"))
    news_service = None
    try:
        from intelligence.news.repository import SQLiteNewsRepository
        from intelligence.news.service import SentimentQueryService
        news_service = SentimentQueryService(
            SQLiteNewsRepository(os.getenv("NEWS_DATABASE_PATH", "news_sentiment.db")),
            float(os.getenv("SENTIMENT_HALF_LIFE_HOURS", "24")),
        )
    except (OSError, ValueError, sqlite3.Error):
        news_service = None
    return RuntimeBotDataService(
        client, connection, instruments, news_service=news_service,
        fundamentals_csv_path=os.getenv("FUNDAMENTALS_CSV_PATH", "").strip() or None,
    )


def _instruments(raw: str) -> tuple[ScannerInstrument, ...]:
    result = []
    for item in raw.split(","):
        parts = item.strip().upper().split(":")
        if len(parts) != 2:
            raise ValueError("BOT_WATCH_SYMBOLS must use SYMBOL:EXCHANGE entries")
        result.append(ScannerInstrument(parts[0], parts[1], "STOCK"))
    return tuple(result)


def _date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE).strftime("%d/%m/%Y")


def _number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


__all__ = [
    "RuntimeBotDataService",
    "build_runtime_service_from_env",
    "ema20",
    "ema50",
    "rsi14",
]
