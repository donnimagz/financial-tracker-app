#!/usr/bin/env python3
"""
scripts/migrate_q3_data.py
Inserts missing Q3 rent and iMessage transactions, reclassifies Google One,
and updates SQLite aggregates and CSV/meta sync.
"""

import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import sync_engine

DB_PATH = os.path.join(BASE_DIR, "finance.db")

NEW_TRANSACTIONS = [
    # Rent for Q3 (1.7M UGX / month)
    {
        "date": "2026-07-01",
        "time": "09:00:00",
        "description": "Rent - July 2026",
        "merchant": "Landlord",
        "type": "Expense",
        "amount": 1700000.0,
        "currency": "UGX",
        "account": "Mobile Money",
        "method": "Mobile Money",
        "group_name": "Living",
        "category": "Housing",
        "subcategory": "Housing",
        "personal_or_business": "Personal",
        "recurring": "monthly",
        "source": "manual_entry",
        "confidence": "high",
        "notes": "Monthly rent 1.7m UGX",
        "flag": "",
        "tx_id": "RENT-2026-07"
    },
    {
        "date": "2026-08-01",
        "time": "09:00:00",
        "description": "Rent - August 2026",
        "merchant": "Landlord",
        "type": "Expense",
        "amount": 1700000.0,
        "currency": "UGX",
        "account": "Mobile Money",
        "method": "Mobile Money",
        "group_name": "Living",
        "category": "Housing",
        "subcategory": "Housing",
        "personal_or_business": "Personal",
        "recurring": "monthly",
        "source": "manual_entry",
        "confidence": "high",
        "notes": "Monthly rent 1.7m UGX",
        "flag": "",
        "tx_id": "RENT-2026-08"
    },
    {
        "date": "2026-09-01",
        "time": "09:00:00",
        "description": "Rent - September 2026",
        "merchant": "Landlord",
        "type": "Expense",
        "amount": 1700000.0,
        "currency": "UGX",
        "account": "Mobile Money",
        "method": "Mobile Money",
        "group_name": "Living",
        "category": "Housing",
        "subcategory": "Housing",
        "personal_or_business": "Personal",
        "recurring": "monthly",
        "source": "manual_entry",
        "confidence": "high",
        "notes": "Monthly rent 1.7m UGX",
        "flag": "",
        "tx_id": "RENT-2026-09"
    },
    # Unrecorded virtual card subscriptions from iMessages
    {
        "date": "2026-08-18",
        "time": "10:42:50",
        "description": "DaVinci AI",
        "merchant": "DAVINCI AI",
        "type": "Expense",
        "amount": 7500.0,
        "currency": "UGX",
        "account": "Momo Card",
        "method": "Virtual Card",
        "group_name": "Other",
        "category": "Subscriptions",
        "subcategory": "Subscriptions",
        "personal_or_business": "Personal",
        "recurring": "monthly",
        "source": "imessage_sms",
        "confidence": "high",
        "notes": "USD 1.99 on Virtual Card 3189",
        "flag": "",
        "tx_id": "MOMOCARD-20260818-DAVINCI"
    },
    {
        "date": "2026-08-21",
        "time": "13:56:31",
        "description": "DeepSeek API",
        "merchant": "DeepSeek",
        "type": "Expense",
        "amount": 8000.0,
        "currency": "UGX",
        "account": "Momo Card",
        "method": "Virtual Card",
        "group_name": "Other",
        "category": "Subscriptions",
        "subcategory": "Subscriptions",
        "personal_or_business": "Personal",
        "recurring": "",
        "source": "imessage_sms",
        "confidence": "high",
        "notes": "USD 2.12 on Virtual Card 3189",
        "flag": "",
        "tx_id": "MOMOCARD-20260821-DEEPSEEK"
    },
    # September 19 Airtime purchases from iMessages
    {
        "date": "2026-09-19",
        "time": "10:32:24",
        "description": "Airtime",
        "merchant": "MTN",
        "type": "Expense",
        "amount": 1000.0,
        "currency": "UGX",
        "account": "Mobile Money",
        "method": "Mobile Money",
        "group_name": "Living",
        "category": "Communication",
        "subcategory": "Communication",
        "personal_or_business": "Personal",
        "recurring": "",
        "source": "imessage_sms",
        "confidence": "high",
        "notes": "MTN Mobile Money airtime purchase",
        "flag": "",
        "tx_id": "MOMO-20260919-1032"
    },
    {
        "date": "2026-09-19",
        "time": "11:24:57",
        "description": "Airtime",
        "merchant": "MTN",
        "type": "Expense",
        "amount": 1000.0,
        "currency": "UGX",
        "account": "Mobile Money",
        "method": "Mobile Money",
        "group_name": "Living",
        "category": "Communication",
        "subcategory": "Communication",
        "personal_or_business": "Personal",
        "recurring": "",
        "source": "imessage_sms",
        "confidence": "high",
        "notes": "MTN Mobile Money airtime purchase",
        "flag": "",
        "tx_id": "MOMO-20260919-1124"
    },
    {
        "date": "2026-09-19",
        "time": "16:55:26",
        "description": "Airtime",
        "merchant": "MTN",
        "type": "Expense",
        "amount": 1000.0,
        "currency": "UGX",
        "account": "Mobile Money",
        "method": "Mobile Money",
        "group_name": "Living",
        "category": "Communication",
        "subcategory": "Communication",
        "personal_or_business": "Personal",
        "recurring": "",
        "source": "imessage_sms",
        "confidence": "high",
        "notes": "MTN Mobile Money airtime purchase",
        "flag": "",
        "tx_id": "MOMO-20260919-1655"
    }
]

def run_migration():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print(f"Connected to {DB_PATH}")

    # 1. Reclassify July 16 transaction
    cur.execute("""
        UPDATE transactions
        SET description = 'Google One',
            merchant = 'Google',
            group_name = 'Other',
            category = 'Subscriptions',
            subcategory = 'Subscriptions',
            recurring = 'monthly',
            notes = 'Virtual Card payment for Google One USD 9.99 (reclassified from Groceries)'
        WHERE date = '2026-07-16' AND description = 'Groceries Mobile Money' AND amount = 38000.0
    """)
    updated = cur.rowcount
    print(f"Reclassified July 16 Google One transaction (rows updated: {updated})")

    # 2. Insert new transactions (idempotent check by tx_id)
    inserted_count = 0
    new_rows_for_sync = []
    for tx in NEW_TRANSACTIONS:
        cur.execute("SELECT id FROM transactions WHERE tx_id = ?", (tx["tx_id"],))
        if cur.fetchone():
            print(f"Skipping already existing tx: {tx['tx_id']}")
            continue

        cur.execute("""
            INSERT INTO transactions (
                date, time, description, merchant, type, amount, currency, account,
                method, group_name, category, subcategory, personal_or_business,
                recurring, source, source_line, confidence, notes, flag, tx_id, is_review_resolved
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, 0)
        """, (
            tx["date"], tx["time"], tx["description"], tx["merchant"], tx["type"],
            tx["amount"], tx["currency"], tx["account"], tx["method"], tx["group_name"],
            tx["category"], tx["subcategory"], tx["personal_or_business"], tx["recurring"],
            tx["source"], tx["confidence"], tx["notes"], tx["flag"], tx["tx_id"]
        ))
        inserted_count += 1
        new_rows_for_sync.append(tx)

    conn.commit()
    print(f"Inserted {inserted_count} new transactions into finance.db")

    # 3. Recalculate aggregates across all summary tables
    print("Recalculating monthly, category, account, and daily aggregates...")
    sync_engine.recalculate_aggregates(conn)
    conn.commit()

    # 4. Sync meta.json and transactions.csv
    print("Updating data/meta.json and data/transactions.csv...")
    sync_engine.update_metadata_and_csv(conn)

    conn.close()
    print("Migration and reconciliation completed successfully!")

if __name__ == "__main__":
    run_migration()
