"""Config parsing, coverage report, CLI scripts and the Telegram non-blocking boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from fundamentals.coverage_store import record_attempt
from runtime.coverage_config import CoverageConfig, CoverageConfigError
from runtime.coverage_report import (
    build_coverage_report, render_report, render_status_listing, render_symbol_detail,
)
from tests.coverage_fakes import T0, make_connection, seed_symbols

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- config
def test_defaults_are_conservative_and_valid() -> None:
    c = CoverageConfig()
    assert c.batch_size == 20 and c.request_delay_seconds > 0 and c.max_retries == 2
    assert c.financials_interval_seconds == 7 * 86400 and c.institutional_interval_seconds == 86400
    assert c.batch_datasets == ("FINANCIALS", "INSTITUTIONAL", "MARKET_HISTORY")
    assert c.news_window_days == 30
    assert c.news_ticker_refresh_interval_seconds == 15 * 60


def test_from_env_reads_every_documented_variable() -> None:
    env = {"COVERAGE_BATCH_SIZE": "7", "COVERAGE_WORKER_INTERVAL": "60", "COVERAGE_REQUEST_DELAY": "0",
           "COVERAGE_MAX_RETRIES": "1", "COVERAGE_RETRY_BACKOFF": "3", "COVERAGE_ERROR_COOLDOWN": "9", "COVERAGE_MISSING_COOLDOWN": "77",
           "COVERAGE_STARTUP_DELAY": "1", "FUNDAMENTAL_REFRESH_INTERVAL": "100",
           "INSTITUTIONAL_REFRESH_INTERVAL": "50", "MARKET_HISTORY_REFRESH_INTERVAL": "40",
           "NEWS_REFRESH_INTERVAL": "30", "NEWS_INGEST_LIMIT": "5", "NEWS_WINDOW_DAYS": "45",
           "NEWS_TICKER_REQUESTS_PER_CYCLE": "12",
           "NEWS_TICKER_REFRESH_INTERVAL_SECONDS": "3600",
           "COVERAGE_SECTOR_REQUESTS_PER_CYCLE": "4",
           "COVERAGE_WORKER_ENABLED": "false", "COVERAGE_DATASETS": "news, financials"}
    c = CoverageConfig.from_env(env)
    assert (c.batch_size, c.worker_interval_seconds, c.max_retries, c.retry_backoff_seconds) == (7, 60, 1, 3)
    assert c.missing_cooldown_seconds == 77
    assert c.enabled is False and c.datasets == ("NEWS", "FINANCIALS")
    assert c.interval_for("FINANCIALS") == 100
    assert c.interval_for("NEWS") == 3600
    assert c.news_window_days == 45
    assert c.news_ticker_requests_per_cycle == 12
    assert c.news_ticker_refresh_interval_seconds == 3600
    assert c.retry_wait(1) == 3 and c.retry_wait(3) == 12


@pytest.mark.parametrize("env", [
    {"COVERAGE_BATCH_SIZE": "0"}, {"COVERAGE_BATCH_SIZE": "abc"}, {"COVERAGE_MAX_RETRIES": "-1"},
    {"COVERAGE_DATASETS": "BOGUS"}, {"COVERAGE_WORKER_ENABLED": "maybe"},
    {"COVERAGE_WORKER_INTERVAL": "0"}, {"NEWS_INGEST_LIMIT": "500"},
    {"NEWS_TICKER_REQUESTS_PER_CYCLE": "0"},
    {"NEWS_TICKER_REQUESTS_PER_CYCLE": "101"},
    {"NEWS_TICKER_REFRESH_INTERVAL_SECONDS": "0"},
    {"NEWS_WINDOW_DAYS": "0"}, {"NEWS_WINDOW_DAYS": "-5"},
])
def test_invalid_env_is_rejected_clearly(env) -> None:
    with pytest.raises(CoverageConfigError):
        CoverageConfig.from_env(env)


def test_every_env_example_coverage_setting_is_consumed() -> None:
    text = (ROOT / ".env.example").read_text()
    names = [l.split("=")[0] for l in text.splitlines() if "=" in l and not l.startswith("#")]
    source = "".join((ROOT / f).read_text() for f in (
        "runtime/coverage_config.py", "runtime/coverage_factory.py",
        "runtime/news_refresh.py", "scripts/run_telegram_bot.py",
        "scripts/test_phase26_telegram_live.py",
    ) if (ROOT / f).exists())
    for name in names:
        if name.startswith(("COVERAGE_", "NEWS_REFRESH", "NEWS_INGEST", "NEWS_WINDOW", "NEWS_TICKER", "FUNDAMENTAL_REFRESH",
                            "INSTITUTIONAL_REFRESH", "MARKET_HISTORY_REFRESH", "VNSTOCK_SOURCE", "YFINANCE",
                            "TEST_TELEGRAM")):
            assert name in source, f"{name} documented but never read"


def test_production_news_refresh_uses_ticker_page_worker_and_sweeper() -> None:
    source = (ROOT / "scripts/run_telegram_bot.py").read_text(encoding="utf-8")
    assert "start_targeted_news_worker_from_env" in source
    assert "news_ticker_requester=news_refresh_worker.request" in source
    assert "build_targeted_news_refresh_worker_from_env" not in source


def test_production_bot_wires_ticker_page_worker_into_news_coverage() -> None:
    source = (ROOT / "scripts/run_telegram_bot.py").read_text(encoding="utf-8")
    assert "start_targeted_news_worker_from_env" in source
    assert "news_ticker_requester=news_refresh_worker.request" in source
    assert "build_targeted_news_refresh_worker_from_env" not in source


# ---------------------------------------------------------------- report
def test_report_counts_come_from_the_database(tmp_path) -> None:
    conn = make_connection(tmp_path)
    seed_symbols(conn, [(s, "HOSE", "STOCK", 1) for s in ("AAA", "BBB", "CCC", "DDD")]
                 + [("OLD", "HOSE", "STOCK", 0)])
    record_attempt(conn, "AAA", "FINANCIALS", "READY", now=T0)
    record_attempt(conn, "BBB", "FINANCIALS", "PARTIAL", now=T0)
    record_attempt(conn, "CCC", "FINANCIALS", "ERROR", now=T0)
    record_attempt(conn, "OLD", "FINANCIALS", "READY", now=T0)            # outside universe
    cfg = CoverageConfig()
    fresh = build_coverage_report(conn, cfg, now=T0)
    assert fresh.universe_size == 4 and fresh.outside_universe == 1
    assert fresh.counts["FINANCIALS"]["READY"] == 1 and fresh.counts["FINANCIALS"]["NEVER_ATTEMPTED"] == 1
    from datetime import timedelta
    aged = build_coverage_report(conn, cfg, now=T0 + timedelta(days=8))
    assert aged.counts["FINANCIALS"]["STALE"] == 2 and aged.counts["FINANCIALS"]["READY"] == 0
    text = render_report(fresh)
    assert "Universe: 4" in text and "Fundamentals (FINANCIALS)" in text and "NEVER_ATTEMPTED" in text
    assert "AAA" in render_status_listing(fresh, "FINANCIALS", "READY")
    detail = render_symbol_detail(conn, "ccc", cfg, now=T0)
    assert "FINANCIALS" in detail and "ERROR" in detail and "in universe: yes" in detail


def test_report_on_empty_universe(tmp_path) -> None:
    conn = make_connection(tmp_path)
    assert "Universe: 0" in render_report(build_coverage_report(conn, CoverageConfig(), now=T0))


# ------------------------------------------------------------------- CLI
def test_cli_dry_run_and_report_use_env_database(tmp_path, monkeypatch, capsys) -> None:
    db = tmp_path / "cli.sqlite3"
    conn = make_connection(tmp_path, "cli.sqlite3")
    seed_symbols(conn, [("AAA", "HOSE", "STOCK", 1), ("BBB", "HNX", "STOCK", 1)])
    conn.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setattr("scripts.coverage_cli.load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr("scripts.coverage_report.load_dotenv", lambda *a, **k: None)
    from scripts import coverage_report, sync_fundamentals
    assert sync_fundamentals.main(["--dry-run", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "1 symbol(s) would be processed" in out and "AAA: FINANCIALS" in out
    assert coverage_report.main([]) == 0
    assert "Universe: 2" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        sync_fundamentals.main(["--limit", "0"])


def test_coverage_report_on_uninitialised_database(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'empty.sqlite3').as_posix()}")
    monkeypatch.setattr("scripts.coverage_report.load_dotenv", lambda *a, **k: None)
    from scripts import coverage_report
    assert coverage_report.main([]) == 2


# ------------------------------------------------ Telegram non-blocking
FORBIDDEN = ("vnstock", "yfinance", "fundamentals.providers", "runtime.coverage_worker",
             "runtime.coverage_factory", "runtime.news_refresh", "intelligence.news.pipeline",
             "intelligence.news.sentiment", "transformers", "torch")


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_telegram_and_command_path_never_import_acquisition_code() -> None:
    files = list((ROOT / "telegram_bot").glob("*.py")) + [
        ROOT / "runtime/bot_service.py", ROOT / "runtime/analysis.py", ROOT / "runtime/views.py"]
    for path in files:
        for module in _imports(path):
            assert not any(module == f or module.startswith(f + ".") for f in FORBIDDEN), (path.name, module)


def test_refresh_service_is_the_only_caller_of_the_chain() -> None:
    # runtime/acceptance.py is the explicit live-acceptance harness and may probe providers directly.
    hits = []
    for path in (ROOT / "runtime").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name != "acceptance.py" and (
            ".fetch_financials(" in text or ".fetch_institutional_flow(" in text
        ):
            hits.append(path.name)
    assert hits == []                                    # worker goes through refresh_service only
