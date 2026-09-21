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
import hashlib
from datetime import datetime, timedelta
import calendar
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from ai_engine import generate_chat_stream
import sync_engine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

def resolve_db_path():
    if os.environ.get("VERCEL"):
        tmp_db = "/tmp/finance.db"
        if os.path.exists(tmp_db) and os.path.getsize(tmp_db) > 0:
            return tmp_db
    
    candidates = [
        os.path.join(BASE_DIR, "finance.db"),
        os.path.join(os.getcwd(), "finance.db"),
        os.path.abspath("finance.db"),
        os.path.join(os.path.dirname(BASE_DIR), "finance.db"),
        "/var/task/finance.db"
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.getsize(p) > 0:
            if os.environ.get("VERCEL"):
                tmp_db = "/tmp/finance.db"
                try:
                    import shutil
                    shutil.copyfile(p, tmp_db)
                    return tmp_db
                except Exception as e:
                    print(f"Failed to copy db to /tmp: {e}", file=sys.stderr)
                    return p
            return p
    return os.path.join(BASE_DIR, "finance.db")

DB_PATH = resolve_db_path()

# Authentication / Passcode Lock Configuration
APP_PASSWORD = os.environ.get("APP_PASSWORD", "2026")
VALID_SESSIONS = set()

def get_session_token():
    return hashlib.sha256(f"finance-tracker-token-salt:{APP_PASSWORD}".encode("utf-8")).hexdigest()

def is_valid_token(token):
    if not token:
        return False
    if token in VALID_SESSIONS:
        return True
    if APP_PASSWORD and (token == APP_PASSWORD or token == get_session_token()):
        return True
    return False

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
        if is_valid_token(token):
            return True

    # 2. Cookie header
    cookie_header = headers.get("Cookie", "")
    for part in cookie_header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            if k == "finance_token" and is_valid_token(v):
                return True

    # 3. Query string token (for EventSource SSE)
    if query and "token" in query:
        token = query["token"][0]
        if is_valid_token(token):
            return True

    return False

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class FinanceAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        if directory is None:
            directory = PUBLIC_DIR
        super().__init__(*args, directory=directory, **kwargs)

    def _parse_request_path(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Vercel rewrite with __route__ parameter
        if "__route__" in query:
            route_val = query.pop("__route__")[0]
            path = "/api/" + route_val.lstrip("/")
        elif path in ("/api", "/api/", "/api/index.py"):
            # 2. Vercel / reverse-proxy header routing
            for h in ("x-matched-path", "x-forwarded-uri", "x-original-uri", "x-rewrite-url"):
                val = self.headers.get(h)
                if val and val.startswith("/api/"):
                    path = urllib.parse.urlparse(val).path
                    break

        return path, query

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
        path, query = self._parse_request_path()

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
                elif path == "/api/sync/status":
                    self.handle_get_sync_status()
                elif path == "/api/daily-glance":
                    self.handle_get_daily_glance(query)
                elif path == "/api/q3-report":
                    self.handle_get_q3_report()
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
        elif path == "/manifest.json":
            self.serve_file(os.path.join(PUBLIC_DIR, "manifest.json"), "application/manifest+json; charset=utf-8")
            return
        elif path == "/sw.js":
            self.serve_file(os.path.join(PUBLIC_DIR, "sw.js"), "application/javascript; charset=utf-8")
            return
        elif path in ("/icons/icon.svg", "/icon.svg"):
            self.serve_file(os.path.join(PUBLIC_DIR, "icons", "icon.svg"), "image/svg+xml")
            return
        elif path == "/reports/Q3_2026_Expense_Report.pdf":
            self.serve_file(os.path.join(PUBLIC_DIR, "reports", "Q3_2026_Expense_Report.pdf"), "application/pdf")
            return
        elif path == "/reports/Q3_2026_Expense_Report.html":
            self.serve_file(os.path.join(PUBLIC_DIR, "reports", "Q3_2026_Expense_Report.html"), "text/html; charset=utf-8")
            return

        super().do_GET()

    def do_POST(self):
        path, query = self._parse_request_path()
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
                token = get_session_token()
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
        if not is_authenticated(self.headers, query):
            self._send_json({"error": "Unauthorized. Passcode required."}, status=401)
            return

        if path == "/api/chat":
            self.handle_chat_stream(body)
            return

        if path == "/api/transactions":
            self.handle_create_transaction(body)
            return

        if path == "/api/transactions/quick":
            self.handle_quick_transaction(body)
            return

        if path == "/api/import":
            self.handle_import_transactions(post_data, body, query)
            return

        if path == "/api/batch-review":
            self.handle_batch_review(body)
            return

        self._send_json({"error": "Endpoint not found"}, status=404)

    def do_PUT(self):
        path, query = self._parse_request_path()
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

        # Prepare SSE headers (unbuffered, close on completion)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        self.close_connection = True

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

    def handle_get_sync_status(self):
        meta_path = os.path.join(DATA_DIR, "meta.json")
        meta = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                pass
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM transactions")
        total_tx = cur.fetchone()[0]
        cur.execute("SELECT MIN(date), MAX(date) FROM transactions")
        min_d, max_d = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM transactions WHERE flag != '' AND is_review_resolved = 0")
        pending_review = cur.fetchone()[0]
        conn.close()
        
        self._send_json({
            "status": "healthy",
            "total_transactions": total_tx,
            "date_range": {"min": min_d, "max": max_d},
            "pending_review_count": pending_review,
            "meta": meta,
            "db_path": DB_PATH
        })

    def handle_get_daily_glance(self, query):
        conn = get_db()
        cur = conn.cursor()

        # Find latest available date in db if not specified
        cur.execute("SELECT MAX(date) FROM transactions")
        max_db_date = cur.fetchone()[0] or datetime.today().strftime("%Y-%m-%d")

        requested_date = query.get("date", [max_db_date])[0].strip()
        if not requested_date:
            requested_date = max_db_date

        try:
            target_dt = datetime.strptime(requested_date, "%Y-%m-%d")
        except ValueError:
            target_dt = datetime.strptime(max_db_date, "%Y-%m-%d")
            requested_date = max_db_date

        prev_dt = target_dt - timedelta(days=1)
        prev_date = prev_dt.strftime("%Y-%m-%d")
        current_month = requested_date[:7]

        # 1. Today's stats
        cur.execute("""
            SELECT 
                SUM(CASE WHEN type='Expense' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as spend,
                SUM(CASE WHEN type='Income' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as income,
                COUNT(*) as tx_count
            FROM transactions
            WHERE date = ?
        """, (requested_date,))
        today_row = cur.fetchone()
        today_spend = (today_row['spend'] or 0.0) if today_row else 0.0
        today_income = (today_row['income'] or 0.0) if today_row else 0.0
        today_count = (today_row['tx_count'] or 0) if today_row else 0

        # Today's transactions
        cur.execute("""
            SELECT id, date, time, description, amount, type, category, subcategory, account, flag
            FROM transactions
            WHERE date = ?
            ORDER BY time DESC, id DESC
        """, (requested_date,))
        today_txs = [dict(r) for r in cur.fetchall()]

        # 2. Yesterday's stats
        cur.execute("""
            SELECT 
                SUM(CASE WHEN type='Expense' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as spend,
                COUNT(*) as tx_count
            FROM transactions
            WHERE date = ?
        """, (prev_date,))
        prev_row = cur.fetchone()
        prev_spend = (prev_row['spend'] or 0.0) if prev_row else 0.0
        prev_count = (prev_row['tx_count'] or 0) if prev_row else 0

        # Yesterday's transactions
        cur.execute("""
            SELECT id, date, time, description, amount, type, category, subcategory, account, flag
            FROM transactions
            WHERE date = ?
            ORDER BY time DESC, id DESC
        """, (prev_date,))
        prev_txs = [dict(r) for r in cur.fetchall()]

        # 3. Rolling 7 days up to target_date
        last_7_days = []
        for i in range(6, -1, -1):
            day_dt = target_dt - timedelta(days=i)
            day_str = day_dt.strftime("%Y-%m-%d")
            day_name = day_dt.strftime("%a")
            cur.execute("""
                SELECT 
                    SUM(CASE WHEN type='Expense' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as spend,
                    SUM(CASE WHEN type='Income' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as income,
                    COUNT(*) as tx_count
                FROM transactions
                WHERE date = ?
            """, (day_str,))
            d_row = cur.fetchone()
            last_7_days.append({
                "date": day_str,
                "day_name": day_name,
                "spend": (d_row['spend'] or 0.0) if d_row else 0.0,
                "income": (d_row['income'] or 0.0) if d_row else 0.0,
                "count": (d_row['tx_count'] or 0) if d_row else 0
            })

        # 4. Month to Date Pacing
        cur.execute("""
            SELECT 
                SUM(CASE WHEN type='Expense' AND flag != 'transfer-between-own-accounts' THEN amount ELSE 0 END) as month_spend,
                COUNT(DISTINCT date) as active_days,
                COUNT(*) as month_tx_count
            FROM transactions
            WHERE date LIKE ? || '%'
        """, (current_month,))
        m_row = cur.fetchone()
        month_spend = (m_row['month_spend'] or 0.0) if m_row else 0.0
        active_days = max(1, (m_row['active_days'] or 1) if m_row else 1)
        daily_avg = month_spend / active_days

        year, month_num = int(current_month[:4]), int(current_month[5:7])
        _, days_in_month = calendar.monthrange(year, month_num)
        projected_month_total = daily_avg * days_in_month

        # Top 3 subcategory spending drivers for current month
        cur.execute("""
            SELECT subcategory, group_name, SUM(amount) as total_spent, COUNT(*) as tx_count
            FROM transactions
            WHERE date LIKE ? || '%' AND type='Expense' AND flag != 'transfer-between-own-accounts' AND subcategory != ''
            GROUP BY subcategory
            ORDER BY total_spent DESC
            LIMIT 3
        """, (current_month,))
        top_subcats = []
        for r in cur.fetchall():
            tot = r['total_spent'] or 0.0
            pct = (tot / month_spend * 100.0) if month_spend > 0 else 0.0
            top_subcats.append({
                "subcategory": r['subcategory'],
                "group_name": r['group_name'],
                "total_spent": tot,
                "percent": round(pct, 1),
                "count": r['tx_count']
            })

        conn.close()

        self._send_json({
            "target_date": requested_date,
            "current_month": current_month,
            "today": {
                "date": requested_date,
                "spend": today_spend,
                "income": today_income,
                "tx_count": today_count,
                "transactions": today_txs
            },
            "yesterday": {
                "date": prev_date,
                "spend": prev_spend,
                "tx_count": prev_count,
                "transactions": prev_txs
            },
            "last_7_days": last_7_days,
            "month_to_date": {
                "month": current_month,
                "total_spend": month_spend,
                "active_days": active_days,
                "daily_avg": round(daily_avg, 2),
                "days_in_month": days_in_month,
                "projected_month_total": round(projected_month_total, 2),
                "top_categories": top_subcats
            }
        })

    def handle_get_q3_report(self):
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT COUNT(*), SUM(amount)
            FROM transactions
            WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
              AND flag != 'transfer-between-own-accounts'
        """)
        cnt, total_q3 = cur.fetchone()
        total_q3 = total_q3 or 0.0

        cur.execute("""
            SELECT date, description, amount, account, notes
            FROM transactions
            WHERE subcategory = 'Housing' AND date >= '2026-07-01' AND date <= '2026-09-30'
              AND description LIKE 'Rent%'
            ORDER BY date ASC
        """)
        rent_txs = [dict(r) for r in cur.fetchall()]
        total_rent = sum(r['amount'] for r in rent_txs)

        cur.execute("""
            SELECT date, description, amount, account
            FROM transactions
            WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
              AND subcategory = 'Loans & Lending'
            ORDER BY date DESC
        """)
        debt_txs = [dict(r) for r in cur.fetchall()]
        total_debt = sum(r['amount'] for r in debt_txs)

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

        cur.execute("""
            SELECT date, description, amount, account
            FROM transactions
            WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
              AND (subcategory = 'Utilities' OR description LIKE '%Yaka%' OR description LIKE '%WiFi%' OR description LIKE '%Electricity%')
            ORDER BY date DESC
        """)
        util_txs = [dict(r) for r in cur.fetchall()]
        total_utils = sum(r['amount'] for r in util_txs)

        months_data = {}
        for m in ['2026-07', '2026-08', '2026-09']:
            cur.execute("""
                SELECT SUM(amount), COUNT(*)
                FROM transactions
                WHERE type = 'Expense' AND date LIKE ? AND flag != 'transfer-between-own-accounts'
            """, (f"{m}%",))
            exp, cnt_m = cur.fetchone()
            months_data[m] = {"spend": exp or 0.0, "count": cnt_m or 0}

        cur.execute("""
            SELECT group_name, subcategory, COUNT(*) as tx_count, SUM(amount) as total_amt
            FROM transactions
            WHERE type = 'Expense' AND date >= '2026-07-01' AND date <= '2026-09-30'
              AND flag != 'transfer-between-own-accounts'
            GROUP BY group_name, subcategory
            ORDER BY total_amt DESC
        """)
        cat_rows = [dict(r) for r in cur.fetchall()]

        conn.close()

        fixed_overhead = total_rent + total_debt + total_subs + total_utils
        variable_spend = total_q3 - fixed_overhead

        self._send_json({
            "total_q3": total_q3,
            "tx_count": cnt,
            "fixed_overhead": fixed_overhead,
            "variable_spend": variable_spend,
            "rent": {"total": total_rent, "transactions": rent_txs},
            "debts": {"total": total_debt, "transactions": debt_txs},
            "subscriptions": {"total": total_subs, "transactions": sub_txs},
            "utilities": {"total": total_utils, "transactions": util_txs},
            "months": months_data,
            "top_categories": cat_rows[:15],
            "pdf_url": "/reports/Q3_2026_Expense_Report.pdf",
            "html_url": "/reports/Q3_2026_Expense_Report.html"
        })

    def handle_import_transactions(self, raw_post_data, body, query):
        dry_run = query.get("dry_run", ["false"])[0].lower() in ("true", "1") or body.get("dry_run", False)
        git_push = query.get("git_push", ["false"])[0].lower() in ("true", "1") or body.get("git_push", False)
        
        csv_text = ""
        # 1. Check if JSON body with csv_data or csv
        if isinstance(body, dict) and (body.get("csv_data") or body.get("csv")):
            csv_text = body.get("csv_data") or body.get("csv")
        # 2. Check Content-Type header
        content_type = self.headers.get("Content-Type", "")
        if not csv_text and ("text/csv" in content_type or "text/plain" in content_type):
            csv_text = raw_post_data.decode("utf-8", errors="replace")
        # 3. If multipart/form-data
        if not csv_text and "multipart/form-data" in content_type:
            raw_str = raw_post_data.decode("utf-8", errors="replace")
            lines = raw_str.splitlines()
            start = False
            content_lines = []
            for line in lines:
                if start:
                    if line.startswith("------"):
                        break
                    content_lines.append(line)
                elif not line.strip() and not start:
                    start = True
            csv_text = "\n".join(content_lines)
        # 4. Fallback: if raw body starts with common CSV header or text
        if not csv_text and raw_post_data:
            try:
                candidate = raw_post_data.decode("utf-8", errors="replace").strip()
                if "Date" in candidate or "UUID" in candidate or "Amount" in candidate:
                    csv_text = candidate
            except Exception:
                pass

        if not csv_text or not csv_text.strip():
            self._send_json({"error": "No CSV content provided. Provide 'csv_data' in JSON or raw CSV payload."}, status=400)
            return

        try:
            result = sync_engine.sync_from_csv_text(csv_text, git_push=git_push, dry_run=dry_run)
            self._send_json(result)
        except Exception as e:
            self._send_json({"error": f"Import failed: {str(e)}"}, status=500)

    def handle_quick_transaction(self, body):
        raw_date = body.get("date", "")
        norm_date = sync_engine.normalize_date(raw_date)
        tx_type = body.get("type", "Expense").capitalize()
        amount = sync_engine.parse_num(body.get("amount", 0))
        cat = body.get("category", "General").strip()
        account = body.get("account", "Mobile Money").strip() or "Mobile Money"
        desc = body.get("description", "").strip() or cat
        notes = body.get("notes", "").strip()
        
        g, sub, _ = sync_engine.PENNYWORTH_CATEGORY_MAP.get(cat, ("Other", cat, tx_type))
        record = {
            "date": norm_date,
            "time": datetime.now().strftime("%H:%M:%S"),
            "description": desc,
            "merchant": body.get("merchant", "").strip(),
            "type": tx_type,
            "amount": amount,
            "currency": body.get("currency", "UGX").strip() or "UGX",
            "account": account,
            "method": account,
            "group_name": g,
            "category": cat,
            "subcategory": sub,
            "personal_or_business": "Personal",
            "recurring": "",
            "source": "quick_api",
            "source_line": "",
            "confidence": "high",
            "notes": notes,
            "flag": "",
            "tx_id": body.get("tx_id", f"quick-{datetime.now().strftime('%Y%m%d%H%M%S')}-{os.urandom(3).hex()}"),
            "is_review_resolved": 0
        }
        res = sync_engine.ingest_records([record])
        self._send_json(res)

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
