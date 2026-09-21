/**
 * Application Controller for Financial Tracker.
 * Manages reactive dashboard state, ECharts visualizations, transactions ledger,
 * needs-review workbench, and Gemini AI streaming chat panel.
 */

// Global State
const state = {
  activeTab: 'dashboard',
  windowMode: 'core', // 'core' (2022-03+) or 'all'
  theme: localStorage.getItem('finance_theme') || 'dark',
  authToken: localStorage.getItem('finance_auth_token') || '',
  stats: null,
  filterOptions: { accounts: [], groups: [], subcategories: [], flags: [] },
  txFilters: {
    search: '',
    type: '',
    account: '',
    group: '',
    flag: '',
    date_from: '',
    date_to: '',
    page: 1,
    limit: 25,
    sort_by: 'date',
    order: 'desc'
  },
  txData: { total: 0, page: 1, pages: 1, data: [] },
  monthly: [],
  categories: [],
  accounts: [],
  recurring: [],
  reviewItems: [],
  selectedReviewIds: new Set(),
  activeReviewFlag: '',
  selectedTx: null,
  chatMessages: [
    {
      role: 'model',
      content: 'Hello! I am your personal financial analyst. I have full indexed access to your **4,221 transactions** (~421M UGX total flow across Mobile Money, Stanbic, Cash, FlexiPay, Wise, etc.). Ask me anything about your finances!',
      thoughts: '',
      suggestions: [
        'How much did I spend on Housing vs Medical?',
        'What are my biggest recurring monthly expenses?',
        'Show summary of transactions needing review'
      ]
    }
  ],
  isChatLoading: false,
  expandedThoughts: {}
};

// Authenticated Fetch Wrapper
async function authFetch(url, options = {}) {
  options.headers = options.headers || {};
  if (state.authToken) {
    if (options.headers instanceof Headers) {
      options.headers.set('Authorization', `Bearer ${state.authToken}`);
    } else {
      options.headers['Authorization'] = `Bearer ${state.authToken}`;
    }
  }
  const res = await fetch(url, options);
  if (res.status === 401 && !url.includes('/api/auth/')) {
    showLockScreen();
    throw new Error('Authentication required');
  }
  return res;
}

function showLockScreen() {
  const lock = document.getElementById('lockScreen');
  if (lock) {
    lock.classList.remove('hidden', 'opacity-0', 'pointer-events-none');
    setTimeout(() => document.getElementById('passcodeInput')?.focus(), 100);
  }
}

function hideLockScreen() {
  const lock = document.getElementById('lockScreen');
  if (lock) {
    lock.classList.add('opacity-0', 'pointer-events-none');
    setTimeout(() => lock.classList.add('hidden'), 300);
  }
}

async function handleUnlockSubmit(e) {
  e.preventDefault();
  const input = document.getElementById('passcodeInput');
  const errEl = document.getElementById('lockErrorMsg');
  const btn = document.getElementById('unlockBtn');
  const pass = input.value.trim();
  if (!pass) return;

  errEl.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Verifying...';

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pass })
    });
    const data = await res.json();
    if (res.ok && data.token) {
      state.authToken = data.token;
      localStorage.setItem('finance_auth_token', data.token);
      hideLockScreen();
      initApp();
    } else {
      errEl.textContent = data.error || 'Incorrect passcode. Please try again.';
      errEl.classList.remove('hidden');
      input.select();
    }
  } catch (err) {
    errEl.textContent = 'Connection error. Please check server.';
    errEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Unlock Ledger';
  }
}

async function lockApp() {
  if (state.authToken) {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: state.authToken })
      });
    } catch (e) {}
  }
  state.authToken = '';
  localStorage.removeItem('finance_auth_token');
  showLockScreen();
}

async function checkAuth() {
  try {
    const headers = state.authToken ? { 'Authorization': `Bearer ${state.authToken}` } : {};
    const res = await fetch('/api/auth/check', { headers });
    const data = await res.json();
    if (!data.auth_required || data.authenticated) {
      hideLockScreen();
      initApp();
    } else {
      showLockScreen();
    }
  } catch (err) {
    showLockScreen();
  }
}

function initApp() {
  loadStats();
  loadFilterOptions();
  loadMonthly();
  loadCategories();
  loadAccounts();
  loadRecurring();
  loadTransactions();
}

// Chart instances
let monthlyChart = null;
let categoryChart = null;
let analyticsBarChart = null;
let accountsFlowChart = null;
let searchDebounceTimer = null;

// Standard Palette (Zinc + Modern Tailwind accents)
const CHART_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1'
];

// --- Formatters ---
function formatUGX(val, compact = false) {
  const num = Number(val) || 0;
  if (compact) {
    if (Math.abs(num) >= 1_000_000_000) return (num / 1_000_000_000).toFixed(1) + 'B UGX';
    if (Math.abs(num) >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M UGX';
    if (Math.abs(num) >= 1_000) return (num / 1_000).toFixed(1) + 'K UGX';
  }
  return 'UGX ' + num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  const parts = dateStr.split('-');
  if (parts.length !== 3) return dateStr;
  const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
  return d.toLocaleDateString('en-US', { month: 'short', day: '2-digit', year: 'numeric' });
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Simple fast Markdown to HTML parser for Chat
function parseMarkdownToHtml(md) {
  if (!md) return '';
  let html = escapeHtml(md);

  // Headers (### Header)
  html = html.replace(/^### (.*$)/gim, '<h3 class="font-bold text-sm text-zinc-900 dark:text-zinc-100 mt-2 mb-1">$1</h3>');
  html = html.replace(/^## (.*$)/gim, '<h2 class="font-bold text-base text-zinc-900 dark:text-zinc-100 mt-3 mb-1.5">$1</h2>');

  // Bold & Italic
  html = html.replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>');
  html = html.replace(/\*(.*?)\*/gim, '<em>$1</em>');

  // Code
  html = html.replace(/`([^`]+)`/gim, '<code class="px-1 py-0.5 rounded bg-zinc-200 dark:bg-zinc-800 text-xs font-mono">$1</code>');

  // Blockquotes
  html = html.replace(/^> (.*$)/gim, '<blockquote class="border-l-2 border-blue-500 pl-2 text-xs italic text-zinc-600 dark:text-zinc-400 my-1">$1</blockquote>');

  // Tables
  const lines = html.split('\n');
  let inTable = false;
  let tableHtml = '';
  const newLines = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.startsWith('|') && line.endsWith('|')) {
      if (!inTable) {
        inTable = true;
        tableHtml = '<div class="overflow-x-auto my-2"><table class="w-full text-left text-xs border border-zinc-200 dark:border-zinc-700 border-collapse">';
      }
      const cells = line.split('|').slice(1, -1);
      const isHeaderSep = cells.every(c => c.trim().match(/^:?-+:?$/));

      if (isHeaderSep) {
        // separator, skip
      } else {
        const isHeaderRow = !tableHtml.includes('<tbody>') && !tableHtml.includes('<tr>');
        const tag = isHeaderRow ? 'th' : 'td';
        const rowClass = isHeaderRow ? 'bg-zinc-100 dark:bg-zinc-800/60 font-semibold' : 'border-t border-zinc-200 dark:border-zinc-800';
        tableHtml += `<tr class="${rowClass}">`;
        for (const c of cells) {
          tableHtml += `<${tag} class="p-1.5 px-2 border-r border-zinc-200 dark:border-zinc-800 last:border-r-0">${c.trim()}</${tag}>`;
        }
        tableHtml += '</tr>';
        if (isHeaderRow) tableHtml += '<tbody>';
      }
    } else {
      if (inTable) {
        tableHtml += '</tbody></table></div>';
        newLines.push(tableHtml);
        inTable = false;
        tableHtml = '';
      }
      newLines.push(line);
    }
  }
  if (inTable) {
    tableHtml += '</tbody></table></div>';
    newLines.push(tableHtml);
  }

  // Lists
  html = newLines.join('\n');
  html = html.replace(/^\s*-\s+(.*$)/gim, '<li class="ml-4 list-disc text-xs">$1</li>');

  // Paragraphs
  return html.split('\n\n').map(p => {
    p = p.trim();
    if (!p) return '';
    if (p.startsWith('<h') || p.startsWith('<div') || p.startsWith('<blockquote') || p.startsWith('<li')) return p;
    return `<p class="mb-1 text-xs leading-relaxed">${p}</p>`;
  }).join('');
}

// --- Theme Management ---
function applyTheme(theme) {
  state.theme = theme;
  localStorage.setItem('finance_theme', theme);
  const html = document.documentElement;
  if (theme === 'dark') {
    html.classList.add('dark');
  } else {
    html.classList.remove('dark');
  }
  refreshChartsTheme();
}

function toggleTheme() {
  applyTheme(state.theme === 'dark' ? 'light' : 'dark');
}

function refreshChartsTheme() {
  if (monthlyChart) initMonthlyChart();
  if (categoryChart) initCategoryChart();
  if (analyticsBarChart) initAnalyticsBarChart();
  if (accountsFlowChart) initAccountsFlowChart();
}

// --- Window Mode (Core vs All) ---
function setWindowMode(mode) {
  state.windowMode = mode;
  const coreBtn = document.getElementById('windowCoreBtn');
  const allBtn = document.getElementById('windowAllBtn');

  if (mode === 'core') {
    coreBtn.className = 'px-3 py-1.5 rounded-lg transition-all font-medium bg-white dark:bg-zinc-800 text-blue-600 dark:text-blue-400 shadow-sm';
    allBtn.className = 'px-3 py-1.5 rounded-lg transition-all text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200';
  } else {
    allBtn.className = 'px-3 py-1.5 rounded-lg transition-all font-medium bg-white dark:bg-zinc-800 text-blue-600 dark:text-blue-400 shadow-sm';
    coreBtn.className = 'px-3 py-1.5 rounded-lg transition-all text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200';
  }

  loadStats();
}

// --- Navigation Tabs ---
function switchTab(tabId) {
  state.activeTab = tabId;
  const tabs = ['daily', 'q3-report', 'dashboard', 'transactions', 'analytics', 'review', 'recurring'];
  tabs.forEach(t => {
    const tabEl = document.getElementById(`tab-${t}`);
    const mobTabEl = document.getElementById(`mobTab-${t}`);
    const viewEl = document.getElementById(`view-${t}`);
    if (t === tabId) {
      tabEl?.classList.add('active');
      mobTabEl?.classList.add('active');
      viewEl?.classList.remove('hidden');
    } else {
      tabEl?.classList.remove('active');
      mobTabEl?.classList.remove('active');
      viewEl?.classList.add('hidden');
    }
  });

  if (tabId === 'daily') {
    loadDailyGlance();
    setTimeout(() => glanceSparklineChart?.resize(), 50);
  } else if (tabId === 'q3-report') {
    loadQ3Report();
  } else if (tabId === 'dashboard') {
    setTimeout(() => {
      monthlyChart?.resize();
      categoryChart?.resize();
    }, 50);
  } else if (tabId === 'transactions') {
    loadTransactions();
  } else if (tabId === 'analytics') {
    setTimeout(() => analyticsBarChart?.resize(), 50);
  } else if (tabId === 'review') {
    loadNeedsReview();
  } else if (tabId === 'recurring') {
    setTimeout(() => accountsFlowChart?.resize(), 50);
  }
}

// --- Data Fetching ---
async function loadStats() {
  try {
    const res = await authFetch(`/api/stats?window=${state.windowMode}`);
    const data = await res.json();
    state.stats = data;

    // Populate KPIs
    document.getElementById('kpiIncome').textContent = formatUGX(data.income);
    document.getElementById('kpiExpenditure').textContent = formatUGX(data.expenditure);
    document.getElementById('kpiNet').textContent = formatUGX(data.net_cash_flow);
    document.getElementById('kpiMonthlyAvg').textContent = formatUGX(data.avg_monthly_expenditure);
    document.getElementById('kpiDailyAvg').textContent = formatUGX(data.avg_daily_expenditure);

    // Header date range
    if (data.date_range && data.date_range.start) {
      document.getElementById('headerDateRange').textContent =
        `${formatDate(data.date_range.start)} → ${formatDate(data.date_range.end)} (${data.transaction_count.toLocaleString()} transactions)`;
    }

    // Tab badges
    document.getElementById('tabTxBadge').textContent = data.transaction_count.toLocaleString();
    document.getElementById('tabReviewBadge').textContent = data.pending_review_count.toLocaleString();
    const countAllEl = document.getElementById('countAllFlags');
    if (countAllEl) countAllEl.textContent = data.pending_review_count;

    // Color net cash flow
    const netEl = document.getElementById('kpiNet');
    if (data.net_cash_flow >= 0) {
      netEl.className = 'text-xl sm:text-2xl font-extrabold font-mono text-emerald-600 dark:text-emerald-400';
    } else {
      netEl.className = 'text-xl sm:text-2xl font-extrabold font-mono text-rose-600 dark:text-rose-400';
    }
  } catch (err) {
    console.error('Error loading stats:', err);
  }
}

async function loadFilterOptions() {
  try {
    const res = await authFetch('/api/filter-options');
    const data = await res.json();
    state.filterOptions = data;

    const accSelect = document.getElementById('filterAccount');
    if (accSelect) {
      accSelect.innerHTML = '<option value="">All Accounts</option>';
      data.accounts.forEach(a => {
        accSelect.innerHTML += `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`;
      });
    }

    const groupSelect = document.getElementById('filterGroup');
    if (groupSelect) {
      groupSelect.innerHTML = '<option value="">All Groups</option>';
      data.groups.forEach(g => {
        groupSelect.innerHTML += `<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`;
      });
    }
  } catch (err) {
    console.error('Error loading filter options:', err);
  }
}

async function loadMonthly() {
  try {
    const res = await authFetch('/api/monthly');
    const json = await res.json();
    state.monthly = json.data || [];
    initMonthlyChart();
  } catch (err) {
    console.error('Error loading monthly summary:', err);
  }
}

async function loadCategories() {
  try {
    const res = await authFetch('/api/categories');
    const json = await res.json();
    state.categories = json.data || [];
    initCategoryChart();
    renderCategoriesTable();
    initAnalyticsBarChart();
  } catch (err) {
    console.error('Error loading categories:', err);
  }
}

async function loadAccounts() {
  try {
    const res = await authFetch('/api/accounts');
    const json = await res.json();
    state.accounts = json.data || [];
    renderAccountsWidgets();
    initAccountsFlowChart();
  } catch (err) {
    console.error('Error loading accounts:', err);
  }
}

async function loadRecurring() {
  try {
    const res = await authFetch('/api/recurring');
    const json = await res.json();
    state.recurring = json.data || [];
    renderRecurringTable();
  } catch (err) {
    console.error('Error loading recurring expenses:', err);
  }
}

// --- ECharts Visualizations ---
function isDark() {
  return document.documentElement.classList.contains('dark');
}

function getChartTheme() {
  const dark = isDark();
  return {
    textColor: dark ? '#a1a1aa' : '#64748b',
    gridColor: dark ? '#27272a' : '#f1f5f9',
    tooltipBg: dark ? '#18181b' : '#ffffff',
    tooltipBorder: dark ? '#3f3f46' : '#e2e8f0',
    tooltipText: dark ? '#fafafa' : '#0f172a'
  };
}

function initMonthlyChart() {
  const dom = document.getElementById('monthlyChart');
  if (!dom || !state.monthly.length) return;
  if (!monthlyChart) monthlyChart = echarts.init(dom);

  const t = getChartTheme();
  // Filter for clean display
  const months = state.monthly.map(m => m.month);
  const income = state.monthly.map(m => m.income);
  const expense = state.monthly.map(m => m.expenditure);
  const net = state.monthly.map(m => m.net_cash_flow);

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 12 },
      formatter: function (params) {
        let res = `<div class="font-bold text-xs mb-1">${params[0].axisValue}</div>`;
        params.forEach(p => {
          res += `<div class="flex items-center justify-between gap-4 text-xs">
            <span>${p.marker} ${p.seriesName}:</span>
            <span class="font-mono font-semibold">${formatUGX(p.value)}</span>
          </div>`;
        });
        return res;
      }
    },
    legend: { show: false },
    grid: { left: '3%', right: '3%', bottom: '8%', top: '5%', containLabel: true },
    xAxis: {
      type: 'category',
      data: months,
      axisLabel: { color: t.textColor, fontSize: 10, rotate: 30 },
      axisLine: { lineStyle: { color: t.gridColor } }
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: t.textColor,
        fontSize: 10,
        formatter: v => (v / 1_000_000).toFixed(0) + 'M'
      },
      splitLine: { lineStyle: { color: t.gridColor, type: 'dashed' } }
    },
    series: [
      {
        name: 'Income',
        type: 'bar',
        data: income,
        itemStyle: { color: '#10b981', borderRadius: [4, 4, 0, 0] }
      },
      {
        name: 'Expense',
        type: 'bar',
        data: expense,
        itemStyle: { color: '#f43f5e', borderRadius: [4, 4, 0, 0] }
      },
      {
        name: 'Net Flow',
        type: 'line',
        data: net,
        itemStyle: { color: '#3b82f6' },
        lineStyle: { width: 2.5 },
        symbol: 'none',
        smooth: true
      }
    ]
  };
  monthlyChart.setOption(option, true);
}

function initCategoryChart() {
  const dom = document.getElementById('categoryChart');
  if (!dom || !state.categories.length) return;
  if (!categoryChart) categoryChart = echarts.init(dom);

  const t = getChartTheme();
  // Top 8 categories + Other
  const top8 = state.categories.slice(0, 7);
  const otherTotal = state.categories.slice(7).reduce((acc, c) => acc + c.total_spent, 0);

  const pieData = top8.map(c => ({ name: c.subcategory, value: c.total_spent }));
  if (otherTotal > 0) pieData.push({ name: 'Other Categories', value: otherTotal });

  const option = {
    backgroundColor: 'transparent',
    color: CHART_COLORS,
    tooltip: {
      trigger: 'item',
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 12 },
      formatter: p => `
        <div class="text-xs">
          <strong>${p.name}</strong><br/>
          Amount: <span class="font-mono">${formatUGX(p.value)}</span><br/>
          Share: <span class="font-bold">${p.percent}%</span>
        </div>`
    },
    series: [
      {
        name: 'Category Spend',
        type: 'pie',
        radius: ['45%', '75%'],
        center: ['50%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 6,
          borderColor: isDark() ? '#0c0c0f' : '#ffffff',
          borderWidth: 2
        },
        label: { show: false },
        labelLine: { show: false },
        data: pieData
      }
    ]
  };
  categoryChart.setOption(option, true);
}

function initAnalyticsBarChart() {
  const dom = document.getElementById('analyticsBarChart');
  if (!dom || !state.categories.length) return;
  if (!analyticsBarChart) analyticsBarChart = echarts.init(dom);

  const t = getChartTheme();
  const top12 = state.categories.slice(0, 12).reverse();
  const names = top12.map(c => c.subcategory);
  const values = top12.map(c => c.total_spent);

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 12 },
      formatter: p => `
        <div class="text-xs">
          <strong>${p[0].name}</strong><br/>
          Total Spent: <span class="font-mono font-bold">${formatUGX(p[0].value)}</span>
        </div>`
    },
    grid: { left: '3%', right: '6%', bottom: '3%', top: '3%', containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: {
        color: t.textColor,
        fontSize: 10,
        formatter: v => (v / 1_000_000).toFixed(0) + 'M'
      },
      splitLine: { lineStyle: { color: t.gridColor, type: 'dashed' } }
    },
    yAxis: {
      type: 'category',
      data: names,
      axisLabel: { color: t.textColor, fontSize: 11 },
      axisLine: { lineStyle: { color: t.gridColor } }
    },
    series: [
      {
        name: 'Total Spent',
        type: 'bar',
        data: values,
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#3b82f6' },
            { offset: 1, color: '#60a5fa' }
          ]),
          borderRadius: [0, 4, 4, 0]
        }
      }
    ]
  };
  analyticsBarChart.setOption(option, true);
}

function initAccountsFlowChart() {
  const dom = document.getElementById('accountsFlowChart');
  if (!dom || !state.accounts.length) return;
  if (!accountsFlowChart) accountsFlowChart = echarts.init(dom);

  const t = getChartTheme();
  const accs = state.accounts.slice(0, 6);
  const names = accs.map(a => a.account);
  const inFlow = accs.map(a => a.total_in);
  const outFlow = accs.map(a => a.total_out);

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 12 }
    },
    legend: {
      textStyle: { color: t.textColor, fontSize: 11 },
      top: 0
    },
    grid: { left: '3%', right: '3%', bottom: '5%', top: '15%', containLabel: true },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: { color: t.textColor, fontSize: 10, interval: 0, rotate: 20 },
      axisLine: { lineStyle: { color: t.gridColor } }
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: t.textColor,
        fontSize: 10,
        formatter: v => (v / 1_000_000).toFixed(0) + 'M'
      },
      splitLine: { lineStyle: { color: t.gridColor, type: 'dashed' } }
    },
    series: [
      {
        name: 'Total In',
        type: 'bar',
        data: inFlow,
        itemStyle: { color: '#10b981', borderRadius: [3, 3, 0, 0] }
      },
      {
        name: 'Total Out',
        type: 'bar',
        data: outFlow,
        itemStyle: { color: '#f43f5e', borderRadius: [3, 3, 0, 0] }
      }
    ]
  };
  accountsFlowChart.setOption(option, true);
}

// --- Render Widgets on Dashboard ---
function renderAccountsWidgets() {
  const container = document.getElementById('accountsList');
  if (!container) return;

  container.innerHTML = state.accounts.map(a => {
    const netColor = a.net_flow >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400';
    return `
      <div class="p-2.5 rounded-xl bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 flex items-center justify-between text-xs">
        <div>
          <span class="font-bold text-zinc-900 dark:text-zinc-100">${escapeHtml(a.account)}</span>
          <div class="text-[11px] text-zinc-500 font-mono">
            In: ${formatUGX(a.total_in, true)} | Out: ${formatUGX(a.total_out, true)}
          </div>
        </div>
        <div class="text-right">
          <span class="font-mono font-bold ${netColor}">${formatUGX(a.net_flow, true)}</span>
          <div class="text-[10px] text-zinc-400 font-mono">${a.tx_count} txs</div>
        </div>
      </div>
    `;
  }).join('');

  // Full list in Recurring & Accounts tab
  const fullList = document.getElementById('accountsFullList');
  if (fullList) {
    fullList.innerHTML = state.accounts.map(a => `
      <div class="p-3 rounded-xl bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 flex items-center justify-between text-xs">
        <div>
          <span class="font-bold text-zinc-900 dark:text-zinc-100">${escapeHtml(a.account)}</span>
          <div class="text-zinc-500 text-[11px]">Flow ratio: ${a.total_out > 0 ? (a.total_in / a.total_out).toFixed(2) : 'N/A'}x</div>
        </div>
        <div class="text-right font-mono">
          <div class="text-emerald-600 dark:text-emerald-400 font-semibold">+${formatUGX(a.total_in)}</div>
          <div class="text-rose-600 dark:text-rose-400">-${formatUGX(a.total_out)}</div>
        </div>
      </div>
    `).join('');
  }
}

function renderRecentTransactions(txs) {
  const tbody = document.getElementById('recentTxTbody');
  if (!tbody) return;

  const topRecent = txs.slice(0, 6);
  tbody.innerHTML = topRecent.map(t => {
    const isIncome = t.type === 'Income';
    const amtColor = isIncome ? 'text-emerald-600 dark:text-emerald-400 font-semibold' : 'text-rose-600 dark:text-rose-400 font-semibold';
    const sign = isIncome ? '+' : '-';
    return `
      <tr onclick="openTxDetail(${t.id})">
        <td class="font-mono text-xs text-zinc-500">${formatDate(t.date)}</td>
        <td>
          <div class="font-medium text-zinc-900 dark:text-zinc-100 truncate max-w-[280px]">${escapeHtml(t.description || t.merchant || 'N/A')}</div>
          ${t.merchant && t.merchant !== t.description ? `<div class="text-[11px] text-zinc-400 truncate max-w-[280px]">${escapeHtml(t.merchant)}</div>` : ''}
        </td>
        <td><span class="badge badge-transfer text-[11px]">${escapeHtml(t.account || 'N/A')}</span></td>
        <td><span class="text-xs text-zinc-600 dark:text-zinc-400">${escapeHtml(t.subcategory || t.group_name || 'General')}</span></td>
        <td class="text-right font-mono ${amtColor}">${sign}${formatUGX(t.amount)}</td>
      </tr>
    `;
  }).join('');
}

// --- Transactions Table & Filter Controller ---
async function loadTransactions() {
  const q = state.txFilters;
  const params = new URLSearchParams({
    page: q.page,
    limit: q.limit,
    search: q.search,
    type: q.type,
    account: q.account,
    group: q.group,
    flag: q.flag,
    date_from: q.date_from,
    date_to: q.date_to,
    sort_by: q.sort_by,
    order: q.order
  });

  try {
    const res = await authFetch(`/api/transactions?${params.toString()}`);
    const json = await res.json();
    state.txData = json;

    renderTransactionsTable(json.data);
    updatePaginationUI(json);
    renderRecentTransactions(json.data);
  } catch (err) {
    console.error('Error loading transactions:', err);
  }
}

function renderTransactionsTable(txs) {
  const tbody = document.getElementById('txTableBody');
  if (!tbody) return;

  if (!txs.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="text-center py-12 text-zinc-500">
          <div class="flex flex-col items-center gap-2">
            <svg class="w-8 h-8 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            <span>No transactions match the selected filter criteria.</span>
            <button onclick="resetTxFilters()" class="text-xs text-blue-500 hover:underline">Reset filters</button>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = txs.map(t => {
    const isIncome = t.type === 'Income';
    const typeBadge = isIncome ? 'badge-income' : 'badge-expense';
    const amtColor = isIncome ? 'text-emerald-600 dark:text-emerald-400 font-bold' : 'text-zinc-950 dark:text-zinc-100 font-semibold';
    const sign = isIncome ? '+' : '-';

    let flagBadge = '';
    if (t.is_review_resolved) {
      flagBadge = '<span class="badge bg-emerald-50 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 text-[10px]">✓ Resolved</span>';
    } else if (t.flag === 'transfer-between-own-accounts') {
      flagBadge = '<span class="badge badge-transfer text-[10px]">Own Transfer</span>';
    } else if (t.flag) {
      flagBadge = `<span class="badge badge-review text-[10px] truncate max-w-[140px]">${escapeHtml(t.flag.replace('needs-review-', ''))}</span>`;
    }

    return `
      <tr onclick="openTxDetail(${t.id})">
        <td class="font-mono text-xs text-zinc-500 whitespace-nowrap">${formatDate(t.date)}</td>
        <td><span class="badge ${typeBadge}">${escapeHtml(t.type)}</span></td>
        <td>
          <div class="font-medium text-zinc-900 dark:text-zinc-100 truncate max-w-[340px]">${escapeHtml(t.description || t.merchant || 'N/A')}</div>
          ${t.merchant && t.merchant !== t.description ? `<div class="text-[11px] text-zinc-400 truncate max-w-[340px]">${escapeHtml(t.merchant)}</div>` : ''}
        </td>
        <td><span class="badge badge-transfer text-[11px]">${escapeHtml(t.account || 'N/A')}</span></td>
        <td>
          <div class="text-xs text-zinc-900 dark:text-zinc-100">${escapeHtml(t.subcategory || 'General')}</div>
          <div class="text-[10px] text-zinc-400">${escapeHtml(t.group_name || '')}</div>
        </td>
        <td class="text-right font-mono ${amtColor}">${sign}${formatUGX(t.amount)}</td>
        <td>${flagBadge}</td>
      </tr>
    `;
  }).join('');
}

function updatePaginationUI(json) {
  document.getElementById('txFilteredCount').textContent = `Showing ${json.data.length} of ${json.total.toLocaleString()} transactions`;
  document.getElementById('pageInfoText').textContent = `Page ${json.page} of ${Math.max(1, json.pages)}`;
  document.getElementById('currentPageBadge').textContent = json.page;

  document.getElementById('btnFirstPage').disabled = json.page <= 1;
  document.getElementById('btnPrevPage').disabled = json.page <= 1;
  document.getElementById('btnNextPage').disabled = json.page >= json.pages;
  document.getElementById('btnLastPage').disabled = json.page >= json.pages;
}

function debounceSearch() {
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    state.txFilters.search = document.getElementById('txSearchInput').value;
    state.txFilters.page = 1;
    loadTransactions();
  }, 300);
}

function applyTxFilters() {
  state.txFilters.type = document.getElementById('filterType').value;
  state.txFilters.account = document.getElementById('filterAccount').value;
  state.txFilters.group = document.getElementById('filterGroup').value;
  state.txFilters.flag = document.getElementById('filterFlag').value;
  state.txFilters.date_from = document.getElementById('filterDateFrom').value;
  state.txFilters.date_to = document.getElementById('filterDateTo').value;
  state.txFilters.page = 1;
  loadTransactions();
}

function resetTxFilters() {
  document.getElementById('txSearchInput').value = '';
  document.getElementById('filterType').value = '';
  document.getElementById('filterAccount').value = '';
  document.getElementById('filterGroup').value = '';
  document.getElementById('filterFlag').value = '';
  document.getElementById('filterDateFrom').value = '';
  document.getElementById('filterDateTo').value = '';

  state.txFilters = {
    search: '',
    type: '',
    account: '',
    group: '',
    flag: '',
    date_from: '',
    date_to: '',
    page: 1,
    limit: state.txFilters.limit,
    sort_by: 'date',
    order: 'desc'
  };
  loadTransactions();
}

function changeSort(column) {
  if (state.txFilters.sort_by === column) {
    state.txFilters.order = state.txFilters.order === 'asc' ? 'desc' : 'asc';
  } else {
    state.txFilters.sort_by = column;
    state.txFilters.order = 'desc';
  }
  document.getElementById('sort-date').textContent = state.txFilters.sort_by === 'date' ? (state.txFilters.order === 'asc' ? '▲' : '▼') : '';
  document.getElementById('sort-amount').textContent = state.txFilters.sort_by === 'amount' ? (state.txFilters.order === 'asc' ? '▲' : '▼') : '';
  loadTransactions();
}

function changePage(delta) {
  const newPage = state.txFilters.page + delta;
  if (newPage >= 1 && newPage <= state.txData.pages) {
    state.txFilters.page = newPage;
    loadTransactions();
  }
}

function goToPage(page) {
  state.txFilters.page = page;
  loadTransactions();
}

function goToLastPage() {
  state.txFilters.page = state.txData.pages;
  loadTransactions();
}

function changePageSize(size) {
  state.txFilters.limit = parseInt(size);
  state.txFilters.page = 1;
  loadTransactions();
}

// --- Categories & Analytics View ---
function renderCategoriesTable() {
  const tbody = document.getElementById('categoriesTableBody');
  if (!tbody) return;

  tbody.innerHTML = state.categories.map(c => `
    <tr>
      <td><span class="badge badge-transfer text-xs">${escapeHtml(c.group_name)}</span></td>
      <td class="font-medium text-zinc-900 dark:text-zinc-100">${escapeHtml(c.subcategory)}</td>
      <td class="text-right font-mono font-bold">${formatUGX(c.total_spent)}</td>
      <td class="text-right font-mono text-zinc-500">${c.percent_spend.toFixed(2)}%</td>
      <td class="text-right font-mono text-zinc-500">${formatUGX(c.monthly_avg)}</td>
      <td class="text-right font-mono text-zinc-500">${formatUGX(c.daily_avg)}</td>
      <td class="text-center font-mono text-xs">${c.tx_count}</td>
    </tr>
  `).join('');
}

// --- Needs Review Workbench ---
async function loadNeedsReview() {
  const flagQuery = state.activeReviewFlag ? `?flag=${encodeURIComponent(state.activeReviewFlag)}` : '';
  try {
    const res = await authFetch(`/api/needs-review${flagQuery}`);
    const json = await res.json();
    state.reviewItems = json.data || [];
    renderReviewTable();

    // Update flag counter chips
    const counts = json.flag_counts || {};
    document.getElementById('countCatFlags').textContent = counts['needs-review-categorise'] || 0;
    document.getElementById('countTransferFlags').textContent = counts['transfer-between-own-accounts'] || 0;
    document.getElementById('countIncomeFlags').textContent = counts['needs-review-income-source'] || 0;
    document.getElementById('countFamilyFlags').textContent = counts['needs-review-family-amount'] || 0;
  } catch (err) {
    console.error('Error loading review items:', err);
  }
}

function filterReviewByFlag(flag) {
  state.activeReviewFlag = flag;
  document.querySelectorAll('.review-chip').forEach(btn => {
    btn.className = 'review-chip px-3 py-1 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 font-medium';
  });
  event.target.className = 'review-chip active px-3 py-1 rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300 font-medium';
  loadNeedsReview();
}

function renderReviewTable() {
  const tbody = document.getElementById('reviewTableBody');
  if (!tbody) return;

  if (!state.reviewItems.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" class="text-center py-12 text-zinc-500">
          <div class="flex flex-col items-center gap-2">
            <svg class="w-8 h-8 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            <span class="font-medium text-sm text-zinc-800 dark:text-zinc-200">No flagged transactions pending in this view!</span>
            <span class="text-xs">All records under this filter have been verified.</span>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = state.reviewItems.map(t => {
    const isChecked = state.selectedReviewIds.has(t.id);
    const isIncome = t.type === 'Income';
    const typeBadge = isIncome ? 'badge-income' : 'badge-expense';

    return `
      <tr>
        <td class="text-center" onclick="event.stopPropagation()">
          <input type="checkbox" onchange="toggleSelectReviewItem(${t.id}, this.checked)" ${isChecked ? 'checked' : ''}>
        </td>
        <td class="font-mono text-xs text-zinc-500 whitespace-nowrap">${formatDate(t.date)}</td>
        <td><span class="badge ${typeBadge}">${escapeHtml(t.type)}</span></td>
        <td onclick="openTxDetail(${t.id})">
          <div class="font-medium text-zinc-900 dark:text-zinc-100 text-xs truncate max-w-[360px]">${escapeHtml(t.description || t.merchant || 'N/A')}</div>
          ${t.merchant ? `<div class="text-[11px] text-zinc-400 truncate max-w-[360px]">${escapeHtml(t.merchant)}</div>` : ''}
        </td>
        <td><span class="badge badge-transfer text-[11px]">${escapeHtml(t.account || 'N/A')}</span></td>
        <td class="text-right font-mono font-bold">${formatUGX(t.amount)}</td>
        <td><span class="badge badge-review text-[10px]">${escapeHtml(t.flag)}</span></td>
        <td class="text-right">
          <button onclick="quickResolveItem(${t.id})" class="px-2.5 py-1 text-xs font-semibold rounded-lg bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-900/60 transition-colors border border-emerald-200 dark:border-emerald-800">
            Resolve
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

function toggleSelectReviewItem(id, checked) {
  if (checked) state.selectedReviewIds.add(id);
  else state.selectedReviewIds.delete(id);
}

function toggleSelectAllReview(checked) {
  if (checked) {
    state.reviewItems.forEach(t => state.selectedReviewIds.add(t.id));
  } else {
    state.selectedReviewIds.clear();
  }
  renderReviewTable();
}

async function quickResolveItem(id) {
  try {
    const res = await authFetch(`/api/transactions/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_review_resolved: 1 })
    });
    if (res.ok) {
      loadNeedsReview();
      loadStats();
    }
  } catch (err) {
    console.error('Error resolving item:', err);
  }
}

async function resolveSelectedReview() {
  const ids = Array.from(state.selectedReviewIds);
  if (!ids.length) {
    alert('Please select one or more transactions to resolve.');
    return;
  }
  try {
    const res = await authFetch('/api/batch-review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids, action: 'resolve' })
    });
    if (res.ok) {
      state.selectedReviewIds.clear();
      loadNeedsReview();
      loadStats();
    }
  } catch (err) {
    console.error('Error in batch resolve:', err);
  }
}

async function dismissSelectedReview() {
  const ids = Array.from(state.selectedReviewIds);
  if (!ids.length) {
    alert('Please select one or more transactions.');
    return;
  }
  try {
    const res = await authFetch('/api/batch-review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids, action: 'dismiss' })
    });
    if (res.ok) {
      state.selectedReviewIds.clear();
      loadNeedsReview();
      loadStats();
    }
  } catch (err) {
    console.error('Error dismissing flag:', err);
  }
}

// --- Recurring Table ---
function renderRecurringTable() {
  const tbody = document.getElementById('recurringTableBody');
  if (!tbody) return;

  tbody.innerHTML = state.recurring.map(r => `
    <tr>
      <td class="font-medium text-zinc-900 dark:text-zinc-100">${escapeHtml(r.item)}</td>
      <td><span class="badge badge-transfer text-xs">${escapeHtml(r.group_name)}</span></td>
      <td class="text-right font-mono font-bold">${formatUGX(r.total_spent)}</td>
      <td class="text-center font-mono text-xs">${r.distinct_months} mos</td>
      <td class="text-right font-mono text-emerald-600 dark:text-emerald-400 font-semibold">${formatUGX(r.est_monthly_equiv)}/mo</td>
    </tr>
  `).join('');
}

// --- Transaction Detail Drawer ---
function openTxDetail(id) {
  // Find in currently loaded sets
  const tx = (state.txData.data || []).find(t => t.id === id) ||
             (state.reviewItems || []).find(t => t.id === id) ||
             (state.dailyTxs || []).find(t => t.id === id);
  if (!tx) return;

  state.selectedTx = tx;
  document.getElementById('txDetailIdLabel').textContent = `ID: #${tx.id} ${tx.tx_id ? `(${tx.tx_id})` : ''}`;
  document.getElementById('txDetailAmount').textContent = formatUGX(tx.amount);
  
  const typeBadge = document.getElementById('txDetailTypeBadge');
  typeBadge.textContent = tx.type;
  typeBadge.className = tx.type === 'Income' ? 'badge badge-income text-sm font-semibold' : 'badge badge-expense text-sm font-semibold';

  document.getElementById('txDetailDesc').textContent = tx.description || tx.merchant || 'N/A';
  document.getElementById('txDetailDate').value = tx.date;
  document.getElementById('txDetailAccount').value = tx.account || 'N/A';
  document.getElementById('txDetailSubcategory').value = tx.subcategory || '';
  document.getElementById('txDetailGroup').value = tx.group_name || '';
  document.getElementById('txDetailNotes').value = tx.notes || '';

  const flagSec = document.getElementById('txDetailFlagSection');
  if (tx.flag && !tx.is_review_resolved) {
    flagSec.classList.remove('hidden');
    document.getElementById('txDetailFlagText').textContent = tx.flag;
  } else {
    flagSec.classList.add('hidden');
  }

  document.getElementById('txDetailBackdrop').classList.add('open');
  document.getElementById('txDetailDrawer').classList.add('open');
}

function closeTxDetailDrawer() {
  document.getElementById('txDetailBackdrop').classList.remove('open');
  document.getElementById('txDetailDrawer').classList.remove('open');
  state.selectedTx = null;
}

async function saveTxDetailChanges() {
  if (!state.selectedTx) return;
  const id = state.selectedTx.id;
  const updates = {
    subcategory: document.getElementById('txDetailSubcategory').value.trim(),
    group_name: document.getElementById('txDetailGroup').value.trim(),
    notes: document.getElementById('txDetailNotes').value.trim()
  };

  try {
    const res = await authFetch(`/api/transactions/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    });
    if (res.ok) {
      closeTxDetailDrawer();
      loadTransactions();
      if (state.activeTab === 'review') loadNeedsReview();
    }
  } catch (err) {
    console.error('Error saving transaction:', err);
  }
}

async function resolveCurrentTxFlag() {
  if (!state.selectedTx) return;
  await quickResolveItem(state.selectedTx.id);
  closeTxDetailDrawer();
}

// --- New Transaction Modal ---
function openNewTxModal() {
  // default date to today
  const today = new Date().toISOString().split('T')[0];
  document.getElementById('newTxDate').value = today;
  document.getElementById('newTxModalBackdrop').classList.add('open');
}

function closeNewTxModal() {
  document.getElementById('newTxModalBackdrop').classList.remove('open');
  document.getElementById('newTxForm').reset();
}

async function handleNewTxSubmit(e) {
  e.preventDefault();
  const body = {
    date: document.getElementById('newTxDate').value,
    type: document.getElementById('newTxType').value,
    amount: document.getElementById('newTxAmount').value,
    account: document.getElementById('newTxAccount').value,
    description: document.getElementById('newTxDesc').value,
    subcategory: document.getElementById('newTxSubcat').value || 'General',
    group_name: document.getElementById('newTxGroup').value,
    notes: document.getElementById('newTxNotes').value
  };

  try {
    const res = await authFetch('/api/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (res.ok) {
      closeNewTxModal();
      loadStats();
      loadTransactions();
      loadMonthly();
      loadCategories();
      loadAccounts();
    }
  } catch (err) {
    console.error('Error creating transaction:', err);
  }
}

// --- Gemini AI Chat Panel (SSE Streaming) ---
function toggleChatPanel(open) {
  const backdrop = document.getElementById('chatDrawerBackdrop');
  const drawer = document.getElementById('chatDrawer');
  if (open) {
    backdrop.classList.add('open');
    drawer.classList.add('open');
    document.getElementById('chatTextarea')?.focus();
  } else {
    backdrop.classList.remove('open');
    drawer.classList.remove('open');
  }
}

function toggleThought(index) {
  state.expandedThoughts[index] = !state.expandedThoughts[index];
  renderChatMessages();
}

function clearChatHistory() {
  state.chatMessages = [
    {
      role: 'model',
      content: 'Chat history cleared. How can I assist you with your finances?',
      thoughts: '',
      suggestions: [
        'What was my spending in 2026 so far?',
        'Show top 5 spending categories',
        'Check accounts summary'
      ]
    }
  ];
  renderChatMessages();
}

function handleChatKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleChatSubmit(e);
  }
}

async function handleChatSubmit(e) {
  e.preventDefault();
  const input = document.getElementById('chatTextarea');
  const query = input.value.trim();
  if (!query || state.isChatLoading) return;

  input.value = '';
  input.style.height = 'auto';
  await sendChatMessage(query);
}

async function sendChatMessage(text) {
  if (state.isChatLoading) return;
  state.isChatLoading = true;
  const sendBtn = document.getElementById('chatSendBtn');
  if (sendBtn) sendBtn.disabled = true;

  // Add User Message
  state.chatMessages.push({ role: 'user', content: text });
  
  // Add placeholder Model Message
  const modelMsg = {
    role: 'model',
    content: '',
    thoughts: '',
    suggestions: []
  };
  state.chatMessages.push(modelMsg);
  renderChatMessages();

  try {
    const response = await authFetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        history: state.chatMessages.slice(0, -2)
      })
    });

    if (!response.ok) {
      const errJson = await response.json().catch(() => ({}));
      throw new Error(errJson.error || `HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let streamDone = false;

    while (!streamDone) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete fragment

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data: ')) continue;
        const dataStr = trimmed.slice(6).trim();

        if (dataStr === '[DONE]') {
          streamDone = true;
          break;
        }

        if (dataStr) {
          try {
            const parsed = JSON.parse(dataStr);
            if (parsed.type === 'THOUGHT') {
              modelMsg.thoughts = (modelMsg.thoughts ? modelMsg.thoughts + '\n' : '') + parsed.content;
            } else if (parsed.type === 'SUGGESTION') {
              if (!modelMsg.suggestions.includes(parsed.content)) {
                modelMsg.suggestions.push(parsed.content);
              }
            } else if (parsed.type === 'FINAL_RESPONSE') {
              modelMsg.content += parsed.content;
            }
            renderChatMessages();
          } catch (err) {
            // incomplete JSON chunk
          }
        }
      }
    }

    try { await reader.cancel(); } catch (e) {}

    // Provide default fallback if response was empty
    if (!modelMsg.content && !modelMsg.thoughts) {
      modelMsg.content = "I couldn't find specific data for that request. Try asking about categories, recurring expenses, or account balances!";
      renderChatMessages();
    }
  } catch (err) {
    console.error('Chat error:', err);
    modelMsg.content = `⚠️ Unable to complete AI analysis (${err.message || 'connection error'}). Please try again.`;
    renderChatMessages();
  } finally {
    state.isChatLoading = false;
    if (sendBtn) sendBtn.disabled = false;
  }
}

function renderChatMessages() {
  const container = document.getElementById('chatMessages');
  if (!container) return;

  container.innerHTML = state.chatMessages.map((m, i) => {
    const isUser = m.role === 'user';
    if (isUser) {
      return `
        <div class="flex gap-2.5 flex-row-reverse">
          <div class="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center flex-shrink-0 mt-0.5 text-xs font-bold">U</div>
          <div class="max-w-[85%] p-3 rounded-2xl rounded-tr-none bg-blue-600 text-white text-xs leading-relaxed shadow-sm">
            ${escapeHtml(m.content)}
          </div>
        </div>
      `;
    }

    // Model message
    const isExpanded = !!state.expandedThoughts[i];
    const thoughtLines = (m.thoughts || '').split('\n').filter(l => l.trim().length > 0);
    const lastThought = thoughtLines.length > 0 ? thoughtLines[thoughtLines.length - 1] : 'Analyzing ledger context...';

    return `
      <div class="flex gap-2.5 flex-row">
        <div class="w-7 h-7 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-500 text-white flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
        </div>
        <div class="max-w-[88%] flex flex-col gap-2">
          
          <!-- Collapsible Thought Container -->
          ${m.thoughts && m.thoughts.trim().length > 0 ? `
            <div class="bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden shadow-sm">
              <button onclick="toggleThought(${i})" class="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors">
                <svg class="w-3.5 h-3.5 text-blue-500 flex-shrink-0 transform transition-transform ${isExpanded ? 'rotate-90' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
                <span class="truncate text-left text-[11px] font-mono">${m.content ? 'Reasoning Process' : escapeHtml(lastThought)}</span>
              </button>
              ${isExpanded ? `
                <div class="px-3 py-2 border-t border-zinc-200 dark:border-zinc-800 max-h-48 overflow-y-auto bg-zinc-100 dark:bg-black/30 font-mono text-[10px] text-zinc-600 dark:text-zinc-400 flex flex-col gap-1 leading-normal">
                  ${thoughtLines.map(l => `<div class="flex gap-1.5"><span class="text-blue-500">›</span><span class="break-words">${escapeHtml(l)}</span></div>`).join('')}
                </div>
              ` : ''}
            </div>
          ` : ''}

          <!-- Loading Spinner if thinking with no content yet -->
          ${!m.content && state.isChatLoading && i === state.chatMessages.length - 1 ? `
            <div class="flex items-center gap-2 text-xs text-zinc-500 italic p-1">
              <svg class="w-3.5 h-3.5 animate-spin text-blue-500" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg>
              Thinking...
            </div>
          ` : ''}

          <!-- Final Response Bubble (Parsed Markdown) -->
          ${m.content ? `
            <div class="p-3.5 rounded-2xl rounded-tl-none bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 text-xs leading-relaxed border border-zinc-200 dark:border-zinc-700/60 shadow-sm chat-markdown">
              ${parseMarkdownToHtml(m.content)}
            </div>
          ` : ''}

          <!-- Follow-up Suggestion Chips -->
          ${m.suggestions && m.suggestions.length > 0 ? `
            <div class="flex flex-col gap-1.5 mt-1">
              ${m.suggestions.slice(0, 3).map(s => `
                <button onclick="sendChatMessage('${escapeHtml(s).replace(/'/g, "\\'")}')" class="text-left text-xs bg-blue-50 dark:bg-blue-900/20 hover:bg-blue-100 dark:hover:bg-blue-800/40 text-blue-700 dark:text-blue-300 p-2 rounded-xl border border-blue-200 dark:border-blue-800/30 transition-colors">
                  💡 ${escapeHtml(s)}
                </button>
              `).join('')}
            </div>
          ` : ''}

        </div>
      </div>
    `;
  }).join('');

  // Scroll to bottom
  container.scrollTop = container.scrollHeight;
}

// Dynamic textarea height adjustment
// --- Import CSV Modal & Processing ---
let currentImportCsvText = '';

function openImportModal() {
  currentImportCsvText = '';
  document.getElementById('importFileInput').value = '';
  document.getElementById('importCsvTextarea').value = '';
  document.getElementById('selectedFileName').classList.add('hidden');
  document.getElementById('importPreview').classList.add('hidden');
  document.getElementById('importResultBanner').classList.add('hidden');
  document.getElementById('confirmImportBtn').disabled = true;
  setImportTab('file');
  document.getElementById('importModalBackdrop').classList.add('open');
}

function closeImportModal() {
  document.getElementById('importModalBackdrop').classList.remove('open');
}

function setImportTab(tab) {
  const fileTab = document.getElementById('importTabFile');
  const pasteTab = document.getElementById('importTabPaste');
  const fileSec = document.getElementById('importFileSection');
  const pasteSec = document.getElementById('importPasteSection');

  if (tab === 'file') {
    fileTab.className = 'flex-1 py-1.5 rounded-md font-medium bg-white dark:bg-zinc-900 shadow-sm text-zinc-900 dark:text-zinc-100 transition-all';
    pasteTab.className = 'flex-1 py-1.5 rounded-md font-medium text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-all';
    fileSec.classList.remove('hidden');
    pasteSec.classList.add('hidden');
  } else {
    pasteTab.className = 'flex-1 py-1.5 rounded-md font-medium bg-white dark:bg-zinc-900 shadow-sm text-zinc-900 dark:text-zinc-100 transition-all';
    fileTab.className = 'flex-1 py-1.5 rounded-md font-medium text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-all';
    pasteSec.classList.remove('hidden');
    fileSec.classList.add('hidden');
    document.getElementById('importCsvTextarea')?.focus();
  }
}

function handleFileSelected(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  const fnBadge = document.getElementById('selectedFileName');
  fnBadge.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
  fnBadge.classList.remove('hidden');

  const reader = new FileReader();
  reader.onload = (e) => {
    currentImportCsvText = e.target.result;
    runDryRunAnalysis(currentImportCsvText);
  };
  reader.readAsText(file);
}

function handlePasteInput() {
  currentImportCsvText = document.getElementById('importCsvTextarea').value;
  if (currentImportCsvText.trim().length > 10) {
    runDryRunAnalysis(currentImportCsvText);
  } else {
    document.getElementById('importPreview').classList.add('hidden');
    document.getElementById('confirmImportBtn').disabled = true;
  }
}

async function runDryRunAnalysis(csvText) {
  const previewDiv = document.getElementById('importPreview');
  const confirmBtn = document.getElementById('confirmImportBtn');
  const badge = document.getElementById('previewStatusBadge');

  badge.textContent = 'Analyzing...';
  badge.className = 'px-2 py-0.5 rounded text-[10px] font-mono bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300';
  previewDiv.classList.remove('hidden');

  try {
    const res = await authFetch('/api/import?dry_run=true', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: csvText
    });
    const data = await res.json();
    if (data.success) {
      const total = (data.new_count || 0) + (data.duplicate_count || 0);
      document.getElementById('previewTotalRows').textContent = total;
      document.getElementById('previewNewCount').textContent = data.new_count || 0;
      document.getElementById('previewDupCount').textContent = data.duplicate_count || 0;

      badge.textContent = `${data.new_count} new to import`;
      badge.className = 'px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300';
      confirmBtn.disabled = false;
    } else {
      badge.textContent = 'Format error';
      badge.className = 'px-2 py-0.5 rounded text-[10px] font-mono bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300';
      confirmBtn.disabled = true;
    }
  } catch (err) {
    badge.textContent = 'Check failed';
    console.error('Dry-run check failed:', err);
  }
}

async function executeImport() {
  if (!currentImportCsvText || !currentImportCsvText.trim()) return;

  const confirmBtn = document.getElementById('confirmImportBtn');
  const banner = document.getElementById('importResultBanner');
  const gitPush = document.getElementById('importGitPush').checked;

  confirmBtn.disabled = true;
  confirmBtn.innerHTML = `
    <svg class="animate-spin -ml-1 mr-1.5 h-3.5 w-3.5 text-white inline" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
    </svg>
    Importing...
  `;

  try {
    const url = `/api/import${gitPush ? '?git_push=true' : ''}`;
    const res = await authFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: currentImportCsvText
    });
    const data = await res.json();

    if (data.success) {
      banner.className = 'p-3 rounded-xl text-xs font-medium bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-200 block';
      banner.innerHTML = `
        <div class="font-bold mb-0.5">✅ Import Complete</div>
        <div>${data.message || `Successfully processed. Total transactions: ${data.total_transactions}.`}</div>
      `;

      // Refresh all dashboard metrics immediately
      loadStats();
      loadTransactions();
      loadMonthly();
      loadCategories();
      loadAccounts();

      confirmBtn.textContent = 'Done!';
      setTimeout(() => {
        closeImportModal();
        confirmBtn.textContent = 'Import Transactions';
        confirmBtn.disabled = false;
      }, 1500);
    } else {
      banner.className = 'p-3 rounded-xl text-xs font-medium bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200 block';
      banner.textContent = data.error || 'Import failed. Please verify CSV formatting.';
      confirmBtn.textContent = 'Import Transactions';
      confirmBtn.disabled = false;
    }
  } catch (err) {
    banner.className = 'p-3 rounded-xl text-xs font-medium bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200 block';
    banner.textContent = `Network error: ${err.message}`;
    confirmBtn.textContent = 'Import Transactions';
    confirmBtn.disabled = false;
  }
}

// --- Daily Glance (Mobile-First) Dashboard Controller ---
let glanceSparklineChart = null;

const CAT_ICONS = {
  'Health': '💊',
  'Medical': '💊',
  'Hospital': '🏥',
  'Groceries': '🛒',
  'Food': '🍽️',
  'Food & Dining': '🍽️',
  'Car': '⛽',
  'Car & Fuel': '⛽',
  'Utilities': '💡',
  'Phone': '📱',
  'Communication': '📱',
  'Socializing': '🎉',
  'Social Activities': '🎉',
  'Housing': '🏠',
  'Substances': '💨',
  'Education': '📚',
  'Staff': '👥',
  'Business Expenses': '💼',
  'Gifts': '🎁',
  'Family Support': '👨‍👩‍👧',
  'Help': '🤝',
  'Help & Gifts': '🤝',
  'Bank Charges': '🏦',
  'Transaction Fees': '🏦',
  'Savings': '💰',
  'Investments': '📈'
};

async function loadDailyGlance(date) {
  try {
    const url = date ? `/api/daily-glance?date=${date}` : '/api/daily-glance';
    const res = await authFetch(url);
    const data = await res.json();
    if (!data || !data.today) return;

    state.dailyGlanceData = data;
    state.dailyTxs = (data.today.transactions || []).concat(data.yesterday.transactions || []);

    // Format target date
    const dParts = data.target_date.split('-');
    const dtObj = new Date(parseInt(dParts[0]), parseInt(dParts[1]) - 1, parseInt(dParts[2]));
    const dateFormatted = dtObj.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' });
    
    document.getElementById('glanceTodayFormatted').textContent = dateFormatted;
    document.getElementById('glanceDateSubtitle').textContent = `Target: ${data.target_date} • Uganda Standard Time (EAT)`;

    // Hero stats
    const todaySpend = data.today.spend || 0;
    document.getElementById('glanceTodaySpend').textContent = formatUGX(todaySpend);
    document.getElementById('glanceTxCountBadge').textContent = `${data.today.tx_count || 0} Transactions`;

    const yestSpend = data.yesterday.spend || 0;
    const diff = todaySpend - yestSpend;
    const diffSign = diff >= 0 ? '+' : '';
    document.getElementById('glanceYesterdayCompare').innerHTML = `
      <span>Yesterday: ${formatUGX(yestSpend)}</span>
      <span class="ml-1 text-[11px] opacity-80">(${diffSign}${formatUGX(diff)})</span>
    `;

    // Burn rate & target badge
    const dailyAvg = data.month_to_date.daily_avg || 0;
    document.getElementById('glanceBurnRateText').textContent = `Daily average: ${formatUGX(dailyAvg)}`;

    const paceBadge = document.getElementById('glancePaceBadge');
    if (todaySpend === 0) {
      paceBadge.textContent = 'No Spend Yet';
      paceBadge.className = 'px-2.5 py-1 text-xs font-semibold rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border border-zinc-500/20';
    } else if (todaySpend <= dailyAvg * 1.1) {
      paceBadge.textContent = 'Within Target';
      paceBadge.className = 'px-2.5 py-1 text-xs font-semibold rounded-full bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20';
    } else {
      paceBadge.textContent = 'Heavy Spending';
      paceBadge.className = 'px-2.5 py-1 text-xs font-semibold rounded-full bg-amber-50 dark:bg-amber-950/50 text-amber-600 dark:text-amber-400 border border-amber-500/20';
    }

    // Month Pacing
    document.getElementById('glanceMonthName').textContent = data.month_to_date.month;
    document.getElementById('glanceMonthSpend').textContent = formatUGX(data.month_to_date.total_spend);
    document.getElementById('glanceProjectedText').textContent = `Projected month total: ${formatUGX(data.month_to_date.projected_month_total)}`;
    document.getElementById('glanceDailyAvgPace').textContent = `${formatUGX(dailyAvg)} / day`;

    // Top Category Drivers
    const driversList = document.getElementById('glanceTopDriversList');
    if (data.month_to_date.top_categories && data.month_to_date.top_categories.length > 0) {
      driversList.innerHTML = data.month_to_date.top_categories.map(c => `
        <div class="space-y-1">
          <div class="flex items-center justify-between text-xs">
            <span class="font-medium text-zinc-800 dark:text-zinc-200">${c.subcategory} <span class="text-zinc-400">(${c.count} txs)</span></span>
            <span class="font-mono font-semibold text-zinc-900 dark:text-zinc-100">${formatUGX(c.total_spent)} (${c.percent}%)</span>
          </div>
          <div class="w-full h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
            <div class="h-full rounded-full bg-blue-600 dark:bg-blue-500" style="width: ${Math.min(100, c.percent)}%"></div>
          </div>
        </div>
      `).join('');
    } else {
      driversList.innerHTML = '<p class="text-xs text-zinc-400">No category expenses this month yet.</p>';
    }

    // Render 7-Day Sparkline
    renderGlanceSparkline(data.last_7_days || []);

    // Render Activity List (Today & Yesterday)
    renderGlanceActivity(data.today, data.yesterday);

  } catch (err) {
    console.error('Error loading daily glance data:', err);
  }
}

function renderGlanceSparkline(days) {
  const dom = document.getElementById('glanceSparklineChart');
  if (!dom) return;
  if (!glanceSparklineChart) glanceSparklineChart = echarts.init(dom);

  const total7 = days.reduce((sum, d) => sum + (d.spend || 0), 0);
  document.getElementById('glance7DayTotal').textContent = `${formatUGX(total7)} (7-day total)`;

  const isDark = state.theme === 'dark';
  const xData = days.map(d => `${d.day_name}\n${d.date.slice(5)}`);
  const yData = days.map(d => d.spend);

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const item = params[0];
        const dayObj = days[item.dataIndex];
        return `
          <div class="font-bold text-xs mb-1">${dayObj.date} (${dayObj.day_name})</div>
          <div class="text-xs text-rose-500">Outflow: ${formatUGX(dayObj.spend)}</div>
          ${dayObj.income > 0 ? `<div class="text-xs text-emerald-500">Inflow: ${formatUGX(dayObj.income)}</div>` : ''}
          <div class="text-[10px] text-zinc-400 mt-1">${dayObj.count} transactions</div>
        `;
      }
    },
    grid: {
      top: 15,
      bottom: 25,
      left: 10,
      right: 10,
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: xData,
      axisLine: { lineStyle: { color: isDark ? '#27272a' : '#e4e4e7' } },
      axisLabel: {
        color: isDark ? '#a1a1aa' : '#71717a',
        fontSize: 10,
        interval: 0
      }
    },
    yAxis: {
      type: 'value',
      show: false
    },
    series: [{
      type: 'bar',
      data: yData,
      barWidth: '45%',
      itemStyle: {
        borderRadius: [6, 6, 0, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#3b82f6' },
          { offset: 1, color: '#1d4ed8' }
        ])
      }
    }]
  };

  glanceSparklineChart.setOption(option);
}

function renderGlanceActivity(today, yesterday) {
  const container = document.getElementById('glanceActivityList');
  if (!container) return;

  const todayTxs = today.transactions || [];
  const yestTxs = yesterday.transactions || [];

  if (todayTxs.length === 0 && yestTxs.length === 0) {
    container.innerHTML = '<p class="text-xs text-zinc-400 py-6 text-center">No transactions logged for today or yesterday yet.</p>';
    return;
  }

  let html = '';

  if (todayTxs.length > 0) {
    html += `<div class="text-[11px] font-bold uppercase tracking-wider text-blue-600 dark:text-blue-400 py-2">Today (${today.date})</div>`;
    html += todayTxs.map(t => renderGlanceTxRow(t)).join('');
  }

  if (yestTxs.length > 0) {
    html += `<div class="text-[11px] font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 py-2 mt-2">Yesterday (${yesterday.date})</div>`;
    html += yestTxs.map(t => renderGlanceTxRow(t)).join('');
  }

  container.innerHTML = html;
}

function renderGlanceTxRow(tx) {
  const cat = tx.subcategory || tx.category || 'General';
  const icon = CAT_ICONS[cat] || CAT_ICONS[tx.category] || '💸';
  const isIncome = tx.type === 'Income';
  const amtClass = isIncome ? 'text-emerald-600 dark:text-emerald-400' : 'text-zinc-900 dark:text-zinc-100';
  const amtPrefix = isIncome ? '+' : '-';

  return `
    <div onclick="openTxDetail(${tx.id})" class="py-2.5 flex items-center justify-between cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-900/50 rounded-xl px-2 transition-colors active:scale-[0.99]">
      <div class="flex items-center gap-3">
        <div class="w-9 h-9 rounded-xl bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-base">
          ${icon}
        </div>
        <div>
          <div class="text-xs font-semibold text-zinc-900 dark:text-zinc-100 line-clamp-1">${tx.description || cat}</div>
          <div class="text-[11px] text-zinc-500">${tx.time ? tx.time.slice(0, 5) + ' • ' : ''}${cat} • ${tx.account || 'Cash'}</div>
        </div>
      </div>
      <div class="text-right">
        <div class="font-mono font-bold text-xs ${amtClass}">${amtPrefix}${formatUGX(tx.amount)}</div>
      </div>
    </div>
  `;
}

// --- Quick Add Bottom Sheet (Mobile-First) ---
function openQuickAddSheet() {
  document.getElementById('quickAmountInput').value = '';
  document.getElementById('quickDescInput').value = '';
  document.getElementById('quickAddSheetBackdrop').classList.add('open');
  setTimeout(() => document.getElementById('quickAmountInput')?.focus(), 250);
}

function closeQuickAddSheet() {
  document.getElementById('quickAddSheetBackdrop').classList.remove('open');
}

function setQuickAmount(amt) {
  const input = document.getElementById('quickAmountInput');
  const current = parseInt(input.value.replace(/,/g, '')) || 0;
  input.value = (current + amt).toLocaleString();
}

function setQuickCategory(catName, btn) {
  document.getElementById('quickCategoryInput').value = catName;
  document.querySelectorAll('.quick-cat-btn').forEach(b => {
    b.className = 'quick-cat-btn px-2 py-2 rounded-xl border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 text-center active:scale-95 transition-all';
  });
  btn.className = 'quick-cat-btn px-2 py-2 rounded-xl border border-blue-500 bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 font-medium text-center active:scale-95 transition-all';
}

function setQuickAccount(accName, btn) {
  document.getElementById('quickAccountInput').value = accName;
  document.querySelectorAll('.quick-acc-btn').forEach(b => {
    b.className = 'quick-acc-btn flex-1 py-2 rounded-xl border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 text-xs font-medium';
  });
  btn.className = 'quick-acc-btn flex-1 py-2 rounded-xl border border-blue-500 bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 text-xs font-medium';
}

async function handleQuickAddSubmit(e) {
  e.preventDefault();
  const rawAmt = document.getElementById('quickAmountInput').value;
  const amt = parseFloat(rawAmt.replace(/,/g, ''));
  if (!amt || isNaN(amt)) return;

  const desc = document.getElementById('quickDescInput').value.trim();
  const cat = document.getElementById('quickCategoryInput').value;
  const acc = document.getElementById('quickAccountInput').value;

  const submitBtn = document.getElementById('quickAddSubmitBtn');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Saving...';

  try {
    const res = await authFetch('/api/transactions/quick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        amount: amt,
        description: desc || cat,
        category: cat,
        account: acc,
        type: 'Expense'
      })
    });
    const data = await res.json();
    if (data.success) {
      closeQuickAddSheet();
      loadDailyGlance();
      loadStats();
      loadTransactions();
    } else {
      alert(data.error || 'Failed to record expense');
    }
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Save Expense';
  }
}

// --- Q3 2026 Expense Report Tab Controller ---
async function loadQ3Report() {
  try {
    const res = await authFetch('/api/q3-report');
    const data = await res.json();
    if (!data || !data.total_q3) return;

    state.q3ReportData = data;

    const total = data.total_q3 || 0;
    const fixed = data.fixed_overhead || 0;
    const variable = data.variable_spend || 0;

    const fixedPct = total > 0 ? (fixed / total * 100).toFixed(1) : '0.0';
    const varPct = total > 0 ? (variable / total * 100).toFixed(1) : '0.0';

    // Top KPIs
    const elKpiTotal = document.getElementById('q3KpiTotal');
    if (elKpiTotal) elKpiTotal.innerHTML = `${formatUGX(total)} <span class="text-xs font-normal text-zinc-500">UGX</span>`;
    const elKpiTxCount = document.getElementById('q3KpiTxCount');
    if (elKpiTxCount) elKpiTxCount.textContent = (data.tx_count || 0).toLocaleString();
    const elKpiFixed = document.getElementById('q3KpiFixed');
    if (elKpiFixed) elKpiFixed.innerHTML = `${formatUGX(fixed)} <span class="text-xs font-normal text-emerald-600/60">UGX</span>`;
    const elKpiFixedPct = document.getElementById('q3KpiFixedPct');
    if (elKpiFixedPct) elKpiFixedPct.textContent = `${fixedPct}%`;
    const elKpiVar = document.getElementById('q3KpiVar');
    if (elKpiVar) elKpiVar.innerHTML = `${formatUGX(variable)} <span class="text-xs font-normal text-zinc-500">UGX</span>`;
    const elKpiVarPct = document.getElementById('q3KpiVarPct');
    if (elKpiVarPct) elKpiVarPct.textContent = `${varPct}%`;

    // 4 Core Overhead Pillars
    const rentTot = data.rent?.total || 0;
    const rentPct = total > 0 ? (rentTot / total * 100).toFixed(1) : '0.0';
    const elRentTot = document.getElementById('q3RentTotal');
    if (elRentTot) elRentTot.innerHTML = `${formatUGX(rentTot)} <span class="text-xs font-normal text-zinc-500">UGX</span>`;
    const elRentBadge = document.getElementById('q3RentPctBadge');
    if (elRentBadge) elRentBadge.textContent = `${rentPct}%`;
    const elRentBar = document.getElementById('q3RentBar');
    if (elRentBar) elRentBar.style.width = `${Math.min(100, parseFloat(rentPct))}%`;

    const debtTot = data.debts?.total || 0;
    const debtPct = total > 0 ? (debtTot / total * 100).toFixed(1) : '0.0';
    const elDebtTot = document.getElementById('q3DebtTotal');
    if (elDebtTot) elDebtTot.innerHTML = `${formatUGX(debtTot)} <span class="text-xs font-normal text-zinc-500">UGX</span>`;
    const elDebtBadge = document.getElementById('q3DebtPctBadge');
    if (elDebtBadge) elDebtBadge.textContent = `${debtPct}%`;
    const elDebtBar = document.getElementById('q3DebtBar');
    if (elDebtBar) elDebtBar.style.width = `${Math.min(100, parseFloat(debtPct))}%`;

    const subsTot = data.subscriptions?.total || 0;
    const subsPct = total > 0 ? (subsTot / total * 100).toFixed(1) : '0.0';
    const elSubsTot = document.getElementById('q3SubsTotal');
    if (elSubsTot) elSubsTot.innerHTML = `${formatUGX(subsTot)} <span class="text-xs font-normal text-zinc-500">UGX</span>`;
    const elSubsBadge = document.getElementById('q3SubsPctBadge');
    if (elSubsBadge) elSubsBadge.textContent = `${subsPct}%`;
    const elSubsBar = document.getElementById('q3SubsBar');
    if (elSubsBar) elSubsBar.style.width = `${Math.min(100, parseFloat(subsPct))}%`;

    const utilsTot = data.utilities?.total || 0;
    const utilsPct = total > 0 ? (utilsTot / total * 100).toFixed(1) : '0.0';
    const elUtilsTot = document.getElementById('q3UtilsTotal');
    if (elUtilsTot) elUtilsTot.innerHTML = `${formatUGX(utilsTot)} <span class="text-xs font-normal text-zinc-500">UGX</span>`;
    const elUtilsBadge = document.getElementById('q3UtilsPctBadge');
    if (elUtilsBadge) elUtilsBadge.textContent = `${utilsPct}%`;
    const elUtilsBar = document.getElementById('q3UtilsBar');
    if (elUtilsBar) elUtilsBar.style.width = `${Math.min(100, parseFloat(utilsPct))}%`;

    // Render Tables
    renderQ3ScheduleTable('q3RentTable', data.rent?.transactions || [], 'text-emerald-600 dark:text-emerald-400');
    renderQ3ScheduleTable('q3DebtsTable', data.debts?.transactions || [], 'text-rose-600 dark:text-rose-400');
    renderQ3ScheduleTable('q3SubsTable', data.subscriptions?.transactions || [], 'text-amber-600 dark:text-amber-400');
    renderQ3ScheduleTable('q3UtilsTable', data.utilities?.transactions || [], 'text-cyan-600 dark:text-cyan-400');

    // Render Categories Table
    renderQ3CategoriesTable(data.top_categories || [], total);

  } catch (err) {
    console.error('Error loading Q3 report data:', err);
  }
}

function renderQ3ScheduleTable(elementId, transactions, amountColorClass) {
  const container = document.getElementById(elementId);
  if (!container) return;

  if (!transactions || transactions.length === 0) {
    container.innerHTML = '<p class="text-xs text-zinc-400 py-3 text-center">No transactions found.</p>';
    return;
  }

  let html = `
    <table class="finance-table w-full text-xs">
      <thead>
        <tr>
          <th>Date</th>
          <th>Description</th>
          <th>Account</th>
          <th class="text-right">Amount (UGX)</th>
        </tr>
      </thead>
      <tbody>
  `;

  transactions.forEach(tx => {
    html += `
      <tr>
        <td class="font-mono text-zinc-500 dark:text-zinc-400 whitespace-nowrap">${escapeHtml(tx.date || '')}</td>
        <td class="font-medium text-zinc-900 dark:text-zinc-100">${escapeHtml(tx.description || '')}</td>
        <td class="text-zinc-500 dark:text-zinc-400 whitespace-nowrap">${escapeHtml(tx.account || '')}</td>
        <td class="text-right font-mono font-semibold ${amountColorClass} whitespace-nowrap">${formatUGX(tx.amount)}</td>
      </tr>
    `;
  });

  html += `
      </tbody>
    </table>
  `;

  container.innerHTML = html;
}

function renderQ3CategoriesTable(categories, totalQ3) {
  const container = document.getElementById('q3CategoriesTable');
  if (!container) return;

  if (!categories || categories.length === 0) {
    container.innerHTML = '<p class="text-xs text-zinc-400 py-3 text-center">No categories found.</p>';
    return;
  }

  let html = `
    <table class="finance-table w-full text-xs">
      <thead>
        <tr>
          <th>Category Group</th>
          <th>Subcategory</th>
          <th class="text-center">Transactions</th>
          <th class="text-right">Total Outflow (UGX)</th>
          <th class="text-right">% of Q3 Spend</th>
        </tr>
      </thead>
      <tbody>
  `;

  categories.forEach(cat => {
    const pct = totalQ3 > 0 ? (cat.total_amt / totalQ3 * 100).toFixed(1) : '0.0';
    html += `
      <tr>
        <td class="text-zinc-500 dark:text-zinc-400 uppercase text-[11px] font-semibold">${escapeHtml(cat.group_name || '')}</td>
        <td class="font-semibold text-zinc-900 dark:text-zinc-100">${escapeHtml(cat.subcategory || '')}</td>
        <td class="text-center font-mono text-zinc-600 dark:text-zinc-400">${(cat.tx_count || 0).toLocaleString()}</td>
        <td class="text-right font-mono font-bold text-zinc-900 dark:text-zinc-100">${formatUGX(cat.total_amt)}</td>
        <td class="text-right font-mono font-semibold text-emerald-600 dark:text-emerald-400">${pct}%</td>
      </tr>
    `;
  });

  html += `
      </tbody>
    </table>
  `;

  container.innerHTML = html;
}

document.addEventListener('DOMContentLoaded', () => {
  // Register PWA Service Worker
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(err => {
        console.warn('SW registration failed:', err);
      });
    });
  }

  const textarea = document.getElementById('chatTextarea');
  if (textarea) {
    textarea.addEventListener('input', () => {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 112) + 'px';
    });
  }

  // Global Keyboard Shortcuts (Cmd+K / Ctrl+K opens Chat)
  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      toggleChatPanel(true);
    }
  });

  // Responsive chart resize listener
  window.addEventListener('resize', () => {
    glanceSparklineChart?.resize();
    monthlyChart?.resize();
    categoryChart?.resize();
    analyticsBarChart?.resize();
    accountsFlowChart?.resize();
  });

  // Initialize
  applyTheme(state.theme);
  checkAuth();

  // Mobile or PWA Standalone Mode: Default to Daily Glance view
  const isMobileOrPwa = window.innerWidth < 640 || window.matchMedia('(display-mode: standalone)').matches;
  if (isMobileOrPwa) {
    switchTab('daily');
  } else {
    loadDailyGlance();
  }
});

