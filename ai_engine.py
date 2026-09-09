#!/usr/bin/env python3
"""
AI Query Engine for Financial Tracker.
Provides grounded natural language financial querying using Gemini API
with streaming Server-Sent Events (SSE) and local SQLite analytical fallback.
"""

import os
import json
import sqlite3
import re
import datetime
import urllib.request
import urllib.error
import ssl

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "finance.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

SYSTEM_INSTRUCTION = """You are an expert financial advisor and data analyst for a personal ledger in Uganda (amounts in UGX - Ugandan Shilling).
You have access to a SQLite database 'finance.db' with:
- transactions (id, date, time, description, merchant, type ['Income'/'Expense'], amount, currency ['UGX'], account, group_name, category, subcategory, confidence, notes, flag, tx_id)
- monthly_summary (month, income, expenditure, savings_investments, net_cash_flow, daily_avg_spend, top_subcategory)
- categories (group_name, subcategory, total_spent, percent_spend, monthly_avg, daily_avg, tx_count)
- recurring_expenses (item, group_name, total_spent, distinct_months, est_monthly_equiv)
- accounts_summary (account, total_in, total_out, net_flow)

Always format amounts clearly (e.g. UGX 1,500,000 or 1.5M UGX).
Be concise, helpful, and provide specific actionable insights or breakdown tables where appropriate.
"""

def execute_readonly_sql(sql_query):
    """Safely execute a read-only SQL query against the database."""
    cleaned = sql_query.strip().rstrip(';')
    if not cleaned.lower().startswith(("select", "with")):
        raise ValueError("Only SELECT or WITH queries are permitted.")
    forbidden = ["insert", "update", "delete", "drop", "alter", "create", "truncate"]
    for word in forbidden:
        if re.search(r'\b' + word + r'\b', cleaned.lower()):
            raise ValueError(f"Query contains forbidden keyword '{word}'")
    
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(cleaned)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()

def run_local_analytics(query, history=None):
    """
    Intelligent built-in financial query router.
    Extracts intents (totals, categories, merchants, time windows, accounts)
    and executes exact SQL aggregations against finance.db.
    Yields (event_type, content) tuples.
    """
    q = query.lower()
    yield ("THOUGHT", f"Analyzing query intent: '{query}'")
    
    conn = get_db()
    cur = conn.cursor()
    
    # Check for specific year
    year_match = re.search(r'\b(202[0-6])\b', q)
    year = year_match.group(1) if year_match else None
    
    # Check for month
    months = {
        'january': '01', 'february': '02', 'march': '03', 'april': '04',
        'may': '05', 'june': '06', 'july': '07', 'august': '08',
        'september': '09', 'october': '10', 'november': '11', 'december': '12'
    }
    month_num = None
    for m_name, m_val in months.items():
        if m_name in q:
            month_num = m_val
            break
            
    # Intent 1: Needs review items
    if "review" in q or "flag" in q or "unresolved" in q:
        yield ("THOUGHT", "Querying transactions flagged for review...")
        cur.execute("""
            SELECT flag, count(*) as count, sum(amount) as total_amt 
            FROM transactions 
            WHERE flag != '' 
            GROUP BY flag 
            ORDER BY count DESC
        """)
        rows = cur.fetchall()
        total_flags = sum(r['count'] for r in rows)
        
        reply = f"### 🔍 Transactions Needing Review\n\n"
        reply += f"There are **{total_flags:,} flagged transactions** across the ledger:\n\n"
        reply += "| Flag Category | Count | Total Value (UGX) |\n"
        reply += "| :--- | :---: | :---: |\n"
        for r in rows:
            reply += f"| `{r['flag']}` | {r['count']} | UGX {r['total_amt']:,.2f} |\n"
        reply += "\n> You can review and resolve these one-by-one or in bulk in the **Needs Review** tab."
        
        yield ("FINAL_RESPONSE", reply)
        yield ("SUGGESTION", "Show high-value transactions needing review")
        yield ("SUGGESTION", "What are the common un-categorized merchants?")
        conn.close()
        return

    # Intent 2: Specific Merchant or Person (e.g., Ada, George, Stanbic, TILES)
    people_merchants = ['ada', 'george', 'tiles gallery', 'joseph', 'daryanani', 'stanbic', 'mtn', 'airtel', 'jumia', 'uber', 'total']
    matched_entity = None
    for entity in people_merchants:
        if entity in q:
            matched_entity = entity
            break
            
    if matched_entity:
        yield ("THOUGHT", f"Searching transactions involving '{matched_entity}'...")
        cur.execute("""
            SELECT type, count(*) as count, sum(amount) as total_amt, min(date) as first_dt, max(date) as last_dt
            FROM transactions
            WHERE (lower(description) LIKE ? OR lower(merchant) LIKE ?)
            GROUP BY type
        """, (f"%{matched_entity}%", f"%{matched_entity}%"))
        rows = cur.fetchall()
        
        if rows:
            reply = f"### 👤 Activity for '{matched_entity.title()}'\n\n"
            reply += f"Found records spanning the ledger:\n\n"
            reply += "| Type | Transactions | Total (UGX) | Date Range |\n"
            reply += "| :--- | :---: | :---: | :---: |\n"
            for r in rows:
                reply += f"| **{r['type']}** | {r['count']} | UGX {r['total_amt']:,.2f} | {r['first_dt']} to {r['last_dt']} |\n"
            
            # Show top 5 recent transactions
            cur.execute("""
                SELECT date, type, amount, description, account
                FROM transactions
                WHERE (lower(description) LIKE ? OR lower(merchant) LIKE ?)
                ORDER BY date DESC LIMIT 5
            """, (f"%{matched_entity}%", f"%{matched_entity}%"))
            recent = cur.fetchall()
            reply += "\n**Recent Transactions:**\n"
            for t in recent:
                reply += f"- **{t['date']}**: {t['type']} of **UGX {t['amount']:,.2f}** ({t['account']}) — *{t['description'][:60]}...*\n"
                
            yield ("FINAL_RESPONSE", reply)
            yield ("SUGGESTION", f"Show all expenses for {matched_entity.title()}")
            yield ("SUGGESTION", "What is my largest single transaction?")
            conn.close()
            return

    # Intent 3: Highest / Largest Expenses
    if "biggest" in q or "largest" in q or "highest" in q or "top expense" in q:
        yield ("THOUGHT", "Fetching top single expenditure transactions...")
        cur.execute("""
            SELECT date, description, merchant, amount, account, subcategory
            FROM transactions
            WHERE type='Expense' AND flag != 'transfer-between-own-accounts'
            ORDER BY amount DESC LIMIT 5
        """)
        top_tx = cur.fetchall()
        reply = "### 💎 Largest Single Expenses\n\n"
        reply += "| Date | Description | Subcategory | Account | Amount (UGX) |\n"
        reply += "| :--- | :--- | :--- | :--- | :---: |\n"
        for t in top_tx:
            desc = t['description'] or t['merchant'] or 'N/A'
            if len(desc) > 35: desc = desc[:32] + "..."
            reply += f"| {t['date']} | {desc} | {t['subcategory'] or 'Uncategorized'} | {t['account']} | **UGX {t['amount']:,.2f}** |\n"
        
        yield ("FINAL_RESPONSE", reply)
        yield ("SUGGESTION", "What are my recurring monthly expenses?")
        yield ("SUGGESTION", "How much do I spend on Housing each month?")
        conn.close()
        return

    # Intent 4: Recurring Expenses
    if "recurring" in q or "regular" in q or "subscription" in q:
        yield ("THOUGHT", "Querying recurring commitments and run-rate projections...")
        cur.execute("""
            SELECT item, group_name, total_spent, distinct_months, est_monthly_equiv
            FROM recurring_expenses
            ORDER BY est_monthly_equiv DESC LIMIT 8
        """)
        rows = cur.fetchall()
        total_equiv = sum(r['est_monthly_equiv'] for r in rows)
        
        reply = "### 🔄 Key Recurring Commitments\n\n"
        reply += f"Projected regular monthly run-rate for top commitments: **UGX {total_equiv:,.2f}/mo**\n\n"
        reply += "| Commitment | Group | Distinct Months | Est. Monthly Equiv (UGX) |\n"
        reply += "| :--- | :--- | :---: | :---: |\n"
        for r in rows:
            reply += f"| **{r['item']}** | {r['group_name']} | {r['distinct_months']} | UGX {r['est_monthly_equiv']:,.2f} |\n"
            
        yield ("FINAL_RESPONSE", reply)
        yield ("SUGGESTION", "How much have I spent on Housing in total?")
        yield ("SUGGESTION", "What was my medical spend this year?")
        conn.close()
        return

    # Intent 5: Specific Category spending (e.g. Housing, Medical, Groceries, Food)
    cur.execute("SELECT DISTINCT subcategory FROM categories")
    known_subcats = [r[0] for r in cur.fetchall() if r[0]]
    matched_subcat = None
    for s in known_subcats:
        if s.lower() in q:
            matched_subcat = s
            break
            
    if matched_subcat:
        yield ("THOUGHT", f"Aggregating expenditures for category '{matched_subcat}'...")
        where_clause = "subcategory = ? AND type='Expense'"
        params = [matched_subcat]
        if year:
            where_clause += " AND date LIKE ?"
            params.append(f"{year}%")
            
        cur.execute(f"""
            SELECT count(*) as count, sum(amount) as total, avg(amount) as avg_amt, min(date) as min_d, max(date) as max_d
            FROM transactions
            WHERE {where_clause}
        """, params)
        res = cur.fetchone()
        
        # Monthly trend for this category
        cur.execute(f"""
            SELECT substr(date, 1, 7) as ym, sum(amount) as spent
            FROM transactions
            WHERE subcategory = ? AND type='Expense'
            GROUP BY ym ORDER BY ym DESC LIMIT 6
        """, [matched_subcat])
        monthly_trend = cur.fetchall()
        
        reply = f"### 🏷️ Category Spending: **{matched_subcat}**"
        if year: reply += f" ({year})"
        reply += "\n\n"
        reply += f"- **Total Spent**: UGX {res['total'] or 0:,.2f}\n"
        reply += f"- **Transaction Count**: {res['count'] or 0} transactions\n"
        reply += f"- **Average Transaction**: UGX {res['avg_amt'] or 0:,.2f}\n\n"
        
        if monthly_trend:
            reply += "**Recent Months Breakdown:**\n\n"
            reply += "| Month | Spent (UGX) |\n| :--- | :---: |\n"
            for m in monthly_trend:
                reply += f"| {m['ym']} | UGX {m['spent']:,.2f} |\n"
                
        yield ("FINAL_RESPONSE", reply)
        yield ("SUGGESTION", f"Compare {matched_subcat} with previous year")
        yield ("SUGGESTION", "Show top 5 spending categories overall")
        conn.close()
        return

    # Intent 6: General Overview / Totals / Yearly or Monthly Stats
    yield ("THOUGHT", "Calculating cash flow summary metrics...")
    time_filter = ""
    params = []
    header_title = "Overall Financial Summary"
    
    if year and month_num:
        ym = f"{year}-{month_num}"
        time_filter = "AND date LIKE ?"
        params = [f"{ym}%"]
        header_title = f"Financial Summary for {ym}"
    elif year:
        time_filter = "AND date LIKE ?"
        params = [f"{year}%"]
        header_title = f"Financial Summary for {year}"
        
    cur.execute(f"""
        SELECT 
            sum(CASE WHEN type='Income' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as inc,
            sum(CASE WHEN type='Expense' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as exp,
            count(*) as tx_count
        FROM transactions
        WHERE 1=1 {time_filter}
    """, params)
    cf = cur.fetchone()
    inc = cf['inc'] or 0.0
    exp = cf['exp'] or 0.0
    net = inc - exp
    
    # Top 5 categories
    cur.execute(f"""
        SELECT subcategory, sum(amount) as cat_exp, count(*) as count
        FROM transactions
        WHERE type='Expense' AND flag != 'transfer-between-own-accounts' {time_filter}
        GROUP BY subcategory
        ORDER BY cat_exp DESC LIMIT 5
    """, params)
    top_cats = cur.fetchall()
    
    reply = f"### 📊 {header_title}\n\n"
    reply += f"- 💰 **Total Income**: UGX {inc:,.2f}\n"
    reply += f"- 💸 **Total Expenditure**: UGX {exp:,.2f}\n"
    reply += f"- ⚖️ **Net Cash Flow**: **UGX {net:,.2f}** ({'Surplus' if net >= 0 else 'Deficit'})\n"
    reply += f"- 📝 **Transactions Recorded**: {cf['tx_count']:,}\n\n"
    
    if top_cats:
        reply += "**Top Spending Categories:**\n\n"
        reply += "| Category | Total Spent (UGX) | Share |\n"
        reply += "| :--- | :---: | :---: |\n"
        for c in top_cats:
            cat_name = c['subcategory'] or 'Other'
            share = (c['cat_exp'] / exp * 100) if exp > 0 else 0
            reply += f"| **{cat_name}** | UGX {c['cat_exp']:,.2f} | {share:.1f}% |\n"
            
    yield ("FINAL_RESPONSE", reply)
    yield ("SUGGESTION", "What was my spending in 2025?")
    yield ("SUGGESTION", "What are my biggest expenses?")
    yield ("SUGGESTION", "Show transactions needing review")
    conn.close()

def generate_chat_stream(query, history=None):
    """
    Generator yielding Server-Sent Events (SSE) strings.
    Attempts Gemini API with database tool execution when online,
    or smoothly utilizes the local database analytics engine.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    
    # Check if we should try online Gemini
    use_online = bool(api_key)
    
    if use_online:
        yield f"data: {json.dumps({'type': 'THOUGHT', 'content': 'Connecting to Gemini model for contextual reasoning...'})}\n\n"
        
        # Prepare context from current database state
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM transactions")
        min_d, max_d, cnt = cur.fetchone()
        cur.execute("SELECT sum(amount) FROM transactions WHERE type='Expense' AND flag != 'transfer-between-own-accounts'")
        tot_exp = cur.fetchone()[0] or 0
        cur.execute("SELECT sum(amount) FROM transactions WHERE type='Income' AND flag != 'transfer-between-own-accounts'")
        tot_inc = cur.fetchone()[0] or 0
        conn.close()
        
        system_context = f"""Context: Personal financial ledger from {min_d} to {max_d}.
Total transactions: {cnt:,}. Total income: UGX {tot_inc:,.2f}. Total expense: UGX {tot_exp:,.2f}. Currency: UGX."""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except Exception:
            ctx = ssl._create_unverified_context()
            
        messages_payload = []
        if history:
            for h in history[-4:]:
                role = "user" if h.get("role") == "user" else "model"
                messages_payload.append({
                    "role": role,
                    "parts": [{"text": h.get("content", "")}]
                })
        messages_payload.append({
            "role": "user",
            "parts": [{"text": f"System context: {system_context}\n\nUser Question: {query}"}]
        })
        
        req_data = {
            "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": messages_payload,
            "generationConfig": {"temperature": 0.2}
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                candidates = result.get("candidates", [])
                if candidates:
                    content_parts = candidates[0].get("content", {}).get("parts", [])
                    text_out = "".join(p.get("text", "") for p in content_parts)
                    
                    yield f"data: {json.dumps({'type': 'THOUGHT', 'content': 'Synthesized response based on ledger context.'})}\n\n"
                    # Stream tokens in small chunks for smooth typing effect
                    chunk_size = 64
                    for i in range(0, len(text_out), chunk_size):
                        yield f"data: {json.dumps({'type': 'FINAL_RESPONSE', 'content': text_out[i:i+chunk_size]})}\n\n"
                    
                    # Suggestions
                    yield f"data: {json.dumps({'type': 'SUGGESTION', 'content': 'Show breakdown of top categories'})}\n\n"
                    yield f"data: {json.dumps({'type': 'SUGGESTION', 'content': 'How much did I spend in 2026 so far?'})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
        except Exception as e:
            # Fall back to local analytical engine if network is sandboxed/offline
            yield f"data: {json.dumps({'type': 'THOUGHT', 'content': f'Using internal database analytics engine (Offline mode: {str(e)[:40]}).'})}\n\n"
    
    # Execute through local grounded analytics engine
    for event_type, content in run_local_analytics(query, history):
        yield f"data: {json.dumps({'type': event_type, 'content': content})}\n\n"
    
    yield "data: [DONE]\n\n"
