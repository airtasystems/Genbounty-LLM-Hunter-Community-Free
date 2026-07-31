/**
 * Domain module: useTests
 */
(function (G) {
  'use strict';

  G.useTests = function useTests(ctx) {
    const {
      activePlaybookId,
      armConfirm,
      clearConfirmArmed,
      component,
      computed,
      isConfirmArmed,
      nextTick,
      onMounted,
      reactive,
      ref,
      site,
      tab,
      watch
    } = ctx;
    const api = G.api;

// --- Armory tab ---
const tmStrategy = ref('');
const tmCategoryL1 = ref('');
const tmPlaybook = ref('');
const tmStrategies = ref([]);
const tmPlaybooks = ref([]);
const tmFile = ref(null);       // loaded probe file { playbook, description, categories }
const tmDirty = ref(false);
const tmSaving = ref(false);
const tmDeleting = ref(false);
const tmSaveMsg = ref('');
const tmEditingId = ref(null);  // prompt id being inline-edited
const tmPayloadEditorReady = ref(false);
const tmAddingCategory = ref('');// category slug for new-prompt form
const tmNewPrompt = reactive({
  id: '', description: '', prompt: '', vector_type: 'text_direct',
  payload_generator: 'text', payload_args_json: '{}',
});
const tmPayloadGenMsg = ref('');
const tmPayloadGenBusy = ref(false);
const tmImportFile = ref(null);
const tmImportName = ref('');
const tmImporting = ref(false);
const tmImportMsg = ref('');
const showTmImportHelpModal = ref(false);
const _savedTmResultsLayout = localStorage.getItem('genbounty_tests_results_layout');
const tmResultsLayout = ref(
  _savedTmResultsLayout === 'maximized' || _savedTmResultsLayout === 'minimized'
    ? _savedTmResultsLayout
    : 'normal'
);

function persistTmResultsLayout() {
  localStorage.setItem('genbounty_tests_results_layout', tmResultsLayout.value);
}

function toggleTmResultsMinimize() {
  tmResultsLayout.value = tmResultsLayout.value === 'minimized' ? 'normal' : 'minimized';
  persistTmResultsLayout();
}

function toggleTmResultsMaximize() {
  tmResultsLayout.value = tmResultsLayout.value === 'maximized' ? 'normal' : 'maximized';
  persistTmResultsLayout();
}

const tmPromptCount = computed(() => {
  const cats = tmFile.value && Array.isArray(tmFile.value.categories) ? tmFile.value.categories : [];
  return cats.reduce((n, cat) => n + (Array.isArray(cat?.prompts) ? cat.prompts.length : 0), 0);
});

const tmResultsMaximizedActive = computed(
  () => tmResultsLayout.value === 'maximized' && !!tmFile.value
);

// Must stay aligned with playbooks.campaign.MULTI_TURN_STRATEGIES.
const TM_MULTI_TURN_STRATEGIES = new Set([
  'multi_shot', 'iterative', 'prompt_chaining', 'adaptive',
]);
const TM_FEW_SHOT_STRATEGIES = new Set(['few_shot']);
const TM_EXAMPLE_BEHAVIORS = ['comply', 'refuse'];
const targetCapabilities = reactive({
  multi_turn: true,
  file_upload: false,
  loaded: false,
});

function tmStrategyNorm() {
  return (tmStrategy.value || '').replace(/-/g, '_');
}

function strategyRequiresMultiTurn(slug) {
  return TM_MULTI_TURN_STRATEGIES.has(String(slug || '').replace(/-/g, '_'));
}

function tmIsMultiTurnStrategy() {
  return TM_MULTI_TURN_STRATEGIES.has(tmStrategyNorm());
}

function tmIsFewShotStrategy() {
  return TM_FEW_SHOT_STRATEGIES.has(tmStrategyNorm());
}

function tmIsMultimodalStrategy() {
  return tmStrategyNorm() === 'multimodal';
}

function tmPromptKind(p) {
  if (Array.isArray(p?.prompts) && p.prompts.length) return 'multi_turn';
  if (Array.isArray(p?.examples) && p.examples.length) return 'few_shot';
  if (p?.payload || (p?.vector_type && p.vector_type !== 'text_direct')) return 'multimodal';
  return 'text';
}

function tmPromptKindLabel(p) {
  const labels = {
    multi_turn: `${p.prompts?.length || 0}-turn`,
    few_shot: `few-shot (${p.examples?.length || 0})`,
    multimodal: p.vector_type || 'artifact',
    text: '',
  };
  return labels[tmPromptKind(p)] || '';
}

function tmPromptPreview(p) {
  const kind = tmPromptKind(p);
  const clip = (s, n = 220) => {
    const t = (s || '').trim();
    return t.length <= n ? t : t.slice(0, n) + '…';
  };
  if (kind === 'multi_turn') {
    const turns = p.prompts || [];
    if (turns.length === 1) return clip(turns[0]);
    return turns.map((t, i) => `Turn ${i + 1}: ${clip(t, 120)}`).join('\n');
  }
  if (kind === 'few_shot') {
    const ex = p.examples || [];
    const lines = ex.map((e, i) => `Ex ${i + 1}: ${clip(e.prompt, 80)}`);
    if (p.prompt) lines.push(`Final: ${clip(p.prompt, 120)}`);
    return lines.join('\n');
  }
  return clip(p.prompt);
}

function tmNormalizeSuite(data) {
  if (!data || !Array.isArray(data.categories)) return data;
  for (const cat of data.categories) {
    if (!cat.name && cat.category) cat.name = cat.category;
    if (!cat.name && cat.mandate) cat.name = cat.mandate;
  }
  return data;
}

function tmAddTurn(p) {
  if (!Array.isArray(p.prompts)) p.prompts = [];
  p.prompts.push('');
  tmMarkDirty();
}

function tmRemoveTurn(p, turnIdx) {
  if (!Array.isArray(p.prompts)) return;
  p.prompts.splice(turnIdx, 1);
  tmMarkDirty();
}

function tmAddExample(p) {
  if (!Array.isArray(p.examples)) p.examples = [];
  p.examples.push({ prompt: '', expected_behavior: 'comply' });
  tmMarkDirty();
}

function tmRemoveExample(p, exampleIdx) {
  if (!Array.isArray(p.examples)) return;
  p.examples.splice(exampleIdx, 1);
  tmMarkDirty();
}

// --- Payloads tab (PayloadEditor component) ---
const payloadFiles = ref([]);
const _savedPayloadsResultsLayout = localStorage.getItem('genbounty_payloads_results_layout');
const payloadsResultsLayout = ref(
  _savedPayloadsResultsLayout === 'maximized' || _savedPayloadsResultsLayout === 'minimized'
    ? _savedPayloadsResultsLayout
    : 'normal'
);

function persistPayloadsResultsLayout() {
  localStorage.setItem('genbounty_payloads_results_layout', payloadsResultsLayout.value);
}

function togglePayloadsResultsMinimize() {
  payloadsResultsLayout.value = payloadsResultsLayout.value === 'minimized' ? 'normal' : 'minimized';
  persistPayloadsResultsLayout();
}

function togglePayloadsResultsMaximize() {
  payloadsResultsLayout.value = payloadsResultsLayout.value === 'maximized' ? 'normal' : 'maximized';
  persistPayloadsResultsLayout();
}

const payloadsResultsMaximizedActive = computed(
  () => payloadsResultsLayout.value === 'maximized'
);

async function loadPayloadFiles() {
  try {
    const res = await api('/api/payloads/list');
    payloadFiles.value = res.files || [];
  } catch (_) {
    payloadFiles.value = [];
  }
}

function payloadDownloadUrl(relativePath) {
  return `/api/payloads/file/${encodeURIComponent(relativePath)}`;
}

function onPayloadGenerated() {
  loadPayloadFiles();
}

const TM_EMPTY_PAYLOAD_ARGS = Object.freeze({});

function tmPayloadEditorArgs(p) {
  return p?.payload?.args || TM_EMPTY_PAYLOAD_ARGS;
}

function tmPayloadEditorUpdateArgs(p, args) {
  if (!p.payload) p.payload = { generator: 'text', args: {} };
  try {
    if (JSON.stringify(p.payload.args || {}) === JSON.stringify(args || {})) return;
  } catch (_) { /* compare failed - apply update */ }
  p.payload.args = args;
  tmMarkDirty();
}

function tmPayloadEditorUpdateGenerator(p, generator) {
  if (!p.payload) p.payload = { generator: 'text', args: {} };
  if (p.payload.generator === generator) return;
  p.payload.generator = generator;
  tmMarkDirty();
}

watch(tmEditingId, (id) => {
  tmPayloadEditorReady.value = false;
  if (!id) return;
  requestAnimationFrame(() => {
    if (tmEditingId.value === id) tmPayloadEditorReady.value = true;
  });
});

async function tmLoadTestFiles({ restorePlaybook = true } = {}) {
  ctx._skipTmSelectionPersist = true;
  tmPlaybooks.value = [];
  tmCategoryL1.value = '';
  tmPlaybook.value = '';
  tmStrategies.value = [];
  tmStrategy.value = '';
  tmFile.value = null;
  tmDirty.value = false;
  try {
    if (!site.value || !component.value) return;
    const s = encodeURIComponent(site.value), c = encodeURIComponent(component.value);
    tmPlaybooks.value = await api(`/api/sites/${s}/${c}/test-files`);
    try {
      if (!ctx.pbCatalog.value.length) {
        ctx.pbCatalog.value = await api('/api/playbooks/manage');
      }
    } catch (_) {
      /* optional category metadata */
    }
    await ctx.applySavedTmTabSelections();
    ensureTmPlayInCategory();
    if (restorePlaybook) await ctx.restoreActivePlaybook();
  } finally {
    ctx._skipTmSelectionPersist = false;
  }
}

const tmCategoryOptions = computed(() => ctx.groupTestFilesByCategory(tmPlaybooks.value));

const tmPlayOptions = computed(() => {
  const group = tmCategoryOptions.value.find((g) => g.key === tmCategoryL1.value);
  return group?.playbooks || [];
});

function syncTmCategoryFromPlaybook() {
  if (!tmPlaybook.value || !tmCategoryOptions.value.length) return;
  const group = tmCategoryOptions.value.find((g) => (
    (g.playbooks || []).some((p) => p.slug === tmPlaybook.value)
  ));
  if (group) tmCategoryL1.value = group.key;
}

function ensureTmPlayInCategory() {
  if (activePlaybookId.value) {
    const slug = ctx.testFileSlugForPlaybook(tmPlaybooks.value, activePlaybookId.value);
    if (slug) {
      if (tmPlaybook.value !== slug || !tmStrategies.value.length) {
        tmPlaybook.value = slug;
        tmOnTestFileChange();
      } else {
        syncTmCategoryFromPlaybook();
      }
      return;
    }
    tmPlaybook.value = '';
    tmStrategies.value = [];
    tmStrategy.value = '';
    tmFile.value = null;
    if (!tmCategoryL1.value && tmCategoryOptions.value.length) {
      tmCategoryL1.value = tmCategoryOptions.value[0].key;
    }
    return;
  }
  if (!tmCategoryOptions.value.length) {
    tmCategoryL1.value = '';
    tmPlaybook.value = '';
    return;
  }
  if (!tmCategoryL1.value || !tmCategoryOptions.value.some((g) => g.key === tmCategoryL1.value)) {
    syncTmCategoryFromPlaybook();
    if (!tmCategoryL1.value) tmCategoryL1.value = tmCategoryOptions.value[0].key;
  }
  const plays = tmPlayOptions.value;
  if (!plays.length) {
    tmPlaybook.value = '';
    return;
  }
  if (!plays.some((p) => p.slug === tmPlaybook.value)) {
    tmPlaybook.value = plays[0].slug;
    tmOnTestFileChange();
  } else {
    syncTmCategoryFromPlaybook();
  }
}

function onTmCategoryL1Change() {
  ctx.setActiveCategory(tmCategoryL1.value, { source: 'tests' });
}

function onTmPlaybookChange() {
  ctx.setActivePlaybook(tmPlaybook.value, { source: 'tests' });
}

function tmSelectedTestFile() {
  if (!tmPlaybook.value) return null;
  return tmPlaybooks.value.find(f => f.slug === tmPlaybook.value) || null;
}

function tmOnTestFileChange() {
  syncTmCategoryFromPlaybook();
  tmStrategies.value = [];
  tmStrategy.value = '';
  tmFile.value = null;
  tmDirty.value = false;
  const file = tmSelectedTestFile();
  if (!file) return;
  tmStrategies.value = file.strategies || [];
  if (tmStrategies.value.length === 1) {
    tmStrategy.value = tmStrategies.value[0].slug;
    tmLoadFile();
  }
}

async function tmOnStrategyChange() {
  await tmLoadFile();
}

async function tmLoadFile() {
  tmFile.value = null;
  tmDirty.value = false;
  tmEditingId.value = null;
  tmAddingCategory.value = '';
  if (!tmPlaybook.value || !tmStrategy.value) return;
  const s = encodeURIComponent(site.value), c = encodeURIComponent(component.value);
  const fw = encodeURIComponent(tmPlaybook.value);
  const strat = encodeURIComponent(tmStrategy.value);
  // tmPlaybook.value holds the full path; extract stem from it
  const stem = tmPlaybook.value.split('/').pop().replace(/\.json$/, '');
  tmFile.value = tmNormalizeSuite(await api(`/api/sites/${s}/${c}/tests/${strat}/${encodeURIComponent(stem)}`));
}

function tmSnapshotPlain() {
  const data = JSON.parse(JSON.stringify(tmFile.value));
  for (const cat of data.categories || []) {
    if (cat.category && !cat.name) cat.name = cat.category;
    delete cat.category;
  }
  return data;
}

async function tmSave() {
  if (!tmFile.value) return;
  tmSaving.value = true;
  tmSaveMsg.value = '';
  try {
    const s = encodeURIComponent(site.value), c = encodeURIComponent(component.value);
    const strat = encodeURIComponent(tmStrategy.value);
    const stem = tmPlaybook.value.split('/').pop().replace(/\.json$/, '');
    await api(`/api/sites/${s}/${c}/tests/${strat}/${encodeURIComponent(stem)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: tmSnapshotPlain() }),
    });
    tmDirty.value = false;
    tmSaveMsg.value = 'Saved';
    setTimeout(() => { tmSaveMsg.value = ''; }, 2000);
  } catch (e) {
    tmSaveMsg.value = 'Save failed: ' + e.message;
  } finally {
    tmSaving.value = false;
  }
}

async function tmDeletePrompt(categoryIdx, promptIdx) {
  const m = tmFile.value.categories[categoryIdx];
  if (!m?.prompts?.length) return;
  if (promptIdx < 0 || promptIdx >= m.prompts.length) return;
  m.prompts = m.prompts.filter((_, i) => i !== promptIdx);
  tmDirty.value = true;
  await tmSave();
}

async function tmDeleteSuite() {
  if (!tmFile.value || !tmPlaybook.value || !tmStrategy.value || !site.value || !component.value) {
    return;
  }
  if (!isConfirmArmed('tm-delete-suite')) {
    armConfirm('tm-delete-suite');
    return;
  }
  clearConfirmArmed('tm-delete-suite');
  tmDeleting.value = true;
  tmSaveMsg.value = '';
  try {
    const s = encodeURIComponent(site.value);
    const c = encodeURIComponent(component.value);
    const strat = encodeURIComponent(tmStrategy.value);
    const stem = tmPlaybook.value.split('/').pop().replace(/\.json$/, '');
    await api(`/api/sites/${s}/${c}/tests/${strat}/${encodeURIComponent(stem)}`, {
      method: 'DELETE',
    });
    tmFile.value = null;
    tmDirty.value = false;
    tmEditingId.value = null;
    tmSaveMsg.value = 'Test deleted';
    setTimeout(() => { tmSaveMsg.value = ''; }, 2000);
    await tmLoadTestFiles({ restorePlaybook: true });
  } catch (e) {
    tmSaveMsg.value = 'Delete failed: ' + e.message;
  } finally {
    tmDeleting.value = false;
  }
}

function tmStartAdd(categorySlug) {
  tmAddingCategory.value = categorySlug;
  tmNewPrompt.id = '';
  tmNewPrompt.description = '';
  tmNewPrompt.prompt = '';
  tmNewPrompt.vector_type = 'text_direct';
  tmNewPrompt.payload_generator = 'text';
  tmNewPrompt.payload_args_json = '{}';
}

function tmNewPromptArgs() {
  try {
    return JSON.parse(tmNewPrompt.payload_args_json || '{}');
  } catch (_) {
    return {};
  }
}

function tmNewPromptSetArgs(args) {
  const next = JSON.stringify(args || {});
  if (tmNewPrompt.payload_args_json === next) return;
  tmNewPrompt.payload_args_json = next;
}

function tmNewPromptSetGenerator(gen) {
  if (tmNewPrompt.payload_generator === gen) return;
  tmNewPrompt.payload_generator = gen;
}

function tmBuildPayloadFromEditor(src) {
  if (!src.payload_generator || src.payload_generator === 'none') return undefined;
  let args = {};
  try {
    args = JSON.parse(src.payload_args_json || '{}');
  } catch (_) {
    args = {};
  }
  return { generator: src.payload_generator, args };
}

async function tmGeneratePayloadForPrompt(p) {
  const gen = p.payload?.generator || p.payload_generator;
  if (!gen || gen === 'none') return;
  tmPayloadGenBusy.value = true;
  tmPayloadGenMsg.value = '';
  let args = p.payload?.args;
  if (!args && p.payload_args_json) {
    try {
      args = JSON.parse(p.payload_args_json || '{}');
    } catch (e) {
      tmPayloadGenMsg.value = 'Invalid payload args JSON';
      tmPayloadGenBusy.value = false;
      return;
    }
  }
  args = args || {};
  try {
    const res = await api('/api/payloads/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ generator: gen, args }),
    });
    tmPayloadGenMsg.value = 'Generated: ' + (res.relative_path || res.path);
    if (res.relative_path && p.payload) {
      p.payload.path = res.relative_path;
      tmMarkDirty();
    }
  } catch (e) {
    tmPayloadGenMsg.value = 'Generate failed: ' + e.message;
  } finally {
    tmPayloadGenBusy.value = false;
  }
}

function tmConfirmAdd(categoryIdx) {
  const id = tmNewPrompt.id.trim();
  const description = tmNewPrompt.description.trim();
  const text = tmNewPrompt.prompt.trim();
  if (!id) return;

  const p = { id, description };
  if (tmIsMultiTurnStrategy()) {
    const turns = text.split(/\n---\n/).map(s => s.trim()).filter(Boolean);
    if (!turns.length) return;
    p.prompts = turns;
  } else if (tmIsFewShotStrategy()) {
    if (!text) return;
    p.examples = [];
    p.prompt = text;
  } else {
    if (!text) return;
    p.prompt = text;
    if (tmIsMultimodalStrategy()) {
      if (tmNewPrompt.vector_type && tmNewPrompt.vector_type !== 'text_direct') {
        p.vector_type = tmNewPrompt.vector_type;
      }
      const payload = tmBuildPayloadFromEditor(tmNewPrompt);
      if (payload) p.payload = payload;
    }
  }

  tmFile.value.categories[categoryIdx].prompts.push(p);
  tmDirty.value = true;
  tmAddingCategory.value = '';
}

function tmMarkDirty() { tmDirty.value = true; }

function openTmImportHelpModal() {
  showTmImportHelpModal.value = true;
}

function closeTmImportHelpModal() {
  showTmImportHelpModal.value = false;
}

function tmImportFileChanged(event) {
  const file = event.target.files?.[0] || null;
  tmImportFile.value = file;
  tmImportMsg.value = '';
  if (file && !tmImportName.value) {
    tmImportName.value = file.name.replace(/\.json$/i, '');
  }
}

function tmReadImportFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        resolve(JSON.parse(reader.result));
      } catch (e) {
        reject(new Error('Invalid JSON: ' + e.message));
      }
    };
    reader.onerror = () => reject(new Error('Could not read file'));
    reader.readAsText(file);
  });
}


async function tmImportZeroShot() {
  if (!site.value || !component.value || !tmImportFile.value) return;
  if (tmDirty.value && !isConfirmArmed('tm-import')) {
    armConfirm('tm-import');
    return;
  }
  clearConfirmArmed('tm-import');
  tmImporting.value = true;
  tmImportMsg.value = '';
  try {
    const data = await tmReadImportFile(tmImportFile.value);
    const s = encodeURIComponent(site.value), c = encodeURIComponent(component.value);
    const result = await api(`/api/sites/${s}/${c}/tests/import-zero-shot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: tmImportName.value || tmImportFile.value.name, data }),
    });
    await tmLoadTestFiles({ restorePlaybook: false });
    const stem = (result.path || result.playbook || '').split('/').pop().replace(/\.json$/i, '');
    await ctx.setActivePlaybook(stem || result.playbook, { source: 'tests' });
    if (result.strategy) tmStrategy.value = result.strategy;
    await tmLoadFile();
    tmImportMsg.value = `Imported ${result.playbook} into Zero-shot`;
  } catch (e) {
    tmImportMsg.value = 'Import failed: ' + e.message;
  } finally {
    tmImporting.value = false;
  }
}

    const api_out = {
      tmStrategy,
      tmCategoryL1,
      tmPlaybook,
      tmStrategies,
      tmPlaybooks,
      tmFile,
      tmDirty,
      tmSaving,
      tmDeleting,
      tmSaveMsg,
      tmEditingId,
      tmPayloadEditorReady,
      tmAddingCategory,
      tmNewPrompt,
      tmPayloadGenMsg,
      tmPayloadGenBusy,
      tmImportFile,
      tmImportName,
      tmImporting,
      tmImportMsg,
      showTmImportHelpModal,
      tmResultsLayout,
      tmPromptCount,
      tmResultsMaximizedActive,
      toggleTmResultsMinimize,
      toggleTmResultsMaximize,
      TM_MULTI_TURN_STRATEGIES,
      TM_FEW_SHOT_STRATEGIES,
      TM_EXAMPLE_BEHAVIORS,
      targetCapabilities,
      tmStrategyNorm,
      strategyRequiresMultiTurn,
      tmIsMultiTurnStrategy,
      tmIsFewShotStrategy,
      tmIsMultimodalStrategy,
      tmPromptKind,
      tmPromptKindLabel,
      tmPromptPreview,
      tmNormalizeSuite,
      tmAddTurn,
      tmRemoveTurn,
      tmAddExample,
      tmRemoveExample,
      payloadFiles,
      payloadsResultsLayout,
      payloadsResultsMaximizedActive,
      togglePayloadsResultsMinimize,
      togglePayloadsResultsMaximize,
      loadPayloadFiles,
      payloadDownloadUrl,
      onPayloadGenerated,
      TM_EMPTY_PAYLOAD_ARGS,
      tmPayloadEditorArgs,
      tmPayloadEditorUpdateArgs,
      tmPayloadEditorUpdateGenerator,
      tmLoadTestFiles,
      tmCategoryOptions,
      tmPlayOptions,
      syncTmCategoryFromPlaybook,
      ensureTmPlayInCategory,
      onTmCategoryL1Change,
      onTmPlaybookChange,
      tmSelectedTestFile,
      tmOnTestFileChange,
      tmOnStrategyChange,
      tmLoadFile,
      tmSnapshotPlain,
      tmSave,
      tmDeletePrompt,
      tmDeleteSuite,
      tmStartAdd,
      tmNewPromptArgs,
      tmNewPromptSetArgs,
      tmNewPromptSetGenerator,
      tmBuildPayloadFromEditor,
      tmGeneratePayloadForPrompt,
      tmConfirmAdd,
      tmMarkDirty,
      openTmImportHelpModal,
      closeTmImportHelpModal,
      tmImportFileChanged,
      tmReadImportFile,
      tmImportZeroShot
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
