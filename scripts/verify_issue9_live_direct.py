import os
import sys
import sqlite3
from datetime import date
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv()

from runtime.coverage_factory import connection_factory_from_env
from asmf_data.scoring import fundamental_score
from asmf_data.store import latest_financial_reports
from data.models import OHLCVBar
from strategy.technical_strategies import evaluate_asmf

conn = connection_factory_from_env()()
conn.row_factory = sqlite3.Row

print('=================================================================')
print('TEST LIVE ISSUE 9: KIEM TRA ASMF TANG 2 TREN DU LIEU THAT (LIVE DB)')
print('=================================================================')

today = date(2026, 9, 22)

for sym in ['FPT', 'VIC']:
    reports = latest_financial_reports(conn, sym, as_of=today)
    print(f'\n--- {sym} ---')
    print(f'So ky BCTC point-in-time co san trong financial_reports: {len(reports)} ky')
    for r in reports[:4]:
        print(f'  Period: {r[" report_period\]} | PublicDate: {r[\public_date\]} | Rev: {r[\revenue\]:,.0f} | Profit: {r[\net_profit\]:,.0f}')
 
 score = fundamental_score(conn, sym, as_of=today)
 print(f'-> ASMF fundamental_score as_of {today}: {score}/100')
 
 # Kiem tra point-in-time safety boundary voi ngay truoc lag 45d
 # 2026Q2 period end = 2026-06-30 -> est public date = 2026-08-14
 rep_before = latest_financial_reports(conn, sym, as_of=date(2026, 8, 13))
 print(f'Point-in-time boundary check (as_of 2026-08-13, truoc 45d lag): {len(rep_before)} ky (KHONG BI LOOK-AHEAD)')
 assert len(rep_before) == len(reports) - 1, 'Q2-2026 phai bi an truoc ngay 2026-08-14'
 
 rep_after = latest_financial_reports(conn, sym, as_of=date(2026, 8, 14))
 print(f'Point-in-time boundary check (as_of 2026-08-14, ngay 45d lag): {len(rep_after)} ky (DA DUOC MO)')
 assert len(rep_after) == len(reports), 'Q2-2026 phai xuat hien tu ngay 2026-08-14'

conn.close()
print('\n-> TAT CA KIEM TRA LIVE TREN DB THAT DA PASS 100%!')
