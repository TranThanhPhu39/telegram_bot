"""Build the production coverage worker from environment configuration.

Kept apart from ``coverage_worker`` so the orchestration module has no direct
knowledge of environment variables, Vietcap credentials or vnstock/yfinance.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
import os
import sqlite3

from dotenv import load_dotenv

from data.database import connect_database
from data.migrations import bootstrap_schema
from fundamentals.providers.provider_chain import ProviderChain, build_default_chain
from runtime.coverage_config import CoverageConfig
from runtime.coverage_worker import MarketCoverageEngine, MarketCoverageWorker
from runtime.news_refresh import build_news_runner_from_env
from runtime.sector_history_sync import (
    SectorHistorySynchronizer,
    SectorHistorySyncWorker,
)

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "sqlite:///stock_bot.db"


def _flag(raw: str | None, default: bool) -> bool:
    value = (raw or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def parse_source_preference(raw: str | None) -> tuple[str, ...] | None:
    """``"VCI, tcbs"`` -> ``("VCI", "TCBS")``; empty -> ``None`` (use defaults)."""
    parts = tuple(part.strip().upper() for part in (raw or "").split(",") if part.strip())
    return parts or None


def build_chain_from_env(environ: Mapping[str, str] | None = None) -> ProviderChain:
    """VNStock first, Yahoo strictly as fallback (Phase 24 chain, env-configured)."""
    source = os.environ if environ is None else environ
    return build_default_chain(
        source_preference=parse_source_preference(source.get("VNSTOCK_SOURCE_PREFERENCE")),
        yfinance_enabled=_flag(source.get("YFINANCE_ENABLED"), True),
        tcbs_enabled=_flag(source.get("TCBS_ENABLED"), True),
    )


def connection_factory_from_env(
    environ: Mapping[str, str] | None = None,
) -> Callable[[], sqlite3.Connection]:
    source = os.environ if environ is None else environ
    url = source.get("DATABASE_URL", DEFAULT_DATABASE_URL) or DEFAULT_DATABASE_URL
    return lambda: connect_database(url)


def build_history_client_from_env(
    connection: sqlite3.Connection, environ: Mapping[str, str] | None = None,
) -> SectorHistorySynchronizer | None:
    """Vietcap daily-history client, or ``None`` when credentials are absent."""
    from data.vietcap.rest import VietcapRestClient

    source = os.environ if environ is None else environ
    required = {name: (source.get(name) or "").strip() for name in (
        "VIETCAP_AUTHORIZATION", "VIETCAP_DEVICE_ID", "VIETCAP_COOKIE"
    )}
    if not all(required.values()):
        logger.warning("Vietcap credentials missing; MARKET_HISTORY coverage disabled")
        return None
    client = VietcapRestClient(
        authorization=required["VIETCAP_AUTHORIZATION"],
        device_id=required["VIETCAP_DEVICE_ID"],
        cookie=required["VIETCAP_COOKIE"],
    )
    return SectorHistorySynchronizer(
        client, connection,
        retry_attempts=int(source.get("SECTOR_HISTORY_RETRY_ATTEMPTS", "3")),
        retry_base_seconds=float(source.get("SECTOR_HISTORY_RETRY_BASE_SECONDS", "2")),
    )


def build_engine_from_env(
    config: CoverageConfig, *,
    connection_factory: Callable[[], sqlite3.Connection],
    sector_requester: Callable[[str], bool] | None = None,
    news_ticker_requester: Callable[[str], bool] | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], object] | None = None,
    environ: Mapping[str, str] | None = None,
) -> MarketCoverageEngine:
    """Engine bound to a fresh connection — call it on the thread that will use it."""
    connection = connection_factory()
    bootstrap_schema(connection)
    kwargs = {} if sleep is None else {"sleep": sleep}
    news_runner = (
        build_news_runner_from_env(connection_factory, window_days=config.news_window_days)
        if config.news_enabled else None
    )
    needs_history = "MARKET_HISTORY" in config.datasets
    return MarketCoverageEngine(
        connection, build_chain_from_env(environ), config,
        history=build_history_client_from_env(connection, environ) if needs_history else None,
        sector_requester=sector_requester,
        news_ticker_requester=news_ticker_requester,
        news_runner=news_runner,
        should_stop=should_stop,
        **kwargs,
    )


def start_coverage_worker_from_env(
    sector_worker: SectorHistorySyncWorker | None = None,
    *, environ: Mapping[str, str] | None = None,
    news_ticker_requester: Callable[[str], bool] | None = None,
) -> MarketCoverageWorker | None:
    """Start the background coverage worker; returns ``None`` when disabled.

    Never blocks: the worker builds its engine and runs its first cycle on its
    own thread after ``COVERAGE_STARTUP_DELAY``. When a sector worker is given,
    coverage hands incomplete sectors to it and records its results.
    """
    load_dotenv()
    config = CoverageConfig.from_env(environ)
    if not config.enabled:
        logger.info("Market coverage worker disabled (COVERAGE_WORKER_ENABLED=false)")
        return None
    connection_factory = connection_factory_from_env(environ)
    requester = None if sector_worker is None else sector_worker.request

    def engine_factory(should_stop, sleep):
        return build_engine_from_env(
            config, connection_factory=connection_factory,
            sector_requester=requester,
            news_ticker_requester=news_ticker_requester,
            should_stop=should_stop, sleep=sleep,
            environ=environ,
        )

    worker = MarketCoverageWorker(
        engine_factory, config, connection_factory=connection_factory
    )
    if sector_worker is not None:
        sector_worker.add_listener(worker.on_sector_result)
    worker.start()
    logger.info(
        "Market coverage worker started batch=%d interval=%.0fs datasets=%s",
        config.batch_size, config.worker_interval_seconds, ",".join(config.datasets),
    )
    return worker
