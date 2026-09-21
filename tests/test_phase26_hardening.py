"""Phase 26 hardening: Telegram boundary, missing data, provider failure, DB, secrets."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from telegram.error import TelegramError

from data.vietcap.rest import VietcapRestError
from fundamentals.coverage_store import load_coverage, record_attempt
from runtime.coverage_worker import MarketCoverageEngine
from runtime.redaction import SecretRedactingFilter, redact_secrets, safe_reason
from runtime.views import ChartRequestView
from telegram_bot.app import build_application, split_message
from telegram_bot.commands import TelegramCommandService
from telegram_bot.portfolio_handlers import PRIVATE_CHAT_ONLY
from tests.coverage_fakes import (
    Clock, ScriptedProvider, Sleeper, chain_of, fast_config, make_connection, seed_symbols,
)
from tests.test_chart_command import PNG_MAGIC, ChartData
from tests.test_runtime_bot import FakeClient, payload, service

TOKEN = "123456789:AAH_fakeTokenValueForTestsOnly_0123456789"
CORE_COMMANDS = {"start", "help", "soi", "scan", "market", "why", "technical", "fundamental",
                 "sector", "tin", "sentiment", "chart", "chienluoc", "performance"}
EMPTY = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}


class Data(ChartData):
    """Every text command answers; captures user ids to prove privacy."""

    def __init__(self, big: int = 0, **kw) -> None:
        super().__init__(**kw)
        self.big = big
        self.portfolio = object()         # lets /soi forward user_id in private chats
        self.soi_kwargs: list[dict] = []

    def symbol_overview(self, symbol, strategy="CL1", **kwargs):
        self.soi_kwargs.append(kwargs)
        return f"{symbol} {strategy}"

    def market_overview(self):
        return ("x" * 900 + "\n\n") * self.big if self.big else "MARKET"

    def technical_overview(self, s): return f"TECH {s}"
    def fundamental_overview(self, s): return f"FUND {s}"
    def sector_overview(self, s): return f"SECTOR {s}"


def handlers(app):
    return {c: h for h in app.handlers[0] for c in getattr(h, "commands", ())}


class Msg:
    def __init__(self, photo_error=None):
        self.texts, self.photos, self.photo_error = [], [], photo_error

    async def reply_text(self, text, reply_markup=None):
        self.texts.append(text)

    async def reply_photo(self, photo, caption=None):
        if self.photo_error:
            raise self.photo_error
        self.photos.append(photo.getvalue())


def run(app, name, args, *, chat="private", user=7, msg=None):
    msg = msg or Msg()
    update = SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=user),
                             effective_chat=SimpleNamespace(id=99, type=chat))
    asyncio.run(handlers(app)[name].callback(update, SimpleNamespace(args=args)))
    return msg


def app_for(data):
    return build_application("123456:TEST_TOKEN", TelegramCommandService(data))


# ------------------------------------------------------------- Telegram
def test_full_command_surface_is_registered() -> None:
    names = set(handlers(app_for(Data())))
    assert CORE_COMMANDS <= names
    assert {"portfolio", "watchlist", "risk"} & names          # Phase 23 surface still present


@pytest.mark.parametrize("args", [[], ["!!!"], ["FPT", "extra", "args", "here"], ["a" * 500], ["  "]])
def test_bad_arguments_get_usage_never_a_crash(args) -> None:
    app = app_for(Data())
    for name in ("soi", "why", "technical", "fundamental", "sector", "tin", "sentiment", "chart"):
        msg = run(app, name, args)
        assert msg.texts or msg.photos, name                    # always answers something
        assert all("Traceback" not in t for t in msg.texts)


def test_lowercase_and_whitespace_symbols_are_normalised() -> None:
    data = Data()
    app = app_for(data)
    assert run(app, "technical", ["  fpt "]).texts == ["TECH FPT"]
    run(app, "chart", [" vhm"])
    assert data.requested == ["VHM"]


def test_long_response_is_chunked_within_telegram_limit() -> None:
    msg = run(app_for(Data(big=30)), "market", [])
    assert len(msg.texts) > 1 and all(len(t) <= 4096 for t in msg.texts)
    chunks = split_message("y" * 10_000)
    assert all(len(c) <= 4096 for c in chunks) and "".join(chunks) == "y" * 10_000


def test_chart_send_failure_falls_back_to_text_without_leaking_token(caplog) -> None:
    err = TelegramError(f"Bad gateway https://api.telegram.org/bot{TOKEN}/sendPhoto")
    caplog.set_level(logging.DEBUG)
    msg = run(app_for(Data()), "chart", ["FPT"], msg=Msg(photo_error=err))
    assert msg.photos == [] and len(msg.texts) == 1 and "Không thể gửi biểu đồ" in msg.texts[0]
    assert TOKEN not in caplog.text and TOKEN.split(":")[1] not in caplog.text


def test_chart_provider_exception_becomes_generic_reply() -> None:
    class Boom(Data):
        def candlestick_chart(self, symbol):
            raise RuntimeError("upstream exploded")

    msg = run(app_for(Boom()), "chart", ["FPT"])
    assert msg.texts == ["Đã xảy ra lỗi tạm thời, vui lòng thử lại sau."]


def test_global_error_handler_replies_and_redacts(caplog) -> None:
    app = app_for(Data())
    (callback,) = app.error_handlers.keys()
    msg = Msg()
    ctx = SimpleNamespace(error=RuntimeError(f"failed calling /bot{TOKEN}/getUpdates"))
    with caplog.at_level(logging.ERROR):
        asyncio.run(callback(SimpleNamespace(effective_message=msg), ctx))
    assert msg.texts == ["Đã xảy ra lỗi tạm thời, vui lòng thử lại sau."]
    assert TOKEN not in caplog.text
    asyncio.run(callback(object(), ctx))                          # non-Update errors are fine too


def test_group_chats_never_expose_portfolio_or_user_context() -> None:
    data = Data()
    app = app_for(data)
    for name in ("portfolio", "watchlist", "risk"):
        assert name in handlers(app)
        msg = run(app, name, [], chat="group")
        assert msg.texts == [PRIVATE_CHAT_ONLY]
    run(app, "soi", ["FPT"], chat="supergroup")
    assert data.soi_kwargs == [{}]                                # no user_id => no holdings/P&L
    run(app, "soi", ["FPT"], chat="private", user=5)
    assert data.soi_kwargs[-1] == {"user_id": 5}                  # private chat may see own context


def test_callbacks_reject_garbage_without_crashing() -> None:
    app = app_for(Data())
    cb = next(h for h in app.handlers[0] if h.__class__.__name__ == "CallbackQueryHandler")
    texts: list[str] = []

    async def reply_text(text, reply_markup=None):
        texts.append(text)

    async def answer():
        return None

    for data in ("garbage", "soi:", "soi:chart:", "x:y:z:w", "soi:bogus:FPT", ""):
        query = SimpleNamespace(data=data, answer=answer, message=SimpleNamespace(reply_text=reply_text, reply_photo=None))
        update = SimpleNamespace(callback_query=query, effective_message=query.message,
                                 effective_user=SimpleNamespace(id=1), effective_chat=SimpleNamespace(id=1, type="private"))
        asyncio.run(cb.callback(update, SimpleNamespace()))
    assert texts and all("Traceback" not in t for t in texts)


def test_text_callback_edits_existing_message() -> None:
    app = app_for(Data())
    cb = next(h for h in app.handlers[0] if h.__class__.__name__ == "CallbackQueryHandler")
    edited: list[str] = []
    replied: list[str] = []

    async def edit_message_text(text, reply_markup=None):
        edited.append(text)

    async def reply_text(text, reply_markup=None):
        replied.append(text)

    async def answer():
        return None

    query = SimpleNamespace(
        data="soi:tech:FPT", answer=answer, edit_message_text=edit_message_text,
        message=SimpleNamespace(reply_text=reply_text, reply_photo=None),
    )
    update = SimpleNamespace(
        callback_query=query, effective_message=query.message,
        effective_user=SimpleNamespace(id=1), effective_chat=SimpleNamespace(id=1, type="private"),
    )
    asyncio.run(cb.callback(update, SimpleNamespace()))
    assert len(edited) == 1
    assert "TECH FPT" in edited[0]
    assert len(replied) == 0  # No spam replies!



# ---------------------------------------------------- missing-data semantics
def test_missing_or_unreachable_history_is_unavailable_not_a_crash() -> None:
    for client in (FakeClient(EMPTY), _failing_client()):
        runtime = service(client)
        for text in (runtime.symbol_overview("FPT"), runtime.technical_overview("FPT"),
                     runtime.fundamental_overview("FPT"), runtime.signal_explanation("FPT"),
                     runtime.market_overview()):
            assert "Chưa có dữ liệu" in text
        view = runtime.candlestick_chart("FPT")
        assert view.png_bytes is None and view.error and "Chưa có dữ liệu" in view.error


def _failing_client(message="timeout"):
    class Failing(FakeClient):
        def get_gap_chart(self, *a, **k):
            raise VietcapRestError(message)
    return Failing(payload())


def test_short_history_keeps_warmup_indicators_unavailable_never_zero() -> None:
    text = service(FakeClient(payload(30))).technical_overview("FPT")
    assert "EMA50: N/A" in text and "MA200: N/A" in text
    assert "MA200: 0" not in text and "EMA50: 0" not in text
    assert "CHƯA ĐỦ DỮ LIỆU" in text


def test_missing_fundamentals_and_asmf_fail_closed() -> None:
    runtime = service(FakeClient(payload()))
    assert runtime.fundamental_overview("FPT") == "🧾 FPT — CƠ BẢN\nFundamental data missing."
    asmf = runtime.symbol_overview("FPT", "ASMF")
    assert "CHƯA ĐỦ ĐIỀU KIỆN" in asmf and "MUA" not in asmf.split("ASMF")[1][:80]
    assert "Fundamental" in asmf or "cơ bản" in asmf.lower() or "Thiếu dữ liệu" in asmf


def test_no_news_is_insufficient_never_neutral(tmp_path) -> None:
    from intelligence.news.repository import SQLiteNewsRepository
    from intelligence.news.service import SentimentQueryService

    repo = SQLiteNewsRepository(str(tmp_path / "news.db"))
    runtime = service(FakeClient(payload()))
    runtime.news_service = SentimentQueryService(repo, 24.0)
    text = runtime.sentiment_overview("FPT")
    assert "unavailable" in text.lower() or "no relevant" in text.lower() or "không" in text.lower()
    assert "NEUTRAL" not in text


def test_news_service_failure_does_not_break_other_commands() -> None:
    class Broken:
        def ticker_sentiment(self, *a, **k):
            raise sqlite3.OperationalError("database is locked")

        def latest_for_ticker(self, *a, **k):
            raise sqlite3.OperationalError("database is locked")

    runtime = service(FakeClient(payload()))
    runtime.news_service = Broken()
    assert "phiên" in runtime.symbol_overview("FPT")
    assert isinstance(runtime.sentiment_overview("FPT"), str)


# ------------------------------------------------------ provider failures
def test_vietcap_timeout_serves_sqlite_and_never_shows_credentials() -> None:
    client = FakeClient(payload())
    runtime = service(client)
    runtime.symbol_overview("FPT")
    bad = _failing_client("timeout Authorization: Bearer abcdefgh12345678 Cookie: sid=zzzzzzzz1")
    runtime.client = bad
    out = runtime.symbol_overview("FPT")
    assert "SQLite cache" in out and "abcdefgh" not in out and "sid=" not in out


def test_news_runner_builds_the_model_once_and_isolates_cafef_timeout(monkeypatch) -> None:
    import intelligence.news.pipeline as pipeline
    from runtime.news_refresh import NewsRefreshRunner

    built = {"model": 0}
    state = {"fail": False}

    class Service:
        def __init__(self, provider, linker, model, repo):
            pass

        def run_once(self, limit):
            if state["fail"]:
                raise TimeoutError("cafef timeout")
            return 2, 1

    monkeypatch.setattr(pipeline, "NewsIngestionService", Service)
    monkeypatch.setattr(pipeline, "build_ticker_linker", lambda conn, cat: object())
    repo = SimpleNamespace(ticker_article_counts=lambda since: {"FPT": 2}, connection=None)

    def model():
        built["model"] += 1
        return object()

    import sqlite3 as s3
    runner = NewsRefreshRunner(connection_factory=lambda: s3.connect(":memory:"), repository_factory=lambda: repo,
                               provider_factory=object, catalog_factory=object, sentiment_factory=model)
    assert runner.run(10).ticker_counts == {"FPT": 2}
    assert runner.run(10).inserted == 2
    assert built["model"] == 1                                    # one PhoBERT/transformer instance
    state["fail"] = True
    with pytest.raises(TimeoutError):
        runner.run(10)                                            # engine records ERROR; bot unaffected


def test_yahoo_and_vnstock_errors_are_isolated_by_the_worker(tmp_path) -> None:
    prov = ScriptedProvider({"AAA": "raise", "BBB": "error"})
    conn = make_connection(tmp_path)
    seed_symbols(conn, [(s, "HOSE", "STOCK", 1) for s in ("AAA", "BBB", "CCC")])
    engine = MarketCoverageEngine(conn, chain_of(prov), fast_config(max_retries=0), clock=Clock(), sleep=Sleeper())
    engine.run_cycle()
    assert [load_coverage(conn, s, "FINANCIALS").status for s in ("AAA", "BBB", "CCC")] == ["ERROR", "ERROR", "READY"]


# ----------------------------------------------------------- database
def test_concurrent_writers_do_not_corrupt_or_duplicate(tmp_path) -> None:
    boot = make_connection(tmp_path)
    seed_symbols(boot, [(f"S{i:02d}", "HOSE", "STOCK", 1) for i in range(20)])
    boot.close()
    errors: list[Exception] = []

    def worker(offset: int) -> None:
        conn = make_connection(tmp_path)
        try:
            for round_ in range(15):
                for i in range(20):
                    record_attempt(conn, f"S{i:02d}", "NEWS", "READY" if (i + offset) % 2 else "MISSING")
        except Exception as error:  # pragma: no cover
            errors.append(error)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(3)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    check = make_connection(tmp_path)
    assert errors == []
    assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert check.execute("SELECT COUNT(*) FROM symbol_data_coverage").fetchone()[0] == 20
    assert check.execute("SELECT MIN(attempts) FROM symbol_data_coverage").fetchone()[0] == 45   # 3 x 15, none lost


def test_locked_database_is_surfaced_and_the_cycle_survives(tmp_path) -> None:
    conn = make_connection(tmp_path)
    seed_symbols(conn, [("AAA", "HOSE", "STOCK", 1), ("BBB", "HOSE", "STOCK", 1)])
    conn.execute("PRAGMA busy_timeout=50")
    holder = make_connection(tmp_path)
    holder.execute("BEGIN IMMEDIATE")                             # another writer holds the lock
    engine = MarketCoverageEngine(conn, chain_of(ScriptedProvider()), fast_config(max_retries=0),
                                  clock=Clock(), sleep=Sleeper())
    report = engine.run_cycle()                                   # must not raise
    assert report.outcomes and all(o.result == "FAILED" for o in report.outcomes)
    assert any("locked" in (o.detail or "") for o in report.outcomes)
    holder.rollback()
    assert engine.run_cycle(force=True).counts()["FINANCIALS"] == {"SUCCESS": 2}    # recovers after unlock


# ------------------------------------------------------------- secrets
def test_redaction_masks_tokens_headers_and_env_values() -> None:
    env = {"TELEGRAM_BOT_TOKEN": TOKEN, "VIETCAP_COOKIE": "sessionid=abcdefgh-cookie-value"}
    text = (f"GET https://api.telegram.org/bot{TOKEN}/getMe failed; Authorization: Bearer abcdefgh12345678 "
            f"Cookie: sessionid=abcdefgh-cookie-value; other {TOKEN}")
    out = redact_secrets(text, environ=env)
    for secret in (TOKEN, TOKEN.split(":")[1], "abcdefgh12345678", "abcdefgh-cookie-value"):
        assert secret not in out
    assert "getMe failed" in out                                  # ordinary text is preserved
    assert redact_secrets("visit /bottom/line and bot names") == "visit /bottom/line and bot names"
    assert len(safe_reason("x" * 900)) <= 300


def test_logging_filter_redacts_message_args_and_tracebacks(caplog) -> None:
    logger = logging.getLogger("phase26.secret")
    handler = logging.StreamHandler()
    stream = []
    handler.emit = lambda record: stream.append(handler.format(record))
    handler.addFilter(SecretRedactingFilter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        try:
            raise RuntimeError(f"boom /bot{TOKEN}/x")
        except RuntimeError:
            logger.info("token %s", TOKEN)
            logger.exception("failed")
    finally:
        logger.removeHandler(handler)
    joined = "\n".join(stream)
    assert TOKEN not in joined and TOKEN.split(":")[1] not in joined


def test_no_source_file_logs_credentials_directly() -> None:
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1]
    pattern = re.compile(r"(logg\w*\.\w+|print)\([^\n]*(getenv|environ\[|\.cookie\b|\.authorization\b|\bcookie\b\s*[,)]|\btoken\b\s*[,)]|\bauthorization\b\s*[,)])", re.I)
    offenders = []
    for path in list((root / "runtime").glob("*.py")) + list((root / "telegram_bot").glob("*.py")) \
            + list((root / "data").rglob("*.py")) + list((root / "scripts").glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{number}")
    assert offenders == []
