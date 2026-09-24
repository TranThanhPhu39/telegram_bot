"""Configuration for the Phase 25 market coverage worker.

Every field here is read by the worker; nothing is declared speculatively.
Defaults are conservative on purpose: public data sources (VNStock, Yahoo,
Vietcap, CafeF) are unofficial or rate-limited, so the worker prefers a slow,
steady trickle of small batches over throughput.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from fundamentals.coverage_store import COVERAGE_DATASETS
from fundamentals.refresh_service import (
    DEFAULT_FINANCIALS_REFRESH_INTERVAL_SECONDS,
    DEFAULT_INSTITUTIONAL_REFRESH_INTERVAL_SECONDS,
)

#: Datasets refreshed symbol-by-symbol inside a bounded batch. SECTOR_HISTORY
#: is handled per *sector* through the existing sector worker. NEWS combines
#: bounded per-ticker page checks with a supplementary global RSS ingest.
BATCH_DATASETS = ("FINANCIALS", "INSTITUTIONAL", "MARKET_HISTORY")

DEFAULT_DATASETS = COVERAGE_DATASETS

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class CoverageConfigError(ValueError):
    """Raised when a coverage environment variable is malformed."""


@dataclass(frozen=True, slots=True)
class CoverageConfig:
    enabled: bool = True
    #: Symbols processed per worker cycle (each may run several datasets). The
    #: 20 symbols / 600 s default sustains ~2,900 symbol-passes per day, enough
    #: to keep a ~1,500-symbol universe's daily datasets fresh without bursts.
    batch_size: int = 20
    #: Sleep between cycles.
    worker_interval_seconds: float = 600.0
    #: Pause between two provider calls inside a cycle.
    request_delay_seconds: float = 1.5
    #: Extra attempts (after the first) for one dataset that ends in ERROR.
    max_retries: int = 2
    #: First in-cycle retry wait; doubles on every further retry.
    retry_backoff_seconds: float = 5.0
    #: Minimum wait before an ERROR dataset is attempted again in a later cycle.
    error_cooldown_seconds: float = 3600.0
    #: Minimum wait before a MISSING dataset is attempted again (capped by the
    #: dataset's own refresh interval). Adapters convert network refusals into
    #: MISSING because the upstream libraries swallow them, so a long wait here
    #: would turn a short outage into days of no data.
    missing_cooldown_seconds: float = 3 * 86400.0
    #: Delay before the first cycle so bot startup never competes with it.
    startup_delay_seconds: float = 10.0
    financials_interval_seconds: float = DEFAULT_FINANCIALS_REFRESH_INTERVAL_SECONDS
    institutional_interval_seconds: float = DEFAULT_INSTITUTIONAL_REFRESH_INTERVAL_SECONDS
    market_history_interval_seconds: float = 24 * 3600.0
    sector_history_interval_seconds: float = 6 * 3600.0
    #: Sector sync requests handed to the existing sector worker per cycle.
    sector_requests_per_cycle: int = 2
    news_interval_seconds: float = 1800.0
    news_ingest_limit: int = 30
    #: A symbol counts as having news coverage if linked to an article this recent.
    news_window_days: int = 30
    #: Per-ticker CafeF page polling is rate-bounded and independent of the RSS sweep.
    news_ticker_requests_per_cycle: int = 100
    news_ticker_refresh_interval_seconds: float = 15 * 60.0
    datasets: tuple[str, ...] = DEFAULT_DATASETS

    def __post_init__(self) -> None:
        if not 1 <= self.batch_size <= 200:
            raise CoverageConfigError("COVERAGE_BATCH_SIZE must be between 1 and 200")
        if self.max_retries < 0 or self.max_retries > 10:
            raise CoverageConfigError("COVERAGE_MAX_RETRIES must be between 0 and 10")
        if not 1 <= self.sector_requests_per_cycle <= 20:
            raise CoverageConfigError(
                "COVERAGE_SECTOR_REQUESTS_PER_CYCLE must be between 1 and 20"
            )
        if not 1 <= self.news_ingest_limit <= 100:
            raise CoverageConfigError("NEWS_INGEST_LIMIT must be between 1 and 100")
        if not 1 <= self.news_ticker_requests_per_cycle <= 100:
            raise CoverageConfigError(
                "NEWS_TICKER_REQUESTS_PER_CYCLE must be between 1 and 100"
            )
        if self.news_window_days < 1:
            raise CoverageConfigError("news_window_days must be positive")
        for name in (
            "worker_interval_seconds", "financials_interval_seconds",
            "institutional_interval_seconds", "market_history_interval_seconds",
            "sector_history_interval_seconds", "news_interval_seconds",
            "news_ticker_refresh_interval_seconds",
        ):
            if getattr(self, name) <= 0:
                raise CoverageConfigError(f"{name} must be positive")
        for name in (
            "request_delay_seconds", "retry_backoff_seconds",
            "error_cooldown_seconds", "missing_cooldown_seconds", "startup_delay_seconds",
        ):
            if getattr(self, name) < 0:
                raise CoverageConfigError(f"{name} cannot be negative")
        unknown = [name for name in self.datasets if name not in COVERAGE_DATASETS]
        if unknown or not self.datasets:
            raise CoverageConfigError(
                "COVERAGE_DATASETS must be a non-empty subset of "
                + ",".join(COVERAGE_DATASETS)
            )

    def interval_for(self, dataset: str) -> float:
        """Freshness window (seconds) after which a READY dataset is stale."""
        return {
            "FINANCIALS": self.financials_interval_seconds,
            "INSTITUTIONAL": self.institutional_interval_seconds,
            "MARKET_HISTORY": self.market_history_interval_seconds,
            "SECTOR_HISTORY": self.sector_history_interval_seconds,
            "NEWS": self.news_ticker_refresh_interval_seconds,
        }[dataset]

    def retry_wait(self, retry_number: int) -> float:
        """Exponential in-cycle backoff: base, 2×base, 4×base, … (1-based)."""
        return self.retry_backoff_seconds * (2 ** max(0, retry_number - 1))

    @property
    def batch_datasets(self) -> tuple[str, ...]:
        return tuple(name for name in BATCH_DATASETS if name in self.datasets)

    @property
    def sector_enabled(self) -> bool:
        return "SECTOR_HISTORY" in self.datasets

    @property
    def news_enabled(self) -> bool:
        return "NEWS" in self.datasets

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "CoverageConfig":
        source = os.environ if environ is None else environ
        defaults = cls()

        def number(name: str, default: float, *, integer: bool = False) -> float:
            raw = (source.get(name) or "").strip()
            if not raw:
                return default
            try:
                return int(raw) if integer else float(raw)
            except ValueError as error:
                raise CoverageConfigError(f"{name} must be a number") from error

        def flag(name: str, default: bool) -> bool:
            raw = (source.get(name) or "").strip().lower()
            if not raw:
                return default
            if raw in _TRUE:
                return True
            if raw in _FALSE:
                return False
            raise CoverageConfigError(f"{name} must be true or false")

        raw_datasets = (source.get("COVERAGE_DATASETS") or "").strip()
        datasets = (
            tuple(dict.fromkeys(
                part.strip().upper() for part in raw_datasets.split(",") if part.strip()
            ))
            if raw_datasets else defaults.datasets
        )
        return cls(
            enabled=flag("COVERAGE_WORKER_ENABLED", defaults.enabled),
            batch_size=int(number("COVERAGE_BATCH_SIZE", defaults.batch_size, integer=True)),
            worker_interval_seconds=number(
                "COVERAGE_WORKER_INTERVAL", defaults.worker_interval_seconds
            ),
            request_delay_seconds=number(
                "COVERAGE_REQUEST_DELAY", defaults.request_delay_seconds
            ),
            max_retries=int(number("COVERAGE_MAX_RETRIES", defaults.max_retries, integer=True)),
            retry_backoff_seconds=number(
                "COVERAGE_RETRY_BACKOFF", defaults.retry_backoff_seconds
            ),
            error_cooldown_seconds=number(
                "COVERAGE_ERROR_COOLDOWN", defaults.error_cooldown_seconds
            ),
            missing_cooldown_seconds=number(
                "COVERAGE_MISSING_COOLDOWN", defaults.missing_cooldown_seconds
            ),
            startup_delay_seconds=number(
                "COVERAGE_STARTUP_DELAY", defaults.startup_delay_seconds
            ),
            financials_interval_seconds=number(
                "FUNDAMENTAL_REFRESH_INTERVAL", defaults.financials_interval_seconds
            ),
            institutional_interval_seconds=number(
                "INSTITUTIONAL_REFRESH_INTERVAL", defaults.institutional_interval_seconds
            ),
            market_history_interval_seconds=number(
                "MARKET_HISTORY_REFRESH_INTERVAL", defaults.market_history_interval_seconds
            ),
            # Shared with the existing sector worker so both agree on "fresh".
            sector_history_interval_seconds=number(
                "SECTOR_HISTORY_SYNC_INTERVAL_SECONDS", defaults.sector_history_interval_seconds
            ),
            sector_requests_per_cycle=int(number(
                "COVERAGE_SECTOR_REQUESTS_PER_CYCLE", defaults.sector_requests_per_cycle,
                integer=True,
            )),
            news_interval_seconds=number("NEWS_REFRESH_INTERVAL", defaults.news_interval_seconds),
            news_ingest_limit=int(number(
                "NEWS_INGEST_LIMIT", defaults.news_ingest_limit, integer=True
            )),
            news_window_days=int(number(
                "NEWS_WINDOW_DAYS", defaults.news_window_days, integer=True
            )),
            news_ticker_requests_per_cycle=int(number(
                "NEWS_TICKER_REQUESTS_PER_CYCLE",
                defaults.news_ticker_requests_per_cycle,
                integer=True,
            )),
            news_ticker_refresh_interval_seconds=number(
                "NEWS_TICKER_REFRESH_INTERVAL_SECONDS",
                defaults.news_ticker_refresh_interval_seconds,
            ),
            datasets=datasets,
        )
