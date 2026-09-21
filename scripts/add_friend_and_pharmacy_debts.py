#!/usr/bin/env python3
"""
scripts/add_friend_and_pharmacy_debts.py
Records additional active liabilities:
- Benon from Ecopharm: 95,000 UGX (Medication debt)
- Vernon (friend loan): 750,000 UGX (Personal loan)
Updates aggregates and synchronizes data/meta.json and data/transactions.csv.
"""

import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from sync_engine import recalculate_aggregates, update_metadata_and_csv, DB_PATH

def add_debts():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    debts_to_add = [
        {
            "date": "2026-09-21",
            "time": "16:15:00",
            "description": "Benon - Ecopharm (Medication Debt)",
            "merchant": "Benon (Ecopharm)",
            "type": "Expense",
            "amount": 95000.0,
            "currency": "UGX",
            "account": "Credit",
            "method": "Credit",
            "group_name": "Health",
            "category": "Health",
            "subcategory": "Medical",
            "personal_or_business": "Personal",
            "recurring": "",
            "source": "user_input",
            "confidence": "high",
            "notes": "Medication debt owed to Benon from Ecopharm (pending settlement)",
            "flag": "debt-owed",
            "tx_id": "OWED-ECOPHARM-BENON-20260921",
            "is_review_resolved": 1
        },
        {
            "date": "2026-09-21",
            "time": "16:15:00",
            "description": "Vernon (Personal Loan Owed)",
            "merchant": "Vernon",
            "type": "Expense",
            "amount": 750000.0,
            "currency": "UGX",
            "account": "Credit",
            "method": "Credit",
            "group_name": "Financial",
            "category": "Loans/Lending",
            "subcategory": "Loans & Lending",
            "personal_or_business": "Personal",
            "recurring": "",
            "source": "user_input",
            "confidence": "high",
            "notes": "Personal loan owed to friend Vernon",
            "flag": "debt-owed",
            "tx_id": "OWED-VERNON-20260921",
            "is_review_resolved": 1
        }
    ]

    inserted_count = 0
    for d in debts_to_add:
        cur.execute("SELECT id FROM transactions WHERE tx_id = ?", (d["tx_id"],))
        existing = cur.fetchone()
        if not existing:
            cur.execute("""
                INSERT INTO transactions (
                    date, time, description, merchant, type, amount, currency, account,
                    method, group_name, category, subcategory, personal_or_business,
                    recurring, source, confidence, notes, flag, tx_id, is_review_resolved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d["date"], d["time"], d["description"], d["merchant"], d["type"],
                d["amount"], d["currency"], d["account"], d["method"], d["group_name"],
                d["category"], d["subcategory"], d["personal_or_business"],
                d["recurring"], d["source"], d["confidence"], d["notes"],
                d["flag"], d["tx_id"], d["is_review_resolved"]
            ))
            inserted_count += 1
            print(f"Inserted: {d['description']} - {d['amount']:,.0f} UGX")
        else:
            print(f"Already exists: {d['description']}")

    conn.commit()

    if inserted_count > 0:
        print("Recalculating database aggregates...")
        recalculate_aggregates(conn)
        print("Updating metadata and transactions.csv...")
        update_metadata_and_csv(conn)

    cur.execute("SELECT COUNT(*), SUM(amount) FROM transactions WHERE type='Expense' AND flag != 'transfer-between-own-accounts'")
    total_tx, total_exp = cur.fetchone()
    print(f"Total expense transactions: {total_tx}, Total expenditure: {total_exp:,.0f} UGX")

    conn.close()

if __name__ == "__main__":
    add_debts()
