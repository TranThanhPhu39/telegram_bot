"""Bounded live-acceptance logic (Phase 26) — importable and testable offline.

The scripts in ``scripts/test_phase24_live.py`` and
``scripts/test_phase26_telegram_live.py`` are thin wrappers around this module.
Everything network-facing is injected, so the same code is exercised offline
with fakes and online with the real providers. Nothing here writes to the
production database: callers pass a temporary connection.

Verdict vocabulary (never a fabricated PASS):

* ``PASS``        — the real dependency answered and every safety check held.
* ``FAIL``        — it answered but a safety/contract check was violated.
* ``NOT TESTED``  — an external blocker (module missing, network/credentials).
* ``INCONCLUSIVE``— reachable-looking but no data for known-good symbols.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import sqlite3
import time

from fundamentals.coverage_store import load_automated_statements
from fundamentals.providers.base import FundamentalProvider, ProviderResult, ProviderStatus
from fundamentals.refresh_service import refresh_financials
from runtime.redaction import redact_secrets, safe_reason
from runtime.bot_service import VIETNAM_TIMEZONE

PASS, FAIL, NOT_TESTED, INCONCLUSIVE = "PASS", "FAIL", "NOT TESTED", "INCONCLUSIVE"
EXIT_CODES = {PASS: 0, FAIL: 1, NOT_TESTED: 3, INCONCLUSIVE: 3}

_BLOCKER_HINTS = re.compile(
    r"not installed|disabled|unavailable|timeout|timed out|connection|network|resolve|refused|"
    r"ssl|ConnectionError|Timeout|no route", re.IGNORECASE,
)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------ Phase 24 live
@dataclass(frozen=True, slots=True)
class ProviderRecord:
    provider: str
    source: str | None
    symbol: str
    dataset: str
    status: str
    rows: int
    periods: tuple[str, ...]
    retrieved_at: str | None
    reason: str | None = None

    def line(self) -> str:
        periods = ",".join(self.periods[:4]) or "-"
        text = (f"provider={self.provider} source={self.source or '-'} symbol={self.symbol} "
                f"dataset={self.dataset} status={self.status} rows={self.rows} "
                f"periods={periods} retrieved_at={self.retrieved_at or '-'}")
        return text + (f" reason={self.reason}" if self.reason else "")


def summarize(result: ProviderResult) -> ProviderRecord:
    """Compact, payload-free description of one provider result."""
    rows = len(result.statements) or len(result.flows)
    if result.statements:
        periods = tuple(sorted({row.period for row in result.statements}, reverse=True))
    else:
        periods = tuple(sorted({row.trading_date.isoformat() for row in result.flows}, reverse=True))
    return ProviderRecord(
        result.provider, result.provider_source, result.symbol, result.dataset,
        result.status.value, rows, periods,
        None if result.retrieved_at is None else result.retrieved_at.isoformat(timespec="seconds"),
        None if result.error_reason is None else safe_reason(result.error_reason, limit=160),
    )


def provider_verdict(records: Sequence[ProviderRecord]) -> tuple[str, str]:
    """Verdict + explanation for one provider's records."""
    if not records:
        return NOT_TESTED, "no symbols were attempted"
    if any(r.status in ("AVAILABLE", "PARTIAL", "STALE") and r.rows > 0 for r in records):
        return PASS, "at least one real symbol returned rows"
    reasons = " | ".join(r.reason or "" for r in records)
    if all(r.status == "ERROR" for r in records) or _BLOCKER_HINTS.search(reasons):
        return NOT_TESTED, "external blocker: " + (records[0].reason or "provider unreachable")
    return INCONCLUSIVE, "provider answered but returned no data for known symbols"


def probe_host(url: str, *, timeout: float = 8.0, getter=None) -> tuple[bool, str]:
    """Cheap reachability probe used to tell "blocked" from "no data".

    The provider adapters deliberately swallow network errors into MISSING, so
    an unreachable host would otherwise look like "the provider has no data".
    A sandbox/egress-proxy refusal carries ``x-deny-reason``.
    """
    try:
        if getter is None:
            import requests

            getter = requests.head
        response = getter(url, timeout=timeout, allow_redirects=True)
    except Exception as error:
        return False, safe_reason(f"{type(error).__name__}", limit=80)
    denied = response.headers.get("x-deny-reason")
    if denied:
        return False, f"egress denied ({denied})"
    return True, f"HTTP {response.status_code}"


def run_provider_acceptance(
    provider: FundamentalProvider, symbols: Iterable[tuple[str, str | None]], *,
    dataset: str = "FINANCIALS", delay: float = 1.0,
    sleep: Callable[[float], object] = time.sleep,
) -> tuple[ProviderRecord, ...]:
    """One direct call per symbol against a single provider; never raises."""
    records: list[ProviderRecord] = []
    for index, (symbol, exchange) in enumerate(symbols):
        if index:
            sleep(delay)
        try:
            if dataset == "FINANCIALS":
                result = provider.fetch_financials(symbol, exchange=exchange)
            else:
                result = provider.fetch_institutional_flow(symbol, exchange=exchange)
            records.append(summarize(result))
        except Exception as error:  # an adapter should not raise; report it if it does
            records.append(ProviderRecord(
                getattr(provider, "name", "?"), None, symbol, dataset, "ERROR", 0, (), None,
                safe_reason(f"{type(error).__name__}: {error}", limit=160),
            ))
    return tuple(records)


def check_promotion_safety(connection: sqlite3.Connection, symbols: Iterable[str]) -> list[str]:
    """Violations of the point-in-time / bank rules in the acceptance database."""
    violations: list[str] = []
    for symbol in symbols:
        for row in load_automated_statements(connection, symbol):
            if row["public_date"] is None and row["promoted_to_canonical"]:
                violations.append(f"{symbol} {row['period']}: promoted without public_date")
    canonical = connection.execute("SELECT COUNT(*) FROM financial_reports").fetchone()[0]
    promoted = connection.execute(
        "SELECT COUNT(*) FROM automated_financial_statements WHERE promoted_to_canonical=1"
    ).fetchone()[0]
    if canonical != promoted:
        violations.append(f"canonical rows ({canonical}) != promoted staging rows ({promoted})")
    if connection.execute("SELECT COUNT(*) FROM bank_financial_reports").fetchone()[0]:
        violations.append("bank_financial_reports was written by the automated path")
    return violations


def run_chain_refresh_acceptance(
    connection: sqlite3.Connection, chain, symbols: Iterable[tuple[str, str | None]], *,
    delay: float = 1.0, sleep: Callable[[float], object] = time.sleep,
) -> tuple[list[ProviderRecord], list[str]]:
    """Real refresh into a TEMP database, then verify promotion safety."""
    records: list[ProviderRecord] = []
    names: list[str] = []
    refresh_status = {
        "SUCCESS": "AVAILABLE",
        "PARTIAL": "PARTIAL",
        "MISSING": "MISSING",
        "FAILED": "ERROR",
        "SKIPPED_FRESH": "STALE",
    }
    for index, (symbol, exchange) in enumerate(symbols):
        if index:
            sleep(delay)
        with connection:
            connection.execute(
                "INSERT INTO symbols(symbol, exchange, instrument_type) VALUES (?,?, 'STOCK') "
                "ON CONFLICT(symbol) DO NOTHING", (symbol, exchange))
        outcome = refresh_financials(connection, chain, symbol, exchange=exchange, force=True)
        names.append(symbol)
        cov = outcome.coverage
        records.append(ProviderRecord(
            outcome.provider or "-", outcome.provider_source, symbol, "FINANCIALS",
            refresh_status[outcome.result.value], outcome.rows_stored,
            tuple(sorted({r["period"] for r in load_automated_statements(connection, symbol)}, reverse=True)),
            None if cov is None else datetime.fromtimestamp(cov.last_attempt_at, timezone.utc).isoformat(timespec="seconds"),
            None if outcome.error_reason is None else safe_reason(outcome.error_reason, limit=160),
        ))
    return records, check_promotion_safety(connection, names)


# --------------------------------------------------- Telegram live matrix
@dataclass(frozen=True, slots=True)
class CommandCheck:
    command: str
    symbol: str | None
    ok: bool
    degraded: bool
    elapsed: float
    size: int
    note: str
    text: str | None = field(default=None, repr=False)
    png: bytes | None = field(default=None, repr=False)

    def line(self) -> str:
        state = "PASS" if self.ok and not self.degraded else ("DEGRADED" if self.ok else "FAIL")
        return (f"{state:<8} {self.command:<10} {self.symbol or '-':<6} "
                f"{self.elapsed:6.2f}s size={self.size} {self.note}")


_LEAK = re.compile(r"Traceback|Exception|sqlite3\.|KeyError|AttributeError|<redacted>", re.IGNORECASE)


def market_session_note(now: datetime | None = None) -> str:
    """Whether the run happens inside a Vietnamese trading session (informational)."""
    local = (now or datetime.now(timezone.utc)).astimezone(VIETNAM_TIMEZONE)
    open_session = local.weekday() < 5 and (
        (9, 0) <= (local.hour, local.minute) < (11, 30) or (13, 0) <= (local.hour, local.minute) < (14, 45))
    stamp = local.strftime("%a %Y-%m-%d %H:%M ICT")
    return (f"{stamp}: trading session OPEN" if open_session else
            f"{stamp}: market CLOSED - Phase 22 live-session acceptance cannot be satisfied by this run")


def _text_check(name, symbol, call, clock) -> CommandCheck:
    started = clock()
    try:
        text = call()
    except Exception as error:
        return CommandCheck(name, symbol, False, False, clock() - started, 0,
                            safe_reason(f"raised {type(error).__name__}: {error}", limit=140))
    elapsed = clock() - started
    if not isinstance(text, str) or not text.strip():
        return CommandCheck(name, symbol, False, False, elapsed, 0, "empty response")
    if _LEAK.search(text):
        return CommandCheck(name, symbol, False, False, elapsed, len(text), "response leaks internals", text)
    degraded = bool(re.search(r"unavailable|chưa có|không khả dụng|missing|N/A", text, re.IGNORECASE))
    return CommandCheck(name, symbol, True, degraded, elapsed, len(text),
                        "honest unavailable/partial data" if degraded else "ok", text)


def run_command_matrix(
    commands, symbols: Sequence[str], *, clock: Callable[[], float] = time.monotonic,
) -> list[CommandCheck]:
    """/soi (CL1 and ASMF), /market, /sentiment and /chart through the real command service."""
    checks = [_text_check("/market", None, commands.market, clock)]
    for symbol in symbols:
        checks.append(_text_check("/soi", symbol, lambda s=symbol: commands.soi([s]), clock))
        checks.append(_text_check("/soi ASMF", symbol, lambda s=symbol: commands.soi([s, "ASMF"]), clock))
        checks.append(_text_check("/sentiment", symbol, lambda s=symbol: commands.sentiment([s]), clock))
        started = clock()
        try:
            view = commands.chart([symbol])
        except Exception as error:
            checks.append(CommandCheck("/chart", symbol, False, False, clock() - started, 0,
                                       safe_reason(f"raised {type(error).__name__}: {error}", limit=140)))
            continue
        elapsed = clock() - started
        if view.png_bytes is not None and view.error is None:
            good = view.png_bytes.startswith(PNG_MAGIC) and len(view.png_bytes) > 200
            checks.append(CommandCheck("/chart", symbol, good, False, elapsed, len(view.png_bytes),
                                       "png ok" if good else "not a valid PNG", png=view.png_bytes,
                                       text=view.caption))
        else:  # an honest text error (e.g. short history) is acceptable, a broken image is not
            checks.append(CommandCheck("/chart", symbol, bool(view.error), True, elapsed, 0,
                                       view.error or "no image and no error", text=view.error))
    return checks


def pick_diverse_symbols(
    connection: sqlite3.Connection, watch_symbols: Sequence[str] = (), *, bank_sector: str = "8300",
    minimum_bars: int = 126,
) -> dict[str, str]:
    """Label -> symbol, chosen deterministically from the runtime database.

    FPT/ACB are stable baselines when eligible. Other labels are picked by
    metadata (exchange, ICB sector, cached history length) so the sample never
    depends on one ticker staying listed. Labels with no candidate are omitted.
    """
    from runtime.market_universe import load_market_universe

    universe = load_market_universe(connection)
    have = {item.symbol: item.exchange for item in universe}
    picks: dict[str, str] = {}
    used: set[str] = set()

    def take(label: str, candidates: Iterable[str]) -> None:
        for symbol in candidates:
            if symbol in have and symbol not in used:
                picks[label] = symbol
                used.add(symbol)
                return

    banks = {r[0] for r in connection.execute(
        "SELECT symbol FROM sector_memberships WHERE sector_code=? AND effective_to IS NULL ORDER BY symbol",
        (bank_sector,))}
    sectored = [r[0] for r in connection.execute(
        "SELECT DISTINCT symbol FROM sector_memberships WHERE effective_to IS NULL "
        "AND sector_code<>? ORDER BY symbol", (bank_sector,))]
    take("baseline non-bank", ["FPT"])
    take("baseline bank", ["ACB"])
    for label, exchange in (("HNX", ("HNX",)), ("UPCOM", ("UPCOM",))):
        take(label, [s for s, e in have.items() if e in exchange])
    take("bank", sorted(banks))
    take("non-bank outside watchlist", [s for s in sectored if s not in watch_symbols])
    counts = {r[0]: r[1] for r in connection.execute(
        "SELECT symbol, COUNT(*) FROM candles WHERE timeframe='ONE_DAY' GROUP BY symbol")}
    take("short history", sorted(s for s, n in counts.items() if 5 <= n < minimum_bars))
    # HOSE last: specialised labels above must not be consumed by the generic board pick.
    take("HOSE", [s for s, e in have.items() if e in ("HOSE", "HSX")])
    return picks


async def deliver_checks(bot, chat_id: int | str, checks: Sequence[CommandCheck], *, chunk: int = 3900) -> list[str]:
    """Send text via ``send_message`` and charts via ``send_photo``; returns per-item outcomes."""
    from io import BytesIO
    from telegram_bot.app import split_message

    outcomes: list[str] = []
    for check in checks:
        label = f"{check.command} {check.symbol or ''}".strip()
        try:
            if check.png is not None:
                await bot.send_photo(chat_id=chat_id, photo=BytesIO(check.png), caption=(check.text or label)[:1000])
            elif check.text:
                for part in split_message(check.text, chunk):
                    await bot.send_message(chat_id=chat_id, text=part)
            else:
                continue
            outcomes.append(f"SENT {label}")
        except Exception as error:
            outcomes.append(f"SEND-FAILED {label}: " + safe_reason(f"{type(error).__name__}: {error}", limit=120))
    return outcomes


def overall(verdicts: Iterable[str]) -> str:
    values = list(verdicts)
    if FAIL in values:
        return FAIL
    if any(v in (NOT_TESTED, INCONCLUSIVE) for v in values):
        return NOT_TESTED
    return PASS if values else NOT_TESTED


__all__ = [n for n in dir() if not n.startswith("_")]
