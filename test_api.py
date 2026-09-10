#!/usr/bin/env python3
"""
Unit and Integration Tests for Financial Tracker API & Analytics Engine.
"""

import unittest
import sqlite3
import os
import json
from ai_engine import generate_chat_stream, run_local_analytics

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "finance.db")

class TestFinanceApp(unittest.TestCase):

    def setUp(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()

    def test_database_integrity(self):
        """Verify the exact count of transactions and expenditure totals match spreadsheet benchmarks."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM transactions")
        tx_count = cur.fetchone()[0]
        self.assertEqual(tx_count, 4221, "Total transactions must be exactly 4221")

        # Full ledger expense benchmark: 218,427,499.00 UGX
        cur.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND flag != 'transfer-between-own-accounts'")
        full_exp = cur.fetchone()[0]
        self.assertAlmostEqual(full_exp, 218427499.0, delta=1.0, msg="Full ledger expenditure mismatch")

        # Core window expense benchmark: 203,994,619.00 UGX
        cur.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND date >= '2022-03-01' AND flag != 'transfer-between-own-accounts'")
        core_exp = cur.fetchone()[0]
        self.assertAlmostEqual(core_exp, 203994619.0, delta=1.0, msg="Core window expenditure mismatch")

    def test_categories_aggregation(self):
        """Verify categories table has correct data."""
        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM categories")
        count = cur.fetchone()[0]
        self.assertGreater(count, 20)

        # Housing should be the top spending category
        cur.execute("SELECT subcategory, total_spent FROM categories ORDER BY total_spent DESC LIMIT 1")
        top_cat = cur.fetchone()
        self.assertEqual(top_cat['subcategory'], "Housing")
        self.assertAlmostEqual(top_cat['total_spent'], 44024250.0, delta=100.0)

    def test_accounts_summary(self):
        """Verify accounts summary contains Mobile Money and Bank."""
        cur = self.conn.cursor()
        cur.execute("SELECT account, total_in, total_out FROM accounts_summary")
        accs = {r['account']: r for r in cur.fetchall()}
        self.assertIn("Bank", accs)
        self.assertIn("Mobile Money", accs)
        self.assertGreater(accs["Bank"]["total_in"], 100000000)

    def test_needs_review_flags(self):
        """Verify needs review items are properly flagged."""
        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM transactions WHERE flag != '' AND is_review_resolved=0")
        review_count = cur.fetchone()[0]
        self.assertEqual(review_count, 541, "Must have 541 flagged transactions initially")

    def test_ai_engine_stream(self):
        """Verify AI Engine yields SSE formatted messages with thoughts, final responses, and suggestions."""
        events = list(generate_chat_stream("What are my top recurring expenses?"))
        self.assertTrue(any("THOUGHT" in e for e in events), "AI stream must contain thoughts")
        self.assertTrue(any("FINAL_RESPONSE" in e for e in events), "AI stream must contain final response")
        self.assertTrue(any("SUGGESTION" in e for e in events), "AI stream must contain suggestions")
        self.assertTrue(events[-1].strip() == "data: [DONE]", "AI stream must terminate with [DONE]")

    def test_ai_engine_merchant_query(self):
        """Verify AI engine handles specific merchant lookups accurately."""
        events = list(generate_chat_stream("How much did I receive from Ada?"))
        full_text = "".join(events)
        self.assertIn("Ada", full_text)
        self.assertIn("UGX", full_text)

    def test_http_api_endpoints(self):
        """Verify HTTP endpoints using simulated HTTP request/response buffers."""
        import io
        from server import FinanceAPIHandler

        class MockSocket:
            def __init__(self, request_bytes):
                self.rfile = io.BytesIO(request_bytes)
                self.wfile = io.BytesIO()

            def sendall(self, data):
                self.wfile.write(data)

            def write(self, data):
                self.wfile.write(data)

            def flush(self):
                self.wfile.flush()

            def makefile(self, mode, *args, **kwargs):
                if 'b' in mode:
                    if 'r' in mode:
                        return self.rfile
                    else:
                        return self
                raise NotImplementedError

        def call_handler(request_str):
            sock = MockSocket(request_str.encode('utf-8'))
            handler = FinanceAPIHandler(sock, ('127.0.0.1', 54321), None)
            sock.wfile.seek(0)
            raw_response = sock.wfile.read().decode('utf-8', errors='replace')
            status_line = raw_response.split('\r\n')[0]
            parts = raw_response.split('\r\n\r\n', 1)
            body = parts[1] if len(parts) > 1 else ''
            return status_line, body

        # 1. Test unauthorized access returns 401
        status, body = call_handler("GET /api/stats?window=core HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertIn("401 Unauthorized", status)

        # 2. Test failed login
        bad_login = json.dumps({"password": "wrongpassword"})
        status, body = call_handler(
            f"POST /api/auth/login HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(bad_login)}\r\n\r\n{bad_login}"
        )
        self.assertIn("401 Unauthorized", status)

        # 3. Test successful login
        good_login = json.dumps({"password": "2026"})
        status, body = call_handler(
            f"POST /api/auth/login HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(good_login)}\r\n\r\n{good_login}"
        )
        self.assertIn("200 OK", status)
        auth_data = json.loads(body)
        self.assertIn("token", auth_data)
        token = auth_data["token"]
        auth_header = f"Authorization: Bearer {token}\r\n"

        # 4. Test /api/stats?window=core with auth
        status, body = call_handler(f"GET /api/stats?window=core HTTP/1.1\r\nHost: localhost\r\n{auth_header}\r\n")
        self.assertIn("200 OK", status)
        stats = json.loads(body)
        self.assertEqual(stats["window"], "core")
        self.assertAlmostEqual(stats["expenditure"], 203994619.0, delta=1.0)

        # 5. Test /api/transactions
        status, body = call_handler(f"GET /api/transactions?limit=2 HTTP/1.1\r\nHost: localhost\r\n{auth_header}\r\n")
        self.assertIn("200 OK", status)
        txs = json.loads(body)
        self.assertEqual(len(txs["data"]), 2)
        self.assertEqual(txs["total"], 4221)

        # 6. Test /api/categories
        status, body = call_handler(f"GET /api/categories HTTP/1.1\r\nHost: localhost\r\n{auth_header}\r\n")
        self.assertIn("200 OK", status)
        cats = json.loads(body)
        self.assertGreater(len(cats["data"]), 10)

        # 7. Test /api/accounts
        status, body = call_handler(f"GET /api/accounts HTTP/1.1\r\nHost: localhost\r\n{auth_header}\r\n")
        self.assertIn("200 OK", status)
        accs = json.loads(body)
        self.assertGreater(len(accs["data"]), 5)

        # 8. Test /api/filter-options
        status, body = call_handler(f"GET /api/filter-options HTTP/1.1\r\nHost: localhost\r\n{auth_header}\r\n")
        self.assertIn("200 OK", status)
        filters = json.loads(body)
        self.assertIn("accounts", filters)
        self.assertIn("groups", filters)

        # 9. Test static file serving /index.html (no auth needed)
        status, body = call_handler("GET /index.html HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertIn("200 OK", status)
        self.assertIn("Financial Tracker", body)

        # 10. Test POST /api/transactions
        post_body = json.dumps({
            "date": "2026-09-08",
            "type": "Expense",
            "amount": 45000,
            "account": "Mobile Money",
            "description": "Test Grocery Store",
            "subcategory": "Groceries",
            "group_name": "Living"
        })
        status, body = call_handler(
            f"POST /api/transactions HTTP/1.1\r\nHost: localhost\r\n{auth_header}Content-Length: {len(post_body)}\r\n\r\n{post_body}"
        )
        self.assertIn("201 Created", status)
        res = json.loads(body)
        new_id = res["id"]

        # 11. Test PUT /api/transactions/<id>
        put_body = json.dumps({
            "notes": "Updated note test",
            "subcategory": "Supermarket"
        })
        status, body = call_handler(
            f"PUT /api/transactions/{new_id} HTTP/1.1\r\nHost: localhost\r\n{auth_header}Content-Length: {len(put_body)}\r\n\r\n{put_body}"
        )
        self.assertIn("200 OK", status)

        # 12. Test POST /api/chat (SSE streaming)
        chat_body = json.dumps({"message": "How much did I spend on Housing?"})
        status, body = call_handler(
            f"POST /api/chat HTTP/1.1\r\nHost: localhost\r\n{auth_header}Content-Length: {len(chat_body)}\r\n\r\n{chat_body}"
        )
        self.assertIn("200 OK", status)
        self.assertIn("THOUGHT", body)
        self.assertIn("FINAL_RESPONSE", body)
        self.assertIn("[DONE]", body)

        # Clean up the test transaction
        cur = self.conn.cursor()
        cur.execute("DELETE FROM transactions WHERE id = ?", [new_id])
        self.conn.commit()

    def test_vercel_serverless_handler(self):
        """Verify Vercel serverless entry point api/index.py handles routing via __route__ query param."""
        from api.index import handler
        import io

        class MockReq:
            def __init__(self, raw_bytes):
                self.raw = raw_bytes
                self.resp = io.BytesIO()
            def makefile(self, mode, *args, **kwargs):
                if "r" in mode:
                    return io.BytesIO(self.raw)
                return self.resp
            def sendall(self, data):
                self.resp.write(data)

        # 1. Login
        login_data = json.dumps({"password": "2026"}).encode("utf-8")
        req1 = MockReq(b"POST /api/index.py?__route__=auth/login HTTP/1.1\r\nContent-Length: " + str(len(login_data)).encode() + b"\r\n\r\n" + login_data)
        h1 = handler(req1, ("127.0.0.1", 12345), None)
        res1 = req1.resp.getvalue().decode()
        self.assertIn("200 OK", res1)
        token = json.loads(res1.split("\r\n\r\n")[1])["token"]

        # 2. Authenticated stats call via Vercel route
        req2 = MockReq(f"GET /api/index.py?__route__=stats&window=core HTTP/1.1\r\nAuthorization: Bearer {token}\r\n\r\n".encode("utf-8"))
        h2 = handler(req2, ("127.0.0.1", 12345), None)
        res2 = req2.resp.getvalue().decode()
        self.assertIn("200 OK", res2)
        stats = json.loads(res2.split("\r\n\r\n")[1])
        self.assertEqual(stats["transaction_count"], 3679)

if __name__ == "__main__":
    unittest.main()
