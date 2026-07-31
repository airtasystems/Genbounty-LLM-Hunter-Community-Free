/**
 * Domain module: prompt transforms (Apply to suite + catalog).
 */
(function (G) {
  'use strict';

  G.usePromptTransforms = function usePromptTransforms(ctx) {
    const {
      computed,
      site,
      component,
      tab,
      gen,
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
      runAttrTemperature,
      runAttrMaxTokens,
      runAttrTopK,
      runAttrTopP,
      runAttrApplying,
      runAttrMsg,
      runObfuscationHasBackup,
      loadRunArtifactStatus,
      jobs,
      activeJobs,
      connectSSE,
      jobIsActive,
      genTransformsLayout,
      manualTransformsLayout,
      persistGenTransformsLayout,
      persistManualTransformsLayout,
      persistGenAttributesPrefs,
    } = ctx;
    const api = G.api;
    const run = ctx.run;

    const isManualTransformsTab = computed(() => tab.value === 'manual');

    const transformsPanelLayout = computed(() => (
      isManualTransformsTab.value
        ? manualTransformsLayout.value
        : genTransformsLayout.value
    ));

    function toggleTransformsPanelMinimize() {
      if (isManualTransformsTab.value) {
        manualTransformsLayout.value = manualTransformsLayout.value === 'minimized'
          ? 'normal'
          : 'minimized';
        persistManualTransformsLayout();
        return;
      }
      genTransformsLayout.value = genTransformsLayout.value === 'minimized'
        ? 'normal'
        : 'minimized';
      persistGenTransformsLayout();
    }

    function toggleTransformsPanelMaximize() {
      if (isManualTransformsTab.value) {
        manualTransformsLayout.value = manualTransformsLayout.value === 'maximized'
          ? 'normal'
          : 'maximized';
        persistManualTransformsLayout();
        return;
      }
      genTransformsLayout.value = genTransformsLayout.value === 'maximized'
        ? 'normal'
        : 'maximized';
      persistGenTransformsLayout();
    }

    function applyTransformOptionsCatalog(catalog) {
      if (!catalog || typeof catalog !== 'object') return false;
      obfuscationTechniques.value = Array.isArray(catalog.techniques) ? catalog.techniques : [];
      translationLanguages.value = Array.isArray(catalog.languages) ? catalog.languages : [];
      nativeLanguages.value = Array.isArray(catalog.native_languages) ? catalog.native_languages : [];
      frameTechniques.value = Array.isArray(catalog.frames) ? catalog.frames : [];
      codeLanguages.value = Array.isArray(catalog.code_languages) ? catalog.code_languages : [];
      cipherTechniques.value = Array.isArray(catalog.ciphers) ? catalog.ciphers : [];
      controlCodes.value = Array.isArray(catalog.control_codes) ? catalog.control_codes : [];
      return (
        obfuscationTechniques.value.length
        || translationLanguages.value.length
        || codeLanguages.value.length
        || controlCodes.value.length
      ) > 0;
    }

    async function loadTransformOptions() {
      // Prefer one neutral catalog URL - some environments block paths containing
      // words like "obfuscation" / "ciphers", which left most dropdowns empty.
      try {
        if (applyTransformOptionsCatalog(await api('/api/transform-options'))) return;
      } catch (_) { /* fall through */ }
      try {
        if (applyTransformOptionsCatalog(await api('/static/transform-options.json'))) return;
      } catch (_) { /* fall through */ }
      obfuscationTechniques.value = [];
      translationLanguages.value = [];
      nativeLanguages.value = [];
      frameTechniques.value = [];
      codeLanguages.value = [];
      cipherTechniques.value = [];
      controlCodes.value = [];
    }

    /** Suite target for Prompt Transforms (Forge selection). */
    function transformPlaybookStem() {
      return (gen.playbook || '').split('/').pop().replace(/\.json$/, '');
    }

    function transformSuiteRefs() {
      // On-disk suite dirs/files use hyphens (tests/zero-shot/<play>.json).
      const strategy = String(gen.strategy || '').replace(/_/g, '-');
      const stem = String(transformPlaybookStem() || '').replace(/_/g, '-');
      return { strategy, stem };
    }

    const canObfuscatePrompts = computed(() =>
      !!site.value
      && !!component.value
      && !!gen.playbook
      && !!gen.strategy
      && gen.strategy !== '__all__'
    );

    /** Forge suite Apply or Firing Range live rewrite (site + component). */
    const canApplyPromptTransforms = computed(() => {
      if (!site.value || !component.value) return false;
      if (isManualTransformsTab.value) return true;
      return canObfuscatePrompts.value;
    });

    const transformsHasRestore = computed(() => {
      if (isManualTransformsTab.value) {
        return !!String(manualHumanPromptBackup.value || '').trim();
      }
      return !!runObfuscationHasBackup.value;
    });

    const runTransformsHint = computed(() => {
      if (isManualTransformsTab.value) return '';
      if (canObfuscatePrompts.value) return '';
      if (!site.value || !component.value) {
        return 'Select a site and component first to Apply transforms to an existing suite.';
      }
      if (!gen.playbook) {
        return 'Select a play above to Apply transforms to an existing suite (pipeline checkboxes still work).';
      }
      if (!gen.strategy) {
        return 'Select a strategy above to Apply transforms to an existing suite (pipeline checkboxes still work).';
      }
      if (gen.strategy === '__all__') {
        return 'Pick a concrete strategy to Apply transforms to one suite file. Pipeline checkboxes still apply on Generate & Enhance for all strategies.';
      }
      return 'Select a play and strategy above to Apply transforms to an existing suite.';
    });

    async function loadRunObfuscationStatus() {
      runObfuscationHasBackup.value = false;
      if (!site.value || !component.value || !canObfuscatePrompts.value) return;
      const s = encodeURIComponent(site.value);
      const c = encodeURIComponent(component.value);
      const { strategy, stem } = transformSuiteRefs();
      const strat = encodeURIComponent(strategy);
      const stemEnc = encodeURIComponent(stem);
      try {
        const res = await api(`/api/sites/${s}/${c}/tests/${strat}/${stemEnc}/obfuscation-status`);
        runObfuscationHasBackup.value = !!res.has_backup;
        if (res.technique) runObfuscationTechnique.value = res.technique;
        if (res.language) runTranslationLanguage.value = res.language;
        if (res.native_language) runNativeLanguage.value = res.native_language;
        if (res.frame_technique) runFrameTechnique.value = res.frame_technique;
        if (res.code_language) runCodeLanguage.value = res.code_language;
        if (res.cipher) runCipherTechnique.value = res.cipher;
        if (res.control_code) runControlCodeTechnique.value = res.control_code;
        if (res.iq != null && res.iq !== '') runIqLevel.value = Number(res.iq);
        if (res.emotion != null && res.emotion !== '') runEmotionLevel.value = Number(res.emotion);
        if (res.attributes) {
          if (res.attributes.temperature != null) runAttrTemperature.value = Number(res.attributes.temperature);
          if (res.attributes.max_tokens != null) runAttrMaxTokens.value = Number(res.attributes.max_tokens);
          if (res.attributes.top_k != null) runAttrTopK.value = Number(res.attributes.top_k);
          if (res.attributes.top_p != null) runAttrTopP.value = Number(res.attributes.top_p);
        }
      } catch (_) {
        runObfuscationHasBackup.value = false;
      }
    }

    /**
     * Shared POST for near-identical Apply-to-suite transforms.
     * @param {{
     *   endpoint: string,
     *   body: object,
     *   busyRef: { value: boolean },
     *   msgRef: { value: string },
     *   successMsg: (res: object) => string,
     *   guardExtra?: () => boolean,
     * }} opts
     */
    async function postSuiteTransform(opts) {
      if (!canObfuscatePrompts.value) return;
      if (opts.guardExtra && !opts.guardExtra()) return;
      opts.busyRef.value = true;
      opts.msgRef.value = '';
      const s = encodeURIComponent(site.value);
      const c = encodeURIComponent(component.value);
      const { strategy, stem: stemRaw } = transformSuiteRefs();
      const strat = encodeURIComponent(strategy);
      const stem = encodeURIComponent(stemRaw);
      try {
        const res = await api(
          `/api/sites/${s}/${c}/tests/${strat}/${stem}/${opts.endpoint}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(opts.body),
          },
        );
        opts.msgRef.value = opts.successMsg(res);
        runObfuscationHasBackup.value = true;
        await loadRunArtifactStatus();
      } catch (e) {
        opts.msgRef.value = e.message || 'Transform failed.';
      } finally {
        opts.busyRef.value = false;
      }
    }

    async function applyManualPromptTransform(opts) {
      /**
       * Live rewrite of run.samplePrompt from Human backup.
       * @param {{
       *   kind: string,
       *   name?: string,
       *   attributes?: object,
       *   busyRef: { value: boolean },
       *   msgRef: { value: string },
       *   successMsg: (res: object) => string,
       *   guardExtra?: () => boolean,
       * }} opts
       */
      if (!isManualTransformsTab.value) return false;
      if (!site.value || !component.value) {
        opts.msgRef.value = 'Select a site/component first.';
        return true;
      }
      if (opts.guardExtra && !opts.guardExtra()) return true;
      if (opts.busyRef.value) return true;

      const current = String(run.samplePrompt || '').trim();
      let backup = String(manualHumanPromptBackup.value || '').trim();
      if (!backup) {
        if (!current) {
          opts.msgRef.value = 'Enter a prompt before converting.';
          return true;
        }
        manualHumanPromptBackup.value = String(run.samplePrompt || '');
        backup = String(manualHumanPromptBackup.value || '').trim();
      }
      const source = backup;
      if (!source) {
        opts.msgRef.value = 'Enter a prompt before converting.';
        return true;
      }

      opts.busyRef.value = true;
      opts.msgRef.value = 'Converting…';
      manualNativeBusy.value = true;
      try {
        const body = {
          prompt: source,
          kind: opts.kind,
          name: opts.name != null ? String(opts.name) : '',
        };
        if (opts.kind === 'attributes') {
          body.attributes = opts.attributes || {};
        }
        const res = await api(
          `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/prompt-transform`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          },
        );
        const rewritten = String(res && res.prompt != null ? res.prompt : '').trim();
        if (!rewritten) throw new Error('Empty rewrite result');
        run.samplePrompt = rewritten;
        opts.msgRef.value = opts.successMsg(res);
        manualNativeMsg.value = opts.msgRef.value;
        if (opts.kind === 'native') {
          manualNativeLanguage.value = String(opts.name || '');
          manualNativePrevLanguage.value = String(opts.name || '');
        }
      } catch (e) {
        let detail = (e && e.message) ? String(e.message) : String(e);
        try {
          const parsed = JSON.parse(detail);
          if (parsed && parsed.detail != null) detail = String(parsed.detail);
        } catch (_) { /* keep raw */ }
        opts.msgRef.value = `Convert failed: ${detail}`;
        manualNativeMsg.value = opts.msgRef.value;
      } finally {
        opts.busyRef.value = false;
        manualNativeBusy.value = false;
      }
      return true;
    }

    function restoreManualPlainPrompt() {
      const backup = String(manualHumanPromptBackup.value || '');
      if (!backup.trim()) {
        runObfuscateMsg.value = 'No Human backup to restore.';
        return;
      }
      run.samplePrompt = backup;
      manualNativeLanguage.value = 'human';
      manualNativePrevLanguage.value = 'human';
      manualNativeMsg.value = 'Reverted → Human';
      runObfuscateMsg.value = 'Restored prompt to plain English.';
      runTranslateMsg.value = '';
      runNativeMsg.value = '';
      runFrameMsg.value = '';
      runCodeEmbedMsg.value = '';
      runCipherMsg.value = '';
      runControlCodeMsg.value = '';
      runIqMsg.value = '';
      runEmotionMsg.value = '';
      runAttrMsg.value = '';
    }

    function clearManualTransformSelections(exceptKind) {
      if (exceptKind !== 'obfuscation') runObfuscationTechnique.value = '';
      if (exceptKind !== 'translation') runTranslationLanguage.value = '';
      if (exceptKind !== 'native') runNativeLanguage.value = '';
      if (exceptKind !== 'frame') runFrameTechnique.value = '';
      if (exceptKind !== 'code_embed') runCodeLanguage.value = '';
      if (exceptKind !== 'cipher') runCipherTechnique.value = '';
      if (exceptKind !== 'control_code') runControlCodeTechnique.value = '';
    }

    const manualTransformStatusMsg = computed(() => {
      if (!isManualTransformsTab.value) return '';
      const msgs = [
        runObfuscateMsg.value,
        runTranslateMsg.value,
        runNativeMsg.value,
        runFrameMsg.value,
        runCodeEmbedMsg.value,
        runCipherMsg.value,
        runControlCodeMsg.value,
        runIqMsg.value,
        runEmotionMsg.value,
        manualNativeMsg.value,
      ];
      for (let i = msgs.length - 1; i >= 0; i--) {
        const m = String(msgs[i] || '').trim();
        if (m) return m;
      }
      return '';
    });

    async function onManualTransformSelect(kind) {
      if (typeof persistGenAttributesPrefs === 'function') persistGenAttributesPrefs();
      if (!isManualTransformsTab.value) return;
      const valueByKind = {
        obfuscation: () => runObfuscationTechnique.value,
        translation: () => runTranslationLanguage.value,
        native: () => runNativeLanguage.value,
        frame: () => runFrameTechnique.value,
        code_embed: () => runCodeLanguage.value,
        cipher: () => runCipherTechnique.value,
        control_code: () => runControlCodeTechnique.value,
        iq: () => String(runIqLevel.value),
        emotion: () => String(runEmotionLevel.value),
      };
      const getVal = valueByKind[kind];
      const val = getVal ? String(getVal() || '').trim() : '';
      if (kind !== 'iq' && kind !== 'emotion' && !val) {
        clearManualTransformSelections('');
        restoreManualPlainPrompt();
        return;
      }
      if (kind !== 'iq' && kind !== 'emotion') {
        clearManualTransformSelections(kind);
      }
      if (kind === 'obfuscation') await obfuscateAllPrompts();
      else if (kind === 'translation') await translateAllPrompts();
      else if (kind === 'native') await nativeRewriteAllPrompts();
      else if (kind === 'frame') await frameRewriteAllPrompts();
      else if (kind === 'code_embed') await codeEmbedAllPrompts();
      else if (kind === 'cipher') await cipherAllPrompts();
      else if (kind === 'control_code') await controlCodeAllPrompts();
      else if (kind === 'iq') await applyIqRewrite();
      else if (kind === 'emotion') await applyEmotionRewrite();
    }

    async function convertManualPromptNative() {
      const HUMAN = 'human';
      const next = String(manualNativeLanguage.value || '').trim() || HUMAN;
      const prev = String(manualNativePrevLanguage.value || HUMAN);

      if (next === HUMAN) {
        const backup = String(manualHumanPromptBackup.value || '');
        if (backup) {
          run.samplePrompt = backup;
          manualNativeMsg.value = 'Reverted → Human';
        } else {
          manualNativeMsg.value = '';
        }
        manualNativePrevLanguage.value = HUMAN;
        return;
      }

      await applyManualPromptTransform({
        kind: 'native',
        name: next,
        busyRef: manualNativeBusy,
        msgRef: manualNativeMsg,
        successMsg: (res) => {
          const slug = res.language || res.name || next;
          const label = nativeLanguages.value.find(l => l.slug === slug)?.label || slug;
          return `Converted → ${label}`;
        },
      });
    }

    async function obfuscateAllPrompts() {
      if (await applyManualPromptTransform({
        kind: 'obfuscation',
        name: runObfuscationTechnique.value,
        busyRef: runObfuscating,
        msgRef: runObfuscateMsg,
        guardExtra: () => !!runObfuscationTechnique.value,
        successMsg: (res) => {
          const slug = res.name || runObfuscationTechnique.value;
          const label = obfuscationTechniques.value.find(t => t.slug === slug)?.label || slug;
          return `Obfuscated prompt using ${label}. Plain English preserved in backup.`;
        },
      })) return;
      await postSuiteTransform({
        endpoint: 'obfuscate',
        body: { technique: runObfuscationTechnique.value },
        busyRef: runObfuscating,
        msgRef: runObfuscateMsg,
        guardExtra: () => !!runObfuscationTechnique.value,
        successMsg: (res) => {
          const label = obfuscationTechniques.value.find(t => t.slug === res.technique)?.label || res.technique;
          return `Obfuscated ${res.fields_obfuscated} prompt field(s) using ${label}. Plain English is preserved in backup - switch techniques freely.`;
        },
      });
    }

    async function translateAllPrompts() {
      if (await applyManualPromptTransform({
        kind: 'translation',
        name: runTranslationLanguage.value,
        busyRef: runTranslating,
        msgRef: runTranslateMsg,
        guardExtra: () => !!runTranslationLanguage.value,
        successMsg: (res) => {
          const slug = res.name || runTranslationLanguage.value;
          const label = translationLanguages.value.find(l => l.slug === slug)?.label || slug;
          return `Translated prompt to ${label}. Plain English preserved in backup.`;
        },
      })) return;
      await postSuiteTransform({
        endpoint: 'translate',
        body: { language: runTranslationLanguage.value },
        busyRef: runTranslating,
        msgRef: runTranslateMsg,
        guardExtra: () => !!runTranslationLanguage.value,
        successMsg: (res) => {
          const label = translationLanguages.value.find(l => l.slug === res.language)?.label || res.language;
          return `Translated ${res.fields_translated} prompt field(s) to ${label}. Plain English preserved in backup.`;
        },
      });
    }

    async function nativeRewriteAllPrompts() {
      if (await applyManualPromptTransform({
        kind: 'native',
        name: runNativeLanguage.value,
        busyRef: runNativeRewriting,
        msgRef: runNativeMsg,
        guardExtra: () => !!runNativeLanguage.value,
        successMsg: (res) => {
          const slug = res.name || runNativeLanguage.value;
          const label = nativeLanguages.value.find(l => l.slug === slug)?.label || slug;
          return `Rewrote prompt as ${label}. Plain English preserved in backup.`;
        },
      })) return;
      await postSuiteTransform({
        endpoint: 'native',
        body: { language: runNativeLanguage.value },
        busyRef: runNativeRewriting,
        msgRef: runNativeMsg,
        guardExtra: () => !!runNativeLanguage.value,
        successMsg: (res) => {
          const label = nativeLanguages.value.find(l => l.slug === res.language)?.label || res.language;
          return `Rewrote ${res.fields_rewritten} prompt field(s) as ${label}. Plain English preserved in backup.`;
        },
      });
    }

    async function frameRewriteAllPrompts() {
      if (await applyManualPromptTransform({
        kind: 'frame',
        name: runFrameTechnique.value,
        busyRef: runFrameRewriting,
        msgRef: runFrameMsg,
        guardExtra: () => !!runFrameTechnique.value,
        successMsg: (res) => {
          const slug = res.name || runFrameTechnique.value;
          const label = frameTechniques.value.find(t => t.slug === slug)?.label || slug;
          return `Rewrote prompt with ${label}. Plain English preserved in backup.`;
        },
      })) return;
      await postSuiteTransform({
        endpoint: 'frame',
        body: { technique: runFrameTechnique.value },
        busyRef: runFrameRewriting,
        msgRef: runFrameMsg,
        guardExtra: () => !!runFrameTechnique.value,
        successMsg: (res) => {
          const label = frameTechniques.value.find(t => t.slug === res.technique)?.label || res.technique;
          return `Rewrote ${res.fields_rewritten} prompt field(s) with ${label}. Plain English preserved in backup.`;
        },
      });
    }

    async function codeEmbedAllPrompts() {
      if (await applyManualPromptTransform({
        kind: 'code_embed',
        name: runCodeLanguage.value,
        busyRef: runCodeEmbedding,
        msgRef: runCodeEmbedMsg,
        guardExtra: () => !!runCodeLanguage.value,
        successMsg: (res) => {
          const slug = res.name || runCodeLanguage.value;
          const label = codeLanguages.value.find(l => l.slug === slug)?.label || slug;
          return `Embedded prompt as ${label} code. Plain English preserved in backup.`;
        },
      })) return;
      await postSuiteTransform({
        endpoint: 'code-embed',
        body: { language: runCodeLanguage.value },
        busyRef: runCodeEmbedding,
        msgRef: runCodeEmbedMsg,
        guardExtra: () => !!runCodeLanguage.value,
        successMsg: (res) => {
          const label = codeLanguages.value.find(l => l.slug === res.language)?.label || res.language;
          return `Embedded ${res.fields_embedded} prompt field(s) as ${label} code. Plain English preserved in backup.`;
        },
      });
    }

    async function cipherAllPrompts() {
      if (await applyManualPromptTransform({
        kind: 'cipher',
        name: runCipherTechnique.value,
        busyRef: runCiphering,
        msgRef: runCipherMsg,
        guardExtra: () => !!runCipherTechnique.value,
        successMsg: (res) => {
          const slug = res.name || runCipherTechnique.value;
          const label = cipherTechniques.value.find(t => t.slug === slug)?.label || slug;
          return `Applied ${label} to prompt. Plain English preserved in backup.`;
        },
      })) return;
      await postSuiteTransform({
        endpoint: 'cipher',
        body: { cipher: runCipherTechnique.value },
        busyRef: runCiphering,
        msgRef: runCipherMsg,
        guardExtra: () => !!runCipherTechnique.value,
        successMsg: (res) => {
          const label = cipherTechniques.value.find(t => t.slug === res.cipher)?.label || res.cipher;
          return `Applied ${label} to ${res.fields_ciphered} prompt field(s). Plain English preserved in backup.`;
        },
      });
    }

    async function controlCodeAllPrompts() {
      if (await applyManualPromptTransform({
        kind: 'control_code',
        name: runControlCodeTechnique.value,
        busyRef: runControlCoding,
        msgRef: runControlCodeMsg,
        guardExtra: () => !!runControlCodeTechnique.value,
        successMsg: (res) => {
          const slug = res.name || runControlCodeTechnique.value;
          const label = controlCodes.value.find(t => t.slug === slug)?.label || slug;
          return `Wrapped prompt with ${label}. Plain English preserved in backup.`;
        },
      })) return;
      await postSuiteTransform({
        endpoint: 'control-code',
        body: { technique: runControlCodeTechnique.value },
        busyRef: runControlCoding,
        msgRef: runControlCodeMsg,
        guardExtra: () => !!runControlCodeTechnique.value,
        successMsg: (res) => {
          const label = controlCodes.value.find(t => t.slug === res.technique)?.label || res.technique;
          return `Wrapped ${res.fields_wrapped} prompt field(s) with ${label}. Plain English preserved in backup.`;
        },
      });
    }

    async function applyIqRewrite() {
      if (await applyManualPromptTransform({
        kind: 'iq',
        name: String(runIqLevel.value),
        busyRef: runIqApplying,
        msgRef: runIqMsg,
        successMsg: (res) => (
          `Rewrote prompt for IQ ${res.name || runIqLevel.value}. Plain English preserved in backup.`
        ),
      })) return;
      await postSuiteTransform({
        endpoint: 'iq-rewrite',
        body: { iq: runIqLevel.value },
        busyRef: runIqApplying,
        msgRef: runIqMsg,
        successMsg: (res) => (
          `Rewrote ${res.fields_rewritten} prompt field(s) for IQ ${res.iq}. Plain English preserved in backup.`
        ),
      });
    }

    async function applyEmotionRewrite() {
      if (await applyManualPromptTransform({
        kind: 'emotion',
        name: String(runEmotionLevel.value),
        busyRef: runEmotionApplying,
        msgRef: runEmotionMsg,
        successMsg: (res) => (
          `Rewrote prompt for emotion ${res.name || runEmotionLevel.value}. Plain English preserved in backup.`
        ),
      })) return;
      await postSuiteTransform({
        endpoint: 'emotion-rewrite',
        body: { emotion: runEmotionLevel.value },
        busyRef: runEmotionApplying,
        msgRef: runEmotionMsg,
        successMsg: (res) => (
          `Rewrote ${res.fields_rewritten} prompt field(s) for emotion ${res.emotion}. Plain English preserved in backup.`
        ),
      });
    }

    async function applyPromptAttributes() {
      if (await applyManualPromptTransform({
        kind: 'attributes',
        attributes: {
          temperature: runAttrTemperature.value,
          max_tokens: runAttrMaxTokens.value,
          top_k: runAttrTopK.value,
          top_p: runAttrTopP.value,
        },
        busyRef: runAttrApplying,
        msgRef: runAttrMsg,
        successMsg: () => (
          `Rewrote prompt `
          + `(temp ${runAttrTemperature.value}, max tokens ${runAttrMaxTokens.value}, `
          + `top-k ${runAttrTopK.value}, top-p ${runAttrTopP.value}). Plain English preserved in backup.`
        ),
      })) return;
      if (!canObfuscatePrompts.value) return;
      runAttrApplying.value = true;
      runAttrMsg.value = '';
      const s = encodeURIComponent(site.value);
      const c = encodeURIComponent(component.value);
      const { strategy, stem: stemRaw } = transformSuiteRefs();
      const strat = encodeURIComponent(strategy);
      const stem = encodeURIComponent(stemRaw);
      try {
        const res = await api(
          `/api/sites/${s}/${c}/tests/${strat}/${stem}/prompt-attributes`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              temperature: runAttrTemperature.value,
              max_tokens: runAttrMaxTokens.value,
              top_k: runAttrTopK.value,
              top_p: runAttrTopP.value,
            }),
          },
        );
        const a = res.attributes || {};
        if (res.job_id) {
          const job = {
            id: res.job_id,
            type: 'prompt_attributes',
            status: 'running',
            site: site.value,
            component: component.value,
            params: { strategy, playbook: stemRaw, attributes: a },
            _output: [],
          };
          jobs.value.unshift(job);
          activeJobs.prompt_attributes = res.job_id;
          connectSSE(res.job_id);
          if (typeof ctx._schedulePoll === 'function') ctx._schedulePoll();
          runAttrMsg.value = (
            `Attribute rewrite running in Experiment Output `
            + `(temp ${a.temperature}, max tokens ${a.max_tokens}, `
            + `top-k ${a.top_k}, top-p ${a.top_p})…`
          );
          const waitDone = () => new Promise((resolve) => {
            const tick = () => {
              const j = jobs.value.find(x => x.id === res.job_id);
              if (!j || !jobIsActive(j.status)) {
                resolve(j);
                return;
              }
              setTimeout(tick, 400);
            };
            tick();
          });
          const finished = await waitDone();
          if (finished?.status === 'done') {
            runAttrMsg.value = (
              `Attribute rewrite finished `
              + `(temp ${a.temperature}, max tokens ${a.max_tokens}, `
              + `top-k ${a.top_k}, top-p ${a.top_p}). Plain English preserved in backup.`
            );
            runObfuscationHasBackup.value = true;
            await loadRunArtifactStatus();
          } else if (finished?.status === 'cancelled') {
            runAttrMsg.value = 'Attribute rewrite cancelled.';
          } else {
            const errLine = [...(finished?._output || [])].reverse().find(l => /\[error\]|failed/i.test(l));
            runAttrMsg.value = errLine || 'Attribute rewrite failed. See Experiment Output.';
          }
        } else {
          runAttrMsg.value = (
            `Rewrote ${res.fields_rewritten || 0} prompt field(s) `
            + `(temp ${a.temperature}, max tokens ${a.max_tokens}, `
            + `top-k ${a.top_k}, top-p ${a.top_p}). Plain English preserved in backup.`
          );
          runObfuscationHasBackup.value = true;
          await loadRunArtifactStatus();
        }
      } catch (e) {
        runAttrMsg.value = e.message || 'Attribute rewrite failed.';
      } finally {
        runAttrApplying.value = false;
      }
    }

    async function restorePlainPrompts() {
      if (isManualTransformsTab.value) {
        restoreManualPlainPrompt();
        return;
      }
      if (!canObfuscatePrompts.value || !runObfuscationHasBackup.value) return;
      runObfuscating.value = true;
      runObfuscateMsg.value = '';
      runTranslateMsg.value = '';
      runNativeMsg.value = '';
      runFrameMsg.value = '';
      runCodeEmbedMsg.value = '';
      runCipherMsg.value = '';
      runIqMsg.value = '';
      runEmotionMsg.value = '';
      runAttrMsg.value = '';
      const s = encodeURIComponent(site.value);
      const c = encodeURIComponent(component.value);
      const { strategy, stem: stemRaw } = transformSuiteRefs();
      const strat = encodeURIComponent(strategy);
      const stem = encodeURIComponent(stemRaw);
      try {
        const res = await api(
          `/api/sites/${s}/${c}/tests/${strat}/${stem}/restore-plain`,
          { method: 'POST' },
        );
        runObfuscateMsg.value = `Restored ${res.fields_restored} prompt field(s) to plain English.`;
        runObfuscationHasBackup.value = false;
        await loadRunArtifactStatus();
      } catch (e) {
        runObfuscateMsg.value = e.message || 'Restore failed.';
      } finally {
        runObfuscating.value = false;
      }
    }

    const api_out = {
      applyTransformOptionsCatalog,
      loadTransformOptions,
      transformPlaybookStem,
      transformSuiteRefs,
      canObfuscatePrompts,
      canApplyPromptTransforms,
      transformsHasRestore,
      transformsPanelLayout,
      toggleTransformsPanelMinimize,
      toggleTransformsPanelMaximize,
      onManualTransformSelect,
      manualTransformStatusMsg,
      runTransformsHint,
      loadRunObfuscationStatus,
      obfuscateAllPrompts,
      translateAllPrompts,
      nativeRewriteAllPrompts,
      convertManualPromptNative,
      frameRewriteAllPrompts,
      codeEmbedAllPrompts,
      cipherAllPrompts,
      controlCodeAllPrompts,
      applyIqRewrite,
      applyEmotionRewrite,
      applyPromptAttributes,
      restorePlainPrompts,
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
