/**
 * Domain module: useRun
 */
(function (G) {
  'use strict';

  G.useRun = function useRun(ctx) {
    const {
      activeCategoryL1,
      activePlaybookId,
      allPlaybooks,
      component,
      computed,
      genCategoryOptions,
      nextTick,
      onMounted,
      reactive,
      ref,
      readTabSelections,
      runCategoryOptions,
      runStrategies,
      runTestFiles,
      site,
      tab,
      watch,
      writeTabSelections,
      ACTIVE_PLAYBOOK_KEY,
      RUN_TAB_SELECTIONS_KEY,
      TM_TAB_SELECTIONS_KEY,
    } = ctx;
    const api = G.api;

const run = reactive({
  scope: 'playbook',
  strategy: '',
  playbook: '',
  category: '',
  assess: true,
  // Firing Range: after Fire, risk-assess into logs/manual/<timestamp>/
  manualAssess: (() => {
    try {
      return localStorage.getItem('genbounty_manual_assess_on_fire') === '1';
    } catch (_) {
      return false;
    }
  })(),
  autoRun: false,
  // Auto-run early-stop severities (default matches backend: high + critical).
  stopLevels: { medium: false, high: true, critical: true },
  // Auto-run round budget (1–8); Enhance and Run uses 1 when Auto-run is off.
  maxRounds: ctx.LOOP_MAX_ROUNDS_CAP,
  // Enhance / Auto-run / Pipeline hunt mode (default = Bug Bounty).
  huntMode: 'bug_bounty',
  customEnhance: false,
  customEnhanceText: '',
  customOverridesFreeze: false,
  samplePrompt: '',
});

const AUTO_RUN_STOP_LEVEL_KEYS = ['medium', 'high', 'critical'];
// Community: Open Hunt is Premium (shown as upsell, not selectable).
const HUNT_MODE_OPTIONS = [
  { value: 'compliance', label: 'Compliance' },
  { value: 'bug_bounty', label: 'Bug Bounty' },
];

function normalizeHuntMode(raw) {
  const m = String(raw || '').trim().toLowerCase().replace(/-/g, '_');
  if (m === 'bounty' || m === 'bugbounty') return 'bug_bounty';
  // Community: coerce Open Hunt to Bug Bounty.
  if (m === 'open' || m === 'openhunt' || m === 'open_hunt') return 'bug_bounty';
  if (m === 'compliance' || m === 'bug_bounty') return m;
  return 'bug_bounty';
}

function normalizeAutoRunStopLevels(raw) {
  const src = raw && typeof raw === 'object' ? raw : {};
  const next = {
    medium: !!src.medium,
    high: !!src.high,
    critical: !!src.critical,
  };
  if (!AUTO_RUN_STOP_LEVEL_KEYS.some((k) => next[k])) {
    next.high = true;
    next.critical = true;
  }
  return next;
}

function selectedAutoRunStopLevels() {
  const levels = normalizeAutoRunStopLevels(run.stopLevels);
  return AUTO_RUN_STOP_LEVEL_KEYS.filter((k) => levels[k]);
}

watch(
  () => run.manualAssess,
  (on) => {
    try {
      localStorage.setItem('genbounty_manual_assess_on_fire', on ? '1' : '0');
    } catch (_) { /* private browsing */ }
  },
);

function autoRunStopLevelsLabel() {
  const levels = selectedAutoRunStopLevels();
  if (!levels.length) return 'high/critical';
  return levels.join('/');
}

function toggleAutoRunStopLevel(level, checked) {
  if (!AUTO_RUN_STOP_LEVEL_KEYS.includes(level)) return;
  const next = { ...run.stopLevels, [level]: !!checked };
  // Keep at least one stop level so Auto-run cannot run forever by accident.
  if (!AUTO_RUN_STOP_LEVEL_KEYS.some((k) => next[k])) return;
  run.stopLevels = next;
}

// Shared with jobs.js via ctx (must not be local lets - Object.assign copies booleans by value).
ctx._skipRunSelectionPersist = false;
ctx._skipTmSelectionPersist = false;

function persistRunTabSelections() {
  if (ctx._skipRunSelectionPersist || !site.value || !component.value) return;
  writeTabSelections(RUN_TAB_SELECTIONS_KEY, site.value, component.value, {
    scope: run.scope,
    playbook: run.playbook,
    category: run.category,
    strategy: run.strategy,
    assess: run.assess,
    stopLevels: normalizeAutoRunStopLevels(run.stopLevels),
    maxRounds: ctx.normalizeLoopMaxRounds(run.maxRounds),
    huntMode: normalizeHuntMode(run.huntMode),
    customEnhance: !!run.customEnhance,
    customEnhanceText: String(run.customEnhanceText || ''),
    customOverridesFreeze: !!run.customOverridesFreeze,
  });
}

function applySavedCustomEnhance(saved) {
  if (!saved || typeof saved !== 'object') return;
  if (typeof saved.customEnhanceText === 'string') {
    run.customEnhanceText = saved.customEnhanceText;
  }
  if (typeof saved.customEnhance === 'boolean') {
    run.customEnhance = saved.customEnhance;
  }
  if (typeof saved.customOverridesFreeze === 'boolean') {
    run.customOverridesFreeze = saved.customOverridesFreeze;
  }
  // "Always apply" implies the guidance panel should stay open when text was saved.
  if (run.customOverridesFreeze && String(run.customEnhanceText || '').trim()) {
    run.customEnhance = true;
  }
}

function applySavedRunTabSelections() {
  const saved = readTabSelections(RUN_TAB_SELECTIONS_KEY, site.value, component.value);
  if (!saved) return;

  if (saved.scope === 'category' || saved.scope === 'playbook') {
    run.scope = saved.scope;
  }

  if (run.scope === 'category') {
    if (saved.category && runCategoryOptions.value.some((g) => g.key === saved.category)) {
      run.category = saved.category;
    } else if (runCategoryOptions.value.length) {
      run.category = runCategoryOptions.value[0].key;
    }
    run.strategy = '__all__';
    if (typeof saved.assess === 'boolean') run.assess = saved.assess;
    if (saved.stopLevels) run.stopLevels = normalizeAutoRunStopLevels(saved.stopLevels);
    if (saved.maxRounds != null) run.maxRounds = ctx.normalizeLoopMaxRounds(saved.maxRounds);
    if (saved.huntMode) run.huntMode = normalizeHuntMode(saved.huntMode);
    applySavedCustomEnhance(saved);
    return;
  }

  if (saved.category && runCategoryOptions.value.some((g) => g.key === saved.category)) {
    run.category = saved.category;
  }
  const preferredPlay = activePlaybookId.value || saved.playbook || '';
  const slug = ctx.testFileSlugForPlaybook(runTestFiles.value, preferredPlay);
  if (!slug) {
    ctx.ensureRunPlayInCategory();
    if (typeof saved.assess === 'boolean') run.assess = saved.assess;
    if (saved.stopLevels) run.stopLevels = normalizeAutoRunStopLevels(saved.stopLevels);
    if (saved.maxRounds != null) run.maxRounds = ctx.normalizeLoopMaxRounds(saved.maxRounds);
    if (saved.huntMode) run.huntMode = normalizeHuntMode(saved.huntMode);
    applySavedCustomEnhance(saved);
    return;
  }

  run.playbook = slug;
  ctx.syncRunCategoryFromPlaybook();
  // Apply saved strategy before runOnTestFileChange so preserveStrategy can keep it
  // (few_shot vs few-shot must match via normalization).
  if (saved.strategy) {
    run.strategy = saved.strategy;
  }
  if (typeof ctx.runOnTestFileChange === 'function') {
    ctx.runOnTestFileChange(true);
  }
  const matchStrategySlug = ctx.matchStrategySlug || G.matchStrategySlug;
  const matched = matchStrategySlug
    ? matchStrategySlug(runStrategies.value, saved.strategy)
    : '';
  const strategyValid = saved.strategy === '__all__'
    || (matched
      && matched !== '__campaign__'
      && matched !== '__recommended__');
  if (strategyValid && saved.strategy) {
    run.strategy = saved.strategy === '__all__' ? '__all__' : matched;
    ctx.loadRunArtifactStatus();
    if (typeof ctx.loadRunObfuscationStatus === 'function') {
      ctx.loadRunObfuscationStatus();
    }
  }
  if (typeof saved.assess === 'boolean') {
    run.assess = saved.assess;
  }
  if (saved.stopLevels) {
    run.stopLevels = normalizeAutoRunStopLevels(saved.stopLevels);
  }
  if (saved.maxRounds != null) {
    run.maxRounds = ctx.normalizeLoopMaxRounds(saved.maxRounds);
  }
  if (saved.huntMode) {
    run.huntMode = normalizeHuntMode(saved.huntMode);
  }
  applySavedCustomEnhance(saved);
}

function persistTmTabSelections() {
  if (ctx._skipTmSelectionPersist || !site.value || !component.value) return;
  writeTabSelections(TM_TAB_SELECTIONS_KEY, site.value, component.value, {
    playbook: ctx.tmPlaybook.value,
    strategy: ctx.tmStrategy.value,
  });
}

async function applySavedTmTabSelections() {
  const saved = readTabSelections(TM_TAB_SELECTIONS_KEY, site.value, component.value);
  const preferredPlay = activePlaybookId.value || saved?.playbook || '';
  const slug = ctx.testFileSlugForPlaybook(ctx.tmPlaybooks.value, preferredPlay);
  if (!slug) return;

  ctx.tmPlaybook.value = slug;
  ctx.syncTmCategoryFromPlaybook();
  const file = ctx.tmSelectedTestFile();
  ctx.tmStrategies.value = file?.strategies || [];
  if (!ctx.tmStrategies.value.length) return;

  if (saved?.strategy && ctx.tmStrategies.value.some((s) => s.slug === saved.strategy)) {
    ctx.tmStrategy.value = saved.strategy;
  } else if (ctx.tmStrategies.value.length === 1) {
    ctx.tmStrategy.value = ctx.tmStrategies.value[0].slug;
  } else {
    return;
  }
  await ctx.tmLoadFile();
}

function persistActivePlaybook() {
  if (!site.value || !component.value) return;
  writeTabSelections(ACTIVE_PLAYBOOK_KEY, site.value, component.value, {
    playbook: activePlaybookId.value || '',
    category: activeCategoryL1.value || '',
  });
}

function readSavedActiveScope() {
  const saved = readTabSelections(ACTIVE_PLAYBOOK_KEY, site.value, component.value);
  if (saved && typeof saved === 'object') {
    return {
      playbook: String(saved.playbook || '').trim(),
      category: String(saved.category || '').trim(),
    };
  }
  const runSaved = readTabSelections(RUN_TAB_SELECTIONS_KEY, site.value, component.value);
  if (runSaved?.playbook || runSaved?.category) {
    return {
      playbook: String(runSaved.playbook || '').trim(),
      category: String(runSaved.category || '').trim(),
    };
  }
  const tmSaved = readTabSelections(TM_TAB_SELECTIONS_KEY, site.value, component.value);
  if (tmSaved?.playbook) {
    return {
      playbook: String(tmSaved.playbook || '').trim(),
      category: '',
    };
  }
  return { playbook: '', category: '' };
}

function readSavedActivePlaybook() {
  return readSavedActiveScope().playbook;
}

function resolveActiveCategoryCandidate(preferred = '') {
  const keys = new Set(genCategoryOptions.value.map((g) => g.key));
  if (preferred && keys.has(preferred)) return preferred;
  const saved = readSavedActiveScope();
  // Prefer play-derived category over sticky localStorage category when they disagree
  // (e.g. prior Other/Custom session left category=other while the play is elsewhere).
  const fromSavedPlay = saved.playbook
    ? ctx.catalogCategoryForPlaybook(saved.playbook)
    : '';
  if (fromSavedPlay && keys.has(fromSavedPlay) && fromSavedPlay !== saved.category) {
    return fromSavedPlay;
  }
  if (saved.category && keys.has(saved.category)) return saved.category;
  if (activeCategoryL1.value && keys.has(activeCategoryL1.value)) return activeCategoryL1.value;
  const fromPlay = ctx.catalogCategoryForPlaybook(
    activePlaybookId.value || saved.playbook || ctx.gen.playbook
  );
  if (fromPlay && keys.has(fromPlay)) return fromPlay;
  return genCategoryOptions.value[0]?.key || '';
}

function resolveActivePlaybookCandidate(preferred = '') {
  const fromPreferred = ctx.catalogIdForPlaybook(preferred);
  if (fromPreferred) {
    if (!activeCategoryL1.value || ctx.catalogCategoryForPlaybook(fromPreferred) === activeCategoryL1.value) {
      return fromPreferred;
    }
  }
  const fromSaved = ctx.catalogIdForPlaybook(readSavedActivePlaybook());
  if (fromSaved) {
    if (!activeCategoryL1.value || ctx.catalogCategoryForPlaybook(fromSaved) === activeCategoryL1.value) {
      return fromSaved;
    }
  }
  const fromActive = ctx.catalogIdForPlaybook(activePlaybookId.value);
  if (fromActive) {
    if (!activeCategoryL1.value || ctx.catalogCategoryForPlaybook(fromActive) === activeCategoryL1.value) {
      return fromActive;
    }
  }
  const fromGen = ctx.catalogIdForPlaybook(ctx.gen.playbook);
  if (fromGen && (!activeCategoryL1.value || ctx.catalogCategoryForPlaybook(fromGen) === activeCategoryL1.value)) {
    return fromGen;
  }
  return ctx.firstCatalogPlaybookId();
}

async function setActiveCategory(key, opts = {}) {
  const { source = '', persist = true, selectPlay = true } = opts;
  if (ctx._skipActivePlaybookSync) return;
  const next = resolveActiveCategoryCandidate(key);
  ctx.mirrorActiveCategory(next);
  if (run.scope === 'category') {
    ctx.runOnCategoryChange();
  }
  ctx.pbExpandGroup(next);
  if (selectPlay) {
    const stillIn = !!activePlaybookId.value
      && ctx.catalogCategoryForPlaybook(activePlaybookId.value) === next;
    if (!stillIn) {
      const firstId = ctx.activePlaybookOptions.value[0]?.id || '';
      await setActivePlaybook(firstId, { source: source || 'category', persist });
      return;
    }
  }
  if (persist && site.value && component.value) persistActivePlaybook();
}

async function setActivePlaybook(id, opts = {}) {
  const {
    source = '',
    persist = true,
    loadPlays = true,
    loadIntelFile = true,
  } = opts;
  // Never keep a renamed/deleted id (e.g. custom_hunt) once the catalog is available.
  const next = ctx.resolveExistingPlaybookId(id, { allowEmpty: true });
  if (ctx._skipActivePlaybookSync) return;
  if (
    source !== 'plays'
    && loadPlays
    && tab.value === 'playbooks'
    && ctx.pbDirty.value
    && next
    && !ctx._samePlaybookId(ctx.pbSelectedId.value, next)
  ) {
    if (!confirm('Discard unsaved playbook changes?')) return;
    ctx.pbDirty.value = false;
  }
  if (
    source !== 'intel'
    && loadIntelFile
    && tab.value === 'intel'
    && ctx.intelDirty.value
    && next
    && ctx.normalizeIntelPlaybookId(ctx.intelSelectedId.value) !== ctx.normalizeIntelPlaybookId(next)
  ) {
    if (!confirm('Discard unsaved intel changes?')) return;
    ctx.intelDirty.value = false;
  }
  ctx._skipActivePlaybookSync = true;
  try {
    activePlaybookId.value = next;

    if (next) {
      ctx.gen.playbook = ctx.catalogIdForPlaybook(next) || next;
      const cat = ctx.catalogCategoryForPlaybook(next);
      if (cat) ctx.mirrorActiveCategory(cat);
      else {
        ctx.syncGenCategoryFromPlaybook();
        if (ctx.gen.categoryL1) ctx.mirrorActiveCategory(ctx.gen.categoryL1);
        else if (!activeCategoryL1.value && genCategoryOptions.value.length) {
          ctx.mirrorActiveCategory(genCategoryOptions.value[0].key);
        }
      }

      if (run.scope === 'playbook') {
        const runSlug = ctx.testFileSlugForPlaybook(runTestFiles.value, next);
        if (runSlug) {
          run.playbook = runSlug;
          if (activeCategoryL1.value) run.category = activeCategoryL1.value;
          else ctx.syncRunCategoryFromPlaybook();
          if (typeof ctx.runOnTestFileChange === 'function') {
            ctx.runOnTestFileChange(true);
          }
        } else {
          run.playbook = next;
          if (activeCategoryL1.value) run.category = activeCategoryL1.value;
          runStrategies.value = [];
          run.strategy = '';
          runArtifactStatus.value = [];
          runUploadWarning.value = '';
        }
      } else if (activeCategoryL1.value) {
        run.category = activeCategoryL1.value;
      }

      const tmSlug = ctx.testFileSlugForPlaybook(ctx.tmPlaybooks.value, next);
      if (tmSlug) {
        if (activeCategoryL1.value) ctx.tmCategoryL1.value = activeCategoryL1.value;
        if (ctx.tmPlaybook.value !== tmSlug) {
          ctx.tmPlaybook.value = tmSlug;
          ctx.tmOnTestFileChange();
        } else {
          ctx.syncTmCategoryFromPlaybook();
        }
      } else if (activeCategoryL1.value) {
        ctx.tmCategoryL1.value = activeCategoryL1.value;
      }

      if (source !== 'plays' && loadPlays) {
        if (tab.value === 'playbooks') {
          if (!ctx._samePlaybookId(ctx.pbSelectedId.value, next) || !ctx.pbRecord.value) {
            await ctx.pbSelectPlaybook(next);
          }
        } else if (!ctx._samePlaybookId(ctx.pbSelectedId.value, next)) {
          ctx.pbSelectedId.value = next;
        }
      }

      if (source !== 'intel' && loadIntelFile && site.value && component.value) {
        const intelId = ctx.normalizeIntelPlaybookId(next);
        if (intelId) {
          ctx.intelSelectedId.value = intelId;
          if (tab.value === 'intel') await ctx.loadIntel();
        }
      }
    } else {
      ctx.gen.playbook = '';
    }

    if (persist && site.value && component.value) persistActivePlaybook();
  } finally {
    ctx._skipActivePlaybookSync = false;
  }
}

async function restoreActivePlaybook() {
  if (!ctx.pbPlayRows().length && allPlaybooks.value.length) {
    const saved = readSavedActiveScope();
    if (saved.category) activeCategoryL1.value = saved.category;
    const bare = ctx.resolveExistingPlaybookId(
      saved.playbook || activePlaybookId.value || allPlaybooks.value[0] || '',
      { allowEmpty: false },
    );
    if (bare) await setActivePlaybook(bare, { source: 'restore', loadPlays: false });
    return;
  }
  const cat = resolveActiveCategoryCandidate();
  if (cat) ctx.mirrorActiveCategory(cat);
  const id = resolveActivePlaybookCandidate();
  if (id) await setActivePlaybook(id, { source: 'restore' });
  else if (cat) await setActiveCategory(cat, { source: 'restore', selectPlay: true });
  // Drop stale localStorage ids (custom_hunt after rename) once catalog resolved.
  const savedPlay = readSavedActivePlaybook();
  if (savedPlay && !ctx.catalogIdForPlaybook(savedPlay) && activePlaybookId.value) {
    persistActivePlaybook();
  }
}

// Max rounds for the auto-run enhance loop (stops early on selected severities).
const runArtifactStatus = ref([]);
const runUploadWarning = ref('');
const obfuscationTechniques = ref([]);
const runObfuscationTechnique = ref('');
const runObfuscating = ref(false);
const runObfuscateMsg = ref('');
const translationLanguages = ref([]);
const runTranslationLanguage = ref('');
const runTranslating = ref(false);
const runTranslateMsg = ref('');
const nativeLanguages = ref([]);
const runNativeLanguage = ref('');
const runNativeRewriting = ref(false);
const runNativeMsg = ref('');
const manualNativeLanguage = ref('human');
const manualNativeBusy = ref(false);
const manualNativeMsg = ref('');
/** Human prompt saved when converting to a Native dialect (Firing Range). */
const manualHumanPromptBackup = ref('');
const manualNativePrevLanguage = ref('human');
const frameTechniques = ref([]);
const runFrameTechnique = ref('');
const runFrameRewriting = ref(false);
const runFrameMsg = ref('');
const codeLanguages = ref([]);
const runCodeLanguage = ref('');
const runCodeEmbedding = ref(false);
const runCodeEmbedMsg = ref('');
const cipherTechniques = ref([]);
const runCipherTechnique = ref('');
const runCiphering = ref(false);
const runCipherMsg = ref('');
const controlCodes = ref([]);
const runControlCodeTechnique = ref('');
const runControlCoding = ref(false);
const runControlCodeMsg = ref('');
const runIqLevel = ref(100);
const runIqApplying = ref(false);
const runIqMsg = ref('');
const runEmotionLevel = ref(150);
const runEmotionApplying = ref(false);
const runEmotionMsg = ref('');
const runEmotionLevelLabel = computed(() => {
  const n = Number(runEmotionLevel.value);
  if (n <= 30) return 'Super loving & caring';
  if (n <= 70) return 'Warm & supportive';
  if (n <= 110) return 'Mildly positive';
  if (n <= 150) return 'Neutral';
  if (n <= 190) return 'Firm & impatient';
  if (n <= 230) return 'Stern & demanding';
  if (n <= 270) return 'Angry & forceful';
  return 'Furious & demanding';
});
const runAttrTemperature = ref(1.0);
const runAttrMaxTokens = ref(256);
const runAttrTopK = ref(40);
const runAttrTopP = ref(0.95);
const runAttrApplying = ref(false);
const runAttrMsg = ref('');
const runGenAttributesEnabled = ref(localStorage.getItem('genbounty_gen_attributes_enabled') === '1');
try {
  const _savedGenAttrs = JSON.parse(localStorage.getItem('genbounty_gen_attributes') || '');
  if (_savedGenAttrs && typeof _savedGenAttrs === 'object') {
    if (_savedGenAttrs.temperature != null) runAttrTemperature.value = Number(_savedGenAttrs.temperature);
    if (_savedGenAttrs.max_tokens != null) runAttrMaxTokens.value = Number(_savedGenAttrs.max_tokens);
    if (_savedGenAttrs.top_k != null) runAttrTopK.value = Number(_savedGenAttrs.top_k);
    if (_savedGenAttrs.top_p != null) runAttrTopP.value = Number(_savedGenAttrs.top_p);
  }
} catch (_) { /* ignore bad prefs */ }

// Per-transform "include in Generate & Enhance pipeline" checkboxes (panel order).
const runGenTransformApply = reactive({
  obfuscation: false,
  translation: false,
  native: false,
  frame: false,
  code_embed: false,
  cipher: false,
  control_code: false,
  iq: false,
  emotion: false,
});
try {
  const _savedApply = JSON.parse(localStorage.getItem('genbounty_gen_transform_apply') || '');
  if (_savedApply && typeof _savedApply === 'object') {
    for (const key of Object.keys(runGenTransformApply)) {
      if (typeof _savedApply[key] === 'boolean') runGenTransformApply[key] = _savedApply[key];
    }
  }
} catch (_) { /* ignore */ }
try {
  const _savedVals = JSON.parse(localStorage.getItem('genbounty_gen_transform_values') || '');
  if (_savedVals && typeof _savedVals === 'object') {
    if (typeof _savedVals.obfuscation === 'string') runObfuscationTechnique.value = _savedVals.obfuscation;
    if (typeof _savedVals.translation === 'string') runTranslationLanguage.value = _savedVals.translation;
    if (typeof _savedVals.native === 'string') runNativeLanguage.value = _savedVals.native;
    if (typeof _savedVals.frame === 'string') runFrameTechnique.value = _savedVals.frame;
    if (typeof _savedVals.code_embed === 'string') runCodeLanguage.value = _savedVals.code_embed;
    if (typeof _savedVals.cipher === 'string') runCipherTechnique.value = _savedVals.cipher;
    if (typeof _savedVals.control_code === 'string') runControlCodeTechnique.value = _savedVals.control_code;
    if (_savedVals.iq != null && _savedVals.iq !== '') runIqLevel.value = Number(_savedVals.iq);
    if (_savedVals.emotion != null && _savedVals.emotion !== '') runEmotionLevel.value = Number(_savedVals.emotion);
  }
} catch (_) { /* ignore */ }

const runObfuscationHasBackup = ref(false);

function currentGenAttributes() {
  return {
    temperature: Number(runAttrTemperature.value),
    max_tokens: Number(runAttrMaxTokens.value),
    top_k: Number(runAttrTopK.value),
    top_p: Number(runAttrTopP.value),
  };
}

function currentGenTransformValues() {
  return {
    obfuscation: runObfuscationTechnique.value || '',
    translation: runTranslationLanguage.value || '',
    native: runNativeLanguage.value || '',
    frame: runFrameTechnique.value || '',
    code_embed: runCodeLanguage.value || '',
    cipher: runCipherTechnique.value || '',
    control_code: runControlCodeTechnique.value || '',
    iq: Number(runIqLevel.value),
    emotion: Number(runEmotionLevel.value),
  };
}

/** Ordered pipeline steps from checked rows that have a value selected. */
function currentGenTransformPipeline() {
  const values = currentGenTransformValues();
  const order = [
    'obfuscation',
    'translation',
    'native',
    'frame',
    'code_embed',
    'cipher',
    'control_code',
    'iq',
    'emotion',
  ];
  const steps = [];
  for (const kind of order) {
    if (!runGenTransformApply[kind]) continue;
    const name = values[kind];
    if (kind === 'iq' || kind === 'emotion') {
      if (name === '' || name == null || Number.isNaN(Number(name))) continue;
      steps.push({ kind, name: String(Number(name)) });
    } else if (typeof name === 'string' && name.trim()) {
      steps.push({ kind, name: name.trim() });
    }
  }
  return steps;
}

const runGenTransformPipelinePreview = computed(() => {
  const steps = currentGenTransformPipeline();
  if (!steps.length) return '';
  return steps.map(s => `${s.kind}:${s.name}`).join(' → ');
});

function persistGenAttributesPrefs() {
  localStorage.setItem(
    'genbounty_gen_attributes_enabled',
    runGenAttributesEnabled.value ? '1' : '0',
  );
  localStorage.setItem('genbounty_gen_attributes', JSON.stringify(currentGenAttributes()));
  localStorage.setItem('genbounty_gen_transform_apply', JSON.stringify({ ...runGenTransformApply }));
  localStorage.setItem('genbounty_gen_transform_values', JSON.stringify(currentGenTransformValues()));
}

function restoreGenAttributesDefaults() {
  runAttrTemperature.value = 1.0;
  runAttrMaxTokens.value = 256;
  runAttrTopK.value = 40;
  runAttrTopP.value = 0.95;
  persistGenAttributesPrefs();
  runAttrMsg.value = 'Restored attribute defaults (temp 1.0, max tokens 256, top-k 40, top-p 0.95).';
}

function genAttributesJobParams() {
  if (!runGenAttributesEnabled.value) {
    return { gen_attributes_enabled: false };
  }
  return {
    gen_attributes_enabled: true,
    gen_attributes: currentGenAttributes(),
  };
}

function genTransformsJobParams() {
  if (!runGenAttributesEnabled.value) {
    return { gen_transforms_enabled: false };
  }
  const steps = currentGenTransformPipeline();
  if (!steps.length) {
    return { gen_transforms_enabled: false };
  }
  return {
    gen_transforms_enabled: true,
    gen_transforms: steps,
  };
}

function genAutoApplyJobParams() {
  return {
    ...genAttributesJobParams(),
    ...genTransformsJobParams(),
  };
}
const _savedGenTransformsLayout = localStorage.getItem('genbounty_gen_transforms_layout');
const _legacyTransformsMinimized = localStorage.getItem('genbounty_run_transforms_minimized');
const genTransformsLayout = ref(
  _savedGenTransformsLayout === 'maximized' || _savedGenTransformsLayout === 'minimized'
    ? _savedGenTransformsLayout
    : _legacyTransformsMinimized === null
      ? 'minimized'
      : (_legacyTransformsMinimized === '1' ? 'minimized' : 'normal')
);

function persistGenTransformsLayout() {
  localStorage.setItem('genbounty_gen_transforms_layout', genTransformsLayout.value);
  localStorage.setItem(
    'genbounty_run_transforms_minimized',
    genTransformsLayout.value === 'minimized' ? '1' : '0'
  );
}

function toggleGenTransformsMinimize() {
  genTransformsLayout.value = genTransformsLayout.value === 'minimized' ? 'normal' : 'minimized';
  persistGenTransformsLayout();
}

function toggleGenTransformsMaximize() {
  genTransformsLayout.value = genTransformsLayout.value === 'maximized' ? 'normal' : 'maximized';
  persistGenTransformsLayout();
}

const _savedManualTransformsLayout = localStorage.getItem('genbounty_manual_transforms_layout');
const manualTransformsLayout = ref(
  _savedManualTransformsLayout === 'maximized' || _savedManualTransformsLayout === 'minimized'
    ? _savedManualTransformsLayout
    : 'minimized'
);

function persistManualTransformsLayout() {
  localStorage.setItem('genbounty_manual_transforms_layout', manualTransformsLayout.value);
}

const genTransformsMaximizedActive = computed(
  () => genTransformsLayout.value === 'maximized'
);

// Experiment Output: follow newest lines when enabled and pinned to the bottom.
// Pin state is updated on user scroll - do not re-measure after content grows
// (burst SSE lines would otherwise exceed the near-bottom threshold and freeze follow).
const _savedOutputFollowTail = localStorage.getItem('genbounty_output_follow_tail');
const outputFollowTail = ref(_savedOutputFollowTail === null ? true : _savedOutputFollowTail === '1');
const panelConsole = ref(null);
const outputFollowPinned = ref(true);

function getOutputConsoleEl() {
  return panelConsole.value || document.querySelector('.output-panel .console');
}

function isOutputConsoleNearBottom(el, threshold = 80) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}

function onOutputConsoleScroll() {
  const el = getOutputConsoleEl();
  if (!el) return;
  outputFollowPinned.value = isOutputConsoleNearBottom(el);
}

function toggleOutputFollowTail() {
  outputFollowTail.value = !outputFollowTail.value;
  localStorage.setItem('genbounty_output_follow_tail', outputFollowTail.value ? '1' : '0');
  if (outputFollowTail.value) {
    outputFollowPinned.value = true;
    maybeScrollOutputConsole(true);
  }
}

function maybeScrollOutputConsole(force = false) {
  const el = getOutputConsoleEl();
  if (!el) return;
  if (!force && !outputFollowTail.value) return;
  if (!force && !outputFollowPinned.value) return;
  el.scrollTop = el.scrollHeight;
  outputFollowPinned.value = true;
}

    const api_out = {
      run,
      AUTO_RUN_STOP_LEVEL_KEYS,
      HUNT_MODE_OPTIONS,
      normalizeHuntMode,
      normalizeAutoRunStopLevels,
      selectedAutoRunStopLevels,
      autoRunStopLevelsLabel,
      toggleAutoRunStopLevel,
      persistRunTabSelections,
      applySavedRunTabSelections,
      persistTmTabSelections,
      applySavedTmTabSelections,
      persistActivePlaybook,
      readSavedActiveScope,
      readSavedActivePlaybook,
      resolveActiveCategoryCandidate,
      resolveActivePlaybookCandidate,
      setActiveCategory,
      setActivePlaybook,
      restoreActivePlaybook,
      runArtifactStatus,
      runUploadWarning,
      obfuscationTechniques,
      runObfuscationTechnique,
      runObfuscating,
      runObfuscateMsg,
      translationLanguages,
      runTranslationLanguage,
      runTranslating,
      runTranslateMsg,
      nativeLanguages,
      runNativeLanguage,
      runNativeRewriting,
      runNativeMsg,
      manualNativeLanguage,
      manualNativeBusy,
      manualNativeMsg,
      manualHumanPromptBackup,
      manualNativePrevLanguage,
      frameTechniques,
      runFrameTechnique,
      runFrameRewriting,
      runFrameMsg,
      codeLanguages,
      runCodeLanguage,
      runCodeEmbedding,
      runCodeEmbedMsg,
      cipherTechniques,
      runCipherTechnique,
      runCiphering,
      runCipherMsg,
      controlCodes,
      runControlCodeTechnique,
      runControlCoding,
      runControlCodeMsg,
      runIqLevel,
      runIqApplying,
      runIqMsg,
      runEmotionLevel,
      runEmotionApplying,
      runEmotionMsg,
      runEmotionLevelLabel,
      runAttrTemperature,
      runAttrMaxTokens,
      runAttrTopK,
      runAttrTopP,
      runAttrApplying,
      runAttrMsg,
      runGenAttributesEnabled,
      runGenTransformApply,
      runObfuscationHasBackup,
      currentGenAttributes,
      currentGenTransformValues,
      currentGenTransformPipeline,
      runGenTransformPipelinePreview,
      persistGenAttributesPrefs,
      restoreGenAttributesDefaults,
      genAttributesJobParams,
      genTransformsJobParams,
      genAutoApplyJobParams,
      genTransformsLayout,
      manualTransformsLayout,
      persistGenTransformsLayout,
      persistManualTransformsLayout,
      genTransformsMaximizedActive,
      toggleGenTransformsMinimize,
      toggleGenTransformsMaximize,
      _savedOutputFollowTail,
      outputFollowTail,
      panelConsole,
      outputFollowPinned,
      getOutputConsoleEl,
      isOutputConsoleNearBottom,
      onOutputConsoleScroll,
      toggleOutputFollowTail,
      maybeScrollOutputConsole
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
