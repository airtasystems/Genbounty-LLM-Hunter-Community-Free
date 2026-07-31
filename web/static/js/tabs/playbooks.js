/**
 * Domain module: usePlaybooks
 */
(function (G) {
  'use strict';

  G.usePlaybooks = function usePlaybooks(ctx) {
    const {
      activeCategoryL1,
      activePlaybookId,
      allPlaybooks,
      armConfirm,
      clearConfirmArmed,
      component,
      computed,
      isConfirmArmed,
      nextTick,
      onMounted,
      reactive,
      ref,
      requestConfirm,
      requestConfirmAsync,
      runStrategies,
      runTestFiles,
      site,
      watch
    } = ctx;
    const api = G.api;

const STRATEGY_DEFAULT_PLAYBOOK = '';

const gen = reactive({ strategy: '', categoryL1: '', playbook: '', multimodal: false });
const showPlaybookModal = ref(false);
const pbWizardStep = ref(1);
const pbCreateMode = ref(''); // '' | 'human' | 'ai'
const pbAiConflict = ref(false);
const pbPreset = ref(null);
const pbPresetCatalog = ref({});
const pbTargetCapabilities = ref({});
const pbWizardAppliedPresetKey = ref('');
const pbWizardAppliedTitleHint = ref('');
const pbGenerating = ref(false);
let pbGenerateAbort = null;
const pbError = ref('');
const pbMsg = ref('');
const pbGenerationOutput = ref([]);
const playCategoryTree = ref([]);
const pbForm = reactive({
  playbook_id: '',
  name: '',
  play: '',
  play_category_l1: 'mission',
  play_category_l2: 'hunt',
  play_category_label: '',
  success_rules: '',
  failure_rules: '',
  success_rule_list: [''],
  failure_rule_list: [''],
  stop_words: '',
  overwrite: false,
  /** After AI create: kick off Missions Deploy Probes for the new play. */
  autorun: false,
  /** AI create: keep Mission brief exactly as written (no bounty-claim rewrite). */
  keep_play_verbatim: false,
  /** Optional exact canary string → success/fail + response_marker. */
  exact_canary: '',
  delivery_constraints: '',
  apply_delivery_to_seeds: true,
  mandatory_directives: '',
  expert_guidance: '',
  followup_guidance: '',
  theory_guidance: '',
  standard_action: '',
  attack_objective: '',
  prompt_template: '',
  prompt_task: '',
  prompt_format: '',
});
const pbConfigForm = reactive({
  delivery_constraints: '',
  apply_delivery_to_seeds: true,
  mandatory_directives: '',
  expert_guidance: '',
  followup_guidance: '',
  theory_guidance: '',
  standard_action: '',
  attack_objective: '',
  prompt_template: '',
  prompt_task: '',
  prompt_format: '',
});
const pbRecordCat = reactive({
  play_category_l1: 'mission',
  play_category_l2: 'hunt',
  play_category_label: '',
});
const pbRecordCategoryBaseline = ref('');

function pbResetGenerationOutput(label = 'Play generation') {
  pbGenerationOutput.value = [`[playbook] ${label} started.`];
}

function pbPushGenerationOutput(line) {
  pbGenerationOutput.value.push(line);
}

function pbStartGenerationHeartbeat(label) {
  let elapsed = 0;
  return setInterval(() => {
    elapsed += 8;
    pbPushGenerationOutput(`[playbook] ${label} still running - ${elapsed}s elapsed.`);
  }, 8000);
}

function pbFormatGenerationLine(line) {
  return String(line || '').replace(/^\[playbook\]\s*/, '');
}

const pbGenerationCurrentPhase = computed(() => {
  const lines = pbGenerationOutput.value;
  if (!lines.length) return '';
  for (let i = lines.length - 1; i >= 0; i--) {
    const text = pbFormatGenerationLine(lines[i]);
    if (/Phase \d\/5:/i.test(text)) return text;
  }
  return pbFormatGenerationLine(lines[lines.length - 1]);
});

const pbGenerationStatusKind = computed(() => {
  if (pbGenerating.value) return 'active';
  const lines = pbGenerationOutput.value;
  const last = lines.length ? pbFormatGenerationLine(lines[lines.length - 1]) : '';
  if (/^Failed:/i.test(last)) return 'failed';
  if (/^Complete\.?$/i.test(last)) return 'done';
  return 'idle';
});

const pbRegenerating = ref(false);

function pbObjectiveLexiconToLines(raw) {
  if (!raw) return '';
  if (typeof raw === 'string') return raw.trim();
  if (typeof raw !== 'object' || Array.isArray(raw)) return '';
  return Object.entries(raw)
    .map(([k, v]) => `${String(k || '').trim()}=${String(v || '').trim()}`)
    .filter((line) => line.includes('=') && !line.startsWith('='))
    .join('\n');
}

/** Starter envelopes for Plan Mission / Missions prompt_template. */
const PB_PROMPT_TEMPLATE_CHIPS = [
  {
    id: 'json',
    label: 'JSON',
    template: '{"task":"{{task}}","input":"{{input}}","output_format":"{{format}}"}',
  },
  {
    id: 'pipe',
    label: 'Pipe',
    template: 'Task: {{task}} | Input: {{input}} | Output: {{format}}',
  },
  {
    id: 'html',
    label: 'HTML',
    template: '<p>Task: {{task}} | Input: {{input}} | Output: {{format}}</p>',
  },
];

function pbApplyPromptTemplateChip(target, chipOrId) {
  const chip = typeof chipOrId === 'string'
    ? PB_PROMPT_TEMPLATE_CHIPS.find((c) => c.id === chipOrId)
    : chipOrId;
  if (!chip || !target) return;
  target.prompt_template = chip.template;
}

function pbEmptyPlaybookConfigFields() {
  return {
    delivery_constraints: '',
    apply_delivery_to_seeds: true,
    mandatory_directives: '',
    expert_guidance: '',
    followup_guidance: '',
    theory_guidance: '',
    standard_action: '',
    attack_objective: '',
    prompt_template: '',
    prompt_task: '',
    prompt_format: '',
  };
}

function pbPlaybookConfigFromRecord(record) {
  const cfg = record?.playbook_config || {};
  const adaptive = cfg.adaptive || {};
  const generation = cfg.generation || {};
  const enhancement = cfg.enhancement || {};
  const storedAction = String(generation.standard_action || '').trim();
  const storedObjective = String(generation.attack_objective || '').trim();
  return {
    delivery_constraints: adaptive.delivery_constraints || '',
    apply_delivery_to_seeds: generation.apply_delivery_to_seeds !== false,
    mandatory_directives: Array.isArray(generation.mandatory_directives)
      ? generation.mandatory_directives.join('\n')
      : '',
    expert_guidance: generation.expert_guidance || '',
    followup_guidance: adaptive.followup_guidance || '',
    theory_guidance: enhancement.theory_guidance || '',
    standard_action: storedAction,
    attack_objective: storedObjective,
    prompt_template: String(generation.prompt_template || '').trim(),
    prompt_task: String(generation.prompt_task || '').trim(),
    prompt_format: String(generation.prompt_format || '').trim(),
  };
}

function pbPlaybookConfigApiPayload(source) {
  const s = source || {};
  const payload = {};
  const delivery = String(s.delivery_constraints || '').trim();
  if (delivery) payload.delivery_constraints = delivery;
  if (s.apply_delivery_to_seeds === true || s.apply_delivery_to_seeds === false) {
    payload.apply_delivery_to_seeds = s.apply_delivery_to_seeds;
  }
  const mandatory = String(s.mandatory_directives || '').trim();
  if (mandatory) payload.mandatory_directives = mandatory;
  const expert = String(s.expert_guidance || '').trim();
  if (expert) payload.expert_guidance = expert;
  const followup = String(s.followup_guidance || '').trim();
  if (followup) payload.followup_guidance = followup;
  const theory = String(s.theory_guidance || '').trim();
  if (theory) payload.theory_guidance = theory;
  const objective = String(s.attack_objective || '').trim();
  if (objective) payload.attack_objective = objective;
  // Always send template fields so clear-on-regenerate works (empty clears prior).
  payload.prompt_template = String(s.prompt_template || '').trim();
  payload.prompt_task = String(s.prompt_task || '').trim();
  payload.prompt_format = String(s.prompt_format || '').trim();
  const action = String(s.standard_action || '').trim();
  if (action) payload.standard_action = action;
  return Object.keys(payload).length ? payload : null;
}

function pbApplyPlaybookConfigFieldsToRecord(source) {
  if (!pbRecord.value) return;
  const s = source || pbConfigForm;
  const delivery = String(s.delivery_constraints || '').trim();
  const mandatory = pbListFromLines(String(s.mandatory_directives || ''));
  const expert = String(s.expert_guidance || '').trim();
  const followup = String(s.followup_guidance || '').trim();
  const theory = String(s.theory_guidance || '').trim();
  const objective = String(s.attack_objective || '').trim();
  const promptTemplate = String(s.prompt_template || '').trim();
  const promptTask = String(s.prompt_task || '').trim();
  const promptFormat = String(s.prompt_format || '').trim();
  const action = String(s.standard_action || '').trim();
  // Preserve structural sections the Advanced form does not edit (oracles, escalate
  // payload, recon, strategy seeds, thesis, adaptive limits). Rebuilding from the
  // form alone used to wipe these and break Regenerate pre-save validation.
  const prev = (pbRecord.value.playbook_config && typeof pbRecord.value.playbook_config === 'object')
    ? pbRecord.value.playbook_config
    : {};
  const prevAdaptive = (prev.adaptive && typeof prev.adaptive === 'object') ? prev.adaptive : {};
  const prevGeneration = (prev.generation && typeof prev.generation === 'object') ? prev.generation : {};
  const prevEnhancement = (prev.enhancement && typeof prev.enhancement === 'object') ? prev.enhancement : {};
  const hasStructural = Boolean(
    prev.assessment
    || prev.recon
    || prevGeneration.escalation_payload
    || prevGeneration.strategies
    || prevEnhancement.thesis
    || prevAdaptive.max_turns != null
    || prevAdaptive.max_llm_calls != null,
  );
  const hasAny = Boolean(
    delivery || mandatory.length || expert || followup || theory || objective
    || promptTemplate || promptTask || promptFormat || action
    || s.apply_delivery_to_seeds === false
    || hasStructural,
  );
  if (!hasAny) {
    delete pbRecord.value.playbook_config;
    return;
  }
  const cfg = {};
  const adaptive = {};
  const generation = {};
  const enhancement = {};
  if (delivery) adaptive.delivery_constraints = delivery;
  if (followup) adaptive.followup_guidance = followup;
  if (prevAdaptive.max_turns != null) adaptive.max_turns = prevAdaptive.max_turns;
  if (prevAdaptive.max_llm_calls != null) adaptive.max_llm_calls = prevAdaptive.max_llm_calls;
  generation.apply_delivery_to_seeds = s.apply_delivery_to_seeds !== false;
  if (mandatory.length) generation.mandatory_directives = mandatory;
  if (expert) generation.expert_guidance = expert;
  if (objective) generation.attack_objective = objective;
  if (promptTemplate) generation.prompt_template = promptTemplate;
  if (promptTask) generation.prompt_task = promptTask;
  if (promptFormat) generation.prompt_format = promptFormat;
  // Preserve legacy lexicon on disk if present (editor no longer authors it).
  if (prevGeneration.objective_lexicon && typeof prevGeneration.objective_lexicon === 'object') {
    generation.objective_lexicon = prevGeneration.objective_lexicon;
  }
  if (action) generation.standard_action = action;
  if (prevGeneration.escalation_payload) {
    generation.escalation_payload = prevGeneration.escalation_payload;
  }
  if (prevGeneration.strategies && typeof prevGeneration.strategies === 'object') {
    generation.strategies = prevGeneration.strategies;
  }
  if (theory) enhancement.theory_guidance = theory;
  if (prevEnhancement.thesis) enhancement.thesis = prevEnhancement.thesis;
  if (Object.keys(adaptive).length) cfg.adaptive = adaptive;
  if (Object.keys(generation).length) cfg.generation = generation;
  if (Object.keys(enhancement).length) cfg.enhancement = enhancement;
  if (prev.assessment) cfg.assessment = prev.assessment;
  if (prev.recon) cfg.recon = prev.recon;
  pbRecord.value.playbook_config = cfg;
}

function pbSyncConfigFormFromRecord(record) {
  Object.assign(pbConfigForm, pbEmptyPlaybookConfigFields(), pbPlaybookConfigFromRecord(record));
}

function pbOnConfigInput() {
  pbApplyPlaybookConfigFieldsToRecord(pbConfigForm);
  pbSyncJsonFromRecord();
  pbMarkDirty();
}

function pbCategoryKeyFromParts(l1, l2, label) {
  const custom = l1 === 'mission' && l2 === 'hunt' ? String(label || '').trim() : '';
  return [l1 || '', l2 || '', custom].join('|');
}

function pbCategoryKeyFromRecord(record) {
  const path = pbPathFromRecord(record);
  return pbCategoryKeyFromParts(path[0], path[1], record?.play_category_label || '');
}

function pbCategoryKeyFromSelectors() {
  return pbCategoryKeyFromParts(
    pbRecordCat.play_category_l1,
    pbRecordCat.play_category_l2,
    pbRecordCat.play_category_label,
  );
}

function pbSetCategoryBaseline(record) {
  pbRecordCategoryBaseline.value = pbCategoryKeyFromRecord(record);
}

function pbCategoryChanged() {
  return pbCategoryKeyFromSelectors() !== pbRecordCategoryBaseline.value;
}

function pbCatL1Options() {
  return playCategoryTree.value;
}

function pbCatL2Options(l1) {
  const node = playCategoryTree.value.find((n) => n.id === l1);
  return node?.children || [];
}

function pbCapabilityRequirementSatisfied(requirement) {
  return String(requirement || '')
    .split('|')
    .map((name) => name.trim())
    .filter(Boolean)
    .some((name) => !!pbTargetCapabilities.value[name]);
}

function pbLeafCapabilityRequirements(l1, l2) {
  const preset = pbPresetCatalog.value?.[`${l1}.${l2}`] || {};
  return Array.isArray(preset.required_capabilities)
    ? preset.required_capabilities.map(String).filter(Boolean)
    : [];
}

function pbLeafCompatible(l1, l2) {
  return pbLeafCapabilityRequirements(l1, l2)
    .every(pbCapabilityRequirementSatisfied);
}

function pbLeafDisabledReason(l1, l2) {
  const missing = pbLeafCapabilityRequirements(l1, l2)
    .filter((requirement) => !pbCapabilityRequirementSatisfied(requirement));
  return missing.length ? `Requires target capability: ${missing.join(', ')}` : '';
}

function pbL1Compatible(l1) {
  const children = pbCatL2Options(l1);
  return !children.length || children.some((child) => pbLeafCompatible(l1, child.id));
}

function pbDefaultL2(l1) {
  const node = playCategoryTree.value.find((n) => n.id === l1);
  if (!node) return '';
  if (node.default_l2) return node.default_l2;
  return node.children?.[0]?.id || '';
}

function pbEnsureCategoryDefaults(form) {
  if (!form) return;
  // Taxonomy is mission.hunt only - lock the wizard/editor to that leaf.
  form.play_category_l1 = 'mission';
  form.play_category_l2 = 'hunt';
}

function pbPathFromRecord(record) {
  if (!record) return [];
  if (Array.isArray(record.play_category_path) && record.play_category_path.length === 2) {
    return record.play_category_path.slice();
  }
  const cat = record.play_category || '';
  if (cat.includes('.')) {
    const parts = cat.split('.').filter(Boolean);
    if (parts.length === 2) return parts;
  }
  return [];
}

function pbApplyPathToSelectors(target, path) {
  // Taxonomy is mission.hunt only - ignore historical multi-leaf paths.
  void path;
  target.play_category_l1 = 'mission';
  target.play_category_l2 = 'hunt';
}

function pbBuildCategoryPath(form) {
  return [form.play_category_l1, form.play_category_l2].filter(Boolean);
}

function pbIsOtherCustom(form) {
  return form.play_category_l1 === 'mission' && form.play_category_l2 === 'hunt';
}

function pbCustomPurposeValid(form = pbForm) {
  if (!pbIsOtherCustom(form)) return true;
  if (!String(form.play_category_label || '').trim()) return false;
  // AI create needs a real purpose; human can refine on the hypothesis step.
  if (pbCreateMode.value === 'ai' && String(form.play || '').trim().length < 15) return false;
  return true;
}

function pbOnCustomHuntNameInput() {
  if (!pbIsOtherCustom(pbForm)) return;
  const label = pbForm.play_category_label.trim();
  if (label && !pbForm.name.trim()) {
    pbForm.name = label.slice(0, 80);
  } else if (label) {
    const cur = pbForm.name.trim();
    if (!cur || /^custom hunt$/i.test(cur)) {
      pbForm.name = label.slice(0, 80);
    }
  }
  pbSuggestId();
  pbWizardLoadPreset();
}

function pbOnCustomPurposeInput() {
  if (!pbIsOtherCustom(pbForm)) return;
  // Keep Build with AI enabled as soon as purpose is long enough.
  pbError.value = '';
}

function pbOnFormCategoryL1() {
  pbForm.play_category_l2 = pbDefaultL2(pbForm.play_category_l1);
  pbEnsureCategoryDefaults(pbForm);
  if (pbForm.play_category_l1 !== 'mission') pbForm.play_category_label = '';
  pbWizardLoadPreset();
}

function pbOnFormCategoryL2() {
  if (pbForm.play_category_l1 !== 'mission') pbForm.play_category_label = '';
  pbWizardLoadPreset();
}

function pbWizardNonEmptyRules(list) {
  return (list || []).map((r) => String(r || '').trim()).filter(Boolean);
}

function pbWizardRulesToText(list) {
  return pbWizardNonEmptyRules(list).join('\n');
}

function pbWizardCategoryLabel() {
  const hunt = String(pbForm.play_category_label || '').trim();
  if (hunt) return hunt;
  return String(pbForm.name || '').trim() || 'Untitled hunt';
}

async function pbWizardLoadPreset(opts = {}) {
  const force = !!opts.force;
  pbEnsureCategoryDefaults(pbForm);
  const l1 = pbForm.play_category_l1;
  const l2 = pbForm.play_category_l2;
  if (!l1 || !l2) return;
  const key = `${l1}.${l2}:${(pbForm.play_category_label || '').trim()}`;
  try {
    const q = pbForm.play_category_label.trim()
      ? `?play_category_label=${encodeURIComponent(pbForm.play_category_label.trim())}`
      : '';
    const preset = await api(`/api/plays/category-presets/${encodeURIComponent(l1)}/${encodeURIComponent(l2)}${q}`);
    pbPreset.value = preset;
    const categoryChanged = key !== pbWizardAppliedPresetKey.value;
    const applyRules = force || categoryChanged;
    const prevHint = pbWizardAppliedTitleHint.value;
    if (applyRules) {
      pbForm.success_rule_list = (preset.success_rules || []).length
        ? preset.success_rules.slice()
        : [''];
      pbForm.failure_rule_list = (preset.failure_rules || []).length
        ? preset.failure_rules.slice()
        : [''];
      if (preset.delivery_constraints) {
        pbForm.delivery_constraints = preset.delivery_constraints;
        pbForm.apply_delivery_to_seeds = true;
      } else if (categoryChanged) {
        // Clear stale delivery rail when switching away from code-execution presets
        pbForm.delivery_constraints = '';
        pbForm.apply_delivery_to_seeds = false;
      }
      if (preset.standard_action) {
        pbForm.standard_action = preset.standard_action;
      } else if (categoryChanged) {
        pbForm.standard_action = '';
      }
      pbWizardAppliedPresetKey.value = key;
    }
    if (!pbForm.play.trim() && preset.play_starter) {
      pbForm.play = preset.play_starter;
    }
    if (categoryChanged) {
      const curName = pbForm.name.trim();
      const shouldReplaceName = !curName
        || (prevHint && curName === prevHint)
        || /^custom hunt$/i.test(curName);
      if (shouldReplaceName && preset.title_hint) {
        pbForm.name = preset.title_hint;
        pbSuggestId();
      }
      pbWizardAppliedTitleHint.value = String(preset.title_hint || '').trim();
    }
    pbSuggestId();
  } catch (_) {
    pbPreset.value = null;
  }
}

function pbWizardExactCanarySuccess(canary) {
  return `Response contains the exact string: '${canary}'`;
}

function pbWizardExactCanaryFailure(canary) {
  return `Response does not contain the exact string: '${canary}'`;
}

function pbWizardExactCanaryObjective(canary) {
  return `Emit exactly this string: ${canary}`;
}

function pbWizardApplyExactCanary() {
  const canary = String(pbForm.exact_canary || '').trim();
  if (!canary) return;
  pbForm.success_rule_list = [pbWizardExactCanarySuccess(canary)];
  pbForm.failure_rule_list = [pbWizardExactCanaryFailure(canary)];
  if (!String(pbForm.attack_objective || '').trim()) {
    pbForm.attack_objective = pbWizardExactCanaryObjective(canary);
  }
}

function pbWizardOnExactCanaryInput() {
  pbWizardApplyExactCanary();
}

function pbWizardResetRulesToPreset() {
  pbForm.exact_canary = '';
  pbWizardLoadPreset({ force: true });
}

async function pbWizardSelectL1(id) {
  if (!pbL1Compatible(id)) return;
  pbForm.play_category_l1 = id;
  const children = pbCatL2Options(id);
  const preferred = pbDefaultL2(id);
  pbForm.play_category_l2 = (
    children.find((child) => child.id === preferred && pbLeafCompatible(id, child.id))
    || children.find((child) => pbLeafCompatible(id, child.id))
    || {}
  ).id || '';
  pbEnsureCategoryDefaults(pbForm);
  if (pbForm.play_category_l1 !== 'mission') pbForm.play_category_label = '';
  await pbWizardLoadPreset();
  pbSuggestId();
}

async function pbWizardSelectL2(id) {
  if (!pbLeafCompatible(pbForm.play_category_l1, id)) return;
  pbForm.play_category_l2 = id;
  if (pbForm.play_category_l1 !== 'mission') pbForm.play_category_label = '';
  await pbWizardLoadPreset();
  pbSuggestId();
}

function pbHypothesisLeafHint(form) {
  // Prompt and Instruction L1 (persona/few-shot leaf hints) was removed.
  return '';
}

async function pbApplySuggestedLeafFromHypothesis(target = 'wizard') {
  if (target === 'record') {
    const hint = pbHypothesisLeafHint({
      play: pbRecord.play,
      play_category_l1: pbRecordCat.play_category_l1,
      play_category_l2: pbRecordCat.play_category_l2,
    });
    if (!hint || !hint.suggestedL2) return;
    pbRecordCat.play_category_l2 = hint.suggestedL2;
    pbOnRecordCategoryL2();
    return;
  }
  const hint = pbHypothesisLeafHint(pbForm);
  if (!hint || !hint.suggestedL2) return;
  await pbWizardSelectL2(hint.suggestedL2);
}

function pbWizardCanAdvance() {
  if (pbWizardStep.value === 1) {
    return pbCreateMode.value === 'human' || pbCreateMode.value === 'ai';
  }
  if (pbWizardStep.value === 2) {
    if (!pbFormCategoryValid()) return false;
    // Hypothesis↔leaf hint only applies on human path once a hypothesis exists.
    if (pbCreateMode.value === 'human' && pbHypothesisLeafHint(pbForm)) return false;
    if (!pbCustomPurposeValid(pbForm)) return false;
    return true;
  }
  if (pbCreateMode.value === 'human' && pbWizardStep.value === 3) {
    const play = pbForm.play.trim();
    return !play || play.length >= 15;
  }
  if (pbCreateMode.value === 'human' && pbWizardStep.value === 4) {
    return (
      pbWizardNonEmptyRules(pbForm.success_rule_list).length > 0
      && pbWizardNonEmptyRules(pbForm.failure_rule_list).length > 0
      && pbForm.play.trim().length >= 15
      && !pbHypothesisLeafHint(pbForm)
    );
  }
  return true;
}

function pbWizardCanGenerate() {
  return (
    pbCreateMode.value === 'human'
    && !!pbForm.name.trim()
    && pbForm.play.trim().length >= 15
    && pbFormCategoryValid()
    && pbWizardNonEmptyRules(pbForm.success_rule_list).length > 0
    && pbWizardNonEmptyRules(pbForm.failure_rule_list).length > 0
    && !!pbSlugify(pbForm.playbook_id || pbForm.name)
    && !pbHypothesisLeafHint(pbForm)
  );
}

async function pbWizardSelectMode(mode) {
  const next = mode === 'ai' ? 'ai' : 'human';
  pbCreateMode.value = next;
  pbError.value = '';
  pbWizardStep.value = 2;
  await pbWizardLoadPreset();
}

async function pbWizardNext() {
  pbError.value = '';
  if (!pbWizardCanAdvance()) {
    if (pbWizardStep.value === 1) {
      pbError.value = 'Choose Human or AI to continue.';
    } else if (pbWizardStep.value === 2) {
      const leafHint = pbCreateMode.value === 'human' ? pbHypothesisLeafHint(pbForm) : '';
      if (leafHint) {
        pbError.value = leafHint.message;
      } else if (pbIsOtherCustom(pbForm) && !pbForm.play_category_label.trim()) {
        pbError.value = 'Enter a hunt name for this mission.';
      } else if (pbIsOtherCustom(pbForm) && pbCreateMode.value === 'ai' && pbForm.play.trim().length < 15) {
        pbError.value = 'Describe what you are testing (at least 15 characters).';
      } else {
        pbError.value = 'Enter a hunt name for this mission.';
      }
    } else if (pbWizardStep.value === 3 && pbCreateMode.value === 'human') {
      if (pbForm.play.trim() && pbForm.play.trim().length < 15) {
        pbError.value = 'Play must be at least 15 characters, or leave it blank to use a preset.';
      }
    } else if (pbWizardStep.value === 4 && pbCreateMode.value === 'human') {
      const leafHint = pbHypothesisLeafHint(pbForm);
      pbError.value = leafHint
        ? leafHint.message
        : 'Add at least one success rule, one failure rule, and a play (≥15 chars).';
    }
    return;
  }
  if (pbWizardStep.value === 1) {
    pbWizardStep.value = 2;
    await pbWizardLoadPreset();
    return;
  }
  if (pbWizardStep.value === 2) {
    await pbWizardLoadPreset({ force: pbCreateMode.value === 'ai' });
    pbWizardApplyExactCanary();
    if (pbCreateMode.value === 'ai') {
      await submitPlaybookGenerateAi();
      return;
    }
    // Human: If user already wrote a play, keep it; otherwise preset filled it.
    if (!pbForm.name.trim() && pbPreset.value?.title_hint) {
      pbForm.name = pbPreset.value.title_hint;
      pbSuggestId();
    }
    pbWizardStep.value = 3;
    return;
  }
  if (pbCreateMode.value === 'human' && pbWizardStep.value === 3) {
    await pbWizardLoadPreset();
    pbWizardApplyExactCanary();
    if (!pbForm.play.trim() && pbPreset.value?.play_starter) {
      pbForm.play = pbPreset.value.play_starter;
    }
    pbWizardStep.value = 4;
    return;
  }
  if (pbCreateMode.value === 'human' && pbWizardStep.value === 4) {
    if (!pbForm.name.trim()) {
      pbForm.name = (pbPreset.value?.title_hint || pbForm.play.trim().slice(0, 60) || 'New play').trim();
      pbSuggestId();
    }
    if (!pbForm.playbook_id) pbSuggestId();
    pbWizardStep.value = 5;
  }
}

function pbWizardBack() {
  pbError.value = '';
  pbAiConflict.value = false;
  if (pbWizardStep.value > 1) pbWizardStep.value -= 1;
}

async function openPlaybookModal() {
  pbError.value = '';
  pbMsg.value = '';
  pbWizardStep.value = 1;
  pbCreateMode.value = '';
  pbAiConflict.value = false;
  pbPreset.value = null;
  pbWizardAppliedPresetKey.value = '';
  pbWizardAppliedTitleHint.value = '';
  pbForm.playbook_id = '';
  pbForm.name = '';
  pbForm.play = '';
  pbForm.play_category_l1 = 'mission';
  pbForm.play_category_l2 = pbDefaultL2('mission') || 'hunt';
  pbEnsureCategoryDefaults(pbForm);
  pbForm.play_category_label = '';
  pbForm.success_rules = '';
  pbForm.failure_rules = '';
  pbForm.success_rule_list = [''];
  pbForm.failure_rule_list = [''];
  pbForm.stop_words = '';
  pbForm.overwrite = false;
  pbForm.autorun = false;
  pbForm.keep_play_verbatim = false;
  pbForm.exact_canary = '';
  Object.assign(pbForm, pbEmptyPlaybookConfigFields());
  pbGenerationOutput.value = [];
  pbTargetCapabilities.value = {};
  if (site.value && component.value) {
    try {
      const target = await api(
        `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/capabilities`,
      );
      pbTargetCapabilities.value = target?.capabilities || {};
    } catch (_) {
      pbTargetCapabilities.value = {};
    }
  }
  showPlaybookModal.value = true;
}

function cancelPlaybookGenerate() {
  if (pbGenerateAbort) {
    pbGenerateAbort.abort();
    pbGenerateAbort = null;
  }
}

function closePlaybookModal() {
  if (pbGenerating.value) {
    cancelPlaybookGenerate();
    return;
  }
  showPlaybookModal.value = false;
}

async function _runPlaybookGenerateRequest(authoringMode) {
  const display_name = pbForm.name.trim();
  const play = pbForm.play.trim();
  const playbook_id = pbSlugify(pbForm.playbook_id || display_name);
  pbWizardApplyExactCanary();
  const success_rules = pbWizardRulesToText(pbForm.success_rule_list);
  const failure_rules = pbWizardRulesToText(pbForm.failure_rule_list);
  pbForm.success_rules = success_rules;
  pbForm.failure_rules = failure_rules;
  const categoryPath = pbBuildCategoryPath(pbForm);
  pbGenerating.value = true;
  pbGenerateAbort = new AbortController();
  const signal = pbGenerateAbort.signal;
  pbResetGenerationOutput(`Creating play ${playbook_id}`);
  try {
    pbPushGenerationOutput(`[playbook] Phase 1/5: preparing play hypothesis and category (${categoryPath.join(' / ')}).`);
    pbPushGenerationOutput('[playbook] Phase 2/5: loading target recon context if available.');
    pbPushGenerationOutput(
      authoringMode === 'ai'
        ? '[playbook] Phase 3/5: Mission planning in progress..'
        : '[playbook] Phase 3/5: Mission planning in progress..',
    );
    const heartbeat = pbStartGenerationHeartbeat('Mission planning');
    let result;
    try {
      result = await api('/api/playbooks/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal,
        body: JSON.stringify({
          name: display_name,
          play,
          play_category_path: categoryPath,
          play_category_label: pbForm.play_category_label.trim(),
          success_rules,
          failure_rules,
          stop_words: pbForm.stop_words.trim(),
          playbook_id,
          overwrite: pbForm.overwrite,
          authoring_mode: authoringMode === 'ai' ? 'ai' : 'human',
          keep_play_verbatim: authoringMode === 'ai' && !!pbForm.keep_play_verbatim,
          exact_canary: String(pbForm.exact_canary || '').trim(),
          site: site.value || '',
          component: component.value || '',
          playbook_config: pbPlaybookConfigApiPayload(pbForm),
        }),
      });
    } finally {
      clearInterval(heartbeat);
    }
    pbAiConflict.value = false;
    pbPushGenerationOutput(`[playbook] Mission planning complete after ${result.generation_attempts || 1} attempt(s).`);
    pbPushGenerationOutput('[playbook] Phase 4/5: refreshing play catalog and selectors.');
    allPlaybooks.value = await api('/api/playbooks');
    await pbLoadCatalog(result.playbook_id);
    const cat = typeof ctx.catalogCategoryForPlaybook === 'function'
      ? ctx.catalogCategoryForPlaybook(result.playbook_id)
      : '';
    if (cat && typeof ctx.setActiveCategory === 'function') {
      await ctx.setActiveCategory(cat, { source: 'plays', selectPlay: false });
    }
    await ctx.setActivePlaybook(result.playbook_id, { source: 'plays', loadPlays: false });
    pbEditMode.value = 'simple';
    pbPushGenerationOutput(`[playbook] Phase 5/5: saved ${result.path || result.playbook_id}.`);
    pbPushGenerationOutput('[playbook] Complete.');
    pbMsg.value = result.generation_attempts > 1
      ? `Created play → ${result.path} (${result.generation_attempts} attempts)`
      : `Created play → ${result.path}`;
    // Community: Start Battle / deploy-after-create is Premium — never auto-pipeline.
    pbForm.autorun = false;
    setTimeout(() => {
      showPlaybookModal.value = false;
      pbMsg.value = '';
    }, 1200);
    return true;
  } catch (e) {
    if (isAbortError(e)) {
      pbPushGenerationOutput('[playbook] Cancelled.');
      pbError.value = '';
      pbMsg.value = 'Generation cancelled.';
      pbAiConflict.value = false;
    } else {
      const msg = e.message || String(e);
      pbPushGenerationOutput(`[playbook] Failed: ${msg}`);
      if (/already exists/i.test(msg) && !pbForm.overwrite) {
        pbAiConflict.value = authoringMode === 'ai';
        pbError.value = 'Playbook ID already exists. Tick “Overwrite” or change the ID, then try again.';
      } else {
        pbAiConflict.value = false;
        pbError.value = 'Generate failed: ' + msg;
      }
    }
    return false;
  } finally {
    pbGenerateAbort = null;
    pbGenerating.value = false;
  }
}

async function submitPlaybookGenerate() {
  pbError.value = '';
  pbMsg.value = '';
  if (!pbWizardCanGenerate()) {
    pbError.value = 'Complete title, play, category, and success/fail rules before creating.';
    return;
  }
  await _runPlaybookGenerateRequest('human');
}

async function submitPlaybookGenerateAi() {
  pbError.value = '';
  pbMsg.value = '';
  pbAiConflict.value = false;
  if (!pbFormCategoryValid() || !pbCustomPurposeValid(pbForm)) {
    pbError.value = pbIsOtherCustom(pbForm)
      ? (
        !pbForm.play_category_label.trim()
          ? 'Enter a hunt name for this mission.'
          : 'Describe what you are testing (at least 15 characters).'
      )
      : 'Enter a hunt name for this mission.';
    return;
  }
  await pbWizardLoadPreset({ force: true });
  const userPurpose = pbForm.play.trim();
  const starter = String(pbPreset.value?.play_starter || '').trim();
  // Always keep the hunter's purpose as the mission brief.
  if (pbIsOtherCustom(pbForm)) {
    if (userPurpose.length < 15) {
      pbError.value = 'Describe what you are testing (at least 15 characters).';
      return;
    }
    pbForm.play = userPurpose;
    if (!pbForm.name.trim()) {
      pbForm.name = (pbForm.play_category_label.trim() || userPurpose.slice(0, 60)).trim();
    }
  } else {
    const playText = starter.length >= 15 ? starter : userPurpose;
    if (playText.length < 15) {
      pbError.value = 'Category preset is missing a play starter (≥15 characters). Enter a hunt name or use Human mode.';
      return;
    }
    pbForm.play = playText;
    if (!pbForm.name.trim()) {
      pbForm.name = (
        pbPreset.value?.title_hint
        || `${pbForm.play_category_l1} ${pbForm.play_category_l2}`.replace(/_/g, ' ')
        || 'New play'
      ).trim();
    }
  }
  pbSuggestId();
  if (!pbWizardNonEmptyRules(pbForm.success_rule_list).length
      || !pbWizardNonEmptyRules(pbForm.failure_rule_list).length) {
    pbError.value = 'Category preset did not supply success/fail rules.';
    return;
  }
  await _runPlaybookGenerateRequest('ai');
}

function pbOnRecordCategoryL1() {
  pbRecordCat.play_category_l2 = pbDefaultL2(pbRecordCat.play_category_l1);
  pbEnsureCategoryDefaults(pbRecordCat);
  if (pbRecordCat.play_category_l1 !== 'mission') pbRecordCat.play_category_label = '';
  pbApplyCategoryToRecord();
  pbSyncJsonFromRecord();
  pbMarkDirty();
}

function pbOnRecordCategoryL2() {
  if (pbRecordCat.play_category_l1 !== 'mission') pbRecordCat.play_category_label = '';
  pbApplyCategoryToRecord();
  pbSyncJsonFromRecord();
  pbMarkDirty();
}

function pbOnRecordCategoryLabelInput() {
  pbApplyCategoryToRecord();
  pbSyncJsonFromRecord();
  pbMarkDirty();
}

function pbApplyCategoryToRecord() {
  if (!pbRecord.value) return;
  const path = pbBuildCategoryPath(pbRecordCat);
  pbRecord.value.play_category_path = path;
  pbRecord.value.play_category = path.join('.');
  pbRecord.value.play_category_label = pbIsOtherCustom(pbRecordCat)
    ? (pbRecordCat.play_category_label || '').trim()
    : '';
}

function pbSyncCategoryFromRecord() {
  if (!pbRecord.value) return;
  const path = pbPathFromRecord(pbRecord.value);
  pbApplyPathToSelectors(pbRecordCat, path);
  pbRecordCat.play_category_label = pbRecord.value.play_category_label || '';
}

function pbPrepareRecordForSave() {
  pbTabError.value = '';
  if (!pbRecord.value && pbEditMode.value === 'json') {
    try {
      pbApplyJsonToRecord();
    } catch (e) {
      pbTabError.value = 'Invalid JSON: ' + e.message;
      return false;
    }
  } else if (pbEditMode.value === 'json') {
    try {
      pbApplyJsonToRecord();
    } catch (e) {
      pbTabError.value = 'Invalid JSON: ' + e.message;
      return false;
    }
  } else {
    pbSyncJsonFromRecord();
    try {
      pbApplyJsonToRecord();
    } catch (e) {
      pbTabError.value = 'Invalid JSON: ' + e.message;
      return false;
    }
  }

  if (pbIsNew.value) {
    const newId = pbSlugify(pbNewId.value || pbRecord.value.playbook_id || '');
    if (!newId) {
      pbTabError.value = 'Enter a playbook ID.';
      return false;
    }
    pbRecord.value.playbook_id = newId;
    if (!String(pbRecord.value.playbook || '').trim()) {
      pbRecord.value.playbook = pretty(newId);
    }
    pbSyncJsonFromRecord();
  }

  pbApplyCategoryToRecord();
  return true;
}

async function pbPersistPlaybookRecord() {
  let result;
  if (pbIsNew.value) {
    result = await api('/api/playbooks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: pbRecord.value }),
    });
    pbIsNew.value = false;
    pbSelectedId.value = result.playbook_id;
  } else {
    const currentId = pbSlugify(pbSelectedId.value || '');
    const nextId = pbSlugify(pbRecord.value.playbook_id || currentId);
    if (!nextId) {
      throw new Error('Playbook ID is required.');
    }
    if (nextId.startsWith('_')) {
      throw new Error('Playbook ID cannot start with underscore.');
    }
    pbRecord.value.playbook_id = nextId;
    if (nextId !== currentId) {
      result = await api(`/api/playbooks/${encodeURIComponent(currentId)}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_playbook_id: nextId, data: pbRecord.value }),
      });
      pbSelectedId.value = result.playbook_id || nextId;
      const suiteN = Array.isArray(result.moved_suites) ? result.moved_suites.length : 0;
      const intelN = Array.isArray(result.moved_intel) ? result.moved_intel.length : 0;
      if (suiteN || intelN) {
        pbTabMsg.value = (
          `Renamed ${currentId} → ${pbSelectedId.value}`
          + (suiteN ? ` · ${suiteN} suite(s)` : '')
          + (intelN ? ` · ${intelN} intel file(s)` : '')
        );
      }
    } else {
      result = await api(`/api/playbooks/${encodeURIComponent(currentId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: pbRecord.value }),
      });
    }
  }
  pbDirty.value = false;
  pbSetCategoryBaseline(pbRecord.value);
  allPlaybooks.value = await api('/api/playbooks');
  await pbLoadCatalog(result.playbook_id);
  if (result.playbook_id) {
    await ctx.setActivePlaybook(result.playbook_id, { source: 'plays', loadPlays: false });
  }
  return result;
}

async function pbRegeneratePlaybookViaApi(opts = {}) {
  if (!pbRecord.value || pbIsNew.value) {
    throw new Error('Cannot regenerate an unsaved playbook.');
  }

  const play = String(pbRecord.value.play || '').trim();
  const categoryPath = pbBuildCategoryPath(pbRecordCat);
  if (!categoryPath[0] || !categoryPath[1]) {
    throw new Error('Select a complete category before regenerating.');
  }
  if (pbIsOtherCustom(pbRecordCat) && !pbRecordCat.play_category_label.trim()) {
    throw new Error('Enter a custom category label before regenerating.');
  }
  if (play.length < 15) {
    throw new Error('Play must be at least 15 characters before regenerating.');
  }

  pbRegenerating.value = true;
  pbGenerateAbort = new AbortController();
  const signal = pbGenerateAbort.signal;
  pbTabError.value = '';
  pbResetGenerationOutput(`Regenerating play ${pbSelectedId.value || pbRecord.value.playbook_id || ''}`.trim());
  try {
    const playbook_id = pbSelectedId.value || pbRecord.value.playbook_id;
    const stopWords = pbSuccessMarkersDisplay(pbRecord.value);
    // Full Create-from-play AI rewrite: do not lock prior attack_objective / delivery /
    // directives. Empty triggers let the API adopt category presets (Create behavior).
    // Exact canary is a structural rail (like prompt_template) - re-send so post-process
    // re-stamps objective, triggers, response_marker, and stop_words.
    const preservedExactCanary = pbExactCanaryFromRecord(pbRecord.value);
    let triggerTexts = { success_rules: '', failure_rules: '' };
    // Operator prompt envelope is a structural rail - keep across rewrite.
    const existingCfg = pbPlaybookConfigFromRecord(pbRecord.value);
    const preservedEnvelope = {
      prompt_template: existingCfg.prompt_template || '',
      prompt_task: existingCfg.prompt_task || '',
      prompt_format: existingCfg.prompt_format || '',
    };
    let playbookConfig = pbPlaybookConfigApiPayload(preservedEnvelope);

    if (opts.useCategoryPreset) {
      pbPushGenerationOutput('[playbook] Loading category preset for new attack surface…');
      try {
        const l1 = pbRecordCat.play_category_l1;
        const l2 = pbRecordCat.play_category_l2;
        const q = pbRecordCat.play_category_label.trim()
          ? `?play_category_label=${encodeURIComponent(pbRecordCat.play_category_label.trim())}`
          : '';
        const preset = await api(
          `/api/plays/category-presets/${encodeURIComponent(l1)}/${encodeURIComponent(l2)}${q}`,
          { signal },
        );
        if ((preset.success_rules || []).length) {
          triggerTexts = {
            ...triggerTexts,
            success_rules: preset.success_rules.map(String).join('\n'),
          };
          pbSimpleSuccessRules.value = preset.success_rules.slice();
        }
        if ((preset.failure_rules || []).length) {
          triggerTexts = {
            ...triggerTexts,
            failure_rules: preset.failure_rules.map(String).join('\n'),
          };
          pbSimpleFailureRules.value = preset.failure_rules.slice();
        }
        // Fresh preset rails + preserved prompt envelope (never drop template on rebuild).
        const freshCfg = { ...preservedEnvelope };
        if (preset.delivery_constraints) {
          freshCfg.delivery_constraints = preset.delivery_constraints;
          freshCfg.apply_delivery_to_seeds = true;
        } else {
          freshCfg.delivery_constraints = '';
          freshCfg.apply_delivery_to_seeds = false;
        }
        if (preset.standard_action) {
          freshCfg.standard_action = preset.standard_action;
        } else {
          freshCfg.standard_action = '';
        }
        playbookConfig = pbPlaybookConfigApiPayload(freshCfg);
        pbApplySimpleRulesToRecord();
      } catch (presetErr) {
        pbPushGenerationOutput(
          `[playbook] Preset load skipped: ${presetErr.message || presetErr}`,
        );
      }
    } else {
      pbPushGenerationOutput(
        '[playbook] Full AI rewrite from play hypothesis (Create-with-AI + overwrite; '
        + 'prior attack_objective / escalate / delivery are not re-locked; '
        + 'prompt_template envelope and exact canary are kept).',
      );
    }
    if (preservedExactCanary) {
      pbPushGenerationOutput(
        `[playbook] Keeping exact canary (${preservedExactCanary.length} chars) across rebuild.`,
      );
    }

    pbPushGenerationOutput(`[playbook] Phase 1/5: preparing play hypothesis and category (${categoryPath.join(' / ')}).`);
    pbPushGenerationOutput('[playbook] Phase 2/5: loading target recon context if available.');
    pbPushGenerationOutput(
      '[playbook] Phase 3/5: Mission planning in progress..',
    );
    const heartbeat = pbStartGenerationHeartbeat('Mission planning');
    let result;
    try {
      const body = {
        name: String(pbRecord.value.playbook || playbook_id).trim(),
        play,
        play_category_path: categoryPath,
        play_category_label: pbRecordCat.play_category_label.trim(),
        success_rules: triggerTexts.success_rules,
        failure_rules: triggerTexts.failure_rules,
        stop_words: stopWords,
        playbook_id,
        overwrite: true,
        authoring_mode: 'ai',
        rebuild_from_objective: false,
        site: site.value || '',
        component: component.value || '',
      };
      if (preservedExactCanary) body.exact_canary = preservedExactCanary;
      if (playbookConfig) body.playbook_config = playbookConfig;
      result = await api('/api/playbooks/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal,
        body: JSON.stringify(body),
      });
    } finally {
      clearInterval(heartbeat);
    }
    pbPushGenerationOutput(`[playbook] Mission planning complete after ${result.generation_attempts || 1} attempt(s).`);
    pbPushGenerationOutput('[playbook] Phase 4/5: reloading saved playbook and refreshing catalog.');
    const row = await api(`/api/playbooks/${encodeURIComponent(result.playbook_id)}`);
    pbRecord.value = row.data;
    pbSyncCategoryFromRecord();
    pbSetCategoryBaseline(pbRecord.value);
    pbSyncConfigFormFromRecord(pbRecord.value);
    pbSyncSimpleRulesFromRecord();
    pbSyncJsonFromRecord();
    pbDirty.value = false;
    allPlaybooks.value = await api('/api/playbooks');
    await pbLoadCatalog(result.playbook_id);
    await ctx.setActivePlaybook(result.playbook_id, { source: 'plays', loadPlays: false });
    pbPushGenerationOutput(`[playbook] Phase 5/5: saved ${result.path || result.playbook_id}.`);
    if (Array.isArray(result.invalidated_test_suites) && result.invalidated_test_suites.length) {
      pbPushGenerationOutput(
        `[playbook] Invalidated ${result.invalidated_test_suites.length} cached probe suite(s) `
        + '(run Forge again before Attack).',
      );
    } else {
      pbPushGenerationOutput(
        '[playbook] Complete. Forge before Attack (no cached suites were on disk).',
      );
    }
    return result;
  } catch (e) {
    if (isAbortError(e)) {
      pbPushGenerationOutput('[playbook] Cancelled.');
      const cancelled = new Error('Playbook generation cancelled');
      cancelled.name = 'AbortError';
      throw cancelled;
    }
    pbPushGenerationOutput(`[playbook] Failed: ${e.message || e}`);
    if (pbSelectedId.value) {
      const row = await api(`/api/playbooks/${encodeURIComponent(pbSelectedId.value)}`);
      pbRecord.value = row.data;
      pbSyncCategoryFromRecord();
      pbSetCategoryBaseline(pbRecord.value);
      pbSyncConfigFormFromRecord(pbRecord.value);
      pbSyncSimpleRulesFromRecord();
      pbSyncJsonFromRecord();
    } else {
      pbSyncCategoryFromRecord();
      pbSetCategoryBaseline(pbRecord.value);
    }
    throw e;
  } finally {
    pbGenerateAbort = null;
    pbRegenerating.value = false;
  }
}

async function pbRegeneratePlaybookForCategoryChange() {
  pbTabMsg.value = 'Regenerating playbook for new category…';
  const result = await pbRegeneratePlaybookViaApi({ useCategoryPreset: true });
  pbTabMsg.value = result.generation_attempts > 1
    ? `Saved with regenerated play → ${result.path || result.playbook_id} (${result.generation_attempts} attempts)`
    : `Saved with regenerated play → ${result.path || result.playbook_id}`;
}

function pbFormatPlaybookApiError(err) {
  const raw = String((err && err.message) || err || '').trim();
  if (!raw) return 'Playbook request failed.';
  try {
    const parsed = JSON.parse(raw);
    const detail = parsed && parsed.detail !== undefined ? parsed.detail : parsed;
    if (detail && typeof detail === 'object') {
      const rows = Array.isArray(detail.errors) ? detail.errors : [];
      const msgs = rows
        .map((row) => (row && (row.message || row.code)) || '')
        .map((s) => String(s).trim())
        .filter(Boolean);
      if (msgs.length) return msgs.join('; ');
      if (detail.message) return String(detail.message);
      if (detail.code) return String(detail.code);
    }
    if (typeof detail === 'string' && detail.trim()) return detail.trim();
  } catch (_) {
    /* plain text */
  }
  return raw;
}

async function pbRegeneratePlaybook() {
  pbTabMsg.value = '';
  if (!pbPrepareRecordForSave()) return;
  if (pbIsNew.value) {
    pbTabError.value = 'Save the mission before regenerating.';
    return;
  }
  pbSaving.value = true;
  try {
    // No pre-save strip: failed regen leaves the previous file intact. Generate
    // overwrites with a full Create-with-AI rewrite from the current play.
    pbTabMsg.value = 'Rewriting mission from mission hypothesis (Create with AI)…';
    const result = await pbRegeneratePlaybookViaApi();
    pbTabMsg.value = result.generation_attempts > 1
      ? `Rewrote from mission → ${result.path || result.playbook_id} (${result.generation_attempts} attempts). Re-Generate probes before Run.`
      : `Rewrote from mission → ${result.path || result.playbook_id}. Re-Generate probes before Run.`;
  } catch (e) {
    if (isAbortError(e)) {
      pbTabError.value = '';
      pbTabMsg.value = 'Regenerate cancelled.';
    } else {
      pbTabError.value = pbFormatPlaybookApiError(e);
    }
  } finally {
    pbSaving.value = false;
  }
}

function pbFormCategoryValid() {
  if (!pbForm.play_category_l1 || !pbForm.play_category_l2) return false;
  if (pbIsOtherCustom(pbForm) && !pbForm.play_category_label.trim()) return false;
  return true;
}

function pbSlugify(text) {
  return (text || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64);
}

function pbSuggestedPlaybookId(form = pbForm) {
  // Mission file ids are the hunt-name slug only (not taxonomy path prefixes).
  return pbSlugify(form.play_category_label || form.name || '') || 'mission';
}

function pbSuggestId() {
  pbForm.playbook_id = pbSuggestedPlaybookId(pbForm);
}

// --- Missions tab (CRUD) ---
const pbCatalog = ref([]);
const pbSelectedId = ref('');
const pbRecord = ref(null);
const pbJsonText = ref('');
const pbEditMode = ref('simple');
const pbDirty = ref(false);
const pbIsNew = ref(false);
const pbLoading = ref(false);
const pbSaving = ref(false);
const pbDeleting = ref(false);
const pbTabError = ref('');
const pbTabMsg = ref('');
const pbNewId = ref('');
const pbSimpleSuccessRules = ref(['']);
const pbSimpleFailureRules = ref(['']);

const _savedPbResultsLayout = localStorage.getItem('genbounty_missions_results_layout');
const pbResultsLayout = ref(
  _savedPbResultsLayout === 'maximized' || _savedPbResultsLayout === 'minimized'
    ? _savedPbResultsLayout
    : 'normal'
);

function persistPbResultsLayout() {
  localStorage.setItem('genbounty_missions_results_layout', pbResultsLayout.value);
}

function togglePbResultsMinimize() {
  pbResultsLayout.value = pbResultsLayout.value === 'minimized' ? 'normal' : 'minimized';
  persistPbResultsLayout();
}

function togglePbResultsMaximize() {
  pbResultsLayout.value = pbResultsLayout.value === 'maximized' ? 'normal' : 'maximized';
  persistPbResultsLayout();
}

const pbResultsMaximizedActive = computed(
  () => pbResultsLayout.value === 'maximized'
);

const PB_EXPANDED_GROUPS_KEY = 'genbounty_pb_expanded_groups';
const pbExpandedGroups = ref({});

function pbLoadExpandedGroups() {
  try {
    const raw = localStorage.getItem(PB_EXPANDED_GROUPS_KEY);
    if (raw) pbExpandedGroups.value = JSON.parse(raw) || {};
  } catch {
    pbExpandedGroups.value = {};
  }
}

function pbPersistExpandedGroups() {
  localStorage.setItem(PB_EXPANDED_GROUPS_KEY, JSON.stringify(pbExpandedGroups.value));
}

function pbGroupKey(group) {
  return group?.key || group?.label || 'uncategorized';
}

function pbPlaybookGroupKey(row) {
  if (!row) return 'uncategorized';
  if (row.group_key) return row.group_key;
  if (Array.isArray(row.play_category_path) && row.play_category_path[0]) {
    return row.play_category_path[0];
  }
  return row.play_category_l1_label || 'uncategorized';
}

function pbIsGroupCollapsed(group) {
  return !pbExpandedGroups.value[pbGroupKey(group)];
}

function pbToggleGroup(group) {
  const key = pbGroupKey(group);
  const next = { ...pbExpandedGroups.value };
  if (next[key]) delete next[key];
  else next[key] = true;
  pbExpandedGroups.value = next;
  pbPersistExpandedGroups();
}

function pbExpandGroup(key) {
  if (!key || pbExpandedGroups.value[key]) return;
  pbExpandedGroups.value = { ...pbExpandedGroups.value, [key]: true };
  pbPersistExpandedGroups();
}

function pbPlayRows() {
  return pbCatalog.value.filter(
    r => r.id && !r.id.startsWith('_') && !String(r.filename || '').startsWith('_')
  );
}

const pbCatalogGrouped = computed(() => {
  const rows = pbPlayRows();
  const byL1 = new Map();
  for (const row of rows) {
    const key = row.group_key || row.play_category_l1_label || 'uncategorized';
    const label = row.play_category_l1_label || row.group_label || row.play_category_display || 'Uncategorized';
    if (!byL1.has(key)) byL1.set(key, { label, key, items: [] });
    byL1.get(key).items.push(row);
  }
  const groups = [];
  for (const l1 of playCategoryTree.value) {
    const g = byL1.get(l1.id);
    if (g?.items.length) groups.push(g);
    byL1.delete(l1.id);
  }
  for (const [, g] of [...byL1.entries()].sort((a, b) => a.label.localeCompare(b.label))) {
    groups.push(g);
  }
  return groups;
});

const playbooksGrouped = computed(() => pbCatalogGrouped.value);

const genCategoryOptions = computed(() => (
  playbooksGrouped.value.map((group) => ({
    key: group.key,
    label: group.label,
    count: (group.items || []).length,
  }))
));

const activeCategoryOptions = computed(() => genCategoryOptions.value);

const activePlaybookOptions = computed(() => {
  const rows = activeCategoryL1.value
    ? (playbooksGrouped.value.find((g) => g.key === activeCategoryL1.value)?.items || [])
    : pbPlayRows();
  return rows.map((row) => ({
    id: row.id,
    label: row.playbook || row.id,
  })).sort((a, b) => String(a.label).localeCompare(String(b.label)));
});

const activeCategoryLabel = computed(() => {
  const key = activeCategoryL1.value;
  if (!key) return '-';
  const hit = activeCategoryOptions.value.find((g) => g.key === key);
  if (hit?.label) return hit.label;
  return pretty(key);
});

const activePlaybookLabel = computed(() => {
  const id = activePlaybookId.value;
  if (!id) return '-';
  const fromOpts = activePlaybookOptions.value.find((r) => _samePlaybookId(r.id, id));
  if (fromOpts?.label) return fromOpts.label;
  const row = pbPlayRows().find((r) => _samePlaybookId(r.id, id) || _samePlaybookId(r.playbook_id, id));
  if (row?.playbook) return row.playbook;
  return pretty(id);
});

function openHeaderScopeSelect(which) {
  const id = which === 'playbook' ? 'header-playbook-select' : 'header-category-select';
  const sel = document.getElementById(id);
  if (!(sel instanceof HTMLSelectElement)) return;
  sel.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  sel.classList.add('header-scope-flash');
  window.setTimeout(() => sel.classList.remove('header-scope-flash'), 1400);
  try {
    sel.focus({ preventScroll: true });
  } catch (_) {
    sel.focus();
  }
  if (typeof sel.showPicker === 'function') {
    try {
      sel.showPicker();
    } catch (_) {
      /* showPicker may reject if not directly tied to a gesture in some browsers */
    }
  }
}

const genPlayOptions = computed(() => {
  const key = activeCategoryL1.value || gen.categoryL1;
  const group = playbooksGrouped.value.find((g) => g.key === key);
  return group?.items || [];
});

function _samePlaybookId(a, b) {
  return String(a || '').replace(/-/g, '_') === String(b || '').replace(/-/g, '_');
}

function catalogIdForPlaybook(raw) {
  const want = String(raw || '').trim();
  if (!want) return '';
  const hit = pbPlayRows().find((row) => _samePlaybookId(row.id, want) || _samePlaybookId(row.playbook_id, want));
  return hit?.id || '';
}

function catalogHasPlaybooks() {
  return pbPlayRows().length > 0 || (allPlaybooks.value || []).length > 0;
}

function firstCatalogPlaybookId() {
  return (
    activePlaybookOptions.value[0]?.id
    || pbPlayRows()[0]?.id
    || (allPlaybooks.value || [])[0]
    || ''
  );
}

/** Resolve a playbook id to one that exists in the catalog (never keep renamed/deleted ghosts). */
function resolveExistingPlaybookId(raw, { allowEmpty = true } = {}) {
  const resolved = catalogIdForPlaybook(raw);
  if (resolved) return resolved;
  if (!String(raw || '').trim()) return allowEmpty ? '' : firstCatalogPlaybookId();
  // Catalog loaded but id missing (e.g. localStorage still has custom_hunt after rename).
  if (catalogHasPlaybooks()) return firstCatalogPlaybookId();
  // Catalog not loaded yet - keep raw only transiently.
  return String(raw || '').trim();
}

function testFileSlugForPlaybook(files, raw) {
  const want = String(raw || '').trim();
  if (!want) return '';
  const hit = (files || []).find((f) => _samePlaybookId(f.slug, want));
  return hit?.slug || '';
}

function catalogCategoryForPlaybook(raw) {
  const id = catalogIdForPlaybook(raw) || String(raw || '').trim();
  if (!id || !playbooksGrouped.value.length) return '';
  const group = playbooksGrouped.value.find((g) => (
    (g.items || []).some((row) => _samePlaybookId(row.id, id))
  ));
  return group?.key || '';
}

function syncGenCategoryFromPlaybook() {
  if (!gen.playbook || !playbooksGrouped.value.length) return;
  const key = catalogCategoryForPlaybook(gen.playbook);
  if (key) gen.categoryL1 = key;
}

function mirrorActiveCategory(key) {
  const next = String(key || '').trim();
  activeCategoryL1.value = next;
  gen.categoryL1 = next;
  ctx.run.category = next;
  ctx.tmCategoryL1.value = next;
}

function ensureGenPlayInCategory() {
  if (!genCategoryOptions.value.length) {
    mirrorActiveCategory('');
    gen.playbook = '';
    return;
  }
  if (activePlaybookId.value) {
    gen.playbook = resolveExistingPlaybookId(activePlaybookId.value, { allowEmpty: true });
    if (gen.playbook && !_samePlaybookId(gen.playbook, activePlaybookId.value)) {
      activePlaybookId.value = gen.playbook;
    }
    syncGenCategoryFromPlaybook();
    if (gen.categoryL1) mirrorActiveCategory(gen.categoryL1);
    else if (!activeCategoryL1.value) mirrorActiveCategory(genCategoryOptions.value[0].key);
    return;
  }
  if (!activeCategoryL1.value || !genCategoryOptions.value.some((g) => g.key === activeCategoryL1.value)) {
    syncGenCategoryFromPlaybook();
    if (gen.categoryL1) mirrorActiveCategory(gen.categoryL1);
    else mirrorActiveCategory(genCategoryOptions.value[0].key);
  } else {
    gen.categoryL1 = activeCategoryL1.value;
  }
  const plays = genPlayOptions.value;
  if (!plays.length) {
    gen.playbook = '';
    return;
  }
  if (!plays.some((row) => _samePlaybookId(row.id, gen.playbook))) {
    gen.playbook = plays[0].id;
  }
}

function onGenCategoryL1Change() {
  ctx.setActiveCategory(gen.categoryL1, { source: 'generate' });
}

function onGenPlaybookChange(event) {
  ctx.setActivePlaybook(event?.target?.value || '', { source: 'generate' });
}

function pbSummaryForRunFile(file) {
  if (!file) return null;
  return pbCatalog.value.find((row) => (
    _samePlaybookId(row.id, file.slug) ||
    _samePlaybookId(row.playbook_id, file.slug) ||
    _samePlaybookId(String(row.filename || '').replace(/\.json$/i, ''), file.slug)
  )) || null;
}

function groupTestFilesByCategory(files) {
  const groups = new Map();
  for (const file of files || []) {
    const summary = pbSummaryForRunFile(file);
    const key = summary?.group_key || summary?.play_category_path?.[0] || 'uncategorized';
    const label = summary?.group_label || summary?.play_category_l1_label || summary?.play_category_display || 'Uncategorized';
    if (!groups.has(key)) {
      groups.set(key, { key, label, playbooks: [] });
    }
    groups.get(key).playbooks.push({
      slug: file.slug,
      label: summary?.playbook || file.label || file.slug,
    });
  }
  const treeOrder = new Map(
    (playCategoryTree.value || []).map((l1, idx) => [l1.id, idx]),
  );
  return [...groups.values()]
    .map((group) => ({
      ...group,
      playbooks: group.playbooks.sort((a, b) => a.label.localeCompare(b.label)),
    }))
    .sort((a, b) => {
      const ai = treeOrder.has(a.key) ? treeOrder.get(a.key) : Number.MAX_SAFE_INTEGER;
      const bi = treeOrder.has(b.key) ? treeOrder.get(b.key) : Number.MAX_SAFE_INTEGER;
      if (ai !== bi) return ai - bi;
      return a.label.localeCompare(b.label);
    });
}

const runCategoryOptions = computed(() => groupTestFilesByCategory(runTestFiles.value));

const runSelectedCategory = computed(() => (
  runCategoryOptions.value.find((group) => group.key === ctx.run.category) || null
));

const runPlayOptions = computed(() => runSelectedCategory.value?.playbooks || []);

function syncRunCategoryFromPlaybook() {
  if (!ctx.run.playbook || !runCategoryOptions.value.length) return;
  const group = runCategoryOptions.value.find((g) => (
    (g.playbooks || []).some((p) => p.slug === ctx.run.playbook)
  ));
  if (group) ctx.run.category = group.key;
}

function ensureRunPlayInCategory() {
  if (ctx.run.scope === 'category') {
    if (!ctx.run.category && runCategoryOptions.value.length) {
      ctx.run.category = runCategoryOptions.value[0].key;
    }
    return;
  }
  if (activePlaybookId.value) {
    const slug = testFileSlugForPlaybook(runTestFiles.value, activePlaybookId.value);
    if (slug) {
      ctx.run.playbook = slug;
      syncRunCategoryFromPlaybook();
      if (typeof ctx.runOnTestFileChange === 'function') {
        ctx.runOnTestFileChange(true);
      }
      return;
    }
    ctx.run.playbook = activePlaybookId.value;
    runStrategies.value = [];
    ctx.run.strategy = '';
    ctx.runArtifactStatus.value = [];
    ctx.runUploadWarning.value = '';
    if (!ctx.run.category && runCategoryOptions.value.length) {
      ctx.run.category = runCategoryOptions.value[0].key;
    }
    return;
  }
  if (!runCategoryOptions.value.length) {
    ctx.run.category = '';
    ctx.run.playbook = '';
    return;
  }
  if (!ctx.run.category || !runCategoryOptions.value.some((g) => g.key === ctx.run.category)) {
    syncRunCategoryFromPlaybook();
    if (!ctx.run.category) ctx.run.category = runCategoryOptions.value[0].key;
  }
  const plays = runPlayOptions.value;
  if (!plays.length) {
    ctx.run.playbook = '';
    return;
  }
  if (!plays.some((p) => p.slug === ctx.run.playbook)) {
    ctx.run.playbook = plays[0].slug;
    if (typeof ctx.runOnTestFileChange === 'function') {
      ctx.runOnTestFileChange(true);
    }
  }
}

function onRunCategoryL1Change() {
  ctx.setActiveCategory(ctx.run.category, { source: 'run' });
}

function onRunPlaybookChange() {
  ctx.setActivePlaybook(ctx.run.playbook, { source: 'run' });
}

function pbFormatDate(ts) {
  if (!ts) return '-';
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return '-';
  }
}

function pbResetEditor() {
  pbRecordCategoryBaseline.value = '';
  pbSelectedId.value = '';
  pbRecord.value = null;
  pbJsonText.value = '';
  pbDirty.value = false;
  pbIsNew.value = false;
  pbNewId.value = '';
  pbEditMode.value = 'simple';
  pbTabError.value = '';
}

async function pbLoadCatalog(selectId = '') {
  pbTabError.value = '';
  try {
    pbCatalog.value = await api('/api/playbooks/manage');
    const want = catalogIdForPlaybook(selectId || activePlaybookId.value);
    if (want) {
      const hit = pbCatalog.value.find((p) => _samePlaybookId(p.id, want));
      if (hit) await pbSelectPlaybook(hit.id);
    }
  } catch (e) {
    pbTabError.value = String(e.message || e);
  }
}

function pbSyncJsonFromRecord() {
  if (!pbRecord.value) {
    pbJsonText.value = '';
    return;
  }
  pbJsonText.value = JSON.stringify(pbRecord.value, null, 2);
}

function pbApplyJsonToRecord() {
  const parsed = JSON.parse(pbJsonText.value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Playbook JSON must be an object');
  }
  pbRecord.value = parsed;
  pbSyncCategoryFromRecord();
}

function pbMarkDirty() {
  pbDirty.value = true;
  pbTabMsg.value = '';
}

async function pbSelectPlaybook(id) {
  if (pbDirty.value && !confirm('Discard unsaved playbook changes?')) return false;
  pbTabError.value = '';
  pbTabMsg.value = '';
  pbLoading.value = true;
  const keepMode = pbSelectedId.value === id && !pbIsNew.value ? pbEditMode.value : 'simple';
  pbIsNew.value = false;
  pbNewId.value = '';
  try {
    const row = await api(`/api/playbooks/${encodeURIComponent(id)}`);
    pbSelectedId.value = row.id;
    const summary = pbCatalog.value.find(p => p.id === row.id);
    pbExpandGroup(pbPlaybookGroupKey(summary));
    pbRecord.value = row.data;
    pbSyncCategoryFromRecord();
    pbSetCategoryBaseline(pbRecord.value);
    pbSyncConfigFormFromRecord(pbRecord.value);
    pbSyncSimpleRulesFromRecord();
    pbSyncJsonFromRecord();
    pbDirty.value = false;
    pbEditMode.value = keepMode === 'overview' || keepMode === 'json' || keepMode === 'simple'
      ? keepMode
      : 'simple';
    if (!ctx._skipActivePlaybookSync) {
      await ctx.setActivePlaybook(row.id, { source: 'plays', loadPlays: false });
    }
    return true;
  } catch (e) {
    pbTabError.value = String(e.message || e);
    return false;
  } finally {
    pbLoading.value = false;
  }
}

async function pbStartBlankPlaybook() {
  if (pbDirty.value && !isConfirmArmed('pb-blank')) {
    armConfirm('pb-blank');
    return;
  }
  clearConfirmArmed('pb-blank');
  pbTabError.value = '';
  pbTabMsg.value = '';
  pbLoading.value = true;
  try {
    const tpl = await api('/api/playbooks/template');
    const data = JSON.parse(JSON.stringify(tpl.template || {}));
    delete data._comment;
    const stem = 'custom_playbook';
    data.playbook_id = stem;
    data.playbook = 'Custom Playbook';
    pbSelectedId.value = '';
    pbNewId.value = stem;
    pbRecord.value = data;
    pbSyncJsonFromRecord();
    pbDirty.value = true;
    pbIsNew.value = true;
    pbEditMode.value = 'json';
  } catch (e) {
    pbTabError.value = String(e.message || e);
  } finally {
    pbLoading.value = false;
  }
}

function pbOnOverviewInput() {
  pbApplyCategoryToRecord();
  pbSyncJsonFromRecord();
  pbMarkDirty();
}

function pbLinesFromList(list) {
  return Array.isArray(list) ? list.join('\n') : '';
}

function pbListFromLines(text) {
  return String(text || '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);
}

function pbCommaListFromArray(list) {
  return Array.isArray(list) ? list.join(', ') : '';
}

function pbArrayFromCommaList(text) {
  return String(text || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

function pbSetCategoryLines(cat, field, text) {
  cat[field] = pbListFromLines(text);
  pbOnOverviewInput();
}

function pbSetCategoryTriggers(cat, side, text) {
  if (!cat.attack_triggers || typeof cat.attack_triggers !== 'object') {
    cat.attack_triggers = {};
  }
  cat.attack_triggers[side] = pbListFromLines(text);
  pbOnOverviewInput();
}

function pbSetMethodologyLines(text) {
  if (!pbRecord.value) return;
  pbRecord.value.evaluation_methodology = pbListFromLines(text);
  pbOnOverviewInput();
}

function pbTermListDisplay(record, field) {
  const raw = record?.[field];
  if (Array.isArray(raw)) return pbCommaListFromArray(raw);
  if (typeof raw === 'string' && raw.trim()) return raw.trim();
  return '';
}

function pbSetTermList(field, text) {
  if (!pbRecord.value) return;
  const words = pbArrayFromCommaList(text);
  if (words.length) {
    pbRecord.value[field] = words;
  } else {
    delete pbRecord.value[field];
  }
  pbOnOverviewInput();
}

function pbSuccessMarkersDisplay(record) {
  return pbTermListDisplay(record, 'stop_words');
}

/** Recover Plan Mission exact canary from stamped fields (marker → objective → rule → stop). */
function pbExactCanaryFromRecord(record) {
  if (!record || typeof record !== 'object') return '';
  const cfg = record.playbook_config || {};
  const oracles = ((cfg.assessment || {}).oracles) || [];
  for (const oracle of oracles) {
    if (!oracle || typeof oracle !== 'object') continue;
    if (String(oracle.type || '').trim() !== 'response_marker') continue;
    const marker = String(oracle.marker || '').trim();
    if (marker) return marker;
  }
  const objective = String(((cfg.generation || {}).attack_objective) || '').trim();
  const objPrefix = 'Emit exactly this string:';
  if (objective.toLowerCase().startsWith(objPrefix.toLowerCase())) {
    const recovered = objective.slice(objPrefix.length).trim();
    if (recovered) return recovered;
  }
  const successPrefix = "Response contains the exact string: '";
  const cats = Array.isArray(record.categories) ? record.categories : [];
  for (const cat of cats) {
    const lines = (((cat || {}).attack_triggers) || {}).exploited_if || [];
    for (const line of lines) {
      const text = String(line || '').trim();
      if (text.startsWith(successPrefix) && text.endsWith("'")) {
        const recovered = text.slice(successPrefix.length, -1);
        if (recovered) return recovered;
      }
    }
  }
  const stops = Array.isArray(record.stop_words) ? record.stop_words : [];
  if (stops.length === 1) {
    const sole = String(stops[0] || '').trim();
    if (sole) return sole;
  }
  return '';
}

function pbSetSuccessMarkers(text) {
  pbSetTermList('stop_words', text);
}

function pbAddCategory() {
  if (!pbRecord.value) return;
  if (!Array.isArray(pbRecord.value.categories)) pbRecord.value.categories = [];
  const n = pbRecord.value.categories.length + 1;
  pbRecord.value.schema_version = 3;
  pbRecord.value.categories.push({
    id: `PLAY${String(n).padStart(2, '0')}`,
    parent_id: `PLAY${String(n).padStart(2, '0')}`,
    channel: 'text',
    name: '',
    focus: '',
    description: '',
    attack_triggers: { exploited_if: [''], mitigated_if: [''] },
    delivery_methods: ['text_direct'],
    category_vectors: [],
    forensic_evidence_required: '',
  });
  pbOnOverviewInput();
}

function pbRemoveCategory(index) {
  if (!pbRecord.value?.categories) return;
  const key = `pb-cat-${index}`;
  if (!isConfirmArmed(key)) {
    armConfirm(key);
    return;
  }
  clearConfirmArmed(key);
  pbRecord.value.categories.splice(index, 1);
  pbOnOverviewInput();
}

function pbAddSeverityTier() {
  if (!pbRecord.value) return;
  if (!Array.isArray(pbRecord.value.severity_tiers)) pbRecord.value.severity_tiers = [];
  pbRecord.value.severity_tiers.push({
    level: '',
    status: '',
    criteria: '',
    remediation_urgency: '',
  });
  pbOnOverviewInput();
}

function pbRemoveSeverityTier(index) {
  if (!pbRecord.value?.severity_tiers) return;
  const key = `pb-tier-${index}`;
  if (!isConfirmArmed(key)) {
    armConfirm(key);
    return;
  }
  clearConfirmArmed(key);
  pbRecord.value.severity_tiers.splice(index, 1);
  pbOnOverviewInput();
}

function pbSchemaKeys() {
  const schema = pbRecord.value?.required_output_schema;
  if (!schema || typeof schema !== 'object') return [];
  return Object.keys(schema);
}

function pbEnsureSchema() {
  if (!pbRecord.value) return;
  if (!pbRecord.value.required_output_schema || typeof pbRecord.value.required_output_schema !== 'object') {
    pbRecord.value.required_output_schema = {};
  }
}

function pbAddSchemaField() {
  pbEnsureSchema();
  const base = 'field';
  let key = base;
  let i = 1;
  while (key in pbRecord.value.required_output_schema) {
    key = `${base}_${i++}`;
  }
  pbRecord.value.required_output_schema[key] = 'string';
  pbOnOverviewInput();
}

function pbRemoveSchemaField(key) {
  if (!pbRecord.value?.required_output_schema) return;
  const armKey = `pb-schema-${key}`;
  if (!isConfirmArmed(armKey)) {
    armConfirm(armKey);
    return;
  }
  clearConfirmArmed(armKey);
  delete pbRecord.value.required_output_schema[key];
  pbOnOverviewInput();
}

function pbOnJsonInput() {
  pbMarkDirty();
}

function pbSyncSimpleRulesFromRecord() {
  const cats = pbRecord.value?.categories || [];
  const first = cats.find((c) => c && typeof c === 'object') || {};
  const triggers = first.attack_triggers || {};
  const success = Array.isArray(triggers.exploited_if) ? triggers.exploited_if.map(String) : [];
  const failure = Array.isArray(triggers.mitigated_if) ? triggers.mitigated_if.map(String) : [];
  pbSimpleSuccessRules.value = success.length ? success.slice() : [''];
  pbSimpleFailureRules.value = failure.length ? failure.slice() : [''];
}

function pbApplySimpleRulesToRecord() {
  if (!pbRecord.value) return;
  const success = pbWizardNonEmptyRules(pbSimpleSuccessRules.value);
  const failure = pbWizardNonEmptyRules(pbSimpleFailureRules.value);
  if (!Array.isArray(pbRecord.value.categories)) pbRecord.value.categories = [];
  for (const cat of pbRecord.value.categories) {
    if (!cat || typeof cat !== 'object') continue;
    if (!cat.attack_triggers || typeof cat.attack_triggers !== 'object') {
      cat.attack_triggers = {};
    }
    cat.attack_triggers.exploited_if = success.slice();
    cat.attack_triggers.mitigated_if = failure.slice();
  }
}

function pbOnSimpleRulesInput() {
  pbApplySimpleRulesToRecord();
  pbOnOverviewInput();
}

function pbTriggersTextFromRecord() {
  const cats = pbRecord.value?.categories || [];
  const first = cats.find((c) => c && typeof c === 'object') || {};
  const triggers = first.attack_triggers || {};
  const success = Array.isArray(triggers.exploited_if) ? triggers.exploited_if : [];
  const failure = Array.isArray(triggers.mitigated_if) ? triggers.mitigated_if : [];
  return {
    success_rules: success.map(String).filter((s) => s.trim()).join('\n'),
    failure_rules: failure.map(String).filter((s) => s.trim()).join('\n'),
  };
}

function pbSwitchEditMode(mode) {
  if (mode === pbEditMode.value) return;
  if (mode === 'overview' || mode === 'simple') {
    try {
      if (pbEditMode.value === 'json') pbApplyJsonToRecord();
      pbTabError.value = '';
      pbSyncSimpleRulesFromRecord();
    } catch (e) {
      pbTabError.value = 'Fix JSON before switching: ' + e.message;
      return;
    }
  } else {
    if (pbEditMode.value === 'simple') pbApplySimpleRulesToRecord();
    pbSyncJsonFromRecord();
  }
  pbEditMode.value = mode;
}

async function pbSavePlaybook() {
  pbTabMsg.value = '';
  if (pbEditMode.value === 'simple') {
    pbApplySimpleRulesToRecord();
    if (
      pbWizardNonEmptyRules(pbSimpleSuccessRules.value).length === 0
      || pbWizardNonEmptyRules(pbSimpleFailureRules.value).length === 0
    ) {
      pbTabError.value = 'Simple view requires at least one success rule and one failure rule.';
      return;
    }
  }
  if (!pbPrepareRecordForSave()) return;

  if (!pbIsNew.value && pbCategoryChanged()) {
    const ok = confirm(
      'Category changed. Apply the new category preset (success/fail rules + strategies) and regenerate mission plans?\n\n'
      + 'OK = apply preset + regenerate\nCancel = save category only (keep current rules, no regenerate)',
    );
    if (ok) {
      pbSaving.value = true;
      try {
        await pbRegeneratePlaybookForCategoryChange();
      } catch (e) {
        if (isAbortError(e)) {
          pbTabError.value = '';
          pbTabMsg.value = 'Regenerate cancelled.';
        } else {
          pbTabError.value = String(e.message || e);
        }
      } finally {
        pbSaving.value = false;
      }
      return;
    }
  }

  pbSaving.value = true;
  try {
    const priorId = pbSlugify(pbSelectedId.value || '');
    const result = await pbPersistPlaybookRecord();
    const nextId = result.playbook_id || pbSlugify(pbRecord.value?.playbook_id || '');
    if (priorId && nextId && priorId !== nextId) {
      const suiteN = Array.isArray(result.moved_suites) ? result.moved_suites.length : 0;
      const intelN = Array.isArray(result.moved_intel) ? result.moved_intel.length : 0;
      pbTabMsg.value = (
        `Renamed ${priorId} → ${nextId} and saved`
        + (suiteN ? ` · ${suiteN} suite(s) relinked` : '')
        + (intelN ? ` · ${intelN} intel file(s) relinked` : '')
      );
    } else {
      pbTabMsg.value = `Saved ${result.path || result.playbook_id}`;
    }
  } catch (e) {
    pbTabError.value = String(e.message || e);
  } finally {
    pbSaving.value = false;
  }
}

async function pbDeletePlaybook() {
  if (!pbSelectedId.value || pbIsNew.value) return;
  if (!isConfirmArmed('pb-delete')) {
    armConfirm('pb-delete');
    return;
  }
  clearConfirmArmed('pb-delete');
  pbTabError.value = '';
  pbTabMsg.value = '';
  pbDeleting.value = true;
  try {
    await api(`/api/playbooks/${encodeURIComponent(pbSelectedId.value)}`, { method: 'DELETE' });
    pbResetEditor();
    allPlaybooks.value = await api('/api/playbooks');
    await pbLoadCatalog();
    pbTabMsg.value = 'Playbook deleted.';
  } catch (e) {
    pbTabError.value = String(e.message || e);
  } finally {
    pbDeleting.value = false;
  }
}

function pbImportFileChanged(ev) {
  const file = ev.target.files?.[0];
  ev.target.value = '';
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const data = JSON.parse(String(reader.result || ''));
      if (!data || typeof data !== 'object' || Array.isArray(data)) {
        throw new Error('Expected a JSON object');
      }
      pbRecord.value = data;
      pbSyncJsonFromRecord();
      pbIsNew.value = true;
      pbSelectedId.value = '';
      pbNewId.value = pbSlugify(data.playbook_id || file.name.replace(/\.json$/i, ''));
      pbDirty.value = true;
      pbEditMode.value = 'json';
      pbTabMsg.value = `Imported ${file.name} - save to write to playbooks/`;
    } catch (e) {
      pbTabError.value = 'Import failed: ' + e.message;
    }
  };
  reader.readAsText(file);
}

const pbSelectedSummary = computed(() => {
  if (pbIsNew.value) {
    return { id: pbNewId.value || pbRecord.value?.playbook_id || '(new)' };
  }
  return pbCatalog.value.find(p => p.id === pbSelectedId.value) || null;
});

const LOOP_MAX_ROUNDS_CAP = 8;
const LOOP_MAX_ROUND_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8];

function normalizeLoopMaxRounds(raw, fallback = LOOP_MAX_ROUNDS_CAP) {
  const n = Number.parseInt(String(raw ?? ''), 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(1, Math.min(LOOP_MAX_ROUNDS_CAP, n));
}

    const api_out = {
      STRATEGY_DEFAULT_PLAYBOOK,
      gen,
      showPlaybookModal,
      pbWizardStep,
      pbCreateMode,
      pbAiConflict,
      pbPreset,
      pbPresetCatalog,
      pbTargetCapabilities,
      pbWizardAppliedPresetKey,
      pbWizardAppliedTitleHint,
      pbGenerating,
      pbGenerateAbort,
      pbError,
      pbMsg,
      pbGenerationOutput,
      playCategoryTree,
      pbForm,
      pbConfigForm,
      pbRecordCat,
      pbRecordCategoryBaseline,
      pbResetGenerationOutput,
      pbPushGenerationOutput,
      pbStartGenerationHeartbeat,
      pbFormatGenerationLine,
      pbGenerationCurrentPhase,
      pbGenerationStatusKind,
      pbRegenerating,
      pbObjectiveLexiconToLines,
      PB_PROMPT_TEMPLATE_CHIPS,
      pbApplyPromptTemplateChip,
      pbEmptyPlaybookConfigFields,
      pbPlaybookConfigFromRecord,
      pbPlaybookConfigApiPayload,
      pbApplyPlaybookConfigFieldsToRecord,
      pbSyncConfigFormFromRecord,
      pbOnConfigInput,
      pbCategoryKeyFromParts,
      pbCategoryKeyFromRecord,
      pbCategoryKeyFromSelectors,
      pbSetCategoryBaseline,
      pbCategoryChanged,
      pbCatL1Options,
      pbCatL2Options,
      pbCapabilityRequirementSatisfied,
      pbLeafCapabilityRequirements,
      pbLeafCompatible,
      pbLeafDisabledReason,
      pbL1Compatible,
      pbDefaultL2,
      pbEnsureCategoryDefaults,
      pbPathFromRecord,
      pbApplyPathToSelectors,
      pbBuildCategoryPath,
      pbIsOtherCustom,
      pbCustomPurposeValid,
      pbOnCustomHuntNameInput,
      pbOnCustomPurposeInput,
      pbOnFormCategoryL1,
      pbOnFormCategoryL2,
      pbWizardNonEmptyRules,
      pbWizardRulesToText,
      pbWizardCategoryLabel,
      pbWizardLoadPreset,
      pbWizardResetRulesToPreset,
      pbWizardApplyExactCanary,
      pbWizardOnExactCanaryInput,
      pbWizardSelectL1,
      pbWizardSelectL2,
      pbHypothesisLeafHint,
      pbApplySuggestedLeafFromHypothesis,
      pbWizardCanAdvance,
      pbWizardCanGenerate,
      pbWizardNext,
      pbWizardSelectMode,
      pbWizardBack,
      openPlaybookModal,
      cancelPlaybookGenerate,
      closePlaybookModal,
      _runPlaybookGenerateRequest,
      submitPlaybookGenerate,
      submitPlaybookGenerateAi,
      pbOnRecordCategoryL1,
      pbOnRecordCategoryL2,
      pbOnRecordCategoryLabelInput,
      pbApplyCategoryToRecord,
      pbSyncCategoryFromRecord,
      pbPrepareRecordForSave,
      pbPersistPlaybookRecord,
      pbRegeneratePlaybookViaApi,
      pbRegeneratePlaybookForCategoryChange,
      pbRegeneratePlaybook,
      pbFormCategoryValid,
      pbSlugify,
      pbSuggestedPlaybookId,
      pbSuggestId,
      pbCatalog,
      pbSelectedId,
      pbRecord,
      pbJsonText,
      pbEditMode,
      pbDirty,
      pbIsNew,
      pbLoading,
      pbSaving,
      pbDeleting,
      pbTabError,
      pbTabMsg,
      pbNewId,
      pbResultsLayout,
      pbResultsMaximizedActive,
      togglePbResultsMinimize,
      togglePbResultsMaximize,
      pbSimpleSuccessRules,
      pbSimpleFailureRules,
      PB_EXPANDED_GROUPS_KEY,
      pbExpandedGroups,
      pbLoadExpandedGroups,
      pbPersistExpandedGroups,
      pbGroupKey,
      pbPlaybookGroupKey,
      pbIsGroupCollapsed,
      pbToggleGroup,
      pbExpandGroup,
      pbPlayRows,
      pbCatalogGrouped,
      playbooksGrouped,
      genCategoryOptions,
      activeCategoryOptions,
      activePlaybookOptions,
      activeCategoryLabel,
      activePlaybookLabel,
      openHeaderScopeSelect,
      genPlayOptions,
      _samePlaybookId,
      catalogIdForPlaybook,
      catalogHasPlaybooks,
      firstCatalogPlaybookId,
      resolveExistingPlaybookId,
      testFileSlugForPlaybook,
      catalogCategoryForPlaybook,
      syncGenCategoryFromPlaybook,
      mirrorActiveCategory,
      ensureGenPlayInCategory,
      onGenCategoryL1Change,
      onGenPlaybookChange,
      pbSummaryForRunFile,
      groupTestFilesByCategory,
      runCategoryOptions,
      runSelectedCategory,
      runPlayOptions,
      syncRunCategoryFromPlaybook,
      ensureRunPlayInCategory,
      onRunCategoryL1Change,
      onRunPlaybookChange,
      pbFormatDate,
      pbResetEditor,
      pbLoadCatalog,
      pbSyncJsonFromRecord,
      pbApplyJsonToRecord,
      pbMarkDirty,
      pbSelectPlaybook,
      pbStartBlankPlaybook,
      pbOnOverviewInput,
      pbLinesFromList,
      pbListFromLines,
      pbCommaListFromArray,
      pbArrayFromCommaList,
      pbSetCategoryLines,
      pbSetCategoryTriggers,
      pbSetMethodologyLines,
      pbTermListDisplay,
      pbSetTermList,
      pbSuccessMarkersDisplay,
      pbExactCanaryFromRecord,
      pbSetSuccessMarkers,
      pbAddCategory,
      pbRemoveCategory,
      pbAddSeverityTier,
      pbRemoveSeverityTier,
      pbSchemaKeys,
      pbEnsureSchema,
      pbAddSchemaField,
      pbRemoveSchemaField,
      pbOnJsonInput,
      pbSyncSimpleRulesFromRecord,
      pbApplySimpleRulesToRecord,
      pbOnSimpleRulesInput,
      pbTriggersTextFromRecord,
      pbSwitchEditMode,
      pbSavePlaybook,
      pbDeletePlaybook,
      pbImportFileChanged,
      pbSelectedSummary,
      LOOP_MAX_ROUNDS_CAP,
      LOOP_MAX_ROUND_OPTIONS,
      normalizeLoopMaxRounds
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
