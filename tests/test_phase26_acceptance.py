"""Offline tests for the live-acceptance harness logic (no network)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from fundamentals.providers.base import ProviderResult
from fundamentals.providers.provider_chain import ProviderChain
from runtime.acceptance import (
    EXIT_CODES, FAIL, INCONCLUSIVE, NOT_TESTED, PASS, ProviderRecord, check_promotion_safety,
    deliver_checks, market_session_note, overall, pick_diverse_symbols, provider_verdict,
    run_chain_refresh_acceptance, run_command_matrix, run_provider_acceptance, summarize,
)
from runtime.views import ChartRequestView
from tests.coverage_fakes import ScriptedProvider, Sleeper, make_connection, seed_symbols, statement
from tests.test_chart_command import PNG_MAGIC


def rec(status, rows=0, reason=None, provider="VNStock"):
    return ProviderRecord(provider, "VCI", "FPT", "FINANCIALS", status, rows, (), None, reason)


def test_summarize_prints_metadata_not_payload() -> None:
    result = ScriptedProvider().fetch_financials("FPT", exchange="HOSE")
    record = summarize(result)
    assert (record.provider, record.symbol, record.status, record.rows) == ("VNStock", "FPT", "AVAILABLE", 1)
    line = record.line()
    for field in ("provider=", "source=", "symbol=", "status=", "rows=", "periods=", "retrieved_at="):
        assert field in line
    assert "revenue" not in line and "1000" not in line


def test_verdicts_never_fabricate_pass() -> None:
    assert provider_verdict([rec("AVAILABLE", 4)])[0] == PASS
    assert provider_verdict([rec("MISSING", reason="vnstock is not installed")])[0] == NOT_TESTED
    assert provider_verdict([rec("ERROR", reason="ConnectionError")])[0] == NOT_TESTED
    assert provider_verdict([rec("MISSING", reason="no data")])[0] == INCONCLUSIVE
    assert provider_verdict([])[0] == NOT_TESTED
    assert overall([PASS, PASS]) == PASS and overall([PASS, NOT_TESTED]) == NOT_TESTED
    assert overall([PASS, FAIL, NOT_TESTED]) == FAIL and overall([]) == NOT_TESTED
    assert EXIT_CODES[PASS] == 0 and EXIT_CODES[FAIL] == 1 and EXIT_CODES[NOT_TESTED] == 3


def test_provider_acceptance_is_bounded_and_never_raises() -> None:
    prov = ScriptedProvider({"BBB": "raise"})
    sleeper = Sleeper()
    records = run_provider_acceptance(prov, [("AAA", "HOSE"), ("BBB", "HNX")], delay=2.0, sleep=sleeper)
    assert [r.status for r in records] == ["AVAILABLE", "ERROR"] and sleeper.calls == [2.0]
    assert "boom" in records[1].reason


def test_live_rows_without_public_date_are_staged_but_not_promoted(tmp_path) -> None:
    conn = make_connection(tmp_path)

    class NoDate(ScriptedProvider):
        def fetch_financials(self, symbol, *, exchange=None):
            r = super().fetch_financials(symbol, exchange=exchange)
            from dataclasses import replace
            return replace(r, statements=(statement(symbol, public_date=None),))

    records, violations = run_chain_refresh_acceptance(
        conn, ProviderChain([NoDate()]), [("FPT", "HOSE")], sleep=Sleeper())
    assert violations == []
    assert conn.execute("SELECT COUNT(*) FROM automated_financial_statements").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM financial_reports").fetchone()[0] == 0   # correctness over coverage
    assert records[0].rows == 1


def test_promotion_safety_detects_violations(tmp_path) -> None:
    conn = make_connection(tmp_path)
    seed_symbols(conn, [("FPT", "HOSE", "STOCK", 1)])
    with conn:
        conn.execute("INSERT INTO automated_financial_statements(symbol,period,source,provider,promoted_to_canonical) "
                     "VALUES ('FPT','2026Q1','VNStock','VNStock',1)")
    problems = check_promotion_safety(conn, ["FPT"])
    assert any("without public_date" in p for p in problems) and any("canonical rows" in p for p in problems)


def test_bank_is_never_auto_promoted_in_acceptance(tmp_path) -> None:
    conn = make_connection(tmp_path)
    records, violations = run_chain_refresh_acceptance(
        conn, ProviderChain([ScriptedProvider()]), [("ACB", "HOSE")], sleep=Sleeper())
    assert violations == [] and conn.execute("SELECT COUNT(*) FROM bank_financial_reports").fetchone()[0] == 0


# --------------------------------------------------------- command matrix
class Cmds:
    def __init__(self, **over):
        self.over = over

    def market(self): return self.over.get("market", "VNINDEX: BULL")
    def soi(self, args): return self.over.get("soi", f"{args[0]} ok")
    def sentiment(self, args): return self.over.get("sentiment", "News sentiment unavailable.")

    def chart(self, args):
        return self.over.get("chart", ChartRequestView(args[0], PNG_MAGIC + b"\0" * 400, "cap", None))


def test_matrix_passes_and_marks_honest_unavailable_as_degraded() -> None:
    checks = run_command_matrix(Cmds(), ["FPT"])
    by = {c.command: c for c in checks}
    assert set(by) == {"/market", "/soi", "/soi ASMF", "/sentiment", "/chart"}
    assert all(c.ok for c in checks)
    assert by["/sentiment"].degraded and not by["/soi"].degraded
    assert by["/chart"].png.startswith(PNG_MAGIC)


def test_matrix_fails_on_leaks_empty_answers_and_broken_images() -> None:
    checks = run_command_matrix(Cmds(market="Traceback (most recent call last)", soi="  ",
                                     chart=ChartRequestView("FPT", b"notpng" * 100, "c", None)), ["FPT"])
    by = {(c.command): c for c in checks}
    assert not by["/market"].ok and not by["/soi"].ok and not by["/chart"].ok


def test_matrix_reports_exceptions_without_raising() -> None:
    class Bad(Cmds):
        def soi(self, args): raise RuntimeError("kaput")
        def chart(self, args): raise RuntimeError("kaput")
    checks = run_command_matrix(Bad(), ["FPT"])
    assert [c.ok for c in checks if c.command in ("/soi", "/chart")] == [False, False]


def test_matrix_accepts_honest_chart_error_as_degraded() -> None:
    checks = run_command_matrix(Cmds(chart=ChartRequestView("NEW", None, "", "cần tối thiểu 5 phiên")), ["NEW"])
    chart = next(c for c in checks if c.command == "/chart")
    assert chart.ok and chart.degraded and chart.png is None


# ------------------------------------------------------- symbol sampling
def test_diverse_sample_is_picked_by_metadata(tmp_path) -> None:
    from asmf_data.models import SectorMembership
    from asmf_data.store import upsert_sector_memberships

    conn = make_connection(tmp_path)
    seed_symbols(conn, [("FPT", "HOSE", "STOCK", 1), ("ACB", "HOSE", "STOCK", 1), ("SHB", "HNX", "STOCK", 1),
                        ("VGI", "UPCOM", "STOCK", 1), ("VCB", "HOSE", "STOCK", 1), ("VHM", "HOSE", "STOCK", 1),
                        ("NEW", "HOSE", "STOCK", 1), ("HPG", "HOSE", "STOCK", 1)])
    upsert_sector_memberships(conn, [
        SectorMembership("ACB", "8300", "Banks", date(2020, 1, 1), None, "T"),
        SectorMembership("VCB", "8300", "Banks", date(2020, 1, 1), None, "T"),
        SectorMembership("VHM", "8600", "RE", date(2020, 1, 1), None, "T")])
    with conn:
        conn.executemany("INSERT INTO candles(symbol,timeframe,timestamp,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?,?)",
                         [("NEW", "ONE_DAY", 1_700_000_000 + i * 86400, 1, 2, 1, 1.5, 9) for i in range(30)])
    picks = pick_diverse_symbols(conn, ["FPT", "ACB"])
    assert picks["baseline non-bank"] == "FPT" and picks["baseline bank"] == "ACB"
    assert picks["HNX"] == "SHB" and picks["UPCOM"] == "VGI" and picks["bank"] == "VCB"
    assert picks["non-bank outside watchlist"] == "VHM" and picks["short history"] == "NEW"
    assert picks["HOSE"] == "HPG"
    assert len(set(picks.values())) == len(picks)                    # no duplicates
    assert pick_diverse_symbols(make_connection(tmp_path, "empty.sqlite3")) == {}


# ---------------------------------------------------------- Telegram send
class Bot:
    def __init__(self, fail_photo=False):
        self.messages, self.photos, self.fail_photo = [], [], fail_photo

    async def send_message(self, chat_id, text): self.messages.append((chat_id, text))

    async def send_photo(self, chat_id, photo, caption=None):
        if self.fail_photo:
            raise RuntimeError("Forbidden https://api.telegram.org/bot123456789:AAH_fakeTokenValueForTestsOnly_0123456789/sendPhoto")
        self.photos.append((chat_id, photo.getvalue()))


def test_delivery_chunks_text_sends_png_and_redacts_failures() -> None:
    checks = run_command_matrix(Cmds(market=("z" * 1500 + "\n\n") * 6), ["FPT"])
    bot = Bot()
    out = asyncio.run(deliver_checks(bot, 42, checks))
    assert all(len(t) <= 4096 for _, t in bot.messages) and len(bot.photos) == 1
    assert all(o.startswith("SENT") for o in out)
    bad = asyncio.run(deliver_checks(Bot(fail_photo=True), 42, checks))
    failed = [o for o in bad if o.startswith("SEND-FAILED")]
    assert failed and "AAH_fake" not in " ".join(failed)


def test_session_note_distinguishes_open_and_closed() -> None:
    open_t = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)      # Mon 10:00 ICT
    shut = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)        # Sunday
    assert "OPEN" in market_session_note(open_t) and "CLOSED" in market_session_note(shut)
    assert "CLOSED" in market_session_note(datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc))   # 16:00 ICT


def test_probe_host_distinguishes_blocked_from_reachable() -> None:
    from runtime.acceptance import probe_host

    def blocked(url, **kw):
        return SimpleNamespace(status_code=403, headers={"x-deny-reason": "host_not_allowed"})

    def ok(url, **kw):
        return SimpleNamespace(status_code=200, headers={})

    def down(url, **kw):
        raise ConnectionError("no route")

    assert probe_host("https://x", getter=ok) == (True, "HTTP 200")
    reachable, note = probe_host("https://x", getter=blocked)
    assert not reachable and "host_not_allowed" in note
    assert probe_host("https://x", getter=down)[0] is False


def test_telegram_live_script_end_to_end_with_a_fake_vietcap(tmp_path, monkeypatch, capsys) -> None:
    """Runs the real script body offline: temp DB copy, sampling, command matrix, verdict."""
    import scripts.test_phase26_telegram_live as script
    from tests.test_runtime_bot import FakeClient, payload

    prod = make_connection(tmp_path, "prod.sqlite3")
    seed_symbols(prod, [("FPT", "HOSE", "STOCK", 1), ("ACB", "HOSE", "STOCK", 1), ("SHB", "HNX", "STOCK", 1)])
    prod.close()
    for name in ("VIETCAP_AUTHORIZATION", "VIETCAP_DEVICE_ID", "VIETCAP_COOKIE"):
        monkeypatch.setenv(name, "x" * 12)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'prod.sqlite3').as_posix()}")
    monkeypatch.setenv("NEWS_DATABASE_PATH", str(tmp_path / "news.db"))
    monkeypatch.setattr(script, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(script, "probe_host", lambda url: (True, "HTTP 200"))
    monkeypatch.setattr("data.vietcap.rest.VietcapRestClient", lambda **kw: FakeClient(payload()))
    code = script.main(["--max-symbols", "3"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Phase 26 Telegram/live acceptance: PASS" in out and "/chart" in out and "sample:" in out
    before = make_connection(tmp_path, "prod.sqlite3")
    assert before.execute("SELECT COUNT(*) FROM candles").fetchone()[0] == 0     # production DB untouched
