/**
 * Domain module: useExport
 */
(function (G) {
  'use strict';

  G.useExport = function useExport(ctx) {
    const {
      EXPORT_RISK_LEVELS,
      RISK_TIME_WINDOWS,
      armConfirm,
      clearConfirmArmed,
      component,
      computed,
      isConfirmArmed,
      jobs,
      logs,
      nextTick,
      onMounted,
      reactive,
      ref,
      risk,
      riskWindowIdFromValue,
      site,
      watch
    } = ctx;
    const api = G.api;

const _savedExportResultsLayout = localStorage.getItem('genbounty_export_results_layout');
const exportResultsLayout = ref(
  _savedExportResultsLayout === 'maximized' || _savedExportResultsLayout === 'minimized'
    ? _savedExportResultsLayout
    : 'normal'
);

function persistExportResultsLayout() {
  localStorage.setItem('genbounty_export_results_layout', exportResultsLayout.value);
}

function toggleExportResultsMinimize() {
  exportResultsLayout.value = exportResultsLayout.value === 'minimized' ? 'normal' : 'minimized';
  persistExportResultsLayout();
}

function toggleExportResultsMaximize() {
  exportResultsLayout.value = exportResultsLayout.value === 'maximized' ? 'normal' : 'maximized';
  persistExportResultsLayout();
}

const exportResultsMaximizedActive = computed(
  () => exportResultsLayout.value === 'maximized'
);

const exportWindowCounts = computed(() => {
  const now = Date.now() / 1000;
  const reports = logs.reports || [];
  const counts = {};
  for (const w of RISK_TIME_WINDOWS) {
    counts[w.id] = reports.filter(r => (r.mtime || 0) >= now - w.seconds).length;
  }
  return counts;
});

const exp = reactive({
  report: '',
  user_id: '',
  autoAfterAssess: false,
  riskLevels: {
    critical: true,
    high: true,
    medium: true,
    low: false,
    informational: false,
    indeterminate: false,
  },
});
const expSaved = ref(false);
const expSaving = ref(false);
const expSaveError = ref('');

function normalizeExportRiskLevel(row) {
  const aliases = { compliant: 'low', mitigated: 'low' };
  const raw = String(row?.risk_level || '').trim().toLowerCase();
  const level = aliases[raw] || raw;
  return EXPORT_RISK_LEVELS.some(l => l.id === level) ? level : 'indeterminate';
}

const expSelectedRiskLevels = computed(() =>
  EXPORT_RISK_LEVELS.filter(l => exp.riskLevels[l.id]).map(l => l.id),
);

function countExportableResults(rows) {
  const allowed = new Set(expSelectedRiskLevels.value);
  if (!allowed.size) return 0;
  return (rows || []).filter(r => allowed.has(normalizeExportRiskLevel(r))).length;
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
    .filter(l => counts[l.id])
    .map(l => `${counts[l.id]} ${l.label}`)
    .join(', ');
}

function toggleExpRiskLevel(id) {
  exp.riskLevels[id] = !exp.riskLevels[id];
}

const exportEnabled = computed(() => {
  if (!exp.report || !expSelectedRiskLevels.value.length) return false;
  const windowId = riskWindowIdFromValue(exp.report);
  if (windowId) return (exportWindowCounts.value[windowId] || 0) > 0;
  if (expPreview.value && expPreview.value.exportCount === 0) return false;
  return true;
});

const exportSubmitBlockedMessage = computed(() => {
  if (!exp.report) {
    return 'Select a pipeline report before submitting.';
  }
  if (!expSelectedRiskLevels.value.length) {
    return 'Select at least one risk level under Export settings.';
  }
  const windowId = riskWindowIdFromValue(exp.report);
  if (windowId) {
    if (!(exportWindowCounts.value[windowId] || 0)) {
      return 'No assessed reports in this time window. Run Attack and Analysis first.';
    }
    return null;
  }
  const preview = expPreview.value;
  if (preview && preview.count > 0 && preview.exportCount === 0) {
    const inReport = preview.severitySummary
      ? ` (${preview.severitySummary})`
      : '';
    const selected = EXPORT_RISK_LEVELS
      .filter(l => exp.riskLevels[l.id])
      .map(l => l.label)
      .join(', ');
    return (
      `No results match your export filter. This report has ${preview.count} assessed result(s)${inReport}, `
      + `but none at ${selected}. Enable the matching risk level(s) above - for example Low when attacks were blocked.`
    );
  }
  if (!expCreds.has_api_key) {
    return 'Configure Genbounty API key before submitting.';
  }
  if (!(exp.user_id || '').trim()) {
    return 'Enter a User ID (saved with export settings).';
  }
  return null;
});
const expResult = ref(null);
const expPreview = ref(null);
// api_key stored server-side in .env; host is hardcoded; user_id is per-export
const expCreds = reactive({ host: 'https://genbounty.com', has_api_key: false });
const expCredsEdit = reactive({ api_key: '' });
const expCredsSaving = ref(false);
const expCredsMsg = ref('');

async function loadExpCreds() {
  try {
    const c = await api('/api/credentials');
    expCreds.host = c.host || 'https://genbounty.com';
    expCreds.has_api_key = c.has_api_key || false;
    expCredsEdit.api_key = '';
  } catch { /* ignore */ }
}

function applyExportConfig(exportCfg) {
  const block = exportCfg || {};
  exp.autoAfterAssess = !!block.auto_after_assess;
  const levels = Array.isArray(block.risk_levels) ? block.risk_levels : [];
  for (const lvl of EXPORT_RISK_LEVELS) {
    exp.riskLevels[lvl.id] = levels.length ? levels.includes(lvl.id) : exp.riskLevels[lvl.id];
  }
  if (block.user_id) exp.user_id = block.user_id;
}

async function loadExportSettings() {
  if (!site.value || !component.value) return;
  expSaveError.value = '';
  try {
    await loadExpCreds();
    const data = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`,
    );
    applyExportConfig(data.export);
    const c = await api('/api/credentials');
    // Prefer component config, then .env GENBOUNTY_USER_ID from credentials API.
    if (data.export?.user_id) exp.user_id = data.export.user_id;
    else if (c.user_id) exp.user_id = c.user_id;
  } catch (e) {
    expSaveError.value = String(e);
  }
}

async function saveExportSettings() {
  if (!site.value || !component.value) return;
  expSaving.value = true;
  expSaveError.value = '';
  expSaved.value = false;
  try {
    const existing = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`,
    );
    const userId = (exp.user_id || '').trim();
    const payload = {
      ...existing,
      export: {
        auto_after_assess: exp.autoAfterAssess,
        risk_levels: expSelectedRiskLevels.value,
        user_id: userId,
      },
    };
    await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: payload }),
      },
    );
    // Keep .env GENBOUNTY_USER_ID in sync when a user id is set.
    if (userId) {
      try {
        await api('/api/credentials', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId }),
        });
      } catch { /* non-fatal */ }
    }
    expSaved.value = true;
    setTimeout(() => { expSaved.value = false; }, 3000);
  } catch (e) {
    expSaveError.value = String(e);
  } finally {
    expSaving.value = false;
  }
}

async function saveExpCreds() {
  expCredsSaving.value = true;
  expCredsMsg.value = '';
  try {
    const result = await api('/api/credentials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: expCredsEdit.api_key }),
    });
    expCreds.host = result.host || 'https://genbounty.com';
    expCreds.has_api_key = result.has_api_key;
    expCredsEdit.api_key = '';
    expCredsMsg.value = 'Saved to .env';
  } catch (e) {
    expCredsMsg.value = 'Save failed: ' + e.message;
  } finally {
    expCredsSaving.value = false;
  }
}

async function clearExpCreds() {
  if (!isConfirmArmed('exp-creds')) {
    armConfirm('exp-creds');
    return;
  }
  clearConfirmArmed('exp-creds');
  await api('/api/credentials', { method: 'DELETE' });
  expCreds.host = 'https://genbounty.com';
  expCreds.has_api_key = false;
  expCredsEdit.api_key = '';
  expCredsMsg.value = 'API key cleared';
}

async function refreshExpPreview() {
  const path = exp.report;
  expPreview.value = null;
  if (!path) return;
  const windowId = riskWindowIdFromValue(path);
  const levels = expSelectedRiskLevels.value;
  if (windowId) {
    expPreview.value = {
      batchReports: exportWindowCounts.value[windowId] || 0,
      batchLabel: RISK_TIME_WINDOWS.find(w => w.id === windowId)?.label || windowId,
      riskLevels: levels,
    };
    return;
  }
  try {
    const data = await api(`/api/log?path=${encodeURIComponent(path)}`);
    const rows = data.adversarial_results || [];
    const exportCount = countExportableResults(rows);
    const severityCounts = summarizeReportSeverities(rows);
    expPreview.value = {
      count: rows.length,
      exportCount,
      severitySummary: formatSeveritySummary(severityCounts),
      playbook: data.playbook || '',
      timestamp: data.timestamp || '',
      riskLevels: levels,
    };
  } catch { /* ignore */ }
}

async function startExport() {
  expResult.value = null;
  if (!expSelectedRiskLevels.value.length) return;
  const windowId = riskWindowIdFromValue(exp.report);
  const params = {
    user_id: (exp.user_id || '').trim(),
    risk_levels: expSelectedRiskLevels.value,
  };
  if (windowId) {
    params.time_window = windowId;
  } else {
    params.report = exp.report;
  }
  const job = await ctx.startJob('export', params);
  if (job && job.id) {
    const poll = setInterval(async () => {
      const j = await api(`/api/jobs/${job.id}`);
      if (j.status !== 'running' && j.status !== 'pending') {
        clearInterval(poll);
        try { expResult.value = await api(`/api/jobs/${job.id}/export-result`); } catch { /* ignore */ }
      }
    }, 2000);
  }
}

const jsonExporting = ref(false);

function filterReportForExport(data) {
  const allowed = new Set(expSelectedRiskLevels.value);
  const rows = (data.adversarial_results || []).filter(r => allowed.has(normalizeExportRiskLevel(r)));
  return { ...data, adversarial_results: rows };
}

function downloadJsonFile(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function exportReportAsJson() {
  if (!exportEnabled.value || jsonExporting.value) return;
  jsonExporting.value = true;
  try {
    const windowId = riskWindowIdFromValue(exp.report);
    let reportPaths = [];
    if (windowId) {
      const now = Date.now() / 1000;
      const window = RISK_TIME_WINDOWS.find(w => w.id === windowId);
      reportPaths = (logs.reports || [])
        .filter(r => window && (r.mtime || 0) >= now - window.seconds)
        .map(r => r.path);
    } else {
      reportPaths = [exp.report];
    }
    if (!reportPaths.length) return;

    const filtered = [];
    for (const path of reportPaths) {
      const data = await api(`/api/log?path=${encodeURIComponent(path)}`);
      filtered.push(filterReportForExport(data));
    }

    if (windowId) {
      const label = RISK_TIME_WINDOWS.find(w => w.id === windowId)?.label || windowId;
      const slug = label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      downloadJsonFile(`pipeline_reports_${slug}.json`, { reports: filtered });
    } else {
      const name = (logs.reports.find(r => r.path === exp.report)?.name || 'pipeline_report')
        .replace(/[^\w.-]+/g, '_');
      downloadJsonFile(`${name}_export.json`, filtered[0]);
    }
  } catch (e) {
    alert('JSON export failed: ' + e.message);
  } finally {
    jsonExporting.value = false;
  }
}

    const api_out = {
      exportResultsLayout,
      exportResultsMaximizedActive,
      toggleExportResultsMinimize,
      toggleExportResultsMaximize,
      exportWindowCounts,
      exp,
      expSaved,
      expSaving,
      expSaveError,
      normalizeExportRiskLevel,
      expSelectedRiskLevels,
      countExportableResults,
      summarizeReportSeverities,
      formatSeveritySummary,
      toggleExpRiskLevel,
      exportEnabled,
      exportSubmitBlockedMessage,
      expResult,
      expPreview,
      expCreds,
      expCredsEdit,
      expCredsSaving,
      expCredsMsg,
      loadExpCreds,
      applyExportConfig,
      loadExportSettings,
      saveExportSettings,
      saveExpCreds,
      clearExpCreds,
      refreshExpPreview,
      startExport,
      jsonExporting,
      filterReportForExport,
      downloadJsonFile,
      exportReportAsJson
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
