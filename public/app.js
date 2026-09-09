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
  const tabs = ['dashboard', 'transactions', 'analytics', 'review', 'recurring'];
  tabs.forEach(t => {
    const tabEl = document.getElementById(`tab-${t}`);
    const viewEl = document.getElementById(`view-${t}`);
    if (t === tabId) {
      tabEl?.classList.add('active');
      viewEl?.classList.remove('hidden');
    } else {
      tabEl?.classList.remove('active');
      viewEl?.classList.add('hidden');
    }
  });

  if (tabId === 'dashboard') {
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
             (state.reviewItems || []).find(t => t.id === id);
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
  document.getElementById('chatSendBtn').disabled = true;

  // Add User Message
  state.chatMessages.push({ role: 'user', content: text });
  
  // Add placeholder Model Message
  const nextIdx = state.chatMessages.length;
  state.chatMessages.push({
    role: 'model',
    content: '',
    thoughts: '',
    suggestions: []
  });
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

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete fragment

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const dataStr = line.replace('data: ', '').trim();
          if (dataStr === '[DONE]') break;
          if (dataStr) {
            try {
              const parsed = JSON.parse(dataStr);
              const target = state.chatMessages[nextIdx];

              if (parsed.type === 'THOUGHT') {
                target.thoughts = (target.thoughts ? target.thoughts + '\n' : '') + parsed.content;
              } else if (parsed.type === 'SUGGESTION') {
                if (!target.suggestions.includes(parsed.content)) {
                  target.suggestions.push(parsed.content);
                }
              } else if (parsed.type === 'FINAL_RESPONSE') {
                target.content += parsed.content;
              }

              renderChatMessages();
            } catch (err) {
              // json parse incomplete chunk
            }
          }
        }
      }
    }
  } catch (err) {
    console.error('Chat error:', err);
    state.chatMessages[nextIdx].content = '⚠️ Error streaming response from server. Please check connection.';
    renderChatMessages();
  } finally {
    state.isChatLoading = false;
    document.getElementById('chatSendBtn').disabled = false;
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
document.addEventListener('DOMContentLoaded', () => {
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
    monthlyChart?.resize();
    categoryChart?.resize();
    analyticsBarChart?.resize();
    accountsFlowChart?.resize();
  });

  // Initialize
  applyTheme(state.theme);
  checkAuth();
});
