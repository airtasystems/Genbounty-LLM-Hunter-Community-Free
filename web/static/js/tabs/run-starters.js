/**
 * Domain module: generate / run / enhance / sample / assess / clear-cache starters.
 */
(function (G) {
  'use strict';

  G.useRunStarters = function useRunStarters(ctx) {
    const {
      armConfirm,
      clearConfirmArmed,
      computed,
      watch,
      site,
      component,
      tab,
      gen,
      run,
      risk,
      cache,
      channelMismatchResolved,
      channelMismatchMsg,
      isConfirmArmed,
      persistGenAttributesPrefs,
      genAutoApplyJobParams,
      startJob,
      runProgress,
      runLivePanelOpen,
      clearRunPreviews,
      initRunPreviewConfig,
      runBlockedInfo,
      showRunLoginModal,
      showRunRateLimitModal,
      showRunCloudflareModal,
      resetRunCloudflareState,
      pendingRunAfterLogin,
      pendingRunAfterRateLimit,
      pendingRunAfterCloudflare,
      runLoginUrl,
      authSaveError,
      rateLimitWaiting,
      rateLimitCountdown,
      _clearRateLimitTimer,
      runSelectedCategory,
      runSuitePath,
      activeJobs,
      normalizeAutoRunStopLevels,
      autoRunStopLevelsLabel,
      selectedAutoRunStopLevels,
      normalizeLoopMaxRounds,
      normalizeHuntMode,
      suiteExistsForSelection,
      hasAssessedReport,
      sampleIntelAdded,
      sampleIntelMsg,
      sidebarSampleReplyCleared,
      openManualCommandView,
      sampleResultAction,
      sampleIntelBusy,
      jobById,
      loadNotes,
      riskWindowIdFromValue,
      ref,
      nextTick,
      activePlaybookId,
      manualAssessMsg,
    } = ctx;
    const api = G.api;

    const headerToolsOpen = ref(false);
    const showNukeHelpModal = ref(false);
    let _headerToolsCloser = null;

    function _unbindHeaderToolsCloser() {
      if (!_headerToolsCloser) return;
      document.removeEventListener('pointerdown', _headerToolsCloser, true);
      _headerToolsCloser = null;
    }

    function closeHeaderTools() {
      headerToolsOpen.value = false;
      _unbindHeaderToolsCloser();
    }

    function openHeaderTools() {
      headerToolsOpen.value = true;
      nextTick(() => {
        _unbindHeaderToolsCloser();
        _headerToolsCloser = (e) => {
          const root = e.target && e.target.closest
            ? e.target.closest('.header-tools')
            : null;
          if (root) return;
          closeHeaderTools();
        };
        document.addEventListener('pointerdown', _headerToolsCloser, true);
      });
    }

    function toggleHeaderTools() {
      if (headerToolsOpen.value) closeHeaderTools();
      else openHeaderTools();
    }

    function openNukeHelpModal() {
      closeHeaderTools();
      showNukeHelpModal.value = true;
    }

    function closeNukeHelpModal() {
      showNukeHelpModal.value = false;
    }

    async function startGenerate() {
      channelMismatchResolved.value = false;
      channelMismatchMsg.value = '';
      persistGenAttributesPrefs();
      await startJob('generate', {
        strategy: gen.strategy,
        playbook: gen.playbook,
        multimodal: !!gen.multimodal,
        ...genAutoApplyJobParams(),
      });
    }

    async function startRunTests() {
      runProgress.value = null;
      runLivePanelOpen.value = true;
      clearRunPreviews();
      await initRunPreviewConfig();
      runBlockedInfo.value = null;
      showRunLoginModal.value = false;
      showRunRateLimitModal.value = false;
      showRunCloudflareModal.value = false;
      resetRunCloudflareState();
      pendingRunAfterLogin.value = false;
      pendingRunAfterRateLimit.value = false;
      pendingRunAfterCloudflare.value = false;
      runLoginUrl.value = '';
      authSaveError.value = '';
      rateLimitWaiting.value = false;
      rateLimitCountdown.value = 0;
      _clearRateLimitTimer();
      if (run.scope === 'category') {
        const group = runSelectedCategory.value;
        const playbooks = (group?.playbooks || []).map(p => p.slug);
        if (!playbooks.length) return;
        await startJob('run_tests', {
          suite: '__category__',
          category: run.category,
          category_label: group?.label || run.category,
          playbooks,
          assess: run.assess,
        });
        return;
      }
      if (run.strategy === '__all__') {
        await startJob('run_tests', { suite: run.strategy, playbook: run.playbook, assess: run.assess });
      } else {
        const suite = runSuitePath();
        if (!suite) return;
        await startJob('run_tests', { suite, assess: run.assess });
      }
    }

    const canEnhanceRerun = computed(() =>
      run.scope === 'playbook'
      && !!run.playbook
      && !!run.strategy
      && run.strategy !== '__all__'
    );

    /** Auto-run drives Enhance & Auto-Run, which needs one concrete strategy. */
    const autoRunBlockedReason = computed(() => {
      if (run.scope !== 'playbook') return '';
      if (run.strategy === '__all__') {
        return 'Auto-run needs a concrete strategy (not All strategies).';
      }
      return '';
    });

    watch(
      () => [run.strategy, autoRunBlockedReason.value],
      () => {
        if (autoRunBlockedReason.value && run.autoRun) {
          run.autoRun = false;
        }
      },
    );

    // Enhance / Auto-run always assesses: feedback drives the next enhance pass;
    // Auto-run also uses severity to stop early on selected Stop at levels.
    watch(
      () => run.autoRun,
      (on) => {
        if (on) {
          run.assess = true;
          run.stopLevels = normalizeAutoRunStopLevels(run.stopLevels);
        }
      },
    );

    const canReconRound = canEnhanceRerun;

    const reconRoundButtonTitle = computed(() => {
      if (!canReconRound.value) {
        return 'Pick a single play and a concrete strategy first';
      }
      return 'Assess the latest run if needed, send targeted recon probes based on recon + intel + playbook + assessment outcomes, and update intel for the next Retarget and attack';
    });

    const shouldPreferEnhance = computed(() =>
      suiteExistsForSelection.value && hasAssessedReport.value
    );

    const generateButtonLabel = computed(() => {
      if (gen.multimodal) return 'Generate Multimodal Probes';
      if (gen.strategy === '__all__') return 'Generate All Strategies';
      if (shouldPreferEnhance.value) return 'Regenerate (open-loop)';
      return 'Generate';
    });

    const enhanceRunButtonTitle = computed(() => {
      if (!canEnhanceRerun.value) {
        return 'Pick a single play and a concrete strategy first';
      }
      if (run.autoRun) {
        return (
          'Assess the latest run if needed, then auto-approve each improvement plan, '
          + `regenerate prompts, run, and assess again until ${autoRunStopLevelsLabel()} `
          + '(max 8 rounds)'
        );
      }
      if (run.customEnhance && run.customEnhanceText.trim()) {
        return 'Assess the latest run, approve the improvement plan, then regenerate with your custom instructions plus assessment feedback';
      }
      return 'Assess the latest run if needed, then regenerate prompts from responses and risk outcomes, run, and assess again';
    });

    const nukeJobActive = computed(() => {
      const id = activeJobs.nuke;
      if (!id) return false;
      const j = jobById(id);
      const st = String(j?.status || '');
      return st === 'pending' || st === 'running';
    });

    async function startReconRound() {
      if (!canReconRound.value) return;
      runProgress.value = null;
      runLivePanelOpen.value = true;
      clearRunPreviews();
      await initRunPreviewConfig();
      runBlockedInfo.value = null;
      showRunLoginModal.value = false;
      showRunRateLimitModal.value = false;
      showRunCloudflareModal.value = false;
      resetRunCloudflareState();
      pendingRunAfterLogin.value = false;
      pendingRunAfterRateLimit.value = false;
      pendingRunAfterCloudflare.value = false;
      runLoginUrl.value = '';
      authSaveError.value = '';
      rateLimitWaiting.value = false;
      rateLimitCountdown.value = 0;
      _clearRateLimitTimer();

      const suite = runSuitePath();
      if (!suite) return;
      const res = await startJob('recon_round', {
        suite,
        playbook: run.playbook,
        strategy: run.strategy,
      });
      delete activeJobs.recon_round;
      activeJobs.run_tests = res.id;
    }

    /**
     * Shared enhance_loop starter for Run tab and Missions Deploy Probes.
     * @param {{
     *   forceAutoRun?: boolean,
     *   playbook?: string,
     *   strategy?: string,
     *   hardRefusalEarlyStop?: number,
     *   circularEnhanceEarlyStop?: number,
     *   allLowEarlyStop?: number,
     *   stopLevels?: string[],
     *   allowCustomEnhance?: boolean,
     *   huntMode?: string,
     * }} opts
     *   forceAutoRun: treat as Auto-run regardless of the Run-tab checkbox.
     *   playbook/strategy: optional overrides (hyphenized) used by Deploy Probes.
     *   hardRefusalEarlyStop: consecutive hard-refusal Low rounds before early
     *     exit (0 = disabled). Pipeline passes 3.
     *   circularEnhanceEarlyStop: consecutive Low overlapping rounds before
     *     soft-advance (0 = disabled). Pipeline passes 3.
     *   allLowEarlyStop: consecutive Low rounds with no partial/exploited before
     *     abort (0 = disabled; backend defaults to 4 in bounty/open). Pipeline passes 4.
     *   stopLevels: optional override for Auto-run Stop at (medium|high|critical).
     *   allowCustomEnhance: when true, inherit Run-tab custom enhance text.
     *     Default false so pipeline does not hitchhike Run guidance.
     *   huntMode: compliance | bug_bounty | open_hunt (defaults to Run-tab huntMode).
     * @returns {Promise<object|null>} job record or null if preconditions fail
     */
    async function launchEnhanceLoop(opts = {}) {
      const forceAutoRun = !!opts.forceAutoRun;
      const auto = forceAutoRun || !!run.autoRun;
      const normalizeHunt = typeof normalizeHuntMode === 'function'
        ? normalizeHuntMode
        : (raw) => {
            const m = String(raw || '').trim().toLowerCase().replace(/-/g, '_');
            if (m === 'bug_bounty' || m === 'open_hunt' || m === 'compliance') return m;
            return 'compliance';
          };
      const huntMode = normalizeHunt(opts.huntMode != null ? opts.huntMode : run.huntMode);

      // Snapshot play/strategy/guidance up front. Switching to the Run tab triggers
      // loadRunTestFiles(), which clears run.playbook/strategy during awaits below.
      let playbook = String(opts.playbook || run.playbook || '')
        .replace(/_/g, '-')
        .trim();
      let strategy = String(opts.strategy || run.strategy || '')
        .replace(/_/g, '-')
        .trim();
      if (strategy === '__all__') strategy = '';
      const allowCustomEnhance = opts.allowCustomEnhance === true;
      const customEnhanceText = (
        allowCustomEnhance
        && run.customEnhance
        && run.customEnhanceText.trim()
      )
        ? run.customEnhanceText.trim()
        : '';
      const customOverridesFreeze = !!(customEnhanceText && run.customOverridesFreeze);

      run.scope = 'playbook';
      run.assess = true;
      run.playbook = playbook;
      run.strategy = strategy;

      if (!playbook || !strategy) {
        console.warn('[enhance] preconditions failed', {
          scope: run.scope,
          playbook,
          strategy,
          site: site.value,
          component: component.value,
        });
        return null;
      }
      if (!site.value || !component.value) {
        console.warn('[enhance] missing site/component');
        return null;
      }

      // Build suite path from the snapshot - do not re-read run.* after awaits.
      const suite = `browser-bot/sites/${site.value}/${component.value}/tests/${strategy}/${playbook}.json`;

      // Mirror startRunTests reset so the shared run live panel + auth/cloudflare
      // modals behave identically while the enhance loop runs.
      runProgress.value = null;
      runLivePanelOpen.value = true;
      clearRunPreviews();
      await initRunPreviewConfig();
      // Re-apply after tab-watch loadRunTestFiles() may have cleared selection.
      run.scope = 'playbook';
      run.playbook = playbook;
      run.strategy = strategy;
      run.assess = true;
      runBlockedInfo.value = null;
      showRunLoginModal.value = false;
      showRunRateLimitModal.value = false;
      showRunCloudflareModal.value = false;
      resetRunCloudflareState();
      pendingRunAfterLogin.value = false;
      pendingRunAfterRateLimit.value = false;
      pendingRunAfterCloudflare.value = false;
      runLoginUrl.value = '';
      authSaveError.value = '';
      rateLimitWaiting.value = false;
      rateLimitCountdown.value = 0;
      _clearRateLimitTimer();

      persistGenAttributesPrefs();
      const jobParams = {
        suite,
        playbook,
        strategy,
        max_rounds: auto ? normalizeLoopMaxRounds(run.maxRounds) : 1,
        // Unattended Auto-run: accept each proposed theory without the modal.
        auto_accept_theory: !!auto,
        hunt_mode: huntMode,
        ...genAutoApplyJobParams(),
      };
      if (auto) {
        const overrideLevels = Array.isArray(opts.stopLevels)
          ? opts.stopLevels
            .map((s) => String(s || '').trim().toLowerCase())
            .filter((s) => s === 'medium' || s === 'high' || s === 'critical')
          : [];
        jobParams.stop_levels = overrideLevels.length
          ? overrideLevels
          : selectedAutoRunStopLevels();
      }
      const earlyStop = Number(opts.hardRefusalEarlyStop);
      if (Number.isFinite(earlyStop) && earlyStop > 0) {
        jobParams.hard_refusal_early_stop = Math.max(1, Math.min(8, Math.floor(earlyStop)));
      }
      const circularStop = Number(opts.circularEnhanceEarlyStop);
      if (Number.isFinite(circularStop) && circularStop > 0) {
        jobParams.circular_enhance_early_stop = Math.max(
          1,
          Math.min(8, Math.floor(circularStop)),
        );
      }
      const allLowStop = Number(opts.allLowEarlyStop);
      if (Number.isFinite(allLowStop) && allLowStop > 0) {
        jobParams.all_low_early_stop = Math.max(
          1,
          Math.min(8, Math.floor(allLowStop)),
        );
      }
      if (customEnhanceText) {
        jobParams.custom_enhance = customEnhanceText;
        if (customOverridesFreeze) {
          jobParams.custom_overrides_freeze = true;
        }
      }
      const res = await startJob('enhance_loop', jobParams);
      // Reuse all existing run-tab plumbing (console, progress, preview, stop).
      delete activeJobs.enhance_loop;
      activeJobs.run_tests = res.id;
      // Keep Run-tab selection aligned with the job we just started.
      run.playbook = playbook;
      run.strategy = strategy;
      return res;
    }

    async function startEnhanceLoop() {
      if (!canEnhanceRerun.value) return;
      await launchEnhanceLoop({ forceAutoRun: false, allowCustomEnhance: true });
    }

    async function startSampleRequest() {
      const prompt = String(run.samplePrompt || '').trim();
      if (!prompt) return;
      sampleIntelAdded.value = false;
      sampleIntelMsg.value = '';
      if (manualAssessMsg) manualAssessMsg.value = '';
      sidebarSampleReplyCleared.value = false;
      openManualCommandView();
      const wantAssess = !!run.manualAssess;
      const params = { prompt, assess: wantAssess };
      if (wantAssess) {
        const playbook = String(
          (activePlaybookId && activePlaybookId.value)
            || run.playbook
            || (gen && gen.playbook)
            || '',
        ).trim();
        if (!playbook) {
          alert('Select a playbook in the header before Fire + Assess.');
          return;
        }
        params.playbook = playbook;
        params.playbook_id = playbook;
      }
      // Keep the prompt in the box after Fire.
      await startJob('sample_request', params);
    }

    async function addSampleResultToNotes() {
      const result = sampleResultAction.value;
      if (!result || sampleIntelBusy.value || sampleIntelAdded.value) return;
      if (!site.value || !component.value) {
        sampleIntelMsg.value = 'Select a site/component first.';
        return;
      }
      sampleIntelBusy.value = true;
      sampleIntelMsg.value = '';
      try {
        await api(
          `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/notes/append-manual-query`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              prompt: result.prompt,
              response: result.response,
            }),
          }
        );
        sampleIntelAdded.value = true;
        sampleIntelMsg.value = 'Added to notes';
        const j = jobById(activeJobs.sample_request);
        if (j && Array.isArray(j._output)) {
          j._output.push('[+] Sample fire added to notes.json');
        }
        if (tab.value === 'notes') await loadNotes();
      } catch (e) {
        sampleIntelMsg.value = 'Add to notes failed: ' + (e.message || String(e));
      } finally {
        sampleIntelBusy.value = false;
      }
    }

    async function startSecurityAssess() {
      runProgress.value = null;
      const windowId = riskWindowIdFromValue(risk.log);
      const params = {};
      if (windowId) {
        params.time_window = windowId;
      } else {
        params.attack_log = risk.log;
      }
      await startJob('security_assess', params);
    }

    function clearGenbountyLocalStorage() {
      const prefixes = ['genbounty_', 'airta_'];
      const removed = [];
      try {
        for (let i = localStorage.length - 1; i >= 0; i -= 1) {
          const key = localStorage.key(i);
          if (!key) continue;
          if (prefixes.some((p) => key === p.slice(0, -1) || key.startsWith(p))) {
            localStorage.removeItem(key);
            removed.push(key);
          }
        }
      } catch (_) {
        /* private browsing / blocked storage */
      }
      return removed;
    }

    async function startClearCache() {
      const clearUi = !!cache.clearLocalStorage;
      await startJob('clear_cache', { delete_on_server: cache.deleteOnServer });
      if (!clearUi) return;
      const removed = clearGenbountyLocalStorage();
      // Reload so Vue state (header playbook, site/component) matches empty storage.
      const n = removed.length;
      window.setTimeout(() => {
        window.location.reload();
      }, 400);
      try {
        console.info(`[genbounty] Cleared ${n} localStorage key(s); reloading.`);
      } catch (_) { /* ignore */ }
    }

    /** Header shortcut: always clear caches + genbounty/airta localStorage, then reload. */
    async function startClearAllCachesAndLocalStorage() {
      if (!isConfirmArmed('header-clear-cache')) {
        armConfirm('header-clear-cache');
        return;
      }
      clearConfirmArmed('header-clear-cache');
      await startJob('clear_cache', { delete_on_server: !!cache.deleteOnServer });
      const removed = clearGenbountyLocalStorage();
      const n = removed.length;
      window.setTimeout(() => {
        window.location.reload();
      }, 400);
      try {
        console.info(`[genbounty] Cleared caches and ${n} localStorage key(s); reloading.`);
      } catch (_) { /* ignore */ }
    }

    /**
     * Header Nuke: wipe component experiment artifacts (tests/logs/intel/theory/…),
     * keep config.yaml + auth.json + recon.json, full backup under nuke_backups/,
     * clear sticky UI storage, reload.
     */
    async function startNuke() {
      if (!site.value || !component.value) return;
      if (ctx.pipelineBusy?.value) return;
      if (activeJobs.nuke && jobById(activeJobs.nuke)
        && ['pending', 'running'].includes(String(jobById(activeJobs.nuke)?.status || ''))) {
        return;
      }
      if (!isConfirmArmed('header-nuke')) {
        armConfirm('header-nuke');
        return;
      }
      clearConfirmArmed('header-nuke');
      const res = await startJob('nuke', {});
      const jobId = String(res?.id || '').trim();
      // Wait for wipe to finish before clearing UI state / reload.
      if (jobId) {
        await new Promise((resolve) => {
          const started = Date.now();
          const tick = () => {
            const j = jobById(jobId);
            const st = String(j?.status || '');
            if (st === 'done' || st === 'failed' || st === 'cancelled') {
              resolve(st);
              return;
            }
            if (Date.now() - started > 120000) {
              resolve('timeout');
              return;
            }
            window.setTimeout(tick, 250);
          };
          tick();
        });
      }
      const removed = clearGenbountyLocalStorage();
      const n = removed.length;
      window.setTimeout(() => {
        window.location.reload();
      }, 400);
      try {
        console.info(
          `[genbounty] Nuke complete for ${site.value}/${component.value}; `
          + `cleared ${n} localStorage key(s); reloading.`,
        );
      } catch (_) { /* ignore */ }
    }

    const api_out = {
      headerToolsOpen,
      showNukeHelpModal,
      toggleHeaderTools,
      closeHeaderTools,
      openNukeHelpModal,
      closeNukeHelpModal,
      startGenerate,
      startRunTests,
      canEnhanceRerun,
      autoRunBlockedReason,
      canReconRound,
      reconRoundButtonTitle,
      shouldPreferEnhance,
      generateButtonLabel,
      enhanceRunButtonTitle,
      startReconRound,
      launchEnhanceLoop,
      startEnhanceLoop,
      startSampleRequest,
      addSampleResultToNotes,
      startSecurityAssess,
      clearGenbountyLocalStorage,
      startClearCache,
      startClearAllCachesAndLocalStorage,
      startNuke,
      nukeJobActive,
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
