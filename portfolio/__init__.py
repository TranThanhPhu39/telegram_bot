"""Portfolio, risk and watchlist domain (Phase 23).

Pure domain logic and SQLite persistence for user watchlists, long-only
holdings, exposure, concentration, position sizing and deterministic stress
tests.  Nothing here talks to Vietcap or Telegram: market data enters through
the ``MarketDataPort`` protocol defined in ``portfolio.service``.
"""