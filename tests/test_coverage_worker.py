"""MarketCoverageEngine / MarketCoverageWorker behaviour with deterministic fakes."""

from __future__ import annotations

from datetime import date, timedelta
import sqlite3
import threading

import pytest

import runtime.coverage_worker as cw
from asmf_data.models import SectorMembership
from asmf_data.store import upsert_sector_memberships
from fundamentals.coverage_store import load_coverage, mark_in_progress, record_attempt
from runtime.coverage_worker import (
    MarketCoverageEngine, MarketCoverageWorker, record_sector_result,
)
from runtime.sector_history_sync import SectorSyncResult
from tests.coverage_fakes import (
    T0, Clock, FakeHistory, FakeNews, ScriptedProvider, Sleeper, chain_of,
    fast_config, make_connection, seed_symbols,
)

SYMS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]


def build(tmp_path, provider=None, config=None, symbols=SYMS, **kw):
    conn = make_connection(tmp_path)
    seed_symbols(conn, [(s, "HOSE", "STOCK", 1) for s in symbols])
    provider = provider or ScriptedProvider()
    clock, sleeper = kw.pop("clock", Clock()), kw.pop("sleeper", Sleeper())
    engine = MarketCoverageEngine(conn, chain_of(provider), config or fast_config(),
                                  clock=clock, sleep=sleeper, **kw)
    return engine, conn, provider, clock, sleeper


# ------------------------------------------------------------ batching
def test_batch_is_bounded_and_ordered_then_continues(tmp_path) -> None:
    engine, conn, provider, *_ = build(tmp_path, config=fast_config(batch_size=3))
    r1 = engine.run_cycle()
    assert r1.selected == ("AAA", "BBB", "CCC") and r1.due_symbols == 8
    assert len(provider.calls) == 6                      # 3 symbols x 2 datasets
    r2 = engine.run_cycle()
    assert r2.selected == ("DDD", "EEE", "FFF")          # never-attempted first
    assert provider.symbols_called("FINANCIALS") == SYMS[:6]


def test_limit_override_and_validation(tmp_path) -> None:
    engine, *_ = build(tmp_path)
    assert engine.run_cycle(limit=2).selected == ("AAA", "BBB")
    with pytest.raises(ValueError):
        engine.run_cycle(limit=0)


def test_priority_financials_worker_wakes_and_notifies_after_attempt(tmp_path) -> None:
    calls = []
    completed = threading.Event()
    notified = []

    class Engine:
        def __init__(self):
            self.connection = sqlite3.connect(":memory:", check_same_thread=False)

        def run_cycle(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("symbols"):
                completed.set()
                return type("Report", (), {
                    "outcomes": [type("Outcome", (), {
                        "dataset": "FINANCIALS", "result": "SUCCESS",
                    })()]
                })()
            return type("Report", (), {"outcomes": []})()

        def close(self):
            return None

    engine = Engine()
    worker = MarketCoverageWorker(
        lambda _should_stop, _sleep: engine,
        fast_config(worker_interval_seconds=60),
        connection_factory=lambda: sqlite3.connect(":memory:"),
    )
    worker.add_financial_refresh_listener(notified.append)
    worker.start()
    try:
        assert worker.request_financials("fpt") is True
        assert worker.request_financials("FPT") is False
        assert completed.wait(2.0)
    finally:
        worker.stop(timeout=2.0)

    priority_call = next(call for call in calls if call.get("symbols"))
    assert priority_call == {
        "symbols": ("FPT",), "limit": 1, "datasets": ("FINANCIALS",),
    }
    assert notified == [("FPT",)]


def test_least_recently_attempted_goes_first(tmp_path) -> None:
    engine, conn, provider, clock, _ = build(tmp_path, symbols=["AAA", "BBB", "CCC"],
                                             config=fast_config(batch_size=1))
    for s, minutes in (("AAA", 30), ("BBB", 10), ("CCC", 20)):
        for ds in ("FINANCIALS", "INSTITUTIONAL"):
            record_attempt(conn, s, ds, "ERROR", now=T0 - timedelta(days=9) + timedelta(minutes=minutes))
    clock.advance(days=1)
    assert engine.run_cycle().selected == ("BBB",)


# ------------------------------------------------------------ freshness
def test_fresh_data_is_skipped_and_force_bypasses(tmp_path) -> None:
    engine, conn, provider, clock, _ = build(tmp_path, symbols=["AAA"])
    engine.run_cycle()
    assert len(provider.calls) == 2
    clock.advance(hours=1)
    r = engine.run_cycle()
    assert len(provider.calls) == 2 and r.due_symbols == 0
    engine.run_cycle(force=True)
    assert len(provider.calls) == 4


def test_stale_after_interval_is_refreshed(tmp_path) -> None:
    engine, conn, provider, clock, _ = build(tmp_path, symbols=["AAA"])
    engine.run_cycle()
    clock.advance(days=2)                               # institutional (1d) stale, financials (7d) fresh
    engine.run_cycle()
    assert provider.count("FINANCIALS") == 1 and provider.count("INSTITUTIONAL") == 2
    assert load_coverage(conn, "AAA", "INSTITUTIONAL").attempts == 2


def test_statuses_success_partial_missing(tmp_path) -> None:
    prov = ScriptedProvider({"BBB": "partial", "CCC": "missing"})
    engine, conn, *_ = build(tmp_path, prov, symbols=["AAA", "BBB", "CCC"])
    r = engine.run_cycle()
    assert [load_coverage(conn, s, "FINANCIALS").status for s in ("AAA", "BBB", "CCC")] == \
        ["PARTIAL", "PARTIAL", "MISSING"]
    assert r.counts()["FINANCIALS"] == {"SUCCESS": 1, "PARTIAL": 1, "MISSING": 1}


# ----------------------------------------------------------- isolation
def test_one_symbol_exception_does_not_stop_the_next(tmp_path, monkeypatch) -> None:
    engine, conn, provider, *_ = build(tmp_path, symbols=["AAA", "BBB", "CCC"],
                                       config=fast_config(max_retries=0))
    real = cw.refresh_financials

    def flaky(connection, chain, symbol, **kw):
        if symbol == "BBB":
            raise RuntimeError("db exploded Authorization: Bearer abcdefgh12345678")
        return real(connection, chain, symbol, **kw)

    monkeypatch.setattr(cw, "refresh_financials", flaky)
    r = engine.run_cycle()
    assert load_coverage(conn, "AAA", "FINANCIALS").status == "PARTIAL"
    assert load_coverage(conn, "CCC", "FINANCIALS").status == "PARTIAL"
    bad = load_coverage(conn, "BBB", "FINANCIALS")
    assert bad.status == "ERROR" and "abcdefgh12345678" not in bad.error_reason
    assert load_coverage(conn, "BBB", "INSTITUTIONAL").status == "READY"   # other dataset unaffected
    assert any(o.result == "FAILED" for o in r.outcomes)


def test_provider_exception_becomes_error_and_batch_continues(tmp_path) -> None:
    prov = ScriptedProvider({("AAA", "FINANCIALS"): "raise"})
    engine, conn, *_ = build(tmp_path, prov, symbols=["AAA", "BBB"], config=fast_config(max_retries=0))
    engine.run_cycle()
    assert load_coverage(conn, "AAA", "FINANCIALS").status == "ERROR"
    assert load_coverage(conn, "AAA", "INSTITUTIONAL").status == "READY"
    assert load_coverage(conn, "BBB", "FINANCIALS").status == "PARTIAL"


def test_successful_writes_survive_later_failures(tmp_path) -> None:
    prov = ScriptedProvider({"CCC": "raise"})
    engine, conn, *_ = build(tmp_path, prov, symbols=["AAA", "BBB", "CCC"], config=fast_config(max_retries=0))
    engine.run_cycle()
    assert conn.execute("SELECT COUNT(*) FROM automated_financial_statements").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM financial_reports").fetchone()[0] == 2


# --------------------------------------------------------- retry/backoff
def test_retry_budget_and_exponential_backoff(tmp_path) -> None:
    prov = ScriptedProvider({("AAA", "FINANCIALS"): "error"})
    engine, conn, provider, _, sleeper = build(tmp_path, prov, symbols=["AAA"],
                                               config=fast_config(datasets=("FINANCIALS",)))
    r = engine.run_cycle()
    assert provider.count("FINANCIALS") == 3             # 1 + max_retries(2)
    assert sleeper.calls == [2.0, 4.0]                   # base, 2x base
    assert r.outcomes[0].result == "FAILED" and r.outcomes[0].attempts == 3
    row = load_coverage(conn, "AAA", "FINANCIALS")
    assert row.status == "ERROR" and row.attempts == 3


def test_retry_recovers(tmp_path) -> None:
    prov = ScriptedProvider({("AAA", "FINANCIALS"): ["error", "ok"]})
    engine, conn, provider, *_ = build(tmp_path, prov, symbols=["AAA"],
                                       config=fast_config(datasets=("FINANCIALS",)))
    r = engine.run_cycle()
    assert r.outcomes[0].result == "SUCCESS" and r.outcomes[0].attempts == 2
    assert load_coverage(conn, "AAA", "FINANCIALS").status == "PARTIAL"


def test_request_delay_between_provider_calls(tmp_path) -> None:
    engine, _, _, _, sleeper = build(tmp_path, symbols=["AAA", "BBB"])
    engine.run_cycle()
    assert sleeper.calls == [0.5, 0.5, 0.5]              # 4 calls -> 3 gaps


def test_rate_limit_stops_retries_and_opens_circuit(tmp_path) -> None:
    prov = ScriptedProvider({("AAA", "FINANCIALS"): "ratelimit", ("BBB", "FINANCIALS"): "ratelimit"})
    engine, _, provider, _, sleeper = build(tmp_path, prov, symbols=["AAA", "BBB", "CCC"])
    r = engine.run_cycle()
    assert provider.symbols_called("FINANCIALS") == ["AAA"]      # no retry, no further calls
    assert r.tripped_datasets == ["FINANCIALS"]
    assert 2.0 not in sleeper.calls
    assert provider.count("INSTITUTIONAL") == 3                  # other dataset keeps going


def test_circuit_breaker_after_consecutive_failures(tmp_path) -> None:
    prov = ScriptedProvider({("AAA", "FINANCIALS"): "error", ("BBB", "FINANCIALS"): "error",
                             ("CCC", "FINANCIALS"): "error", ("DDD", "FINANCIALS"): "error"})
    engine, _, provider, *_ = build(tmp_path, prov, symbols=["AAA", "BBB", "CCC", "DDD"],
                                    config=fast_config(max_retries=0))
    r = engine.run_cycle()
    assert provider.count("FINANCIALS") == 3 and r.tripped_datasets == ["FINANCIALS"]
    assert provider.count("INSTITUTIONAL") == 4


# ------------------------------------------------- cooldown / permanent
def test_missing_waits_a_full_interval_and_error_waits_cooldown(tmp_path) -> None:
    prov = ScriptedProvider({("AAA", "FINANCIALS"): "missing", ("BBB", "FINANCIALS"): "error"})
    engine, conn, provider, clock, _ = build(tmp_path, prov, symbols=["AAA", "BBB"],
                                             config=fast_config(datasets=("FINANCIALS",), max_retries=0))
    engine.run_cycle()
    assert provider.count("FINANCIALS") == 2
    clock.advance(minutes=30)
    assert engine.run_cycle().due_symbols == 0           # both cooling down
    clock.advance(hours=2)                               # past error cooldown (1h)
    r = engine.run_cycle()
    assert r.selected == ("BBB",)                        # MISSING still waits
    clock.advance(days=8)
    assert engine.run_cycle().selected == ("AAA", "BBB")


def test_missing_cooldown_is_capped_by_interval_and_configurable(tmp_path) -> None:
    prov = ScriptedProvider({"AAA": "missing"})
    cfg = fast_config(datasets=("FINANCIALS",), missing_cooldown_seconds=7200.0)
    engine, conn, provider, clock, _ = build(tmp_path, prov, symbols=["AAA"], config=cfg)
    engine.run_cycle()
    clock.advance(hours=1)
    assert engine.run_cycle().due_symbols == 0            # still cooling down
    clock.advance(hours=2)
    assert engine.run_cycle().selected == ("AAA",)        # far sooner than the 7-day interval
    assert provider.count("FINANCIALS") == 2


def test_error_with_recent_success_is_not_retried(tmp_path) -> None:
    engine, conn, provider, clock, _ = build(tmp_path, symbols=["AAA"], config=fast_config(datasets=("FINANCIALS",)))
    record_attempt(conn, "AAA", "FINANCIALS", "READY", now=T0)
    record_attempt(conn, "AAA", "FINANCIALS", "ERROR", now=T0 + timedelta(minutes=5))
    clock.advance(hours=3)
    assert engine.run_cycle().due_symbols == 0


# ----------------------------------------------------- restart / idempotent
def test_restart_reuses_persisted_state_without_duplicates(tmp_path) -> None:
    engine, conn, provider, clock, _ = build(tmp_path, symbols=["AAA", "BBB"])
    engine.run_cycle()
    calls = len(provider.calls)
    second = MarketCoverageEngine(conn, chain_of(provider), fast_config(), clock=clock, sleep=Sleeper())
    assert second.run_cycle().due_symbols == 0 and len(provider.calls) == calls
    second.run_cycle(force=True)
    second.run_cycle(force=True)
    assert conn.execute("SELECT COUNT(*) FROM symbol_data_coverage").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM automated_financial_statements").fetchone()[0] == 2


def test_abandoned_in_progress_is_reclaimed_but_live_one_is_not(tmp_path) -> None:
    engine, conn, provider, clock, _ = build(tmp_path, symbols=["AAA", "BBB"],
                                             config=fast_config(datasets=("FINANCIALS",)))
    mark_in_progress(conn, "AAA", "FINANCIALS", now=T0 - timedelta(hours=2))   # crashed run
    mark_in_progress(conn, "BBB", "FINANCIALS", now=T0 - timedelta(minutes=1)) # running now
    r = engine.run_cycle()
    assert r.selected == ("AAA",)
    assert load_coverage(conn, "AAA", "FINANCIALS").status == "PARTIAL"
    assert load_coverage(conn, "BBB", "FINANCIALS").status == "IN_PROGRESS"


# ------------------------------------------------------------------ stop
def test_graceful_stop_leaves_unprocessed_symbols_untouched(tmp_path) -> None:
    flag = {"stop": False}
    prov = ScriptedProvider()
    orig = prov.fetch_financials

    def stopping(symbol, **kw):
        if symbol == "BBB":
            flag["stop"] = True
        return orig(symbol, **kw)

    prov.fetch_financials = stopping
    engine, conn, *_ = build(tmp_path, prov, symbols=["AAA", "BBB", "CCC"],
                             config=fast_config(datasets=("FINANCIALS",)),
                             should_stop=lambda: flag["stop"])
    r = engine.run_cycle()
    assert r.stopped_early and load_coverage(conn, "CCC", "FINANCIALS") is None
    assert load_coverage(conn, "BBB", "FINANCIALS").status == "PARTIAL"


def test_worker_thread_runs_and_stops_promptly(tmp_path) -> None:
    conn_factory = lambda: make_connection(tmp_path)
    boot = conn_factory()
    seed_symbols(boot, [("AAA", "HOSE", "STOCK", 1)])
    boot.close()
    ran = threading.Event()
    prov = ScriptedProvider()
    orig = prov.fetch_financials
    prov.fetch_financials = lambda s, **kw: (ran.set(), orig(s, **kw))[1]
    cfg = fast_config(worker_interval_seconds=3600.0)

    def factory(should_stop, sleep):
        return MarketCoverageEngine(conn_factory(), chain_of(prov), cfg, should_stop=should_stop, sleep=sleep)

    worker = MarketCoverageWorker(factory, cfg, connection_factory=conn_factory)
    thread = worker.start()
    assert worker.start() is thread                       # idempotent, one thread
    assert ran.wait(5)
    worker.stop(timeout=5)                                # interval is 1h: must not wait for it
    assert not thread.is_alive() and worker.cycles_completed == 1
    with pytest.raises(RuntimeError):
        worker.start()


def test_worker_survives_a_crashing_cycle(tmp_path) -> None:
    calls = {"n": 0}
    done = threading.Event()

    class Boom:
        connection = make_connection(tmp_path)

        def run_cycle(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("cycle blew up")
            done.set()
            return None

        def close(self):
            pass

    cfg = fast_config(worker_interval_seconds=0.01)
    w = MarketCoverageWorker(lambda s, sl: Boom(), cfg, connection_factory=lambda: None)
    w.start()
    assert done.wait(5)
    w.stop(timeout=5)


# ------------------------------------------------------- market history
def test_market_history_statuses_and_missing_client(tmp_path) -> None:
    hist = FakeHistory({"AAA": 200, "BBB": 30, "EEE": 150}, errored={"DDD"})
    cfg = fast_config(datasets=("MARKET_HISTORY",), max_retries=0)
    engine, conn, *_ = build(tmp_path, symbols=["AAA", "BBB", "CCC", "DDD", "EEE"], config=cfg, history=hist)
    engine.run_cycle()
    got = {s: load_coverage(conn, s, "MARKET_HISTORY") for s in ("AAA", "BBB", "CCC", "DDD", "EEE")}
    assert [got[s].status for s in got] == ["READY", "PARTIAL", "MISSING", "ERROR", "PARTIAL"]
    assert "short history: 30 of 200 daily bars; need 200 for ASMF/CL1" == got["BBB"].error_reason
    assert "short history: 150 of 200 daily bars; need 200 for ASMF/CL1" == got["EEE"].error_reason

    lone = MarketCoverageEngine(conn, chain_of(ScriptedProvider()), cfg, clock=Clock(), sleep=Sleeper())
    r = lone.run_cycle(force=True)
    assert r.outcomes == []                                # skipped, not falsely recorded


# ---------------------------------------------------------------- sector
def add_sector(conn, code, members, cached):
    upsert_sector_memberships(conn, [SectorMembership(m, code, "Sec", date(2020, 1, 1), None, "T") for m in members])
    with conn:
        for m in members[:cached]:
            conn.executemany(
                "INSERT INTO candles(symbol,timeframe,timestamp,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)",
                [(m, "ONE_DAY", 1_700_000_000 + i * 86400, 1, 2, 1, 1.5, 10) for i in range(126)])


def test_sector_ready_without_network_and_incomplete_is_requested(tmp_path) -> None:
    asked = []
    cfg = fast_config(datasets=("SECTOR_HISTORY",), sector_requests_per_cycle=1)
    engine, conn, *_ = build(tmp_path, symbols=["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "XA", "XB", "YA", "YB", "ZZ"],
                             config=cfg, sector_requester=lambda s: asked.append(s) or True)
    add_sector(conn, "S1", ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"], cached=5)   # ready
    add_sector(conn, "S2", ["XA", "XB"], cached=1)                                   # incomplete
    add_sector(conn, "S3", ["YA", "YB"], cached=0)                                   # incomplete, over quota
    r = engine.run_cycle()
    assert load_coverage(conn, "AAA", "SECTOR_HISTORY").status == "READY"
    assert load_coverage(conn, "ZZ", "SECTOR_HISTORY").status == "MISSING"           # no membership
    assert asked == ["XA"] and r.sector_requested == ["S2"] and r.sector_deferred == 2
    assert load_coverage(conn, "XB", "SECTOR_HISTORY").status == "IN_PROGRESS"
    assert load_coverage(conn, "YA", "SECTOR_HISTORY") is None                       # deferred, untouched


def test_sector_request_refused_is_deferred_not_recorded(tmp_path) -> None:
    cfg = fast_config(datasets=("SECTOR_HISTORY",))
    engine, conn, *_ = build(tmp_path, symbols=["XA", "XB"], config=cfg, sector_requester=lambda s: False)
    add_sector(conn, "S2", ["XA", "XB"], cached=0)
    r = engine.run_cycle()
    assert r.sector_deferred == 2 and load_coverage(conn, "XA", "SECTOR_HISTORY") is None


@pytest.mark.parametrize("res,status", [
    (SectorSyncResult("AAA", "S1", 6, 3, 2, ()), "READY"),
    (SectorSyncResult("AAA", "S1", 6, 1, 1, ("CCC",)), "PARTIAL"),
    (SectorSyncResult("AAA", "S1", 6, 0, 0, ("BBB", "CCC")), "ERROR"),
    (SectorSyncResult("AAA", "S1", 6, 0, 0, ()), "MISSING"),
    (SectorSyncResult("AAA", None, 0, 0, 0, ()), "MISSING"),
])
def test_sector_result_maps_to_coverage_for_all_members(tmp_path, res, status) -> None:
    conn = make_connection(tmp_path)
    members = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    seed_symbols(conn, [(m, "HOSE", "STOCK", 1) for m in members])
    upsert_sector_memberships(conn, [SectorMembership(m, "S1", "S", date(2020, 1, 1), None, "T") for m in members])
    n = record_sector_result(conn, res, now=T0)
    assert load_coverage(conn, "AAA", "SECTOR_HISTORY").status == status
    assert n == (1 if res.sector_code is None else 6)


# ------------------------------------------------------------------ news
def test_news_scheduled_projected_and_absence_is_missing(tmp_path) -> None:
    news = FakeNews({"AAA": 4})
    cfg = fast_config(datasets=("NEWS",), news_interval_seconds=1800.0)
    engine, conn, _, clock, _ = build(tmp_path, symbols=["AAA", "BBB"], config=cfg, news_runner=news)
    r = engine.run_cycle()
    assert news.calls == [30] and r.news.startswith("OK")
    assert load_coverage(conn, "AAA", "NEWS").status == "READY"
    b = load_coverage(conn, "BBB", "NEWS")
    assert b.status == "MISSING" and "no relevant news" in b.error_reason   # never Neutral
    clock.advance(minutes=10)
    assert engine.run_cycle().news == "NOT_DUE" and len(news.calls) == 1
    clock.advance(minutes=30)
    engine.run_cycle()
    assert len(news.calls) == 2


def test_news_schedule_survives_restart_via_db(tmp_path) -> None:
    news = FakeNews({"AAA": 1})
    cfg = fast_config(datasets=("NEWS",))
    engine, conn, prov, clock, _ = build(tmp_path, symbols=["AAA"], config=cfg, news_runner=news)
    engine.run_cycle()
    fresh = MarketCoverageEngine(conn, chain_of(prov), cfg, news_runner=news, clock=clock, sleep=Sleeper())
    assert fresh.run_cycle().news == "NOT_DUE"


def test_news_failure_is_isolated_and_marks_existing_rows(tmp_path) -> None:
    news = FakeNews({"AAA": 1})
    cfg = fast_config(datasets=("FINANCIALS", "NEWS"), news_interval_seconds=1800.0)
    engine, conn, prov, clock, _ = build(tmp_path, symbols=["AAA"], config=cfg, news_runner=news)
    engine.run_cycle()
    news.error = TimeoutError("cafef timeout")
    clock.advance(hours=1)
    r = engine.run_cycle()
    assert r.news.startswith("FAILED")
    row = load_coverage(conn, "AAA", "NEWS")
    assert row.status == "ERROR" and row.last_success_at is not None
    assert load_coverage(conn, "AAA", "FINANCIALS").status == "PARTIAL"      # untouched


def test_news_runner_absent_and_close(tmp_path) -> None:
    engine, *_ = build(tmp_path, config=fast_config(datasets=("NEWS",)))
    assert engine.run_cycle().news == "UNAVAILABLE"
    news = FakeNews()
    engine.news_runner = news
    engine.close()
    assert news.closed


def test_news_canonical_eligibility_statuses_ready_partial_stale_missing(tmp_path) -> None:
    # Canonical news eligibility:
    # READY: >= 3 eligible articles (<= 30d)
    # PARTIAL: 1-2 eligible articles (<= 30d)
    # STALE: 0 eligible articles in 30d, but known to have articles in DB
    # MISSING: 0 eligible articles, never has had articles
    news = FakeNews(
        counts={"AAA": 3, "BBB": 2},
        known_tickers={"AAA", "BBB", "CCC"},
    )
    cfg = fast_config(datasets=("NEWS",), news_interval_seconds=1800.0)
    assert cfg.news_window_days == 30
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    engine, conn, _, _, _ = build(tmp_path, symbols=symbols, config=cfg, news_runner=news)
    r = engine.run_cycle()
    assert r.news.startswith("OK")

    aaa = load_coverage(conn, "AAA", "NEWS")
    assert aaa.status == "READY"
    assert "3 article(s) in last 30d" in aaa.error_reason

    bbb = load_coverage(conn, "BBB", "NEWS")
    assert bbb.status == "PARTIAL"
    assert "2 article(s) in last 30d" in bbb.error_reason

    ccc = load_coverage(conn, "CCC", "NEWS")
    assert ccc.status == "STALE"
    assert "newest article is older than 30d" in ccc.error_reason

    ddd = load_coverage(conn, "DDD", "NEWS")
    assert ddd.status == "MISSING"
    assert "no relevant news in last 30d" in ddd.error_reason

