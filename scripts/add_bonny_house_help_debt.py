#!/usr/bin/env python3
"""
scripts/add_bonny_house_help_debt.py
Records Bonny (House Help) wage arrears:
- Missed past 2 months @ 110,000 UGX/mo = 220,000 UGX total debt.
Updates aggregates and synchronizes data/meta.json and data/transactions.csv.
"""

import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from sync_engine import recalculate_aggregates, update_metadata_and_csv, DB_PATH

def add_bonny_debt():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    debt = {
        "date": "2026-09-21",
        "time": "23:00:00",
        "description": "Bonny - House Help (Wage Arrears - 2 Months)",
        "merchant": "Bonny",
        "type": "Expense",
        "amount": 220000.0,
        "currency": "UGX",
        "account": "Credit",
        "method": "Credit",
        "group_name": "Work & Business",
        "category": "Staff",
        "subcategory": "Staff",
        "personal_or_business": "Personal",
        "recurring": "Monthly",
        "source": "user_input",
        "confidence": "high",
        "notes": "House help wage arrears for past 2 missed months (110,000 UGX/month owed to Bonny)",
        "flag": "debt-owed",
        "tx_id": "OWED-STAFF-BONNY-20260921",
        "is_review_resolved": 1
    }

    cur.execute("SELECT id FROM transactions WHERE tx_id = ?", (debt["tx_id"],))
    existing = cur.fetchone()
    if not existing:
        cur.execute("""
            INSERT INTO transactions (
                date, time, description, merchant, type, amount, currency, account,
                method, group_name, category, subcategory, personal_or_business,
                recurring, source, confidence, notes, flag, tx_id, is_review_resolved
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            debt["date"], debt["time"], debt["description"], debt["merchant"], debt["type"],
            debt["amount"], debt["currency"], debt["account"], debt["method"], debt["group_name"],
            debt["category"], debt["subcategory"], debt["personal_or_business"],
            debt["recurring"], debt["source"], debt["confidence"], debt["notes"],
            debt["flag"], debt["tx_id"], debt["is_review_resolved"]
        ))
        print(f"Inserted: {debt['description']} - {debt['amount']:,.0f} UGX")
    else:
        print(f"Already exists: {debt['description']}")

    conn.commit()

    print("Recalculating database aggregates...")
    recalculate_aggregates(conn)
    print("Updating metadata and transactions.csv...")
    update_metadata_and_csv(conn)

    cur.execute("SELECT COUNT(*), SUM(amount) FROM transactions WHERE type='Expense' AND flag != 'transfer-between-own-accounts'")
    total_tx, total_exp = cur.fetchone()
    print(f"Total expense transactions: {total_tx}, Total expenditure: {total_exp:,.0f} UGX")

    # Verify active owed debts
    cur.execute("SELECT description, amount FROM transactions WHERE flag = 'debt-owed'")
    debts = cur.fetchall()
    print(f"\nActive Owed Debts ({len(debts)} total):")
    for d, a in debts:
        print(f" - {d}: {a:,.0f} UGX")
    print(f"Total Active Owed: {sum(a for _, a in debts):,.0f} UGX")

    conn.close()

if __name__ == "__main__":
    add_bonny_debt()
