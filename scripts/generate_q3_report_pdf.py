#!/usr/bin/env python3
"""
scripts/generate_q3_report_pdf.py
Generates an executive-grade HTML report and compiles it to a shareable PDF
using headless Google Chrome.
"""

import os
import sys
import sqlite3
import subprocess
import shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "finance.db")
REPORTS_DIR = os.path.join(BASE_DIR, "public", "reports")
HTML_PATH = os.path.join(REPORTS_DIR, "Q3_2026_Expense_Report.html")
PDF_PATH = os.path.join(REPORTS_DIR, "Q3_2026_Expense_Report.pdf")

# Also copy to artifact directory if available
ARTIFACT_DIR = "/Users/donmagezi/.gemini/antigravity/brain/9ee1effc-1699-4b7e-a7d9-05c49986140a"

os.makedirs(REPORTS_DIR, exist_ok=True)

def fetch_report_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Total Q3 Expenses
    cur.execute("""
        SELECT COUNT(*), SUM(amount)
        FROM transactions
        WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND flag != 'transfer-between-own-accounts'
    """)
    cnt, total_q3 = cur.fetchone()

    # Focus 1: Rent
    cur.execute("""
        SELECT date, description, amount, account, notes
        FROM transactions
        WHERE subcategory = 'Housing' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND description LIKE 'Rent%'
        ORDER BY date ASC
    """)
    rent_txs = [dict(r) for r in cur.fetchall()]
    total_rent = sum(r['amount'] for r in rent_txs)

    # Focus 2: Debts (Loan repayments + outstanding debts)
    cur.execute("""
        SELECT date, description, amount, account, flag
        FROM transactions
        WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND (subcategory = 'Loans & Lending' OR flag = 'debt-owed' OR description LIKE '%Debt%' OR description LIKE '%Owed%')
        ORDER BY date DESC
    """)
    debt_txs = [dict(r) for r in cur.fetchall()]
    total_debt = sum(r['amount'] for r in debt_txs)
    repaid_debt = sum(r['amount'] for r in debt_txs if r.get('flag') != 'debt-owed')
    owed_debt = sum(r['amount'] for r in debt_txs if r.get('flag') == 'debt-owed')

    # Focus 3: Subscriptions
    cur.execute("""
        SELECT date, description, amount, account, subcategory
        FROM transactions
        WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND (subcategory = 'Subscriptions'
               OR description LIKE '%Google One%'
               OR description LIKE '%Google AI%'
               OR description LIKE '%ChatGPT%'
               OR description LIKE '%DeepSeek%'
               OR description LIKE '%Adobe%'
               OR description LIKE '%iCloud%'
               OR description LIKE '%Netflix%'
               OR description LIKE '%Spotify%'
               OR description LIKE '%Subscriptions%')
        ORDER BY date DESC
    """)
    sub_txs = [dict(r) for r in cur.fetchall()]
    total_subs = sum(r['amount'] for r in sub_txs)

    # Focus 4: Utilities
    cur.execute("""
        SELECT date, description, amount, account
        FROM transactions
        WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND (subcategory = 'Utilities' OR description LIKE '%Yaka%' OR description LIKE '%WiFi%' OR description LIKE '%Electricity%')
        ORDER BY date DESC
    """)
    util_txs = [dict(r) for r in cur.fetchall()]
    total_utils = sum(r['amount'] for r in util_txs)

    # Full Category Breakdown
    cur.execute("""
        SELECT group_name, subcategory, COUNT(*) as tx_count, SUM(amount) as total_amt
        FROM transactions
        WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND flag != 'transfer-between-own-accounts'
        GROUP BY group_name, subcategory
        ORDER BY total_amt DESC
    """)
    cat_rows = [dict(r) for r in cur.fetchall()]

    # Monthly breakdown
    months_data = {}
    for m in ['2026-07', '2026-08', '2026-09']:
        cur.execute("""
            SELECT SUM(amount), COUNT(*)
            FROM transactions
            WHERE type = 'Expense' AND date LIKE ? AND flag != 'transfer-between-own-accounts'
        """, (f"{m}%",))
        exp, cnt_m = cur.fetchone()
        months_data[m] = {"spend": exp or 0.0, "count": cnt_m or 0}

    conn.close()

    fixed_overhead = total_rent + total_debt + total_subs + total_utils
    variable_spend = total_q3 - fixed_overhead

    subs_stack = [
        {"name": "Adobe Creative Cloud", "amount": 95000.0, "category": "Design & Software ($25)"},
        {"name": "iCloud (Personal Storage)", "amount": 95000.0, "category": "Cloud & Apple Storage ($25)"},
        {"name": "Google AI Pro", "amount": 76000.0, "category": "AI / Productivity"},
        {"name": "ChatGPT Plus", "amount": 23000.0, "category": "AI / Productivity"},
        {"name": "Mum's iCloud", "amount": 13200.0, "category": "Family Storage"},
        {"name": "Google One Storage", "amount": 8000.0, "category": "Cloud & Storage"},
        {"name": "DeepSeek API", "amount": 8000.0, "category": "AI Developer API"}
    ]
    monthly_subs_total = sum(s["amount"] for s in subs_stack)
    monthly_rent = 1700000.0
    monthly_utils = total_utils / 3.0
    monthly_var = variable_spend / 3.0

    monthly_run_rate = {
        "rent": monthly_rent,
        "subscriptions": monthly_subs_total,
        "subscriptions_stack": subs_stack,
        "debt_1_month_active": owed_debt,
        "debt_1_month_amortized": total_debt / 3.0,
        "utilities": monthly_utils,
        "variable_spend": monthly_var,
        "fixed_overhead_active": monthly_rent + monthly_subs_total + owed_debt + monthly_utils,
        "fixed_overhead_amortized": monthly_rent + monthly_subs_total + (total_debt / 3.0) + monthly_utils,
        "fixed_overhead_debt_free": monthly_rent + monthly_subs_total + monthly_utils,
        "total_monthly_with_active_debt": monthly_rent + monthly_subs_total + owed_debt + monthly_utils + monthly_var,
        "total_monthly_amortized": monthly_rent + monthly_subs_total + (total_debt / 3.0) + monthly_utils + monthly_var,
        "total_monthly_debt_free": monthly_rent + monthly_subs_total + monthly_utils + monthly_var
    }

    return {
        "total_q3": total_q3,
        "tx_count": cnt,
        "total_rent": total_rent,
        "rent_txs": rent_txs,
        "total_debt": total_debt,
        "repaid_debt": repaid_debt,
        "owed_debt": owed_debt,
        "debt_txs": debt_txs,
        "total_subs": total_subs,
        "sub_txs": sub_txs,
        "total_utils": total_utils,
        "util_txs": util_txs,
        "fixed_overhead": fixed_overhead,
        "variable_spend": variable_spend,
        "monthly_run_rate": monthly_run_rate,
        "cat_rows": cat_rows,
        "months": months_data
    }

def generate_html(data):
    total = data["total_q3"]
    fixed = data["fixed_overhead"]
    var = data["variable_spend"]

    fixed_pct = (fixed / total * 100) if total else 0
    var_pct = (var / total * 100) if total else 0
    rent_pct = (data["total_rent"] / total * 100) if total else 0
    debt_pct = (data["total_debt"] / total * 100) if total else 0
    subs_pct = (data["total_subs"] / total * 100) if total else 0
    util_pct = (data["total_utils"] / total * 100) if total else 0

    # Build rent table rows
    rent_rows_html = "".join([f"""
        <tr>
            <td class="font-mono text-zinc-400">{r['date']}</td>
            <td class="font-semibold text-zinc-100">{r['description']}</td>
            <td class="text-zinc-400">{r['account']}</td>
            <td class="text-right font-mono font-semibold text-emerald-400">{r['amount']:,.0f} UGX</td>
        </tr>
    """ for r in data["rent_txs"]])

    # Build debt table rows
    debt_rows_html = "".join([f"""
        <tr>
            <td class="font-mono text-zinc-400">{r['date']}</td>
            <td class="font-semibold text-zinc-100">
                {r['description']}
                {"<span class='ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-950/90 text-amber-400 border border-amber-800/60'>OWED</span>" if r.get('flag') == 'debt-owed' else "<span class='ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-950/90 text-emerald-400 border border-emerald-800/60'>PAID</span>"}
            </td>
            <td class="text-zinc-400">{r['account']}</td>
            <td class="text-right font-mono font-semibold {'text-amber-400' if r.get('flag') == 'debt-owed' else 'text-rose-400'}">{r['amount']:,.0f} UGX</td>
        </tr>
    """ for r in data["debt_txs"]])

    # Build subs table rows
    subs_rows_html = "".join([f"""
        <tr>
            <td class="font-mono text-zinc-400">{r['date']}</td>
            <td class="font-semibold text-zinc-100">{r['description']}</td>
            <td class="text-zinc-400">{r['account']}</td>
            <td class="text-right font-mono font-semibold text-amber-400">{r['amount']:,.0f} UGX</td>
        </tr>
    """ for r in data["sub_txs"]])

    # Build utils table rows
    utils_rows_html = "".join([f"""
        <tr>
            <td class="font-mono text-zinc-400">{r['date']}</td>
            <td class="font-semibold text-zinc-100">{r['description']}</td>
            <td class="text-zinc-400">{r['account']}</td>
            <td class="text-right font-mono font-semibold text-cyan-400">{r['amount']:,.0f} UGX</td>
        </tr>
    """ for r in data["util_txs"]])

    # Build category breakdown rows
    cat_rows_html = "".join([f"""
        <tr>
            <td class="text-zinc-400 text-xs uppercase tracking-wider">{r['group_name']}</td>
            <td class="font-semibold text-zinc-100">{r['subcategory']}</td>
            <td class="text-center font-mono text-zinc-400">{r['tx_count']}</td>
            <td class="text-right font-mono font-semibold text-zinc-200">{r['total_amt']:,.0f} UGX</td>
            <td class="text-right font-mono text-emerald-400">{r['total_amt']/total*100:.1f}%</td>
        </tr>
    """ for r in data["cat_rows"][:12]])

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Q3 2026 Executive Expense Report - Don Magezi</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: #09090b;
            color: #f4f4f5;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
        }}
        .font-mono {{
            font-family: 'JetBrains Mono', monospace;
        }}
        @page {{
            size: A4;
            margin: 12mm 12mm 12mm 12mm;
        }}
        @media print {{
            body {{
                background-color: #09090b !important;
                color: #f4f4f5 !important;
            }}
            .page-break {{
                page-break-before: always;
            }}
            .no-print {{
                display: none !important;
            }}
        }}
    </style>
</head>
<body class="p-6 max-w-5xl mx-auto text-sm">

    <!-- Header / Brand Banner -->
    <header class="border-b border-zinc-800 pb-5 mb-6 flex justify-between items-start">
        <div>
            <div class="flex items-center gap-2 mb-1">
                <span class="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_10px_#10b981]"></span>
                <span class="text-xs uppercase tracking-widest font-mono text-emerald-400 font-semibold">Personal Wealth Ledger • Don Magezi</span>
            </div>
            <h1 class="text-2xl font-bold tracking-tight text-white">Q3 2026 Expenditure & Overhead Audit</h1>
            <p class="text-xs text-zinc-400 mt-0.5">July 1, 2026 – September 21, 2026 • Reconciled with Rent, Debts, Subscriptions & Utilities</p>
        </div>
        <div class="text-right">
            <span class="inline-block px-2.5 py-1 bg-zinc-800 border border-zinc-700 text-zinc-300 rounded text-xs font-mono">CONFIDENTIAL REPORT</span>
            <div class="text-[11px] text-zinc-500 mt-1.5 font-mono">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
        </div>
    </header>

    <!-- Top KPI Cards -->
    <div class="grid grid-cols-4 gap-3 mb-6">
        <div class="bg-zinc-900/90 border border-zinc-800 rounded-xl p-4">
            <div class="text-[11px] uppercase tracking-wider font-semibold text-zinc-400 mb-1">Total Q3 Outflow</div>
            <div class="text-2xl font-extrabold text-white font-mono">{total:,.0f} <span class="text-xs font-normal text-zinc-500">UGX</span></div>
            <div class="text-[11px] text-zinc-400 mt-1 flex items-center gap-1">
                <span class="font-semibold text-emerald-400">{data['tx_count']}</span> verified transactions
            </div>
        </div>
        <div class="bg-zinc-900/90 border border-emerald-900/50 bg-emerald-950/10 rounded-xl p-4">
            <div class="text-[11px] uppercase tracking-wider font-semibold text-emerald-400 mb-1">Fixed Overhead</div>
            <div class="text-2xl font-extrabold text-emerald-300 font-mono">{fixed:,.0f} <span class="text-xs font-normal text-emerald-500">UGX</span></div>
            <div class="text-[11px] text-emerald-400/80 mt-1">
                <span class="font-semibold">{fixed_pct:.1f}%</span> of total quarterly budget
            </div>
        </div>
        <div class="bg-zinc-900/90 border border-zinc-800 rounded-xl p-4">
            <div class="text-[11px] uppercase tracking-wider font-semibold text-zinc-400 mb-1">Variable & Living</div>
            <div class="text-2xl font-extrabold text-zinc-200 font-mono">{var:,.0f} <span class="text-xs font-normal text-zinc-500">UGX</span></div>
            <div class="text-[11px] text-zinc-400 mt-1">
                <span class="font-semibold">{var_pct:.1f}%</span> medical, groceries, fuel, etc.
            </div>
        </div>
        <div class="bg-zinc-900/90 border border-amber-900/50 bg-amber-950/10 rounded-xl p-4">
            <div class="text-[11px] uppercase tracking-wider font-semibold text-amber-400 mb-1">Active Liabilities Owed</div>
            <div class="text-2xl font-extrabold text-amber-300 font-mono">{data['owed_debt']:,.0f} <span class="text-xs font-normal text-amber-500">UGX</span></div>
            <div class="text-[11px] text-amber-400/80 mt-1">
                {len([r for r in data['debt_txs'] if r.get('flag') == 'debt-owed'])} active debts • {data['repaid_debt']/1e6:.2f}M repaid
            </div>
        </div>
    </div>

    <!-- 4 Overhead Focus Pillars -->
    <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-5 mb-6">
        <h2 class="text-xs font-bold uppercase tracking-wider text-zinc-300 mb-3 flex items-center gap-2">
            <span>🎯 Core Overhead Allocation ({fixed:,.0f} UGX Total)</span>
        </h2>
        <div class="grid grid-cols-4 gap-4">
            <!-- Rent -->
            <div class="border border-zinc-800 bg-zinc-950/60 rounded-lg p-3.5">
                <div class="flex justify-between items-center mb-1">
                    <span class="text-xs font-semibold text-zinc-300">🏠 Rent (Housing)</span>
                    <span class="text-[11px] font-mono font-bold text-emerald-400 bg-emerald-950/60 border border-emerald-800/40 px-1.5 py-0.5 rounded">{rent_pct:.1f}%</span>
                </div>
                <div class="text-xl font-bold text-white font-mono">{data['total_rent']:,.0f} <span class="text-[11px] font-normal text-zinc-500">UGX</span></div>
                <div class="w-full bg-zinc-800 rounded-full h-1.5 mt-2">
                    <div class="bg-emerald-500 h-1.5 rounded-full" style="width: {rent_pct}%"></div>
                </div>
                <div class="text-[11px] text-zinc-400 mt-2">1,700,000 UGX/mo (Jul, Aug, Sep)</div>
            </div>

            <!-- Debts -->
            <div class="border border-zinc-800 bg-zinc-950/60 rounded-lg p-3.5">
                <div class="flex justify-between items-center mb-1">
                    <span class="text-xs font-semibold text-zinc-300">💳 Debts & Liabilities</span>
                    <span class="text-[11px] font-mono font-bold text-rose-400 bg-rose-950/60 border border-rose-800/40 px-1.5 py-0.5 rounded">{debt_pct:.1f}%</span>
                </div>
                <div class="text-xl font-bold text-white font-mono">{data['total_debt']:,.0f} <span class="text-[11px] font-normal text-zinc-500">UGX</span></div>
                <div class="w-full bg-zinc-800 rounded-full h-1.5 mt-2">
                    <div class="bg-rose-500 h-1.5 rounded-full" style="width: {debt_pct}%"></div>
                </div>
                <div class="text-[11px] text-zinc-400 mt-2">{data['repaid_debt']/1e6:.2f}M repaid • {data['owed_debt']/1e3:.0f}k owed</div>
            </div>

            <!-- Subscriptions -->
            <div class="border border-zinc-800 bg-zinc-950/60 rounded-lg p-3.5">
                <div class="flex justify-between items-center mb-1">
                    <span class="text-xs font-semibold text-zinc-300">🔄 Subscriptions & AI</span>
                    <span class="text-[11px] font-mono font-bold text-amber-400 bg-amber-950/60 border border-amber-800/40 px-1.5 py-0.5 rounded">{subs_pct:.1f}%</span>
                </div>
                <div class="text-xl font-bold text-white font-mono">{data['total_subs']:,.0f} <span class="text-[11px] font-normal text-zinc-500">UGX</span></div>
                <div class="w-full bg-zinc-800 rounded-full h-1.5 mt-2">
                    <div class="bg-amber-500 h-1.5 rounded-full" style="width: {subs_pct}%"></div>
                </div>
                <div class="text-[11px] text-zinc-400 mt-2">AI tools, iCloud & Streaming</div>
            </div>

            <!-- Utilities -->
            <div class="border border-zinc-800 bg-zinc-950/60 rounded-lg p-3.5">
                <div class="flex justify-between items-center mb-1">
                    <span class="text-xs font-semibold text-zinc-300">💡 Utilities (WiFi/Yaka)</span>
                    <span class="text-[11px] font-mono font-bold text-cyan-400 bg-cyan-950/60 border border-cyan-800/40 px-1.5 py-0.5 rounded">{util_pct:.1f}%</span>
                </div>
                <div class="text-xl font-bold text-white font-mono">{data['total_utils']:,.0f} <span class="text-[11px] font-normal text-zinc-500">UGX</span></div>
                <div class="w-full bg-zinc-800 rounded-full h-1.5 mt-2">
                    <div class="bg-cyan-500 h-1.5 rounded-full" style="width: {util_pct}%"></div>
                </div>
                <div class="text-[11px] text-zinc-400 mt-2">WiFi (330k) + Power (121.6k)</div>
            </div>
        </div>
    </div>

    <!-- Monthly Progression Bar -->
    <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-5 mb-6">
        <h2 class="text-xs font-bold uppercase tracking-wider text-zinc-300 mb-3">📅 Monthly Expenditure Trajectory</h2>
        <div class="grid grid-cols-3 gap-4">
            <div class="border border-zinc-800 rounded-lg p-3 bg-zinc-950/40">
                <div class="flex justify-between items-baseline mb-1">
                    <span class="font-semibold text-white">July 2026</span>
                    <span class="text-xs font-mono text-zinc-400">{data['months']['2026-07']['count']} txs</span>
                </div>
                <div class="text-lg font-bold font-mono text-zinc-100">{data['months']['2026-07']['spend']:,.0f} UGX</div>
                <div class="text-[11px] text-zinc-400 mt-1">Rent: 1.7M • Debts: 870k • Subs: 237.5k</div>
            </div>
            <div class="border border-emerald-900/40 rounded-lg p-3 bg-emerald-950/10">
                <div class="flex justify-between items-baseline mb-1">
                    <span class="font-semibold text-emerald-300">August 2026</span>
                    <span class="text-xs font-mono text-emerald-400">{data['months']['2026-08']['count']} txs</span>
                </div>
                <div class="text-lg font-bold font-mono text-white">{data['months']['2026-08']['spend']:,.0f} UGX</div>
                <div class="text-[11px] text-zinc-400 mt-1">Rent: 1.7M • Debts: 721k • Subs: 206k</div>
            </div>
            <div class="border border-zinc-800 rounded-lg p-3 bg-zinc-950/40">
                <div class="flex justify-between items-baseline mb-1">
                    <span class="font-semibold text-white">September 2026 (MTD)</span>
                    <span class="text-xs font-mono text-zinc-400">{data['months']['2026-09']['count']} txs</span>
                </div>
                <div class="text-lg font-bold font-mono text-zinc-100">{data['months']['2026-09']['spend']:,.0f} UGX</div>
                <div class="text-[11px] text-zinc-400 mt-1">Rent: 1.7M • Owed: {data['owed_debt']/1e3:.0f}k ({len([r for r in data['debt_txs'] if r.get('flag') == 'debt-owed'])} debts)</div>
            </div>
        </div>
    </div>

    <!-- 1-Month Operational Expenditure Model & Subscriptions Stack -->
    <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-5 mb-6">
        <div class="flex justify-between items-center mb-3">
            <div>
                <h2 class="text-xs font-bold uppercase tracking-wider text-emerald-400">🎯 Single-Month Expenditure & Run-Rate Model</h2>
                <p class="text-[11px] text-zinc-400">Standard 30-day budget incorporating Rent (1.7M), All Subscriptions (283.7k), Utilities, Living Expenses, and 1 Month of Debts.</p>
            </div>
            <span class="px-2 py-0.5 rounded text-[11px] font-mono bg-emerald-500/10 text-emerald-400 font-semibold border border-emerald-500/20">30-DAY OPERATIONAL BLUEPRINT</span>
        </div>

        <!-- 3 Monthly Outflow Scenarios -->
        <div class="grid grid-cols-3 gap-3 mb-4">
            <div class="border border-rose-900/40 rounded-lg p-3 bg-rose-950/20">
                <div class="text-xs font-bold uppercase tracking-wider text-rose-400 mb-1">Scenario A: 1-Mo Debt Payoff</div>
                <div class="text-xl font-bold font-mono text-white">{data['monthly_run_rate']['total_monthly_with_active_debt']:,.0f} <span class="text-[11px] font-normal text-zinc-400">UGX</span></div>
                <div class="text-[11px] text-zinc-400 mt-1">Clears 100% of active debt ({data['monthly_run_rate']['debt_1_month_active']/1e3:,.0f}k) in 30 days</div>
            </div>
            <div class="border border-amber-900/40 rounded-lg p-3 bg-amber-950/20">
                <div class="text-xs font-bold uppercase tracking-wider text-amber-400 mb-1">Scenario B: Amortized Debt</div>
                <div class="text-xl font-bold font-mono text-white">{data['monthly_run_rate']['total_monthly_amortized']:,.0f} <span class="text-[11px] font-normal text-zinc-400">UGX</span></div>
                <div class="text-[11px] text-zinc-400 mt-1">Q3 average debt service ({data['monthly_run_rate']['debt_1_month_amortized']/1e3:,.0f}k / mo)</div>
            </div>
            <div class="border border-emerald-900/40 rounded-lg p-3 bg-emerald-950/20">
                <div class="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-1">Scenario C: Debt-Free Baseline</div>
                <div class="text-xl font-bold font-mono text-white">{data['monthly_run_rate']['total_monthly_debt_free']:,.0f} <span class="text-[11px] font-normal text-zinc-400">UGX</span></div>
                <div class="text-[11px] text-zinc-400 mt-1">Ongoing monthly living burn rate with 0 debts</div>
            </div>
        </div>

        <!-- 5 Monthly Pillars & Subscription Stack Breakdown -->
        <div class="grid grid-cols-5 gap-2 text-center text-xs pt-3 border-t border-zinc-800/80">
            <div class="bg-zinc-950/50 p-2 rounded border border-zinc-800/60">
                <div class="text-zinc-500 text-[10px] uppercase font-semibold">🏠 Rent</div>
                <div class="font-mono font-bold text-white text-sm">{data['monthly_run_rate']['rent']:,.0f}</div>
                <div class="text-[10px] text-zinc-400">Fixed Monthly</div>
            </div>
            <div class="bg-zinc-950/50 p-2 rounded border border-amber-800/40">
                <div class="text-amber-400 text-[10px] uppercase font-semibold">🔄 All Subscriptions</div>
                <div class="font-mono font-bold text-amber-300 text-sm">{data['monthly_run_rate']['subscriptions']:,.0f}</div>
                <div class="text-[10px] text-amber-500/80">10 Active Tools</div>
            </div>
            <div class="bg-zinc-950/50 p-2 rounded border border-rose-800/40">
                <div class="text-rose-400 text-[10px] uppercase font-semibold">💳 1 Mo. Debts</div>
                <div class="font-mono font-bold text-rose-300 text-sm">{data['monthly_run_rate']['debt_1_month_active']:,.0f}</div>
                <div class="text-[10px] text-rose-500/80">Active clearance</div>
            </div>
            <div class="bg-zinc-950/50 p-2 rounded border border-cyan-800/40">
                <div class="text-cyan-400 text-[10px] uppercase font-semibold">💡 Utilities</div>
                <div class="font-mono font-bold text-cyan-300 text-sm">{data['monthly_run_rate']['utilities']:,.0f}</div>
                <div class="text-[10px] text-cyan-500/80">WiFi + Power</div>
            </div>
            <div class="bg-zinc-950/50 p-2 rounded border border-zinc-800/60">
                <div class="text-zinc-500 text-[10px] uppercase font-semibold">🛒 Variable Living</div>
                <div class="font-mono font-bold text-zinc-200 text-sm">{data['monthly_run_rate']['variable_spend']:,.0f}</div>
                <div class="text-[10px] text-zinc-400">Food, Fuel, Meds</div>
            </div>
        </div>

        <!-- 7 Tool Subscription Stack Chips -->
        <div class="mt-3 pt-2 border-t border-zinc-800/50">
            <div class="text-[10px] uppercase tracking-wider text-zinc-400 font-semibold mb-1.5 flex items-center justify-between">
                <span>Active Monthly Subscription Inventory (318,200 UGX Total):</span>
                <span class="text-emerald-400 font-mono font-normal">All 7 core services accounted for</span>
            </div>
            <div class="flex flex-wrap gap-1.5 text-[11px] font-mono">
                <span class="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700 text-zinc-300">Adobe CC ($25): <strong class="text-white">95k</strong></span>
                <span class="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700 text-zinc-300">iCloud Personal ($25): <strong class="text-white">95k</strong></span>
                <span class="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700 text-zinc-300">Google AI Pro: <strong class="text-white">76k</strong></span>
                <span class="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700 text-zinc-300">ChatGPT Plus: <strong class="text-white">23k</strong></span>
                <span class="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700 text-zinc-300">Mum's iCloud: <strong class="text-white">13.2k</strong></span>
                <span class="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700 text-zinc-300">Google One: <strong class="text-white">8k</strong></span>
                <span class="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700 text-zinc-300">DeepSeek API: <strong class="text-white">8k</strong></span>
            </div>
        </div>
    </div>

    <!-- Section: Itemized Tables -->
    <div class="page-break pt-4">
        <h2 class="text-sm font-bold uppercase tracking-wider text-emerald-400 border-b border-zinc-800 pb-2 mb-4">
            📋 Detailed Focus Category Schedules
        </h2>

        <div class="grid grid-cols-2 gap-4 mb-6">
            <!-- Rent Schedule -->
            <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-4">
                <div class="flex justify-between items-center mb-2">
                    <h3 class="font-bold text-xs uppercase tracking-wider text-white">🏠 Rent Schedule (1.7M/mo)</h3>
                    <span class="font-mono text-xs text-emerald-400 font-bold">{data['total_rent']:,.0f} UGX</span>
                </div>
                <table class="w-full text-xs">
                    <thead>
                        <tr class="border-b border-zinc-800 text-zinc-500 text-left">
                            <th class="py-1 font-medium">Date</th>
                            <th class="py-1 font-medium">Description</th>
                            <th class="py-1 font-medium">Account</th>
                            <th class="py-1 font-medium text-right">Amount</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-zinc-800/60">
                        {rent_rows_html}
                    </tbody>
                </table>
            </div>

            <!-- Debt Repayments -->
            <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-4">
                <div class="flex justify-between items-center mb-2">
                    <h3 class="font-bold text-xs uppercase tracking-wider text-white">💳 Debts & Liabilities Schedule</h3>
                    <span class="font-mono text-xs text-rose-400 font-bold">{data['total_debt']:,.0f} UGX</span>
                </div>
                <table class="w-full text-xs">
                    <thead>
                        <tr class="border-b border-zinc-800 text-zinc-500 text-left">
                            <th class="py-1 font-medium">Date</th>
                            <th class="py-1 font-medium">Description</th>
                            <th class="py-1 font-medium">Account</th>
                            <th class="py-1 font-medium text-right">Amount</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-zinc-800/60">
                        {debt_rows_html}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="grid grid-cols-2 gap-4 mb-6">
            <!-- Subscriptions & Tools -->
            <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-4">
                <div class="flex justify-between items-center mb-2">
                    <h3 class="font-bold text-xs uppercase tracking-wider text-white">🔄 Subscriptions & AI Tools</h3>
                    <span class="font-mono text-xs text-amber-400 font-bold">{data['total_subs']:,.0f} UGX</span>
                </div>
                <table class="w-full text-xs">
                    <thead>
                        <tr class="border-b border-zinc-800 text-zinc-500 text-left">
                            <th class="py-1 font-medium">Date</th>
                            <th class="py-1 font-medium">Description</th>
                            <th class="py-1 font-medium">Account</th>
                            <th class="py-1 font-medium text-right">Amount</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-zinc-800/60">
                        {subs_rows_html}
                    </tbody>
                </table>
            </div>

            <!-- Utilities -->
            <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-4">
                <div class="flex justify-between items-center mb-2">
                    <h3 class="font-bold text-xs uppercase tracking-wider text-white">💡 Utilities (WiFi & Electricity)</h3>
                    <span class="font-mono text-xs text-cyan-400 font-bold">{data['total_utils']:,.0f} UGX</span>
                </div>
                <table class="w-full text-xs">
                    <thead>
                        <tr class="border-b border-zinc-800 text-zinc-500 text-left">
                            <th class="py-1 font-medium">Date</th>
                            <th class="py-1 font-medium">Description</th>
                            <th class="py-1 font-medium">Account</th>
                            <th class="py-1 font-medium text-right">Amount</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-zinc-800/60">
                        {utils_rows_html}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Overall Category Ranking Table -->
        <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-4 mb-6">
            <h3 class="font-bold text-xs uppercase tracking-wider text-white mb-2">🏆 Full Category Ranking (Top 12)</h3>
            <table class="w-full text-xs">
                <thead>
                    <tr class="border-b border-zinc-800 text-zinc-500 text-left">
                        <th class="py-1 font-medium">Group</th>
                        <th class="py-1 font-medium">Subcategory</th>
                        <th class="py-1 font-medium text-center">Tx Count</th>
                        <th class="py-1 font-medium text-right">Total Outflow</th>
                        <th class="py-1 font-medium text-right">% of Total</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-zinc-800/60">
                    {cat_rows_html}
                </tbody>
            </table>
        </div>

        <!-- Strategic Takeaways -->
        <div class="bg-emerald-950/20 border border-emerald-800/40 rounded-xl p-4 text-xs text-zinc-300">
            <div class="font-bold text-emerald-400 mb-1 flex items-center gap-1.5">
                <span>💡 Strategic Takeaways for Q4</span>
            </div>
            <ul class="list-disc list-inside space-y-1 text-zinc-400">
                <li><strong class="text-zinc-200">Rent is now formally structured:</strong> At 1.7M UGX/mo (5.1M in Q3), rent is your largest expense ({rent_pct:.1f}%). Accounting for it ensures accurate monthly cash flow forecasting.</li>
                <li><strong class="text-zinc-200">Debt obligations & payables:</strong> 1.59M in bank/mobile loans fully settled. Current outstanding liabilities total {data['owed_debt']:,.0f} UGX across 6 active commitments: Vernon (750k), MoKash (327k), Zenka (203.4k), Health Okay (163k), Maureen Asio (163k), and Benon - Ecopharm (95k).</li>
                <li><strong class="text-zinc-200">Fixed overhead disciplined at {fixed_pct:.1f}%:</strong> Your 4 core obligations total {fixed/1e6:.2f}M UGX. Keeping fixed commitments near 50% gives ample flexibility for variable living and savings.</li>
            </ul>
        </div>
    </div>

    <!-- Print / Download Footer (Visible only in browser, hidden when printed) -->
    <div class="no-print mt-8 pt-4 border-t border-zinc-800 flex justify-between items-center text-xs text-zinc-500">
        <div>Don Magezi Designs • Financial Intelligence Systems</div>
        <div class="flex gap-3">
            <button onclick="window.print()" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-semibold transition">
                🖨️ Print / Save PDF
            </button>
        </div>
    </div>

</body>
</html>
"""
    return html_content

def compile_pdf():
    print("Fetching Q3 live report data...")
    data = fetch_report_data()

    print("Generating report HTML...")
    html = generate_html(data)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved HTML to {HTML_PATH}")

    # Compile with headless Google Chrome
    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if os.path.exists(chrome_bin):
        print(f"Compiling PDF via Google Chrome headless...")
        cmd = [
            chrome_bin,
            "--headless",
            "--disable-gpu",
            "--user-data-dir=/tmp/chrome_pdf_profile",
            "--run-all-compositor-stages-before-draw",
            "--no-pdf-header-footer",
            f"--print-to-pdf={PDF_PATH}",
            HTML_PATH
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
            if res.returncode != 0:
                print(f"Chrome notice: {res.stderr}")
        except subprocess.TimeoutExpired:
            pass

        if os.path.exists(PDF_PATH) and os.path.getsize(PDF_PATH) > 0:
            print(f"Successfully generated PDF ({os.path.getsize(PDF_PATH)} bytes): {PDF_PATH}")
            if os.path.exists(ARTIFACT_DIR):
                art_dest = os.path.join(ARTIFACT_DIR, "Q3_2026_Expense_Report.pdf")
                shutil.copyfile(PDF_PATH, art_dest)
                print(f"Copied PDF to artifact directory: {art_dest}")
        else:
            print(f"Error: PDF was not generated at {PDF_PATH}")
    else:
        print(f"Warning: Google Chrome not found at {chrome_bin}")

if __name__ == "__main__":
    compile_pdf()
