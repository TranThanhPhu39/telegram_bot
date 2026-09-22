import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import sqlite3
from datetime import date
from asmf_data.scoring import fundamental_score

from runtime.coverage_factory import connection_factory_from_env

factory = connection_factory_from_env()
conn = factory()
conn.row_factory = sqlite3.Row

for symbol in ("FPT", "VIC"):
    reports = conn.execute(
        'SELECT report_period, public_date, revenue, net_profit, equity, total_debt, source '
        'FROM financial_reports WHERE symbol=? ORDER BY report_period DESC',
        (symbol,)
    ).fetchall()

    print(f"\n=== REAL LIVE financial_reports FOR {symbol}: {len(reports)} records ===")
    for r in reports:
        print(f"  Period: {r['report_period']} | PublicDate: {r['public_date']} | Rev: {r['revenue']:,.0f} | Profit: {r['net_profit']:,.0f} | Source: {r['source']}")

    # Check fundamental score with real live data as of today (2026-09-22)
    score = fundamental_score(conn, symbol, as_of=date(2026, 9, 22))
    print(f"=== ASMF fundamental_score for {symbol} as of 2026-09-22: {score} ===")
conn.close()
