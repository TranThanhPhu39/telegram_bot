"""The set of symbols the coverage worker is responsible for.

The universe is read from the SQLite ``symbols`` table on every cycle — there
is no ticker list in code. Eligibility follows the repository's existing
semantics (``scanner.universe``, ``intelligence.news.pipeline.active_stock_symbols``
and ``asmf_data.vietcap_sectors``):

* ``is_active = 1``;
* ``instrument_type`` in ``STOCK``/``COMMON_STOCK``;
* exchange in ``HOSE``/``HSX``/``HNX``/``UPCOM``, **or unknown (NULL)**.

The NULL-exchange rule is deliberate and matches how the table is really
populated: the Vietcap sector snapshot (already filtered to those four boards)
and the history caches insert ``symbols`` rows without an exchange. Excluding
NULL would empty the universe on a real database. A row with an explicit
exchange outside the supported set (an index, a foreign board) is excluded.

A symbol a provider cannot serve stays in the universe; the *coverage* row
records that dataset as MISSING instead of dropping the symbol.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from portfolio.repository import NON_STOCK_SYMBOLS
from scanner.universe import COMMON_STOCK_TYPES, SUPPORTED_EXCHANGES
#: ``HSX`` is what the Vietcap catalog calls HOSE; scanner.universe only lists HOSE.
UNIVERSE_EXCHANGES = frozenset(SUPPORTED_EXCHANGES | {"HSX"})


@dataclass(frozen=True, slots=True)
class MarketSymbol:
    symbol: str
    #: Stored exchange (upper-case) or ``None`` when the database does not know it.
    exchange: str | None

    @property
    def provider_exchange(self) -> str | None:
        """Exchange hint for providers, with HSX folded into HOSE."""
        return "HOSE" if self.exchange == "HSX" else self.exchange


def load_market_universe(
    connection: sqlite3.Connection, *, symbols: tuple[str, ...] | None = None,
) -> tuple[MarketSymbol, ...]:
    """Eligible symbols in deterministic (alphabetical) order.

    ``symbols`` narrows the result for manual CLI runs; a requested symbol that
    is not eligible is simply absent, never invented.
    """
    type_marks = ",".join("?" for _ in COMMON_STOCK_TYPES)
    exchange_marks = ",".join("?" for _ in UNIVERSE_EXCHANGES)
    index_marks = ",".join("?" for _ in NON_STOCK_SYMBOLS)
    rows = connection.execute(
        "SELECT symbol, exchange FROM symbols WHERE is_active=1 "
        f"AND instrument_type IN ({type_marks}) "
        f"AND (exchange IS NULL OR exchange IN ({exchange_marks})) "
        f"AND symbol NOT IN ({index_marks}) "
        "ORDER BY symbol",
        (*sorted(COMMON_STOCK_TYPES), *sorted(UNIVERSE_EXCHANGES), *sorted(NON_STOCK_SYMBOLS)),
    ).fetchall()
    universe = tuple(MarketSymbol(row["symbol"], row["exchange"]) for row in rows)
    if symbols is None:
        return universe
    wanted = {item.strip().upper() for item in symbols if item.strip()}
    return tuple(item for item in universe if item.symbol in wanted)