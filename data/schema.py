"""Incremental SQLite schema definitions for the V1 datastore."""

from __future__ import annotations

import sqlite3

SYMBOLS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    exchange TEXT,
    instrument_type TEXT NOT NULL DEFAULT 'STOCK',
    is_active INTEGER NOT NULL DEFAULT 1,
    CHECK (length(symbol) BETWEEN 1 AND 32),
    CHECK (symbol = upper(trim(symbol))),
    CHECK (symbol NOT GLOB '*[^A-Z0-9]*'),
    CHECK (
        exchange IS NULL OR (
            length(exchange) BETWEEN 1 AND 16
            AND exchange = upper(trim(exchange))
            AND exchange NOT GLOB '*[^A-Z0-9]*'
        )
    ),
    CHECK (length(instrument_type) BETWEEN 1 AND 32),
    CHECK (instrument_type = upper(trim(instrument_type))),
    CHECK (instrument_type NOT GLOB '*[^A-Z0-9_]*'),
    CHECK (is_active IN (0, 1))
) WITHOUT ROWID
"""

CANDLES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, timeframe, timestamp),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (length(timeframe) BETWEEN 1 AND 32),
    CHECK (timeframe = upper(trim(timeframe))),
    CHECK (timeframe NOT GLOB '*[^A-Z0-9_]*'),
    CHECK (typeof(timestamp) = 'integer' AND timestamp > 0),
    CHECK (typeof(open) IN ('integer', 'real') AND open > 0),
    CHECK (typeof(high) IN ('integer', 'real') AND high > 0),
    CHECK (typeof(low) IN ('integer', 'real') AND low > 0),
    CHECK (typeof(close) IN ('integer', 'real') AND close > 0),
    CHECK (typeof(volume) IN ('integer', 'real') AND volume >= 0),
    CHECK (high >= open AND high >= low AND high >= close),
    CHECK (low <= open AND low <= high AND low <= close)
) WITHOUT ROWID
"""

SIGNALS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    trigger_price REAL,
    reason_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (length(strategy) BETWEEN 1 AND 64),
    CHECK (strategy = upper(trim(strategy))),
    CHECK (strategy NOT GLOB '*[^A-Z0-9_]*'),
    CHECK (length(timeframe) BETWEEN 1 AND 32),
    CHECK (timeframe = upper(trim(timeframe))),
    CHECK (timeframe NOT GLOB '*[^A-Z0-9_]*'),
    CHECK (length(state) BETWEEN 1 AND 32),
    CHECK (state = upper(trim(state))),
    CHECK (state NOT GLOB '*[^A-Z0-9_]*'),
    CHECK (typeof(created_at) = 'integer' AND created_at > 0),
    CHECK (typeof(updated_at) = 'integer' AND updated_at >= created_at),
    CHECK (
        trigger_price IS NULL OR (
            typeof(trigger_price) IN ('integer', 'real')
            AND trigger_price > 0
        )
    ),
    CHECK (json_valid(reason_json))
)
"""

SIGNALS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_signals_symbol_created_at
ON signals(symbol, created_at DESC)
"""

SIGNAL_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS signal_events (
    event_id INTEGER PRIMARY KEY,
    signal_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    occurred_at INTEGER NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    price REAL,
    reason_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (signal_id, sequence),
    FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (typeof(sequence) = 'integer' AND sequence > 0),
    CHECK (typeof(occurred_at) = 'integer' AND occurred_at > 0),
    CHECK (
        from_state IS NULL OR (
            length(from_state) BETWEEN 1 AND 32
            AND from_state = upper(trim(from_state))
            AND from_state NOT GLOB '*[^A-Z0-9_]*'
        )
    ),
    CHECK (length(to_state) BETWEEN 1 AND 32),
    CHECK (to_state = upper(trim(to_state))),
    CHECK (to_state NOT GLOB '*[^A-Z0-9_]*'),
    CHECK (
        price IS NULL OR (
            typeof(price) IN ('integer', 'real')
            AND price > 0
        )
    ),
    CHECK (json_valid(reason_json))
)
"""

SIGNAL_EVENTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_signal_events_signal_time
ON signal_events(signal_id, occurred_at, sequence)
"""

SECTOR_MEMBERSHIPS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sector_memberships (
    symbol TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    source TEXT NOT NULL,
    PRIMARY KEY (symbol, sector_code, effective_from),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (symbol = upper(trim(symbol))),
    CHECK (sector_code = upper(trim(sector_code))),
    CHECK (length(trim(sector_name)) > 0),
    CHECK (date(effective_from) = effective_from),
    CHECK (effective_to IS NULL OR date(effective_to) = effective_to),
    CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CHECK (length(trim(source)) > 0)
) WITHOUT ROWID
"""

FINANCIAL_REPORTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS financial_reports (
    symbol TEXT NOT NULL,
    report_period TEXT NOT NULL,
    public_date TEXT NOT NULL,
    consolidated INTEGER NOT NULL,
    revenue REAL NOT NULL,
    net_profit REAL NOT NULL,
    equity REAL NOT NULL,
    total_debt REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (symbol, report_period, consolidated),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (symbol = upper(trim(symbol))),
    CHECK (date(public_date) = public_date),
    CHECK (consolidated IN (0, 1)),
    CHECK (revenue >= 0 AND equity > 0 AND total_debt >= 0),
    CHECK (length(trim(source)) > 0)
) WITHOUT ROWID
"""

INSTITUTIONAL_FLOWS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS institutional_flows (
    symbol TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    foreign_buy_value REAL,
    foreign_sell_value REAL,
    proprietary_buy_value REAL,
    proprietary_sell_value REAL,
    source TEXT NOT NULL,
    PRIMARY KEY (symbol, trading_date),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (symbol = upper(trim(symbol))),
    CHECK (date(trading_date) = trading_date),
    CHECK (foreign_buy_value IS NULL OR foreign_buy_value >= 0),
    CHECK (foreign_sell_value IS NULL OR foreign_sell_value >= 0),
    CHECK (proprietary_buy_value IS NULL OR proprietary_buy_value >= 0),
    CHECK (proprietary_sell_value IS NULL OR proprietary_sell_value >= 0),
    CHECK (length(trim(source)) > 0)
) WITHOUT ROWID
"""

BANK_FINANCIAL_REPORTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bank_financial_reports (
    symbol TEXT NOT NULL,
    report_period TEXT NOT NULL,
    public_date TEXT NOT NULL,
    period_months INTEGER NOT NULL,
    net_interest_income REAL NOT NULL,
    net_profit REAL NOT NULL,
    equity REAL NOT NULL,
    gross_loans REAL NOT NULL,
    nonperforming_loans REAL,
    loan_loss_reserve REAL,
    car_percent REAL,
    source TEXT NOT NULL,
    PRIMARY KEY (symbol, report_period),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (symbol = upper(trim(symbol))),
    CHECK (report_period GLOB '[0-9][0-9][0-9][0-9]Q[1-4]'),
    CHECK (date(public_date) = public_date),
    CHECK (period_months IN (3, 6, 9, 12)),
    CHECK (net_interest_income >= 0 AND equity > 0 AND gross_loans > 0),
    CHECK (nonperforming_loans IS NULL OR nonperforming_loans >= 0),
    CHECK (loan_loss_reserve IS NULL OR loan_loss_reserve >= 0),
    CHECK (car_percent IS NULL OR car_percent > 0),
    CHECK (length(trim(source)) > 0)
) WITHOUT ROWID
"""


def create_symbols_table(connection: sqlite3.Connection) -> None:
    """Create the normalized symbol catalog without altering existing rows."""
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    with connection:
        connection.execute(SYMBOLS_TABLE_SQL)


def create_candles_table(connection: sqlite3.Connection) -> None:
    """Create OHLCV storage linked to the normalized symbol catalog."""
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    with connection:
        connection.execute(CANDLES_TABLE_SQL)


def create_signals_table(connection: sqlite3.Connection) -> None:
    """Create current/high-level signal records without defining events."""
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    with connection:
        connection.execute(SIGNALS_TABLE_SQL)
        connection.execute(SIGNALS_INDEX_SQL)


def create_signal_events_table(connection: sqlite3.Connection) -> None:
    """Create the ordered audit trail for signal state transitions."""
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    with connection:
        connection.execute(SIGNAL_EVENTS_TABLE_SQL)
        connection.execute(SIGNAL_EVENTS_INDEX_SQL)


USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    telegram_user_id INTEGER PRIMARY KEY,
    risk_profile TEXT,
    default_risk_per_trade_pct REAL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (telegram_user_id > 0),
    CHECK (risk_profile IS NULL OR length(trim(risk_profile)) > 0),
    CHECK (
        default_risk_per_trade_pct IS NULL OR (
            typeof(default_risk_per_trade_pct) IN ('integer', 'real')
            AND default_risk_per_trade_pct > 0
            AND default_risk_per_trade_pct <= 100
        )
    ),
    CHECK (typeof(created_at) = 'integer' AND created_at > 0),
    CHECK (typeof(updated_at) = 'integer' AND updated_at >= created_at)
) WITHOUT ROWID
"""

WATCHLIST_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS watchlist (
    telegram_user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (telegram_user_id, symbol),
    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (typeof(created_at) = 'integer' AND created_at > 0)
) WITHOUT ROWID
"""

PORTFOLIO_HOLDINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS portfolio_holdings (
    telegram_user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    average_cost REAL NOT NULL,
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (telegram_user_id, symbol),
    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (symbol) REFERENCES symbols(symbol)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (typeof(quantity) = 'integer' AND quantity > 0),
    CHECK (typeof(average_cost) IN ('integer', 'real') AND average_cost > 0),
    CHECK (typeof(updated_at) = 'integer' AND updated_at > 0)
) WITHOUT ROWID
"""

WATCHLIST_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist(symbol)
"""

PORTFOLIO_HOLDINGS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_portfolio_holdings_symbol ON portfolio_holdings(symbol)
"""

# Migration 5 adds canonical decimal text beside the Phase 23 v4 REAL columns.
# SQLite REAL cannot round-trip every Decimal exactly.  The legacy columns stay
# populated for backward compatibility and their existing CHECK constraints;
# repository reads use the exact text columns after migration.
USERS_RISK_DECIMAL_COLUMN_SQL = """
ALTER TABLE users ADD COLUMN default_risk_per_trade_decimal TEXT
    CHECK (
        default_risk_per_trade_decimal IS NULL
        OR length(trim(default_risk_per_trade_decimal)) > 0
    )
"""

PORTFOLIO_COST_DECIMAL_COLUMN_SQL = """
ALTER TABLE portfolio_holdings ADD COLUMN average_cost_decimal TEXT
    CHECK (
        average_cost_decimal IS NULL
        OR length(trim(average_cost_decimal)) > 0
    )
"""

BACKFILL_USERS_RISK_DECIMAL_SQL = """
UPDATE users
SET default_risk_per_trade_decimal = CAST(default_risk_per_trade_pct AS TEXT)
WHERE default_risk_per_trade_pct IS NOT NULL
  AND default_risk_per_trade_decimal IS NULL
"""

BACKFILL_PORTFOLIO_COST_DECIMAL_SQL = """
UPDATE portfolio_holdings
SET average_cost_decimal = CAST(average_cost AS TEXT)
WHERE average_cost_decimal IS NULL
"""

SECTOR_SYNC_WATCHERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sector_sync_watchers (
    chat_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    incomplete_sent INTEGER NOT NULL DEFAULT 0,
    closed INTEGER NOT NULL DEFAULT 0,
    pending_kind TEXT,
    pending_text TEXT,
    pending_attempts INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (chat_id, symbol),
    CHECK (length(trim(chat_id)) BETWEEN 1 AND 64),
    CHECK (length(symbol) BETWEEN 1 AND 32),
    CHECK (symbol = upper(trim(symbol))),
    CHECK (symbol NOT GLOB '*[^A-Z0-9]*'),
    CHECK (incomplete_sent IN (0, 1)),
    CHECK (closed IN (0, 1)),
    CHECK (
        pending_kind IS NULL
        OR pending_kind IN ('INCOMPLETE', 'READY', 'UNAVAILABLE')
    ),
    CHECK ((pending_kind IS NULL) = (pending_text IS NULL)),
    CHECK (typeof(pending_attempts) = 'integer' AND pending_attempts >= 0),
    CHECK (typeof(created_at) = 'integer' AND created_at > 0),
    CHECK (typeof(updated_at) = 'integer' AND updated_at >= created_at)
) WITHOUT ROWID
"""

SECTOR_SYNC_RESULTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sector_sync_results (
    symbol TEXT PRIMARY KEY,
    sector_code TEXT,
    members INTEGER NOT NULL,
    usable INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    ready INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (length(symbol) BETWEEN 1 AND 32),
    CHECK (symbol = upper(trim(symbol))),
    CHECK (symbol NOT GLOB '*[^A-Z0-9]*'),
    CHECK (sector_code IS NULL OR length(trim(sector_code)) > 0),
    CHECK (typeof(members) = 'integer' AND members >= 0),
    CHECK (typeof(usable) = 'integer' AND usable >= 0),
    CHECK (typeof(failed) = 'integer' AND failed >= 0),
    CHECK (ready IN (0, 1)),
    CHECK (length(trim(fingerprint)) > 0),
    CHECK (typeof(updated_at) = 'integer' AND updated_at > 0)
) WITHOUT ROWID
"""

SECTOR_SYNC_WATCHERS_SYMBOL_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sector_sync_watchers_symbol
    ON sector_sync_watchers(symbol)
"""

SECTOR_SYNC_WATCHERS_PENDING_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_sector_sync_watchers_pending
    ON sector_sync_watchers(pending_kind)
"""

AUTOMATED_FINANCIAL_STATEMENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS automated_financial_statements (
    symbol TEXT NOT NULL,
    period TEXT NOT NULL,
    source TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_source TEXT,
    public_date TEXT,
    consolidated INTEGER NOT NULL DEFAULT 1,
    revenue REAL,
    gross_profit REAL,
    operating_profit REAL,
    net_income REAL,
    net_income_parent REAL,
    total_assets REAL,
    total_equity REAL,
    total_liabilities REAL,
    cash REAL,
    short_term_debt REAL,
    long_term_debt REAL,
    operating_cash_flow REAL,
    capex REAL,
    net_interest_income REAL,
    bank_net_profit REAL,
    bank_equity REAL,
    gross_loans REAL,
    nonperforming_loans REAL,
    loan_loss_reserve REAL,
    car_percent REAL,
    retrieved_at INTEGER NOT NULL DEFAULT (unixepoch()),
    promoted_to_canonical INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, period, source),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (symbol = upper(trim(symbol))),
    CHECK (period GLOB '[0-9][0-9][0-9][0-9]Q[1-4]' OR period GLOB '[0-9][0-9][0-9][0-9]'),
    CHECK (length(trim(source)) > 0),
    CHECK (length(trim(provider)) > 0),
    CHECK (public_date IS NULL OR date(public_date) = public_date),
    CHECK (consolidated IN (0, 1)),
    CHECK (promoted_to_canonical IN (0, 1)),
    CHECK (typeof(retrieved_at) = 'integer' AND retrieved_at > 0)
) WITHOUT ROWID
"""

AUTOMATED_FINANCIAL_STATEMENTS_SYMBOL_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_automated_financial_statements_symbol
    ON automated_financial_statements(symbol)
"""

SYMBOL_DATA_COVERAGE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS symbol_data_coverage (
    symbol TEXT NOT NULL,
    dataset TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT,
    provider_source TEXT,
    error_reason TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at INTEGER,
    last_success_at INTEGER,
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (symbol, dataset),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (symbol = upper(trim(symbol))),
    CHECK (dataset IN ('FINANCIALS', 'INSTITUTIONAL')),
    CHECK (status IN (
        'NEVER_ATTEMPTED', 'READY', 'PARTIAL', 'MISSING', 'STALE', 'ERROR', 'IN_PROGRESS'
    )),
    CHECK (typeof(attempts) = 'integer' AND attempts >= 0),
    CHECK (typeof(updated_at) = 'integer' AND updated_at > 0)
) WITHOUT ROWID
"""

SYMBOL_DATA_COVERAGE_STATUS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_symbol_data_coverage_status
    ON symbol_data_coverage(dataset, status)
"""

# --- Migration v8 (Phase 25) --------------------------------------------------
# v7 restricted symbol_data_coverage.dataset to FINANCIALS/INSTITUTIONAL with a
# CHECK constraint, which SQLite cannot alter in place. Phase 25 tracks three
# more datasets in the SAME table (no competing coverage table), so v8 rebuilds
# it: create-new, copy every row unchanged, drop-old, rename, re-index. The
# migration runner wraps the sequence in a single transaction.
SYMBOL_DATA_COVERAGE_V8_TABLE_SQL = """
CREATE TABLE symbol_data_coverage_v8 (
    symbol TEXT NOT NULL,
    dataset TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT,
    provider_source TEXT,
    error_reason TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at INTEGER,
    last_success_at INTEGER,
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (symbol, dataset),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON UPDATE CASCADE ON DELETE RESTRICT,
    CHECK (symbol = upper(trim(symbol))),
    CHECK (dataset IN (
        'FINANCIALS', 'INSTITUTIONAL', 'MARKET_HISTORY', 'SECTOR_HISTORY', 'NEWS'
    )),
    CHECK (status IN (
        'NEVER_ATTEMPTED', 'READY', 'PARTIAL', 'MISSING', 'STALE', 'ERROR', 'IN_PROGRESS'
    )),
    CHECK (typeof(attempts) = 'integer' AND attempts >= 0),
    CHECK (typeof(updated_at) = 'integer' AND updated_at > 0)
) WITHOUT ROWID
"""

SYMBOL_DATA_COVERAGE_V8_COPY_SQL = """
INSERT INTO symbol_data_coverage_v8 (
    symbol, dataset, status, provider, provider_source, error_reason,
    attempts, last_attempt_at, last_success_at, updated_at
) SELECT
    symbol, dataset, status, provider, provider_source, error_reason,
    attempts, last_attempt_at, last_success_at, updated_at
FROM symbol_data_coverage
"""

SYMBOL_DATA_COVERAGE_V8_DROP_INDEX_SQL = "DROP INDEX IF EXISTS idx_symbol_data_coverage_status"
SYMBOL_DATA_COVERAGE_V8_DROP_SQL = "DROP TABLE symbol_data_coverage"
SYMBOL_DATA_COVERAGE_V8_RENAME_SQL = (
    "ALTER TABLE symbol_data_coverage_v8 RENAME TO symbol_data_coverage"
)

SCAN_SNAPSHOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scan_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    scanned_at INTEGER NOT NULL,
    total_universe INTEGER NOT NULL,
    screened_count INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '[]',
    CHECK (length(strategy) BETWEEN 1 AND 32),
    CHECK (strategy = upper(trim(strategy))),
    CHECK (strategy NOT GLOB '*[^A-Z0-9_]*'),
    CHECK (length(as_of_date) BETWEEN 8 AND 16),
    CHECK (typeof(scanned_at) = 'integer' AND scanned_at > 0),
    CHECK (total_universe >= 0),
    CHECK (screened_count >= 0),
    CHECK (json_valid(payload_json))
)
"""

SCAN_SNAPSHOTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_scan_snapshots_strategy_scanned_at
ON scan_snapshots(strategy, scanned_at DESC)
"""

# Issue 3.4: total_universe was the full market count and screened_count was
# already the *capped* watch-list size, so the UI had no honest number for
# "how many symbols actually passed the prescreen filter" before the cap was
# applied. This column stores that real intermediate count.
SCAN_SNAPSHOTS_PRESCREEN_COUNT_COLUMN_SQL = """
ALTER TABLE scan_snapshots ADD COLUMN prescreen_count INTEGER NOT NULL DEFAULT 0
    CHECK (prescreen_count >= 0)
"""

# --- Migration v11 (Performance remediation P2) ------------------------------
BACKTEST_RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    run_kind TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    completed_at INTEGER,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    universe_size INTEGER NOT NULL,
    symbols_json TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    final_equity REAL,
    trade_count INTEGER NOT NULL,
    open_position_count INTEGER NOT NULL DEFAULT 0,
    total_return_percent REAL,
    cagr_percent REAL,
    max_drawdown_percent REAL,
    sharpe_ratio REAL,
    sortino_ratio REAL,
    calmar_ratio REAL,
    win_rate_percent REAL,
    average_return_percent REAL,
    profit_factor REAL,
    expectancy_percent REAL,
    average_win_percent REAL,
    average_loss_percent REAL,
    payoff_ratio REAL,
    best_trade_percent REAL,
    worst_trade_percent REAL,
    average_holding_sessions REAL,
    longest_losing_streak INTEGER,
    exposure_percent REAL,
    trades_per_year REAL,
    benchmark_return_percent REAL,
    benchmark_max_drawdown_percent REAL,
    excess_return_percent REAL,
    config_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (length(trim(run_id)) > 0),
    CHECK (strategy IN ('CL1', 'ASMF')),
    CHECK (run_kind = 'STRATEGY_BACKTEST'),
    CHECK (validation_status IN ('ENGINE_ONLY','IN_SAMPLE_ONLY','OOS_AVAILABLE','VALIDATED')),
    CHECK (status IN ('RUNNING','SUCCESS','FAILED')),
    CHECK (typeof(started_at) = 'integer' AND started_at > 0),
    CHECK (completed_at IS NULL OR completed_at >= started_at),
    CHECK (status != 'SUCCESS' OR completed_at IS NOT NULL),
    CHECK (date(start_date) = start_date AND date(end_date) = end_date AND start_date <= end_date),
    CHECK (typeof(universe_size) = 'integer' AND universe_size > 0),
    CHECK (json_valid(symbols_json) AND json_type(symbols_json) = 'array'),
    CHECK (initial_capital > 0),
    CHECK (final_equity IS NULL OR final_equity >= 0),
    CHECK (typeof(trade_count) = 'integer' AND trade_count >= 0),
    CHECK (typeof(open_position_count) = 'integer' AND open_position_count >= 0),
    CHECK (longest_losing_streak IS NULL OR (typeof(longest_losing_streak) = 'integer' AND longest_losing_streak >= 0)),
    CHECK (json_valid(config_json) AND json_type(config_json) = 'object'),
    CHECK (json_valid(warnings_json) AND json_type(warnings_json) = 'array'),
    CHECK (typeof(created_at) = 'integer' AND created_at > 0)
)
"""

BACKTEST_RUNS_LATEST_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy_status_completed
ON backtest_runs(strategy, status, completed_at DESC)
"""

