/**
 * Domain module: Discover tab (browser/API transport, presets, help modal).
 */
(function (G) {
  'use strict';

  G.useDiscover = function useDiscover(ctx) {
    const {
      ref,
      reactive,
      computed,
      site,
      component,
      tab,
      settingsTab,
      jobs,
      startJob,
      loadCompCfg,
      llmApiPresets,
      apiNeedsAuth,
      apiAuthReady,
      authApiKeyHeader,
      authApiKeyQueryParam,
      authUseBearer,
      globalUseCdpBrowser,
      applyNormalizedLoginUrl,
      persistComponentLoginUrl,
      manualDiscoverJobId,
      manualDiscoverRunning,
      PROMPT_TEMPLATE_HINT,
      PROMPT_MODEL_HINT,
      compCfg,
      watch,
    } = ctx;
    const api = G.api;

    const discoverTransport = ref(G.preferredDiscoverTransport());
    const guidedDiscovery = ref(false);
    const guidedDiscoveryUseCdp = ref(false);

    function applyDiscoverTransportPref() {
      discoverTransport.value = G.preferredDiscoverTransport();
    }

    /** Map saved submission.transport → Connection type dropdown (api | browser). */
    function syncDiscoverTransportFromSubmission(transport) {
      const t = String(transport || 'ui').trim().toLowerCase();
      const next = ['api', 'api_document', 'api_multipart'].includes(t) ? 'api' : 'browser';
      discoverTransport.value = next;
      if (typeof G.persistDiscoverTransport === 'function') {
        G.persistDiscoverTransport(next);
      }
      return next;
    }

    const effectiveGuidedDiscoveryUseCdp = computed(
      () => globalUseCdpBrowser.value || guidedDiscoveryUseCdp.value,
    );

    function onGuidedDiscoveryUseCdpChange(event) {
      if (globalUseCdpBrowser.value) return;
      guidedDiscoveryUseCdp.value = !!event.target.checked;
    }

    const apiDiscover = reactive({
      presetId: 'custom',
      transport: 'api',
      url: 'http://localhost:3000/api/chat',
      uploadUrl: '',
      method: 'POST',
      responsePath: 'response',
      model: '',
      bodyJson: '{\n  "prompt": "{{prompt}}"\n}',
      headersJson: '{}',
    });

    async function loadLlmApiPresets() {
      try {
        llmApiPresets.value = await api('/api/llm-api-presets');
      } catch {
        llmApiPresets.value = [];
      }
    }

    function applyApiPreset(presetId, { authOnly = false } = {}) {
      const preset = llmApiPresets.value.find(p => p.id === presetId);
      if (!preset) return;
      apiDiscover.presetId = presetId;
      if (authOnly) return;
      apiDiscover.transport = 'api';
      apiDiscover.url = preset.url || '';
      apiDiscover.method = preset.method || 'POST';
      apiDiscover.responsePath = preset.response_path || 'response';
      apiDiscover.model = preset.default_model || '';
      apiDiscover.bodyJson = JSON.stringify(preset.body || { prompt: PROMPT_TEMPLATE_HINT }, null, 2);
      apiDiscover.headersJson = JSON.stringify(preset.headers || {}, null, 2);
      if (preset.auth_header) authApiKeyHeader.value = preset.auth_header;
      if (preset.auth_query_param) authApiKeyQueryParam.value = preset.auth_query_param;
      if (!authOnly) {
        authUseBearer.value = preset.auth_header === 'Authorization';
      }
    }

    async function onDiscoverTransportChange() {
      G.persistDiscoverTransport(discoverTransport.value);
      if (discoverTransport.value === 'api') {
        await loadLlmApiPresets();
        if (!llmApiPresets.value.length) return;
        if (!llmApiPresets.value.find(p => p.id === apiDiscover.presetId)) {
          applyApiPreset('custom');
        } else if (!(apiDiscover.url || '').trim()) {
          applyApiPreset(apiDiscover.presetId);
        }
      }
    }

    function onApiPresetChange() {
      applyApiPreset(apiDiscover.presetId);
    }

    function onSettingsApiPreset(ev) {
      const id = ev.target?.value;
      if (!id) return;
      applyApiPreset(id);
      compCfg.submission.transport = 'api';
      compCfg.submission.api_url = apiDiscover.url;
      compCfg.submission.api_method = apiDiscover.method;
      compCfg.submission.api_response_path = apiDiscover.responsePath;
      compCfg.submission.api_model = apiDiscover.model;
      compCfg.submission.api_body_json = apiDiscover.bodyJson;
      compCfg.submission.api_headers_json = apiDiscover.headersJson;
    }

    const apiDiscoverJobId = ref(null);
    const apiDiscoverRunning = computed(() => {
      if (!apiDiscoverJobId.value) return false;
      const j = jobs.value.find(x => x.id === apiDiscoverJobId.value);
      return j && (j.status === 'running' || j.status === 'pending');
    });

    async function startApiDiscover() {
      if (apiNeedsAuth.value && !apiAuthReady.value) {
        alert('Save an API key in Step 1 (Target access) before connecting via API.');
        return;
      }
      const url = (apiDiscover.url || '').trim();
      if (url.includes(PROMPT_MODEL_HINT) && !(apiDiscover.model || '').trim()) {
        alert('Enter a model name - the API URL contains ' + PROMPT_MODEL_HINT);
        return;
      }
      let api_body = null;
      let api_headers = {};
      try { api_body = JSON.parse(apiDiscover.bodyJson || '{}'); } catch (e) {
        alert('Invalid request body JSON: ' + e.message);
        return;
      }
      try { api_headers = JSON.parse(apiDiscover.headersJson || '{}'); } catch (e) {
        alert('Invalid headers JSON: ' + e.message);
        return;
      }
      const transport = ['api_document', 'api_multipart'].includes(apiDiscover.transport)
        ? apiDiscover.transport
        : 'api';
      const j = await startJob('api_discover', {
        transport,
        api_url: url,
        upload_url: apiDiscover.uploadUrl,
        api_method: apiDiscover.method,
        api_response_path: apiDiscover.responsePath,
        api_model: (apiDiscover.model || '').trim(),
        api_body,
        api_headers,
      });
      apiDiscoverJobId.value = j.id;
    }

    const showDiscoverHelpModal = ref(false);

    function openDiscoverHelpModal() {
      showDiscoverHelpModal.value = true;
    }

    function closeDiscoverHelpModal() {
      showDiscoverHelpModal.value = false;
    }

    function openManualComponentSettings() {
      tab.value = 'settings';
      settingsTab.value = 'component';
      if (site.value && component.value) loadCompCfg();
    }

    function openManualComponentSettingsFromDiscoverHelp() {
      closeDiscoverHelpModal();
      openManualComponentSettings();
    }

    async function startManualDiscover() {
      const login = applyNormalizedLoginUrl();
      if (login) await persistComponentLoginUrl(login);
      const j = await startJob('manual_discover', {
        guided: guidedDiscovery.value,
        use_cdp: globalUseCdpBrowser.value
          || (guidedDiscovery.value && guidedDiscoveryUseCdp.value),
      });
      manualDiscoverJobId.value = j.id;
    }

    async function retryManualDiscover() {
      closeDiscoverHelpModal();
      await startManualDiscover();
    }

    const quickConnectOutcome = ref(null); // null | 'ok' | 'error'

    const quickConnectBusy = computed(() => {
      if (apiDiscoverRunning.value) return true;
      if (!manualDiscoverJobId.value) return false;
      const j = jobs.value.find(x => x.id === manualDiscoverJobId.value);
      return !!(j && (j.status === 'running' || j.status === 'pending'));
    });

    const canQuickConnect = computed(() => !!(site.value && component.value) && !quickConnectBusy.value);

    const quickConnectConnected = computed(() => {
      if (quickConnectBusy.value || quickConnectOutcome.value === 'error') return false;
      if (quickConnectOutcome.value === 'ok') return true;
      return !!(ctx.configOwnComplete && ctx.configOwnComplete.value);
    });

    const quickConnectFailed = computed(
      () => !quickConnectBusy.value && quickConnectOutcome.value === 'error',
    );

    const quickConnectTitle = computed(() => {
      if (quickConnectBusy.value) return 'Connecting…';
      if (quickConnectFailed.value) {
        return 'Connect failed - click to retry (uses last Connection type)';
      }
      if (quickConnectConnected.value) {
        return 'Connected - click to reconnect (uses last Connection type)';
      }
      return 'Quick connect - start Discovery or Connect via API (uses last Connection type)';
    });

    async function _onDiscoverJobTerminal(status) {
      if (status === 'done') {
        quickConnectOutcome.value = 'ok';
        if (typeof ctx.loadConfigStatus === 'function') {
          try { await ctx.loadConfigStatus(); } catch { /* ignore */ }
        }
        return;
      }
      if (status === 'failed' || status === 'cancelled') {
        quickConnectOutcome.value = 'error';
      }
    }

    watch(
      () => {
        const id = apiDiscoverJobId.value || manualDiscoverJobId.value;
        if (!id) return '';
        const j = jobs.value.find(x => x.id === id);
        return j ? `${j.id}:${j.status}` : '';
      },
      (sig, prev) => {
        if (!sig || sig === prev) return;
        const status = sig.split(':')[1];
        if (status === 'running' || status === 'pending') return;
        _onDiscoverJobTerminal(status);
      },
    );

    watch(
      () => `${site.value || ''}:${component.value || ''}`,
      () => {
        quickConnectOutcome.value = null;
      },
    );

    async function quickConnectFromHeader(opts) {
      if (!canQuickConnect.value) return;
      const auto = !!(opts && opts.auto);
      // Auto-connect (header component change): API endpoints only - never launch
      // Playwright for Browser UI. Explicit icon click may still use browser.
      if (auto && discoverTransport.value !== 'api') {
        return;
      }
      quickConnectOutcome.value = null;
      if (discoverTransport.value === 'api') {
        await onDiscoverTransportChange();
        if (!(apiDiscover.url || '').trim()) return;
        await startApiDiscover();
        return;
      }
      await startManualDiscover();
    }

    const api_out = {
      discoverTransport,
      applyDiscoverTransportPref,
      syncDiscoverTransportFromSubmission,
      guidedDiscovery,
      guidedDiscoveryUseCdp,
      effectiveGuidedDiscoveryUseCdp,
      onGuidedDiscoveryUseCdpChange,
      apiDiscover,
      loadLlmApiPresets,
      applyApiPreset,
      onDiscoverTransportChange,
      onApiPresetChange,
      onSettingsApiPreset,
      apiDiscoverJobId,
      apiDiscoverRunning,
      startApiDiscover,
      showDiscoverHelpModal,
      openDiscoverHelpModal,
      closeDiscoverHelpModal,
      openManualComponentSettings,
      openManualComponentSettingsFromDiscoverHelp,
      startManualDiscover,
      retryManualDiscover,
      quickConnectBusy,
      canQuickConnect,
      quickConnectConnected,
      quickConnectFailed,
      quickConnectTitle,
      quickConnectFromHeader,
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
