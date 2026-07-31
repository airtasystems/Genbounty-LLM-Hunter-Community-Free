/**
 * Domain module: useRecon
 */
(function (G) {
  'use strict';

  G.useRecon = function useRecon(ctx) {
    const {
      activePlaybookId,
      armConfirm,
      clearConfirmArmed,
      component,
      computed,
      isConfirmArmed,
      jobs,
      nextTick,
      onMounted,
      reactive,
      ref,
      site,
      tab,
      watch
    } = ctx;
    const api = G.api;

// --- Recon tab ---
const reconRecord = ref(null);
const reconJsonText = ref('');
const reconViewMode = ref('overview');
const reconDirty = ref(false);
const reconExists = ref(false);
const reconLoading = ref(false);
const reconSaving = ref(false);
const reconError = ref('');
const reconMsg = ref('');
const reconMode = ref('connected');
const reconManualUrl = ref('');
const reconJobId = ref(null);
const reconReportPath = ref('');
const reconAggregateAllReports = ref(false);

// Minimal fleet stubs (fleet UI/API removed from split; keep watcher/modal bindings safe).
const fleetPlan = reactive({
  summary: '',
  error: '',
  runnable_count: 0,
  plays: [],
});
const fleetPlanRevealed = ref(false);
const fleetPlanLoading = ref(false);
const showFleetGenerateModal = ref(false);
const canGenerateCampaignFleet = computed(() => !!(reconExists.value && site.value && component.value));
function clearFleetPlan() {
  fleetPlan.summary = '';
  fleetPlan.error = '';
  fleetPlan.runnable_count = 0;
  fleetPlan.plays = [];
  fleetPlanRevealed.value = false;
}
async function loadFleetPlan() {
  clearFleetPlan();
}
async function generateCampaignFleet() {
  /* fleet generate removed from Vue split */
}
function cancelFleetGenerate() {
  showFleetGenerateModal.value = false;
}
async function confirmFleetGenerate() {
  showFleetGenerateModal.value = false;
  await generateCampaignFleet();
}

// Must be after reconExists is declared (clearFleetPlan / button gate use it).
watch(reconExists, () => { clearFleetPlan(); });
const reconRunning = computed(() => {
  if (!reconJobId.value) return false;
  const j = jobs.value.find(x => x.id === reconJobId.value);
  return j && ctx.jobIsActive(j.status) && j.type === 'recon';
});
const reconFromReportRunning = computed(() => {
  if (!reconJobId.value) return false;
  const j = jobs.value.find(x => x.id === reconJobId.value);
  return j && ctx.jobIsActive(j.status) && j.type === 'recon_from_report';
});

function normalizeIntelPlaybookId(raw) {
  const text = String(raw || '').trim();
  if (!text) return '';
  return text.split('/').pop().replace(/\.json$/, '').replace(/-/g, '_');
}

function emptyIntelTemplate(playbookId) {
  const pid = normalizeIntelPlaybookId(playbookId);
  return {
    playbook_id: pid,
    play_category: '',
    updated_at: new Date().toISOString(),
    last_strategy: '',
    last_report: '',
    capabilities: [],
    tools: [],
    integrations: [],
    model_hints: [],
    security_observations: [],
    attack_surface_notes: [],
    recon_findings: [],
    recon_rounds: [],
    recon_round_at: '',
    grounding_issues: [],
    ui_capability_response: '',
    credentials_and_paths: null,
  };
}

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function prettyScalar(value) {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function prettyComplex(value) {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return prettyScalar(value);
  }
  if (Array.isArray(value)) {
    if (!value.length) return '-';
    try { return JSON.stringify(value, null, 2); } catch (_) { return String(value); }
  }
  if (typeof value === 'object') {
    if (!Object.keys(value).length) return '-';
    try { return JSON.stringify(value, null, 2); } catch (_) { return String(value); }
  }
  return String(value);
}

function prettyRoundLabel(round, index) {
  if (round == null) return `Round ${index + 1}`;
  if (typeof round !== 'object') return String(round);
  const parts = [
    round.at,
    round.strategy,
    round.playbook_id,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : `Round ${index + 1}`;
}

const intelSelectedId = ref('');
const intelFiles = ref([]);
const intelListLoading = ref(false);
const intelViewMode = ref('overview');
const intelRecord = ref(null);
const intelJsonText = ref('');
const intelDirty = ref(false);
const intelExists = ref(false);
const intelLoading = ref(false);
const intelSaving = ref(false);
const intelMsg = ref('');
const intelError = ref('');

const capEnabled = ref(true);
const capData = reactive({
  updated_at: '',
  last_extract_at: '',
  scanned_reports: [],
  entries: [],
});
const capLoading = ref(false);
const capSaving = ref(false);
const capDirty = ref(false);
const capMsg = ref('');
const capError = ref('');
const capJobId = ref(null);
const capExtractRunning = computed(() => {
  if (!capJobId.value) return false;
  const j = jobs.value.find(x => x.id === capJobId.value);
  return j && ctx.jobIsActive(j.status);
});

function formatCapSource(path) {
  const text = String(path || '');
  if (!text) return '-';
  const parts = text.replace(/\\/g, '/').split('/');
  const idx = parts.lastIndexOf('logs');
  if (idx >= 0 && parts[idx + 1]) return `${parts[idx + 1]}/pipeline_report.json`;
  return parts.slice(-2).join('/');
}

function applyCapPayload(res) {
  capEnabled.value = res.enabled !== false;
  const data = res.data || {};
  capData.updated_at = data.updated_at || '';
  capData.last_extract_at = data.last_extract_at || '';
  capData.scanned_reports = Array.isArray(data.scanned_reports) ? data.scanned_reports : [];
  capData.entries = Array.isArray(data.entries) ? data.entries.map(e => ({ ...e })) : [];
  capDirty.value = false;
}

async function loadCredentialsAndPaths() {
  capError.value = '';
  if (!site.value || !component.value) {
    applyCapPayload({ enabled: true, data: emptyInventoryLike() });
    return;
  }
  capLoading.value = true;
  try {
    const res = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/credentials-and-paths`
    );
    applyCapPayload(res);
  } catch (e) {
    capError.value = String(e.message || e);
  } finally {
    capLoading.value = false;
  }
}

function emptyInventoryLike() {
  return {
    updated_at: '',
    last_extract_at: '',
    scanned_reports: [],
    entries: [],
  };
}

async function saveCapEnabled() {
  if (!site.value || !component.value) return;
  capSaving.value = true;
  capError.value = '';
  capMsg.value = '';
  try {
    const res = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/credentials-and-paths`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !!capEnabled.value }),
      }
    );
    // Toggle only updates the setting - do not clobber unsaved entry edits.
    if (capDirty.value) {
      capEnabled.value = res.enabled !== false;
    } else {
      applyCapPayload(res);
    }
    capMsg.value = capEnabled.value
      ? 'Auto-extract on Analysis enabled'
      : 'Auto-extract on Analysis disabled';
  } catch (e) {
    capError.value = String(e.message || e);
    if (!capDirty.value) await loadCredentialsAndPaths();
  } finally {
    capSaving.value = false;
  }
}

async function saveCapEntries() {
  if (!site.value || !component.value) return;
  capSaving.value = true;
  capError.value = '';
  capMsg.value = '';
  try {
    const res = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/credentials-and-paths`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entries: capData.entries }),
      }
    );
    applyCapPayload(res);
    capMsg.value = 'Credentials inventory saved';
  } catch (e) {
    capError.value = String(e.message || e);
  } finally {
    capSaving.value = false;
  }
}

function removeCapEntry(index) {
  if (index < 0 || index >= (capData.entries || []).length) return;
  capData.entries.splice(index, 1);
  capDirty.value = true;
}

async function pullCredentialsFromReports() {
  if (!site.value || !component.value) return;
  capError.value = '';
  capMsg.value = '';
  try {
    const job = await ctx.startJob('credentials_from_reports', {
      aggregate_all: true,
      force: true,
    });
    capJobId.value = job.id;
    capMsg.value = 'Pulling credentials/paths from all pipeline reports…';
  } catch (e) {
    capError.value = String(e.message || e);
  }
}

const intelActiveRunId = computed(() => normalizeIntelPlaybookId(activePlaybookId.value || ctx.run.playbook));

const intelSelectedSummary = computed(() => {
  if (!intelSelectedId.value) return null;
  return (intelFiles.value || []).find(f => f.playbook_id === intelSelectedId.value) || null;
});

function intelSyncJsonFromRecord() {
  if (!intelRecord.value) {
    intelJsonText.value = '';
    return;
  }
  intelJsonText.value = JSON.stringify(intelRecord.value, null, 2);
}

function intelApplyJsonToRecord() {
  const parsed = JSON.parse(intelJsonText.value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Intel JSON must be an object');
  }
  intelRecord.value = parsed;
}

async function loadIntelList(preferId = '') {
  intelError.value = '';
  if (!site.value || !component.value) {
    intelFiles.value = [];
    intelSelectedId.value = '';
    return;
  }
  intelListLoading.value = true;
  try {
    const res = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/intel`
    );
    intelFiles.value = Array.isArray(res.items) ? res.items : [];
    const preferred = normalizeIntelPlaybookId(
      preferId || activePlaybookId.value || intelActiveRunId.value
    );
    if (!intelDirty.value) {
      intelSelectedId.value = preferred || '';
    }
    if (tab.value === 'intel' && intelSelectedId.value) await loadIntel();
  } catch (e) {
    intelError.value = String(e.message || e);
  } finally {
    intelListLoading.value = false;
  }
}

// Lean intel entries are {text: "..."} (or bare strings / tool {name}).
function intelEntryText(item) {
  if (item == null) return '';
  if (typeof item === 'object') return String(item.text ?? item.name ?? '');
  return String(item);
}

function draftNewIntel() {
  intelError.value = '';
  intelMsg.value = '';
  const pid = normalizeIntelPlaybookId(activePlaybookId.value || intelSelectedId.value);
  if (!pid) {
    intelError.value = 'Select a play in the header first';
    return;
  }
  if (intelExists.value && !intelDirty.value) {
    intelSelectedId.value = pid;
    loadIntel();
    return;
  }
  if (intelDirty.value && !isConfirmArmed('intel-draft')) {
    armConfirm('intel-draft');
    return;
  }
  clearConfirmArmed('intel-draft');
  intelSelectedId.value = pid;
  intelRecord.value = emptyIntelTemplate(pid);
  intelSyncJsonFromRecord();
  intelExists.value = false;
  intelDirty.value = true;
  intelMsg.value = `Draft intel for ${pid} - save to create`;
}

async function loadIntel() {
  intelMsg.value = '';
  intelError.value = '';
  if (!site.value || !component.value || !intelSelectedId.value) {
    intelRecord.value = null;
    intelJsonText.value = '';
    intelExists.value = false;
    return;
  }
  intelLoading.value = true;
  try {
    const res = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/intel/${encodeURIComponent(intelSelectedId.value)}`
    );
    if (res.exists && res.data) {
      intelRecord.value = res.data;
      intelExists.value = true;
      intelSyncJsonFromRecord();
      intelDirty.value = false;
    } else {
      intelRecord.value = null;
      intelJsonText.value = '';
      intelExists.value = false;
      intelDirty.value = false;
    }
  } catch (e) {
    intelError.value = String(e.message || e);
  } finally {
    intelLoading.value = false;
  }
}

function setIntelViewMode(mode) {
  const next = mode === 'json' ? 'json' : 'overview';
  if (next === intelViewMode.value) return;
  if (intelViewMode.value === 'json' && next === 'overview') {
    try {
      if (intelJsonText.value.trim()) {
        intelApplyJsonToRecord();
      }
      intelError.value = '';
    } catch (e) {
      intelError.value = String(e.message || e);
      return;
    }
  } else if (intelViewMode.value === 'overview' && next === 'json') {
    intelSyncJsonFromRecord();
  }
  intelViewMode.value = next;
}

async function saveIntel() {
  if (!site.value || !component.value || intelSaving.value) return;
  intelError.value = '';
  intelMsg.value = '';
  intelSaving.value = true;
  try {
    if (intelViewMode.value === 'json') {
      intelApplyJsonToRecord();
    } else if (!intelRecord.value) {
      throw new Error('No intel data to save - paste JSON in the JSON tab or create a draft');
    }
    const pid = normalizeIntelPlaybookId(intelRecord.value?.playbook_id || intelSelectedId.value);
    if (!pid) throw new Error('Intel JSON must include playbook_id');
    intelRecord.value.playbook_id = pid;
    intelSelectedId.value = pid;
    await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/intel/${encodeURIComponent(pid)}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: intelRecord.value }),
      }
    );
    intelExists.value = true;
    intelDirty.value = false;
    intelSyncJsonFromRecord();
    intelMsg.value = `Saved intel for ${pid}`;
    await ctx.setActivePlaybook(pid, { source: 'intel', loadIntelFile: false });
    await loadIntelList(pid);
  } catch (e) {
    intelError.value = String(e.message || e);
  } finally {
    intelSaving.value = false;
  }
}

function intelRevertJson() {
  intelSyncJsonFromRecord();
  intelDirty.value = false;
  intelError.value = '';
  intelMsg.value = '';
}

function intelOnJsonInput() {
  intelDirty.value = true;
  intelMsg.value = '';
}

async function resetIntel() {
  if (!site.value || !component.value || !intelSelectedId.value) return;
  if (intelExists.value && !isConfirmArmed('intel-delete')) {
    armConfirm('intel-delete');
    return;
  }
  clearConfirmArmed('intel-delete');
  intelError.value = '';
  try {
    await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/intel/${encodeURIComponent(intelSelectedId.value)}`,
      { method: 'DELETE' }
    );
    intelRecord.value = null;
    intelJsonText.value = '';
    intelExists.value = false;
    intelDirty.value = false;
    intelMsg.value = 'Intel file deleted';
    intelRecord.value = null;
    intelJsonText.value = '';
    intelExists.value = false;
    intelDirty.value = false;
    await loadIntelList(activePlaybookId.value || intelActiveRunId.value);
  } catch (e) {
    intelError.value = String(e.message || e);
  }
}

function reconSyncJsonFromRecord() {
  if (!reconRecord.value) {
    reconJsonText.value = '';
    return;
  }
  reconJsonText.value = JSON.stringify(reconRecord.value, null, 2);
}

function reconApplyJsonToRecord() {
  const parsed = JSON.parse(reconJsonText.value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Recon JSON must be an object');
  }
  reconRecord.value = parsed;
}

async function loadRecon() {
  reconError.value = '';
  if (!site.value || !component.value) {
    reconRecord.value = null;
    reconJsonText.value = '';
    reconExists.value = false;
    return;
  }
  reconLoading.value = true;
  try {
    await ctx.loadDiscoverContext();
    const res = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/recon`
    );
    if (res.exists && res.data) {
      reconRecord.value = res.data;
      reconExists.value = true;
      reconSyncJsonFromRecord();
      reconDirty.value = false;
    } else {
      reconRecord.value = null;
      reconJsonText.value = '';
      reconExists.value = false;
      reconDirty.value = false;
    }
  } catch (e) {
    reconError.value = String(e.message || e);
  } finally {
    reconLoading.value = false;
  }
}

function setReconViewMode(mode) {
  const next = mode === 'json' ? 'json' : 'overview';
  if (next === reconViewMode.value) return;
  if (reconViewMode.value === 'json' && next === 'overview') {
    try {
      reconApplyJsonToRecord();
      reconError.value = '';
    } catch (e) {
      reconError.value = String(e.message || e);
      return;
    }
  } else if (reconViewMode.value === 'overview' && next === 'json') {
    reconSyncJsonFromRecord();
  }
  reconViewMode.value = next;
}

async function saveRecon() {
  if (!site.value || !component.value || reconSaving.value) return;
  reconError.value = '';
  reconMsg.value = '';
  reconSaving.value = true;
  try {
    if (reconViewMode.value === 'json') {
      reconApplyJsonToRecord();
    } else {
      reconSyncJsonFromRecord();
    }
    await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/recon`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: reconRecord.value }),
      }
    );
    reconExists.value = true;
    reconDirty.value = false;
    reconSyncJsonFromRecord();
    reconMsg.value = 'Saved recon.json';
  } catch (e) {
    reconError.value = String(e.message || e);
  } finally {
    reconSaving.value = false;
  }
}

function reconRevertJson() {
  reconSyncJsonFromRecord();
  reconDirty.value = false;
  reconError.value = '';
}

function reconOnJsonInput() {
  reconDirty.value = true;
  reconMsg.value = '';
}

const reconResetArmed = ref(false);
let reconResetArmedTimer = null;
const RECON_RESET_ARM_MS = 4000;

function clearReconResetArmed() {
  if (reconResetArmedTimer) {
    clearTimeout(reconResetArmedTimer);
    reconResetArmedTimer = null;
  }
  reconResetArmed.value = false;
}

function armReconReset() {
  if (reconResetArmedTimer) clearTimeout(reconResetArmedTimer);
  reconResetArmed.value = true;
  reconResetArmedTimer = setTimeout(() => {
    reconResetArmed.value = false;
    reconResetArmedTimer = null;
  }, RECON_RESET_ARM_MS);
}

const reconResetButtonLabel = computed(() => (
  reconResetArmed.value ? 'Confirm' : 'Reset'
));

watch(reconExists, (exists) => {
  if (!exists) clearReconResetArmed();
});

async function resetRecon() {
  if (!site.value || !component.value || !reconExists.value) return;
  if (!reconResetArmed.value) {
    armReconReset();
    return;
  }
  clearReconResetArmed();
  reconError.value = '';
  try {
    await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/recon`,
      { method: 'DELETE' }
    );
    reconRecord.value = null;
    reconJsonText.value = '';
    reconExists.value = false;
    reconDirty.value = false;
    reconMsg.value = 'Recon file deleted';
  } catch (e) {
    reconError.value = String(e.message || e);
  }
}

async function startRecon() {
  if (!site.value || !component.value) return;
  if (reconMode.value === 'manual_url' && !reconManualUrl.value.trim()) {
    reconError.value = 'Enter a URL for manual recon mode';
    return;
  }
  reconError.value = '';
  reconMsg.value = '';
  const j = await ctx.startJob('recon', {
    mode: reconMode.value,
    manual_url: reconMode.value === 'manual_url' ? reconManualUrl.value.trim() : '',
    overwrite: true,
  });
  j._output.push(`[recon] Queued ${reconMode.value === 'manual_url' ? 'manual URL' : 'connected target'} reconnaissance for ${site.value}/${component.value}`);
  reconJobId.value = j.id;
}

async function startReconFromReport() {
  if (!reconAggregateAllReports.value && !reconReportPath.value) {
    reconError.value = 'Select an assessment report (pipeline_report.json)';
    return;
  }
  if (reconAggregateAllReports.value && !logs.reports.length) {
    reconError.value = 'No assessed reports to aggregate for this component.';
    return;
  }
  reconError.value = '';
  reconMsg.value = '';
  const params = reconAggregateAllReports.value
    ? { aggregate_all: true }
    : { pipeline_report: reconReportPath.value };
  const j = await ctx.startJob('recon_from_report', params);
  j._output.push(
    reconAggregateAllReports.value
      ? `[recon_from_report] Queued batch report recon (${logs.reports.length} report(s)) for ${site.value}/${component.value}`
      : `[recon_from_report] Queued report recon for ${site.value}/${component.value}`
  );
  reconJobId.value = j.id;
}

const reconConnectedSummary = computed(() => {
  const sub = ctx.compCfg.submission || {};
  const transport = (sub.transport || 'ui').toLowerCase();
  if (ctx.discoverTransport.value === 'api' || transport !== 'ui') {
    return {
      transport: sub.transport || 'api',
      target: sub.api_url || sub.start_url || '(not configured)',
      model: sub.api_model || '',
    };
  }
  return {
    transport: 'ui',
    target: sub.start_url || ctx.compCfg.login_url || '(not configured)',
    model: '',
  };
});

const sampleRequestRunning = computed(() => {
  const jid = ctx.activeJobs.sample_request;
  if (!jid) return false;
  const j = jobs.value.find(x => x.id === jid);
  return !!(j && (j.status === 'running' || j.status === 'pending'));
});

/** Experiment Output lines for Risk → Attack LLM rewrite (not a server job). */

    const api_out = {
      reconRecord,
      reconJsonText,
      reconViewMode,
      reconDirty,
      reconExists,
      reconLoading,
      reconSaving,
      reconError,
      reconMsg,
      reconMode,
      reconManualUrl,
      reconJobId,
      reconReportPath,
      reconAggregateAllReports,
      reconRunning,
      reconFromReportRunning,
      normalizeIntelPlaybookId,
      emptyIntelTemplate,
      asList,
      prettyScalar,
      prettyComplex,
      prettyRoundLabel,
      intelSelectedId,
      intelFiles,
      intelListLoading,
      intelViewMode,
      intelRecord,
      intelJsonText,
      intelDirty,
      intelExists,
      intelLoading,
      intelSaving,
      intelMsg,
      intelError,
      capEnabled,
      capData,
      capLoading,
      capSaving,
      capDirty,
      capMsg,
      capError,
      capJobId,
      capExtractRunning,
      formatCapSource,
      applyCapPayload,
      loadCredentialsAndPaths,
      emptyInventoryLike,
      saveCapEnabled,
      saveCapEntries,
      removeCapEntry,
      pullCredentialsFromReports,
      intelActiveRunId,
      intelSelectedSummary,
      intelSyncJsonFromRecord,
      intelApplyJsonToRecord,
      loadIntelList,
      intelEntryText,
      draftNewIntel,
      loadIntel,
      setIntelViewMode,
      saveIntel,
      intelRevertJson,
      intelOnJsonInput,
      resetIntel,
      reconSyncJsonFromRecord,
      reconApplyJsonToRecord,
      loadRecon,
      setReconViewMode,
      saveRecon,
      reconRevertJson,
      reconOnJsonInput,
      reconResetArmed,
      reconResetArmedTimer,
      RECON_RESET_ARM_MS,
      clearReconResetArmed,
      armReconReset,
      reconResetButtonLabel,
      resetRecon,
      startRecon,
      startReconFromReport,
      reconConnectedSummary,
      sampleRequestRunning,
      fleetPlan,
      fleetPlanRevealed,
      fleetPlanLoading,
      showFleetGenerateModal,
      canGenerateCampaignFleet,
      clearFleetPlan,
      loadFleetPlan,
      generateCampaignFleet,
      cancelFleetGenerate,
      confirmFleetGenerate,
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
