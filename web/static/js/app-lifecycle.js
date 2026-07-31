/**
 * App lifecycle: export watches, job poll, site modal, onMounted, tab watches.
 */
(function (G) {
  'use strict';

  G.useAppLifecycle = function useAppLifecycle(ctx) {
    const {
      watch,
      onMounted,
      site,
      component,
      sites,
      components,
      tab,
      settingsTab,
      jobs,
      jobIsActive,
      refreshJobs,
      loadLatestRunLog,
      syncRunTableToMetricsWindow,
      exp,
      expResult,
      expSelectedRiskLevels,
      refreshExpPreview,
      modalError,
      modalMsg,
      modalNewSite,
      modalNewComponent,
      modalSite,
      modalComponent,
      modalComponents,
      modalRenameSite,
      modalRenameComponent,
      showModal,
      readSavedContextSelection,
      pbLoadExpandedGroups,
      loadSites,
      loadConfig,
      loadLlmApiPresets,
      loadTransformOptions,
      applySavedContext,
      loadCompCfg,
      loadLlmConfig,
      loadPipelineSettings,
      loadDefaultsConfig,
      loadCacheSettings,
      loadCorpusStores,
      loadTheoryHistory,
      loadExportSettings,
      loadLogs,
      loadLatestRiskReport,
      tmLoadTestFiles,
      pbLoadCatalog,
      loadPayloadFiles,
      loadDiscoverContext,
      loadRecon,
      logs,
      reconReportPath,
      loadIntelList,
      intelActiveRunId,
      loadCredentialsAndPaths,
      loadNotes,
      pipelineBusy,
      runJobActive,
      loadRunTestFiles,
      initRunPreviewConfig,
      loadContext,
      discoverTransport,
      onDiscoverTransportChange,
      onSiteChange,
      onComponentChange,
    } = ctx;
    const api = G.api;

    watch(() => exp.report, async () => {
      expResult.value = null;
      await refreshExpPreview();
    });

    watch(expSelectedRiskLevels, async () => {
      await refreshExpPreview();
    });

    let _pollTimer = null;

    function _schedulePoll() {
      if (_pollTimer) return;
      _pollTimer = setInterval(async () => {
        const watched = jobs.value.filter(
          (j) => jobIsActive(j.status)
            && (j.type === 'run_tests' || j.type === 'enhance_loop' || j.type === 'recon_round')
        );
        const before = new Map(watched.map((j) => [j.id, j.status]));
        const hasRunning = jobs.value.some(j => jobIsActive(j.status));
        if (hasRunning) {
          await refreshJobs();
          let ranFinished = false;
          for (const [id, prevStatus] of before) {
            const j = jobs.value.find((x) => x.id === id);
            if (!j || jobIsActive(j.status)) continue;
            if (j.type === 'run_tests' || j.type === 'enhance_loop' || j.type === 'recon_round') {
              ranFinished = true;
            }
          }
          if (ranFinished) {
            if (typeof syncRunTableToMetricsWindow === 'function') {
              await syncRunTableToMetricsWindow();
            } else {
              await loadLatestRunLog();
            }
          }
        } else {
          clearInterval(_pollTimer);
          _pollTimer = null;
        }
      }, 10000);
    }
    ctx._schedulePoll = _schedulePoll;

    async function openModal() {
      modalError.value = '';
      modalMsg.value = '';
      modalNewSite.value = '';
      modalNewComponent.value = '';
      if (site.value) {
        modalSite.value = site.value;
        modalComponents.value = components.value.length ? [...components.value] : await api(`/api/sites/${encodeURIComponent(site.value)}/components`);
        modalComponent.value = component.value || '';
        modalRenameSite.value = modalSite.value;
        modalRenameComponent.value = modalComponent.value;
      } else {
        // Prefill from browser-local last selection if still valid
        const saved = readSavedContextSelection();
        if (saved.site && sites.value.includes(saved.site)) {
          modalSite.value = saved.site;
          modalComponents.value = await api(`/api/sites/${encodeURIComponent(saved.site)}/components`);
          modalComponent.value = saved.component && modalComponents.value.includes(saved.component)
            ? saved.component
            : '';
          modalRenameSite.value = modalSite.value;
          modalRenameComponent.value = modalComponent.value;
        } else {
          modalSite.value = '';
          modalComponent.value = '';
          modalRenameSite.value = '';
          modalRenameComponent.value = '';
          modalComponents.value = [];
        }
      }
      showModal.value = true;
    }

    const HEADER_CREATE_SENTINEL = '__create__';

    async function onHeaderSiteChange(event) {
      const next = String(event?.target?.value || '');
      if (next === HEADER_CREATE_SENTINEL) {
        if (event?.target) event.target.value = site.value || '';
        await openModal();
        return;
      }
      site.value = next;
      await onSiteChange();
    }

    async function onHeaderComponentChange(event) {
      const next = String(event?.target?.value || '');
      if (next === HEADER_CREATE_SENTINEL) {
        if (event?.target) event.target.value = component.value || '';
        await openModal();
        return;
      }
      if (next === (component.value || '')) return;
      // Header dropdown only - auto-connect after onComponentChange finishes.
      ctx._autoConnectOnComponentChange = !!next;
      component.value = next;
    }

    onMounted(async () => {
      pbLoadExpandedGroups();
      await loadSites();
      await loadConfig();
      await loadLlmApiPresets();
      await loadTransformOptions();
      await refreshJobs();
      if (!site.value) {
        try {
          if (await applySavedContext()) return;
        } catch { /* fall through to modal */ }
        openModal();
      }
    });

    watch(tab, () => {
      if (tab.value === 'settings') {
        if (settingsTab.value === 'browser') loadConfig();
        else if (settingsTab.value === 'component') loadCompCfg();
        else if (settingsTab.value === 'llm') loadLlmConfig();
        else if (settingsTab.value === 'pipeline') loadPipelineSettings();
        else if (settingsTab.value === 'defaults') loadDefaultsConfig();
        else if (settingsTab.value === 'cache') {
          loadCacheSettings();
          loadCorpusStores();
        }
        else if (settingsTab.value === 'theory') loadTheoryHistory();
      } else if (tab.value === 'export' || tab.value === 'risk') {
        loadExportSettings();
        if (tab.value === 'export') loadLogs();
        // Risk tab enter: risk.js watch(tab) → syncRiskTableToMetricsWindow only
        // (avoid double-fetch / empty flash with loadLatestRiskReport here).
      } else if (tab.value === 'tests') tmLoadTestFiles();
      else if (tab.value === 'playbooks') pbLoadCatalog();
      else if (tab.value === 'payloads') { loadPayloadFiles(); }
      else if (tab.value === 'discover') loadDiscoverContext();
      else if (tab.value === 'recon') {
        loadRecon();
        loadLogs().then(() => {
          const known = reconReportPath.value && logs.reports.some(r => r.path === reconReportPath.value);
          if (!known) {
            reconReportPath.value = logs.reports.length ? logs.reports[0].path : '';
          }
        });
      }
      else if (tab.value === 'intel') {
        loadIntelList(intelActiveRunId.value);
        loadCredentialsAndPaths();
      }
      else if (tab.value === 'notes') {
        loadNotes();
      }
      else if (tab.value === 'run') {
        // Pipeline / active Run or Enhance own the selection - reloading
        // test-files would clear playbook/strategy (especially few_shot vs few-shot).
        const runBusy = !!(
          pipelineBusy?.value
          || runJobActive?.value
        );
        if (!runBusy) {
          loadRunTestFiles();
        }
        loadTransformOptions();
        initRunPreviewConfig();
        if (typeof syncRunTableToMetricsWindow === 'function') {
          syncRunTableToMetricsWindow();
        } else {
          loadLatestRunLog();
        }
      }
      else if (site.value && component.value) loadContext();
    });

    watch(discoverTransport, onDiscoverTransportChange);

    watch(component, async (newComp, oldComp) => {
      if (newComp === oldComp) return;
      if (!site.value || !newComp) return;
      await onComponentChange();
    });

    watch(settingsTab, () => {
      if (tab.value !== 'settings') return;
      if (settingsTab.value === 'browser') loadConfig();
      else if (settingsTab.value === 'component') loadCompCfg();
      else if (settingsTab.value === 'llm') loadLlmConfig();
      else if (settingsTab.value === 'pipeline') loadPipelineSettings();
      else if (settingsTab.value === 'defaults') loadDefaultsConfig();
      else if (settingsTab.value === 'cache') {
        loadCacheSettings();
        loadCorpusStores();
      }
      else if (settingsTab.value === 'theory') loadTheoryHistory();
    });

    const api_out = {
      _schedulePoll,
      openModal,
      onHeaderSiteChange,
      onHeaderComponentChange,
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
