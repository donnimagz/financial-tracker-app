#!/usr/bin/env python3
"""
sync_engine.py - Ingestion and Reconciliation Engine for Financial Tracker.

Handles:
- Ingestion of Pennyworth iOS CSV exports, Google Sheets exports, and JSON payloads
- Format auto-detection and category taxonomy mapping
- Idempotent deduplication via UUID (tx_id) and composite keys
- Atomic SQLite insertions into finance.db
- Dynamic recalculation of monthly_summary, categories, accounts_summary, and daily_spending
- Synchronization with data/meta.json and data/transactions.csv
- Git commit and push automation for Render / Vercel auto-deployment
"""

import os
import sys
import csv
import io
import json
import sqlite3
import urllib.request
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(BASE_DIR, "finance.db")

# Complete taxonomy mapping for Pennyworth categories -> (group_name, subcategory, default_type)
PENNYWORTH_CATEGORY_MAP = {
    # Living
    'Apartment Bills': ('Living', 'Housing', 'Expense'),
    'House Expenses': ('Living', 'Housing', 'Expense'),
    'Food': ('Living', 'Food & Dining', 'Expense'),
    'Groceries': ('Living', 'Groceries', 'Expense'),
    'Car': ('Living', 'Car & Fuel', 'Expense'),
    'Utilities': ('Living', 'Utilities', 'Expense'),
    'Phone': ('Living', 'Communication', 'Expense'),
    'Transportation': ('Living', 'Transport', 'Expense'),
    'Clothes': ('Living', 'Clothing', 'Expense'),
    'Pet': ('Living', 'Pets', 'Expense'),
    'Beauty': ('Living', 'Personal Care', 'Expense'),
    
    # Health
    'Health': ('Health', 'Medical', 'Expense'),
    'Natural Health': ('Health', 'Medical', 'Expense'),
    'Hospital': ('Health', 'Hospital', 'Expense'),
    
    # Lifestyle
    'Socializing': ('Lifestyle', 'Social Activities', 'Expense'),
    'Entertainment': ('Lifestyle', 'Entertainment', 'Expense'),
    'Baetime': ('Lifestyle', 'Entertainment', 'Expense'),
    'Traveling': ('Lifestyle', 'Travel', 'Expense'),
    'Hotel': ('Lifestyle', 'Travel', 'Expense'),
    'Shopping': ('Lifestyle', 'Shopping', 'Expense'),
    'Random Expenses': ('Lifestyle', 'Miscellaneous', 'Expense'),
    'Repairs': ('Lifestyle', 'Miscellaneous', 'Expense'),
    
    # Giving & Family
    'Wifey': ('Giving & Family', 'Family Support', 'Expense'),
    'Fam': ('Giving & Family', 'Family Support', 'Expense'),
    'Friends': ('Giving & Family', 'Gifts', 'Expense'),
    'Gift': ('Giving & Family', 'Gifts', 'Expense'),
    
    # Work & Business
    'Work': ('Work & Business', 'Business Expenses', 'Expense'),
    'Office': ('Work & Business', 'Business Expenses', 'Expense'),
    'Books': ('Work & Business', 'Education', 'Expense'),
    'Education': ('Work & Business', 'Education', 'Expense'),
    'Staff': ('Work & Business', 'Staff', 'Expense'),
    'Farm': ('Work & Business', 'Farm', 'Expense'),
    
    # Financial
    'Transaction Fees': ('Financial', 'Bank Charges', 'Expense'),
    'Transfer fee': ('Financial', 'Bank Charges', 'Expense'),
    'Loans/Lending': ('Financial', 'Loans & Lending', 'Expense'),
    'Savings': ('Financial', 'Savings', 'Expense'),
    'Invested': ('Financial', 'Investments', 'Expense'),
    
    # Other
    'Vape': ('Other', 'Substances', 'Expense'),
    'Drogas': ('Other', 'Substances', 'Expense'),
    'Subscriptions': ('Other', 'Uncategorized', 'Expense'),
    'Bribes': ('Other', 'Other', 'Expense'),
    
    # Income & Transfers
    'Salary': ('Income', 'Salary', 'Income'),
    'Bonus': ('Income', 'Salary', 'Income'),
    'Freelance': ('Income', 'Freelance & Side', 'Income'),
    'Side income': ('Income', 'Freelance & Side', 'Income'),
    'Help': ('Income', 'Help & Gifts', 'Income'),
    'Friends Debts': ('Income', 'Repayments', 'Income'),
    'Borrowed': ('Transfer-In', 'Loan Received', 'Income'),
    'Loan': ('Transfer-In', 'Loan Received', 'Income'),
}

def parse_num(val):
    if val is None or val == "":
        return 0.0
    val_str = str(val).replace(",", "").strip()
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def normalize_date(val):
    """Normalize date string to YYYY-MM-DD."""
    if not val:
        return datetime.today().strftime("%Y-%m-%d")
    val = str(val).strip()
    # If 8 digits like '20260914'
    if len(val) == 8 and val.isdigit():
        return f"{val[0:4]}-{val[4:6]}-{val[6:8]}"
    # If already YYYY-MM-DD
    if len(val) == 10 and val[4] == '-' and val[7] == '-':
        return val
    # Try common formats
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return val

def strip_metadata_lines(lines):
    """Strip metadata lines often prepended by Google Sheet exports."""
    start = 0
    for i, line in enumerate(lines):
        line_s = line.lstrip('\ufeff').strip()
        if not line_s:
            continue
        if line_s.startswith("Title:") or line_s.startswith("Description:") or line_s.startswith("Source:") or line_s.startswith("---"):
            continue
        start = i
        break
    return lines[start:]

def detect_format(header_line):
    """Detect format from header row."""
    header_lower = header_line.lstrip('\ufeff').lower()
    if "income/expenses" in header_lower or "uuid" in header_lower or "memo" in header_lower:
        return "pennyworth"
    if "txid" in header_lower or "group" in header_lower or "subcategory" in header_lower:
        return "tracker_csv"
    return "unknown"

def parse_pennyworth_rows(csv_text):
    """Parse CSV exported from Pennyworth iOS app."""
    csv_text = csv_text.lstrip('\ufeff')
    lines = [l for l in csv_text.splitlines() if l.strip()]
    if not lines:
        return []
    
    lines = strip_metadata_lines(lines)
    reader = csv.DictReader(lines)
    records = []
    
    for raw_r in reader:
        r = {k.lstrip('\ufeff').strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw_r.items() if k}
        raw_date = r.get("Date", "").strip()
        last_updated = r.get("Last updated", "").strip()
        
        if not raw_date and last_updated:
            raw_date = last_updated.split(" ")[0].replace("-", "")
            
        date_str = normalize_date(raw_date)
        
        time_str = ""
        if last_updated and " " in last_updated:
            time_str = last_updated.split(" ", 1)[1].strip()
        
        raw_io = r.get("Income/Expenses", "").strip().lower()
        if raw_io in ("in", "income"):
            tx_type = "Income"
        elif raw_io in ("out", "expense", "expenses"):
            tx_type = "Expense"
        else:
            tx_type = "Expense"
            
        amount = parse_num(r.get("Amount", 0))
        currency = r.get("Currency", "UGX").strip() or "UGX"
        
        cat_name = r.get("Category", "").strip()
        account_val = r.get("Account", "Mobile Money").strip() or "Mobile Money"
        member_val = r.get("Member", "").strip()
        memo_val = r.get("Memo", "").strip()
        uuid_val = r.get("UUID", "").strip()
        
        group_name = ""
        subcategory = ""
        flag_val = ""
        
        if cat_name in PENNYWORTH_CATEGORY_MAP:
            g, sub, default_type = PENNYWORTH_CATEGORY_MAP[cat_name]
            group_name = g
            subcategory = sub
            if tx_type == "Expense" and default_type == "Income":
                tx_type = "Expense"
            elif tx_type == "Income" and default_type == "Expense":
                if cat_name == "Drinks":
                    group_name = "Income"
                    subcategory = "Other Income"
                elif cat_name == "Farm":
                    group_name = "Income"
                    subcategory = "Business"
        else:
            if tx_type == "Income":
                group_name = "Income"
                subcategory = cat_name if cat_name else "Other Income"
            else:
                group_name = "Other"
                subcategory = cat_name if cat_name else "Uncategorized"
                flag_val = "needs-review-category"
                
        description = memo_val
        if not description:
            if cat_name == "Help" and member_val:
                description = "Help Mobile Money"
            elif cat_name:
                description = cat_name
            else:
                description = f"{tx_type} transaction"
                
        notes = ""
        if member_val and member_val.lower() != "self":
            notes = member_val
            
        records.append({
            "date": date_str,
            "time": time_str,
            "description": description,
            "merchant": "",
            "type": tx_type,
            "amount": amount,
            "currency": currency,
            "account": account_val,
            "method": account_val,
            "group_name": group_name,
            "category": cat_name,
            "subcategory": subcategory,
            "personal_or_business": "Personal",
            "recurring": "",
            "source": "pennyworth",
            "source_line": "",
            "confidence": "high",
            "notes": notes,
            "flag": flag_val,
            "tx_id": uuid_val,
            "is_review_resolved": 0
        })
        
    return records

def parse_tracker_csv_rows(csv_text):
    """Parse standard tracker schema CSV rows."""
    csv_text = csv_text.lstrip('\ufeff')
    lines = [l for l in csv_text.splitlines() if l.strip()]
    if not lines:
        return []
    lines = strip_metadata_lines(lines)
    reader = csv.DictReader(lines)
    records = []
    for raw_r in reader:
        r = {k.lstrip('\ufeff').strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw_r.items() if k}
        amt = parse_num(r.get("Amount", 0))
        records.append({
            "date": normalize_date(r.get("Date", "").strip()),
            "time": r.get("Time", "").strip(),
            "description": r.get("Description", "").strip(),
            "merchant": r.get("Merchant", "").strip(),
            "type": r.get("Type", "Expense").strip().capitalize(),
            "amount": amt,
            "currency": r.get("Currency", "UGX").strip() or "UGX",
            "account": r.get("Account", "").strip(),
            "method": r.get("Method", "").strip(),
            "group_name": r.get("Group", "").strip(),
            "category": r.get("Category", "").strip(),
            "subcategory": r.get("Subcategory", "").strip(),
            "personal_or_business": r.get("PersonalOrBusiness", "Personal").strip() or "Personal",
            "recurring": r.get("Recurring", "").strip(),
            "source": r.get("Source", "csv_import").strip() or "csv_import",
            "source_line": r.get("SourceLine", "").strip(),
            "confidence": r.get("Confidence", "high").strip() or "high",
            "notes": r.get("Notes", "").strip(),
            "flag": r.get("Flag", "").strip(),
            "tx_id": r.get("TxID", "").strip(),
            "is_review_resolved": 0
        })
    return records

def parse_incoming_csv(csv_content):
    """Auto-detect format and return normalized transaction records."""
    if not csv_content:
        return []
    csv_content = csv_content.lstrip('\ufeff')
    lines = [l for l in csv_content.splitlines() if l.strip()]
    if not lines:
        return []
    cleaned_lines = strip_metadata_lines(lines)
    if not cleaned_lines:
        return []
    header = cleaned_lines[0]
    fmt = detect_format(header)
    if fmt == "pennyworth":
        return parse_pennyworth_rows("\n".join(cleaned_lines))
    else:
        return parse_tracker_csv_rows("\n".join(cleaned_lines))

def recalculate_aggregates(conn):
    """Recalculate monthly_summary, categories, accounts_summary, and daily_spending."""
    cur = conn.cursor()
    
    # 1. Recalculate monthly_summary
    cur.execute("""
        SELECT substr(date, 1, 7) as m,
               SUM(CASE WHEN type='Income' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as inc,
               SUM(CASE WHEN type='Expense' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as exp,
               COUNT(DISTINCT date) as active_days
        FROM transactions
        GROUP BY m
    """)
    month_stats = cur.fetchall()
    for m, inc, exp, active_days in month_stats:
        if not m:
            continue
        inc = inc or 0.0
        exp = exp or 0.0
        active_days = max(1, active_days or 1)
        net = inc - exp
        daily_avg = exp / active_days
        
        # Find top subcategory for this month
        cur.execute("""
            SELECT subcategory, SUM(amount) as sub_total
            FROM transactions
            WHERE substr(date, 1, 7) = ? AND type='Expense' AND flag != 'transfer-between-own-accounts' AND subcategory != ''
            GROUP BY subcategory
            ORDER BY sub_total DESC
            LIMIT 1
        """, (m,))
        top_row = cur.fetchone()
        top_sub = top_row[0] if top_row else ""
        
        cur.execute("SELECT month FROM monthly_summary WHERE month = ?", (m,))
        if cur.fetchone():
            cur.execute("""
                UPDATE monthly_summary
                SET income = ?, expenditure = ?, net_cash_flow = ?, daily_avg_spend = ?, top_subcategory = ?
                WHERE month = ?
            """, (inc, exp, net, daily_avg, top_sub, m))
        else:
            cur.execute("""
                INSERT INTO monthly_summary (month, income, expenditure, savings_investments, net_cash_flow, daily_avg_spend, top_subcategory)
                VALUES (?, ?, ?, 0.0, ?, ?, ?)
            """, (m, inc, exp, net, daily_avg, top_sub))

    # 2. Recalculate categories table
    cur.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND flag != 'transfer-between-own-accounts'")
    tot_exp = cur.fetchone()[0] or 1.0
    
    cur.execute("SELECT COUNT(DISTINCT substr(date, 1, 7)), COUNT(DISTINCT date) FROM transactions")
    tot_months, tot_days = cur.fetchone()
    tot_months = max(1, tot_months or 1)
    tot_days = max(1, tot_days or 1)
    
    cur.execute("""
        SELECT group_name, subcategory, SUM(amount) as spent, COUNT(*) as cnt
        FROM transactions
        WHERE type='Expense' AND flag != 'transfer-between-own-accounts' AND subcategory != ''
        GROUP BY group_name, subcategory
        ORDER BY spent DESC
    """)
    cat_rows = cur.fetchall()
    
    cur.execute("DELETE FROM categories")
    for g, sub, spent, cnt in cat_rows:
        spent = spent or 0.0
        pct = (spent / tot_exp) * 100.0
        m_avg = spent / tot_months
        d_avg = spent / tot_days
        cur.execute("""
            INSERT INTO categories (group_name, subcategory, total_spent, percent_spend, monthly_avg, daily_avg, tx_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (g, sub, spent, pct, m_avg, d_avg, cnt))

    # 3. Recalculate daily_spending table
    cur.execute("""
        SELECT date,
               SUM(CASE WHEN type='Income' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as inc,
               SUM(CASE WHEN type='Expense' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as exp,
               COUNT(*) as cnt
        FROM transactions
        GROUP BY date
    """)
    daily_rows = cur.fetchall()
    cur.execute("DELETE FROM daily_spending")
    for d, inc, exp, cnt in daily_rows:
        inc = inc or 0.0
        exp = exp or 0.0
        cur.execute("""
            INSERT INTO daily_spending (date, income, expenditure, net, tx_count)
            VALUES (?, ?, ?, ?, ?)
        """, (d, inc, exp, inc - exp, cnt))

    # 4. Recalculate accounts_summary table
    cur.execute("""
        SELECT account,
               SUM(CASE WHEN type='Income' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as tin,
               SUM(CASE WHEN type='Expense' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as tout
        FROM transactions
        WHERE account != ''
        GROUP BY account
    """)
    acc_rows = cur.fetchall()
    cur.execute("DELETE FROM accounts_summary")
    for acc, tin, tout in acc_rows:
        tin = tin or 0.0
        tout = tout or 0.0
        cur.execute("""
            INSERT INTO accounts_summary (account, total_in, total_out, net_flow)
            VALUES (?, ?, ?, ?)
        """, (acc, tin, tout, tin - tout))

    conn.commit()

def update_metadata_and_csv(conn):
    """Update data/meta.json and append new rows to data/transactions.csv."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM transactions")
    tx_count = cur.fetchone()[0]
    
    cur.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND flag != 'transfer-between-own-accounts'")
    full_exp = cur.fetchone()[0] or 0.0
    
    cur.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND date >= '2022-03-01' AND flag != 'transfer-between-own-accounts'")
    core_exp = cur.fetchone()[0] or 0.0
    
    cur.execute("SELECT COUNT(*) FROM transactions WHERE flag != '' AND is_review_resolved=0")
    review_count = cur.fetchone()[0]
    
    cur.execute("SELECT MIN(date), MAX(date) FROM transactions")
    min_date, max_date = cur.fetchone()
    
    metadata = {
        "total_transactions": tx_count,
        "full_expenditure": full_exp,
        "core_expenditure": core_exp,
        "review_count": review_count,
        "date_range": {
            "min": min_date,
            "max": max_date
        },
        "last_sync": datetime.now().isoformat()
    }
    
    meta_path = os.path.join(DATA_DIR, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        
    tx_csv_path = os.path.join(DATA_DIR, "transactions.csv")
    cur.execute("""
        SELECT date, time, description, merchant, type, amount, currency, account,
               method, group_name, category, subcategory, personal_or_business,
               recurring, source, source_line, confidence, notes, flag, tx_id
        FROM transactions
        ORDER BY date ASC, time ASC, id ASC
    """)
    all_rows = cur.fetchall()
    
    with open(tx_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Date", "Time", "Description", "Merchant", "Type", "Amount", "Currency",
            "Account", "Method", "Group", "Category", "Subcategory", "PersonalOrBusiness",
            "Recurring", "Source", "SourceLine", "Confidence", "Notes", "Flag", "TxID"
        ])
        for r in all_rows:
            amt_formatted = f"{r[5]:,.2f}"
            row_list = list(r)
            row_list[5] = amt_formatted
            writer.writerow(row_list)
            
    return metadata

def ingest_records(records, db_path=None, dry_run=False):
    """
    Reconcile and insert records with idempotent deduplication.
    Returns summary dict.
    """
    if db_path is None:
        db_path = DB_PATH
        
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Existing transactions indexed by date, amount, type
    cur.execute("SELECT id, date, amount, type, description, tx_id FROM transactions")
    existing_rows = cur.fetchall()
    
    # Fast lookup dictionaries
    uuid_map = {}
    sig_map = {} # (date, amount, type) -> list of (id, desc_lower, tx_id)
    
    for row_id, d, a, t, desc, tx_id in existing_rows:
        d_str = str(d).strip()
        a_rnd = round(float(a or 0), 2)
        t_low = str(t or "").strip().lower()
        desc_low = str(desc or "").strip().lower()
        tx_id_str = str(tx_id or "").strip()
        
        if tx_id_str:
            uuid_map[tx_id_str] = row_id
            
        key_3 = (d_str, a_rnd, t_low)
        if key_3 not in sig_map:
            sig_map[key_3] = []
        sig_map[key_3].append((row_id, desc_low, tx_id_str))

    to_insert = []
    duplicates = []
    
    for r in records:
        uuid_val = r.get("tx_id", "").strip()
        date_val = r.get("date", "").strip()
        amt_val = round(float(r.get("amount", 0)), 2)
        type_val = r.get("type", "").strip().lower()
        desc_val = r.get("description", "").strip().lower()
        cat_val = r.get("category", "").strip().lower()
        
        # 1. UUID Match
        if uuid_val and uuid_val in uuid_map:
            duplicates.append(r)
            continue
            
        # 2. Composite (Date, Amount, Type) and Description Match
        key_3 = (date_val, amt_val, type_val)
        matched_duplicate = False
        if key_3 in sig_map:
            for ex_id, ex_desc, ex_uuid in sig_map[key_3]:
                # Exact or containment or category match
                if (desc_val == ex_desc or 
                    (desc_val and desc_val in ex_desc) or 
                    (ex_desc and ex_desc in desc_val) or
                    (cat_val and cat_val in ex_desc)):
                    matched_duplicate = True
                    # If existing transaction lacks UUID and incoming has one, enrich it!
                    if uuid_val and not ex_uuid and not dry_run:
                        cur.execute("UPDATE transactions SET tx_id = ? WHERE id = ?", (uuid_val, ex_id))
                        uuid_map[uuid_val] = ex_id
                    break
                    
        if matched_duplicate:
            duplicates.append(r)
            continue
            
        to_insert.append(r)
        if uuid_val:
            uuid_map[uuid_val] = -1
        if key_3 not in sig_map:
            sig_map[key_3] = []
        sig_map[key_3].append((-1, desc_val, uuid_val))
        
    if dry_run:
        conn.close()
        return {
            "success": True,
            "dry_run": True,
            "new_count": len(to_insert),
            "duplicate_count": len(duplicates),
            "sample_new": to_insert[:5]
        }
        
    if to_insert:
        cur.executemany("""
            INSERT INTO transactions (
                date, time, description, merchant, type, amount, currency, account,
                method, group_name, category, subcategory, personal_or_business,
                recurring, source, source_line, confidence, notes, flag, tx_id, is_review_resolved
            ) VALUES (
                :date, :time, :description, :merchant, :type, :amount, :currency, :account,
                :method, :group_name, :category, :subcategory, :personal_or_business,
                :recurring, :source, :source_line, :confidence, :notes, :flag, :tx_id, :is_review_resolved
            )
        """, to_insert)
        conn.commit()
        
        recalculate_aggregates(conn)
        meta = update_metadata_and_csv(conn)
    else:
        meta = update_metadata_and_csv(conn)
        
    conn.close()
    
    return {
        "success": True,
        "dry_run": False,
        "imported_count": len(to_insert),
        "duplicate_count": len(duplicates),
        "total_transactions": meta["total_transactions"],
        "full_expenditure": meta["full_expenditure"],
        "core_expenditure": meta["core_expenditure"],
        "review_count": meta["review_count"],
        "latest_date": meta["date_range"]["max"],
        "imported_items": [
            {
                "date": item["date"],
                "description": item["description"],
                "amount": item["amount"],
                "type": item["type"],
                "category": item["category"] or item["subcategory"]
            }
            for item in to_insert
        ],
        "message": f"Successfully processed: {len(to_insert)} imported, {len(duplicates)} duplicate(s) skipped."
    }

def git_commit_and_push(imported_count, latest_date):
    """Commit changes to git and push to origin/main."""
    try:
        msg = f"Auto-sync: Ingested {imported_count} new transactions (latest: {latest_date})"
        subprocess.run(["git", "add", "finance.db", "data/"], cwd=BASE_DIR, check=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=BASE_DIR, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=BASE_DIR, check=True)
        print(f"Git commit and push succeeded: '{msg}'")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Git commit/push error: {e}", file=sys.stderr)
        return False

def sync_from_csv_text(csv_text, git_push=False, dry_run=False):
    """Main entry point to sync from raw CSV string."""
    records = parse_incoming_csv(csv_text)
    if not records:
        return {"success": False, "error": "No valid transaction records found in CSV."}
    result = ingest_records(records, dry_run=dry_run)
    if git_push and not dry_run and result.get("imported_count", 0) > 0:
        git_commit_and_push(result["imported_count"], result.get("latest_date", ""))
    return result

def sync_from_file(filepath, git_push=False, dry_run=False):
    """Sync from local file path."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return sync_from_csv_text(content, git_push=git_push, dry_run=dry_run)

def sync_from_url(url, git_push=False, dry_run=False):
    """Sync from remote URL (e.g. Google Sheets export URL)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        content = response.read().decode("utf-8", errors="replace")
    return sync_from_csv_text(content, git_push=git_push, dry_run=dry_run)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Financial Tracker Ingestion & Sync Engine")
    parser.add_argument("--file", help="Path to CSV file to ingest")
    parser.add_argument("--url", help="URL of CSV to download and ingest")
    parser.add_argument("--git-push", action="store_true", help="Commit and push changes to git")
    parser.add_argument("--dry-run", action="store_true", help="Preview without modifying database")
    args = parser.parse_args()
    
    if args.file:
        res = sync_from_file(args.file, git_push=args.git_push, dry_run=args.dry_run)
        print(json.dumps(res, indent=2))
    elif args.url:
        res = sync_from_url(args.url, git_push=args.git_push, dry_run=args.dry_run)
        print(json.dumps(res, indent=2))
    else:
        parser.print_help()
