#!/usr/bin/env python3
"""
Seed SQLite database for Financial Tracker from Google Sheet raw exports.
"""

import os
import csv
import sqlite3
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "finance.db")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

SOURCE_FILES = {
    'transactions': os.path.join(DATA_DIR, 'transactions.csv'),
    'monthly': os.path.join(DATA_DIR, 'monthly.csv'),
    'categories': os.path.join(DATA_DIR, 'categories.csv'),
    'accounts': os.path.join(DATA_DIR, 'accounts.csv'),
    'recurring': os.path.join(DATA_DIR, 'recurring.csv'),
    'daily': os.path.join(DATA_DIR, 'daily.csv'),
    'y2026': os.path.join(DATA_DIR, 'y2026.csv'),
    'needs_review': os.path.join(DATA_DIR, 'needs_review.csv')
}

def clean_csv_lines(filepath):
    """Read file and strip leading metadata before CSV header."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    start = 0
    for i, line in enumerate(lines):
        if not line.startswith("Title:") and not line.startswith("Description:") and not line.startswith("Source:") and not line.startswith("---") and line.strip():
            start = i
            break
    return lines[start:]

def parse_num(val):
    if not val:
        return 0.0
    val_str = str(val).replace(",", "").strip()
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def seed():
    print(f"Connecting to SQLite database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Drop existing tables
    cur.execute("DROP TABLE IF EXISTS transactions")
    cur.execute("DROP TABLE IF EXISTS monthly_summary")
    cur.execute("DROP TABLE IF EXISTS categories")
    cur.execute("DROP TABLE IF EXISTS recurring_expenses")
    cur.execute("DROP TABLE IF EXISTS accounts_summary")
    cur.execute("DROP TABLE IF EXISTS daily_spending")

    # 1. Transactions Table
    cur.execute("""
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        time TEXT,
        description TEXT,
        merchant TEXT,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT DEFAULT 'UGX',
        account TEXT,
        method TEXT,
        group_name TEXT,
        category TEXT,
        subcategory TEXT,
        personal_or_business TEXT,
        recurring TEXT,
        source TEXT,
        source_line TEXT,
        confidence TEXT,
        notes TEXT,
        flag TEXT,
        tx_id TEXT,
        is_review_resolved INTEGER DEFAULT 0
    )
    """)
    cur.execute("CREATE INDEX idx_tx_date ON transactions(date)")
    cur.execute("CREATE INDEX idx_tx_type ON transactions(type)")
    cur.execute("CREATE INDEX idx_tx_account ON transactions(account)")
    cur.execute("CREATE INDEX idx_tx_group ON transactions(group_name)")
    cur.execute("CREATE INDEX idx_tx_subcategory ON transactions(subcategory)")
    cur.execute("CREATE INDEX idx_tx_flag ON transactions(flag)")

    # 2. Monthly Summary Table
    cur.execute("""
    CREATE TABLE monthly_summary (
        month TEXT PRIMARY KEY,
        income REAL NOT NULL,
        expenditure REAL NOT NULL,
        savings_investments REAL DEFAULT 0,
        net_cash_flow REAL NOT NULL,
        daily_avg_spend REAL DEFAULT 0,
        top_subcategory TEXT
    )
    """)

    # 3. Categories Table
    cur.execute("""
    CREATE TABLE categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT,
        subcategory TEXT,
        total_spent REAL,
        percent_spend REAL,
        monthly_avg REAL,
        daily_avg REAL,
        tx_count INTEGER
    )
    """)

    # 4. Recurring Expenses Table
    cur.execute("""
    CREATE TABLE recurring_expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item TEXT,
        group_name TEXT,
        total_spent REAL,
        distinct_months INTEGER,
        est_monthly_equiv REAL
    )
    """)

    # 5. Accounts Summary Table
    cur.execute("""
    CREATE TABLE accounts_summary (
        account TEXT PRIMARY KEY,
        total_in REAL,
        total_out REAL,
        net_flow REAL
    )
    """)

    # 6. Daily Spending Table
    cur.execute("""
    CREATE TABLE daily_spending (
        date TEXT PRIMARY KEY,
        income REAL,
        expenditure REAL,
        net REAL,
        tx_count INTEGER
    )
    """)

    # Parse and insert transactions
    tx_lines = clean_csv_lines(SOURCE_FILES['transactions'])
    tx_reader = csv.DictReader(tx_lines)
    tx_records = []
    for r in tx_reader:
        amt = parse_num(r.get("Amount", 0))
        flag_val = r.get("Flag", "").strip()
        tx_records.append((
            r.get("Date", "").strip(),
            r.get("Time", "").strip(),
            r.get("Description", "").strip(),
            r.get("Merchant", "").strip(),
            r.get("Type", "").strip(),
            amt,
            r.get("Currency", "UGX").strip(),
            r.get("Account", "").strip(),
            r.get("Method", "").strip(),
            r.get("Group", "").strip(),
            r.get("Category", "").strip(),
            r.get("Subcategory", "").strip(),
            r.get("PersonalOrBusiness", "").strip(),
            r.get("Recurring", "").strip(),
            r.get("Source", "").strip(),
            r.get("SourceLine", "").strip(),
            r.get("Confidence", "").strip(),
            r.get("Notes", "").strip(),
            flag_val,
            r.get("TxID", "").strip(),
            0
        ))

    cur.executemany("""
    INSERT INTO transactions (
        date, time, description, merchant, type, amount, currency, account,
        method, group_name, category, subcategory, personal_or_business,
        recurring, source, source_line, confidence, notes, flag, tx_id, is_review_resolved
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, tx_records)
    print(f"Inserted {len(tx_records)} transactions into SQLite.")

    # Monthly summary
    monthly_lines = clean_csv_lines(SOURCE_FILES['monthly'])
    monthly_reader = csv.DictReader(monthly_lines)
    monthly_records = []
    for r in monthly_reader:
        if not r.get("Month"):
            continue
        monthly_records.append((
            r.get("Month", "").strip(),
            parse_num(r.get("Income", 0)),
            parse_num(r.get("Expenditure", 0)),
            parse_num(r.get("Savings/Investments", 0)),
            parse_num(r.get("Net Cash Flow", 0)),
            parse_num(r.get("Daily Avg Spend", 0)),
            r.get("Top Subcategory", "").strip()
        ))
    cur.executemany("""
    INSERT INTO monthly_summary (
        month, income, expenditure, savings_investments, net_cash_flow, daily_avg_spend, top_subcategory
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, monthly_records)
    print(f"Inserted {len(monthly_records)} monthly summary records.")

    # Categories
    cat_lines = clean_csv_lines(SOURCE_FILES['categories'])
    cat_reader = csv.DictReader(cat_lines)
    cat_records = []
    for r in cat_reader:
        if not r.get("Subcategory"):
            continue
        cat_records.append((
            r.get("Group", "").strip(),
            r.get("Subcategory", "").strip(),
            parse_num(r.get("Total Spent (UGX)", 0)),
            parse_num(r.get("% of Spend", 0)),
            parse_num(r.get("Monthly Avg", 0)),
            parse_num(r.get("Daily Avg", 0)),
            int(parse_num(r.get("# Transactions", 0)))
        ))
    cur.executemany("""
    INSERT INTO categories (
        group_name, subcategory, total_spent, percent_spend, monthly_avg, daily_avg, tx_count
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, cat_records)
    print(f"Inserted {len(cat_records)} categories.")

    # Recurring
    rec_lines = clean_csv_lines(SOURCE_FILES['recurring'])
    rec_reader = csv.DictReader(rec_lines)
    rec_records = []
    for r in rec_reader:
        if not r.get("Recurring Item"):
            continue
        rec_records.append((
            r.get("Recurring Item", "").strip(),
            r.get("Category Group", "").strip(),
            parse_num(r.get("Total Spent (UGX)", 0)),
            int(parse_num(r.get("Distinct Months", 0))),
            parse_num(r.get("Est. Monthly Equiv", 0))
        ))
    cur.executemany("""
    INSERT INTO recurring_expenses (
        item, group_name, total_spent, distinct_months, est_monthly_equiv
    ) VALUES (?, ?, ?, ?, ?)
    """, rec_records)
    print(f"Inserted {len(rec_records)} recurring expenses.")

    # Accounts
    acc_lines = clean_csv_lines(SOURCE_FILES['accounts'])
    acc_reader = csv.DictReader(acc_lines)
    acc_records = []
    for r in acc_reader:
        acc_name = r.get("Account", "").strip()
        if not acc_name:
            continue
        tin = parse_num(r.get("Total In (UGX)", 0))
        tout = parse_num(r.get("Total Out (UGX)", 0))
        acc_records.append((acc_name, tin, tout, tin - tout))
    cur.executemany("""
    INSERT INTO accounts_summary (
        account, total_in, total_out, net_flow
    ) VALUES (?, ?, ?, ?)
    """, acc_records)
    print(f"Inserted {len(acc_records)} accounts summary records.")

    # Daily spending
    daily_lines = clean_csv_lines(SOURCE_FILES['daily'])
    daily_reader = csv.DictReader(daily_lines)
    daily_records = []
    for r in daily_reader:
        d = r.get("Date", "").strip()
        if not d:
            continue
        daily_records.append((
            d,
            parse_num(r.get("Income", 0)),
            parse_num(r.get("Expenditure", 0)),
            parse_num(r.get("Net", 0)),
            int(parse_num(r.get("# Transactions", 0)))
        ))
    cur.executemany("""
    INSERT INTO daily_spending (
        date, income, expenditure, net, tx_count
    ) VALUES (?, ?, ?, ?, ?)
    """, daily_records)
    print(f"Inserted {len(daily_records)} daily spending rows.")

    conn.commit()

    # Integrity verification
    cur.execute("SELECT COUNT(*) FROM transactions")
    tx_count = cur.fetchone()[0]
    cur.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND flag != 'transfer-between-own-accounts'")
    full_exp = cur.fetchone()[0]
    cur.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND date >= '2022-03-01' AND flag != 'transfer-between-own-accounts'")
    core_exp = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM transactions WHERE flag != '' AND is_review_resolved=0")
    review_count = cur.fetchone()[0]

    print("\n--- Integrity Verification ---")
    print(f"Total Transactions: {tx_count} (Expected: 4221)")
    print(f"Full Ledger Expense: UGX {full_exp:,.2f} (Expected: 218,427,499.00)")
    print(f"Core Window Expense: UGX {core_exp:,.2f} (Expected: 203,994,619.00)")
    print(f"Pending Review Items: {review_count} (Expected: 541)")

    # Save a static JSON bundle for instant front-end hydration
    metadata = {
        "total_transactions": tx_count,
        "full_expenditure": full_exp,
        "core_expenditure": core_exp,
        "review_count": review_count,
        "date_range": {
            "min": cur.execute("SELECT MIN(date) FROM transactions").fetchone()[0],
            "max": cur.execute("SELECT MAX(date) FROM transactions").fetchone()[0]
        }
    }
    with open(os.path.join(DATA_DIR, "meta.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    conn.close()
    print("Database seeding completed successfully!")

if __name__ == "__main__":
    seed()
