/**
 * Domain module: usePipeline
 * Missions "Deploy Probes": ensure suite → enhance Auto-run.
 * Strategy "__all__" cycles every in-scope strategy through enhance once each.
 */
(function (G) {
  'use strict';

  G.usePipeline = function usePipeline(ctx) {
    const {
      activePlaybookId,
      availableGenerateStrategies,
      component,
      computed,
      gen,
      isStrategyOptionDisabled,
      jobById,
      jobIsActive,
      pbIsNew,
      pbSelectedId,
      reactive,
      ref,
      run,
      runTestFiles,
      site,
    } = ctx;
    const api = G.api;

    const pipelineBusy = ctx.pipelineBusy || ref(false);
    const pipelinePromptOutput = ctx.pipelinePromptOutput || ref([]);
    ctx.pipelineBusy = pipelineBusy;
    ctx.pipelinePromptOutput = pipelinePromptOutput;

    const PIPELINE_STOP_LEVEL_KEYS = ['medium', 'high', 'critical'];
    const DEFAULT_PIPELINE_STOP_LEVELS = Object.freeze({
      medium: false,
      high: true,
      critical: true,
    });

    function _defaultStopLevelsObj() {
      return { ...DEFAULT_PIPELINE_STOP_LEVELS };
    }

    function _normalizeStopLevelsObj(raw) {
      const src = raw && typeof raw === 'object' ? raw : {};
      const next = {
        medium: !!src.medium,
        high: !!src.high,
        critical: !!src.critical,
      };
      if (!PIPELINE_STOP_LEVEL_KEYS.some((k) => next[k])) {
        return _defaultStopLevelsObj();
      }
      return next;
    }

    function _stopLevelsObjToList(obj) {
      const levels = _normalizeStopLevelsObj(obj);
      return PIPELINE_STOP_LEVEL_KEYS.filter((k) => levels[k]);
    }

    function _normalizeStopLevelList(raw) {
      const allowed = new Set(PIPELINE_STOP_LEVEL_KEYS);
      const seen = new Set();
      const list = Array.isArray(raw) ? raw : [];
      for (const item of list) {
        const key = String(item || '').trim().toLowerCase();
        if (allowed.has(key)) seen.add(key);
      }
      const out = PIPELINE_STOP_LEVEL_KEYS.filter((k) => seen.has(k));
      return out.length ? out : ['high', 'critical'];
    }

    const pipelinePhase = ctx.pipelinePhase || ref('idle'); // idle|generate|enhance|done
    const pipelineStrategy = ctx.pipelineStrategy || ref('zero_shot');
    const pipelineAllMode = ref(false);
    const pipelineStrategyIndex = ref(0);
    const pipelineStrategyTotal = ref(0);
    /** Concrete strategy currently running while dropdown stays on __all__. */
    const pipelineActiveStrategyLabel = ctx.pipelineActiveStrategyLabel || ref('');
    ctx.pipelinePhase = pipelinePhase;
    ctx.pipelineStrategy = pipelineStrategy;
    ctx.pipelineActiveStrategyLabel = pipelineActiveStrategyLabel;
    const pipelineGeneration = ref(0);
    /** Set by Stop - aborts All-strategies loop even if a job ends as failed/cancelled. */
    const pipelineCancelRequested = ref(false);
    const pipelineActiveJobId = ref('');
    const pipelineMsg = ref('');
    const showPipelineResultModal = ref(false);
    const pipelineResultReason = ref(''); // all_strategies_exhausted | enhance_failed
    const pipelineModalStrategy = ref('zero_shot');
    const pipelineModalMode = ref('again'); // again | different
    const showPipelineRunModal = ref(false);
    const pipelineForm = reactive({
      strategy: '__all__',
      probeStopLevels: _defaultStopLevelsObj(),
      useCustomEnhance: false,
    });
    /** Last submitted (or default) probe Stop at list for this session's pipeline runs. */
    const pipelineRunStopLevels = ref({
      probe: [...PIPELINE_STOP_LEVEL_KEYS],
    });
    /** When true, next runPipelineForStrategy invalidates + regenerates the suite. */
    let pipelineForceSuiteRegen = false;
    /** Snapshot of modal "Use Run custom enhance" for the active pipeline run. */
    let pipelineAllowCustomEnhance = false;

    function pushPipelineLog(line) {
      const text = String(line || '').trimEnd();
      if (!text) return;
      pipelinePromptOutput.value = [...pipelinePromptOutput.value, text];
    }

    function clearPipelineLog() {
      pipelinePromptOutput.value = [];
    }

    function _normStrat(s) {
      return String(s || '').trim().toLowerCase().replace(/-/g, '_');
    }

    function _hyphenStrat(s) {
      return _normStrat(s).replace(/_/g, '-');
    }

    function _aborted(genToken) {
      return pipelineCancelRequested.value || genToken !== pipelineGeneration.value;
    }

    /** Job outcomes that must end the whole pipeline (never advance to next strategy). */
    function _isPipelineAbortStatus(status) {
      const s = String(status || '').toLowerCase();
      return s === 'cancelled' || s === 'missing';
    }

    function _playbookMatches(slug, playbookId) {
      const a = String(slug || '').trim();
      const b = String(playbookId || '').trim();
      if (!a || !b) return false;
      if (typeof ctx._samePlaybookId === 'function') return ctx._samePlaybookId(a, b);
      return a === b
        || a.replace(/-/g, '_') === b.replace(/_/g, '_')
        || a.replace(/_/g, '-') === b.replace(/_/g, '-');
    }

    function suiteExistsForStrategy(playbookId, strategy) {
      const want = _hyphenStrat(strategy);
      const wantUnder = _normStrat(strategy);
      const files = runTestFiles.value || [];
      const file = files.find((f) => _playbookMatches(f.slug, playbookId));
      if (!file) return false;
      return (file.strategies || []).some((s) => {
        const slug = String(s.slug || '');
        return slug === want || _normStrat(slug) === wantUnder;
      });
    }

    const pipelineStrategyOptions = computed(() => {
      const list = availableGenerateStrategies.value || [];
      return list.filter((s) => {
        const slug = typeof s === 'string' ? s : s?.slug;
        if (!slug || slug === '__all__') return false;
        return !isStrategyOptionDisabled(slug);
      }).map((s) => (typeof s === 'string' ? s : s.slug));
    });

    const canStartPipeline = computed(() => {
      if (pipelineBusy.value) return false;
      if (!site.value || !component.value) return false;
      if (!pbSelectedId.value || pbIsNew.value) return false;
      if (ctx.runJobActive?.value) return false;
      const genJob = jobById(ctx.activeJobs?.generate);
      if (genJob && jobIsActive(genJob.status)) return false;
      return true;
    });

    function prettyStrat(s) {
      if (s === '__all__') return 'all strategies';
      if (typeof G.pretty === 'function') return G.pretty(s);
      return String(s || '').replace(/_/g, ' ');
    }

    const pipelineButtonLabel = computed(() => {
      if (!pipelineBusy.value) return 'Start Battle';
      if (pipelineAllMode.value && pipelineStrategyTotal.value > 0) {
        const idx = Math.max(1, pipelineStrategyIndex.value);
        const total = pipelineStrategyTotal.value;
        const strat = prettyStrat(
          pipelineActiveStrategyLabel.value || pipelineStrategy.value,
        );
        if (pipelinePhase.value === 'generate') {
          return `Battle: ${strat} ${idx}/${total} gen…`;
        }
        if (pipelinePhase.value === 'run') {
          return `Battle: ${strat} ${idx}/${total} run…`;
        }
        if (pipelinePhase.value === 'enhance') {
          return `Battle: ${strat} ${idx}/${total} enhance…`;
        }
        return `Battle: ${strat} ${idx}/${total}…`;
      }
      if (pipelinePhase.value === 'generate') return 'Battle: generating…';
      if (pipelinePhase.value === 'run') return 'Battle: baseline…';
      if (pipelinePhase.value === 'enhance') return 'Battle: enhance…';
      return 'Battling…';
    });

    function _stale(gen) {
      return gen !== pipelineGeneration.value;
    }

    function awaitJobDone(jobId, genToken) {
      const api = G.api;
      return new Promise((resolve) => {
        let ticks = 0;
        let missingTicks = 0;
        let mirrored = 0;
        const tick = async () => {
          try {
            if (_aborted(genToken)) {
              resolve('cancelled');
              return;
            }
            ticks += 1;
            let j = typeof jobById === 'function' ? jobById(jobId) : null;
            if (!j && typeof ctx.jobById === 'function') j = ctx.jobById(jobId);
            if (!j && Array.isArray(ctx.jobs?.value)) {
              j = ctx.jobs.value.find((x) => x.id === jobId) || null;
            }
            let s = j ? String(j.status || '') : '';

            // Mirror live job console into the pipeline Experiment Output transcript.
            const out = Array.isArray(j?._output) ? j._output : [];
            if (out.length > mirrored) {
              for (let i = mirrored; i < out.length; i += 1) {
                const raw = String(out[i] || '').trimEnd();
                if (!raw) continue;
                if (raw.startsWith('[genbounty_progress]') || raw.startsWith('[airta_progress]')) {
                  continue;
                }
                if (raw.startsWith('Input: ') || raw.startsWith('Response:')) continue;
                pushPipelineLog(raw);
              }
              mirrored = out.length;
            }

            // Always reconcile with the API - SSE can miss the terminal `done`
            // event, leaving a local status stuck on running/pending.
            if (ticks === 1 || ticks % 3 === 0) {
              if (typeof ctx.refreshJobs === 'function') {
                try { await ctx.refreshJobs(); } catch (_e) { /* ignore */ }
                if (_aborted(genToken)) {
                  resolve('cancelled');
                  return;
                }
                j = (typeof jobById === 'function' ? jobById(jobId) : null)
                  || (Array.isArray(ctx.jobs?.value)
                    ? ctx.jobs.value.find((x) => x.id === jobId)
                    : null)
                  || j;
                if (j) s = String(j.status || s);
              }
              if (typeof api === 'function') {
                try {
                  const remote = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
                  if (remote && remote.status) {
                    s = String(remote.status);
                    if (j) j.status = remote.status;
                    missingTicks = 0;
                  } else {
                    // Gone from server (e.g. process restart) - even if UI still
                    // has a stale local row stuck on running/pending.
                    missingTicks += 1;
                    if (j && (s === 'running' || s === 'pending' || s === 'awaiting_theory')) {
                      j.status = 'cancelled';
                      s = 'cancelled';
                    }
                  }
                } catch (_e) {
                  // api() throws on 404 - job lost after server restart.
                  missingTicks += 1;
                  if (j && (s === 'running' || s === 'pending' || s === 'awaiting_theory')) {
                    j.status = 'cancelled';
                    s = 'cancelled';
                  }
                }
              }
            }

            if (_aborted(genToken)) {
              resolve('cancelled');
              return;
            }
            if (s === 'done' || s === 'failed' || s === 'cancelled') {
              // Final mirror in case last SSE lines arrived with the terminal status.
              const finalOut = Array.isArray(j?._output) ? j._output : [];
              if (finalOut.length > mirrored) {
                for (let i = mirrored; i < finalOut.length; i += 1) {
                  const raw = String(finalOut[i] || '').trimEnd();
                  if (!raw) continue;
                  if (raw.startsWith('[genbounty_progress]') || raw.startsWith('[airta_progress]')) {
                    continue;
                  }
                  if (raw.startsWith('Input: ') || raw.startsWith('Response:')) continue;
                  pushPipelineLog(raw);
                }
              }
              resolve(s);
              return;
            }
            // Prefer quick exit once the server has confirmed the job is gone.
            if (missingTicks >= 2) {
              if (j && (s === 'running' || s === 'pending' || s === 'awaiting_theory')) {
                j.status = 'cancelled';
              }
              resolve('missing');
              return;
            }
          } catch (e) {
            console.warn('[pipeline] awaitJobDone poll error:', e);
          }
          setTimeout(tick, 500);
        };
        tick();
      });
    }

    function _pipelineLog(line) {
      const text = String(line || '').trimEnd();
      if (!text) return;
      pipelineMsg.value = text.replace(/^\[pipeline\]\s*/, '');
      pushPipelineLog(text.startsWith('[') ? text : `[pipeline] ${text}`);
    }

    function _logEnhanceTail(enhanceJobId) {
      try {
        const ej = (typeof jobById === 'function' ? jobById(enhanceJobId) : null)
          || (Array.isArray(ctx.jobs?.value)
            ? ctx.jobs.value.find((x) => x.id === enhanceJobId)
            : null);
        // Client jobs stream into `_output` (SSE); `output` is the server field name.
        const lines = ej?._output || ej?.output || [];
        const tail = lines
          .map((line) => String(line || '').trimEnd())
          .filter(Boolean)
          .filter((line) => !line.startsWith('[genbounty_progress]') && !line.startsWith('[airta_progress]'))
          .slice(-8);
        for (const line of tail) {
          _pipelineLog(line.startsWith('[') ? line : `[enhance] ${line}`);
        }
      } catch (_e) { /* ignore */ }
    }

    async function alignScopeForPipeline(strategy) {
      const playId = String(pbSelectedId.value || activePlaybookId.value || '').trim();
      if (!playId) throw new Error('Select a saved play first.');
      const genStrat = _normStrat(strategy) || 'zero_shot';
      const runStrat = _hyphenStrat(genStrat);

      if (typeof ctx.setActivePlaybook === 'function') {
        await ctx.setActivePlaybook(playId, { source: 'pipeline', loadPlays: false });
      }
      gen.playbook = ctx.catalogIdForPlaybook?.(playId) || playId;
      gen.strategy = genStrat;
      gen.multimodal = false;

      run.scope = 'playbook';
      run.autoRun = true;
      run.assess = true;

      await ctx.loadRunTestFiles({ applySaved: false, restorePlaybook: false });
      const runSlug = ctx.testFileSlugForPlaybook?.(runTestFiles.value, playId)
        || ctx.testFileSlugForPlaybook?.(runTestFiles.value, gen.playbook)
        || '';
      if (runSlug) {
        run.playbook = runSlug;
        ctx.runOnTestFileChange?.(true);
      } else {
        // Suite may not exist yet - use hyphen stem so runSuitePath works after generate.
        run.playbook = String(gen.playbook || playId).replace(/_/g, '-');
        run.strategy = runStrat;
      }
      // Prefer hyphen dir name for run.strategy (matches tests/<strategy>/ on disk).
      const file = (runTestFiles.value || []).find((f) => _playbookMatches(f.slug, run.playbook));
      const hasHyphen = (file?.strategies || []).some((s) => s.slug === runStrat);
      run.strategy = hasHyphen || !file ? runStrat : (file.strategies[0]?.slug || runStrat);
      // Keep dropdown on All strategies while cycling; track concrete strategy separately.
      if (!pipelineAllMode.value) {
        pipelineStrategy.value = genStrat;
      }
    }

    function openPipelineResultModal(reason) {
      pipelineResultReason.value = reason || 'enhance_failed';
      if (pipelineAllMode.value) {
        pipelineModalStrategy.value = (pipelineStrategyOptions.value || [])[0] || 'zero_shot';
      } else {
        pipelineModalStrategy.value = _normStrat(pipelineStrategy.value) || 'zero_shot';
      }
      pipelineModalMode.value = 'again';
      showPipelineResultModal.value = true;
    }

    function closePipelineResultModal() {
      showPipelineResultModal.value = false;
    }

    function resetPipelineForm() {
      pipelineForm.strategy = '__all__';
      pipelineForm.probeStopLevels = _defaultStopLevelsObj();
      pipelineForm.useCustomEnhance = false;
    }

    function openPipelineRunModal() {
      // Community: Start Battle is Premium.
      if (typeof ctx.openPremiumModal === 'function') {
        ctx.openPremiumModal('start_battle');
      }
      pipelineMsg.value =
        'Start Battle is Premium — use Run and Enhance on the Attack tab.';
    }

    function closePipelineRunModal() {
      if (pipelineBusy.value) return;
      showPipelineRunModal.value = false;
    }

    function togglePipelineProbeStopLevel(level, checked) {
      if (!PIPELINE_STOP_LEVEL_KEYS.includes(level)) return;
      const next = { ...pipelineForm.probeStopLevels, [level]: !!checked };
      if (!PIPELINE_STOP_LEVEL_KEYS.some((k) => next[k])) return;
      pipelineForm.probeStopLevels = next;
    }

    const canSubmitPipelineRunModal = computed(() => {
      if (!canStartPipeline.value) return false;
      const strat = pipelineForm.strategy;
      if (strat !== '__all__' && isStrategyOptionDisabled(strat)) return false;
      if (!_stopLevelsObjToList(pipelineForm.probeStopLevels).length) return false;
      return true;
    });

    function submitPipelineRunModal() {
      showPipelineRunModal.value = false;
      if (typeof ctx.openPremiumModal === 'function') {
        ctx.openPremiumModal('start_battle');
      }
    }

    async function cancelPipeline() {
      pipelineCancelRequested.value = true;
      pipelineGeneration.value += 1;
      pipelineMsg.value = 'Cancelling pipeline…';
      _pipelineLog('[pipeline] Stop - aborting entire pipeline (no further strategies).');
      const ids = new Set();
      const primary = String(pipelineActiveJobId.value || '').trim();
      if (primary) ids.add(primary);
      // Enhance is aliased onto activeJobs.run_tests; also cancel any live battle jobs.
      for (const key of ['run_tests', 'enhance_loop', 'generate', 'security_assess']) {
        const id = String(ctx.activeJobs?.[key] || '').trim();
        if (id) ids.add(id);
      }
      for (const jobId of ids) {
        if (typeof ctx.cancelJob === 'function') {
          try { await ctx.cancelJob(jobId, { soft: true }); } catch (_e) { /* ignore */ }
        }
      }
      pipelineBusy.value = false;
      pipelinePhase.value = 'idle';
      pipelineActiveJobId.value = '';
      pipelineStrategyIndex.value = 0;
      pipelineStrategyTotal.value = 0;
      pipelineActiveStrategyLabel.value = '';
      pipelineMsg.value = 'Pipeline cancelled.';
    }

    /**
     * One strategy cycle: ensure suite → enhance Auto-run.
     * @param {string} strategy
     * @param {number} genToken
     * @param {{ forceSuiteRegen?: boolean }} cycleOpts
     * @returns {Promise<{ ok: boolean, cancelled: boolean, reason: string }>}
     */
    async function runPipelineForStrategy(strategy, genToken, cycleOpts = {}) {
      const empty = { ok: false, cancelled: false, reason: '' };
      const aborted = { ok: false, cancelled: true, reason: 'cancelled' };
      const strat = _normStrat(strategy) || 'zero_shot';
      if (_aborted(genToken)) return aborted;

      await alignScopeForPipeline(strat);
      if (_aborted(genToken)) return aborted;

      const playForSuite = run.playbook || gen.playbook || pbSelectedId.value;
      const playIdForTheory = String(
        playForSuite || pbSelectedId.value || activePlaybookId.value || '',
      ).replace(/-/g, '_').trim();

      // Clean lane: clear accepted theories + elite for this play+strategy before enhance.
      // Playbook strategy_handoff (if any) may reseed elite on the next theory step.
      if (site.value && component.value && playIdForTheory) {
        try {
          const qs = new URLSearchParams({
            playbook_id: playIdForTheory,
            strategy: strat,
            clear_elite: '1',
          });
          await api(
            `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/theory-history?${qs}`,
            { method: 'DELETE' },
          );
          _pipelineLog(
            `[pipeline] Cleared theory history for ${playIdForTheory}/${strat}`,
          );
          _pipelineLog(
            `[pipeline] Prior playbook strategy_handoff (if any) may reseed elite on enhance.`,
          );
        } catch (e) {
          _pipelineLog(
            `[pipeline] Theory history clear failed (${e.message || e}) - continuing.`,
          );
        }
      }
      if (_aborted(genToken)) return aborted;

      const forceRegen = !!(cycleOpts.forceSuiteRegen || pipelineForceSuiteRegen);
      let hasSuite = suiteExistsForStrategy(playForSuite, strat);
      if (forceRegen && hasSuite && site.value && component.value && playForSuite) {
        const playStem = String(playForSuite).replace(/_/g, '-').trim();
        const stratHyphen = _hyphenStrat(strat);
        try {
          await api(
            `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/tests/${encodeURIComponent(stratHyphen)}/${encodeURIComponent(playStem)}`,
            { method: 'DELETE' },
          );
          _pipelineLog(
            `[pipeline] Invalidated ${stratHyphen}/${playStem} suite (clean lane regen).`,
          );
        } catch (e) {
          _pipelineLog(
            `[pipeline] Suite invalidate failed (${e.message || e}) - will regenerate if missing.`,
          );
        }
        await ctx.loadRunTestFiles?.({ applySaved: false, restorePlaybook: false });
        hasSuite = suiteExistsForStrategy(playForSuite, strat);
      }
      pipelineForceSuiteRegen = false;

      if (!hasSuite || forceRegen) {
        pipelinePhase.value = 'generate';
        _pipelineLog(`[pipeline] Generating ${strat} suite…`);
        if (typeof ctx.persistGenAttributesPrefs === 'function') {
          ctx.persistGenAttributesPrefs();
        }
        const genJob = await ctx.startJob('generate', {
          strategy: _normStrat(strat),
          playbook: gen.playbook,
          multimodal: false,
          ...(typeof ctx.genAutoApplyJobParams === 'function' ? ctx.genAutoApplyJobParams() : {}),
        });
        if (_aborted(genToken)) return aborted;
        pipelineActiveJobId.value = genJob.id;
        const genStatus = await awaitJobDone(genJob.id, genToken);
        if (_aborted(genToken) || _isPipelineAbortStatus(genStatus)) {
          _pipelineLog(
            `[pipeline] Generate ${genStatus || 'cancelled'} for ${strat} - pipeline stopped.`,
          );
          return aborted;
        }
        if (genStatus !== 'done') {
          _pipelineLog(`[pipeline] Generate ${genStatus} for ${strat} - advancing.`);
          return { ...empty, reason: `generate_${genStatus}` };
        }
        await ctx.loadRunTestFiles({ applySaved: false, restorePlaybook: false });
        if (_aborted(genToken)) return aborted;
        const runSlug = ctx.testFileSlugForPlaybook?.(runTestFiles.value, gen.playbook)
          || ctx.testFileSlugForPlaybook?.(runTestFiles.value, pbSelectedId.value);
        if (runSlug) {
          run.playbook = runSlug;
          ctx.runOnTestFileChange?.(true);
        }
        run.strategy = _hyphenStrat(strat);
      } else {
        _pipelineLog(`[pipeline] Using existing ${strat} suite.`);
      }

      if (_aborted(genToken)) return aborted;

      // Baseline Attack + Analysis before enhance. Newly generated suites
      // must be tested first; enhance never regenerates cold prompts.
      const baselinePlay = String(
        run.playbook || gen.playbook || pbSelectedId.value || activePlaybookId.value || '',
      ).replace(/_/g, '-');
      const baselineStrat = _hyphenStrat(strat);
      run.scope = 'playbook';
      run.assess = true;
      run.playbook = baselinePlay;
      run.strategy = baselineStrat;
      if (!baselinePlay || !baselineStrat || !site.value || !component.value) {
        _pipelineLog(
          `[pipeline] Missing play/strategy for baseline run`
          + ` (play=${baselinePlay || '?'}, strategy=${baselineStrat || '?'}) - advancing.`,
        );
        return { ...empty, reason: 'missing_scope' };
      }
      const baselineSuite = (
        `browser-bot/sites/${site.value}/${component.value}/tests/`
        + `${baselineStrat}/${baselinePlay}.json`
      );
      pipelinePhase.value = 'run';
      _pipelineLog(
        `[pipeline] Baseline Attack + Analysis for ${baselineStrat}/${baselinePlay}…`,
      );
      const baselineJob = await ctx.startJob('run_tests', {
        suite: baselineSuite,
        assess: true,
      });
      if (_aborted(genToken)) return aborted;
      pipelineActiveJobId.value = baselineJob.id;
      const baselineStatus = await awaitJobDone(baselineJob.id, genToken);
      if (_aborted(genToken) || _isPipelineAbortStatus(baselineStatus)) {
        _pipelineLog(
          `[pipeline] Baseline run ${baselineStatus || 'cancelled'} for ${strat}`
          + ' - pipeline stopped.',
        );
        return aborted;
      }
      if (baselineStatus !== 'done') {
        _pipelineLog(
          `[pipeline] Baseline run ${baselineStatus} for ${strat}`
          + ' - skipping enhance (need Analysis first).',
        );
        return { ...empty, reason: `baseline_${baselineStatus}` };
      }
      _pipelineLog(`[pipeline] Baseline assess complete for ${strat}.`);

      if (_aborted(genToken)) return aborted;
      pipelinePhase.value = 'enhance';
      // Snapshot before enhance launch - Run-tab watches can clear run.playbook/strategy
      // while awaits are in flight.
      const enhancePlay = String(
        run.playbook || gen.playbook || pbSelectedId.value || activePlaybookId.value || '',
      ).replace(/_/g, '-');
      const enhanceStrat = _hyphenStrat(strat);
      run.scope = 'playbook';
      run.autoRun = true;
      run.assess = true;
      run.playbook = enhancePlay;
      run.strategy = enhanceStrat;
      if (!enhancePlay || !enhanceStrat) {
        _pipelineLog(
          `[pipeline] Missing play/strategy after align`
          + ` (play=${enhancePlay || '?'}, strategy=${enhanceStrat || '?'}) - advancing.`,
        );
        return { ...empty, reason: 'missing_scope' };
      }
      const enhanceJob = await ctx.launchEnhanceLoop({
        forceAutoRun: true,
        playbook: enhancePlay,
        strategy: enhanceStrat,
        // Soft-advance sooner under sustained hard-refusal / circular Low
        // (any header Deploy Probes run - single strategy or All).
        hardRefusalEarlyStop: 3,
        circularEnhanceEarlyStop: 3,
        allLowEarlyStop: 4,
        stopLevels: pipelineRunStopLevels.value.probe,
        allowCustomEnhance: !!pipelineAllowCustomEnhance,
        // Follow Attack hunt mode (Compliance / Bug Bounty / Open Hunt).
        huntMode: run.huntMode,
      });
      if (_aborted(genToken)) return aborted;
      if (!enhanceJob) {
        _pipelineLog(
          `[pipeline] Could not start enhance for ${strat}`
          + ` (play=${enhancePlay}, site=${site.value || '?'}/${component.value || '?'}) - advancing.`,
        );
        return { ...empty, reason: 'enhance_start_failed' };
      }
      const enhanceRounds = enhanceJob.params?.max_rounds;
      _pipelineLog(
        `[pipeline] Enhance Auto-run started`
        + ` (job ${enhanceJob.id}, max ${enhanceRounds || '?'} rounds,`
        + ` auto_accept=${!!enhanceJob.params?.auto_accept_theory}).`,
      );
      pipelineActiveJobId.value = enhanceJob.id;
      const enhanceStatus = await awaitJobDone(enhanceJob.id, genToken);
      if (_aborted(genToken) || _isPipelineAbortStatus(enhanceStatus)) {
        _pipelineLog(
          `[pipeline] Enhance ${enhanceStatus || 'cancelled'} for ${strat} - pipeline stopped.`,
        );
        // Do not dump in-flight assess tails after Stop - they look like the
        // pipeline kept going.
        if (!_aborted(genToken)) {
          _logEnhanceTail(enhanceJob.id);
        }
        return aborted;
      }
      if (enhanceStatus !== 'done') {
        _pipelineLog(`[pipeline] Enhance ${enhanceStatus} for ${strat} - advancing.`);
        _logEnhanceTail(enhanceJob.id);
        return { ...empty, reason: `enhance_${enhanceStatus}` };
      }
      _pipelineLog(`[pipeline] Enhance complete for ${strat}.`);
      return { ok: true, cancelled: false, reason: '' };
    }

    async function startPipeline(opts = {}) {
      // Community: Start Battle orchestration is Premium (Enhance Auto-run stays).
      // Body below the return is retained for Premium→Community sync diffs.
      if (typeof ctx.openPremiumModal === 'function') {
        ctx.openPremiumModal('start_battle');
      }
      pipelineMsg.value =
        'Start Battle is Premium — use Run and Enhance on the Attack tab.';
      return;

      if (pipelineBusy.value) return;
      const rawStrategy = opts.strategy != null
        ? opts.strategy
        : (pipelineStrategy.value || 'zero_shot');
      const wantAll = !!opts.allStrategies
        || String(rawStrategy).trim() === '__all__'
        || _normStrat(rawStrategy) === '__all__';

      if (!canStartPipeline.value && !opts.fromModal) {
        pipelineMsg.value = 'Select a site, component, and saved play before running the pipeline.';
        return;
      }

      const strategyList = wantAll
        ? (pipelineStrategyOptions.value || []).map((s) => _normStrat(s)).filter(Boolean)
        : [_normStrat(rawStrategy) || 'zero_shot'];

      if (!strategyList.length) {
        pipelineMsg.value = 'No in-scope strategies available for this target.';
        return;
      }

      if (!wantAll && isStrategyOptionDisabled(strategyList[0])) {
        pipelineMsg.value = `Strategy ${strategyList[0]} is out of scope for this target.`;
        return;
      }

      // Snapshot probe Stop at list for this run (explicit opts, else last/default).
      const nextProbe = opts.probeStopLevels != null
        ? _normalizeStopLevelList(opts.probeStopLevels)
        : _normalizeStopLevelList(pipelineRunStopLevels.value.probe);
      pipelineRunStopLevels.value = { probe: nextProbe };
      pipelineAllowCustomEnhance = !!opts.allowCustomEnhance;
      pipelineForceSuiteRegen = false;

      showPipelineResultModal.value = false;
      showPipelineRunModal.value = false;
      pipelineCancelRequested.value = false;
      pipelineGeneration.value += 1;
      const genToken = pipelineGeneration.value;
      pipelineBusy.value = true;
      pipelineMsg.value = '';
      pipelinePhase.value = 'generate';
      pipelineActiveJobId.value = '';
      pipelineAllMode.value = wantAll;
      pipelineStrategyTotal.value = strategyList.length;
      pipelineStrategyIndex.value = 0;
      pipelineActiveStrategyLabel.value = '';
      if (typeof ctx.selectSidebarTab === 'function') {
        ctx.selectSidebarTab('war-room');
      }
      if (wantAll) {
        pipelineStrategy.value = '__all__';
      }
      clearPipelineLog();
      _pipelineLog(
        wantAll
          ? `[pipeline] === Start Battle starting (all ${strategyList.length} in-scope strategies) ===`
          : '[pipeline] === Start Battle starting ===',
      );
      _pipelineLog(
        `[pipeline] Probe Stop at: ${nextProbe.join('/') || 'medium+'}`,
      );

      try {
        let lastReason = '';
        for (let i = 0; i < strategyList.length; i += 1) {
          if (_aborted(genToken)) {
            _pipelineLog('[pipeline] Cancelled - not starting further strategies.');
            return;
          }
          const strat = strategyList[i];
          pipelineStrategyIndex.value = i + 1;
          pipelineActiveStrategyLabel.value = strat;
          if (!pipelineAllMode.value) {
            pipelineStrategy.value = strat;
          } else {
            _pipelineLog(
              `[pipeline] Strategy ${i + 1}/${strategyList.length}: ${prettyStrat(strat)}`,
            );
          }

          const result = await runPipelineForStrategy(strat, genToken, {
            forceSuiteRegen: pipelineForceSuiteRegen,
          });
          if (_aborted(genToken) || result.cancelled) {
            _pipelineLog('[pipeline] Cancelled - pipeline stopped.');
            return;
          }
          if (result.ok) {
            if (!wantAll) {
              pipelinePhase.value = 'done';
              _pipelineLog('[pipeline] Complete: enhance finished.');
              return;
            }
            // All mode: advance to next strategy after a successful enhance cycle.
            pipelineForceSuiteRegen = true;
            continue;
          }
          lastReason = result.reason || lastReason;
          // Soft miss → force suite regen for next strategy.
          pipelineForceSuiteRegen = true;
          if (!wantAll) {
            if (lastReason) {
              _pipelineLog(`[pipeline] Stopped: ${lastReason}.`);
              openPipelineResultModal('enhance_failed');
            }
            return;
          }
        }

        if (_aborted(genToken)) return;
        if (wantAll) {
          pipelinePhase.value = 'done';
          _pipelineLog(
            `[pipeline] Complete: finished ${strategyList.length} strategies.`,
          );
        }
      } catch (e) {
        if (!_aborted(genToken)) {
          _pipelineLog(`[pipeline] Failed: ${e.message || e}`);
        }
      } finally {
        // Always release busy when this run owns the token or was cancelled mid-flight.
        const owned = !_stale(genToken) || pipelineCancelRequested.value;
        if (owned) {
          pipelineBusy.value = false;
          pipelineActiveJobId.value = '';
          pipelineStrategyIndex.value = 0;
          pipelineStrategyTotal.value = 0;
          pipelineActiveStrategyLabel.value = '';
          if (pipelineAllMode.value && !pipelineCancelRequested.value) {
            pipelineStrategy.value = '__all__';
          }
          if (pipelineCancelRequested.value) {
            pipelinePhase.value = 'idle';
          } else if (pipelinePhase.value !== 'idle') {
            pipelinePhase.value = showPipelineResultModal.value ? pipelinePhase.value : 'idle';
          }
        }
      }
    }

    async function pipelineRunAgain() {
      closePipelineResultModal();
      if (pipelineAllMode.value || pipelineResultReason.value === 'all_strategies_exhausted') {
        await startPipeline({ allStrategies: true, fromModal: true });
        return;
      }
      await startPipeline({ strategy: pipelineStrategy.value, fromModal: true });
    }

    async function pipelineTryDifferentStrategy() {
      const next = _normStrat(pipelineModalStrategy.value);
      if (!next) return;
      closePipelineResultModal();
      pipelineAllMode.value = false;
      await startPipeline({ strategy: next, fromModal: true });
    }

    const pipelineResultTitle = computed(() => {
      if (pipelineResultReason.value === 'all_strategies_exhausted') {
        return 'All strategies finished';
      }
      return 'Pipeline stopped';
    });

    const pipelineResultBody = computed(() => {
      const play = pbSelectedId.value || activePlaybookId.value || 'this play';
      if (pipelineResultReason.value === 'all_strategies_exhausted') {
        const n = (pipelineStrategyOptions.value || []).length;
        return (
          `Finished ${n || 'all'} in-scope strateg${n === 1 ? 'y' : 'ies'} for ${play}. `
          + 'Run again through all strategies, or pick a single strategy.'
        );
      }
      const strat = prettyStrat(
        pipelineStrategy.value === '__all__' ? 'all strategies' : pipelineStrategy.value,
      );
      return (
        `Pipeline stopped for ${play} (${strat}) before enhance finished. `
        + 'Run again, or try a different strategy.'
      );
    });

    const api_out = {
      pipelineBusy,
      pipelinePromptOutput,
      pushPipelineLog,
      clearPipelineLog,
      pipelinePhase,
      pipelineStrategy,
      pipelineAllMode,
      pipelineStrategyIndex,
      pipelineStrategyTotal,
      pipelineActiveStrategyLabel,
      pipelineGeneration,
      pipelineActiveJobId,
      pipelineMsg,
      showPipelineResultModal,
      pipelineResultReason,
      pipelineModalStrategy,
      pipelineModalMode,
      showPipelineRunModal,
      pipelineForm,
      pipelineRunStopLevels,
      pipelineStrategyOptions,
      canStartPipeline,
      canSubmitPipelineRunModal,
      pipelineButtonLabel,
      pipelineResultTitle,
      pipelineResultBody,
      suiteExistsForStrategy,
      alignScopeForPipeline,
      runPipelineForStrategy,
      startPipeline,
      cancelPipeline,
      openPipelineRunModal,
      closePipelineRunModal,
      submitPipelineRunModal,
      togglePipelineProbeStopLevel,
      closePipelineResultModal,
      pipelineRunAgain,
      pipelineTryDifferentStrategy,
      openPipelineResultModal,
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
