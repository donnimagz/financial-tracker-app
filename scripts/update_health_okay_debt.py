#!/usr/bin/env python3
"""
scripts/update_health_okay_debt.py
Updates Health Okay medication debt from 163,000 UGX to 188,500 UGX.
Updates aggregates and synchronizes data/meta.json and data/transactions.csv.
"""

import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from sync_engine import recalculate_aggregates, update_metadata_and_csv, DB_PATH

def update_health_okay():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    new_amount = 188500.0
    tx_id = "OWED-HEALTH-OKAY-20260921"

    cur.execute("SELECT id, description, amount FROM transactions WHERE tx_id = ?", (tx_id,))
    row = cur.fetchone()
    if row:
        old_id, desc, old_amt = row
        print(f"Updating {desc} (ID: {old_id}): {old_amt:,.0f} UGX -> {new_amount:,.0f} UGX")
        cur.execute("UPDATE transactions SET amount = ? WHERE tx_id = ?", (new_amount, tx_id))
    else:
        print(f"Error: Transaction with tx_id {tx_id} not found!")
        sys.exit(1)

    conn.commit()

    print("Recalculating database aggregates...")
    recalculate_aggregates(conn)
    print("Updating metadata and transactions.csv...")
    update_metadata_and_csv(conn)

    # Verify active owed debts
    cur.execute("SELECT description, amount FROM transactions WHERE flag = 'debt-owed' ORDER BY amount DESC")
    debts = cur.fetchall()
    print(f"\nActive Owed Debts ({len(debts)} total):")
    for d, a in debts:
        print(f" - {d}: {a:,.0f} UGX")
    print(f"\nTotal Active Owed: {sum(a for _, a in debts):,.0f} UGX")

    conn.close()

if __name__ == "__main__":
    update_health_okay()
