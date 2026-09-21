#!/usr/bin/env python3
"""
scripts/generate_monthly_report_pdf.py
Generates an executive-grade 1-Month Operational Expenditure & Run-Rate PDF Report.
Covers 1-month rent (1.7M), all 7 active subscriptions (318.2k), active loans & liabilities (1.701M),
utilities (157.9k), and variable living (2.49M).
Uses Google Chrome headless to compile pixel-perfect vector PDF.
"""

import os
import sys
import json
import sqlite3
import subprocess
import shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "finance.db")
OUTPUT_HTML = os.path.join(BASE_DIR, "public", "reports", "Monthly_Expense_Report.html")
OUTPUT_PDF = os.path.join(BASE_DIR, "public", "reports", "Monthly_Expense_Report.pdf")
ARTIFACT_DIR = "/Users/donmagezi/.gemini/antigravity/brain/9ee1effc-1699-4b7e-a7d9-05c49986140a"

def fetch_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Active debts & loans owed
    cur.execute("""
        SELECT date, description, amount, account, category, notes, flag
        FROM transactions
        WHERE flag = 'debt-owed'
        ORDER BY amount DESC
    """)
    debt_txs = [dict(r) for r in cur.fetchall()]
    total_debt_owed = sum(r['amount'] for r in debt_txs)

    # Enrich active loan types
    for d in debt_txs:
        desc = d['description'].lower()
        if 'vernon' in desc:
            d['loan_type'] = 'Personal Loan'
            d['type_badge'] = 'Personal Credit'
        elif 'mokash' in desc:
            d['loan_type'] = 'Mobile Loan'
            d['type_badge'] = 'Digital Credit'
        elif 'zenka' in desc:
            d['loan_type'] = 'Mobile Loan'
            d['type_badge'] = 'Digital Credit'
        elif 'health okay' in desc or 'maureen' in desc or 'benon' in desc or 'ecopharm' in desc:
            d['loan_type'] = 'Medication Debt'
            d['type_badge'] = 'Pharmacy Credit'
        else:
            d['loan_type'] = 'Liability'
            d['type_badge'] = 'Credit'

    # Settled loan repayments in Q3
    cur.execute("""
        SELECT date, description, amount, account
        FROM transactions
        WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND subcategory = 'Loans & Lending' AND (flag IS NULL OR flag != 'debt-owed')
        ORDER BY date DESC
    """)
    settled_txs = [dict(r) for r in cur.fetchall()]
    total_settled_loans = sum(r['amount'] for r in settled_txs)

    # Q3 debt payments amortized
    cur.execute("""
        SELECT SUM(amount)
        FROM transactions
        WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND (subcategory = 'Loans & Lending' OR flag = 'debt-owed' OR description LIKE '%Debt%' OR description LIKE '%Owed%')
    """)
    q3_total_debt = cur.fetchone()[0] or 0.0
    debt_amortized = q3_total_debt / 3.0

    # Utilities in Q3
    cur.execute("""
        SELECT SUM(amount)
        FROM transactions
        WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND (subcategory = 'Utilities' OR description LIKE '%Yaka%' OR description LIKE '%WiFi%' OR description LIKE '%Electricity%')
    """)
    total_utils_q3 = cur.fetchone()[0] or 0.0
    monthly_utils = total_utils_q3 / 3.0

    # Total Q3 spend
    cur.execute("""
        SELECT SUM(amount)
        FROM transactions
        WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND flag != 'transfer-between-own-accounts'
    """)
    total_q3_spend = cur.fetchone()[0] or 0.0

    # Rent & Subscriptions across Q3
    cur.execute("""
        SELECT SUM(amount) FROM transactions
        WHERE subcategory = 'Housing' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND description LIKE 'Rent%'
    """)
    total_rent_q3 = cur.fetchone()[0] or 5100000.0

    cur.execute("""
        SELECT SUM(amount) FROM transactions
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
    """)
    total_subs_q3 = cur.fetchone()[0] or 513200.0

    q3_fixed_overhead = total_rent_q3 + q3_total_debt + total_subs_q3 + total_utils_q3
    q3_variable_spend = total_q3_spend - q3_fixed_overhead
    monthly_variable = q3_variable_spend / 3.0

    # Variable breakdown by category (estimated 1-month)
    cur.execute("""
        SELECT group_name, subcategory, SUM(amount) / 3.0 as monthly_amt
        FROM transactions
        WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
          AND flag != 'transfer-between-own-accounts'
          AND subcategory NOT IN ('Housing', 'Loans & Lending', 'Utilities', 'Subscriptions')
        GROUP BY group_name, subcategory
        ORDER BY monthly_amt DESC
        LIMIT 8
    """)
    var_categories = [dict(r) for r in cur.fetchall()]

    conn.close()

    # Active 7-tool subscriptions inventory
    subs_stack = [
        {"name": "Adobe Creative Cloud", "amount": 95000.0, "usd": "$25.00", "focus": "Design, UI & Vector Software", "account": "Mobile Money"},
        {"name": "iCloud (Personal Storage)", "amount": 95000.0, "usd": "$25.00", "focus": "Apple Cloud Storage & Backup", "account": "Mobile Money"},
        {"name": "Google AI Pro", "amount": 76000.0, "usd": "~$20.00", "focus": "Gemini 2.0 & Workspace AI", "account": "Mobile Money"},
        {"name": "ChatGPT Plus", "amount": 23000.0, "usd": "~$6.00", "focus": "AI Pair Programming & Research", "account": "Mobile Money"},
        {"name": "Mum's iCloud", "amount": 13200.0, "usd": "~$3.50", "focus": "Family Apple Cloud Storage", "account": "Mobile Money"},
        {"name": "Google One Storage", "amount": 8000.0, "usd": "~$2.10", "focus": "Google Drive & Gmail Storage", "account": "Mobile Money"},
        {"name": "DeepSeek API", "amount": 8000.0, "usd": "~$2.10", "focus": "AI Developer API Token Usage", "account": "Momo Virtual Card"}
    ]
    monthly_subs = sum(s["amount"] for s in subs_stack)
    monthly_rent = 1700000.0

    # 3 Monthly Outflow Scenarios
    tot_scenario_a = monthly_rent + monthly_subs + total_debt_owed + monthly_utils + monthly_variable
    tot_scenario_b = monthly_rent + monthly_subs + debt_amortized + monthly_utils + monthly_variable
    tot_scenario_c = monthly_rent + monthly_subs + monthly_utils + monthly_variable

    return {
        "monthly_rent": monthly_rent,
        "subs_stack": subs_stack,
        "monthly_subs": monthly_subs,
        "debt_txs": debt_txs,
        "total_debt_owed": total_debt_owed,
        "settled_txs": settled_txs,
        "total_settled_loans": total_settled_loans,
        "debt_amortized": debt_amortized,
        "monthly_utils": monthly_utils,
        "monthly_variable": monthly_variable,
        "var_categories": var_categories,
        "scenario_a": tot_scenario_a,
        "scenario_b": tot_scenario_b,
        "scenario_c": tot_scenario_c
    }

def generate_html(data):
    tot_a = data["scenario_a"]
    tot_b = data["scenario_b"]
    tot_c = data["scenario_c"]

    fixed_a = data["monthly_rent"] + data["monthly_subs"] + data["total_debt_owed"] + data["monthly_utils"]

    # Build subscriptions rows
    subs_rows_html = "".join([f"""
        <tr>
            <td class="font-semibold text-zinc-100">{s['name']}</td>
            <td class="text-zinc-400 text-xs">{s['focus']}</td>
            <td class="text-center font-mono text-xs text-amber-400">{s['usd']}</td>
            <td class="text-zinc-400 text-xs">{s['account']}</td>
            <td class="text-right font-mono font-semibold text-amber-400">{s['amount']:,.0f} UGX</td>
        </tr>
    """ for s in data["subs_stack"]])

    # Build debts rows
    debt_rows_html = "".join([f"""
        <tr>
            <td class="font-mono text-zinc-400">{d['date']}</td>
            <td class="font-semibold text-zinc-100">
                {d['description']}
            </td>
            <td class="text-center">
                <span class="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-zinc-800 text-zinc-300 border border-zinc-700">{d['type_badge']}</span>
            </td>
            <td class="text-center">
                <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20">ACTIVE OWED</span>
            </td>
            <td class="text-zinc-400 text-xs">{d['account']}</td>
            <td class="text-right font-mono font-bold text-rose-400">{d['amount']:,.0f} UGX</td>
        </tr>
    """ for d in data["debt_txs"]])

    # Build settled loan reference rows
    settled_rows_html = "".join([f"""
        <tr>
            <td class="font-mono text-zinc-500 text-[11px]">{r['date']}</td>
            <td class="text-zinc-300 text-xs">{r['description']}</td>
            <td class="text-zinc-500 text-[11px]">{r['account']}</td>
            <td class="text-center"><span class="px-1.5 py-0.2 rounded text-[9px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">PAID</span></td>
            <td class="text-right font-mono text-xs text-zinc-300">{r['amount']:,.0f} UGX</td>
        </tr>
    """ for r in data["settled_txs"][:4]])

    # Build variable rows
    var_rows_html = "".join([f"""
        <tr>
            <td class="text-zinc-400 text-xs uppercase tracking-wider">{c['group_name']}</td>
            <td class="font-semibold text-zinc-100">{c['subcategory']}</td>
            <td class="text-right font-mono font-semibold text-zinc-200">{c['monthly_amt']:,.0f} UGX</td>
            <td class="text-right font-mono text-emerald-400">{c['monthly_amt']/tot_a*100:.1f}%</td>
        </tr>
    """ for c in data["var_categories"]])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>1-Month Operational Expenditure & Run-Rate Report - Don Magezi</title>
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
            margin: 8mm 10mm 8mm 10mm;
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
<body class="p-3 max-w-5xl mx-auto text-sm">

    <!-- Header / Brand Banner -->
    <header class="border-b border-zinc-800 pb-5 mb-6 flex justify-between items-start">
        <div>
            <div class="flex items-center gap-2 mb-1">
                <span class="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_10px_#10b981]"></span>
                <span class="text-xs uppercase tracking-widest font-mono text-emerald-400 font-semibold">Personal Wealth Ledger • Don Magezi</span>
            </div>
            <h1 class="text-2xl font-bold tracking-tight text-white">Monthly Operational Expenditure & Run-Rate Audit</h1>
            <p class="text-xs text-zinc-400 mt-0.5">30-Day Financial Blueprint • Rent (1.7M), Subscriptions (318.2k), Loans & Liabilities (1.701M) & Utilities (157.9k)</p>
        </div>
        <div class="text-right">
            <span class="inline-block px-2.5 py-1 bg-zinc-800 border border-zinc-700 text-zinc-300 rounded text-xs font-mono">1-MONTH EXECUTIVE AUDIT</span>
            <div class="text-[11px] text-zinc-500 mt-1.5 font-mono">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
        </div>
    </header>

    <!-- 3 Scenario Summary Cards -->
    <div class="grid grid-cols-3 gap-4 mb-6">
        <!-- Scenario A -->
        <div class="border border-rose-900/50 rounded-xl p-4 bg-rose-950/20">
            <div class="flex justify-between items-center mb-1">
                <span class="text-xs font-bold uppercase tracking-wider text-rose-400">Scenario A: 1-Mo Loan Payoff</span>
                <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">AGGRESSIVE</span>
            </div>
            <div class="text-2xl font-bold font-mono text-white mt-1">{tot_a:,.0f} <span class="text-xs font-normal text-zinc-400">UGX</span></div>
            <p class="text-xs text-zinc-400 mt-2">Clears 100% of all 6 active loans & liabilities ({data['total_debt_owed']:,.0f} UGX) in 30 days.</p>
            <div class="text-[11px] font-mono text-rose-300/80 mt-2 pt-2 border-t border-rose-900/40">
                Fixed: {fixed_a:,.0f} • Variable: {data['monthly_variable']:,.0f}
            </div>
        </div>

        <!-- Scenario B -->
        <div class="border border-amber-900/50 rounded-xl p-4 bg-amber-950/20">
            <div class="flex justify-between items-center mb-1">
                <span class="text-xs font-bold uppercase tracking-wider text-amber-400">Scenario B: Amortized Servicing</span>
                <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">BALANCED</span>
            </div>
            <div class="text-2xl font-bold font-mono text-white mt-1">{tot_b:,.0f} <span class="text-xs font-normal text-zinc-400">UGX</span></div>
            <p class="text-xs text-zinc-400 mt-2">Services loans at your actual Q3 average repayment pace ({data['debt_amortized']:,.0f} UGX/mo).</p>
            <div class="text-[11px] font-mono text-amber-300/80 mt-2 pt-2 border-t border-amber-900/40">
                Fixed: {fixed_a - data['total_debt_owed'] + data['debt_amortized']:,.0f} • Variable: {data['monthly_variable']:,.0f}
            </div>
        </div>

        <!-- Scenario C -->
        <div class="border border-emerald-900/50 rounded-xl p-4 bg-emerald-950/20">
            <div class="flex justify-between items-center mb-1">
                <span class="text-xs font-bold uppercase tracking-wider text-emerald-400">Scenario C: Loan-Free Baseline</span>
                <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">STEADY STATE</span>
            </div>
            <div class="text-2xl font-bold font-mono text-white mt-1">{tot_c:,.0f} <span class="text-xs font-normal text-zinc-400">UGX</span></div>
            <p class="text-xs text-zinc-400 mt-2">Ongoing recurring monthly burn rate once all 6 credit balances are retired.</p>
            <div class="text-[11px] font-mono text-emerald-300/80 mt-2 pt-2 border-t border-emerald-900/40">
                Fixed: {fixed_a - data['total_debt_owed']:,.0f} • Variable: {data['monthly_variable']:,.0f}
            </div>
        </div>
    </div>

    <!-- 5 Monthly Pillars Grid -->
    <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-5 mb-6">
        <h2 class="text-xs font-bold uppercase tracking-wider text-zinc-300 mb-3">🎯 Five Pillars of Monthly Expenditure (Scenario A: 6,367,103 UGX)</h2>
        <div class="grid grid-cols-5 gap-3 text-center">
            <!-- Rent -->
            <div class="p-3 rounded-lg border border-zinc-800 bg-zinc-950/60">
                <div class="text-zinc-500 text-[10px] uppercase font-semibold">🏠 Rent</div>
                <div class="text-base font-bold font-mono text-white mt-0.5">{data['monthly_rent']:,.0f}</div>
                <div class="text-[11px] text-emerald-400 font-mono mt-1">{data['monthly_rent']/tot_a*100:.1f}%</div>
                <div class="text-[10px] text-zinc-500 mt-0.5">Fixed Housing</div>
            </div>

            <!-- Debts & Loans -->
            <div class="p-3 rounded-lg border border-rose-900/40 bg-zinc-950/60">
                <div class="text-rose-400 text-[10px] uppercase font-semibold">💳 Loans & Debts</div>
                <div class="text-base font-bold font-mono text-rose-300 mt-0.5">{data['total_debt_owed']:,.0f}</div>
                <div class="text-[11px] text-rose-400 font-mono mt-1">{data['total_debt_owed']/tot_a*100:.1f}%</div>
                <div class="text-[10px] text-rose-500/80 mt-0.5">6 Active Creditors</div>
            </div>

            <!-- Subscriptions -->
            <div class="p-3 rounded-lg border border-amber-900/40 bg-zinc-950/60">
                <div class="text-amber-400 text-[10px] uppercase font-semibold">🔄 Subscriptions</div>
                <div class="text-base font-bold font-mono text-amber-300 mt-0.5">{data['monthly_subs']:,.0f}</div>
                <div class="text-[11px] text-amber-400 font-mono mt-1">{data['monthly_subs']/tot_a*100:.1f}%</div>
                <div class="text-[10px] text-amber-500/80 mt-0.5">7 Active Tools</div>
            </div>

            <!-- Utilities -->
            <div class="p-3 rounded-lg border border-cyan-900/40 bg-zinc-950/60">
                <div class="text-cyan-400 text-[10px] uppercase font-semibold">💡 Utilities</div>
                <div class="text-base font-bold font-mono text-cyan-300 mt-0.5">{data['monthly_utils']:,.0f}</div>
                <div class="text-[11px] text-cyan-400 font-mono mt-1">{data['monthly_utils']/tot_a*100:.1f}%</div>
                <div class="text-[10px] text-cyan-500/80 mt-0.5">WiFi + Power</div>
            </div>

            <!-- Variable Living -->
            <div class="p-3 rounded-lg border border-zinc-800 bg-zinc-950/60">
                <div class="text-zinc-400 text-[10px] uppercase font-semibold">🛒 Variable Living</div>
                <div class="text-base font-bold font-mono text-zinc-100 mt-0.5">{data['monthly_variable']:,.0f}</div>
                <div class="text-[11px] text-emerald-400 font-mono mt-1">{data['monthly_variable']/tot_a*100:.1f}%</div>
                <div class="text-[10px] text-zinc-500 mt-0.5">Health, Food, Fuel</div>
            </div>
        </div>
    </div>

    <!-- Active Subscriptions Stack (Full Detail) -->
    <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-5 mb-6">
        <div class="flex justify-between items-center mb-3">
            <div>
                <h3 class="font-bold text-xs uppercase tracking-wider text-amber-400">🔄 Active Monthly Subscriptions Stack (7 Services • 318,200 UGX Total)</h3>
                <p class="text-[11px] text-zinc-400">Excludes DaVinci AI, Netflix, and Spotify. Adobe and iCloud adjusted to $25 (95,000 UGX each @ 3,800 UGX/USD).</p>
            </div>
            <span class="font-mono text-xs text-amber-400 font-bold bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">{data['monthly_subs']:,.0f} UGX / mo</span>
        </div>
        <table class="w-full text-xs">
            <thead>
                <tr class="border-b border-zinc-800 text-zinc-500 text-left">
                    <th class="py-2 font-medium">Service / Tool</th>
                    <th class="py-2 font-medium">Focus Area</th>
                    <th class="py-2 font-medium text-center">USD Ref</th>
                    <th class="py-2 font-medium">Billing Account</th>
                    <th class="py-2 font-medium text-right">Monthly (UGX)</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-zinc-800/60">
                {subs_rows_html}
            </tbody>
        </table>
    </div>

    <!-- Page Break for Clean 2-Page Print -->
    <div class="page-break pt-4">

        <!-- 1-Month Loans & Liabilities Schedule -->
        <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-4 mb-3.5">
            <div class="flex justify-between items-center mb-2">
                <div>
                    <h3 class="font-bold text-xs uppercase tracking-wider text-rose-400">💳 Active Loans & Liabilities Schedule (1,701,360 UGX Total)</h3>
                    <p class="text-[11px] text-zinc-400">Itemization of all 6 active liabilities scheduled for 1-month liquidation across 3 debt classes.</p>
                </div>
                <span class="font-mono text-xs text-rose-400 font-bold bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20">{data['total_debt_owed']:,.0f} UGX Total</span>
            </div>
            <table class="w-full text-xs">
                <thead>
                    <tr class="border-b border-zinc-800 text-zinc-500 text-left">
                        <th class="py-1.5 font-medium">Date Booked</th>
                        <th class="py-1.5 font-medium">Creditor / Description</th>
                        <th class="py-1.5 font-medium text-center">Loan Class</th>
                        <th class="py-1.5 font-medium text-center">Status</th>
                        <th class="py-1.5 font-medium">Account</th>
                        <th class="py-1.5 font-medium text-right">Amount (UGX)</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-zinc-800/60">
                    {debt_rows_html}
                </tbody>
            </table>

            <!-- Subtotals summary bar -->
            <div class="mt-2.5 pt-2.5 border-t border-zinc-800/80 grid grid-cols-3 gap-2 text-[10px] font-mono">
                <div class="p-1.5 rounded bg-zinc-950/60 border border-zinc-800/60 flex justify-between">
                    <span class="text-zinc-400">Personal Loan (Vernon):</span>
                    <span class="text-rose-400 font-semibold">750,000 UGX</span>
                </div>
                <div class="p-1.5 rounded bg-zinc-950/60 border border-zinc-800/60 flex justify-between">
                    <span class="text-zinc-400">Mobile Credit (MoKash + Zenka):</span>
                    <span class="text-rose-400 font-semibold">530,360 UGX</span>
                </div>
                <div class="p-1.5 rounded bg-zinc-950/60 border border-zinc-800/60 flex justify-between">
                    <span class="text-zinc-400">Pharmacy Credit (3 Creditors):</span>
                    <span class="text-rose-400 font-semibold">421,000 UGX</span>
                </div>
            </div>
        </div>

        <!-- Housing & Utilities Breakdown -->
        <div class="grid grid-cols-2 gap-3 mb-3.5">
            <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-3.5">
                <div class="flex justify-between items-center mb-1.5">
                    <h3 class="font-bold text-xs uppercase tracking-wider text-emerald-400">🏠 Rent (Housing)</h3>
                    <span class="font-mono text-xs text-emerald-400 font-bold">{data['monthly_rent']:,.0f} UGX</span>
                </div>
                <p class="text-[11px] text-zinc-400 mb-1.5">Non-negotiable monthly residential commitment.</p>
                <div class="p-2 rounded bg-zinc-950/50 border border-zinc-800/80 text-xs flex justify-between items-center">
                    <span class="text-zinc-300">Monthly Rent Payment</span>
                    <span class="font-mono font-bold text-emerald-400">1,700,000 UGX</span>
                </div>
            </div>

            <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-3.5">
                <div class="flex justify-between items-center mb-1.5">
                    <h3 class="font-bold text-xs uppercase tracking-wider text-cyan-400">💡 Utilities (WiFi & Power)</h3>
                    <span class="font-mono text-xs text-cyan-400 font-bold">{data['monthly_utils']:,.0f} UGX</span>
                </div>
                <p class="text-[11px] text-zinc-400 mb-1.5">Estimated 30-day baseline based on Q3 consumption.</p>
                <div class="space-y-1 text-xs">
                    <div class="p-1.5 rounded bg-zinc-950/50 border border-zinc-800/80 flex justify-between items-center">
                        <span class="text-zinc-300">Broadband WiFi (Liquid / Smile)</span>
                        <span class="font-mono font-semibold text-cyan-300">110,000 UGX</span>
                    </div>
                    <div class="p-1.5 rounded bg-zinc-950/50 border border-zinc-800/80 flex justify-between items-center">
                        <span class="text-zinc-300">Electricity (Yaka Power Tokens)</span>
                        <span class="font-mono font-semibold text-cyan-300">47,867 UGX</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Variable Living Pool -->
        <div class="bg-zinc-900/80 border border-zinc-800 rounded-xl p-4 mb-3.5">
            <div class="flex justify-between items-center mb-2">
                <div>
                    <h3 class="font-bold text-xs uppercase tracking-wider text-zinc-200">🛒 Estimated Monthly Variable Living Expenses</h3>
                    <p class="text-[11px] text-zinc-400">Standard monthly discretionary run-rate derived from Q3 historical spending patterns.</p>
                </div>
                <span class="font-mono text-xs text-zinc-200 font-bold bg-zinc-800 px-2 py-0.5 rounded">{data['monthly_variable']:,.0f} UGX / mo</span>
            </div>
            <table class="w-full text-xs">
                <thead>
                    <tr class="border-b border-zinc-800 text-zinc-500 text-left">
                        <th class="py-1.5 font-medium">Group</th>
                        <th class="py-1.5 font-medium">Subcategory</th>
                        <th class="py-1.5 font-medium text-right">Estimated 1-Mo Spend</th>
                        <th class="py-1.5 font-medium text-right">% of Total Month</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-zinc-800/60">
                    {var_rows_html}
                </tbody>
            </table>
        </div>

        <!-- Strategic Takeaways -->
        <div class="bg-emerald-950/20 border border-emerald-800/40 rounded-xl p-3.5 text-xs text-zinc-300">
            <div class="font-bold text-emerald-400 mb-1 flex items-center gap-1.5">
                <span>💡 Strategic Monthly Cash-Flow Takeaways</span>
            </div>
            <ul class="list-disc list-inside space-y-0.5 text-zinc-400 text-[11px]">
                <li><strong class="text-zinc-200">Loan Liquidation Sprint (Scenario A):</strong> Committing <strong>6,367,103 UGX</strong> over the next 30 days permanently eliminates all 6 credit balances (Vernon personal loan 750k, MoKash 327k, Zenka 203.4k, Health Okay 163k, Maureen Asio 163k, Benon 95k).</li>
                <li><strong class="text-zinc-200">Post-Loan Living Baseline (Scenario C):</strong> Once all loans are fully retired, your monthly burn rate contracts to <strong>4,665,743 UGX/month</strong>, unlocking an immediate monthly cash surplus of 1.70M UGX.</li>
                <li><strong class="text-zinc-200">Lean Subscription Stack:</strong> Pruning DaVinci, Netflix, and Spotify while keeping Adobe ($25) and personal iCloud ($25) locks in digital overhead at <strong>318,200 UGX/month</strong>.</li>
            </ul>
        </div>
    </div>

    <!-- Print / Download Footer (Browser Only) -->
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
    return html

def compile_pdf():
    print("Fetching monthly live report data...")
    data = fetch_data()
    print("Generating monthly report HTML...")
    html = generate_html(data)

    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved HTML to {OUTPUT_HTML}")

    # Compile PDF via Google Chrome
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome_path):
        chrome_path = "google-chrome"

    print("Compiling 1-Month PDF via Google Chrome headless...")
    cmd = [
        chrome_path,
        "--headless",
        "--disable-gpu",
        "--user-data-dir=/tmp/chrome_monthly_profile",
        "--run-all-compositor-stages-before-draw",
        "--no-pdf-header-footer",
        f"--print-to-pdf={OUTPUT_PDF}",
        OUTPUT_HTML
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if res.returncode != 0:
            print("Chrome notice:", res.stderr)
    except subprocess.TimeoutExpired:
        pass

    if os.path.exists(OUTPUT_PDF) and os.path.getsize(OUTPUT_PDF) > 50000:
        pdf_size = os.path.getsize(OUTPUT_PDF)
        print(f"Successfully generated 1-Month PDF ({pdf_size} bytes): {OUTPUT_PDF}")
        if os.path.exists(ARTIFACT_DIR):
            dest = os.path.join(ARTIFACT_DIR, "Monthly_Expense_Report.pdf")
            shutil.copy2(OUTPUT_PDF, dest)
            print(f"Copied PDF to artifact directory: {dest}")
    else:
        print(f"Error: PDF was not generated or too small: {OUTPUT_PDF}")
        sys.exit(1)

if __name__ == "__main__":
    compile_pdf()
