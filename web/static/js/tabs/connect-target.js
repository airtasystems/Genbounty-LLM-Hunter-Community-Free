/**
 * Domain module: useConnectTarget - Connect Target / auth / login / CDP /
 * Cloudflare / rate-limit resume / troubleshoot helpers.
 */
(function (G) {
  'use strict';

  G.useConnectTarget = function useConnectTarget(ctx) {
    const {
      authSaveError,
      authSaving,
      component,
      computed,
      jobs,
      nextTick,
      ref,
      runLoginUrl,
      site,
      watch,
    } = ctx;
    const api = G.api;

const loginJobId = ref(null);
const loginRunning = computed(() => {
  if (!loginJobId.value) return false;
  const j = jobs.value.find(x => x.id === loginJobId.value);
  return j && (j.status === 'running' || j.status === 'pending');
});
// panelOutputLines is created in useJobs (runs after this module in app-setup).
// Defer so the watch attaches once the computed exists; loginRunning is already on ctx.
queueMicrotask(() => {
  if (!ctx.panelOutputLines) return;
  watch(ctx.panelOutputLines, async () => {
    await nextTick();
    if (typeof ctx.maybeScrollOutputConsole === 'function') {
      ctx.maybeScrollOutputConsole();
    }
  });
});

const loginUrl = ref('');
const loginUseCdp = ref(false);

const globalUseCdpBrowser = computed(() => !!ctx.cfg?.USE_CDP_BROWSER);
const effectiveLoginUseCdp = computed(() => globalUseCdpBrowser.value || loginUseCdp.value);
const globalCdpBrowserMessage =
  'Chrome CDP is enabled globally in Settings → Browser Config → Browser. '
  + 'Connect Target login, browser discovery, and headed Attack use real Chrome (auto-launch, port 9222).';

function onLoginUseCdpChange(event) {
  if (globalUseCdpBrowser.value) return;
  loginUseCdp.value = !!event.target.checked;
}

const authConfigured = ref(false);
const authMode = ref(null);
const authLoginChoice = ref(null);
const authPublicSaving = ref(false);
const authApiKeySaving = ref(false);
const authApiKeyInput = ref('');
const authApiKeyError = ref('');
const authHasApiKey = ref(false);
const authScope = ref('none');
const authOwnConfigured = ref(false);
const authSharedFrom = ref('');
const authReuseOptions = ref([]);
const authReuseSaving = ref(false);
const authReuseError = ref('');
const configOwnComplete = ref(false);
const configReuseOptions = ref([]);
const configReuseSaving = ref(false);
const configReuseError = ref('');
const configCopiedFrom = ref('');
const discoverStartUrlSaving = ref(false);
const discoverStartUrlSaved = ref(false);
const discoverStartUrlError = ref('');
const showComponentStartUrlEditor = computed(() => {
  if (ctx.discoverTransport.value !== 'browser') return false;
  return !!configCopiedFrom.value;
});
const authApiKeyHeader = ref('Authorization');
const authApiKeyQueryParam = ref('');
const authUseBearer = ref(false);
const llmApiPresets = ref([]);
const selectedApiPreset = computed(() => {
  const id = ctx.apiDiscover.presetId;
  return llmApiPresets.value.find(p => p.id === id) || null;
});
const apiNeedsAuth = computed(() => {
  const p = selectedApiPreset.value;
  return !!(p && p.requires_auth);
});
const apiAuthReady = computed(() => {
  if (!apiNeedsAuth.value) return true;
  return authMode.value === 'api_key' && authHasApiKey.value;
});

function hostLooksLocal(host) {
  const h = String(host || '').toLowerCase();
  return (
    h === 'localhost'
    || h === '0.0.0.0'
    || h.startsWith('127.')
    || /^\d{1,3}(\.\d{1,3}){3}$/.test(h)
  );
}

/** Prepend https:// (http for local) and append .com when hostname has no TLD. */
function normalizeTargetAccessUrl(raw) {
  const original = String(raw || '').trim();
  if (!original) return '';
  let s = original;
  try {
    if (s.startsWith('//')) s = `https:${s}`;
    // Require "://" so host:port (e.g. localhost:3000) is not treated as a scheme.
    if (!s.includes('://')) {
      const hostPart = s.split('/')[0].split('?')[0].split('#')[0];
      const hostOnly = hostPart.includes('@') ? hostPart.split('@').pop() : hostPart;
      const hostname = String(hostOnly || '').replace(/:\d+$/, '');
      s = `${hostLooksLocal(hostname) ? 'http' : 'https'}://${s}`;
    }
    const u = new URL(s);
    if ((u.protocol === 'http:' || u.protocol === 'https:')
      && u.hostname
      && !hostLooksLocal(u.hostname)
      && !u.hostname.includes('.')) {
      // Rebuild instead of hostname setter - avoids engines dropping the TLD.
      const port = u.port ? `:${u.port}` : '';
      const rest = (u.pathname === '/' && !u.search && !u.hash)
        ? ''
        : `${u.pathname}${u.search}${u.hash}`;
      return `${u.protocol}//${u.hostname}.com${port}${rest}`;
    }
    let out = u.toString();
    if (u.pathname === '/' && !u.search && !u.hash) out = out.replace(/\/$/, '');
    return out || original;
  } catch {
    return original;
  }
}

async function persistComponentLoginUrl(url) {
  const target = String(url || '').trim();
  if (!target || !site.value || !component.value) return;
  try {
    const existing = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`
    );
    if ((existing.login_url || '').trim() === target) return;
    await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...existing, login_url: target }),
      }
    );
  } catch {
    /* non-fatal - discovery/login still normalize server-side */
  }
}

function applyNormalizedLoginUrl() {
  const next = normalizeTargetAccessUrl(loginUrl.value);
  if (next) {
    loginUrl.value = next;
    // Keep config in sync so a later loadAuthStatus/loadDiscoverContext
    // cannot overwrite the field with a pre-normalization value.
    ctx.compCfg.login_url = next;
    void persistComponentLoginUrl(next);
  }
  return loginUrl.value.trim();
}

function applyNormalizedStartUrl() {
  const next = normalizeTargetAccessUrl(ctx.compCfg.submission.start_url);
  if (next) ctx.compCfg.submission.start_url = next;
  return String(ctx.compCfg.submission.start_url || '').trim();
}

function defaultLoginUrlForSite(siteId) {
  if (!siteId) return '';
  return normalizeTargetAccessUrl(siteId);
}

function authApiPath(suffix) {
  if (!site.value || !component.value) return null;
  const s = encodeURIComponent(site.value);
  const c = encodeURIComponent(component.value);
  return `/api/sites/${s}/${c}${suffix}`;
}

function resetDiscoverAuthUi() {
  authApiKeyError.value = '';
  authApiKeyInput.value = '';
  loginJobId.value = null;
  authPublicSaving.value = false;
  authApiKeySaving.value = false;
}

async function loadAuthStatus(loginUrlOverride = '') {
  if (!site.value || !component.value) {
    authConfigured.value = false;
    authMode.value = null;
    authLoginChoice.value = null;
    authHasApiKey.value = false;
    authScope.value = 'none';
    authOwnConfigured.value = false;
    authSharedFrom.value = '';
    authReuseOptions.value = [];
    authReuseError.value = '';
    authApiKeyInput.value = '';
    loginUrl.value = '';
    return;
  }
  // Always normalize - stale config may be https://chatgpt without .com, and a
  // late loadAuthStatus must not undo a blur that just appended the TLD.
  const rawLogin = (loginUrlOverride || '').trim();
  loginUrl.value = rawLogin
    ? (normalizeTargetAccessUrl(rawLogin) || rawLogin)
    : defaultLoginUrlForSite(site.value);
  const statusPath = authApiPath('/auth-status');
  if (!statusPath) return;
  try {
    const s = await api(statusPath);
    authConfigured.value = s.configured;
    authMode.value = s.mode || null;
    authScope.value = s.scope || 'none';
    authOwnConfigured.value = !!s.own_configured;
    authSharedFrom.value = s.shared_from || '';
    authReuseOptions.value = Array.isArray(s.reuse_options) ? s.reuse_options : [];
    authReuseError.value = '';
    authHasApiKey.value = !!s.has_api_key;
    authApiKeyHeader.value = s.auth_header || 'Authorization';
    authApiKeyQueryParam.value = s.auth_query_param || '';
    authUseBearer.value = !!s.use_bearer;
    if (s.own_configured) {
      if (s.mode === 'none') authLoginChoice.value = false;
      else if (s.mode === 'api_key') authLoginChoice.value = 'api_key';
      else authLoginChoice.value = true;
    } else {
      authLoginChoice.value = null;
    }
  } catch {
    authConfigured.value = false;
    authMode.value = null;
    authLoginChoice.value = null;
    authHasApiKey.value = false;
    authScope.value = 'none';
    authOwnConfigured.value = false;
    authSharedFrom.value = '';
    authReuseOptions.value = [];
  }
}

async function reuseSiteAuth(opt) {
  authReuseError.value = '';
  const path = authApiPath('/auth/reuse');
  if (!path || !opt) return;
  authReuseSaving.value = true;
  try {
    await api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: opt.source,
        source_component: opt.component || '',
      }),
    });
    await loadAuthStatus(ctx.compCfg.login_url);
  } catch (e) {
    authReuseError.value = e.message || 'Could not copy auth.';
  } finally {
    authReuseSaving.value = false;
  }
}

async function loadConfigStatus() {
  if (!site.value || !component.value) {
    configOwnComplete.value = false;
    configReuseOptions.value = [];
    configReuseError.value = '';
    configCopiedFrom.value = '';
    return;
  }
  try {
    const s = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config/status`
    );
    configOwnComplete.value = !!s.own_complete;
    configReuseOptions.value = Array.isArray(s.reuse_options) ? s.reuse_options : [];
    configReuseError.value = '';
  } catch {
    configOwnComplete.value = false;
    configReuseOptions.value = [];
  }
}

async function reuseComponentConfig(opt) {
  configReuseError.value = '';
  if (!site.value || !component.value || !opt?.component) return;
  configReuseSaving.value = true;
  try {
    await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config/reuse`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_component: opt.component }),
      }
    );
    configCopiedFrom.value = opt.label || opt.component;
    discoverStartUrlSaved.value = false;
    discoverStartUrlError.value = '';
    await loadDiscoverContext();
  } catch (e) {
    configReuseError.value = e.message || 'Could not copy component config.';
  } finally {
    configReuseSaving.value = false;
  }
}

async function saveDiscoverStartUrl() {
  discoverStartUrlError.value = '';
  discoverStartUrlSaved.value = false;
  if (!site.value || !component.value) return;
  const url = applyNormalizedStartUrl();
  if (!url) {
    discoverStartUrlError.value = 'Enter a Start URL.';
    return;
  }
  discoverStartUrlSaving.value = true;
  try {
    const existing = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`
    );
    const payload = {
      ...existing,
      login_url: ctx.compCfg.login_url,
      submission: ctx.buildSubmissionPayload(),
    };
    await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: payload }),
      }
    );
    discoverStartUrlSaved.value = true;
    setTimeout(() => { discoverStartUrlSaved.value = false; }, 3000);
    configCopiedFrom.value = '';
    await loadConfigStatus();
    ctx.compCfgEmpty.value = !configOwnComplete.value;
  } catch (e) {
    discoverStartUrlError.value = e.message || 'Could not save Start URL.';
  } finally {
    discoverStartUrlSaving.value = false;
  }
}

function chooseAuthRequired() {
  authApiKeyError.value = '';
  authLoginChoice.value = true;
  if (!loginUrl.value.trim()) {
    loginUrl.value = (ctx.compCfg.login_url || '').trim() || defaultLoginUrlForSite(site.value);
  }
  applyNormalizedLoginUrl();
}

function chooseAuthApiKey() {
  authApiKeyError.value = '';
  authLoginChoice.value = 'api_key';
  if (ctx.discoverTransport.value === 'api' && ctx.apiDiscover.presetId) {
    ctx.applyApiPreset(ctx.apiDiscover.presetId, { authOnly: true });
  }
}

async function chooseAuthNotRequired() {
  if (!site.value || !component.value || authPublicSaving.value) return;
  const path = authApiPath('/auth/public');
  if (!path) return;
  authPublicSaving.value = true;
  try {
    await api(path, { method: 'POST' });
    await loadAuthStatus();
  } catch (e) {
    alert('Could not save public auth: ' + e.message);
  } finally {
    authPublicSaving.value = false;
  }
}

async function saveTargetApiKey() {
  if (!site.value || !component.value || authApiKeySaving.value) return;
  const path = authApiPath('/auth/api-key');
  if (!path) return;
  const key = authApiKeyInput.value.trim();
  if (!key) {
    authApiKeyError.value = 'Enter an API key.';
    return;
  }
  authApiKeySaving.value = true;
  authApiKeyError.value = '';
  try {
    await api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key: key,
        header_name: authApiKeyHeader.value,
        use_bearer: authUseBearer.value,
        query_param_name: authApiKeyQueryParam.value,
      }),
    });
    authApiKeyInput.value = '';
    await loadAuthStatus();
  } catch (e) {
    authApiKeyError.value = e.message || 'Could not save API key.';
  } finally {
    authApiKeySaving.value = false;
  }
}

async function resetAuthSetup() {
  if (!site.value || !component.value) return;
  const path = authApiPath('/auth');
  if (!path) return;
  try {
    await api(path, { method: 'DELETE' });
  } catch {
    /* no auth file yet - still show choice */
  }
  authConfigured.value = false;
  authMode.value = null;
  authLoginChoice.value = null;
  authHasApiKey.value = false;
  authScope.value = 'none';
  authOwnConfigured.value = false;
  authSharedFrom.value = '';
  authReuseOptions.value = [];
  authReuseError.value = '';
  authApiKeyInput.value = '';
  authApiKeyError.value = '';
  await loadAuthStatus(ctx.compCfg.login_url);
}

async function checkSetupAndNavigate() {
  if (!site.value || !component.value) return;
  await loadAuthStatus();
  try {
    await api(`/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`);
  } catch { /* ignore */ }
}

function applyDiscoverTransportPref() {
  if (typeof ctx.applyDiscoverTransportPref === 'function') {
    ctx.applyDiscoverTransportPref();
  } else if (ctx.discoverTransport) {
    ctx.discoverTransport.value = G.preferredDiscoverTransport();
  }
}

async function loadDiscoverContext() {
  resetDiscoverAuthUi();
  if (!site.value || !component.value) {
    applyDiscoverTransportPref();
    ctx.compCfgEmpty.value = true;
    authConfigured.value = false;
    authMode.value = null;
    authLoginChoice.value = null;
    authHasApiKey.value = false;
    authScope.value = 'none';
    configCopiedFrom.value = '';
    return;
  }
  try {
    const data = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`
    );
    ctx.compCfg.login_url = data.login_url || '';
    await loadAuthStatus(ctx.compCfg.login_url);
    ctx.applySubmissionToCompCfg(data.submission);
    await loadConfigStatus();
    ctx.compCfgEmpty.value = !configOwnComplete.value;
  } catch {
    applyDiscoverTransportPref();
    ctx.compCfgEmpty.value = true;
    configOwnComplete.value = false;
    configReuseOptions.value = [];
    await loadAuthStatus();
  }
  if (ctx.discoverTransport.value === 'api') {
    await ctx.onDiscoverTransportChange();
  }
}

async function onComponentChange() {
  ctx.manualDiscoverJobId.value = null;
  if (ctx.apiDiscoverJobId) ctx.apiDiscoverJobId.value = null;
  ctx.reconJobId.value = null;
  ctx.reconReportPath.value = '';
  configCopiedFrom.value = '';
  discoverStartUrlSaved.value = false;
  discoverStartUrlError.value = '';
  ctx.intelSelectedId.value = '';
  ctx.intelFiles.value = [];
  ctx.intelRecord.value = null;
  ctx.intelJsonText.value = '';
  ctx.intelExists.value = false;
  ctx.intelDirty.value = false;
  ctx.intelMsg.value = '';
  ctx.intelError.value = '';
  ctx.notesRecord.value = ctx.emptyNotesTemplate();
  ctx.notesJsonText.value = '';
  ctx.notesExists.value = false;
  ctx.notesDirty.value = false;
  ctx.notesMsg.value = '';
  ctx.notesError.value = '';
  ctx.notesDraftTitle.value = '';
  ctx.notesDraftBody.value = '';
  ctx.persistContextSelection();
  await loadDiscoverContext();
  await ctx.loadContext();
  await checkSetupAndNavigate();
  if (ctx._autoConnectOnComponentChange) {
    ctx._autoConnectOnComponentChange = false;
    // API endpoints only - never auto-launch Playwright for Browser UI components.
    if (
      component.value
      && ctx.discoverTransport
      && ctx.discoverTransport.value === 'api'
      && typeof ctx.quickConnectFromHeader === 'function'
    ) {
      await ctx.quickConnectFromHeader({ auto: true });
    }
  }
}

async function startLogin(url) {
  const raw = (typeof url === 'string' ? url : '') || loginUrl.value;
  const targetUrl = normalizeTargetAccessUrl(raw);
  if (!targetUrl || !site.value) return;
  loginUrl.value = targetUrl;
  ctx.compCfg.login_url = targetUrl;
  await persistComponentLoginUrl(targetUrl);
  const j = await ctx.startJob('login', { url: targetUrl, use_cdp: effectiveLoginUseCdp.value });
  loginJobId.value = j.id;
}

async function prepareAuthForLoginCapture() {
  if (authMode.value === 'none') {
    const clearPath = authApiPath('/auth');
    if (clearPath) {
      await api(clearPath, { method: 'DELETE' });
    }
    authConfigured.value = false;
    authMode.value = null;
    authScope.value = 'none';
  }
  authLoginChoice.value = true;
}

async function confirmRunLogin() {
  authSaveError.value = '';
  const url = normalizeTargetAccessUrl(runLoginUrl.value || loginUrl.value);
  if (!url) return;
  loginUrl.value = url;
  runLoginUrl.value = url;
  await prepareAuthForLoginCapture();
  await startLogin(url);
}

async function saveAuth() {
  if (!loginJobId.value || authSaving.value) return;
  authSaving.value = true;
  authSaveError.value = '';
  try {
    await api(`/api/jobs/${loginJobId.value}/stdin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: '\n' })
    });
    await new Promise(r => setTimeout(r, 1200));
    await loadAuthStatus();
    if (authMode.value !== 'session') {
      authSaveError.value = 'Auth was not saved. Finish sign-in in the browser, then try again.';
      return;
    }
    if (ctx.pendingRunAfterLogin?.value) {
      ctx.showRunLoginModal.value = false;
      ctx.runBlockedInfo.value = null;
      ctx.pendingRunAfterLogin.value = false;
      await ctx.startRunTests();
    }
  } catch (e) {
    authSaveError.value = e.message || 'Could not save auth.';
  } finally {
    authSaving.value = false;
  }
}

function dismissRunLoginModal() {
  if (ctx.showRunLoginModal) ctx.showRunLoginModal.value = false;
}

function dismissRunRateLimitModal() {
  if (ctx.rateLimitWaiting?.value) return;
  if (ctx.showRunRateLimitModal) ctx.showRunRateLimitModal.value = false;
}

function resetRunCloudflareState() {
  if (ctx.runCloudflareStopIssued) ctx.runCloudflareStopIssued.value = false;
  if (ctx.runCloudflareModalShown) ctx.runCloudflareModalShown.value = false;
  if (ctx.runCloudflareTestsStopped) ctx.runCloudflareTestsStopped.value = false;
  if (ctx.runCloudflareSaving) ctx.runCloudflareSaving.value = false;
  if (ctx.runCloudflareError) ctx.runCloudflareError.value = '';
  if (ctx.runCloudflareSettings) {
    ctx.runCloudflareSettings.FETCH_METHOD = 'pool';
    ctx.runCloudflareSettings.HEADLESS = false;
    ctx.runCloudflareSettings.cloudflare_headed = true;
  }
}

async function stopActiveRunTests(reason) {
  const jid = ctx.activeJobs.run_tests;
  if (!jid || ctx.runCloudflareStopIssued?.value) return;
  ctx.runCloudflareStopIssued.value = true;
  if (ctx.runCloudflareTestsStopped) ctx.runCloudflareTestsStopped.value = true;
  try {
    await ctx.cancelJob(jid);
  } catch (e) {
    if (ctx.runCloudflareError) ctx.runCloudflareError.value = reason || String(e);
  }
}

async function skipCurrentRunPrompt() {
  const jid = ctx.activeJobs.run_tests;
  if (!jid || ctx.runSkipCurrentBusy?.value || !ctx.canSkipCurrentRunPrompt?.value) return;
  ctx.runSkipCurrentBusy.value = true;
  try {
    await api(`/api/jobs/${jid}/stdin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: `${JSON.stringify({ type: 'skip_current' })}\n` }),
    });
  } catch (e) {
    console.error('Skip current prompt failed', e);
  } finally {
    ctx.runSkipCurrentBusy.value = false;
  }
}

function handleRunCloudflareBlocked(p) {
  const needsSettings = !!p.needs_headed_browser;
  const shouldStop = needsSettings || !!(p.stop_run || p.fatal);
  if (shouldStop) {
    void stopActiveRunTests(
      needsSettings
        ? 'Cloudflare requires a visible browser (Headless off).'
        : 'Cloudflare verification did not complete in time.',
    );
  } else if (ctx.pendingRunAfterCloudflare) {
    ctx.pendingRunAfterCloudflare.value = true;
  }
  if (ctx.runCloudflareModalShown && !ctx.runCloudflareModalShown.value) {
    ctx.runCloudflareModalShown.value = true;
    if (ctx.showRunCloudflareModal) ctx.showRunCloudflareModal.value = true;
  }
}

function onCloudflareBackdropClick() {
  if (!ctx.cloudflareModalNeedsSettings?.value) dismissRunCloudflareModal();
}

function dismissRunCloudflareModal() {
  if (ctx.showRunCloudflareModal) ctx.showRunCloudflareModal.value = false;
  if (ctx.pendingRunAfterCloudflare) ctx.pendingRunAfterCloudflare.value = false;
}

async function cancelRunTestsFromCloudflare() {
  await stopActiveRunTests('Stopped from Cloudflare dialog.');
  dismissRunCloudflareModal();
}

async function rerunAfterCloudflareTimeout() {
  dismissRunCloudflareModal();
  resetRunCloudflareState();
  await ctx.startRunTests();
}

async function applyCloudflareSettingsAndRerun() {
  if (!site.value || !component.value) return;
  if (ctx.runCloudflareError) ctx.runCloudflareError.value = '';
  if (ctx.runCloudflareSaving) ctx.runCloudflareSaving.value = true;
  try {
    const s = encodeURIComponent(site.value);
    const c = encodeURIComponent(component.value);
    const existing = await api(`/api/sites/${s}/${c}/config`);
    const cf = ctx.runCloudflareSettings || {};
    const settings = { ...(existing.settings || {}), FETCH_METHOD: cf.FETCH_METHOD };
    settings.HEADLESS = !!cf.HEADLESS;
    settings.POOL_CLUSTER_USE_STEALTH = true;
    settings.POOL_CLUSTER_USE_HUMAN_CONTEXT = true;
    const submission = { ...(existing.submission || {}) };
    if (cf.cloudflare_headed) {
      submission.cloudflare_headed = true;
    } else {
      delete submission.cloudflare_headed;
    }
    await api(`/api/sites/${s}/${c}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: { ...existing, settings, submission } }),
    });
    dismissRunCloudflareModal();
    resetRunCloudflareState();
    await ctx.startRunTests();
  } catch (e) {
    if (ctx.runCloudflareError) ctx.runCloudflareError.value = String(e);
  } finally {
    if (ctx.runCloudflareSaving) ctx.runCloudflareSaving.value = false;
  }
}

function _clearRateLimitTimer() {
  // rateLimitTimer is a plain let on settings - keep the live handle on ctx.
  if (ctx.rateLimitTimer) {
    clearInterval(ctx.rateLimitTimer);
    ctx.rateLimitTimer = null;
  }
}

async function confirmRateLimitResume() {
  if (ctx.rateLimitWaiting?.value) return;
  const total = Math.max(1, Math.round(Number(ctx.runRateLimitBackoffSec?.value) || 60));
  ctx.rateLimitWaiting.value = true;
  ctx.rateLimitCountdown.value = total;
  _clearRateLimitTimer();
  ctx.rateLimitTimer = setInterval(() => {
    ctx.rateLimitCountdown.value = Math.max(0, ctx.rateLimitCountdown.value - 1);
    if (ctx.rateLimitCountdown.value <= 0) _clearRateLimitTimer();
  }, 1000);
  await new Promise(r => setTimeout(r, total * 1000));
  _clearRateLimitTimer();
  ctx.rateLimitWaiting.value = false;
  if (ctx.showRunRateLimitModal) ctx.showRunRateLimitModal.value = false;
  if (ctx.runBlockedInfo) ctx.runBlockedInfo.value = null;
  const shouldResume = !!ctx.pendingRunAfterRateLimit?.value;
  if (ctx.pendingRunAfterRateLimit) ctx.pendingRunAfterRateLimit.value = false;
  if (shouldResume) await ctx.startRunTests();
}

function onRunTroubleshoot() {
  if (ctx.runBlockedInfo?.value?.kind === 'login_required') {
    if (ctx.showRunLoginModal) ctx.showRunLoginModal.value = true;
    return;
  }
  if (ctx.runBlockedInfo?.value?.kind === 'rate_limited') {
    if (ctx.showRunRateLimitModal) ctx.showRunRateLimitModal.value = true;
    return;
  }
  if (ctx.runBlockedInfo?.value?.kind === 'cloudflare') {
    if (ctx.showRunCloudflareModal) ctx.showRunCloudflareModal.value = true;
    return;
  }
  ctx.showRunTroubleshoot.value = true;
}

async function sendLoginEnter() {
  if (loginJobId.value) {
    await api(`/api/jobs/${loginJobId.value}/stdin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: '\n' })
    });
    await new Promise(r => setTimeout(r, 1200));
    await loadAuthStatus();
  }
}

    const api_out = {
      loginJobId,
      loginRunning,
      loginUrl,
      loginUseCdp,
      globalUseCdpBrowser,
      effectiveLoginUseCdp,
      globalCdpBrowserMessage,
      onLoginUseCdpChange,
      authConfigured,
      authMode,
      authLoginChoice,
      authPublicSaving,
      authApiKeySaving,
      authApiKeyInput,
      authApiKeyError,
      authHasApiKey,
      authScope,
      authOwnConfigured,
      authSharedFrom,
      authReuseOptions,
      authReuseSaving,
      authReuseError,
      configOwnComplete,
      configReuseOptions,
      configReuseSaving,
      configReuseError,
      configCopiedFrom,
      discoverStartUrlSaving,
      discoverStartUrlSaved,
      discoverStartUrlError,
      showComponentStartUrlEditor,
      authApiKeyHeader,
      authApiKeyQueryParam,
      authUseBearer,
      llmApiPresets,
      selectedApiPreset,
      apiNeedsAuth,
      apiAuthReady,
      hostLooksLocal,
      normalizeTargetAccessUrl,
      persistComponentLoginUrl,
      applyNormalizedLoginUrl,
      applyNormalizedStartUrl,
      defaultLoginUrlForSite,
      authApiPath,
      resetDiscoverAuthUi,
      loadAuthStatus,
      reuseSiteAuth,
      loadConfigStatus,
      reuseComponentConfig,
      saveDiscoverStartUrl,
      chooseAuthRequired,
      chooseAuthApiKey,
      chooseAuthNotRequired,
      saveTargetApiKey,
      resetAuthSetup,
      checkSetupAndNavigate,
      loadDiscoverContext,
      onComponentChange,
      startLogin,
      prepareAuthForLoginCapture,
      confirmRunLogin,
      saveAuth,
      dismissRunLoginModal,
      dismissRunRateLimitModal,
      resetRunCloudflareState,
      stopActiveRunTests,
      skipCurrentRunPrompt,
      handleRunCloudflareBlocked,
      onCloudflareBackdropClick,
      dismissRunCloudflareModal,
      cancelRunTestsFromCloudflare,
      rerunAfterCloudflareTimeout,
      applyCloudflareSettingsAndRerun,
      _clearRateLimitTimer,
      confirmRateLimitResume,
      onRunTroubleshoot,
      sendLoginEnter
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
