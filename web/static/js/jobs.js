/**
 * Domain module: useJobs
 */
(function (G) {
  'use strict';

  G.useJobs = function useJobs(ctx) {
    const {
      activeJobs,
      activePlaybookId,
      allPlaybooks,
      allStrategies,
      closeEnhanceTheoryModal,
      component,
      components,
      computed,
      findTabJob,
      jobById,
      jobIsActive,
      jobs,
      jobsOpen,
      logs,
      nextTick,
      onMounted,
      openEnhanceTheoryReview,
      pbCatalog,
      pbEnsureCategoryDefaults,
      pbForm,
      pbPresetCatalog,
      pbRecordCat,
      pendingRunAfterCloudflare,
      pendingRunAfterLogin,
      pendingRunAfterRateLimit,
      playCategoryTree,
      previewUrlFor,
      reactive,
      ref,
      runBlockedInfo,
      runCloudflareModalShown,
      runJob,
      runJobActive,
      runLivePanelOpen,
      runLoginUrl,
      runPreviewBySlot,
      runPreviewConfig,
      runPreviewImgRetries,
      runPreviewModalSlot,
      ensureRunPreviewSlots,
      initRunPreviewConfig,
      runProgress,
      runProgressClock,
      ensureRunProgressClock,
      stopRunProgressClock,
      runRateLimitBackoffSec,
      runStrategies,
      runSubmissionTransport,
      runTestFiles,
      settingsTab,
      showRunCloudflareModal,
      showRunLoginModal,
      showRunPreviewModal,
      showRunRateLimitModal,
      site,
      sites,
      sseConnections,
      strategyRequiresMultiTurn,
      tab,
      watch
    } = ctx;
    const api = G.api;
    const isAbortError = G.isAbortError;
    const lineClass = G.lineClass;
    const pretty = G.pretty;
    const prettyJobType = G.prettyJobType;

const jobsDrawerSummary = computed(() => {
  const list = jobs.value || [];
  const counts = {
    running: 0,
    pending: 0,
    awaiting_theory: 0,
    done: 0,
    failed: 0,
    cancelled: 0,
  };
  for (const j of list) {
    const s = String(j.status || '');
    if (Object.prototype.hasOwnProperty.call(counts, s)) counts[s] += 1;
    else if (jobIsActive(s)) counts.running += 1;
  }

  let tone = 'idle';
  if (counts.running || counts.pending) tone = 'active';
  else if (counts.awaiting_theory) tone = 'waiting';
  else if (counts.failed) tone = 'failed';
  else if (counts.done) tone = 'done';

  const chipOrder = [
    ['running', 'running'],
    ['pending', 'pending'],
    ['awaiting_theory', 'awaiting'],
    ['failed', 'failed'],
    ['done', 'done'],
    ['cancelled', 'cancelled'],
  ];
  const chips = chipOrder
    .filter(([key]) => counts[key] > 0)
    .map(([key, label]) => ({ key, label, count: counts[key] }));

  const focusJob = list.find((j) => jobIsActive(j.status)) || list[0] || null;
  let focus = `${list.length} total`;
  if (focusJob) {
    const typeLabel = prettyJobType(focusJob.type);
    const scope = [focusJob.site, focusJob.component].filter(Boolean).join('/');
    const idShort = String(focusJob.id || '').slice(0, 8);
    focus = [typeLabel, scope, focusJob.status, idShort ? `#${idShort}` : '']
      .filter(Boolean)
      .join(' · ');
  }

  return {
    tone,
    chips,
    focus,
    total: list.length,
    active: counts.running + counts.pending + counts.awaiting_theory,
  };
});

function updateRunPreview(jobId, slot = 0, opts = {}) {
  if (!jobId) return;
  const s = Number(slot) || 0;
  const sequence = opts.sequence;
  const url = previewUrlFor(jobId, s, {
    sequence,
    site: site.value,
    component: component.value,
    bust: opts.forceRefresh ? Date.now() : undefined,
  });
  // Always key by real worker slot so pool/cluster frames are not collapsed.
  ensureRunPreviewSlots(s);
  const parallel = (runPreviewConfig.value?.slotCount || 1) > 1
    || runPreviewConfig.value?.mode === 'parallel'
    || s > 0;
  const entry = {
    slot: s,
    url,
    jobId,
    sequence,
    label: parallel ? `Worker ${s + 1}` : 'Browser',
  };
  runPreviewBySlot.value = {
    ...runPreviewBySlot.value,
    [s]: entry,
  };
}

function clearRunPreviews() {
  runPreviewBySlot.value = {};
  runPreviewImgRetries.value = {};
  closeRunPreviewModal();
}

function openRunPreviewModal(preview, slot = null) {
  if (!preview && slot == null) return;
  const s = slot ?? preview?.slot ?? 0;
  runPreviewModalSlot.value = s;
  // Refresh capacity from settings so pool=N opens N panes even before every worker frames.
  Promise.resolve(initRunPreviewConfig()).catch(() => {});
  showRunPreviewModal.value = true;
}

function closeRunPreviewModal() {
  showRunPreviewModal.value = false;
  runPreviewModalSlot.value = 0;
}

function formatRunEta(sec) {
  if (sec == null || sec === '' || Number.isNaN(Number(sec))) return '-';
  const n = Number(sec);
  if (n <= 0) return '~0s';
  if (n < 90) return `~${Math.round(n)}s`;
  const m = Math.floor(n / 60);
  const s = Math.round(n % 60);
  return `~${m}m ${s}s`;
}

const ENHANCE_PHASE_LABELS = {
  freeze: 'Freeze',
  escalate: 'Escalate',
  cool_down: 'Cool-down',
  hard_refusal: 'Hard-refusal',
  theory: 'Theory',
  bounty_invent: 'Bounty invent',
  bounty_mutate: 'Bounty mutate',
  open_broaden: 'Open broaden',
};

const WAR_ROOM_COMMS_CAP = 6;
const WAR_ROOM_TRAFFIC_CAP = 50;
const warRoomActive = ctx.warRoomActive || ref(false);
const warRoomHasSnapshot = ctx.warRoomHasSnapshot || ref(false);
const warRoomMeta = ctx.warRoomMeta || ref(null);
const warRoomProgress = ctx.warRoomProgress || ref(null);
const warRoomOutcomes = ctx.warRoomOutcomes || ref({ ok: 0, rejected: 0, other: 0 });
const warRoomRiskCounts = ctx.warRoomRiskCounts || ref({
  critical: 0,
  high: 0,
  medium: 0,
  low: 0,
  informational: 0,
  indeterminate: 0,
  other: 0,
});
const warRoomFeed = ctx.warRoomFeed || ref([]);
const warRoomQaFeed = ctx.warRoomQaFeed || ref([]);
const warRoomStartedAt = ctx.warRoomStartedAt || ref(null);
const warRoomTick = ctx.warRoomTick || ref(0);
let warRoomClockTimer = null;
ctx.warRoomActive = warRoomActive;
ctx.warRoomHasSnapshot = warRoomHasSnapshot;
ctx.warRoomMeta = warRoomMeta;
ctx.warRoomProgress = warRoomProgress;
ctx.warRoomOutcomes = warRoomOutcomes;
ctx.warRoomRiskCounts = warRoomRiskCounts;
ctx.warRoomFeed = warRoomFeed;
ctx.warRoomQaFeed = warRoomQaFeed;
ctx.warRoomStartedAt = warRoomStartedAt;
ctx.warRoomTick = warRoomTick;

function warRoomStopClock() {
  if (warRoomClockTimer != null) {
    clearInterval(warRoomClockTimer);
    warRoomClockTimer = null;
  }
}

function warRoomStartClock() {
  warRoomStartedAt.value = Date.now();
  warRoomTick.value = Date.now();
  warRoomStopClock();
  warRoomClockTimer = setInterval(() => {
    if (!warRoomActive.value) return;
    warRoomTick.value = Date.now();
  }, 1000);
}

function _warRoomHasTiming(v) {
  return v != null && v !== '' && Number.isFinite(Number(v));
}

function warRoomTruncate(s, n = 96) {
  const t = String(s || '').replace(/\s+/g, ' ').trim();
  if (t.length <= n) return t;
  return `${t.slice(0, n - 1)}…`;
}

function warRoomNormalizeOutcome(outcome) {
  const o = String(outcome || '').toLowerCase().trim();
  if (!o) return 'other';
  if (o === 'ok' || o === 'accepted' || o === 'success' || o === 'submitted') return 'ok';
  if (o.includes('reject') || o === 'blocked' || o === 'denied' || o === 'refused') {
    return 'rejected';
  }
  return 'other';
}

function warRoomNormalizeRisk(level) {
  const l = String(level || '').toLowerCase().trim();
  if (['critical', 'high', 'medium', 'low', 'informational', 'indeterminate'].includes(l)) {
    return l;
  }
  if (l === 'info') return 'informational';
  if (!l || l === 'unknown') return 'indeterminate';
  return 'other';
}

function warRoomPushFeed(kind, title, detail) {
  const entry = {
    ts: Date.now(),
    kind: String(kind || 'event'),
    title: String(title || ''),
    detail: detail ? String(detail) : '',
  };
  warRoomFeed.value = [entry, ...(warRoomFeed.value || [])].slice(0, WAR_ROOM_COMMS_CAP);
}

function warRoomPushQa(entry) {
  const row = {
    ts: Date.now(),
    label: String(entry?.label || ''),
    id: String(entry?.id || ''),
    prompt: String(entry?.prompt || ''),
    response: String(entry?.response || ''),
    judgeReasoning: String(entry?.judgeReasoning || ''),
    outcome: String(entry?.outcome || ''),
    riskLevel: String(entry?.riskLevel || ''),
    reportPath: String(entry?.reportPath || ''),
  };
  warRoomQaFeed.value = [row, ...(warRoomQaFeed.value || [])].slice(0, WAR_ROOM_TRAFFIC_CAP);
}

function warRoomEmptyOutcomes() {
  return { ok: 0, rejected: 0, other: 0 };
}

function warRoomEmptyRiskCounts() {
  return {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    informational: 0,
    indeterminate: 0,
    other: 0,
  };
}

function warRoomIsMonitoredJob(j) {
  if (!j) return false;
  if ((j.type === 'run_tests' || j.type === 'enhance_loop') && activeJobs.run_tests === j.id) {
    return true;
  }
  if (j.type === 'security_assess' && activeJobs.security_assess === j.id) {
    return true;
  }
  return false;
}

function warRoomResetForJob(j, feedTitle) {
  if (!j) return;
  const p = j.params || {};
  warRoomActive.value = true;
  warRoomHasSnapshot.value = true;
  warRoomMeta.value = {
    jobId: j.id,
    jobType: j.type,
    site: p.site || site.value || '',
    component: p.component || component.value || '',
    strategy: String(p.strategy || p.suite || '').trim(),
    playbook: String(p.playbook || '').trim(),
    status: j.status || 'running',
  };
  warRoomProgress.value = null;
  warRoomOutcomes.value = warRoomEmptyOutcomes();
  warRoomRiskCounts.value = warRoomEmptyRiskCounts();
  warRoomFeed.value = [];
  warRoomQaFeed.value = [];
  warRoomStartClock();
  const title = feedTitle
    || (j.type === 'enhance_loop'
      ? 'Enhance started'
      : j.type === 'security_assess'
        ? 'Analysis started'
        : 'Run started');
  warRoomPushFeed('start', title, '');
}

function warRoomEnsureMeta(j) {
  if (!j) return;
  if (!warRoomMeta.value || warRoomMeta.value.jobId !== j.id) {
    warRoomResetForJob(j);
    return;
  }
  warRoomActive.value = true;
  warRoomHasSnapshot.value = true;
  warRoomMeta.value = {
    ...warRoomMeta.value,
    status: j.status || warRoomMeta.value.status,
  };
}

function warRoomSetStatus(status) {
  if (!warRoomMeta.value) return;
  warRoomMeta.value = { ...warRoomMeta.value, status: String(status || warRoomMeta.value.status) };
}

function warRoomSyncProgress(p, pct, phase) {
  const prev = warRoomProgress.value || {};
  const cur = p?.current != null ? p.current : (p?.round != null ? p.round : null);
  const inFlight = p?.in_flight != null ? Number(p.in_flight) : prev.in_flight;
  warRoomProgress.value = {
    ...prev,
    ...(p || {}),
    pct: pct != null ? pct : (p && p.pct != null ? p.pct : prev.pct),
    phase: phase || (p && p.phase) || prev.phase || '',
    current: cur != null ? cur : prev.current,
    total: p?.total != null ? p.total : prev.total,
    round: p?.round != null ? p.round : prev.round,
    in_flight: Number.isFinite(inFlight) ? inFlight : 0,
    status: p?.status != null ? p.status : prev.status,
    // Enhance-round / theory events omit timing - keep last known SSE values.
    elapsed_sec: _warRoomHasTiming(p?.elapsed_sec) ? Number(p.elapsed_sec) : prev.elapsed_sec,
    eta_sec: _warRoomHasTiming(p?.eta_sec) ? Number(p.eta_sec) : prev.eta_sec,
    enhance_phase: p?.enhance_phase || p?.enhancePhase || prev.enhance_phase,
    mode: p?.mode != null ? p.mode : prev.mode,
    _localElapsedAt: Date.now(),
  };
}

function _warRoomSoftRiskPct(p, fallback = 0) {
  const total = Number(p?.total) || 0;
  const cur = Number(p?.current) || 0;
  const inflight = Number(p?.in_flight) || 0;
  if (!(total > 0)) return fallback;
  return Math.min(99, Math.round(((cur + inflight * 0.4) / total) * 100));
}

function warRoomOnProgress(j, p, opts) {
  if (!j || !p || !opts) return;
  const { isCampaign, isRisk } = opts;
  if (!isCampaign && !isRisk) return;
  // After Stop/cancel, ignore late progress so TRAFFIC is not wiped mid-assess.
  const st = String(j.status || '').toLowerCase();
  if (st === 'cancelled' || st === 'failed') return;

  if (p.type === 'run_start') {
    warRoomResetForJob(j, j.type === 'enhance_loop' ? 'Enhance started' : 'Run started');
    warRoomSyncProgress(p, 0, 'submit');
    return;
  }
  if (p.type === 'suite' && (Number(p.current) || 0) <= 1) {
    warRoomResetForJob(j, 'Suite started');
    const total = p.total || 0;
    const cur = p.current || 0;
    const pct = total ? Math.min(100, Math.round((cur / total) * 100)) : 0;
    warRoomSyncProgress(p, pct, 'suite');
    warRoomPushFeed('suite', `Suite ${cur}/${total || '?'}`, warRoomTruncate(p.label || p.suite || ''));
    return;
  }

  warRoomEnsureMeta(j);

  if (p.type === 'theory_review' || p.phase === 'theory') {
    if (ctx.pipelineBusy?.value) {
      warRoomSetStatus('running');
      warRoomSyncProgress(p, 0, 'enhance');
      warRoomPushFeed('theory', 'Theory auto-accepted (pipeline)', '');
      return;
    }
    warRoomSetStatus('awaiting_theory');
    warRoomSyncProgress(p, 0, 'theory');
    warRoomPushFeed('theory', 'Awaiting theory confirmation', '');
    return;
  }
  if (p.type === 'theory_auto_accepted') {
    warRoomSetStatus('running');
    warRoomSyncProgress(p, p.pct ?? warRoomProgress.value?.pct ?? 0, 'enhance');
    warRoomPushFeed('theory', 'Theory auto-accepted', '');
    return;
  }
  if (p.type === 'cloudflare_wait' || (p.type === 'blocked' && (p.kind === 'cloudflare' || p.action === 'prompt_cloudflare'))) {
    warRoomSyncProgress(p, warRoomProgress.value?.pct ?? 0, 'blocked');
    warRoomPushFeed('blocker', 'Cloudflare wait', p.remaining_sec != null ? `${p.remaining_sec}s remaining` : '');
    return;
  }
  if (p.type === 'blocked') {
    warRoomSyncProgress(p, warRoomProgress.value?.pct ?? 0, 'blocked');
    warRoomPushFeed('blocker', `Blocked · ${p.kind || p.action || 'pause'}`, warRoomTruncate(p.message || p.detail || ''));
    return;
  }
  if (p.type === 'probe_result' && isCampaign) {
    const total = p.total || 0;
    const cur = p.current || 0;
    const pct = total ? Math.min(100, Math.round((cur / total) * 100)) : 0;
    if (cur === 1) {
      warRoomOutcomes.value = warRoomEmptyOutcomes();
      warRoomQaFeed.value = [];
    }
    const bucket = warRoomNormalizeOutcome(p.submission_outcome);
    warRoomOutcomes.value = {
      ...warRoomOutcomes.value,
      [bucket]: (warRoomOutcomes.value[bucket] || 0) + 1,
    };
    warRoomSyncProgress(p, pct, 'submit');
    const label = p.label || `#${cur}`;
    warRoomPushFeed(
      'probe',
      `${label} → ${p.submission_outcome || bucket}`,
      warRoomTruncate(p.input || ''),
    );
    // TRAFFIC only shows assessed rows (risk_result); COMMS still gets probes.
    return;
  }
  if (p.type === 'enhance_round') {
    const total = p.total || 1;
    const cur = p.current || 1;
    const pct = Math.min(95, Math.round(((cur - 0.5) / total) * 100));
    warRoomSyncProgress(p, pct, 'enhance');
    const phase = String(p.enhance_phase || '').trim();
    warRoomPushFeed(
      'enhance',
      `Enhance round ${cur}/${total}`,
      phase ? (ENHANCE_PHASE_LABELS[phase] || phase) : '',
    );
    return;
  }
  if (p.type === 'enhance_result') {
    const total = p.total || warRoomProgress.value?.total || 1;
    const cur = p.round || p.current || 1;
    const pct = Math.min(100, Math.round((cur / total) * 100));
    warRoomSyncProgress(p, pct, 'enhance');
    warRoomPushFeed('enhance', `Round ${cur} result`, warRoomTruncate(p.worst || ''));
    return;
  }
  if (p.type === 'risk_result') {
    const total = p.total || 0;
    const cur = p.current || 0;
    const inflight = p.in_flight != null
      ? Number(p.in_flight)
      : Math.max(0, (warRoomProgress.value?.in_flight || 1) - 1);
    const pct = _warRoomSoftRiskPct({ ...p, in_flight: inflight }, warRoomProgress.value?.pct ?? 0);
    if (cur === 1) {
      warRoomRiskCounts.value = warRoomEmptyRiskCounts();
      warRoomQaFeed.value = [];
    }
    const level = warRoomNormalizeRisk(p.risk_level);
    warRoomRiskCounts.value = {
      ...warRoomRiskCounts.value,
      [level]: (warRoomRiskCounts.value[level] || 0) + 1,
    };
    warRoomSyncProgress({ ...p, in_flight: inflight }, pct, 'risk');
    const label = p.label || `#${cur}`;
    warRoomPushFeed(
      'risk',
      `${String(p.risk_level || level).toUpperCase()} · ${label}`,
      warRoomTruncate(p.outcome || p.exploit_status || ''),
    );
    if (p.input || p.response || p.prompt || p.judge_reasoning) {
      warRoomPushQa({
        label,
        id: p.id || '',
        prompt: p.input || p.prompt || '',
        response: p.response || '',
        judgeReasoning: p.judge_reasoning || '',
        outcome: p.outcome || p.exploit_status || '',
        riskLevel: p.risk_level || level,
        reportPath: ctx.selectedRiskReportPath?.value
          || ctx.riskViewMeta?.value?.reportPath
          || '',
      });
    }
    return;
  }
  if (p.type === 'risk_start' || p.type === 'security_start' || p.type === 'batch_start') {
    warRoomRiskCounts.value = warRoomEmptyRiskCounts();
    if (p.type !== 'batch_start' || p.phase !== 'recon_from_report') {
      warRoomQaFeed.value = [];
    }
    if (typeof ctx.beginLiveRiskAssessment === 'function'
        && (p.type === 'risk_start' || p.type === 'security_start'
          || (p.type === 'batch_start' && p.phase !== 'recon_from_report'))) {
      ctx.beginLiveRiskAssessment();
    }
    warRoomSyncProgress(p, 0, p.phase === 'recon_from_report' ? 'recon_from_report' : 'risk');
    warRoomPushFeed(
      'risk',
      p.phase === 'recon_from_report' ? 'Report aggregation started' : 'Analysis started',
      p.total ? `${p.total} entries` : '',
    );
    return;
  }
  if (p.type === 'risk_done' || p.type === 'security_done' || p.type === 'batch_done') {
    warRoomSyncProgress(p, 100, p.phase === 'recon_from_report' ? 'recon_from_report' : 'risk');
    warRoomPushFeed(
      'risk',
      p.phase === 'recon_from_report' ? 'Report aggregation finished' : 'Analysis finished',
      '',
    );
    return;
  }
  if (p.type === 'run_done') {
    warRoomSyncProgress(p, 100, 'submit');
    warRoomPushFeed('done', 'Run finished', '');
    return;
  }
  if (p.type === 'progress' || p.type === 'suite' || p.type === 'batch_progress'
      || p.type === 'risk_progress' || p.type === 'security_progress') {
    const total = p.total || 0;
    const cur = p.current || 0;
    let phase = p.phase || 'submit';
    if (p.type === 'suite') phase = 'suite';
    if (p.type.startsWith('risk') || p.type.startsWith('security') || p.type.startsWith('batch')) {
      phase = p.phase === 'recon_from_report' ? 'recon_from_report' : 'risk';
    }
    const pct = (phase === 'risk' || p.type === 'risk_progress' || p.type === 'security_progress')
      ? _warRoomSoftRiskPct(p, warRoomProgress.value?.pct ?? 0)
      : (total ? Math.min(100, Math.round((cur / total) * 100)) : (warRoomProgress.value?.pct ?? 0));
    warRoomSyncProgress(p, pct, phase);
  }
}

function warRoomOnJobTerminal(j, status) {
  if (!j || !warRoomMeta.value || warRoomMeta.value.jobId !== j.id) return;
  warRoomActive.value = false;
  warRoomStopClock();
  warRoomSetStatus(status || j.status || 'done');
  warRoomPushFeed(
    'done',
    status === 'failed' ? 'Job failed' : status === 'cancelled' ? 'Job cancelled' : 'Job finished',
    '',
  );
}

const runEnhancePhaseLabel = computed(() => {
  const p = runProgress.value;
  if (!p) return '';
  const phase = String(p.enhance_phase || p.enhancePhase || '').trim().toLowerCase();
  return ENHANCE_PHASE_LABELS[phase] || '';
});

const runProgressBarLabel = computed(() => {
  // Depend on clock so labels refresh while heartbeats keep elapsed moving.
  void runProgressClock.value;
  const p = runProgress.value;
  if (!p) return '';
  if (p.type === 'enhance_round') return `Enhancing · round ${p.current} / ${p.total}`;
  if (p.type === 'enhance_result') return `Round ${p.round} worst: ${String(p.worst || '').toUpperCase()}`;
  if (p.type === 'theory_auto_accepted') return 'Enhancement theory auto-accepted…';
  if (p.type === 'theory_review' || p.phase === 'theory') return 'Confirm enhancement theory…';
  if (p.type === 'batch_start') {
    return p.phase === 'recon_from_report' ? 'Aggregating reports…' : 'Batch assessment…';
  }
  if (p.type === 'batch_progress') {
    const cur = p.current || 0;
    const total = p.total || 0;
    if (p.phase === 'recon_from_report') {
      return total ? `Report ${cur}/${total}…` : 'Aggregating reports…';
    }
    return total ? `Assessing log ${cur}/${total}…` : 'Batch assessment…';
  }
  if (p.type === 'batch_done') {
    return p.phase === 'recon_from_report' ? 'Report aggregation complete' : 'Batch assessment complete';
  }
  if (p.phase === 'risk' || p.type === 'risk_start' || p.type === 'risk_progress' || p.type === 'risk_done' || p.type === 'risk_result') {
    const total = p.total || 0;
    const cur = p.current || 0;
    const inflight = p.in_flight || 0;
    if (p.type === 'risk_done') return 'Analysis complete';
    if (p.type === 'risk_start' && !total) return 'Analysis · preparing…';
    if (inflight > 0) {
      return total
        ? `Analysis · ${cur}/${total} done · ${inflight} judging`
        : `Analysis · ${inflight} judging…`;
    }
    if (p.status && String(p.status).startsWith('judging')) {
      return total ? `Analysis · ${cur}/${total} · ${p.status}` : `Analysis · ${p.status}`;
    }
    if (p.type === 'risk_start' || (cur === 0 && total)) {
      return total ? `Analysis · 0/${total} · starting…` : 'Analysis…';
    }
    return total ? `Analysis · ${cur} / ${total} entries` : 'Analysis…';
  }
  if (p.type === 'suite') {
    return `Strategy ${p.current} / ${p.total}${p.strategy ? ' · ' + p.strategy : ''}`;
  }
  if (p.type === 'run_start') return 'Starting probes…';
  if (p.type === 'probe_result') {
    return `${p.mode === 'multi' || p.mode === 'adaptive' ? 'Multi-turn' : 'Single'} · ${p.current ?? 0} / ${p.total ?? 0} prompts`;
  }
  if (p.type === 'run_done' && p.phase === 'recon') return 'Recon round complete';
  if (p.type === 'run_done') return 'Probes complete';
  if (p.phase === 'recon' || p.mode === 'recon_round') {
    return `Recon probe ${p.current ?? 0} / ${p.total ?? 0}`;
  }
  if (p.type === 'blocked') return p.message || 'Probes paused';
  if (p.type === 'client_rejected') return p.message || 'Client rejected prompt';
  if (p.type === 'resilience') return p.message || 'Resilience attempt';
  return `${p.mode === 'multi' ? 'Multi-turn' : 'Single'} · ${p.current ?? 0} / ${p.total ?? 0} prompts`;
});

/** Status strip should show for Attack/Enhance and standalone Analysis jobs. */
const warRoomOpsProgressActive = computed(() => {
  if (!runProgress.value) return false;
  if (runJobActive.value) return true;
  const riskJob = jobById(activeJobs.security_assess);
  if (riskJob && jobIsActive(riskJob.status)) return true;
  return !!warRoomActive.value;
});

/** Visual % that moves during in-flight work (not only after each completion). */
const runProgressDisplayPct = computed(() => {
  void runProgressClock.value;
  const p = runProgress.value;
  if (!p) return 0;
  if (p.type === 'risk_done' || p.type === 'run_done' || p.type === 'batch_done') {
    return 100;
  }
  const total = Number(p.total) || 0;
  const cur = Number(p.current) || 0;
  const inflight = Number(p.in_flight) || 0;
  if (total > 0 && (p.phase === 'risk' || p.type === 'risk_progress' || p.type === 'risk_result' || p.type === 'risk_start')) {
    const soft = Math.min(99, Math.round(((cur + inflight * 0.4) / total) * 100));
    if (soft > 0) return soft;
    // Indeterminate pulse while waiting on first judge result.
    const pulse = Math.round((Math.sin(runProgressClock.value / 450) + 1) * 6);
    return Math.max(2, pulse);
  }
  if (p.pct != null && p.pct !== '') return Number(p.pct) || 0;
  if (total > 0) return Math.min(100, Math.round((cur / total) * 100));
  if (warRoomOpsProgressActive.value) {
    const pulse = Math.round((Math.sin(runProgressClock.value / 450) + 1) * 8);
    return Math.max(3, pulse);
  }
  return 0;
});

const runProgressLive = computed(() => {
  void runProgressClock.value;
  if (!runProgress.value) return false;
  if (runProgress.value.type === 'risk_done' || runProgress.value.type === 'run_done' || runProgress.value.type === 'batch_done') {
    return false;
  }
  return !!warRoomOpsProgressActive.value;
});

const runJobStatusLabel = computed(() => {
  const j = runJob.value;
  if (!j || !jobIsActive(j.status)) return '';
  if (j.status === 'awaiting_theory') return 'Waiting for enhancement theory confirmation';
  if (j.type === 'enhance_loop') {
    if (runProgress.value?.type === 'theory_review' || runProgress.value?.phase === 'theory') {
      return 'Enhance loop · confirm theory before regenerating prompts';
    }
    if (runProgressBarLabel.value) return `Enhance loop · ${runProgressBarLabel.value}`;
    return 'Enhance loop running…';
  }
  if (j.type === 'recon_round') {
    if (runProgressBarLabel.value) return `Recon round · ${runProgressBarLabel.value}`;
    return 'Recon round running…';
  }
  if (runProgressBarLabel.value) return runProgressBarLabel.value;
  return j.status === 'pending' ? 'Starting attack…' : 'Attack in progress…';
});

const canSkipCurrentRunPrompt = computed(() => {
  if (!runJobActive.value) return false;
  const j = runJob.value;
  if (!j || (j.type !== 'run_tests' && j.type !== 'recon_round')) return false;
  if (j.status === 'awaiting_theory') return false;
  const p = runProgress.value;
  if (p?.type === 'blocked' || p?.phase === 'blocked') return false;
  if (p?.type === 'suite' || p?.type === 'run_start' || p?.type === 'run_done') return false;
  if (p?.phase === 'theory' || p?.phase === 'risk') return false;
  if (p?.type === 'enhance_round' || p?.type === 'theory_review') return false;
  return true;
});

const runProgressEtaText = computed(() => {
  void runProgressClock.value;
  const p = runProgress.value;
  if (!p) return '';
  const liveElapsed = (() => {
    if (p.elapsed_sec == null || p.elapsed_sec === '') return null;
    // Keep elapsed climbing between heartbeats using local clock delta.
    const base = Number(p.elapsed_sec);
    if (!Number.isFinite(base)) return null;
    const stamped = Number(p._localElapsedAt);
    if (!stamped || !runJobActive.value) return base;
    const drift = Math.max(0, (runProgressClock.value - stamped) / 1000);
    return base + drift;
  })();
  if (p.type === 'risk_start' && (p.eta_sec == null || p.eta_sec === '')) {
    return liveElapsed != null ? `${formatRunEta(liveElapsed)} elapsed` : 'Estimating…';
  }
  if (p.phase === 'risk' || p.type === 'risk_progress' || p.type === 'risk_done' || p.type === 'risk_result') {
    if (p.type === 'risk_done') return `${formatRunEta(p.elapsed_sec)} total`;
    const elapsedBit = liveElapsed != null ? formatRunEta(liveElapsed) : formatRunEta(p.elapsed_sec);
    if (p.eta_sec != null && p.eta_sec !== '') return `ETA ${formatRunEta(p.eta_sec)} · ${elapsedBit} elapsed`;
    return elapsedBit ? `${elapsedBit} elapsed` : 'Working…';
  }
  if (p.type === 'run_start' || p.type === 'suite') {
    return liveElapsed != null ? `${formatRunEta(liveElapsed)} elapsed` : 'Estimating…';
  }
  if (p.type === 'run_done') return `${formatRunEta(p.elapsed_sec)} total`;
  if (p.eta_sec != null && p.eta_sec !== '') {
    const elapsedBit = liveElapsed != null ? formatRunEta(liveElapsed) : formatRunEta(p.elapsed_sec);
    return `ETA ${formatRunEta(p.eta_sec)} · ${elapsedBit} elapsed`;
  }
  if (liveElapsed != null) return `${formatRunEta(liveElapsed)} elapsed`;
  if (p.elapsed_sec != null && p.elapsed_sec !== '') return `${formatRunEta(p.elapsed_sec)} elapsed`;
  return runJobActive.value ? 'Working…' : '';
});

/** Risk tab: standalone risk job, or run_tests job while in risk phase (e.g. after probes when “assess after” is on). */
const riskTabProgressBarVisible = computed(() => {
  const p = runProgress.value;
  if (!p) return false;
  const riskJob = jobById(activeJobs.security_assess);
  if (riskJob && jobIsActive(riskJob.status)) return true;
  return !!(p.phase === 'risk' && runJobActive.value);
});

async function loadSites() {
  sites.value = await api('/api/sites');
  allStrategies.value = await api('/api/strategies');
  allPlaybooks.value = await api('/api/playbooks');
  try {
    const catData = await api('/api/plays/categories');
    playCategoryTree.value = catData.tree || [];
    const presetData = await api('/api/plays/category-presets');
    pbPresetCatalog.value = presetData.leaf_presets || {};
    pbEnsureCategoryDefaults(pbForm);
    pbEnsureCategoryDefaults(pbRecordCat);
  } catch (_) {
    playCategoryTree.value = [];
    pbPresetCatalog.value = {};
  }
  try {
    pbCatalog.value = await api('/api/playbooks/manage');
  } catch (_) {
    /* optional */
  }
  await ctx.restoreActivePlaybook();
}

const CONTEXT_SITE_KEY = 'genbounty_site';
const CONTEXT_COMPONENT_KEY = 'genbounty_component';

function persistContextSelection() {
  try {
    if (site.value) localStorage.setItem(CONTEXT_SITE_KEY, site.value);
    else localStorage.removeItem(CONTEXT_SITE_KEY);
    if (component.value) localStorage.setItem(CONTEXT_COMPONENT_KEY, component.value);
    else localStorage.removeItem(CONTEXT_COMPONENT_KEY);
  } catch {
    /* private mode / quota */
  }
}

function readSavedContextSelection() {
  try {
    return {
      site: (localStorage.getItem(CONTEXT_SITE_KEY) || '').trim(),
      component: (localStorage.getItem(CONTEXT_COMPONENT_KEY) || '').trim(),
    };
  } catch {
    return { site: '', component: '' };
  }
}

/** Restore site/component from localStorage. Returns true when both are selected. */
async function applySavedContext() {
  const saved = readSavedContextSelection();
  const target = saved.site;
  if (!target || !sites.value.includes(target)) return false;

  const comps = await api(`/api/sites/${encodeURIComponent(target)}/components`);
  let comp = saved.component;
  if (comp && !comps.includes(comp)) {
    comp = comps.length === 1 ? comps[0] : '';
  }
  if (!comp) {
    if (comps.length === 1) comp = comps[0];
    else {
      site.value = target;
      components.value = comps;
      component.value = '';
      persistContextSelection();
      return false;
    }
  }

  site.value = target;
  components.value = comps;
  component.value = comp;
  persistContextSelection();
  await ctx.loadDiscoverContext();
  await loadContext();
  await ctx.checkSetupAndNavigate();
  return true;
}

async function onSiteChange() {
  component.value = '';
  manualDiscoverJobId.value = null;
  if (ctx.apiDiscoverJobId) ctx.apiDiscoverJobId.value = null;
  ctx.reconJobId.value = null;
  ctx.reconReportPath.value = '';
  if (typeof ctx.applyDiscoverTransportPref === 'function') {
    ctx.applyDiscoverTransportPref();
  } else if (ctx.discoverTransport) {
    ctx.discoverTransport.value = G.preferredDiscoverTransport();
  }
  if (typeof ctx.resetDiscoverAuthUi === 'function') ctx.resetDiscoverAuthUi();
  if (site.value) {
    components.value = await api(`/api/sites/${encodeURIComponent(site.value)}/components`);
    if (components.value.length === 1) {
      component.value = components.value[0];
    } else if (ctx.authConfigured) {
      ctx.authConfigured.value = false;
      if (ctx.authMode) ctx.authMode.value = null;
      if (ctx.authLoginChoice) ctx.authLoginChoice.value = null;
      if (ctx.authHasApiKey) ctx.authHasApiKey.value = false;
      if (ctx.authScope) ctx.authScope.value = 'none';
    }
  } else {
    components.value = [];
    if (ctx.authConfigured) {
      ctx.authConfigured.value = false;
      if (ctx.authMode) ctx.authMode.value = null;
      if (ctx.authLoginChoice) ctx.authLoginChoice.value = null;
      if (ctx.authHasApiKey) ctx.authHasApiKey.value = false;
      if (ctx.authScope) ctx.authScope.value = 'none';
    }
  }
  persistContextSelection();
}

async function refreshIntelAfterJob() {
  await ctx.loadIntelList(ctx.intelActiveRunId.value);
  if (tab.value === 'intel' && ctx.intelSelectedId.value) await ctx.loadIntel();
  if (tab.value === 'intel') await ctx.loadCredentialsAndPaths();
}

async function loadContext() {
  if (site.value && component.value) {
    const s = encodeURIComponent(site.value), c = encodeURIComponent(component.value);
    await loadRunTestFiles({ applySaved: true, restorePlaybook: false });
    await ctx.restoreActivePlaybook();
    await ctx.loadLogs();
    if (tab.value === 'run') {
      if (typeof ctx.syncRunTableToMetricsWindow === 'function') {
        await ctx.syncRunTableToMetricsWindow();
      } else {
        await ctx.loadLatestRunLog();
      }
    }
    if (tab.value === 'risk') {
      if (typeof ctx.syncRiskTableToMetricsWindow === 'function') {
        await ctx.syncRiskTableToMetricsWindow();
      } else {
        await ctx.loadLatestRiskReport();
      }
    }
    ctx.loadRecon();
    if (tab.value === 'intel') {
      await ctx.loadIntelList(activePlaybookId.value || ctx.intelActiveRunId.value);
      await ctx.loadCredentialsAndPaths();
    }
    if (tab.value === 'notes') await ctx.loadNotes();
    if (tab.value === 'export' || tab.value === 'risk') await ctx.loadExportSettings();
    if (tab.value === 'settings' && settingsTab.value === 'component') ctx.loadCompCfg();
    if (tab.value === 'tests') await ctx.tmLoadTestFiles({ restorePlaybook: false });
  }
}

function runSuitePath() {
  if (!site.value || !component.value || !ctx.run.playbook || !ctx.run.strategy || ctx.run.strategy === '__all__') {
    return '';
  }
  // On-disk layout is always hyphenated (tests/zero-shot/<play>.json).
  const strat = String(ctx.run.strategy).replace(/_/g, '-');
  const play = String(ctx.run.playbook).replace(/_/g, '-');
  return `browser-bot/sites/${site.value}/${component.value}/tests/${strat}/${play}.json`;
}

async function loadRunSubmissionTransport() {
  runSubmissionTransport.value = 'ui';
  if (!site.value || !component.value) return;
  try {
    const data = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`
    );
    runSubmissionTransport.value = (data?.submission?.transport || 'ui').toLowerCase();
  } catch {
    runSubmissionTransport.value = 'ui';
  }
}

async function loadRunTestFiles({ applySaved = true, restorePlaybook = true } = {}) {
  ctx._skipRunSelectionPersist = true;
  runTestFiles.value = [];
  ctx.run.playbook = '';
  ctx.run.category = '';
  runStrategies.value = [];
  ctx.run.strategy = '';
  ctx.runArtifactStatus.value = [];
  ctx.runUploadWarning.value = '';
  runSubmissionTransport.value = 'ui';
  try {
    if (!site.value || !component.value) return;
    const s = encodeURIComponent(site.value), c = encodeURIComponent(component.value);
    await loadRunSubmissionTransport();
    runTestFiles.value = await api(`/api/sites/${s}/${c}/test-files`);
    try {
      pbCatalog.value = await api('/api/playbooks/manage');
    } catch (_) {
      /* optional category metadata */
    }
    if (applySaved) ctx.applySavedRunTabSelections();
    else ctx.ensureRunPlayInCategory();
    if (!ctx.run.category && ctx.runCategoryOptions.value.length) {
      ctx.ensureRunPlayInCategory();
    }
    if (restorePlaybook) await ctx.restoreActivePlaybook();
  } finally {
    ctx._skipRunSelectionPersist = false;
  }
}

function runOnScopeChange() {
  ctx.runArtifactStatus.value = [];
  ctx.runUploadWarning.value = '';
  if (ctx.run.scope === 'category') {
    ctx.run.playbook = '';
    ctx.run.strategy = '__all__';
    if (!ctx.run.category && ctx.runCategoryOptions.value.length) {
      ctx.run.category = ctx.runCategoryOptions.value[0].key;
    }
  } else {
    ctx.run.strategy = '';
    ctx.ensureRunPlayInCategory();
  }
}

function runOnCategoryChange() {
  ctx.runArtifactStatus.value = [];
  ctx.runUploadWarning.value = '';
  ctx.run.strategy = '__all__';
}

function runSelectedTestFile() {
  if (!ctx.run.playbook) return null;
  return runTestFiles.value.find(f => f.slug === ctx.run.playbook) || null;
}

const runGenerationProfile = computed(() => {
  const file = runSelectedTestFile();
  return (file && file.generation_profile) ? file.generation_profile : '';
});

const runGenerationNotes = computed(() => {
  const file = runSelectedTestFile();
  return (file && file.generation_notes) ? file.generation_notes : '';
});

function runOnTestFileChange(preserveStrategy = false) {
  ctx.syncRunCategoryFromPlaybook();
  const prev = preserveStrategy === true ? ctx.run.strategy : '';
  runStrategies.value = [];
  if (!preserveStrategy) ctx.run.strategy = '';
  ctx.runArtifactStatus.value = [];
  ctx.runUploadWarning.value = '';
  const file = runSelectedTestFile();
  if (!file) return;
  runStrategies.value = file.strategies || [];
  const matchStrategySlug = G.matchStrategySlug || ctx.matchStrategySlug;
  const matched = matchStrategySlug ? matchStrategySlug(runStrategies.value, prev) : '';
  const keepAll = prev === '__all__';
  const keepStrat = !!matched && matched !== '__all__'
    && matched !== '__campaign__'
    && matched !== '__recommended__';
  if (keepAll) {
    ctx.run.strategy = '__all__';
  } else if (keepStrat) {
    // Prefer disk slug (few-shot) even if prev was few_shot.
    ctx.run.strategy = matched;
    loadRunArtifactStatus();
  } else if (runStrategies.value.length === 1) {
    const only = runStrategies.value[0];
    ctx.run.strategy = (
      typeof ctx.isPremiumStrategy === 'function' && ctx.isPremiumStrategy(only.slug)
    ) ? '' : only.slug;
    loadRunArtifactStatus();
  } else if (runStrategies.value.length) {
    const fallback = runStrategies.value.find((s) => !isStrategyOptionDisabled(s.slug))
      || runStrategies.value.find(
        (s) => !(typeof ctx.isPremiumStrategy === 'function' && ctx.isPremiumStrategy(s.slug)),
      );
    ctx.run.strategy = fallback?.slug || '';
    loadRunArtifactStatus();
  }
}

function runOnStrategyChange() {
  loadRunArtifactStatus();
  if (typeof ctx.loadRunObfuscationStatus === 'function') {
    ctx.loadRunObfuscationStatus();
  }
}

async function loadRunArtifactStatus() {
  ctx.runArtifactStatus.value = [];
  ctx.runUploadWarning.value = '';
  if (ctx.run.strategy !== 'multimodal' || !ctx.run.playbook || ctx.run.strategy === '__all__') return;
  const suitePath = runSuitePath();
  if (!suitePath) return;
  try {
    const res = await api(`/api/payloads/artifact-status?suite_path=${encodeURIComponent(suitePath)}`);
    ctx.runArtifactStatus.value = res.prompts || [];
    if (ctx.runArtifactStatus.value.length) {
      let uploadOk = false;
      try {
        const caps = await api(
          `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/capabilities`
        );
        uploadOk = !!(caps?.capabilities?.file_upload);
      } catch (_) {
        const cfg = await api(`/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/config`);
        const sub = cfg?.submission || {};
        const transport = (sub.transport || 'ui').toLowerCase();
        uploadOk = transport === 'api_document' || transport === 'api_multipart';
        if (!uploadOk && transport === 'ui') {
          uploadOk = (sub.inputs || []).some(i => i.type === 'file' || i.path_from === 'payload');
        }
      }
      if (!uploadOk) {
        ctx.runUploadWarning.value = 'Target has no file upload (recon/config). Multimodal run may fail.';
      }
    }
  } catch (_) {
    ctx.runArtifactStatus.value = [];
  }
}

watch(ctx.runResults, (rows) => {
  if (!rows.length && ctx.runResultsLayout.value === 'maximized') {
    ctx.runResultsLayout.value = 'normal';
    ctx.persistRunResultsLayout();
  }
});

watch(ctx.riskViewResults, (rows) => {
  if (!rows.length && ctx.riskViewLayout.value === 'maximized') {
    ctx.riskViewLayout.value = 'normal';
    ctx.persistRiskViewLayout();
  }
});

watch(() => [ctx.run.playbook, ctx.run.strategy], () => {
  loadRunArtifactStatus();
});

watch(() => [ctx.gen.playbook, ctx.gen.strategy], () => {
  if (typeof ctx.loadRunObfuscationStatus === 'function') {
    ctx.loadRunObfuscationStatus();
  }
});

watch(
  () => [
    site.value,
    component.value,
    ctx.run.scope,
    ctx.run.playbook,
    ctx.run.category,
    ctx.run.strategy,
    ctx.run.assess,
    ctx.run.stopLevels.medium,
    ctx.run.stopLevels.high,
    ctx.run.stopLevels.critical,
    ctx.run.maxRounds,
    ctx.run.huntMode,
    ctx.run.customEnhance,
    ctx.run.customEnhanceText,
    ctx.run.customOverridesFreeze,
  ],
  () => ctx.persistRunTabSelections(),
);

watch(
  () => [site.value, component.value, ctx.tmPlaybook.value, ctx.tmStrategy.value],
  () => ctx.persistTmTabSelections(),
);

async function refreshTargetCapabilities() {
  ctx.targetCapabilities.loaded = false;
  ctx.targetCapabilities.multi_turn = true;
  ctx.targetCapabilities.file_upload = false;
  if (!site.value || !component.value) return;
  try {
    const q = new URLSearchParams();
    if (ctx.gen.playbook) q.set('playbook', ctx.gen.playbook);
    const caps = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/capabilities?${q}`
    );
    const c = caps?.capabilities || {};
    ctx.targetCapabilities.multi_turn = c.multi_turn !== false;
    ctx.targetCapabilities.file_upload = !!c.file_upload;
    ctx.targetCapabilities.loaded = true;
  } catch (_) {
    /* keep defaults */
  }
}

function firstAllowedGenerateStrategy() {
  const strategies = availableGenerateStrategies.value || [];
  const allowed = strategies.find((s) => !isStrategyOptionDisabled(s));
  if (allowed) return allowed;
  // Never fall back to a Premium-only slug (e.g. adaptive) when everything is disabled.
  const nonPremium = strategies.find(
    (s) => !(typeof ctx.isPremiumStrategy === 'function' && ctx.isPremiumStrategy(s)),
  );
  return nonPremium || '';
}

function ensureGenStrategySelection() {
  if (ctx.gen.strategy === '__campaign__' || ctx.gen.strategy === '__recommended__') {
    ctx.gen.strategy = firstAllowedGenerateStrategy();
    return;
  }
  if (
    ctx.gen.strategy
    && ctx.gen.strategy !== '__all__'
    && isStrategyOptionDisabled(ctx.gen.strategy)
  ) {
    ctx.gen.strategy = firstAllowedGenerateStrategy();
    return;
  }
  if (!ctx.gen.strategy && ctx.gen.playbook) {
    ctx.gen.strategy = firstAllowedGenerateStrategy();
  }
}

function strategyBlockedOnStatelessTarget(slug) {
  const s = String(slug || '').replace(/-/g, '_');
  return strategyRequiresMultiTurn(s) || s === 'multimodal';
}

const availableGenerateStrategies = computed(() => {
  const base = allStrategies.value || [];
  // Wait for API strategies before appending the Premium Adaptive stub option.
  if (!base.length) return base;
  // Community: surface Adaptive as a disabled Premium option even when filtered from API.
  if (!base.some((s) => String(s).replace(/-/g, '_') === 'adaptive')) {
    return [...base, 'adaptive'];
  }
  return base;
});

const availableRunStrategies = computed(() => runStrategies.value || []);

function isStrategyOptionDisabled(slug) {
  if (typeof ctx.isPremiumStrategy === 'function' && ctx.isPremiumStrategy(slug)) {
    return true;
  }
  return ctx.targetCapabilities.multi_turn === false && strategyBlockedOnStatelessTarget(slug);
}

function strategyOptionDisabledSuffix(slug) {
  if (!isStrategyOptionDisabled(slug)) return '';
  if (typeof ctx.isPremiumStrategy === 'function' && ctx.isPremiumStrategy(slug)) {
    return ' (Premium)';
  }
  return ' (out of scope for API)';
}

const multiTurnBlockedNote = computed(() => {
  if (ctx.targetCapabilities.multi_turn !== false) return '';
  return (
    'This target has no conversation history (stateless API). '
    + 'Multi-turn strategies (multi_shot, iterative, prompt_chaining, adaptive) and multimodal '
    + 'are listed but marked out of scope for API - use zero_shot, few_shot, jailbreak, or Enhance.'
  );
});

watch(
  () => ctx.targetCapabilities.multi_turn,
  (multiTurn) => {
    if (multiTurn !== false) return;
    if (ctx.gen.multimodal) ctx.gen.multimodal = false;
    if (String(ctx.gen.strategy || '').replace(/-/g, '_') === 'multimodal') {
      ctx.gen.strategy = firstAllowedGenerateStrategy();
    }
  },
);

watch(() => [site.value, component.value, ctx.gen.playbook], async () => {
  await refreshTargetCapabilities();
  ensureGenStrategySelection();
});
watch(
  () => [ctx.targetCapabilities.multi_turn, availableGenerateStrategies.value, ctx.gen.playbook],
  () => { ensureGenStrategySelection(); },
);
function firstAllowedRunStrategySlug() {
  const list = availableRunStrategies.value || [];
  const allowed = list.find((s) => !isStrategyOptionDisabled(s.slug));
  if (allowed) return allowed.slug || '';
  const nonPremium = list.find(
    (s) => !(typeof ctx.isPremiumStrategy === 'function' && ctx.isPremiumStrategy(s.slug)),
  );
  return nonPremium?.slug || '';
}

watch(
  () => [ctx.run.strategy, availableRunStrategies.value],
  () => {
    if (ctx.run.strategy === '__campaign__' || ctx.run.strategy === '__recommended__') {
      ctx.run.strategy = firstAllowedRunStrategySlug();
      return;
    }
    if (
      ctx.run.strategy
      && ctx.run.strategy !== '__all__'
      && isStrategyOptionDisabled(ctx.run.strategy)
    ) {
      ctx.run.strategy = firstAllowedRunStrategySlug();
    }
  },
);

const suiteExistsForSelection = computed(() => {
  if (!ctx.gen.playbook || !runTestFiles.value.length) return false;
  const stem = ctx.gen.playbook.replace(/-/g, '_');
  const alt = ctx.gen.playbook.replace(/_/g, '-');
  return runTestFiles.value.some(f => f.slug === stem || f.slug === alt || f.slug === ctx.gen.playbook);
});

const hasAssessedReport = computed(() => (logs.reports || []).length > 0);

watch(() => ctx.gen.playbook, () => {
  ctx.syncGenCategoryFromPlaybook();
  ensureGenStrategySelection();
});

watch(ctx.playbooksGrouped, () => {
  ctx.ensureGenPlayInCategory();
});

async function refreshRunTests() {
  if (!site.value || !component.value) return;
  const prevScope = ctx.run.scope;
  const prevCategory = ctx.run.category;
  const prevPlaybook = ctx.run.playbook;
  const prevStrategy = ctx.run.strategy;
  await loadRunTestFiles({ applySaved: false });
  ctx.run.scope = prevScope || 'playbook';
    if (ctx.run.scope === 'category') {
    if (prevCategory && ctx.runCategoryOptions.value.some(g => g.key === prevCategory)) {
      ctx.run.category = prevCategory;
    } else if (ctx.runCategoryOptions.value.length) {
      ctx.run.category = ctx.runCategoryOptions.value[0].key;
    }
    ctx.run.strategy = '__all__';
    if (typeof ctx.syncRunTableToMetricsWindow === 'function') {
      await ctx.syncRunTableToMetricsWindow();
    } else {
      await ctx.loadLatestRunLog();
    }
    return;
  }
  if (prevCategory && ctx.runCategoryOptions.value.some(g => g.key === prevCategory)) {
    ctx.run.category = prevCategory;
  }
  if (prevPlaybook && runTestFiles.value.some(f => f.slug === prevPlaybook)) {
    ctx.run.playbook = prevPlaybook;
    ctx.syncRunCategoryFromPlaybook();
    runOnTestFileChange(true);
    const matched = (G.matchStrategySlug || ctx.matchStrategySlug)?.(
      runStrategies.value,
      prevStrategy,
    ) || '';
    if (
      prevStrategy === '__all__'
      || (matched
        && matched !== '__campaign__'
        && matched !== '__recommended__')
    ) {
      ctx.run.strategy = prevStrategy === '__all__' ? '__all__' : matched;
      await loadRunArtifactStatus();
    } else {
      ctx.run.strategy = '';
    }
  } else {
    ctx.ensureRunPlayInCategory();
  }
  if (typeof ctx.syncRunTableToMetricsWindow === 'function') {
    await ctx.syncRunTableToMetricsWindow();
  } else {
    await ctx.loadLatestRunLog();
  }
}

// Lines to suppress in the run_tests console - individual prompt/response
// entries are shown in the results table instead.
function _isRunDetailLine(line) {
  const t = line.trimStart();
  return t.startsWith('Input: ') || t.startsWith('Response: ') || t.startsWith('Response:None');
}

function _isProgressMetaLine(line) {
  return line.trimStart().startsWith('[genbounty_progress]') || line.trimStart().startsWith('[airta_progress]');
}

function activeOutput(type) {
  const jid = activeJobs[type];
  if (!jid) return [];
  const j = jobs.value.find(x => x.id === jid);
  if (!j) return [];
  const lines = j._output || [];
  if (type === 'run_tests' || type === 'security_assess') {
    return lines.filter(l => !_isRunDetailLine(l) && !_isProgressMetaLine(l));
  }
  return lines;
}

const SAMPLE_RESULT_MARKER = '[genbounty_sample_result]';
const MANUAL_ASSESS_RESULT_MARKER = '[genbounty_manual_assess_result]';
const sampleIntelAdded = ref(false);
const sampleIntelBusy = ref(false);
const sampleIntelMsg = ref('');
/** Cleared until the next Fire. */
const sidebarSampleReplyCleared = ref(false);

const manualAssessMsg = ref('');

const manualAssessCheckboxTitle =
  'After Fire, run risk assessment for this Q→A using the header playbook '
  + 'and save under component/logs/manual/<timestamp>/';

function _manualAssessEnabled() {
  return !!(ctx.run && ctx.run.manualAssess);
}

function _parseMarkerResultFromJob(jobType, marker) {
  const j = jobById(activeJobs[jobType]);
  if (!j) return null;
  const lines = j._output || [];
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = String(lines[i] || '');
    const idx = line.indexOf(marker);
    if (idx < 0) continue;
    const raw = line.slice(idx + marker.length).trim();
    try {
      const data = JSON.parse(raw);
      if (data && typeof data === 'object') {
        return {
          prompt: String(data.prompt || ''),
          response: String(data.response || ''),
          attack_id: String(data.attack_id || '').trim(),
        };
      }
    } catch {
      return null;
    }
  }
  return null;
}

function _parseSampleResultFromJob() {
  return _parseMarkerResultFromJob('sample_request', SAMPLE_RESULT_MARKER);
}

/** Tab-scoped job output (Firing Range Q→A is sidebar-only, not Experiment Output). */
function _tabPanelOutput() {
  // Header Nuke may run from any tab - prefer its output while active/recent.
  if (activeJobs.nuke) {
    const nukeLines = activeOutput('nuke');
    if (nukeLines.length) return nukeLines;
  }
  const t = tab.value;
  if (t === 'generate') {
    const genJob = jobById(activeJobs.generate);
    if (genJob && jobIsActive(genJob.status)) {
      return activeOutput('generate');
    }
    if (genJob && (genJob._output || []).length) {
      return genJob._output;
    }
    if (ctx.pbGenerating.value && ctx.pbGenerationOutput.value.length) {
      return ctx.pbGenerationOutput.value;
    }
    return [];
  }
  if (t === 'playbooks') return ctx.pbGenerationOutput.value;
  if (t === 'discover') {
    for (const key of ['discover', 'manual_discover', 'api_discover', 'login']) {
      const lines = activeOutput(key);
      if (lines.length) return lines;
    }
    return [];
  }
  if (t === 'run') {
    const attrLines = activeOutput('prompt_attributes');
    if (attrLines.length) return attrLines;
    const runLines = activeOutput('run_tests');
    if (runLines.length) return runLines;
    // Sample fire from Attack (Firing Range Q→A stays on the manual tab chat pane).
    const sampleLines = activeOutput('sample_request');
    if (sampleLines.length) return sampleLines;
    return [];
  }
  if (t === 'war-room') {
    const runLines = activeOutput('run_tests');
    const enhanceJob = jobById(activeJobs.enhance_loop);
    const enhanceLines = activeOutput('enhance_loop');
    const enhanceActive = !!(enhanceJob && jobIsActive(enhanceJob.status));
    if (enhanceActive && enhanceLines.length) {
      return runLines.length ? [...runLines, '', ...enhanceLines] : enhanceLines;
    }
    const assessJob = jobById(activeJobs.security_assess);
    const assessLines = activeOutput('security_assess');
    const overview = _securityAssessOverviewLines(assessLines);
    const assessActive = !!(assessJob && jobIsActive(assessJob.status));
    const showAssess = overview.length && (
      assessActive
      || (assessJob && (assessJob.status === 'done' || assessJob.status === 'failed'
        || assessJob.status === 'cancelled'))
    );
    const assessBlock = showAssess
      ? ['[risk] ── Assessment overview ──', ...overview]
      : [];
    if (assessActive && assessBlock.length) {
      return runLines.length ? [...runLines, '', ...assessBlock] : assessBlock;
    }
    if (runLines.length && assessBlock.length) {
      return [...runLines, '', ...assessBlock];
    }
    if (runLines.length) return runLines;
    if (enhanceLines.length) return enhanceLines;
    return assessBlock;
  }
  if (t === 'recon') {
    for (const key of ['recon', 'recon_from_report']) {
      const lines = activeOutput(key);
      if (lines.length) return lines;
    }
    return [];
  }
  if (t === 'intel') return activeOutput('credentials_from_reports');
  if (t === 'risk') return activeOutput('security_assess');
  if (t === 'export') return activeOutput('export');
  if (t === 'settings' && settingsTab.value === 'cache') {
    return activeOutput('clear_cache').concat(activeOutput('nuke'));
  }
  if (t === 'settings') {
    const loginLines = activeOutput('login');
    if (loginLines.length) return loginLines;
  }
  return [];
}

function _lineLooksLikeFilesystemPath(line) {
  const t = String(line || '');
  if (!t.trim()) return false;
  // Absolute / home / drive / repo-relative log artifact paths.
  if (/(?:^|[\s`"'])(?:\/|\\|[A-Za-z]:\\)/.test(t)) return true;
  if (/browser-bot\/sites\//i.test(t)) return true;
  if (/\/logs\/(?:probes|manual|attack)\//i.test(t)) return true;
  if (/\b\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\b/.test(t) && /\.json\b/i.test(t)) {
    return true;
  }
  if (/(?:^|[\s])(?:\.?\.?\/)?[\w.-]+(?:\/[\w.-]+)+\.(?:json|har|log)\b/i.test(t)) {
    return true;
  }
  return false;
}

function _securityAssessOverviewLines(lines) {
  const out = [];
  for (const raw of lines || []) {
    const t = String(raw || '');
    if (!t.trim()) continue;
    if (t.includes('[genbounty_progress]')) continue;
    if (t.includes('[genbounty_manual_assess_result]')) continue;
    if (_lineLooksLikeFilesystemPath(t)) continue;
    if (
      t.startsWith('[*]')
      || t.startsWith('[+]')
      || t.startsWith('[!]')
      || t.startsWith('[error]')
      || t.startsWith('[sample] Failed')
      || /^\s+\S/.test(t)
    ) {
      out.push(t);
    }
  }
  return out;
}

/** Firing Range reply lives in the sidebar - never owns Experiment Output. */
const panelOutputIsSample = computed(() => false);

const sampleResultAction = computed(() => {
  if (sidebarSampleReplyCleared.value) return null;
  const j = jobById(activeJobs.sample_request);
  if (!j || jobIsActive(j.status)) return null;
  if (j.status !== 'done') return null;
  return _parseSampleResultFromJob();
});

function _sampleResponseBodyFromLines(lines, opts = {}) {
  const resultMarker = opts.resultMarker || SAMPLE_RESULT_MARKER;
  const responseLabel = opts.responseLabel || /^\[sample\]\s+Response:\s*$/i;
  const sectionPrefix = opts.sectionPrefix || /^\[sample\]\s+/i;
  const out = [];
  let inResponse = false;
  for (const line of lines || []) {
    const t = String(line || '');
    if (t.includes(resultMarker)) continue;
    const trimmed = t.trimStart();
    if (responseLabel.test(trimmed)) {
      inResponse = true;
      continue;
    }
    if (sectionPrefix.test(trimmed)) {
      inResponse = false;
      continue;
    }
    if (inResponse) out.push(t);
  }
  return out.join('\n').trim();
}

const sidebarSampleReply = computed(() => {
  if (sidebarSampleReplyCleared.value) return '';
  const j = jobById(activeJobs.sample_request);
  if (!j) return '';
  if (jobIsActive(j.status)) {
    const partial = _sampleResponseBodyFromLines(j._output || []);
    if (partial) return partial;
    if (_manualAssessEnabled()) {
      const lines = j._output || [];
      const hasSample = lines.some((l) => String(l || '').includes(SAMPLE_RESULT_MARKER));
      if (hasSample) return 'Assessing…';
    }
    return 'Firing…';
  }
  if (j.status === 'done') {
    const parsed = _parseSampleResultFromJob();
    if (parsed && String(parsed.response || '').trim()) return String(parsed.response);
    const body = _sampleResponseBodyFromLines(j._output || []);
    return body || '(empty response)';
  }
  if (j.status === 'failed' || j.status === 'cancelled') {
    const lines = j._output || [];
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      const t = String(lines[i] || '').trim();
      if (!t) continue;
      if (t.startsWith('[error]') || t.startsWith('[!]')) return t;
    }
    // Fall back to last non-empty output line (e.g. unknown job type before restart).
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      const t = String(lines[i] || '').trim();
      if (t) return t;
    }
    return j.status === 'cancelled' ? 'Cancelled.' : 'Request failed.';
  }
  return '';
});

const manualCommandBusy = computed(() => {
  const j = jobById(activeJobs.sample_request);
  return !!(j && jobIsActive(j.status));
});

const manualFireBusyLabel = computed(() => {
  if (!manualCommandBusy.value) return 'Fire';
  if (_manualAssessEnabled()) {
    const j = jobById(activeJobs.sample_request);
    const lines = j && Array.isArray(j._output) ? j._output : [];
    const hasSample = lines.some((l) => String(l || '').includes(SAMPLE_RESULT_MARKER));
    if (hasSample) return 'Assessing…';
  }
  return 'Firing…';
});

const manualFireButtonTitle = computed(() => {
  if (manualCommandBusy.value) {
    return manualFireBusyLabel.value === 'Assessing…'
      ? 'Running risk assessment…'
      : 'Firing…';
  }
  return _manualAssessEnabled()
    ? 'Fire at target, then risk-assess into logs/manual/<timestamp>/'
    : 'Fire at target';
});

function _parseManualAssessResultFromJob() {
  const j = jobById(activeJobs.sample_request);
  if (!j) return null;
  const lines = j._output || [];
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = String(lines[i] || '');
    const idx = line.indexOf(MANUAL_ASSESS_RESULT_MARKER);
    if (idx < 0) continue;
    const raw = line.slice(idx + MANUAL_ASSESS_RESULT_MARKER.length).trim();
    try {
      const data = JSON.parse(raw);
      if (data && typeof data === 'object') return data;
    } catch {
      return null;
    }
  }
  return null;
}

watch(
  () => {
    const j = jobById(activeJobs.sample_request);
    return j ? `${j.id}:${j.status}:${(j._output || []).length}` : '';
  },
  () => {
    const j = jobById(activeJobs.sample_request);
    if (!j || jobIsActive(j.status)) return;
    const parsed = _parseManualAssessResultFromJob();
    if (parsed) {
      const sev = String(parsed.severity || '').trim();
      const dir = String(parsed.run_dir || parsed.pipeline_report || '').trim();
      const shortDir = dir.includes('/logs/')
        ? dir.slice(dir.indexOf('/logs/') + 1)
        : dir;
      manualAssessMsg.value = sev
        ? `${sev}${shortDir ? ' · ' + shortDir : ''}`
        : (shortDir || 'Assessed');
      return;
    }
    const lines = j._output || [];
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      const t = String(lines[i] || '').trim();
      if (
        t.startsWith('[!] Firing Range assess')
        || t.startsWith('[error]')
      ) {
        manualAssessMsg.value = t.replace(/^\[!\]\s*/, '').replace(/^\[error\]\s*/, '');
        return;
      }
    }
    if (_manualAssessEnabled() && j.status === 'done') {
      // Assess was requested but no result marker - surface last sample assess line.
      for (let i = lines.length - 1; i >= 0; i -= 1) {
        const t = String(lines[i] || '').trim();
        if (t.includes('[sample] Assess') || t.includes('Assess off')) {
          manualAssessMsg.value = t.replace(/^\[sample\]\s*/, '');
          return;
        }
      }
    }
  },
);

const panelOutput = computed(() => {
  if (ctx.loginRunning?.value) {
    const loginLines = activeOutput('login');
    if (loginLines.length) return loginLines;
  }
  // Deploy Probes: Experiment Output follows the pipeline transcript. While a
  // generate/enhance job is active, awaitJobDone mirrors that job's console
  // into pipelinePromptOutput so steps appear here (not only sparse [pipeline] lines).
  if (ctx.pipelineBusy?.value || ctx.pipelinePromptOutput?.value?.length) {
    if (ctx.pipelinePromptOutput?.value?.length) return ctx.pipelinePromptOutput.value;
    if (ctx.pipelineBusy?.value) return ['[pipeline] Start Battle starting…'];
  }
  const tabLines = _tabPanelOutput();
  if (tabLines.length) return tabLines;
  return [];
});

const panelOutputLines = computed(() =>
  panelOutput.value.filter((line) => {
    if (line.includes('[genbounty_discovery_ui]')) return false;
    if (line.includes(SAMPLE_RESULT_MARKER)) return false;
    if (line.includes(MANUAL_ASSESS_RESULT_MARKER)) return false;
    if (loginCdpCommand.value && line.includes('[genbounty_login_cdp_cmd]')) return false;
    return true;
  })
);

const loginCdpCommand = computed(() => {
  const marker = '[genbounty_login_cdp_cmd]';
  for (const line of panelOutput.value) {
    const idx = line.indexOf(marker);
    if (idx >= 0) {
      return line.slice(idx + marker.length).trim();
    }
  }
  return '';
});

async function copyLoginCdpCommand() {
  const cmd = loginCdpCommand.value;
  if (!cmd) return;
  try {
    await navigator.clipboard.writeText(cmd);
  } catch {
    // clipboard may be unavailable
  }
}

const panelOutputStatus = computed(() => {
  const tabJob = findTabJob();
  const j = tabJob && tabJob.type !== 'sample_request'
    ? tabJob
    : null;
  const lines = panelOutput.value;
  const tabHints = {
    generate: 'Idle - generate probes to see forge output here.',
    playbooks: 'Idle - create or regenerate a play to see mission planning progress here.',
    run: 'Idle - run or enhance probes to see progress here.',
    'war-room': 'Idle - run, enhance, or assess to see campaign and risk output here.',
    discover: 'Idle - connect target or run discovery to see output.',
    recon: 'Idle - run recon to see browser/API probing and recon grounding output.',
    intel: 'Idle - pull credentials/paths from pipeline reports to see extract output here.',
    risk: 'Idle - run Analysis to see assessment output.',
    export: 'Idle - export or submit reports to see output.',
    settings: 'Idle - cache clear / nuke and login jobs stream here when run from Settings.',
    tests: 'Idle - Armory edits stay in the editor; forge and attack jobs stream on their tabs.',
    manual: 'Idle - Firing Range Q→A stays in the chat pane; other jobs may still stream here.',
    payloads: 'Idle - Multimodal asset work stays on this tab; run jobs stream on Attack / War Room.',
    notes: 'Idle - use Firing Range for Q→A; Add to notes is in that chat box.',
  };

  if (ctx.pipelineBusy?.value) {
    const phase = String(ctx.pipelinePhase?.value || '').trim();
    const strat = String(ctx.pipelineActiveStrategyLabel?.value || ctx.pipelineStrategy?.value || '').trim();
    const phaseLabel = phase === 'generate'
      ? 'generating suite'
      : phase === 'run'
        ? 'baseline run + assess'
        : phase === 'enhance'
          ? 'enhance auto-run'
          : 'running';
    const detail = strat
      ? `Start Battle · ${strat.replace(/_/g, ' ')} · ${phaseLabel}`
      : `Start Battle · ${phaseLabel}`;
    return { chip: 'Pipeline', tone: 'active', detail, placeholder: '' };
  }

  if (ctx.pbGenerating?.value) {
    const phase = String(ctx.pbGenerationCurrentPhase?.value || '').trim();
    return {
      chip: 'Building',
      tone: 'active',
      detail: phase || 'Planning mission play…',
      placeholder: '',
    };
  }

  if (j && jobIsActive(j.status)) {
    const chip = j.status === 'awaiting_theory' ? 'Awaiting theory' : 'Running';
    const tone = j.status === 'awaiting_theory' ? 'waiting' : 'active';
    let detail = '';
    if (tab.value === 'run' || tab.value === 'war-room') {
      detail = runJobStatusLabel.value || `${prettyJobType(j.type)} active`;
      if (tab.value === 'war-room' && j.type === 'security_assess') {
        detail = runProgressBarLabel.value || 'Security assessment in progress…';
      }
    } else if (j.type === 'generate') {
      detail = 'Generating probe suite…';
    } else if (j.type === 'security_assess') {
      detail = runProgressBarLabel.value || 'Security assessment in progress…';
    } else if (j.type === 'enhance_loop') {
      detail = runJobStatusLabel.value || 'Enhance & re-run loop active';
    } else if (j.type === 'recon_round') {
      detail = runJobStatusLabel.value || 'Recon round active';
    } else if (j.type === 'recon_from_report') {
      detail = runProgressBarLabel.value || 'Extracting recon from report(s)…';
    } else if (j.type === 'credentials_from_reports') {
      detail = 'Pulling credentials/paths from pipeline reports…';
    } else if (j.type === 'login') {
      const useCdp = !!ctx.effectiveLoginUseCdp?.value;
      detail = loginCdpCommand.value && !useCdp
        ? 'Run the Chrome command in Experiment Output, sign in, then press Enter (done).'
        : useCdp
          ? 'Chrome CDP login - sign in in the launched window, then press Enter (done).'
          : 'Waiting for browser sign-in…';
    } else if (j.type === 'sample_request') {
      detail = 'Sample fire at in-scope target…';
    } else {
      detail = `${prettyJobType(j.type)} · ${j.status}`;
    }
    return { chip, tone, detail, placeholder: '' };
  }

  if (j && (j.status === 'failed' || j.status === 'cancelled')) {
    return {
      chip: j.status === 'failed' ? 'Failed' : 'Cancelled',
      tone: 'failed',
      detail: lines.length ? 'See output below for details.' : '',
      placeholder: lines.length ? '' : 'Job ended without output.',
    };
  }

  if (j && j.status === 'done') {
    return {
      chip: 'Done',
      tone: 'done',
      detail: lines.length ? 'Last job finished - output below.' : 'Last job finished.',
      placeholder: tabHints[tab.value] || 'Idle - start a job on this tab to see live output.',
    };
  }

  if (lines.length) {
    return { chip: '', tone: 'idle', detail: '', placeholder: '' };
  }

  return {
    chip: 'Idle',
    tone: 'idle',
    detail: '',
    placeholder: tabHints[tab.value] || 'Output for the active tab appears here when a job runs.',
  };
});

const CHANNEL_MISMATCH_LINE = '[genbounty_channel_mismatch]';
const CHANNEL_MISMATCH_RE = /No playbook categories apply to strategy '([^']+)'/;

function parseChannelMismatchFromLines(lines) {
  if (!Array.isArray(lines) || !lines.length) return null;
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i];
    if (!line.includes(CHANNEL_MISMATCH_LINE)) continue;
    try {
      const payload = JSON.parse(line.split(CHANNEL_MISMATCH_LINE)[1].trim());
      if (payload && payload.type === 'channel_mismatch') return payload;
    } catch (_) { /* fall through */ }
  }
  for (let i = lines.length - 1; i >= 0; i--) {
    const m = lines[i].match(CHANNEL_MISMATCH_RE);
    if (m) {
      return {
        type: 'channel_mismatch',
        strategy: m[1],
        playbook_id: (ctx.gen.playbook || '').replace(/-/g, '_'),
      };
    }
  }
  return null;
}

const channelMismatchConverting = ref(false);
const channelMismatchMsg = ref('');
const channelMismatchResolved = ref(false);

const DISCOVERY_UI_MARKER = '[genbounty_discovery_ui]';

function parseDiscoveryUiPrompt(lines) {
  if (!Array.isArray(lines) || !lines.length) return null;
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i];
    if (!line.includes(DISCOVERY_UI_MARKER)) continue;
    try {
      const payload = JSON.parse(line.split(DISCOVERY_UI_MARKER)[1].trim());
      if (payload && payload.type === 'prompt') return payload;
    } catch (_) { /* fall through */ }
  }
  return null;
}

const discoveryUiPrompt = computed(() => {
  if (tab.value !== 'discover' || !manualDiscoverRunning.value) return null;
  return parseDiscoveryUiPrompt(activeOutput('manual_discover'));
});

const discoveryUiBusy = ref(false);

async function respondDiscoveryUi(actionType) {
  const prompt = discoveryUiPrompt.value;
  if (!manualDiscoverJobId.value || !prompt) return;
  discoveryUiBusy.value = true;
  try {
    await api(`/api/jobs/${manualDiscoverJobId.value}/stdin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: `${JSON.stringify({ type: actionType, id: prompt.id || '' })}\n`,
      }),
    });
  } catch (e) {
    console.error('Discovery UI response failed', e);
  } finally {
    discoveryUiBusy.value = false;
  }
}

function discoveryUiStepBadge() {
  const p = discoveryUiPrompt.value;
  if (!p) return '';
  if (p.step_number != null && p.step_total != null) {
    return `Step ${p.step_number} of ${p.step_total}`;
  }
  return '';
}

function discoveryUiStepHeading() {
  const p = discoveryUiPrompt.value;
  if (!p) return 'Component discovery';
  return (p.step_name || p.step_title || p.title || 'Component discovery').trim();
}

function discoveryUiBrowserSteps() {
  const p = discoveryUiPrompt.value;
  if (!p) return [];
  if (Array.isArray(p.instructions) && p.instructions.length) {
    return p.instructions.map((s) => String(s).trim()).filter(Boolean);
  }
  const out = [];
  if ((p.do_now || '').trim()) out.push(String(p.do_now).trim());
  if ((p.tip || '').trim()) out.push(`Tip: ${String(p.tip).trim()}`);
  if ((p.warn || '').trim()) out.push(`⚠ ${String(p.warn).trim()}`);
  if (Array.isArray(p.saved_lines) && p.saved_lines.length) {
    out.push(`Already saved (${p.saved_lines.length}): ${p.saved_lines.slice(0, 5).join('; ')}`);
  }
  if (out.length) return out;
  const msg = (p.message || '').trim();
  if (!msg) return [];
  return msg.split(/\n+/).map((s) => s.trim()).filter(Boolean);
}

function discoveryUiWhatToDo() {
  const p = discoveryUiPrompt.value;
  if (!p) return [];
  const steps = discoveryUiBrowserSteps();
  if (p.mode === 'pick') {
    const out = steps.length ? [...steps] : ['Click the target in the browser.'];
    if ((p.action || '').trim()) {
      out.push(`Or "${p.action}" to skip.`);
    }
    return out;
  }
  if (p.mode === 'busy') {
    return steps.length ? steps : ['Please wait - do not use the browser.'];
  }
  if (p.mode === 'confirm') {
    const primary = discoveryUiPrimaryLabel();
    const secondary = discoveryUiSecondaryLabel();
    const out = steps.length ? [...steps] : ['Review the captured value.'];
    if (primary && secondary) {
      out.push(`"${primary}" to save, or "${secondary}" to redo.`);
    } else if (primary) {
      out.push(`Click "${primary}" when ready.`);
    }
    return out;
  }
  const label = p.action || 'Continue';
  if (!steps.length) {
    return [`Click "${label}" when ready.`];
  }
  return [...steps, `Then click "${label}".`];
}

function discoveryUiSummary() {
  const p = discoveryUiPrompt.value;
  if (!p) return '';
  return (p.summary || '').trim();
}

function discoveryUiModeNote() {
  const lines = activeOutput('manual_discover');
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i];
    if (!line.includes(DISCOVERY_UI_MARKER)) continue;
    try {
      const payload = JSON.parse(line.split(DISCOVERY_UI_MARKER)[1].trim());
      if (payload && payload.type === 'mode' && payload.message) return payload.message;
    } catch (_) { /* fall through */ }
  }
  return '';
}

function discoveryUiPrimaryLabel() {
  const p = discoveryUiPrompt.value;
  if (!p) return 'Continue';
  if (p.mode === 'confirm') return p.action || 'Confirm & save';
  if (p.mode === 'pick') return '';
  return p.action || 'Continue';
}

function discoveryUiSecondaryLabel() {
  const p = discoveryUiPrompt.value;
  if (!p) return '';
  if (p.secondary) return p.secondary;
  if (p.mode === 'pick' && (p.action || '').trim()) return p.action;
  return '';
}

function discoveryUiShowPrimary() {
  const p = discoveryUiPrompt.value;
  if (!p || p.mode === 'busy' || p.mode === 'pick') return false;
  return Boolean(discoveryUiPrimaryLabel());
}

function discoveryUiShowSecondary() {
  const p = discoveryUiPrompt.value;
  if (!p) return false;
  // Pick mode: primary already shows Done/Skip - do not duplicate it as secondary.
  if (p.mode === 'pick' && (p.action || '').trim() && !(p.secondary || '').trim()) return false;
  if (p.secondary) return true;
  if (p.mode === 'pick' && (p.action || '').trim()) return true;
  return false;
}

async function discoveryUiPrimaryAction() {
  const p = discoveryUiPrompt.value;
  if (!p) return;
  if (p.mode === 'confirm') await respondDiscoveryUi('confirm');
  // Pick-mode primary is Skip/Done - must send skip, not continue.
  else if (p.mode === 'pick' && (p.action || '').trim()) await respondDiscoveryUi('skip');
  else await respondDiscoveryUi('continue');
}

async function discoveryUiSecondaryAction() {
  const p = discoveryUiPrompt.value;
  if (!p) return;
  const sec = (p.secondary || '').toLowerCase();
  const act = (p.action || '').toLowerCase();
  if (p.mode === 'confirm') await respondDiscoveryUi('retry');
  else if (p.mode === 'pick' && (p.action || '').trim()) await respondDiscoveryUi('skip');
  else if (sec.includes('skip') || act.includes('skip') || act.includes('done')) await respondDiscoveryUi('skip');
  else await respondDiscoveryUi('retry');
}

const channelMismatchAction = computed(() => {
  if (tab.value !== 'generate' || channelMismatchResolved.value) return null;
  const lines = panelOutput.value;
  if (!lines.length) return null;
  const payload = parseChannelMismatchFromLines(lines);
  if (!payload) return null;
  const playbookId = (payload.playbook_id || ctx.gen.playbook || '').replace(/-/g, '_');
  const strategy = payload.strategy || ctx.gen.strategy || '';
  const artifactN = payload.artifact_categories;
  const textN = payload.text_categories;
  const channelDetail = Number.isFinite(artifactN)
    ? `${artifactN} artifact categor${artifactN === 1 ? 'y' : 'ies'}`
    : 'artifact-channel categories';
  const strategyLabel = pretty(String(strategy || '').replace(/-/g, '_'));
  return {
    playbook_id: playbookId,
    strategy,
    strategyLabel,
    channelDetail,
    textCategories: textN,
    canConvert: Number.isFinite(artifactN) ? artifactN > 0 : true,
    message:
      `Strategy “${strategyLabel}” only runs text-channel categories, but this play uses ${channelDetail}. `
      + 'For CTF targets with a text-only chat harness, convert the playbook to paste content inline instead of file upload.',
  };
});

async function convertPlaybookToTextChannel() {
  const action = channelMismatchAction.value;
  const playbookId = (action?.playbook_id || ctx.gen.playbook || '').replace(/-/g, '_');
  if (!playbookId) return;
  channelMismatchConverting.value = true;
  channelMismatchMsg.value = '';
  try {
    const res = await api(
      `/api/playbooks/${encodeURIComponent(playbookId)}/convert-text-channel`,
      { method: 'POST' },
    );
    channelMismatchMsg.value = res.message || 'Playbook converted to text-based channel.';
    channelMismatchResolved.value = true;
    await loadSites();
    await ctx.pbLoadCatalog(playbookId);
    await ctx.setActivePlaybook(playbookId, { source: 'force' });
  } catch (e) {
    channelMismatchMsg.value = 'Conversion failed: ' + (e.message || String(e));
  } finally {
    channelMismatchConverting.value = false;
  }
}

function connectSSE(jobId) {
  if (sseConnections[jobId]) return;
  const j = jobs.value.find(x => x.id === jobId);
  if (!j) return;
  if (!j._output) j._output = [];
  const src = new EventSource(`/api/jobs/${jobId}/stream`);
  sseConnections[jobId] = src;
  src.onmessage = (e) => {
    const line = e.data;
    const progressPrefix = line.startsWith('[genbounty_progress] ')
      ? '[genbounty_progress] '
      : line.startsWith('[airta_progress] ')
        ? '[airta_progress] '
        : null;
    if (progressPrefix) {
      try {
        const p = JSON.parse(line.slice(progressPrefix.length));
        const isRunJob = (j.type === 'run_tests' || j.type === 'enhance_loop' || j.type === 'recon_round') && activeJobs.run_tests === j.id;
        const isRiskJob = j.type === 'security_assess' && activeJobs.security_assess === j.id;
        const isReconReportJob = j.type === 'recon_from_report' && activeJobs.recon_from_report === j.id;
        if (p.type === 'screenshot') {
          if (isRunJob) {
            try {
              runLivePanelOpen.value = true;
              updateRunPreview(p.job_id || jobId, p.slot ?? 0, {
                sequence: p.sequence,
              });
            } catch (err) {
              console.warn('[run preview] screenshot update failed:', err);
            }
          }
        } else if (isRunJob || isRiskJob || isReconReportJob) {
          if (p.type === 'theory_review' && isRunJob) {
            // Deploy Probes / Auto-run must not block on the theory modal.
            if (ctx.pipelineBusy?.value) {
              const jid = String(p.job_id || j.id || '').trim();
              runProgress.value = { ...p, pct: 0, phase: 'enhance' };
              if (jid && typeof api === 'function') {
                api(`/api/jobs/${encodeURIComponent(jid)}/theory/accept`, { method: 'POST' })
                  .catch((e) => console.warn('[pipeline] auto-accept theory failed:', e));
              }
            } else {
              openEnhanceTheoryReview(p);
              runProgress.value = { ...p, pct: 0, phase: 'theory' };
            }
          } else if (p.type === 'theory_auto_accepted' && isRunJob) {
            // Unattended Auto-run: never open the confirmation modal.
            runProgress.value = { ...p, pct: 0, phase: 'enhance' };
          } else if (p.type === 'cloudflare_wait' && isRunJob) {
            runBlockedInfo.value = { ...runBlockedInfo.value, ...p, kind: 'cloudflare' };
            if (!runCloudflareModalShown.value) {
              runCloudflareModalShown.value = true;
              pendingRunAfterCloudflare.value = true;
              showRunCloudflareModal.value = true;
            }
            runProgress.value = {
              ...runProgress.value,
              phase: 'blocked',
              remaining_sec: p.remaining_sec,
              pct: runProgress.value?.pct ?? 0,
            };
          } else if (p.type === 'blocked' && isRunJob) {
            runBlockedInfo.value = p;
            if (p.kind === 'login_required' || p.action === 'prompt_login' || p.action === 'start_login') {
              pendingRunAfterLogin.value = true;
              runLoginUrl.value = p.login_url || ctx.loginUrl?.value || '';
              showRunLoginModal.value = true;
            } else if (p.kind === 'rate_limited' || p.action === 'prompt_rate_limit') {
              pendingRunAfterRateLimit.value = true;
              runRateLimitBackoffSec.value = Math.max(1, Math.round(Number(p.backoff_sec) || 60));
              showRunRateLimitModal.value = true;
            } else if (p.kind === 'cloudflare' || p.action === 'prompt_cloudflare') {
              ctx.handleRunCloudflareBlocked(p);
            }
            runProgress.value = { ...p, pct: runProgress.value?.pct ?? 0, phase: 'blocked' };
          } else {
          let pct = 0;
          let phase = p.phase || 'submit';
          if (p.type === 'suite') {
            const total = p.total || 0;
            const cur = p.current || 0;
            pct = total ? Math.min(100, Math.round((cur / total) * 100)) : 0;
            phase = 'suite';
          } else if (p.type === 'run_start') {
            pct = 0;
            phase = 'submit';
            // Keep prior Run rows visible until the first probe_result (cur===1)
            // replaces the snapshot. Clearing here caused an empty-table flash.
            if (isRunJob && ctx.runResultsLoading) {
              ctx.runResultsLoading.value = false;
            }
          } else if (p.type === 'probe_result' && isRunJob) {
            const total = p.total || 0;
            const cur = p.current || 0;
            pct = total ? Math.min(100, Math.round((cur / total) * 100)) : 0;
            phase = 'submit';
            const windowId = ctx.normalizeFindingsMetricsWindow
              ? ctx.normalizeFindingsMetricsWindow(ctx.findingsMetricsWindow?.value)
              : (ctx.findingsMetricsWindow?.value || 'last_run');
            // Live rows only feed the table in last_run mode (period windows merge logs).
            if (windowId === 'last_run' && ctx.runResults) {
              const row = {
                label: p.label || `#${cur || (ctx.runResults?.value?.length || 0) + 1}`,
                turnFraction: String(cur || ''),
                isMultiTurn: false,
                input: p.input || '',
                response: p.response || '',
                submissionOutcome: p.submission_outcome || '',
                rejectionSignals: p.rejection_signals || [],
              };
              // First probe of a run replaces the prior snapshot (including when
              // run_start was missed).
              if (cur === 1) {
                if (ctx.expandedRunRows) ctx.expandedRunRows.value = {};
                ctx.runResults.value = [row];
              } else {
                ctx.runResults.value = [...(ctx.runResults.value || []), row];
              }
              if (ctx.runResultsLoading) ctx.runResultsLoading.value = false;
            }
          } else if (p.type === 'progress' && p.mode) {
            const total = p.total || 0;
            const cur = p.current || 0;
            pct = total ? Math.min(100, Math.round((cur / total) * 100)) : 0;
            phase = 'submit';
          } else if (p.type === 'run_done') {
            pct = 100;
            phase = 'submit';
          } else if (p.type === 'batch_start') {
            pct = 0;
            phase = p.phase === 'recon_from_report' ? 'recon_from_report' : 'risk';
          } else if (p.type === 'batch_progress') {
            const total = p.total || 0;
            const cur = p.current || 0;
            pct = total ? Math.min(100, Math.round((cur / total) * 100)) : 0;
            phase = p.phase === 'recon_from_report' ? 'recon_from_report' : 'risk';
          } else if (p.type === 'batch_done') {
            pct = 100;
            phase = p.phase === 'recon_from_report' ? 'recon_from_report' : 'risk';
          } else if (p.type === 'risk_start' || p.type === 'security_start') {
            pct = 0;
            phase = 'risk';
            if (ctx.riskViewLoading) {
              // Keep prior Risk rows until first risk_result replaces (appendLiveRiskResult
              // resets on cur===1). Avoid empty-table flash.
              ctx.riskViewLoading.value = false;
            }
          } else if (p.type === 'risk_result') {
            const total = p.total || 0;
            const cur = p.current || 0;
            const inflight = p.in_flight != null
              ? p.in_flight
              : Math.max(0, (runProgress.value?.in_flight || 1) - 1);
            pct = total
              ? Math.min(99, Math.round(((cur + inflight * 0.4) / total) * 100))
              : 0;
            phase = 'risk';
            p.in_flight = inflight;
            if (typeof ctx.appendLiveRiskResult === 'function') {
              ctx.appendLiveRiskResult(p);
            }
          } else if (p.type === 'risk_progress' || p.type === 'security_progress') {
            const total = p.total || 0;
            const cur = p.current || 0;
            const inflight = p.in_flight || 0;
            pct = total
              ? Math.min(99, Math.round(((cur + inflight * 0.4) / total) * 100))
              : 0;
            phase = 'risk';
          } else if (p.type === 'risk_done' || p.type === 'security_done') {
            pct = 100;
            phase = 'risk';
          } else if (p.type === 'theory_review') {
            pct = 0;
            phase = 'theory';
          } else if (p.type === 'theory_auto_accepted') {
            pct = runProgress.value?.pct ?? 0;
            phase = 'enhance';
          } else if (p.type === 'enhance_round') {
            const total = p.total || 1;
            const cur = p.current || 1;
            pct = Math.min(95, Math.round(((cur - 0.5) / total) * 100));
            phase = 'enhance';
          } else if (p.type === 'enhance_result') {
            const total = p.total || runProgress.value?.total || 1;
            const cur = p.round || p.current || 1;
            pct = Math.min(100, Math.round((cur / total) * 100));
            phase = 'enhance';
          }
          runProgress.value = {
            ...p,
            pct,
            phase,
            elapsed_sec: p.elapsed_sec != null && p.elapsed_sec !== '' ? p.elapsed_sec : (runProgress.value?.elapsed_sec ?? 0),
            _localElapsedAt: Date.now(),
          };
          ensureRunProgressClock();
          }
        }
        const isWarRoomCampaign =
          (j.type === 'run_tests' || j.type === 'enhance_loop') && activeJobs.run_tests === j.id;
        const isWarRoomRiskJob =
          j.type === 'security_assess' && activeJobs.security_assess === j.id;
        if (
          p.type !== 'screenshot'
          && (isWarRoomCampaign || isWarRoomRiskJob)
        ) {
          warRoomOnProgress(j, p, {
            isCampaign: isWarRoomCampaign,
            isRisk: isWarRoomRiskJob || isWarRoomCampaign,
          });
        }
      } catch { /* ignore */ }
    }
    j._output.push(line);
    nextTick(() => {
      ctx.maybeScrollOutputConsole();
    });
  };
  src.addEventListener('done', (e) => {
    j.status = e.data || 'done';
    src.close();
    delete sseConnections[jobId];
    if (
      warRoomIsMonitoredJob(j)
      || (warRoomMeta.value && warRoomMeta.value.jobId === j.id)
    ) {
      warRoomOnJobTerminal(j, e.data || 'done');
    }
    refreshJobs();
    if (j.type === 'run_tests' || j.type === 'enhance_loop' || j.type === 'recon_round') {
      closeEnhanceTheoryModal();
      // Re-apply snapshotted play/strategy so UI isn't left blank after
      // loadRunTestFiles wiped selection mid-run (few_shot vs few-shot).
      if (j.type === 'enhance_loop' || j.type === 'run_tests') {
        const p = j.params || {};
        const play = String(p.playbook || '').trim();
        const strat = String(p.strategy || '').trim();
        if (play) ctx.run.playbook = play.replace(/_/g, '-');
        if (strat && strat !== '__all__') {
          const hyphen = G.hyphenStratSlug
            ? G.hyphenStratSlug(strat)
            : String(strat).replace(/_/g, '-');
          ctx.run.strategy = hyphen;
          if (typeof runOnTestFileChange === 'function') {
            runOnTestFileChange(true);
          }
          // Prefer disk slug from loaded strategies when available.
          const matched = (G.matchStrategySlug || ctx.matchStrategySlug)?.(
            runStrategies.value,
            hyphen,
          );
          if (matched) ctx.run.strategy = matched;
        }
        ctx.run.scope = 'playbook';
        ctx.run.assess = true;
      }
      if (typeof ctx.syncRunTableToMetricsWindow === 'function') {
        ctx.syncRunTableToMetricsWindow();
      } else {
        ctx.loadLatestRunLog();
      }
      if (j.type === 'enhance_loop') { ctx.loadLogs(); }
      if ((j.type === 'run_tests' || j.type === 'enhance_loop') && e.data === 'done' && jobWantsAssess(j)) {
        ctx.loadLogs().then(() => {
          if (typeof ctx.syncRiskTableToMetricsWindow === 'function') {
            return ctx.syncRiskTableToMetricsWindow();
          }
          return ctx.loadLatestRiskReport();
        });
      }
      if (j.type === 'recon_round' && e.data === 'done') { ctx.loadRecon(); refreshIntelAfterJob(); }
      setTimeout(() => {
        if (activeJobs.run_tests === j.id) {
          runProgress.value = null;
          stopRunProgressClock();
        }
      }, 5000);
    }
    if (j.type === 'security_assess') {
      ctx.loadLogs().then(() => {
        if (typeof ctx.syncRiskTableToMetricsWindow === 'function') {
          return ctx.syncRiskTableToMetricsWindow();
        }
        return ctx.loadLatestRiskReport();
      });
      if (tab.value === 'intel') ctx.loadCredentialsAndPaths();
      setTimeout(() => {
        if (activeJobs.security_assess === j.id) {
          runProgress.value = null;
          stopRunProgressClock();
        }
      }, 5000);
    }
    if (j.type === 'credentials_from_reports') {
      ctx.loadCredentialsAndPaths().then(() => {
        capMsg.value = e.data === 'done'
          ? 'Credentials/paths pull complete'
          : `Credentials/paths job ${e.data || 'finished'}`;
      });
    }
    if ((j.type === 'recon' || j.type === 'recon_from_report') && e.data === 'done') {
      ctx.loadRecon();
      refreshIntelAfterJob();
    }
    if ((j.type === 'run_tests' || j.type === 'enhance_loop') && e.data === 'done') {
      refreshIntelAfterJob();
    }
  });
  src.onerror = () => {
    src.close();
    delete sseConnections[jobId];
  };
}

async function refreshJobs() {
  const list = await api('/api/jobs');
  const remoteIds = new Set((list || []).map((j) => j.id));
  for (const j of list) {
    const existing = jobs.value.find(x => x.id === j.id);
    if (existing) {
      existing.status = j.status;
      if (warRoomMeta.value && warRoomMeta.value.jobId === existing.id) {
        warRoomSetStatus(existing.status);
        warRoomActive.value = !!jobIsActive(existing.status);
      }
    } else {
      j._output = [];
      jobs.value.unshift(j);
    }
  }
  // After a server restart, in-memory jobs are gone but the UI may still hold
  // rows stuck on running/pending - that keeps _schedulePoll forever. Mark them
  // cancelled so the backup poller and pipeline waiters can stop.
  const isActive = typeof jobIsActive === 'function'
    ? jobIsActive
    : (s) => s === 'running' || s === 'pending' || s === 'awaiting_theory';
  for (const local of jobs.value || []) {
    if (!remoteIds.has(local.id) && isActive(local.status)) {
      local.status = 'cancelled';
    }
  }
}

function jobWantsAssess(j) {
  const v = j?.params?.assess;
  if (typeof v === 'string') return /^(1|true|yes|on)$/i.test(v.trim());
  return !!v;
}

/** Backup status sync when SSE misses a terminal `done` event. */
let _jobPollTimer = null;
function _schedulePoll() {
  if (_jobPollTimer != null) return;
  _jobPollTimer = setInterval(async () => {
    const isActive = typeof ctx.jobIsActive === 'function'
      ? ctx.jobIsActive
      : (s) => s === 'running' || s === 'pending' || s === 'awaiting_theory';
    const active = (jobs.value || []).filter((j) => isActive(j.status));
    if (!active.length) {
      clearInterval(_jobPollTimer);
      _jobPollTimer = null;
      return;
    }
    try {
      await refreshJobs();
    } catch (_e) { /* ignore */ }
  }, 2000);
}
ctx._schedulePoll = _schedulePoll;

async function startJob(type, params = {}) {
  const res = await api('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, site: site.value, component: component.value, params })
  });
  res._output = [];
  jobs.value.unshift(res);
  activeJobs[type] = res.id;
  if (type === 'run_tests' || type === 'enhance_loop') {
    activeJobs.run_tests = res.id;
    warRoomResetForJob(res);
    if (typeof ctx.selectSidebarTab === 'function') {
      ctx.selectSidebarTab('war-room');
    }
  } else if (type === 'security_assess') {
    warRoomResetForJob(res);
  }
  connectSSE(res.id);
  _schedulePoll();
  return res;
}

async function cancelJob(id, opts = {}) {
  const soft = !!opts.soft;
  const j = jobs.value.find(x => x.id === id);
  if (j && jobIsActive(j.status)) {
    j.status = 'cancelled';
  }
  try {
    await api(`/api/jobs/${id}`, { method: 'DELETE' });
  } catch (err) {
    try {
      if (j) await refreshJobs();
    } catch (_e) { /* ignore */ }
    if (soft) return false;
    throw err;
  }
  try {
    await refreshJobs();
  } catch (_e) { /* ignore */ }
  return true;
}

/** Jobs drawer Cancel - never throw (avoids white-screen on mid-flight DELETE). */
async function onJobsDrawerCancel(j) {
  const id = String(j?.id || '').trim();
  if (!id) return;
  try {
    await cancelJob(id, { soft: true });
  } catch (e) {
    console.warn('Job cancel failed:', e);
  }
}


const manualDiscoverJobId = ref(null);
const manualDiscoverRunning = computed(() => {
  if (!manualDiscoverJobId.value) return false;
  const j = jobs.value.find(x => x.id === manualDiscoverJobId.value);
  return j && j.status === 'running';
});

    const api_out = {
      jobsDrawerSummary,
      updateRunPreview,
      clearRunPreviews,
      openRunPreviewModal,
      closeRunPreviewModal,
      formatRunEta,
      ENHANCE_PHASE_LABELS,
      warRoomActive,
      warRoomHasSnapshot,
      warRoomMeta,
      warRoomProgress,
      warRoomOutcomes,
      warRoomRiskCounts,
      warRoomFeed,
      warRoomQaFeed,
      runEnhancePhaseLabel,
      runProgressBarLabel,
      runProgressDisplayPct,
      runProgressLive,
      warRoomOpsProgressActive,
      runJobStatusLabel,
      canSkipCurrentRunPrompt,
      runProgressEtaText,
      riskTabProgressBarVisible,
      loadSites,
      CONTEXT_SITE_KEY,
      CONTEXT_COMPONENT_KEY,
      persistContextSelection,
      readSavedContextSelection,
      applySavedContext,
      onSiteChange,
      refreshIntelAfterJob,
      loadContext,
      runSuitePath,
      loadRunSubmissionTransport,
      loadRunTestFiles,
      runOnScopeChange,
      runOnCategoryChange,
      runSelectedTestFile,
      runGenerationProfile,
      runGenerationNotes,
      runOnTestFileChange,
      runOnStrategyChange,
      loadRunArtifactStatus,
      refreshTargetCapabilities,
      firstAllowedGenerateStrategy,
      ensureGenStrategySelection,
      strategyBlockedOnStatelessTarget,
      availableGenerateStrategies,
      availableRunStrategies,
      isStrategyOptionDisabled,
      strategyOptionDisabledSuffix,
      multiTurnBlockedNote,
      suiteExistsForSelection,
      hasAssessedReport,
      refreshRunTests,
      _isRunDetailLine,
      _isProgressMetaLine,
      activeOutput,
      SAMPLE_RESULT_MARKER,
      MANUAL_ASSESS_RESULT_MARKER,
      sampleIntelAdded,
      sampleIntelBusy,
      sampleIntelMsg,
      sidebarSampleReplyCleared,
      manualAssessMsg,
      manualAssessCheckboxTitle,
      manualFireBusyLabel,
      manualFireButtonTitle,
      manualCommandBusy,
      _parseSampleResultFromJob,
      _tabPanelOutput,
      _lineLooksLikeFilesystemPath,
      _securityAssessOverviewLines,
      panelOutputIsSample,
      sampleResultAction,
      _sampleResponseBodyFromLines,
      sidebarSampleReply,
      panelOutput,
      panelOutputLines,
      loginCdpCommand,
      copyLoginCdpCommand,
      panelOutputStatus,
      CHANNEL_MISMATCH_LINE,
      CHANNEL_MISMATCH_RE,
      parseChannelMismatchFromLines,
      channelMismatchConverting,
      channelMismatchMsg,
      channelMismatchResolved,
      DISCOVERY_UI_MARKER,
      parseDiscoveryUiPrompt,
      discoveryUiPrompt,
      discoveryUiBusy,
      respondDiscoveryUi,
      discoveryUiStepBadge,
      discoveryUiStepHeading,
      discoveryUiBrowserSteps,
      discoveryUiWhatToDo,
      discoveryUiSummary,
      discoveryUiModeNote,
      discoveryUiPrimaryLabel,
      discoveryUiSecondaryLabel,
      discoveryUiShowPrimary,
      discoveryUiShowSecondary,
      discoveryUiPrimaryAction,
      discoveryUiSecondaryAction,
      channelMismatchAction,
      convertPlaybookToTextChannel,
      connectSSE,
      refreshJobs,
      jobWantsAssess,
      startJob,
      cancelJob,
      onJobsDrawerCancel,
      _schedulePoll,
      manualDiscoverJobId,
      manualDiscoverRunning
    };
    Object.assign(ctx, api_out);
    ctx._schedulePoll = _schedulePoll;
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
