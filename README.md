# 📊 Personal Finance Tracker & AI Financial Analyst

A high-performance personal finance tracking web application and AI assistant built from 4,221 financial transactions spanning August 2020 through September 2026 (~UGX 421M total transaction volume).

Designed specifically for Ugandan multi-channel transactions (MTN Mobile Money, Stanbic Bank, Cash, FlexiPay, Wise).

---

## 🌟 Features

- **Executive KPI Dashboard**: Total income, core window expenditure, net cash flow, daily and monthly averages, and spending velocity.
- **Interactive ECharts Visualizations**:
  - Monthly cash flow trends with stacked bar charts and net surplus line overlays.
  - Expense breakdown by category and subcategory with interactive ring charts.
  - Category comparative horizontal bar charts with budget percentages.
  - Accounts flow & transfer dynamics (Bank, Mobile Money, Cash).
- **Full Transaction Ledger**: Search, filter by transaction type, account, spending group, and flags, with responsive pagination and quick drawer inspector.
- **Needs Review Workbench**: Triage flagged transactions (unassigned categories, inter-account transfers, family contributions, unverified income) with one-click resolution and batch dismissal.
- **AI Financial Analyst**: Embedded Gemini AI chat drawer with streaming thoughts (`THOUGHT`), grounded local analytics fallback, and contextual quick prompt suggestions.
- **Passcode Protection**: Built-in privacy lock screen (default passcode: `2026` or configured via `APP_PASSWORD` environment variable).
- **Lightweight & Fast**: Zero-pip, zero-npm runtime using pure Python 3 standard library (`http.server`, `sqlite3`, `json`, `urllib`).

---

## 🚀 Quick Start (Local)

1. Clone or download this repository.
2. Seed the database from CSV ledgers:
   ```bash
   python3 seed_data.py
   ```
3. Start the server:
   ```bash
   python3 server.py 8000
   ```
4. Open [http://localhost:8000](http://localhost:8000) in your browser.
5. Enter passcode `2026` to unlock your financial ledger.

---

## ☁️ Deployment to Render

This application is 100% cloud-ready for Render:

1. Push this repository to GitHub (Private or Public).
2. Go to your [Render Dashboard](https://dashboard.render.com).
3. Click **New +** -> **Web Service** (or **Blueprint**).
4. Connect this GitHub repository.
5. Configure settings:
   - **Environment**: `Python`
   - **Build Command**: `python3 seed_data.py`
   - **Start Command**: `python3 server.py`
6. Under **Environment Variables**, optionally set:
   - `APP_PASSWORD`: Your custom passcode (defaults to `2026` if unset).
   - `GEMINI_API_KEY`: Your Google Gemini API key for cloud AI generation (optional; the app automatically falls back to grounded local SQLite analytics if no key is provided).
7. Click **Deploy Web Service**!
