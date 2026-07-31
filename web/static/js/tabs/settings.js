/**
 * Domain module: useSettings
 */
(function (G) {
  'use strict';

  G.useSettings = function useSettings(ctx) {
    const {
      armConfirm,
      clearConfirmArmed,
      component,
      components,
      computed,
      findingsMetricsWindow,
      FINDINGS_METRICS_WINDOWS,
      isConfirmArmed,
      logs,
      nextTick,
      normalizeFindingsMetricsWindow,
      onMounted,
      reactive,
      ref,
      settingsTab,
      site,
      sites,
      tab,
      watch
    } = ctx;
    const api = G.api;

const cache = reactive({
  deleteOnServer: false,
  clearLocalStorage: false,
  useGeminiCache: false,
  effectiveGeminiCache: false,
  componentOverride: null,
  useOpenaiCache: true,
  openaiRetention: 'standard',
  useGrokCache: true,
  useAnthropicCache: true,
  anthropicTtl: '5m',
  effectiveOpenaiCache: true,
  effectiveGrokCache: true,
  effectiveAnthropicCache: true,
});
const cacheSettingsSaving = ref(false);
const cacheSettingsMsg = ref('');

const pipelineSettingsMeta = ref(null);
const pipelineSettings = reactive({
  security_assess_concurrency: 4,
  open_loop_prompts: 4,
  closed_loop_prompts: 4,
  payloads_output_dir: 'payloads/generate',
  export_batch_size: 25,
  export_delay_seconds: 2,
  export_max_retries: 6,
  export_retry_base_seconds: 5,
});
const pipelineBounds = reactive({
  security_assess_concurrency: { min: 1, max: 32 },
  open_loop_prompts: { min: 1, max: 64 },
  closed_loop_prompts: { min: 1, max: 64 },
  export_batch_size: { min: 1, max: 2500 },
  export_max_retries: { min: 1, max: 20 },
});
const pipelineSettingsLoading = ref(false);
const pipelineSettingsSaving = ref(false);
const pipelineSettingsMsg = ref('');
const pipelineSettingsError = ref('');

function applyPipelineSettingsPayload(data) {
  pipelineSettingsMeta.value = data || null;
  const values = data?.values || {};
  pipelineSettings.security_assess_concurrency = Number(values.security_assess_concurrency) || 4;
  pipelineSettings.open_loop_prompts = Number(values.open_loop_prompts) || 4;
  pipelineSettings.closed_loop_prompts = Number(values.closed_loop_prompts) || 4;
  pipelineSettings.payloads_output_dir = values.payloads_output_dir || 'payloads/generate';
  const expCfg = data?.export || {};
  pipelineSettings.export_batch_size = Number(expCfg.batch_size) || 25;
  pipelineSettings.export_delay_seconds = Number(expCfg.delay_seconds);
  if (Number.isNaN(pipelineSettings.export_delay_seconds)) pipelineSettings.export_delay_seconds = 2;
  pipelineSettings.export_max_retries = Number(expCfg.max_retries) || 6;
  pipelineSettings.export_retry_base_seconds = Number(expCfg.retry_base_seconds);
  if (Number.isNaN(pipelineSettings.export_retry_base_seconds)) pipelineSettings.export_retry_base_seconds = 5;
  const bounds = data?.bounds || {};
  for (const key of ['security_assess_concurrency', 'open_loop_prompts', 'closed_loop_prompts']) {
    if (bounds[key]) {
      pipelineBounds[key] = {
        min: Number(bounds[key].min) || 1,
        max: Number(bounds[key].max) || 64,
      };
    }
  }
  const exportBounds = data?.export_bounds || {};
  if (exportBounds.batch_size) {
    pipelineBounds.export_batch_size = {
      min: Number(exportBounds.batch_size.min) || 1,
      max: Number(exportBounds.batch_size.max) || 2500,
    };
  }
  if (exportBounds.max_retries) {
    pipelineBounds.export_max_retries = {
      min: Number(exportBounds.max_retries.min) || 1,
      max: Number(exportBounds.max_retries.max) || 20,
    };
  }
}

async function loadPipelineSettings() {
  pipelineSettingsError.value = '';
  pipelineSettingsLoading.value = true;
  try {
    applyPipelineSettingsPayload(await api('/api/pipeline-settings'));
  } catch (e) {
    pipelineSettingsError.value = String(e);
  } finally {
    pipelineSettingsLoading.value = false;
  }
}

async function savePipelineSettings() {
  pipelineSettingsSaving.value = true;
  pipelineSettingsMsg.value = '';
  pipelineSettingsError.value = '';
  try {
    const result = await api('/api/pipeline-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        security_assess_concurrency: pipelineSettings.security_assess_concurrency,
        open_loop_prompts: pipelineSettings.open_loop_prompts,
        closed_loop_prompts: pipelineSettings.closed_loop_prompts,
        payloads_output_dir: pipelineSettings.payloads_output_dir,
        export_batch_size: pipelineSettings.export_batch_size,
        export_delay_seconds: pipelineSettings.export_delay_seconds,
        export_max_retries: pipelineSettings.export_max_retries,
        export_retry_base_seconds: pipelineSettings.export_retry_base_seconds,
      }),
    });
    applyPipelineSettingsPayload({
      ...(pipelineSettingsMeta.value || {}),
      values: result.values || {},
      export: result.export || {},
    });
    pipelineSettingsMsg.value = 'Saved';
    setTimeout(() => { if (pipelineSettingsMsg.value === 'Saved') pipelineSettingsMsg.value = ''; }, 3000);
  } catch (e) {
    pipelineSettingsError.value = 'Save failed: ' + e.message;
  } finally {
    pipelineSettingsSaving.value = false;
  }
}

async function resetPipelineSettingsDefaults() {
  const defaults = pipelineSettingsMeta.value?.defaults || {
    security_assess_concurrency: 4,
    open_loop_prompts: 4,
    closed_loop_prompts: 4,
    payloads_output_dir: 'payloads/generate',
  };
  const exportDefaults = pipelineSettingsMeta.value?.export_defaults || {
    batch_size: 25,
    delay_seconds: 2,
    max_retries: 6,
    retry_base_seconds: 5,
  };
  pipelineSettings.security_assess_concurrency = Number(defaults.security_assess_concurrency) || 4;
  pipelineSettings.open_loop_prompts = Number(defaults.open_loop_prompts) || 4;
  pipelineSettings.closed_loop_prompts = Number(defaults.closed_loop_prompts) || 4;
  pipelineSettings.payloads_output_dir = defaults.payloads_output_dir || 'payloads/generate';
  pipelineSettings.export_batch_size = Number(exportDefaults.batch_size) || 25;
  pipelineSettings.export_delay_seconds = Number(exportDefaults.delay_seconds);
  if (Number.isNaN(pipelineSettings.export_delay_seconds)) pipelineSettings.export_delay_seconds = 2;
  pipelineSettings.export_max_retries = Number(exportDefaults.max_retries) || 6;
  pipelineSettings.export_retry_base_seconds = Number(exportDefaults.retry_base_seconds);
  if (Number.isNaN(pipelineSettings.export_retry_base_seconds)) pipelineSettings.export_retry_base_seconds = 5;
  await savePipelineSettings();
}

async function loadCacheSettings() {
  try {
    let path = '/api/cache-settings';
    if (site.value && component.value) {
      const s = encodeURIComponent(site.value);
      const c = encodeURIComponent(component.value);
      path += `?site=${s}&component=${c}`;
    }
    const s = await api(path);
    cache.useGeminiCache = !!s.gemini_use_cache;
    cache.effectiveGeminiCache = !!s.effective_gemini_use_cache;
    cache.componentOverride = s.component_override;
    cache.useOpenaiCache = !!s.openai_use_cache;
    cache.openaiRetention = s.openai_cache_retention || 'standard';
    cache.useGrokCache = !!s.grok_use_cache;
    cache.useAnthropicCache = !!s.anthropic_use_cache;
    cache.anthropicTtl = s.anthropic_cache_ttl || '5m';
    cache.effectiveOpenaiCache = !!s.effective_openai_use_cache;
    cache.effectiveGrokCache = !!s.effective_grok_use_cache;
    cache.effectiveAnthropicCache = !!s.effective_anthropic_use_cache;
  } catch { /* ignore */ }
}

async function saveCacheSettings() {
  cacheSettingsSaving.value = true;
  cacheSettingsMsg.value = '';
  try {
    const result = await api('/api/cache-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gemini_use_cache: cache.useGeminiCache,
        openai_use_cache: cache.useOpenaiCache,
        openai_cache_retention: cache.openaiRetention,
        grok_use_cache: cache.useGrokCache,
        anthropic_use_cache: cache.useAnthropicCache,
        anthropic_cache_ttl: cache.anthropicTtl,
      }),
    });
    cache.useGeminiCache = !!result.gemini_use_cache;
    cache.useOpenaiCache = !!result.openai_use_cache;
    cache.openaiRetention = result.openai_cache_retention || 'standard';
    cache.useGrokCache = !!result.grok_use_cache;
    cache.useAnthropicCache = !!result.anthropic_use_cache;
    cache.anthropicTtl = result.anthropic_cache_ttl || '5m';
    cacheSettingsMsg.value = 'Cache settings saved';
    await loadCacheSettings();
  } catch (e) {
    cacheSettingsMsg.value = 'Save failed: ' + e.message;
  } finally {
    cacheSettingsSaving.value = false;
  }
}

const corpusStores = reactive({
  learned: false,
  breakthrough: false,
  history: false,
  curated: false,
});
const corpusStoreStats = reactive({
  learned: { exists: false, file_count: 0, bytes: 0 },
  breakthrough: { exists: false, file_count: 0, bytes: 0 },
  history: { exists: false, file_count: 0, bytes: 0 },
  curated: { exists: false, file_count: 0, bytes: 0 },
});
const corpusStoresBusy = ref(false);
const corpusStoresMsg = ref('');
const corpusStoresAnySelected = computed(() => (
  !!corpusStores.learned
  || !!corpusStores.breakthrough
  || !!corpusStores.history
  || !!corpusStores.curated
));

function corpusStoreLabel(storeId) {
  const info = corpusStoreStats[storeId] || {};
  const n = Number(info.file_count) || 0;
  if (!info.exists && n === 0) return 'empty';
  return `${n} file${n === 1 ? '' : 's'}`;
}

function applyCorpusStoreStats(stores) {
  const src = stores || {};
  for (const id of ['learned', 'breakthrough', 'history', 'curated']) {
    const row = src[id] || {};
    corpusStoreStats[id] = {
      exists: !!row.exists,
      file_count: Number(row.file_count) || 0,
      bytes: Number(row.bytes) || 0,
    };
  }
}

async function loadCorpusStores() {
  try {
    const data = await api('/api/corpus-stores');
    applyCorpusStoreStats(data.stores);
  } catch (e) {
    corpusStoresMsg.value = 'Load failed: ' + e.message;
  }
}

async function clearCorpusStoresSelected() {
  const selected = ['learned', 'breakthrough', 'history', 'curated']
    .filter((id) => !!corpusStores[id]);
  if (!selected.length) return;
  if (!isConfirmArmed('corpus-clear')) {
    armConfirm('corpus-clear');
    return;
  }
  clearConfirmArmed('corpus-clear');
  corpusStoresBusy.value = true;
  corpusStoresMsg.value = '';
  try {
    const res = await api('/api/corpus-stores/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stores: selected }),
    });
    applyCorpusStoreStats(res.stores);
    const removed = res.removed || {};
    const parts = Object.keys(removed).map((k) => `${k}: ${removed[k]}`);
    corpusStoresMsg.value = parts.length
      ? `Removed ${parts.join(', ')}.`
      : 'Nothing to remove for the selected stores.';
    if ((res.skipped || []).length) {
      corpusStoresMsg.value += ` Skipped: ${(res.skipped || []).join(', ')}.`;
    }
  } catch (e) {
    corpusStoresMsg.value = 'Delete failed: ' + e.message;
  } finally {
    corpusStoresBusy.value = false;
  }
}

const theoryHistory = reactive({
  path: '',
  entries: [],
  total: 0,
  accepted: 0,
  rejected: 0,
});
const theoryHistoryLoading = ref(false);
const theoryHistoryBusy = ref(false);
const theoryHistoryMsg = ref('');
const theoryHistoryFilterPlaybook = ref('');
const theoryHistoryFilterStrategy = ref('');

async function loadTheoryHistory() {
  if (!site.value || !component.value) {
    theoryHistory.path = '';
    theoryHistory.entries = [];
    theoryHistory.total = 0;
    theoryHistory.accepted = 0;
    theoryHistory.rejected = 0;
    return;
  }
  theoryHistoryLoading.value = true;
  theoryHistoryMsg.value = '';
  try {
    const s = encodeURIComponent(site.value);
    const c = encodeURIComponent(component.value);
    const data = await api(`/api/sites/${s}/${c}/theory-history`);
    theoryHistory.path = data.path || '';
    theoryHistory.entries = data.entries || [];
    theoryHistory.total = data.total || 0;
    theoryHistory.accepted = data.accepted || 0;
    theoryHistory.rejected = data.rejected || 0;
  } catch (e) {
    theoryHistoryMsg.value = 'Load failed: ' + e.message;
  } finally {
    theoryHistoryLoading.value = false;
  }
}

async function clearTheoryHistoryAll() {
  if (!site.value || !component.value) return;
  if (!isConfirmArmed('theory-all')) {
    armConfirm('theory-all');
    return;
  }
  clearConfirmArmed('theory-all');
  theoryHistoryBusy.value = true;
  theoryHistoryMsg.value = '';
  try {
    const s = encodeURIComponent(site.value);
    const c = encodeURIComponent(component.value);
    const res = await api(`/api/sites/${s}/${c}/theory-history`, { method: 'DELETE' });
    theoryHistoryMsg.value = `Removed ${res.removed || 0} entr${(res.removed || 0) === 1 ? 'y' : 'ies'}.`;
    await loadTheoryHistory();
  } catch (e) {
    theoryHistoryMsg.value = 'Clear failed: ' + e.message;
  } finally {
    theoryHistoryBusy.value = false;
  }
}

async function clearTheoryHistoryFiltered() {
  if (!site.value || !component.value) return;
  const playbook = theoryHistoryFilterPlaybook.value.trim();
  const strategy = theoryHistoryFilterStrategy.value.trim();
  if (!playbook && !strategy) {
    theoryHistoryMsg.value = 'Enter a playbook and/or strategy to clear a filtered subset.';
    return;
  }
  if (!isConfirmArmed('theory-filtered')) {
    armConfirm('theory-filtered');
    return;
  }
  clearConfirmArmed('theory-filtered');
  theoryHistoryBusy.value = true;
  theoryHistoryMsg.value = '';
  try {
    const s = encodeURIComponent(site.value);
    const c = encodeURIComponent(component.value);
    const qs = new URLSearchParams();
    if (playbook) qs.set('playbook_id', playbook);
    if (strategy) qs.set('strategy', strategy);
    const res = await api(`/api/sites/${s}/${c}/theory-history?${qs}`, { method: 'DELETE' });
    theoryHistoryMsg.value = `Removed ${res.removed || 0} matching entr${(res.removed || 0) === 1 ? 'y' : 'ies'}.`;
    await loadTheoryHistory();
  } catch (e) {
    theoryHistoryMsg.value = 'Clear failed: ' + e.message;
  } finally {
    theoryHistoryBusy.value = false;
  }
}

async function deleteTheoryHistoryEntry(index) {
  if (!site.value || !component.value) return;
  const key = `theory-entry-${index}`;
  if (!isConfirmArmed(key)) {
    armConfirm(key);
    return;
  }
  clearConfirmArmed(key);
  theoryHistoryBusy.value = true;
  theoryHistoryMsg.value = '';
  try {
    const s = encodeURIComponent(site.value);
    const c = encodeURIComponent(component.value);
    await api(`/api/sites/${s}/${c}/theory-history/${index}`, { method: 'DELETE' });
    theoryHistoryMsg.value = 'Entry deleted.';
    await loadTheoryHistory();
  } catch (e) {
    theoryHistoryMsg.value = 'Delete failed: ' + e.message;
  } finally {
    theoryHistoryBusy.value = false;
  }
}

// Component config
const PROMPT_TEMPLATE_HINT = '{{prompt}}';
const PROMPT_MODEL_HINT = '{{model}}';
const PROMPT_BODY_PLACEHOLDER = '{"prompt": "' + PROMPT_TEMPLATE_HINT + '"}';
const AUTH_HEADER_OPTIONS = [
  { value: 'Authorization', label: 'Authorization (Bearer)' },
  { value: 'x-goog-api-key', label: 'x-goog-api-key' },
  { value: 'x-api-key', label: 'x-api-key' },
  { value: 'api-key', label: 'api-key' },
];

const INPUT_TYPES = ['text', 'textarea', 'contenteditable', 'password', 'email', 'search', 'select', 'combobox', 'checkbox', 'radio', 'click', 'file'];
const compCfg = reactive({
  login_url: '',
  submission: {
    transport: 'ui',
    start_url: '', inputs: [], submit_selector: '', response_selector: '',
    response_within_selector: '', response_text_within_selector: '',
    response_capture_mode: 'last', response_list_selector: '', response_role_selector: '',
    submit_via: 'click', response_wait_ms: 5000,
    api_url: '', api_method: 'POST', api_response_path: 'response', api_model: '',
    api_body_json: '{\n  "prompt": "{{prompt}}"\n}',
    api_headers_json: '{}',
    api_context_mode: '',
    api_messages_prefix_json: '[]',
    upload_url: '', upload_file_field: 'file', upload_response_path: 'document_id',
    multipart_prompt_field: 'prompt', multipart_file_field: 'file',
  },
});
const settingsSchema = ref(null);
const effectiveSettingsDetail = ref(null);
const compSettings = reactive({});
const compSettingsInherited = reactive({});
const compCfgSaved = ref(false);
const compCfgError = ref('');
const compCfgEmpty = ref(false);

function settingMeta(key) {
  return (settingsSchema.value?.meta || {})[key] || { type: 'string', label: key };
}

function settingLabel(key) {
  return settingMeta(key).label || key;
}

function formatSettingValue(val, key) {
  if (key === 'BLOCKED_TYPES') {
    const arr = Array.isArray(val) ? val : [];
    return arr.length ? arr.join(', ') : '(none)';
  }
  if (typeof val === 'boolean') return val ? 'on' : 'off';
  if (val === null || val === undefined || val === '') return '(empty)';
  return String(val);
}

function formatSettingGlobal(key) {
  return formatSettingValue(settingsSchema.value?.globals?.[key], key);
}

function resolveSettingWithoutComponent(key) {
  const d = effectiveSettingsDetail.value?.[key];
  if (!d) return formatSettingGlobal(key);
  if (d.site_override !== undefined && d.site_override !== null && d.site_override !== '') {
    return formatSettingValue(d.site_override, key);
  }
  if (d.global !== undefined && d.global !== null && d.global !== '') {
    return formatSettingValue(d.global, key);
  }
  return formatSettingValue(d.defaults, key);
}

function compSettingInheritHint(key) {
  if (compSettingsInherited[key]) {
    const eff = effectiveSettingsDetail.value?.[key]?.effective;
    return `using ${formatSettingValue(eff, key)} (effective for ${site.value}/${component.value})`;
  }
  return `would use ${resolveSettingWithoutComponent(key)} if checked`;
}

function settingsValuesEqual(a, b, key) {
  if (key === 'BLOCKED_TYPES') {
    const aa = Array.isArray(a) ? [...a].sort().join(',') : '';
    const bb = Array.isArray(b) ? [...b].sort().join(',') : '';
    return aa === bb;
  }
  return String(a ?? '') === String(b ?? '');
}

function browserSettingDiffers(key) {
  if (!settingsSchema.value?.defaults) return false;
  return !settingsValuesEqual(cfg[key], settingsSchema.value.defaults[key], key);
}

function browserSettingDiffersFromDefaults(key) {
  if (!settingsSchema.value?.defaults || settingsTab.value !== 'defaults') return false;
  const globalVal = settingsSchema.value?.globals?.[key];
  if (globalVal === undefined || globalVal === null) return false;
  return !settingsValuesEqual(defaultsCfg[key], globalVal, key);
}

function cloneSettingGlobal(key) {
  const val = settingsSchema.value?.globals?.[key];
  if (key === 'BLOCKED_TYPES') return Array.isArray(val) ? [...val] : [];
  if (typeof val === 'boolean') return val;
  if (val === null || val === undefined) return '';
  return val;
}

function initCompSettingsFromConfig(overrides) {
  if (!settingsSchema.value) return;
  for (const group of settingsSchema.value.groups || []) {
    for (const key of group.keys || []) {
      const inherited = !(key in (overrides || {}));
      compSettingsInherited[key] = inherited;
      if (inherited) {
        compSettings[key] = cloneSettingGlobal(key);
      } else {
        const raw = overrides[key];
        if (key === 'BLOCKED_TYPES') {
          compSettings[key] = Array.isArray(raw) ? [...raw] : [];
        } else if (typeof settingsSchema.value.globals?.[key] === 'boolean') {
          compSettings[key] = !!raw;
        } else {
          compSettings[key] = raw;
        }
      }
    }
  }
}

function onCompSettingInheritChange(key) {
  if (compSettingsInherited[key]) {
    compSettings[key] = cloneSettingGlobal(key);
  }
}

function toggleCompSettingSet(key, type) {
  if (!Array.isArray(compSettings[key])) compSettings[key] = [];
  const idx = compSettings[key].indexOf(type);
  if (idx === -1) compSettings[key].push(type);
  else compSettings[key].splice(idx, 1);
}

function buildCompSettingsPayload() {
  const settings = {};
  if (!settingsSchema.value) return settings;
  for (const group of settingsSchema.value.groups || []) {
    for (const key of group.keys || []) {
      if (compSettingsInherited[key]) continue;
      const val = compSettings[key];
      if (key === 'BLOCKED_TYPES') {
        settings[key] = Array.isArray(val) ? [...val].sort() : [];
      } else {
        settings[key] = val;
      }
    }
  }
  return settings;
}

async function loadSettingsSchema() {
  try {
    settingsSchema.value = await api('/api/settings-schema');
  } catch { /* ignore */ }
}

async function loadEffectiveSettingsDetail() {
  if (!site.value || !component.value) {
    effectiveSettingsDetail.value = null;
    return;
  }
  try {
    effectiveSettingsDetail.value = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/effective-settings`
    );
  } catch {
    effectiveSettingsDetail.value = null;
  }
}

function submissionConfigComplete(sub) {
  if (!sub || typeof sub !== 'object') return false;
  const transport = (sub.transport || 'ui').toLowerCase();
  if (transport === 'api' || transport === 'api_multipart') {
    return !!(sub.api_url || sub.start_url);
  }
  if (transport === 'api_document') {
    return !!(sub.upload_url && sub.api_url);
  }
  const hasFile = (sub.inputs || []).some(i => i.type === 'file' || i.path_from === 'payload');
  if (hasFile) {
    return !!(sub.start_url && sub.submit_selector && sub.inputs?.length);
  }
  return !!(sub.start_url && sub.submit_selector && (sub.inputs?.length || sub.input_selector));
}

function applySubmissionToCompCfg(sub) {
  const s = sub || {};
  const t = (s.transport || 'ui').toLowerCase();
  compCfg.submission.transport = ['api', 'api_document', 'api_multipart'].includes(t) ? t : 'ui';
  compCfg.submission.start_url = s.start_url || '';
  compCfg.submission.submit_selector = s.submit_selector || '';
  compCfg.submission.response_selector = s.response_selector || '';
  compCfg.submission.response_within_selector = s.response_within_selector || '';
  compCfg.submission.response_text_within_selector = s.response_text_within_selector || '';
  compCfg.submission.response_capture_mode = s.response_capture_mode || 'last';
  compCfg.submission.response_list_selector = s.response_list_selector || '';
  compCfg.submission.response_role_selector = s.response_role_selector || '';
  compCfg.submission.submit_via = s.submit_via || 'click';
  compCfg.submission.response_wait_ms = s.response_wait_ms ?? 5000;
  compCfg.submission.inputs = (s.inputs || []).map(inp => ({ ...inp }));
  compCfg.submission.api_url = s.api_url || '';
  compCfg.submission.api_method = s.api_method || 'POST';
  compCfg.submission.api_response_path = s.api_response_path || 'response';
  compCfg.submission.api_model = s.api_model || '';
  compCfg.submission.api_body_json = JSON.stringify(s.api_body || { prompt: '{{prompt}}' }, null, 2);
  compCfg.submission.api_headers_json = JSON.stringify(s.api_headers || {}, null, 2);
  compCfg.submission.api_context_mode = s.api_context_mode || '';
  compCfg.submission.api_messages_prefix_json = JSON.stringify(s.api_messages_prefix || [], null, 2);
  compCfg.submission.upload_url = s.upload_url || '';
  compCfg.submission.upload_file_field = s.upload_file_field || 'file';
  compCfg.submission.upload_response_path = s.upload_response_path || 'document_id';
  compCfg.submission.multipart_prompt_field = s.multipart_prompt_field || 'prompt';
  compCfg.submission.multipart_file_field = s.multipart_file_field || 'file';
  if (['api', 'api_document', 'api_multipart'].includes(compCfg.submission.transport)) {
    syncApiDiscoverFromCompCfg();
  }
  // Sync Connection type from this component's saved transport (not global localStorage).
  if (typeof ctx.syncDiscoverTransportFromSubmission === 'function') {
    ctx.syncDiscoverTransportFromSubmission(compCfg.submission.transport);
  } else if (ctx.discoverTransport) {
    const t = (compCfg.submission.transport || 'ui').toLowerCase();
    ctx.discoverTransport.value = ['api', 'api_document', 'api_multipart'].includes(t)
      ? 'api'
      : 'browser';
  }
}

function syncApiDiscoverFromCompCfg() {
  ctx.apiDiscover.transport = compCfg.submission.transport || 'api';
  ctx.apiDiscover.url = compCfg.submission.api_url;
  ctx.apiDiscover.uploadUrl = compCfg.submission.upload_url;
  ctx.apiDiscover.method = compCfg.submission.api_method;
  ctx.apiDiscover.responsePath = compCfg.submission.api_response_path;
  ctx.apiDiscover.model = compCfg.submission.api_model || '';
  ctx.apiDiscover.bodyJson = compCfg.submission.api_body_json;
  ctx.apiDiscover.headersJson = compCfg.submission.api_headers_json;
}

function buildSubmissionPayload() {
  const transport = compCfg.submission.transport || 'ui';
  if (transport === 'api_document') {
    let api_body = { prompt: '{{prompt}}', document_id: '{{document_id}}', context_from: 'upload' };
    let api_headers = {};
    try { api_body = JSON.parse(compCfg.submission.api_body_json || '{}'); } catch { /* keep default */ }
    try { api_headers = JSON.parse(compCfg.submission.api_headers_json || '{}'); } catch { /* ignore */ }
    return {
      transport: 'api_document',
      upload_url: compCfg.submission.upload_url,
      upload_file_field: compCfg.submission.upload_file_field || 'file',
      upload_response_path: compCfg.submission.upload_response_path || 'document_id',
      api_url: compCfg.submission.api_url,
      api_method: compCfg.submission.api_method || 'POST',
      api_headers,
      api_body,
      api_response_path: compCfg.submission.api_response_path || 'response',
    };
  }
  if (transport === 'api_multipart') {
    return {
      transport: 'api_multipart',
      api_url: compCfg.submission.api_url,
      multipart_prompt_field: compCfg.submission.multipart_prompt_field || 'prompt',
      multipart_file_field: compCfg.submission.multipart_file_field || 'file',
      api_response_path: compCfg.submission.api_response_path || 'response',
    };
  }
  if (transport === 'api') {
    let api_body = { prompt: '{{prompt}}' };
    let api_headers = {};
    try { api_body = JSON.parse(compCfg.submission.api_body_json || '{}'); } catch { /* keep default */ }
    try { api_headers = JSON.parse(compCfg.submission.api_headers_json || '{}'); } catch { /* ignore */ }
    const out = {
      transport: 'api',
      api_url: compCfg.submission.api_url,
      api_method: compCfg.submission.api_method || 'POST',
      api_headers,
      api_body,
      api_response_path: compCfg.submission.api_response_path || 'response',
    };
    if (compCfg.submission.api_model) out.api_model = compCfg.submission.api_model;
    if (compCfg.submission.api_context_mode) {
      out.api_context_mode = compCfg.submission.api_context_mode;
    }
    try {
      const prefix = JSON.parse(compCfg.submission.api_messages_prefix_json || '[]');
      if (Array.isArray(prefix) && prefix.length) out.api_messages_prefix = prefix;
    } catch { /* ignore */ }
    return out;
  }
  const out = {
    transport: 'ui',
    start_url: compCfg.submission.start_url,
    inputs: compCfg.submission.inputs.map(i => ({ ...i })),
    submit_selector: compCfg.submission.submit_selector,
    response_selector: compCfg.submission.response_selector,
    response_within_selector: compCfg.submission.response_within_selector || '',
    response_text_within_selector: compCfg.submission.response_text_within_selector || '',
    submit_via: compCfg.submission.submit_via,
    response_wait_ms: Number(compCfg.submission.response_wait_ms),
  };
  const capMode = (compCfg.submission.response_capture_mode || 'last').trim();
  if (capMode && capMode !== 'last') out.response_capture_mode = capMode;
  if (compCfg.submission.response_list_selector) {
    out.response_list_selector = compCfg.submission.response_list_selector;
  }
  if (compCfg.submission.response_role_selector) {
    out.response_role_selector = compCfg.submission.response_role_selector;
  }
  return out;
}

async function loadCompCfg() {
  if (!site.value || !component.value) return;
  compCfgError.value = '';
  try {
    await loadSettingsSchema();
    await loadEffectiveSettingsDetail();
    const data = await api(`/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`);
    compCfg.login_url = data.login_url || '';
    applySubmissionToCompCfg(data.submission);
    compCfgEmpty.value = !submissionConfigComplete(data.submission);
    initCompSettingsFromConfig(data.settings || {});
  } catch (e) { compCfgError.value = String(e); }
}

async function saveCompCfg() {
  compCfgError.value = '';
  compCfgSaved.value = false;
  try {
    const existing = await api(`/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`);
    const payload = {
      ...existing,
      login_url: compCfg.login_url,
      submission: buildSubmissionPayload(),
    };
    // Preserve non-schema settings (e.g. intel_credentials_and_paths from Intel tab)
    // so schema-only rebuild does not wipe them.
    const schemaKeys = new Set();
    for (const group of settingsSchema.value?.groups || []) {
      for (const key of group.keys || []) schemaKeys.add(key);
    }
    const existingSettings =
      existing.settings && typeof existing.settings === 'object' ? existing.settings : {};
    const preserved = {};
    for (const [k, v] of Object.entries(existingSettings)) {
      if (!schemaKeys.has(k)) preserved[k] = v;
    }
    const settings = { ...preserved, ...buildCompSettingsPayload() };
    if (Object.keys(settings).length) payload.settings = settings;
    else delete payload.settings;
    await api(`/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: payload }),
    });
    compCfgSaved.value = true;
    setTimeout(() => { compCfgSaved.value = false; }, 3000);
    await ctx.loadContext();
  } catch (e) { compCfgError.value = String(e); }
}

function addInput() {
  compCfg.submission.inputs.push({ selector: '', type: 'text' });
}
function removeInput(i) {
  compCfg.submission.inputs.splice(i, 1);
}

const cfg = reactive({});
const cfgSaved = ref(false);
const cfgError = ref('');
const defaultsCfg = reactive({});
const defaultsCfgSaved = ref(false);
const defaultsCfgError = ref('');
const factoryResetting = ref(false);
const factoryResetMsg = ref('');
const llmConfigMeta = ref(null);
const llmProfiles = reactive({});
const llmConfigLoading = ref(false);
const llmConfigSaving = ref(false);
const llmConfigSaved = ref(false);
const llmConfigError = ref('');
const llmProfileEntries = computed(() => {
  const profiles = llmConfigMeta.value?.profiles || {};
  return Object.entries(profiles).map(([id, meta]) => ({ id, ...meta }));
});
const llmKeys = ref([
  { id: 'gemini', label: 'Gemini', env_var: 'GEMINI_API_KEY', has_key: false },
  { id: 'anthropic', label: 'Anthropic', env_var: 'ANTHROPIC_API_KEY', has_key: false },
  { id: 'openai', label: 'OpenAI', env_var: 'OPENAI_API_KEY', has_key: false },
  { id: 'grok', label: 'Grok', env_var: 'GROK_API_KEY', has_key: false },
  { id: 'openrouter', label: 'OpenRouter', env_var: 'OPENROUTER_API_KEY', has_key: false },
]);
const llmKeysEdit = reactive({ gemini: '', anthropic: '', openai: '', grok: '', openrouter: '' });
const llmKeysLoading = ref(false);
const llmKeysSaving = ref(false);
const llmKeysMsg = ref('');
const llmKeysError = ref('');
const llmKeysEditDirty = computed(() =>
  Object.values(llmKeysEdit).some(v => String(v || '').trim())
);
const BLOCKED_OPTIONS = ['image', 'font', 'media', 'stylesheet'];
const COUNTRIES = ['US', 'UK', 'DE', 'FR', 'JP', 'CA', 'AU', 'NL', 'ES', 'IT'];
const CHANNELS = ['chromium', 'chrome', 'chrome-beta', 'msedge'];
const FETCH_METHODS = ['auto', 'pool', 'cluster', 'human'];

async function loadConfig() {
  try {
    await loadSettingsSchema();
    const data = await api('/api/config');
    Object.assign(cfg, data);
    // Ensure BLOCKED_TYPES is always an array for checkbox binding
    if (!Array.isArray(cfg.BLOCKED_TYPES)) cfg.BLOCKED_TYPES = [];
  } catch (e) {
    cfgError.value = String(e);
  }
}

function initDefaultsCfgFromSchema() {
  if (!settingsSchema.value) return;
  for (const group of settingsSchema.value.groups || []) {
    for (const key of group.keys || []) {
      const val = settingsSchema.value.defaults?.[key];
      if (key === 'BLOCKED_TYPES') {
        defaultsCfg[key] = Array.isArray(val) ? [...val] : [];
      } else if (typeof val === 'boolean') {
        defaultsCfg[key] = val;
      } else if (val === null || val === undefined) {
        defaultsCfg[key] = settingsSchema.value.globals?.[key] ?? '';
      } else {
        defaultsCfg[key] = val;
      }
    }
  }
}

async function loadDefaultsConfig() {
  defaultsCfgError.value = '';
  try {
    await loadSettingsSchema();
    initDefaultsCfgFromSchema();
  } catch (e) {
    defaultsCfgError.value = String(e);
  }
}

async function saveDefaultsConfig() {
  defaultsCfgError.value = '';
  defaultsCfgSaved.value = false;
  factoryResetMsg.value = '';
  try {
    await api('/api/defaults-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ changes: { ...defaultsCfg } }),
    });
    defaultsCfgSaved.value = true;
    setTimeout(() => { defaultsCfgSaved.value = false; }, 3000);
    await loadSettingsSchema();
    initDefaultsCfgFromSchema();
  } catch (e) {
    defaultsCfgError.value = String(e);
  }
}

function applyLlmKeyStatus(providers) {
  const byId = Object.fromEntries((providers || []).map(p => [p.id, p]));
  llmKeys.value = llmKeys.value.map(row => {
    const next = byId[row.id];
    return next
      ? {
        id: next.id,
        label: next.label || row.label,
        env_var: next.env_var || row.env_var,
        has_key: !!next.has_key,
      }
      : row;
  });
}

async function loadLlmKeys() {
  llmKeysError.value = '';
  llmKeysLoading.value = true;
  try {
    const data = await api('/api/llm-keys');
    applyLlmKeyStatus(data.providers);
    llmKeysEdit.gemini = '';
    llmKeysEdit.anthropic = '';
    llmKeysEdit.openai = '';
    llmKeysEdit.grok = '';
    llmKeysEdit.openrouter = '';
  } catch (e) {
    llmKeysError.value = String(e);
  } finally {
    llmKeysLoading.value = false;
  }
}

async function saveLlmKeys() {
  if (!llmKeysEditDirty.value) return;
  llmKeysSaving.value = true;
  llmKeysMsg.value = '';
  llmKeysError.value = '';
  try {
    const result = await api('/api/llm-keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gemini: llmKeysEdit.gemini,
        anthropic: llmKeysEdit.anthropic,
        openai: llmKeysEdit.openai,
        grok: llmKeysEdit.grok,
        openrouter: llmKeysEdit.openrouter,
      }),
    });
    applyLlmKeyStatus(result.providers);
    llmKeysEdit.gemini = '';
    llmKeysEdit.anthropic = '';
    llmKeysEdit.openai = '';
    llmKeysEdit.grok = '';
    llmKeysEdit.openrouter = '';
    llmKeysMsg.value = 'Saved to .env';
    setTimeout(() => { if (llmKeysMsg.value === 'Saved to .env') llmKeysMsg.value = ''; }, 3000);
  } catch (e) {
    llmKeysError.value = 'Save failed: ' + e.message;
  } finally {
    llmKeysSaving.value = false;
  }
}

async function clearLlmKey(providerId) {
  const row = llmKeys.value.find(k => k.id === providerId);
  if (!row) return;
  const key = `llm-key-${providerId}`;
  if (!isConfirmArmed(key)) {
    armConfirm(key);
    return;
  }
  clearConfirmArmed(key);
  llmKeysSaving.value = true;
  llmKeysMsg.value = '';
  llmKeysError.value = '';
  try {
    const result = await api(`/api/llm-keys?provider=${encodeURIComponent(providerId)}`, {
      method: 'DELETE',
    });
    applyLlmKeyStatus(result.providers);
    llmKeysEdit[providerId] = '';
    llmKeysMsg.value = `${row.label} key cleared`;
  } catch (e) {
    llmKeysError.value = 'Clear failed: ' + e.message;
  } finally {
    llmKeysSaving.value = false;
  }
}

async function clearAllLlmKeys() {
  if (!isConfirmArmed('llm-keys-all')) {
    armConfirm('llm-keys-all');
    return;
  }
  clearConfirmArmed('llm-keys-all');
  llmKeysSaving.value = true;
  llmKeysMsg.value = '';
  llmKeysError.value = '';
  try {
    const result = await api('/api/llm-keys', { method: 'DELETE' });
    applyLlmKeyStatus(result.providers);
    llmKeysEdit.gemini = '';
    llmKeysEdit.anthropic = '';
    llmKeysEdit.openai = '';
    llmKeysEdit.grok = '';
    llmKeysEdit.openrouter = '';
    llmKeysMsg.value = 'All provider keys cleared';
  } catch (e) {
    llmKeysError.value = 'Clear failed: ' + e.message;
  } finally {
    llmKeysSaving.value = false;
  }
}

async function loadLlmConfig() {
  llmConfigError.value = '';
  llmConfigSaved.value = false;
  llmConfigLoading.value = true;
  try {
    await loadLlmKeys();
    const data = await api('/api/llm-config');
    llmConfigMeta.value = data;
    for (const key of Object.keys(llmProfiles)) delete llmProfiles[key];
    for (const [name, prof] of Object.entries(data.profiles || {})) {
      llmProfiles[name] = {
        provider: prof.provider || 'gemini',
        model: prof.model || '',
      };
    }
  } catch (e) {
    llmConfigError.value = String(e);
    llmConfigMeta.value = null;
  } finally {
    llmConfigLoading.value = false;
  }
}

async function saveLlmConfig() {
  llmConfigError.value = '';
  llmConfigSaved.value = false;
  llmConfigSaving.value = true;
  try {
    await api('/api/llm-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profiles: { ...llmProfiles } }),
    });
    llmConfigSaved.value = true;
    setTimeout(() => { llmConfigSaved.value = false; }, 3000);
    await loadLlmConfig();
  } catch (e) {
    llmConfigError.value = String(e);
  } finally {
    llmConfigSaving.value = false;
  }
}

async function resetFactorySettings() {
  defaultsCfgError.value = '';
  defaultsCfgSaved.value = false;
  factoryResetMsg.value = '';
  factoryResetting.value = true;
  try {
    const result = await api('/api/settings/reset-factory', { method: 'POST' });
    const parts = [];
    if (result.sites_cleared?.length) {
      parts.push(`${result.sites_cleared.length} site(s)`);
    }
    if (result.components_cleared?.length) {
      parts.push(`${result.components_cleared.length} component(s)`);
    }
    const cleared = parts.length ? ` Cleared overrides from ${parts.join(' and ')}.` : '';
    factoryResetMsg.value = `Factory settings restored.${cleared}`;
    setTimeout(() => { factoryResetMsg.value = ''; }, 8000);
    await loadSettingsSchema();
    initDefaultsCfgFromSchema();
    await loadConfig();
    if (site.value && component.value) {
      await loadCompCfg();
    }
    if (tab.value === 'settings' && settingsTab.value === 'cache') {
      await loadCacheSettings();
      await loadCorpusStores();
    }
  } catch (e) {
    defaultsCfgError.value = String(e);
  } finally {
    factoryResetting.value = false;
  }
}

function confirmResetFactorySettings() {
  if (!isConfirmArmed('factory-reset')) {
    armConfirm('factory-reset');
    return;
  }
  clearConfirmArmed('factory-reset');
  resetFactorySettings();
}

function toggleDefaultsSettingSet(key, type) {
  if (!Array.isArray(defaultsCfg[key])) defaultsCfg[key] = [];
  const idx = defaultsCfg[key].indexOf(type);
  if (idx === -1) defaultsCfg[key].push(type);
  else defaultsCfg[key].splice(idx, 1);
}

async function saveConfig() {
  cfgError.value = '';
  cfgSaved.value = false;
  try {
    await api('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ changes: { ...cfg } }),
    });
    cfgSaved.value = true;
    setTimeout(() => { cfgSaved.value = false; }, 3000);
  } catch (e) {
    cfgError.value = String(e);
  }
}

function toggleBlocked(type) {
  const idx = cfg.BLOCKED_TYPES.indexOf(type);
  if (idx === -1) cfg.BLOCKED_TYPES.push(type);
  else cfg.BLOCKED_TYPES.splice(idx, 1);
}

// --- Startup modal ---
const showModal = ref(false);
const modalSite = ref('');
const modalComponent = ref('');
const modalComponents = ref([]);
const modalNewSite = ref('');
const modalNewComponent = ref('');
const modalRenameSite = ref('');
const modalRenameComponent = ref('');
const modalError = ref('');
const modalMsg = ref('');

async function onModalSiteChange() {
  modalComponent.value = '';
  modalComponents.value = [];
  modalNewSite.value = '';
  modalNewComponent.value = '';
  modalRenameSite.value = modalSite.value || '';
  modalRenameComponent.value = '';
  if (modalSite.value) {
    modalComponents.value = await api(`/api/sites/${encodeURIComponent(modalSite.value)}/components`);
  }
}

function onModalComponentChange() {
  modalRenameComponent.value = modalComponent.value || '';
}

async function modalCreateSite() {
  modalError.value = '';
  modalMsg.value = '';
  const domain = modalNewSite.value.trim();
  if (!domain) { modalError.value = 'Enter a domain.'; return; }
  try {
    const created = await api('/api/sites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain }),
    });
    await ctx.loadSites();
    modalSite.value = created.domain;
    modalRenameSite.value = created.domain;
    modalNewSite.value = '';
    modalComponent.value = '';
    modalRenameComponent.value = '';
    modalComponents.value = await api(`/api/sites/${encodeURIComponent(created.domain)}/components`);
    modalMsg.value = 'Site created';
  } catch (e) {
    modalError.value = 'Create site failed: ' + e.message;
  }
}

async function modalRenameSiteAction() {
  modalError.value = '';
  modalMsg.value = '';
  const current = modalSite.value;
  const next = modalRenameSite.value.trim();
  if (!current || !next || current === next) return;
  try {
    const renamed = await api(`/api/sites/${encodeURIComponent(current)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain: next }),
    });
    if (site.value === current) site.value = renamed.domain;
    await ctx.loadSites();
    modalSite.value = renamed.domain;
    modalRenameSite.value = renamed.domain;
    modalComponents.value = await api(`/api/sites/${encodeURIComponent(renamed.domain)}/components`);
    components.value = site.value === renamed.domain ? [...modalComponents.value] : components.value;
    ctx.persistContextSelection();
    modalMsg.value = 'Site renamed';
  } catch (e) {
    modalError.value = 'Rename site failed: ' + e.message;
  }
}

async function modalDeleteSite() {
  modalError.value = '';
  modalMsg.value = '';
  if (!modalSite.value) return;
  if (!isConfirmArmed('modal-del-site')) {
    armConfirm('modal-del-site');
    return;
  }
  clearConfirmArmed('modal-del-site');
  const deleting = modalSite.value;
  try {
    await api(`/api/sites/${encodeURIComponent(deleting)}`, { method: 'DELETE' });
    if (site.value === deleting) {
      site.value = '';
      component.value = '';
      components.value = [];
      ctx.persistContextSelection();
    }
    await ctx.loadSites();
    modalSite.value = '';
    modalRenameSite.value = '';
    modalComponent.value = '';
    modalRenameComponent.value = '';
    modalComponents.value = [];
    modalMsg.value = 'Site deleted';
  } catch (e) {
    modalError.value = 'Delete site failed: ' + e.message;
  }
}

async function modalCreateComponent() {
  modalError.value = '';
  modalMsg.value = '';
  if (!modalSite.value) { modalError.value = 'Select a site first.'; return; }
  const name = modalNewComponent.value.trim();
  if (!name) { modalError.value = 'Enter a component name.'; return; }
  try {
    const created = await api(`/api/sites/${encodeURIComponent(modalSite.value)}/components`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    modalComponents.value = await api(`/api/sites/${encodeURIComponent(modalSite.value)}/components`);
    if (site.value === modalSite.value) components.value = [...modalComponents.value];
    modalComponent.value = created.name;
    modalRenameComponent.value = created.name;
    modalNewComponent.value = '';
    modalMsg.value = 'Component created';
  } catch (e) {
    modalError.value = 'Create component failed: ' + e.message;
  }
}

async function modalRenameComponentAction() {
  modalError.value = '';
  modalMsg.value = '';
  const current = modalComponent.value;
  const next = modalRenameComponent.value.trim();
  if (!modalSite.value || !current || !next || current === next) return;
  try {
    const renamed = await api(`/api/sites/${encodeURIComponent(modalSite.value)}/components/${encodeURIComponent(current)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: next }),
    });
    if (site.value === modalSite.value && component.value === current) component.value = renamed.name;
    modalComponents.value = await api(`/api/sites/${encodeURIComponent(modalSite.value)}/components`);
    if (site.value === modalSite.value) components.value = [...modalComponents.value];
    modalComponent.value = renamed.name;
    modalRenameComponent.value = renamed.name;
    ctx.persistContextSelection();
    modalMsg.value = 'Component renamed';
  } catch (e) {
    modalError.value = 'Rename component failed: ' + e.message;
  }
}

async function modalDeleteComponent() {
  modalError.value = '';
  modalMsg.value = '';
  if (!modalSite.value || !modalComponent.value) return;
  if (!isConfirmArmed('modal-del-comp')) {
    armConfirm('modal-del-comp');
    return;
  }
  clearConfirmArmed('modal-del-comp');
  const deleting = modalComponent.value;
  try {
    await api(`/api/sites/${encodeURIComponent(modalSite.value)}/components/${encodeURIComponent(deleting)}`, { method: 'DELETE' });
    if (site.value === modalSite.value && component.value === deleting) {
      component.value = '';
      ctx.persistContextSelection();
    }
    modalComponents.value = await api(`/api/sites/${encodeURIComponent(modalSite.value)}/components`);
    if (site.value === modalSite.value) components.value = [...modalComponents.value];
    modalComponent.value = '';
    modalRenameComponent.value = '';
    modalMsg.value = 'Component deleted';
  } catch (e) {
    modalError.value = 'Delete component failed: ' + e.message;
  }
}

async function confirmModal() {
  modalError.value = '';
  let s = modalSite.value, c = modalComponent.value;
  if (!s) { modalError.value = 'Select or create a site.'; return; }
  if (!c) { modalError.value = 'Select or create a component.'; return; }
  site.value = s;
  components.value = await api(`/api/sites/${encodeURIComponent(s)}/components`);
  component.value = c;
  ctx.persistContextSelection();
  await ctx.loadDiscoverContext();
  await ctx.loadContext();
  showModal.value = false;
  await ctx.checkSetupAndNavigate();
}

const settingsPrecedence = computed(() => {
  const layers = settingsSchema.value?.precedence || [];
  return layers.map((layer, i) => ({
    ...layer,
    rank: i + 1,
    pathDisplay: layer.path
      .replace('<site>', site.value || '<site>')
      .replace('<component>', component.value || '<component>'),
  }));
});

const runResults = ref([]);
const runResultsLoading = ref(false);
const expandedRunRows = ref({});
const runResultsCopiedKey = ref('');
let runResultsCopiedTimer = null;
const selectedRunLogPath = ref('');
const _savedRunResultsLayout = localStorage.getItem('genbounty_run_results_layout');
const runResultsLayout = ref(
  _savedRunResultsLayout === 'maximized' || _savedRunResultsLayout === 'minimized'
    ? _savedRunResultsLayout
    : 'normal'
);

function persistRunResultsLayout() {
  localStorage.setItem('genbounty_run_results_layout', runResultsLayout.value);
}

function toggleRunResultsMinimize() {
  runResultsLayout.value = runResultsLayout.value === 'minimized' ? 'normal' : 'minimized';
  persistRunResultsLayout();
}

function toggleRunResultsMaximize() {
  runResultsLayout.value = runResultsLayout.value === 'maximized' ? 'normal' : 'maximized';
  persistRunResultsLayout();
}

const runResultsMaximizedActive = computed(
  () => runResultsLayout.value === 'maximized' && runResults.value.length > 0
);

const runResultsHasMultiTurn = computed(
  () => runResults.value.some(r => r.isMultiTurn)
);

async function loadLogs() {
  if (!site.value || !component.value) return;
  const s = encodeURIComponent(site.value), c = encodeURIComponent(component.value);
  const l = await api(`/api/sites/${s}/${c}/logs`);
  logs.runs = l.runs;
  logs.attacks = l.attacks || [];
  logs.reports = l.reports;
}

function runOutcomeLabel(outcome) {
  const labels = {
    client_rejected: 'Client rejected',
    timeout: 'No response',
    submit_failed: 'Submit failed',
    skipped: 'Skipped',
    executed: 'Executed',
  };
  return labels[outcome] || '';
}

function parseRunLogEntries(data) {
  const mode = data.mode || '';
  if (mode === 'multi' || mode === 'adaptive') {
    return (data.batches || []).flatMap((b, bi) => {
      const turns = b.turns || [];
      const turnTotal = turns.length || Number(b.turn_count) || 0;
      const batchNum = (b.batch_index ?? bi) + 1;
      const batchShort = `Batch ${batchNum}`;
      const caseLabel = b.id || batchShort;
      const batchLabel = b.id ? `${batchShort} · ${b.id}` : batchShort;
      return turns.map((t, ti) => {
        const turnNum = ti + 1;
        const isMultiTurn = turnTotal > 1;
        const turnFraction = `${turnNum}/${turnTotal || turnNum}`;
        const generated = t.generated ? ' · adaptive' : '';
        return {
          label: mode === 'adaptive'
            ? `${caseLabel} · ${turnFraction}${generated}`
            : isMultiTurn
              ? `${batchShort} · ${turnFraction}`
              : batchShort,
          turnFraction,
          batchLabel,
          batchShort,
          batchNum,
          turnNum,
          turnTotal: turnTotal || turnNum,
          batchFirst: ti === 0,
          batchLast: ti === turns.length - 1,
          isMultiTurn,
          mode,
          input: t.input,
          response: t.response,
          submissionOutcome: t.submission_outcome || '',
          rejectionSignals: t.rejection_signals || [],
        };
      });
    });
  }
  return (data.entries || []).map((e, i) => ({
    label: `#${i + 1}`,
    turnFraction: `${i + 1}`,
    isMultiTurn: false,
    input: e.input,
    response: e.response,
    submissionOutcome: e.submission_outcome || '',
    rejectionSignals: e.rejection_signals || [],
  }));
}

function runResultRowClasses(row) {
  const classes = {};
  if (row?.submissionOutcome === 'client_rejected') {
    classes['run-results-row--client-rejected'] = true;
  } else if (row?.submissionOutcome === 'skipped') {
    classes['run-results-row--skipped'] = true;
  } else if (row?.submissionOutcome === 'timeout' && !row?.response) {
    classes['run-results-row--timeout'] = true;
  }
  if (row?.isMultiTurn) {
    classes['run-results-batch-row'] = true;
    classes['run-results-batch-row--first'] = row.batchFirst;
    classes['run-results-batch-row--last'] = row.batchLast;
    classes[`run-results-batch-row--group-${(row.batchNum || 1) % 4}`] = true;
  }
  return Object.keys(classes).length ? classes : null;
}

function formatRunLogLabel(entry, index) {
  const when = entry.mtime
    ? new Date(entry.mtime * 1000).toLocaleString()
    : entry.name;
  const latest = index === 0 ? ' · latest' : '';
  return `${when} - ${entry.name}${latest}`;
}

function _runMetricsWindowId() {
  return normalizeFindingsMetricsWindow
    ? normalizeFindingsMetricsWindow(findingsMetricsWindow?.value)
    : (findingsMetricsWindow?.value || 'last_run');
}

function _runLogsInMetricsWindow(windowId) {
  const id = windowId || _runMetricsWindowId();
  const runs = logs.runs || [];
  if (id === 'last_run') return [];
  if (id === 'all') return runs.slice();
  const now = Date.now() / 1000;
  const win = (FINDINGS_METRICS_WINDOWS || []).find((w) => w.id === id);
  const secs = win && win.seconds != null ? win.seconds : 0;
  return runs.filter((r) => (r.mtime || 0) >= now - secs);
}

let runWindowRowsLoadGen = 0;

async function loadRunResultsForMetricsWindow(windowId) {
  const id = windowId || _runMetricsWindowId();
  const gen = ++runWindowRowsLoadGen;
  const hadRows = Array.isArray(runResults.value) && runResults.value.length > 0;
  if (!hadRows) runResultsLoading.value = true;
  try {
    await loadLogs();
    if (gen !== runWindowRowsLoadGen) return;
    const runs = _runLogsInMetricsWindow(id);
    if (!runs.length) {
      runResults.value = [];
      expandedRunRows.value = {};
      return;
    }
    const chunks = [];
    for (const log of runs) {
      if (gen !== runWindowRowsLoadGen) return;
      try {
        const data = await api(`/api/files?path=${encodeURIComponent(log.path)}`);
        chunks.push(parseRunLogEntries(data).map((row) => ({
          ...row,
          logPath: log.path,
          logName: log.name,
        })));
      } catch (e) {
        console.error(e);
        chunks.push([]);
      }
    }
    if (gen !== runWindowRowsLoadGen) return;
    const merged = [];
    for (const part of chunks) {
      for (const row of part || []) merged.push(row);
    }
    let n = 0;
    expandedRunRows.value = {};
    runResults.value = merged.map((r) => {
      if (r.isMultiTurn) return r;
      n += 1;
      return { ...r, label: `#${n}`, turnFraction: `${n}` };
    });
    if (runs[0]?.path) selectedRunLogPath.value = runs[0].path;
  } catch (e) {
    console.error(e);
    if (gen === runWindowRowsLoadGen && !hadRows) runResults.value = [];
  } finally {
    if (gen === runWindowRowsLoadGen) runResultsLoading.value = false;
  }
}

async function syncRunTableToMetricsWindow() {
  const windowId = _runMetricsWindowId();
  if (windowId === 'last_run') {
    await loadLatestRunLog();
    return;
  }
  await loadRunResultsForMetricsWindow(windowId);
}

async function loadRunLog(path) {
  if (!site.value || !component.value) return;
  const hadRows = Array.isArray(runResults.value) && runResults.value.length > 0;
  // Keep the table mounted while refreshing when prior rows exist.
  if (!hadRows) runResultsLoading.value = true;
  try {
    await loadLogs();
    if (!logs.runs.length) {
      selectedRunLogPath.value = '';
      runResults.value = [];
      return;
    }
    // Explicit '' (from loadLatestRunLog) always picks newest; omit/undefined
    // keeps the current dropdown selection when still present.
    const forceLatest = path === '';
    const preferred = forceLatest
      ? ''
      : (path !== undefined && path !== null && path !== ''
        ? path
        : (selectedRunLogPath.value || ''));
    const known = preferred && logs.runs.some(r => r.path === preferred);
    const targetPath = known ? preferred : logs.runs[0].path;
    selectedRunLogPath.value = targetPath;
    const data = await api(`/api/files?path=${encodeURIComponent(targetPath)}`);
    expandedRunRows.value = {};
    runResults.value = parseRunLogEntries(data);
  } catch (e) {
    console.error(e);
    // Preserve prior snapshot on transient fetch errors.
    if (!hadRows) runResults.value = [];
  } finally {
    runResultsLoading.value = false;
  }
}

function loadLatestRunLog() {
  selectedRunLogPath.value = '';
  return loadRunLog('');
}

function onSelectedRunLogChange() {
  // Window owns the table when not last_run; log picker only updates selection.
  if (_runMetricsWindowId() !== 'last_run') return;
  if (selectedRunLogPath.value) loadRunLog(selectedRunLogPath.value);
}

watch(
  () => findingsMetricsWindow?.value,
  () => {
    if (tab?.value === 'run') syncRunTableToMetricsWindow();
  },
);

function toggleRunRow(i) {
  expandedRunRows.value = { ...expandedRunRows.value, [i]: !expandedRunRows.value[i] };
}

function runResultCopyKey(rowIndex, kind) {
  return `${rowIndex}:${kind}`;
}

function runResultCellCopied(rowIndex, kind) {
  return runResultsCopiedKey.value === runResultCopyKey(rowIndex, kind);
}

async function copyRunResultText(text, rowIndex, kind) {
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
  runResultsCopiedKey.value = runResultCopyKey(rowIndex, kind);
  if (runResultsCopiedTimer) clearTimeout(runResultsCopiedTimer);
  runResultsCopiedTimer = setTimeout(() => {
    if (runResultsCopiedKey.value === runResultCopyKey(rowIndex, kind)) {
      runResultsCopiedKey.value = '';
    }
  }, 1500);
}

const activeJobs = reactive({});
const sseConnections = {};
const runProgress = ref(null);
const runProgressClock = ref(Date.now());
let _runProgressClockTimer = null;

function ensureRunProgressClock() {
  if (_runProgressClockTimer != null) return;
  _runProgressClockTimer = setInterval(() => {
    runProgressClock.value = Date.now();
  }, 400);
}

function stopRunProgressClock() {
  if (_runProgressClockTimer == null) return;
  clearInterval(_runProgressClockTimer);
  _runProgressClockTimer = null;
}
const runPreviewBySlot = ref({});
const runPreviewConfig = ref({ mode: 'human', slotCount: 1 });
const runLivePanelOpen = ref(true);
const runSubmissionTransport = ref('ui');
const runPreviewModalSlot = ref(0);
const showRunPreviewModal = ref(false);
const showRunLoginModal = ref(false);
const showRunRateLimitModal = ref(false);
const showRunCloudflareModal = ref(false);
const pendingRunAfterCloudflare = ref(false);
const runCloudflareStopIssued = ref(false);
const runCloudflareModalShown = ref(false);
const runCloudflareTestsStopped = ref(false);
const runCloudflareSaving = ref(false);
const runCloudflareError = ref('');
const runSkipCurrentBusy = ref(false);
const runCloudflareSettings = reactive({
  FETCH_METHOD: 'pool',
  HEADLESS: false,
  cloudflare_headed: true,
});
const cloudflareModalNeedsSettings = computed(() => {
  return !!runBlockedInfo.value?.needs_headed_browser;
});
const cloudflareModalTimedOut = computed(() => {
  const p = runBlockedInfo.value;
  return !!(p?.stop_run && p?.kind === 'cloudflare' && !p?.needs_headed_browser);
});
const runRateLimitBackoffSec = ref(60);
const rateLimitCountdown = ref(0);
const rateLimitWaiting = ref(false);
const pendingRunAfterRateLimit = ref(false);
// Live timer handle must live on ctx (plain let is copied by value on Object.assign).
ctx.rateLimitTimer = null;
const runLoginUrl = ref('');
const runBlockedInfo = ref(null);
const pendingRunAfterLogin = ref(false);
const authSaving = ref(false);
const authSaveError = ref('');
const showEnhanceTheoryModal = ref(false);
const enhanceTheoryText = ref('');
const enhanceTheoryRejectReason = ref('');
const enhanceTheoryJobId = ref('');
const enhanceTheoryRound = ref(0);
const enhanceTheorySubmitting = ref(false);
const enhanceTheoryError = ref('');

function openEnhanceTheoryReview(p) {
  enhanceTheoryText.value = String(p.theory || '').trim();
  enhanceTheoryJobId.value = String(p.job_id || activeJobs.run_tests || '').trim();
  enhanceTheoryRound.value = Number(p.round) || 0;
  enhanceTheoryRejectReason.value = '';
  enhanceTheoryError.value = '';
  showEnhanceTheoryModal.value = true;
}

function closeEnhanceTheoryModal() {
  showEnhanceTheoryModal.value = false;
  enhanceTheorySubmitting.value = false;
  enhanceTheoryError.value = '';
}

async function acceptEnhanceTheory() {
  const jid = enhanceTheoryJobId.value || activeJobs.run_tests;
  if (!jid) return;
  enhanceTheorySubmitting.value = true;
  enhanceTheoryError.value = '';
  try {
    await api(`/api/jobs/${encodeURIComponent(jid)}/theory/accept`, { method: 'POST' });
    closeEnhanceTheoryModal();
  } catch (e) {
    enhanceTheoryError.value = String(e.message || e);
  } finally {
    enhanceTheorySubmitting.value = false;
  }
}

async function rejectEnhanceTheory() {
  const jid = enhanceTheoryJobId.value || activeJobs.run_tests;
  const reason = enhanceTheoryRejectReason.value.trim();
  if (!jid || !reason) return;
  enhanceTheorySubmitting.value = true;
  enhanceTheoryError.value = '';
  try {
    await api(`/api/jobs/${encodeURIComponent(jid)}/theory/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    });
    enhanceTheoryRejectReason.value = '';
  } catch (e) {
    enhanceTheoryError.value = String(e.message || e);
  } finally {
    enhanceTheorySubmitting.value = false;
  }
}

async function cancelEnhanceTheoryReview() {
  const jid = enhanceTheoryJobId.value || activeJobs.run_tests;
  closeEnhanceTheoryModal();
  if (jid) {
    try {
      await cancelJob(jid);
    } catch (e) {
      enhanceTheoryError.value = String(e.message || e);
    }
  }
}

function previewUrlFor(jobId, slot, opts = {}) {
  const params = new URLSearchParams();
  params.set('t', String(Date.now()));
  const seq = opts.sequence;
  if (seq != null && seq !== '') params.set('seq', String(seq));
  const s = opts.site || site.value;
  const c = opts.component || component.value;
  if (s) params.set('site', s);
  if (c) params.set('component', c);
  // Relative to the web origin (API base is empty in api.js).
  return `/api/jobs/${encodeURIComponent(jobId)}/preview/${slot}?${params.toString()}`;
}

const runPreviewImgRetries = ref({});

function runPreviewImgKey(slot) {
  const preview = previewForSlot(slot);
  if (!preview) return `slot-${slot}-idle`;
  return `${slot}:${preview.url}:${runPreviewImgRetries.value[slot] || 0}`;
}

function onRunPreviewImgError(slot) {
  const preview = previewForSlot(slot);
  if (!preview) return;
  const retries = runPreviewImgRetries.value[slot] || 0;
  if (retries >= 4) return;
  runPreviewImgRetries.value = {
    ...runPreviewImgRetries.value,
    [slot]: retries + 1,
  };
  const jobId = preview.jobId;
  if (!jobId) return;
  window.setTimeout(() => {
    updateRunPreview(jobId, slot, {
      sequence: preview.sequence,
      forceRefresh: true,
    });
  }, 400 * (retries + 1));
}

async function resolveRunPreviewConfig() {
  let method = 'human';
  let poolSize = 1;
  let contextCount = 1;
  let pagesPerContext = 1;
  try {
    if (site.value && component.value) {
      const eff = await api(
        `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/effective-settings`
      );
      const pick = (key) => {
        const row = eff?.[key];
        if (!row || typeof row !== 'object') return undefined;
        if (row.effective !== undefined && row.effective !== null && row.effective !== '') {
          return row.effective;
        }
        if (row.global !== undefined && row.global !== null && row.global !== '') {
          return row.global;
        }
        return row.defaults;
      };
      method = String(pick('FETCH_METHOD') || 'human').toLowerCase().trim();
      poolSize = Number(pick('POOL_SIZE')) || 1;
      contextCount = Number(pick('CONTEXT_COUNT')) || 1;
      pagesPerContext = Number(pick('PAGES_PER_CONTEXT')) || 1;
    } else {
      await loadConfig();
      method = String(cfg.FETCH_METHOD || 'human').toLowerCase().trim();
      poolSize = Number(cfg.POOL_SIZE) || 1;
      contextCount = Number(cfg.CONTEXT_COUNT) || 1;
      pagesPerContext = Number(cfg.PAGES_PER_CONTEXT) || 1;
    }
  } catch (err) {
    console.warn('[run preview] resolve config failed, falling back to /api/config:', err);
    try {
      await loadConfig();
      method = String(cfg.FETCH_METHOD || 'human').toLowerCase().trim();
      poolSize = Number(cfg.POOL_SIZE) || 1;
      contextCount = Number(cfg.CONTEXT_COUNT) || 1;
      pagesPerContext = Number(cfg.PAGES_PER_CONTEXT) || 1;
    } catch {
      method = 'human';
    }
  }

  if (method === 'human') {
    return { mode: 'human', slotCount: 1 };
  }
  if (method === 'pool') {
    return { mode: 'parallel', slotCount: Math.max(1, Math.min(32, poolSize)) };
  }
  if (method === 'cluster') {
    return { mode: 'parallel', slotCount: Math.max(1, contextCount * pagesPerContext) };
  }
  // auto (and unknown): show the larger of pool / cluster capacity
  const pool = Math.max(1, Math.min(32, poolSize));
  const cluster = Math.max(1, contextCount * pagesPerContext);
  return { mode: 'parallel', slotCount: Math.max(pool, cluster) };
}

async function initRunPreviewConfig() {
  runPreviewConfig.value = await resolveRunPreviewConfig();
}

/** Grow configured slot grid when live screenshots arrive from extra workers. */
function ensureRunPreviewSlots(slot) {
  const need = Math.max(1, (Number(slot) || 0) + 1);
  const cur = runPreviewConfig.value || { mode: 'human', slotCount: 1 };
  const slotCount = Math.max(1, Math.min(32, Math.max(cur.slotCount || 1, need)));
  const mode = slotCount > 1 ? 'parallel' : cur.mode;
  if (mode !== cur.mode || slotCount !== cur.slotCount) {
    runPreviewConfig.value = { mode, slotCount };
  }
}

function previewForSlot(slot) {
  return runPreviewBySlot.value[slot] || null;
}

const runPreviewSlotIndices = computed(() => {
  const configured = runPreviewConfig.value.slotCount || 1;
  const keys = Object.keys(runPreviewBySlot.value || {})
    .map((k) => Number(k))
    .filter((n) => Number.isFinite(n) && n >= 0);
  const fromLive = keys.length ? Math.max(...keys) + 1 : 0;
  const n = Math.max(1, Math.min(32, Math.max(configured, fromLive)));
  return Array.from({ length: n }, (_, i) => i);
});

const hasRunLivePreview = computed(() => Object.keys(runPreviewBySlot.value).length > 0);

function isApiSubmissionTransport(transport) {
  const t = (transport || 'ui').toLowerCase();
  return t === 'api' || t === 'api_document' || t === 'api_multipart';
}

const runUsesBrowserTransport = computed(() => !isApiSubmissionTransport(runSubmissionTransport.value));

const runLivePanelVisible = computed(() => {
  if (!runUsesBrowserTransport.value) return false;
  if (runJobActive.value) return true;
  return hasRunLivePreview.value;
});

function jobIsActive(status) {
  return status === 'running' || status === 'pending' || status === 'awaiting_theory';
}

function jobById(id) {
  if (!id) return null;
  const list = ctx.jobs?.value;
  if (!Array.isArray(list)) return null;
  return list.find(x => x.id === id) || null;
}

function tabJobTypes(tabId, settingsTabId) {
  if (tabId === 'generate') return ['generate'];
  if (tabId === 'playbooks') return [];
  if (tabId === 'run') return ['prompt_attributes', 'run_tests', 'sample_request'];
  if (tabId === 'war-room') return ['enhance_loop', 'security_assess', 'run_tests'];
  if (tabId === 'recon') return ['recon', 'recon_from_report'];
  if (tabId === 'intel') return ['credentials_from_reports'];
  if (tabId === 'risk') return ['security_assess'];
  if (tabId === 'export') return ['export'];
  if (tabId === 'discover') return ['discover', 'manual_discover', 'api_discover', 'login'];
  if (tabId === 'settings' && settingsTabId === 'cache') return ['clear_cache', 'nuke'];
  if (tabId === 'settings') return ['login'];
  return [];
}

function findTabJob() {
  let fallback = null;
  for (const type of tabJobTypes(tab.value, settingsTab.value)) {
    const j = jobById(activeJobs[type]);
    if (!j) continue;
    if (jobIsActive(j.status)) return j;
    if (!fallback) fallback = j;
  }
  return fallback;
}

const runJob = computed(() => jobById(activeJobs.run_tests));

const runJobActive = computed(() => {
  const j = runJob.value;
  return !!(j && jobIsActive(j.status));
});

const activeJobsCount = computed(() => {
  const list = ctx.jobs?.value;
  if (!Array.isArray(list)) return 0;
  return list.filter(j => jobIsActive(j.status)).length;
});

    const api_out = {
      cache,
      cacheSettingsSaving,
      cacheSettingsMsg,
      pipelineSettingsMeta,
      pipelineSettings,
      pipelineBounds,
      pipelineSettingsLoading,
      pipelineSettingsSaving,
      pipelineSettingsMsg,
      pipelineSettingsError,
      applyPipelineSettingsPayload,
      loadPipelineSettings,
      savePipelineSettings,
      resetPipelineSettingsDefaults,
      loadCacheSettings,
      saveCacheSettings,
      corpusStores,
      corpusStoreStats,
      corpusStoresBusy,
      corpusStoresMsg,
      corpusStoresAnySelected,
      corpusStoreLabel,
      applyCorpusStoreStats,
      loadCorpusStores,
      clearCorpusStoresSelected,
      theoryHistory,
      theoryHistoryLoading,
      theoryHistoryBusy,
      theoryHistoryMsg,
      theoryHistoryFilterPlaybook,
      theoryHistoryFilterStrategy,
      loadTheoryHistory,
      clearTheoryHistoryAll,
      clearTheoryHistoryFiltered,
      deleteTheoryHistoryEntry,
      PROMPT_TEMPLATE_HINT,
      PROMPT_MODEL_HINT,
      PROMPT_BODY_PLACEHOLDER,
      AUTH_HEADER_OPTIONS,
      INPUT_TYPES,
      compCfg,
      settingsSchema,
      effectiveSettingsDetail,
      compSettings,
      compSettingsInherited,
      compCfgSaved,
      compCfgError,
      compCfgEmpty,
      settingMeta,
      settingLabel,
      formatSettingValue,
      formatSettingGlobal,
      resolveSettingWithoutComponent,
      compSettingInheritHint,
      settingsValuesEqual,
      browserSettingDiffers,
      browserSettingDiffersFromDefaults,
      cloneSettingGlobal,
      initCompSettingsFromConfig,
      onCompSettingInheritChange,
      toggleCompSettingSet,
      buildCompSettingsPayload,
      loadSettingsSchema,
      loadEffectiveSettingsDetail,
      submissionConfigComplete,
      applySubmissionToCompCfg,
      syncApiDiscoverFromCompCfg,
      buildSubmissionPayload,
      loadCompCfg,
      saveCompCfg,
      addInput,
      removeInput,
      cfg,
      cfgSaved,
      cfgError,
      defaultsCfg,
      defaultsCfgSaved,
      defaultsCfgError,
      factoryResetting,
      factoryResetMsg,
      llmConfigMeta,
      llmProfiles,
      llmConfigLoading,
      llmConfigSaving,
      llmConfigSaved,
      llmConfigError,
      llmProfileEntries,
      llmKeys,
      llmKeysEdit,
      llmKeysLoading,
      llmKeysSaving,
      llmKeysMsg,
      llmKeysError,
      llmKeysEditDirty,
      BLOCKED_OPTIONS,
      COUNTRIES,
      CHANNELS,
      FETCH_METHODS,
      loadConfig,
      initDefaultsCfgFromSchema,
      loadDefaultsConfig,
      saveDefaultsConfig,
      applyLlmKeyStatus,
      loadLlmKeys,
      saveLlmKeys,
      clearLlmKey,
      clearAllLlmKeys,
      loadLlmConfig,
      saveLlmConfig,
      resetFactorySettings,
      confirmResetFactorySettings,
      toggleDefaultsSettingSet,
      saveConfig,
      toggleBlocked,
      showModal,
      modalSite,
      modalComponent,
      modalComponents,
      modalNewSite,
      modalNewComponent,
      modalRenameSite,
      modalRenameComponent,
      modalError,
      modalMsg,
      onModalSiteChange,
      onModalComponentChange,
      modalCreateSite,
      modalRenameSiteAction,
      modalDeleteSite,
      modalCreateComponent,
      modalRenameComponentAction,
      modalDeleteComponent,
      confirmModal,
      settingsPrecedence,
      runResults,
      runResultsLoading,
      expandedRunRows,
      runResultsCopiedKey,
      runResultsCopiedTimer,
      selectedRunLogPath,
      _savedRunResultsLayout,
      runResultsLayout,
      persistRunResultsLayout,
      toggleRunResultsMinimize,
      toggleRunResultsMaximize,
      runResultsMaximizedActive,
      runResultsHasMultiTurn,
      loadLogs,
      runOutcomeLabel,
      parseRunLogEntries,
      runResultRowClasses,
      formatRunLogLabel,
      loadRunLog,
      loadLatestRunLog,
      loadRunResultsForMetricsWindow,
      syncRunTableToMetricsWindow,
      onSelectedRunLogChange,
      toggleRunRow,
      runResultCopyKey,
      runResultCellCopied,
      copyRunResultText,
      activeJobs,
      sseConnections,
      runProgress,
      runProgressClock,
      ensureRunProgressClock,
      stopRunProgressClock,
      runPreviewBySlot,
      runPreviewConfig,
      runLivePanelOpen,
      runSubmissionTransport,
      runPreviewModalSlot,
      showRunPreviewModal,
      showRunLoginModal,
      showRunRateLimitModal,
      showRunCloudflareModal,
      pendingRunAfterCloudflare,
      runCloudflareStopIssued,
      runCloudflareModalShown,
      runCloudflareTestsStopped,
      runCloudflareSaving,
      runCloudflareError,
      runSkipCurrentBusy,
      runCloudflareSettings,
      cloudflareModalNeedsSettings,
      cloudflareModalTimedOut,
      runRateLimitBackoffSec,
      rateLimitCountdown,
      rateLimitWaiting,
      pendingRunAfterRateLimit,
      runLoginUrl,
      runBlockedInfo,
      pendingRunAfterLogin,
      authSaving,
      authSaveError,
      showEnhanceTheoryModal,
      enhanceTheoryText,
      enhanceTheoryRejectReason,
      enhanceTheoryJobId,
      enhanceTheoryRound,
      enhanceTheorySubmitting,
      enhanceTheoryError,
      openEnhanceTheoryReview,
      closeEnhanceTheoryModal,
      acceptEnhanceTheory,
      rejectEnhanceTheory,
      cancelEnhanceTheoryReview,
      previewUrlFor,
      runPreviewImgRetries,
      runPreviewImgKey,
      onRunPreviewImgError,
      resolveRunPreviewConfig,
      initRunPreviewConfig,
      ensureRunPreviewSlots,
      previewForSlot,
      runPreviewSlotIndices,
      hasRunLivePreview,
      isApiSubmissionTransport,
      runUsesBrowserTransport,
      runLivePanelVisible,
      jobIsActive,
      jobById,
      tabJobTypes,
      findTabJob,
      runJob,
      runJobActive,
      activeJobsCount
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
