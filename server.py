#!/usr/bin/env python3
"""
Multi-threaded Python HTTP and REST API Server for Financial Tracker.
Zero external dependencies (uses standard library http.server, sqlite3, json, urllib).
"""

import os
import sys
import json
import sqlite3
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from ai_engine import generate_chat_stream

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "finance.db")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

# Authentication / Passcode Lock Configuration
APP_PASSWORD = os.environ.get("APP_PASSWORD", "2026")
VALID_SESSIONS = set()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def is_authenticated(headers, query=None):
    if not APP_PASSWORD:
        return True
    
    # 1. Bearer Token
    auth_header = headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token in VALID_SESSIONS:
            return True

    # 2. Cookie header
    cookie_header = headers.get("Cookie", "")
    for part in cookie_header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            if k == "finance_token" and v in VALID_SESSIONS:
                return True

    # 3. Query string token (for EventSource SSE)
    if query and "token" in query:
        token = query["token"][0]
        if token in VALID_SESSIONS:
            return True

    return False

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class FinanceAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PUBLIC_DIR, **kwargs)

    def serve_file(self, filepath, content_type):
        if not os.path.exists(filepath):
            self.send_error(404, "File not found")
            return
        with open(filepath, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            # Public auth check endpoint
            if path == "/api/auth/check":
                self._send_json({
                    "auth_required": bool(APP_PASSWORD),
                    "authenticated": is_authenticated(self.headers, query)
                })
                return

            # Require authentication for all other /api/ endpoints
            if not is_authenticated(self.headers, query):
                self._send_json({"error": "Unauthorized. Passcode required."}, status=401)
                return

            try:
                if path == "/api/stats":
                    self.handle_get_stats(query)
                elif path == "/api/transactions":
                    self.handle_get_transactions(query)
                elif path == "/api/monthly":
                    self.handle_get_monthly(query)
                elif path == "/api/categories":
                    self.handle_get_categories(query)
                elif path == "/api/accounts":
                    self.handle_get_accounts(query)
                elif path == "/api/recurring":
                    self.handle_get_recurring(query)
                elif path == "/api/needs-review":
                    self.handle_get_needs_review(query)
                elif path == "/api/filter-options":
                    self.handle_get_filter_options()
                else:
                    self._send_json({"error": "Endpoint not found"}, status=404)
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            return

        # Explicitly serve frontend static files with exact MIME types
        if path in ("/", "/index.html"):
            self.serve_file(os.path.join(PUBLIC_DIR, "index.html"), "text/html; charset=utf-8")
            return
        elif path == "/styles.css":
            self.serve_file(os.path.join(PUBLIC_DIR, "styles.css"), "text/css; charset=utf-8")
            return
        elif path == "/app.js":
            self.serve_file(os.path.join(PUBLIC_DIR, "app.js"), "application/javascript; charset=utf-8")
            return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len) if content_len > 0 else b"{}"

        try:
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            body = {}

        # 1. Login endpoint
        if path == "/api/auth/login":
            entered_pass = body.get("password", "")
            if entered_pass == APP_PASSWORD:
                token = os.urandom(24).hex()
                VALID_SESSIONS.add(token)
                self._send_json({"status": "ok", "token": token})
            else:
                self._send_json({"error": "Incorrect passcode"}, status=401)
            return

        # 2. Logout endpoint
        if path == "/api/auth/logout":
            token = body.get("token", "")
            if token in VALID_SESSIONS:
                VALID_SESSIONS.remove(token)
            self._send_json({"status": "logged_out"})
            return

        # Require authentication for protected POST actions
        query = urllib.parse.parse_qs(parsed.query)
        if not is_authenticated(self.headers, query):
            self._send_json({"error": "Unauthorized. Passcode required."}, status=401)
            return

        if path == "/api/chat":
            self.handle_chat_stream(body)
            return

        if path == "/api/transactions":
            self.handle_create_transaction(body)
            return

        if path == "/api/batch-review":
            self.handle_batch_review(body)
            return

        self._send_json({"error": "Endpoint not found"}, status=404)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if not is_authenticated(self.headers, query):
            self._send_json({"error": "Unauthorized. Passcode required."}, status=401)
            return
        content_len = int(self.headers.get("Content-Length", 0))
        put_data = self.rfile.read(content_len) if content_len > 0 else b"{}"

        try:
            body = json.loads(put_data.decode("utf-8")) if put_data else {}
        except Exception:
            body = {}

        if path.startswith("/api/transactions/"):
            tx_id = path.split("/")[-1]
            self.handle_update_transaction(tx_id, body)
            return

        self._send_json({"error": "Endpoint not found"}, status=404)

    # ------------------ API Handlers ------------------

    def handle_get_stats(self, query):
        window = query.get("window", ["core"])[0]
        conn = get_db()
        cur = conn.cursor()

        date_condition = "AND date >= '2022-03-01'" if window == "core" else ""

        # Income & Expenditure
        cur.execute(f"""
            SELECT 
                SUM(CASE WHEN type='Income' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as income,
                SUM(CASE WHEN type='Expense' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as expenditure,
                COUNT(*) as tx_count,
                COUNT(DISTINCT substr(date, 1, 7)) as active_months,
                COUNT(DISTINCT date) as active_days,
                MIN(date) as min_date,
                MAX(date) as max_date
            FROM transactions
            WHERE 1=1 {date_condition}
        """)
        row = cur.fetchone()

        # Needs Review Count (across entire ledger)
        cur.execute("SELECT COUNT(*) FROM transactions WHERE flag != '' AND is_review_resolved=0")
        pending_review = cur.fetchone()[0]

        income = row['income'] or 0.0
        expenditure = row['expenditure'] or 0.0
        net = income - expenditure
        active_months = max(1, row['active_months'] or 1)
        active_days = max(1, row['active_days'] or 1)

        data = {
            "window": window,
            "income": income,
            "expenditure": expenditure,
            "net_cash_flow": net,
            "avg_monthly_expenditure": expenditure / active_months,
            "avg_daily_expenditure": expenditure / active_days,
            "transaction_count": row['tx_count'],
            "pending_review_count": pending_review,
            "active_months": active_months,
            "active_days": active_days,
            "date_range": {
                "start": row['min_date'],
                "end": row['max_date']
            }
        }
        conn.close()
        self._send_json(data)

    def handle_get_transactions(self, query):
        page = max(1, int(query.get("page", [1])[0]))
        limit = min(200, max(1, int(query.get("limit", [25])[0])))
        offset = (page - 1) * limit

        search = query.get("search", [""])[0].strip()
        account = query.get("account", [""])[0].strip()
        tx_type = query.get("type", [""])[0].strip()
        group = query.get("group", [""])[0].strip()
        subcategory = query.get("subcategory", [""])[0].strip()
        flag = query.get("flag", [""])[0].strip()
        date_from = query.get("date_from", [""])[0].strip()
        date_to = query.get("date_to", [""])[0].strip()
        sort_by = query.get("sort_by", ["date"])[0].strip()
        order = query.get("order", ["desc"])[0].lower()

        allowed_sorts = {"date", "amount", "type", "account", "subcategory", "group_name"}
        if sort_by not in allowed_sorts:
            sort_by = "date"
        if order not in {"asc", "desc"}:
            order = "desc"

        where_clauses = ["1=1"]
        params = []

        if search:
            where_clauses.append("(description LIKE ? OR merchant LIKE ? OR notes LIKE ? OR tx_id LIKE ?)")
            p = f"%{search}%"
            params.extend([p, p, p, p])

        if account:
            where_clauses.append("account = ?")
            params.append(account)

        if tx_type:
            where_clauses.append("type = ?")
            params.append(tx_type)

        if group:
            where_clauses.append("group_name = ?")
            params.append(group)

        if subcategory:
            where_clauses.append("subcategory = ?")
            params.append(subcategory)

        if flag:
            if flag == "any":
                where_clauses.append("flag != ''")
            elif flag == "needs-review":
                where_clauses.append("flag LIKE 'needs-review%' AND is_review_resolved = 0")
            elif flag == "resolved":
                where_clauses.append("is_review_resolved = 1")
            else:
                where_clauses.append("flag = ?")
                params.append(flag)

        if date_from:
            where_clauses.append("date >= ?")
            params.append(date_from)

        if date_to:
            where_clauses.append("date <= ?")
            params.append(date_to)

        where_sql = " AND ".join(where_clauses)

        conn = get_db()
        cur = conn.cursor()

        # Count total matching
        cur.execute(f"SELECT COUNT(*) FROM transactions WHERE {where_sql}", params)
        total_count = cur.fetchone()[0]

        # Fetch records
        cur.execute(f"""
            SELECT id, date, time, description, merchant, type, amount, currency, account,
                   method, group_name, category, subcategory, personal_or_business,
                   recurring, confidence, notes, flag, tx_id, is_review_resolved
            FROM transactions
            WHERE {where_sql}
            ORDER BY {sort_by} {order}, id {order}
            LIMIT ? OFFSET ?
        """, params + [limit, offset])
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        pages = (total_count + limit - 1) // limit
        self._send_json({
            "total": total_count,
            "page": page,
            "limit": limit,
            "pages": pages,
            "data": rows
        })

    def handle_get_monthly(self, query):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT month, income, expenditure, savings_investments, net_cash_flow, daily_avg_spend, top_subcategory
            FROM monthly_summary
            ORDER BY month ASC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        self._send_json({"data": rows})

    def handle_get_categories(self, query):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT group_name, subcategory, total_spent, percent_spend, monthly_avg, daily_avg, tx_count
            FROM categories
            ORDER BY total_spent DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        self._send_json({"data": rows})

    def handle_get_accounts(self, query):
        conn = get_db()
        cur = conn.cursor()
        # Compute live in/out totals from transactions to include any edits
        cur.execute("""
            SELECT account,
                   SUM(CASE WHEN type='Income' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as total_in,
                   SUM(CASE WHEN type='Expense' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as total_out,
                   COUNT(*) as tx_count
            FROM transactions
            WHERE account != ''
            GROUP BY account
            ORDER BY (total_in + total_out) DESC
        """)
        rows = []
        for r in cur.fetchall():
            tin = r['total_in'] or 0.0
            tout = r['total_out'] or 0.0
            rows.append({
                "account": r['account'],
                "total_in": tin,
                "total_out": tout,
                "net_flow": tin - tout,
                "tx_count": r['tx_count']
            })
        conn.close()
        self._send_json({"data": rows})

    def handle_get_recurring(self, query):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT item, group_name, total_spent, distinct_months, est_monthly_equiv
            FROM recurring_expenses
            ORDER BY est_monthly_equiv DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        self._send_json({"data": rows})

    def handle_get_needs_review(self, query):
        flag_filter = query.get("flag", [""])[0].strip()
        conn = get_db()
        cur = conn.cursor()

        where_clause = "WHERE flag != '' AND is_review_resolved = 0"
        params = []
        if flag_filter:
            where_clause += " AND flag = ?"
            params.append(flag_filter)

        cur.execute(f"""
            SELECT id, date, description, merchant, type, amount, account, group_name, subcategory, flag, confidence, notes, tx_id
            FROM transactions
            {where_clause}
            ORDER BY date DESC
        """, params)
        rows = [dict(r) for r in cur.fetchall()]

        # Summary of flag counts
        cur.execute("SELECT flag, count(*) FROM transactions WHERE flag != '' AND is_review_resolved = 0 GROUP BY flag")
        flag_counts = dict(cur.fetchall())
        conn.close()

        self._send_json({
            "total": len(rows),
            "flag_counts": flag_counts,
            "data": rows
        })

    def handle_get_filter_options(self):
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT DISTINCT account FROM transactions WHERE account != '' ORDER BY account ASC")
        accounts = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT DISTINCT group_name FROM transactions WHERE group_name != '' ORDER BY group_name ASC")
        groups = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT DISTINCT subcategory FROM transactions WHERE subcategory != '' ORDER BY subcategory ASC")
        subcategories = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT DISTINCT flag FROM transactions WHERE flag != '' ORDER BY flag ASC")
        flags = [r[0] for r in cur.fetchall()]

        conn.close()
        self._send_json({
            "accounts": accounts,
            "groups": groups,
            "subcategories": subcategories,
            "flags": flags
        })

    def handle_create_transaction(self, body):
        required = ["date", "type", "amount", "account"]
        for f in required:
            if f not in body or not body[f]:
                self._send_json({"error": f"Missing required field '{f}'"}, status=400)
                return

        amt = float(str(body["amount"]).replace(",", "").strip())
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO transactions (
                date, time, description, merchant, type, amount, currency, account,
                method, group_name, category, subcategory, personal_or_business,
                recurring, source, confidence, notes, flag, tx_id, is_review_resolved
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            body.get("date"),
            body.get("time", ""),
            body.get("description", ""),
            body.get("merchant", ""),
            body.get("type"),
            amt,
            body.get("currency", "UGX"),
            body.get("account"),
            body.get("method", body.get("account")),
            body.get("group_name", "Other"),
            body.get("category", ""),
            body.get("subcategory", "General"),
            body.get("personal_or_business", "Personal"),
            body.get("recurring", ""),
            "manual_entry",
            "high",
            body.get("notes", ""),
            body.get("flag", ""),
            body.get("tx_id", f"manual-{os.urandom(4).hex()}")
        ))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
        self._send_json({"status": "created", "id": new_id}, status=201)

    def handle_update_transaction(self, tx_id, body):
        conn = get_db()
        cur = conn.cursor()

        allowed_fields = [
            "subcategory", "group_name", "category", "notes",
            "flag", "is_review_resolved", "amount", "type", "account"
        ]
        updates = []
        params = []
        for k in allowed_fields:
            if k in body:
                updates.append(f"{k} = ?")
                params.append(body[k])

        if not updates:
            conn.close()
            self._send_json({"error": "No valid fields provided for update"}, status=400)
            return

        params.append(tx_id)
        cur.execute(f"UPDATE transactions SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()
        self._send_json({"status": "updated", "id": tx_id})

    def handle_batch_review(self, body):
        ids = body.get("ids", [])
        action = body.get("action")  # 'resolve', 'dismiss', 'categorize'
        subcategory = body.get("subcategory")
        group_name = body.get("group_name")

        if not ids:
            self._send_json({"error": "No IDs provided"}, status=400)
            return

        conn = get_db()
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in ids)

        if action == "resolve":
            cur.execute(f"UPDATE transactions SET is_review_resolved = 1 WHERE id IN ({placeholders})", ids)
        elif action == "dismiss":
            cur.execute(f"UPDATE transactions SET flag = '', is_review_resolved = 1 WHERE id IN ({placeholders})", ids)
        elif action == "categorize":
            params = [subcategory, group_name or "Other"] + ids
            cur.execute(f"""
                UPDATE transactions 
                SET subcategory = ?, group_name = ?, is_review_resolved = 1 
                WHERE id IN ({placeholders})
            """, params)

        conn.commit()
        conn.close()
        self._send_json({"status": "batch_completed", "count": len(ids)})

    def handle_chat_stream(self, body):
        message = body.get("message", "").strip()
        history = body.get("history", [])

        if not message:
            self._send_json({"error": "Message cannot be empty"}, status=400)
            return

        # Prepare SSE headers
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            for sse_event in generate_chat_stream(message, history):
                self.wfile.write(sse_event.encode("utf-8"))
                self.wfile.flush()
        except BrokenPipeError:
            pass
        except Exception as e:
            err_data = json.dumps({"type": "FINAL_RESPONSE", "content": f"\n\n**Error**: {str(e)}"})
            self.wfile.write(f"data: {err_data}\n\ndata: [DONE]\n\n".encode("utf-8"))
            self.wfile.flush()

def run_server(port=8000):
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, FinanceAPIHandler)
    print(f"Personal Finance Tracker App running at http://localhost:{port}", flush=True)
    httpd.serve_forever()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    run_server(port)
