/**
 * Domain module: useRisk
 */
(function (G) {
  'use strict';

  G.useRisk = function useRisk(ctx) {
    const {
      armConfirm,
      clearConfirmArmed,
      component,
      computed,
      isConfirmArmed,
      logs,
      onMounted,
      reactive,
      ref,
      site,
      tab,
      watch,
      findingsMetricsWindow,
      FINDINGS_METRICS_WINDOWS,
      normalizeFindingsMetricsWindow,
    } = ctx;
    const api = G.api;

const risk = reactive({ log: '' });
const RISK_TIME_WINDOWS = [
  { id: '1h', label: 'Last hour', seconds: 3600 },
  { id: '4h', label: 'Last 4 hours', seconds: 14400 },
  { id: '24h', label: 'Last 24 hours (daily)', seconds: 86400 },
];
const EXPORT_RISK_LEVELS = [
  { id: 'critical', label: 'Critical' },
  { id: 'high', label: 'High' },
  { id: 'medium', label: 'Medium' },
  { id: 'low', label: 'Low' },
  { id: 'informational', label: 'Informational' },
  { id: 'indeterminate', label: 'Indeterminate' },
];
const RISK_WINDOW_PREFIX = '__window:';

function riskWindowValue(windowId) {
  return `${RISK_WINDOW_PREFIX}${windowId}`;
}

function riskWindowIdFromValue(value) {
  if (!value || !value.startsWith(RISK_WINDOW_PREFIX)) return '';
  return value.slice(RISK_WINDOW_PREFIX.length);
}

/** Local copy - Export's helper is not in scope inside useRisk. */
function normalizeExportRiskLevel(row) {
  const aliases = { compliant: 'low', mitigated: 'low' };
  const raw = String(row?.risk_level || '').trim().toLowerCase();
  const level = aliases[raw] || raw;
  return EXPORT_RISK_LEVELS.some((l) => l.id === level) ? level : 'indeterminate';
}

function summarizeReportSeverities(rows) {
  const counts = {};
  for (const row of rows || []) {
    const level = normalizeExportRiskLevel(row);
    counts[level] = (counts[level] || 0) + 1;
  }
  return counts;
}

function formatSeveritySummary(counts) {
  return EXPORT_RISK_LEVELS
    .filter((l) => counts[l.id])
    .map((l) => `${counts[l.id]} ${l.label}`)
    .join(', ');
}

function severityRank(level) {
  const id = String(level || '').trim().toLowerCase();
  const idx = EXPORT_RISK_LEVELS.findIndex((l) => l.id === id);
  return idx >= 0 ? idx : EXPORT_RISK_LEVELS.length;
}

/** Sort critical → indeterminate; stable by original report index. */
function sortRiskRowsBySeverity(rows) {
  return [...(rows || [])].sort((a, b) => {
    const ra = severityRank(a.riskLevel);
    const rb = severityRank(b.riskLevel);
    if (ra !== rb) return ra - rb;
    return (a.index ?? 0) - (b.index ?? 0);
  });
}

/** Full severity counts (zeros included) for the metrics bar. */
function completeSeverityCounts(partial) {
  const counts = {};
  for (const l of EXPORT_RISK_LEVELS) {
    counts[l.id] = (partial && partial[l.id]) || 0;
  }
  return counts;
}

const riskWindowCounts = computed(() => {
  const now = Date.now() / 1000;
  const attacks = logs.attacks || [];
  const counts = {};
  for (const w of RISK_TIME_WINDOWS) {
    counts[w.id] = attacks.filter(a => (a.mtime || 0) >= now - w.seconds).length;
  }
  return counts;
});

const riskAssessEnabled = computed(() => {
  if (!risk.log) return false;
  const windowId = riskWindowIdFromValue(risk.log);
  if (windowId) return (riskWindowCounts.value[windowId] || 0) > 0;
  return true;
});

const riskViewResults = ref([]);
const riskViewLoading = ref(false);
const riskViewMeta = ref(null);
const riskLevelFilter = ref([]); // empty = all levels
const riskTablePage = ref(1);
const RISK_TABLE_PAGE_SIZE = 50;
const riskWindowRowsLoading = ref(false);
let riskWindowRowsLoadGen = 0;
const riskViewFlaggedIds = ref([]);
const riskFlagMsg = ref('');
const riskFlagBusy = ref(false);
const selectedRiskReportPath = ref('');
const expandedRiskRows = ref({});
const expandedRiskPromptRows = ref({});
const expandedRiskReasonRows = ref({});
const riskViewCopiedKey = ref('');
let riskViewCopiedTimer = null;
const _savedRiskViewLayout = localStorage.getItem('genbounty_risk_view_layout');
const riskViewLayout = ref(
  _savedRiskViewLayout === 'maximized' || _savedRiskViewLayout === 'minimized'
    ? _savedRiskViewLayout
    : 'normal'
);

function persistRiskViewLayout() {
  localStorage.setItem('genbounty_risk_view_layout', riskViewLayout.value);
}

function toggleRiskViewMinimize() {
  riskViewLayout.value = riskViewLayout.value === 'minimized' ? 'normal' : 'minimized';
  persistRiskViewLayout();
}

function toggleRiskViewMaximize() {
  riskViewLayout.value = riskViewLayout.value === 'maximized' ? 'normal' : 'maximized';
  persistRiskViewLayout();
}

const riskViewMaximizedActive = computed(
  () => riskViewLayout.value === 'maximized' && riskViewResults.value.length > 0
);

function _metricsWindowId() {
  return normalizeFindingsMetricsWindow
    ? normalizeFindingsMetricsWindow(findingsMetricsWindow?.value)
    : (findingsMetricsWindow?.value || 'last_run');
}

function _probeReportsInMetricsWindow(windowId) {
  const id = windowId || _metricsWindowId();
  const reports = riskProbeReports.value || [];
  if (id === 'last_run') return [];
  if (id === 'all') return reports.slice();
  const now = Date.now() / 1000;
  const win = (FINDINGS_METRICS_WINDOWS || []).find((w) => w.id === id);
  const secs = win && win.seconds != null ? win.seconds : 0;
  return reports.filter((r) => (r.mtime || 0) >= now - secs);
}

function toggleRiskLevelFilter(levelId) {
  const id = String(levelId || '').trim();
  if (!id) return;
  const cur = Array.isArray(riskLevelFilter.value) ? [...riskLevelFilter.value] : [];
  const idx = cur.indexOf(id);
  if (idx >= 0) cur.splice(idx, 1);
  else cur.push(id);
  riskLevelFilter.value = cur;
  riskTablePage.value = 1;
}

function isRiskLevelFilterActive(levelId) {
  return (riskLevelFilter.value || []).includes(String(levelId || ''));
}

const riskFilteredResults = computed(() => {
  const rows = Array.isArray(riskViewResults.value) ? riskViewResults.value : [];
  const selected = riskLevelFilter.value || [];
  if (!selected.length) return rows;
  const want = new Set(selected);
  return rows.filter((r) => want.has(String(r.riskLevel || 'indeterminate')));
});

const riskTablePageCount = computed(() => {
  const n = riskFilteredResults.value.length;
  return Math.max(1, Math.ceil(n / RISK_TABLE_PAGE_SIZE));
});

const riskPagedResults = computed(() => {
  const rows = riskFilteredResults.value;
  const page = Math.min(
    Math.max(1, riskTablePage.value || 1),
    riskTablePageCount.value,
  );
  const start = (page - 1) * RISK_TABLE_PAGE_SIZE;
  return rows.slice(start, start + RISK_TABLE_PAGE_SIZE);
});

const riskTableRangeLabel = computed(() => {
  const total = riskFilteredResults.value.length;
  if (!total) return '0 findings';
  const page = Math.min(Math.max(1, riskTablePage.value || 1), riskTablePageCount.value);
  const start = (page - 1) * RISK_TABLE_PAGE_SIZE + 1;
  const end = Math.min(total, page * RISK_TABLE_PAGE_SIZE);
  return `Showing ${start}–${end} of ${total}`;
});

const riskWindowStatusLabel = computed(() => {
  const windowId = _metricsWindowId();
  const win = (FINDINGS_METRICS_WINDOWS || []).find((w) => w.id === windowId);
  const label = win?.label || windowId;
  const n = riskViewResults.value.length;
  const filtered = riskLevelFilter.value?.length
    ? ` · filtered to ${riskFilteredResults.value.length}`
    : '';
  if (windowId === 'last_run') {
    return n ? `${n} finding${n === 1 ? '' : 's'} in selected report${filtered}` : '';
  }
  return `${n} finding${n === 1 ? '' : 's'} in ${label}${filtered}`;
});

function riskTablePrevPage() {
  riskTablePage.value = Math.max(1, (riskTablePage.value || 1) - 1);
}

function riskTableNextPage() {
  riskTablePage.value = Math.min(
    riskTablePageCount.value,
    (riskTablePage.value || 1) + 1,
  );
}

watch(riskFilteredResults, () => {
  if (riskTablePage.value > riskTablePageCount.value) {
    riskTablePage.value = riskTablePageCount.value;
  }
});

function formatRiskReportLabel(entry, index) {
  const when = entry.mtime
    ? new Date(entry.mtime * 1000).toLocaleString()
    : entry.name;
  const latest = index === 0 ? ' · latest' : '';
  return `${when} - ${entry.name}${latest}`;
}

/** Risk view shows suite probe assessments only (not Manual attacks). */
function isProbePipelineReportPath(path) {
  const p = String(path || '').replace(/\\/g, '/');
  return p.includes('/logs/probes/');
}

const riskProbeReports = computed(() =>
  (logs.reports || []).filter((r) => isProbePipelineReportPath(r?.path)),
);

function parentPlaybookStemFromReport(data) {
  const source = String(data?.source_file || '');
  if (source) {
    const base = source.split('/').pop() || '';
    const stem = base.replace(/\.json$/i, '');
    if (stem) return stem;
  }
  const pid = String(data?.playbook_id || '').trim();
  if (pid) return pid.replace(/_/g, '-');
  const playbook = String(data?.playbook || '').trim();
  if (!playbook) return '';
  return playbook.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

function mapRiskResultRow(r, index = 0, reportPath = '') {
  const riskLevel = normalizeExportRiskLevel(r);
  const turns = Array.isArray(r.turns) ? r.turns : (Array.isArray(r.prior_turns) ? r.prior_turns : null);
  let prompt = String(r.prompt || '').trim();
  if (turns && turns.length) {
    prompt = turns
      .map((t, ti) => {
        const text = String(t.prompt || t.input || '').trim();
        return text ? `[${ti + 1}] ${text}` : '';
      })
      .filter(Boolean)
      .join('\n\n');
  }
  if (!prompt) prompt = String(r.prompt || '').trim();
  return {
    label: `#${index + 1}`,
    index,
    id: r.id || '',
    categoryId: r.category_id || '',
    category: r.category_id || r.category || '',
    riskLevel,
    prompt,
    response: r.response || '',
    reasoning: r.judge_reasoning || '',
    confidence: r.confidence || '',
    evidenceStrength: (typeof r.evidence_strength === 'number') ? r.evidence_strength : null,
    evidenceSignals: r.evidence_signals && typeof r.evidence_signals === 'object'
      ? Object.keys(r.evidence_signals).filter((k) => r.evidence_signals[k])
      : [],
    exploitStatus: String(r.exploit_status || '').trim().toLowerCase(),
    outcome: String(r.outcome || '').trim().toLowerCase(),
    reportPath: String(reportPath || '').trim(),
  };
}

function parseRiskReportRows(data, reportPath = '') {
  const rows = data?.adversarial_results || [];
  const mapped = rows.map((r, i) => mapRiskResultRow(r, i, reportPath));
  return sortRiskRowsBySeverity(mapped);
}

function appendLiveRiskResult(raw) {
  if (!raw || typeof raw !== 'object') return;
  const windowId = normalizeFindingsMetricsWindow
    ? normalizeFindingsMetricsWindow(findingsMetricsWindow?.value)
    : (findingsMetricsWindow?.value || 'last_run');
  // Period windows keep a merged table; live rows still update severity tiles.
  if (windowId !== 'last_run') {
    _applyLiveRiskResultToPeriodMetrics(raw);
    return;
  }
  const cur = Number(raw.current);
  const isFirst = Number.isFinite(cur) && cur === 1;
  const existing = (!isFirst && Array.isArray(riskViewResults.value))
    ? [...riskViewResults.value]
    : [];
  if (isFirst && expandedRiskRows) {
    expandedRiskRows.value = {};
  }
  const id = String(raw.id || '').trim();
  const reportPath = String(selectedRiskReportPath.value || '').trim();
  const row = mapRiskResultRow(raw, existing.length, reportPath);
  let next;
  if (id) {
    const idx = existing.findIndex((r) => String(r.id || '') === id);
    if (idx >= 0) {
      next = existing.slice();
      next[idx] = {
        ...row,
        label: existing[idx].label || row.label,
        index: existing[idx].index,
        reportPath: existing[idx].reportPath || reportPath,
      };
    } else {
      next = [...existing, row];
    }
  } else {
    next = [...existing, row];
  }
  // Relabel sequentially for live view; final reload re-sorts by severity.
  riskViewResults.value = next.map((r, i) => ({ ...r, label: `#${i + 1}`, index: i }));
  riskTablePage.value = 1;
  if (riskViewLoading) riskViewLoading.value = false;
  riskMetricsWindowCounts.value = _severityFromRiskViewResults();
}

/** Cached per-report severity totals: path → { mtime, counts }. */
const riskReportSeverityCache = ref({});
const riskMetricsWindowCounts = ref(completeSeverityCounts({}));
const riskMetricsLoading = ref(false);
let riskMetricsRefreshGen = 0;
let riskMetricsRefreshTimer = null;
/** In-flight /api/log fetches keyed by path (dedupe concurrent ensure calls). */
const riskSeverityInflight = Object.create(null);
const RISK_METRICS_FETCH_CONCURRENCY = 4;

/**
 * While a period window (1h / 3h / all) is selected, live assess results do not
 * rewrite the merged table - but severity tiles must still update. Track the
 * in-flight assess as an overlay on top of cached per-report counts.
 */
let livePeriodMetricsPath = '';
let livePeriodMetricsCounts = null;
const livePeriodMetricsById = Object.create(null);

function _clearLivePeriodMetrics() {
  livePeriodMetricsPath = '';
  livePeriodMetricsCounts = null;
  for (const k of Object.keys(livePeriodMetricsById)) delete livePeriodMetricsById[k];
}

/** Call when Analysis starts so War Room / Risk tiles do not show the previous run. */
function beginLiveRiskAssessment() {
  const windowId = normalizeFindingsMetricsWindow
    ? normalizeFindingsMetricsWindow(findingsMetricsWindow?.value)
    : (findingsMetricsWindow?.value || 'last_run');
  if (windowId === 'last_run') {
    if (expandedRiskRows) expandedRiskRows.value = {};
    riskViewResults.value = [];
    riskMetricsWindowCounts.value = completeSeverityCounts({});
    if (riskViewLoading) riskViewLoading.value = false;
    return;
  }
  livePeriodMetricsPath = _livePeriodAssessPath();
  livePeriodMetricsCounts = completeSeverityCounts({});
  for (const k of Object.keys(livePeriodMetricsById)) delete livePeriodMetricsById[k];
  if (livePeriodMetricsPath && riskReportSeverityCache.value[livePeriodMetricsPath]) {
    const next = { ...riskReportSeverityCache.value };
    delete next[livePeriodMetricsPath];
    riskReportSeverityCache.value = next;
  }
  _recomputePeriodMetricsFromCache();
}

function _livePeriodAssessPath() {
  return String(
    selectedRiskReportPath?.value
    || riskViewMeta?.value?.reportPath
    || livePeriodMetricsPath
    || '',
  ).trim();
}

function _reportsInMetricsWindow(windowId) {
  const id = windowId || _metricsWindowId();
  const now = Date.now() / 1000;
  const win = (FINDINGS_METRICS_WINDOWS || []).find((w) => w.id === id);
  return (riskProbeReports.value || []).filter((r) => {
    if (id === 'all') return true;
    if (id === 'last_run') return false;
    const secs = win && win.seconds != null ? win.seconds : 0;
    return (r.mtime || 0) >= now - secs;
  });
}

function _mergeSeverityInto(totals, counts) {
  if (!counts) return;
  for (const l of EXPORT_RISK_LEVELS) {
    totals[l.id] += counts[l.id] || 0;
  }
}

/** Sync recompute of period-window tiles from cache + live assess overlay. */
function _recomputePeriodMetricsFromCache() {
  const windowId = _metricsWindowId();
  if (windowId === 'last_run') return;
  const reports = _reportsInMetricsWindow(windowId);
  const totals = completeSeverityCounts({});
  let liveApplied = false;
  for (const r of reports) {
    if (
      livePeriodMetricsCounts
      && livePeriodMetricsPath
      && r.path === livePeriodMetricsPath
    ) {
      _mergeSeverityInto(totals, livePeriodMetricsCounts);
      liveApplied = true;
      continue;
    }
    const cached = riskReportSeverityCache.value[r.path];
    if (cached && cached.counts) _mergeSeverityInto(totals, cached.counts);
  }
  // New assess report may not be in logs.reports yet - still count live rows.
  if (livePeriodMetricsCounts && livePeriodMetricsPath && !liveApplied) {
    _mergeSeverityInto(totals, livePeriodMetricsCounts);
  }
  riskMetricsWindowCounts.value = totals;
}

function _applyLiveRiskResultToPeriodMetrics(raw) {
  const cur = Number(raw.current);
  const isFirst = Number.isFinite(cur) && cur === 1;
  const level = normalizeExportRiskLevel({
    risk_level: raw.risk_level || raw.riskLevel,
  });
  const id = String(raw.id || '').trim();
  const path = _livePeriodAssessPath();

  if (isFirst) {
    livePeriodMetricsPath = path;
    livePeriodMetricsCounts = completeSeverityCounts({});
    for (const k of Object.keys(livePeriodMetricsById)) delete livePeriodMetricsById[k];
    if (path && riskReportSeverityCache.value[path]) {
      const next = { ...riskReportSeverityCache.value };
      delete next[path];
      riskReportSeverityCache.value = next;
    }
    // Refresh other reports in the window; overlay stays authoritative for this path.
    scheduleRiskMetricsRefresh();
  } else if (!livePeriodMetricsCounts) {
    livePeriodMetricsPath = path;
    livePeriodMetricsCounts = completeSeverityCounts({});
  } else if (path && !livePeriodMetricsPath) {
    livePeriodMetricsPath = path;
  }

  if (id && livePeriodMetricsById[id]) {
    const prev = livePeriodMetricsById[id];
    livePeriodMetricsCounts[prev] = Math.max(
      0,
      (livePeriodMetricsCounts[prev] || 0) - 1,
    );
  }
  livePeriodMetricsCounts[level] = (livePeriodMetricsCounts[level] || 0) + 1;
  if (id) livePeriodMetricsById[id] = level;

  _recomputePeriodMetricsFromCache();
}

function _severityFromRiskViewResults() {
  const partial = {};
  for (const r of riskViewResults.value || []) {
    const level = r.riskLevel || 'indeterminate';
    partial[level] = (partial[level] || 0) + 1;
  }
  return completeSeverityCounts(partial);
}

function _mtimeForRiskReportPath(path) {
  const hit = (riskProbeReports.value || []).find((r) => r.path === path);
  return hit && hit.mtime != null ? hit.mtime : 0;
}

function _cacheRiskReportSeverity(path, counts, mtime) {
  if (!path || !counts) return;
  const mt = mtime != null ? mtime : _mtimeForRiskReportPath(path);
  riskReportSeverityCache.value = {
    ...riskReportSeverityCache.value,
    [path]: { mtime: mt, counts: completeSeverityCounts(counts) },
  };
}

function _pruneRiskReportSeverityCache(reports) {
  const keep = new Set((reports || []).map((r) => r.path));
  const cur = riskReportSeverityCache.value || {};
  let changed = false;
  const next = {};
  for (const [path, entry] of Object.entries(cur)) {
    if (!keep.has(path)) {
      changed = true;
      continue;
    }
    const mt = _mtimeForRiskReportPath(path);
    if (entry && entry.mtime === mt) next[path] = entry;
    else changed = true;
  }
  if (changed) riskReportSeverityCache.value = next;
}

async function ensureRiskReportSeverity(path, mtime) {
  const p = String(path || '').trim();
  if (!p) return completeSeverityCounts({});
  if (
    livePeriodMetricsCounts
    && livePeriodMetricsPath
    && p === livePeriodMetricsPath
  ) {
    return completeSeverityCounts(livePeriodMetricsCounts);
  }
  const mt = mtime != null ? mtime : _mtimeForRiskReportPath(p);
  const cached = riskReportSeverityCache.value[p];
  if (cached && cached.mtime === mt && cached.counts) return cached.counts;

  if (riskSeverityInflight[p]) return riskSeverityInflight[p];

  const pending = (async () => {
    try {
      if (
        livePeriodMetricsCounts
        && livePeriodMetricsPath
        && p === livePeriodMetricsPath
      ) {
        return completeSeverityCounts(livePeriodMetricsCounts);
      }
      if (
        p === selectedRiskReportPath.value
        && (riskViewResults.value || []).length
        && _metricsWindowId() === 'last_run'
      ) {
        const counts = _severityFromRiskViewResults();
        _cacheRiskReportSeverity(p, counts, mt);
        return counts;
      }
      const data = await api(`/api/log?path=${encodeURIComponent(p)}`);
      if (
        livePeriodMetricsCounts
        && livePeriodMetricsPath
        && p === livePeriodMetricsPath
      ) {
        return completeSeverityCounts(livePeriodMetricsCounts);
      }
      const counts = completeSeverityCounts(
        summarizeReportSeverities(data.adversarial_results || []),
      );
      _cacheRiskReportSeverity(p, counts, mt);
      return counts;
    } finally {
      delete riskSeverityInflight[p];
    }
  })();
  riskSeverityInflight[p] = pending;
  return pending;
}

async function _mapPool(items, limit, fn) {
  const list = items || [];
  if (!list.length) return [];
  const out = new Array(list.length);
  let cursor = 0;
  async function worker() {
    while (cursor < list.length) {
      const idx = cursor++;
      out[idx] = await fn(list[idx], idx);
    }
  }
  const n = Math.max(1, Math.min(limit || 1, list.length));
  await Promise.all(Array.from({ length: n }, () => worker()));
  return out;
}

async function refreshRiskMetricsWindowCounts() {
  const gen = ++riskMetricsRefreshGen;
  const windowId = normalizeFindingsMetricsWindow
    ? normalizeFindingsMetricsWindow(findingsMetricsWindow?.value)
    : (findingsMetricsWindow?.value || 'last_run');

  // Last run = newest / currently viewed report.
  if (windowId === 'last_run') {
    _clearLivePeriodMetrics();
    riskMetricsWindowCounts.value = _severityFromRiskViewResults();
    if (gen === riskMetricsRefreshGen) riskMetricsLoading.value = false;
    return;
  }

  if (tab?.value && tab.value !== 'risk' && tab.value !== 'war-room') {
    if (gen === riskMetricsRefreshGen) riskMetricsLoading.value = false;
    return;
  }

  const reports = _reportsInMetricsWindow(windowId);

  riskMetricsLoading.value = true;
  try {
    const totals = completeSeverityCounts({});
    const chunks = await _mapPool(reports, RISK_METRICS_FETCH_CONCURRENCY, async (r) => {
      if (gen !== riskMetricsRefreshGen) return completeSeverityCounts({});
      try {
        return await ensureRiskReportSeverity(r.path, r.mtime);
      } catch (e) {
        console.error(e);
        return completeSeverityCounts({});
      }
    });
    if (gen !== riskMetricsRefreshGen) return;
    let liveApplied = false;
    for (let i = 0; i < reports.length; i++) {
      const r = reports[i];
      const c = chunks[i];
      if (
        livePeriodMetricsCounts
        && livePeriodMetricsPath
        && r.path === livePeriodMetricsPath
      ) {
        _mergeSeverityInto(totals, livePeriodMetricsCounts);
        liveApplied = true;
      } else {
        _mergeSeverityInto(totals, c);
      }
    }
    if (livePeriodMetricsCounts && livePeriodMetricsPath && !liveApplied) {
      _mergeSeverityInto(totals, livePeriodMetricsCounts);
    }
    riskMetricsWindowCounts.value = totals;
  } catch (e) {
    console.error(e);
    if (gen === riskMetricsRefreshGen) {
      riskMetricsWindowCounts.value = completeSeverityCounts({});
    }
  } finally {
    if (gen === riskMetricsRefreshGen) riskMetricsLoading.value = false;
  }
}

function scheduleRiskMetricsRefresh() {
  if (riskMetricsRefreshTimer != null) clearTimeout(riskMetricsRefreshTimer);
  riskMetricsRefreshTimer = setTimeout(() => {
    riskMetricsRefreshTimer = null;
    refreshRiskMetricsWindowCounts();
  }, 0);
}

function _cancelRiskMetricsRefresh() {
  riskMetricsRefreshGen += 1;
  if (riskMetricsRefreshTimer != null) {
    clearTimeout(riskMetricsRefreshTimer);
    riskMetricsRefreshTimer = null;
  }
  for (const k of Object.keys(riskSeverityInflight)) delete riskSeverityInflight[k];
  riskMetricsLoading.value = false;
  _clearLivePeriodMetrics();
}

watch(
  () => findingsMetricsWindow?.value,
  () => {
    scheduleRiskMetricsRefresh();
    syncRiskTableToMetricsWindow();
  },
);

watch(
  () => (riskProbeReports.value || []).map((r) => `${r.path}:${r.mtime || 0}`).join('|'),
  () => {
    _pruneRiskReportSeverityCache(riskProbeReports.value);
    scheduleRiskMetricsRefresh();
  },
);

watch(tab, (t) => {
  if (t === 'risk' || t === 'war-room') {
    scheduleRiskMetricsRefresh();
    syncRiskTableToMetricsWindow();
  }
});

watch([site, component], () => {
  // Clear only - do not fetch against the previous site's logs.reports.
  _cancelRiskMetricsRefresh();
  riskWindowRowsLoadGen += 1;
  riskReportSeverityCache.value = {};
  riskMetricsWindowCounts.value = completeSeverityCounts({});
  riskLevelFilter.value = [];
  riskTablePage.value = 1;
  riskViewResults.value = [];
  // Drop stale log lists until loadContext/loadLogs fills the new scope.
  if (logs) {
    logs.reports = [];
    logs.runs = [];
    logs.attacks = [];
  }
});

async function loadRiskResultsForMetricsWindow(windowId) {
  const id = windowId || _metricsWindowId();
  const gen = ++riskWindowRowsLoadGen;
  const hadRows = Array.isArray(riskViewResults.value) && riskViewResults.value.length > 0;
  riskWindowRowsLoading.value = true;
  // Keep the assessment table mounted while refreshing when prior rows exist.
  if (!hadRows) riskViewLoading.value = true;
  clearRiskDeleteArmed();
  try {
    if (typeof ctx.loadLogs === 'function') await ctx.loadLogs();
    if (gen !== riskWindowRowsLoadGen) return;
    const reports = _probeReportsInMetricsWindow(id);
    if (!reports.length) {
      riskViewResults.value = [];
      riskViewMeta.value = null;
      riskTablePage.value = 1;
      return;
    }
    const chunks = await _mapPool(reports, RISK_METRICS_FETCH_CONCURRENCY, async (r) => {
      if (gen !== riskWindowRowsLoadGen) return [];
      try {
        const data = await api(`/api/log?path=${encodeURIComponent(r.path)}`);
        const counts = completeSeverityCounts(
          summarizeReportSeverities(data.adversarial_results || []),
        );
        _cacheRiskReportSeverity(r.path, counts, r.mtime);
        return parseRiskReportRows(data, r.path);
      } catch (e) {
        console.error(e);
        return [];
      }
    });
    if (gen !== riskWindowRowsLoadGen) return;
    const merged = [];
    for (const part of chunks) {
      for (const row of part || []) merged.push(row);
    }
    const sorted = sortRiskRowsBySeverity(merged).map((row, i) => ({
      ...row,
      label: `#${i + 1}`,
      index: i,
    }));
    expandedRiskRows.value = {};
    expandedRiskPromptRows.value = {};
    expandedRiskReasonRows.value = {};
    riskViewResults.value = sorted;
    riskTablePage.value = 1;
    // Meta from newest report in the window (for flag suite defaults).
    const newest = reports[0];
    if (newest?.path) {
      try {
        const data = await api(`/api/log?path=${encodeURIComponent(newest.path)}`);
        if (gen !== riskWindowRowsLoadGen) return;
        riskViewMeta.value = {
          playbook: data.playbook_id || data.playbook || '',
          strategy: data.strategy || '',
          strategyDir: (data.strategy || 'zero_shot').replace(/_/g, '-'),
          parentPlaybook: parentPlaybookStemFromReport(data),
          sourceFile: data.source_file || '',
          reportPath: newest.path,
          timestamp: data.timestamp || '',
          windowId: id,
        };
        await loadRiskFlaggedIds();
      } catch (e) {
        console.error(e);
        riskViewMeta.value = { reportPath: newest.path, windowId: id };
      }
    } else {
      riskViewMeta.value = null;
    }
  } catch (e) {
    console.error(e);
    if (gen === riskWindowRowsLoadGen && !hadRows) {
      riskViewResults.value = [];
      riskViewMeta.value = null;
    }
  } finally {
    if (gen === riskWindowRowsLoadGen) {
      riskWindowRowsLoading.value = false;
      riskViewLoading.value = false;
    }
  }
}

async function syncRiskTableToMetricsWindow() {
  const windowId = _metricsWindowId();
  riskTablePage.value = 1;
  // Last run: always pin dropdown + table to the newest report (pipeline/assess/
  // tab enter). Period windows (1h/3h/all) own the table as a merge instead.
  if (windowId === 'last_run') {
    await loadLatestRiskReport();
    return;
  }
  await loadRiskResultsForMetricsWindow(windowId);
}
async function loadRiskFlaggedIds() {
  riskViewFlaggedIds.value = [];
  const meta = riskViewMeta.value;
  if (!site.value || !component.value || !meta?.parentPlaybook || !meta?.strategyDir) return;
  const s = encodeURIComponent(site.value);
  const c = encodeURIComponent(component.value);
  const strat = encodeURIComponent(meta.strategyDir);
  const parent = encodeURIComponent(meta.parentPlaybook);
  try {
    const res = await api(`/api/sites/${s}/${c}/flagged-prompts?strategy=${strat}&parent=${parent}`);
    riskViewFlaggedIds.value = res.prompt_ids || [];
  } catch {
    riskViewFlaggedIds.value = [];
  }
}

function isRiskPromptFlagged(row) {
  const id = String(row?.id || '').trim();
  return !!(id && riskViewFlaggedIds.value.includes(id));
}

async function flagRiskPrompt(row) {
  const meta = riskViewMeta.value;
  const reportPath = String(row?.reportPath || meta?.reportPath || '').trim();
  if (!reportPath || !row) return;
  riskFlagBusy.value = true;
  riskFlagMsg.value = '';
  const s = encodeURIComponent(site.value);
  const c = encodeURIComponent(component.value);
  try {
    const res = await api(`/api/sites/${s}/${c}/flag-prompt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        report_path: reportPath,
        prompt_id: row.id || '',
        position: row.index,
      }),
    });
    riskViewFlaggedIds.value = res.flagged_ids || [];
    const suiteName = res.playbook || 'flagged suite';
    if (res.already_flagged) {
      riskFlagMsg.value = `Already in ${suiteName} (${res.flagged_count} prompt(s)).`;
    } else {
      riskFlagMsg.value = `Added to ${suiteName} (${res.flagged_count} prompt(s)).`;
    }
    if (tab.value === 'run' || tab.value === 'generate') {
      await ctx.loadRunTestFiles({ applySaved: false });
    }
  } catch (e) {
    riskFlagMsg.value = e.message || 'Failed to flag prompt.';
  } finally {
    riskFlagBusy.value = false;
  }
}

const riskDeleteBusy = ref(false);
const riskDeleteArmedKey = ref('');
let riskDeleteArmedTimer = null;
const RISK_DELETE_ARM_MS = 3000;

function riskDeleteRowKey(row) {
  if (!row) return '';
  const id = String(row.id || '').trim();
  if (id) return id;
  return `idx:${row.index}`;
}

function isRiskDeleteArmed(row) {
  const key = riskDeleteRowKey(row);
  return !!(key && riskDeleteArmedKey.value === key);
}

function clearRiskDeleteArmed() {
  if (riskDeleteArmedTimer) {
    clearTimeout(riskDeleteArmedTimer);
    riskDeleteArmedTimer = null;
  }
  riskDeleteArmedKey.value = '';
}

function armRiskDelete(row) {
  const key = riskDeleteRowKey(row);
  if (!key) return;
  if (riskDeleteArmedTimer) clearTimeout(riskDeleteArmedTimer);
  riskDeleteArmedKey.value = key;
  riskDeleteArmedTimer = setTimeout(() => {
    riskDeleteArmedKey.value = '';
    riskDeleteArmedTimer = null;
  }, RISK_DELETE_ARM_MS);
}

async function onRiskDeleteClick(row) {
  if (!row || riskDeleteBusy.value) return;
  if (!isRiskDeleteArmed(row)) {
    armRiskDelete(row);
    return;
  }
  clearRiskDeleteArmed();
  await deleteRiskReportEntry(row);
}

async function deleteRiskReportEntry(row) {
  const meta = riskViewMeta.value;
  const reportPath = String(row?.reportPath || meta?.reportPath || '').trim();
  if (!reportPath || !row || !site.value || !component.value) return;
  const label = row.id || row.label || 'this entry';
  riskDeleteBusy.value = true;
  riskFlagMsg.value = '';
  const s = encodeURIComponent(site.value);
  const c = encodeURIComponent(component.value);
  try {
    const res = await api(`/api/sites/${s}/${c}/report-entry`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        report_path: reportPath,
        prompt_id: row.id || '',
        position: row.index,
      }),
    });
    clearRiskDeleteArmed();
    await syncRiskTableToMetricsWindow();
    const left = typeof res.remaining_count === 'number'
      ? res.remaining_count
      : riskViewResults.value.length;
    riskFlagMsg.value = `Deleted ${res.removed_id || label}. ${left} entr${left === 1 ? 'y' : 'ies'} remaining.`;
  } catch (e) {
    riskFlagMsg.value = e.message || 'Failed to delete entry.';
  } finally {
    riskDeleteBusy.value = false;
  }
}

async function loadRiskReport(path) {
  if (!site.value || !component.value) return;
  const hadRows = Array.isArray(riskViewResults.value) && riskViewResults.value.length > 0;
  if (!hadRows) riskViewLoading.value = true;
  clearRiskDeleteArmed();
  try {
    if (typeof ctx.loadLogs === 'function') await ctx.loadLogs();
    const reports = riskProbeReports.value;
    if (!reports.length) {
      selectedRiskReportPath.value = '';
      riskViewResults.value = [];
      riskViewMeta.value = null;
      scheduleRiskMetricsRefresh();
      return;
    }
    const preferred = path !== undefined && path !== null && path !== ''
      ? path
      : (selectedRiskReportPath.value || '');
    // Prefer an explicit probe path; ignore attack/manual if somehow selected.
    const preferredOk = preferred && isProbePipelineReportPath(preferred)
      && reports.some((r) => r.path === preferred);
    const targetPath = preferredOk ? preferred : reports[0].path;
    selectedRiskReportPath.value = targetPath;
    const data = await api(`/api/log?path=${encodeURIComponent(targetPath)}`);
    expandedRiskRows.value = {};
    expandedRiskPromptRows.value = {};
    expandedRiskReasonRows.value = {};
    riskViewResults.value = parseRiskReportRows(data, targetPath);
    riskTablePage.value = 1;
    riskViewMeta.value = {
      playbook: data.playbook_id || data.playbook || '',
      strategy: data.strategy || '',
      strategyDir: (data.strategy || 'zero_shot').replace(/_/g, '-'),
      parentPlaybook: parentPlaybookStemFromReport(data),
      sourceFile: data.source_file || '',
      reportPath: targetPath,
      timestamp: data.timestamp || '',
    };
    _cacheRiskReportSeverity(targetPath, _severityFromRiskViewResults());
    _clearLivePeriodMetrics();
    await loadRiskFlaggedIds();
    scheduleRiskMetricsRefresh();
  } catch (e) {
    console.error(e);
    if (!hadRows) {
      riskViewResults.value = [];
      riskViewMeta.value = null;
    }
    scheduleRiskMetricsRefresh();
  } finally {
    riskViewLoading.value = false;
  }
}

function loadLatestRiskReport() {
  selectedRiskReportPath.value = '';
  return loadRiskReport();
}

function onSelectedRiskReportChange() {
  // Window owns the table when not last_run; report picker only updates selection meta.
  if (_metricsWindowId() !== 'last_run') return;
  if (selectedRiskReportPath.value) loadRiskReport(selectedRiskReportPath.value);
}

function toggleRiskViewRow(i) {
  expandedRiskRows.value = { ...expandedRiskRows.value, [i]: !expandedRiskRows.value[i] };
}

function toggleRiskPromptRow(i) {
  expandedRiskPromptRows.value = { ...expandedRiskPromptRows.value, [i]: !expandedRiskPromptRows.value[i] };
}

function toggleRiskReasonRow(i) {
  expandedRiskReasonRows.value = { ...expandedRiskReasonRows.value, [i]: !expandedRiskReasonRows.value[i] };
}

function riskViewCopyKey(rowIndex, kind) {
  return `${rowIndex}:${kind}`;
}

function riskViewCellCopied(rowIndex, kind) {
  return riskViewCopiedKey.value === riskViewCopyKey(rowIndex, kind);
}

async function copyRiskViewText(text, rowIndex, kind) {
  const value = (text ?? '').toString();
  if (!value || value === '-') return;
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const ta = document.createElement('textarea');
    ta.value = value;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch { /* ignore */ }
    document.body.removeChild(ta);
  }
  riskViewCopiedKey.value = riskViewCopyKey(rowIndex, kind);
  if (riskViewCopiedTimer) clearTimeout(riskViewCopiedTimer);
  riskViewCopiedTimer = setTimeout(() => {
    if (riskViewCopiedKey.value === riskViewCopyKey(rowIndex, kind)) {
      riskViewCopiedKey.value = '';
    }
  }, 1500);
}

    const api_out = {
      risk,
      RISK_TIME_WINDOWS,
      EXPORT_RISK_LEVELS,
      RISK_WINDOW_PREFIX,
      riskWindowValue,
      riskWindowIdFromValue,
      riskWindowCounts,
      riskAssessEnabled,
      riskViewResults,
      riskViewLoading,
      riskViewMeta,
      riskLevelFilter,
      riskTablePage,
      RISK_TABLE_PAGE_SIZE,
      riskWindowRowsLoading,
      riskFilteredResults,
      riskPagedResults,
      riskTablePageCount,
      riskTableRangeLabel,
      riskWindowStatusLabel,
      toggleRiskLevelFilter,
      isRiskLevelFilterActive,
      riskTablePrevPage,
      riskTableNextPage,
      syncRiskTableToMetricsWindow,
      loadRiskResultsForMetricsWindow,
      riskViewFlaggedIds,
      riskFlagMsg,
      riskFlagBusy,
      selectedRiskReportPath,
      expandedRiskRows,
      expandedRiskPromptRows,
      expandedRiskReasonRows,
      riskViewCopiedKey,
      riskViewCopiedTimer,
      _savedRiskViewLayout,
      riskViewLayout,
      persistRiskViewLayout,
      toggleRiskViewMinimize,
      toggleRiskViewMaximize,
      riskViewMaximizedActive,
      formatRiskReportLabel,
      isProbePipelineReportPath,
      riskProbeReports,
      riskMetricsWindowCounts,
      riskMetricsLoading,
      refreshRiskMetricsWindowCounts,
      scheduleRiskMetricsRefresh,
      findingsMetricsWindow,
      FINDINGS_METRICS_WINDOWS,
      severityRank,
      sortRiskRowsBySeverity,
      completeSeverityCounts,
      summarizeReportSeverities,
      formatSeveritySummary,
      normalizeExportRiskLevel,
      parentPlaybookStemFromReport,
      parseRiskReportRows,
      loadRiskFlaggedIds,
      isRiskPromptFlagged,
      flagRiskPrompt,
      riskDeleteBusy,
      riskDeleteArmedKey,
      riskDeleteArmedTimer,
      RISK_DELETE_ARM_MS,
      riskDeleteRowKey,
      isRiskDeleteArmed,
      clearRiskDeleteArmed,
      armRiskDelete,
      onRiskDeleteClick,
      deleteRiskReportEntry,
      loadRiskReport,
      loadLatestRiskReport,
      appendLiveRiskResult,
      beginLiveRiskAssessment,
      mapRiskResultRow,
      onSelectedRiskReportChange,
      toggleRiskViewRow,
      toggleRiskPromptRow,
      toggleRiskReasonRow,
      riskViewCopyKey,
      riskViewCellCopied,
      copyRiskViewText
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
