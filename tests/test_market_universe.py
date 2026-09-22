"""Universe selection: driven by the symbols table, never a ticker list."""

from __future__ import annotations

from runtime.market_universe import MarketSymbol, load_market_universe
from tests.coverage_fakes import make_connection, seed_symbols


def test_only_active_common_stocks_on_supported_exchanges(tmp_path) -> None:
    connection = make_connection(tmp_path)
    seed_symbols(connection, [
        ("FPT", "HOSE", "STOCK", 1),
        ("ACB", "HSX", "STOCK", 1),          # Vietcap name for HOSE
        ("SHB", "HNX", "STOCK", 1),
        ("VGI", "UPCOM", "COMMON_STOCK", 1),
        ("OLD", "HOSE", "STOCK", 0),          # inactive
        ("FUT", "HOSE", "FUTURE", 1),         # not a stock
        ("ETF", "HOSE", "ETF", 1),
        ("FOR", "NYSE", "STOCK", 1),          # unsupported exchange
        ("VNINDEX", "HOSE", "INDEX", 1),
    ])
    universe = load_market_universe(connection)
    assert [item.symbol for item in universe] == ["ACB", "FPT", "SHB", "VGI"]


def test_unknown_exchange_is_kept_because_sector_import_leaves_it_null(tmp_path) -> None:
    connection = make_connection(tmp_path)
    seed_symbols(connection, [("VIX", None, "STOCK", 1), ("BAD", "OTC", "STOCK", 1)])
    assert [item.symbol for item in load_market_universe(connection)] == ["VIX"]

def test_index_auto_created_as_stock_is_still_excluded(tmp_path) -> None:
    """Regression: several write paths (RuntimeBotDataService._store,
    sector_history_sync, fundamentals.coverage_store, asmf_data.store,
    portfolio.repository) auto-create a `symbols` row the first time a
    ticker's bars are cached, defaulting instrument_type to 'STOCK' with no
    exchange. VNINDEX gets its bars cached constantly as the benchmark, so it
    ends up with exactly this shape — indistinguishable from a real stock by
    instrument_type/exchange alone — and slipped into live /scan results."""
    connection = make_connection(tmp_path)
    seed_symbols(connection, [
        ("FPT", "HOSE", "STOCK", 1),
        ("VNINDEX", None, "STOCK", 1),   # exactly what `_store()` creates
        ("VN30", None, "STOCK", 1),
        ("HNXINDEX", None, "STOCK", 1),
    ])
    assert [item.symbol for item in load_market_universe(connection)] == ["FPT"]

def test_hsx_is_presented_to_providers_as_hose(tmp_path) -> None:
    connection = make_connection(tmp_path)
    seed_symbols(connection, [("ACB", "HSX", "STOCK", 1), ("SHB", "HNX", "STOCK", 1)])
    by_symbol = {item.symbol: item for item in load_market_universe(connection)}
    assert by_symbol["ACB"].exchange == "HSX"
    assert by_symbol["ACB"].provider_exchange == "HOSE"
    assert by_symbol["SHB"].provider_exchange == "HNX"


def test_order_is_alphabetical_and_deterministic(tmp_path) -> None:
    connection = make_connection(tmp_path)
    seed_symbols(connection, [("ZZZ", "HOSE", "STOCK", 1), ("AAA", "HOSE", "STOCK", 1),
                              ("MMM", "HNX", "STOCK", 1)])
    first = load_market_universe(connection)
    assert [item.symbol for item in first] == ["AAA", "MMM", "ZZZ"]
    assert load_market_universe(connection) == first


def test_symbol_filter_never_invents_or_admits_ineligible_symbols(tmp_path) -> None:
    connection = make_connection(tmp_path)
    seed_symbols(connection, [("FPT", "HOSE", "STOCK", 1), ("OLD", "HOSE", "STOCK", 0)])
    result = load_market_universe(connection, symbols=("fpt", "OLD", "NOPE"))
    assert result == (MarketSymbol("FPT", "HOSE"),)


def test_universe_follows_the_table_not_code(tmp_path) -> None:
    connection = make_connection(tmp_path)
    assert load_market_universe(connection) == ()
    seed_symbols(connection, [("NEW", "UPCOM", "STOCK", 1)])
    assert [item.symbol for item in load_market_universe(connection)] == ["NEW"]
