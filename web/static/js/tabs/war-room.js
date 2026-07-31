/**
 * Domain module: useWarRoom - computed helpers for the War Room live monitor.
 * Progress state is written only from jobs.js SSE handlers (warRoom*).
 */
(function (G) {
  'use strict';

  G.useWarRoom = function useWarRoom(ctx) {
    const { computed, ref } = ctx;

    if (!ctx.warRoomActive) ctx.warRoomActive = ref(false);
    if (!ctx.warRoomHasSnapshot) ctx.warRoomHasSnapshot = ref(false);
    if (!ctx.warRoomMeta) ctx.warRoomMeta = ref(null);
    if (!ctx.warRoomProgress) ctx.warRoomProgress = ref(null);
    if (!ctx.warRoomOutcomes) {
      ctx.warRoomOutcomes = ref({ ok: 0, rejected: 0, other: 0 });
    }
    if (!ctx.warRoomRiskCounts) {
      ctx.warRoomRiskCounts = ref({
        critical: 0,
        high: 0,
        medium: 0,
        low: 0,
        informational: 0,
        indeterminate: 0,
        other: 0,
      });
    }
    if (!ctx.warRoomFeed) ctx.warRoomFeed = ref([]);
    if (!ctx.warRoomQaFeed) ctx.warRoomQaFeed = ref([]);
    if (!ctx.warRoomStartedAt) ctx.warRoomStartedAt = ref(null);
    if (!ctx.warRoomTick) ctx.warRoomTick = ref(0);

    const warRoomJobTypeLabel = computed(() => {
      const t = ctx.warRoomMeta?.value?.jobType;
      if (t === 'enhance_loop') return 'Enhance';
      if (t === 'run_tests') return 'Attack';
      if (t === 'security_assess') return 'Risk';
      return t ? (G.prettyJobType ? G.prettyJobType(t) : t) : '';
    });

    const warRoomStatusBadge = computed(() => {
      const s = String(ctx.warRoomMeta?.value?.status || 'idle');
      if (s === 'awaiting_theory') return 'awaiting_theory';
      if (s === 'running' || s === 'pending') return 'running';
      if (s === 'done') return 'done';
      if (s === 'failed') return 'failed';
      if (s === 'cancelled') return 'cancelled';
      return 'pending';
    });

    const warRoomStatusLabel = computed(() => {
      const s = String(ctx.warRoomMeta?.value?.status || '');
      if (s === 'awaiting_theory') return 'Awaiting theory';
      if (s === 'running') return 'Live';
      if (s === 'pending') return 'Pending';
      if (s === 'done') return 'Done';
      if (s === 'failed') return 'Failed';
      if (s === 'cancelled') return 'Cancelled';
      return s || 'Idle';
    });

    const warRoomPctLabel = computed(() => {
      // Prefer the live display % (soft in-flight) so PROGRESS matches the status strip.
      const livePct = ctx.runProgressDisplayPct?.value;
      const opsLive = ctx.warRoomOpsProgressActive?.value;
      if (opsLive && livePct != null && Number.isFinite(Number(livePct))) {
        return `${Math.max(0, Math.min(100, Math.round(Number(livePct))))}%`;
      }
      const p = ctx.warRoomProgress?.value;
      if (!p) return '-';
      const pct = Number(p.pct);
      if (Number.isFinite(pct)) return `${Math.max(0, Math.min(100, Math.round(pct)))}%`;
      const total = Number(p.total) || 0;
      const cur = Number(p.current) || 0;
      const inflight = Number(p.in_flight) || 0;
      if (total > 0) {
        return `${Math.min(100, Math.round(((cur + inflight * 0.4) / total) * 100))}%`;
      }
      return '-';
    });

    const warRoomCurrentTotal = computed(() => {
      const p = ctx.warRoomProgress?.value;
      if (!p) return '-';
      const cur = p.current != null ? p.current : (p.round != null ? p.round : null);
      const total = p.total != null ? p.total : null;
      const inflight = Number(p.in_flight) || 0;
      if (cur == null && total == null) return '-';
      if (inflight > 0 && total != null) {
        return `${cur != null ? cur : 0}+${inflight}/${total}`;
      }
      return `${cur != null ? cur : '-'}/${total != null ? total : '-'}`;
    });

    const warRoomElapsedLabel = computed(() => {
      // Wall-clock campaign elapsed while live - stays concurrent between SSE heartbeats.
      void ctx.warRoomTick?.value;
      const fmt = ctx.formatRunEta || G.formatRunEta;
      let sec = null;
      if (ctx.warRoomActive?.value && ctx.warRoomStartedAt?.value) {
        sec = Math.max(0, (Date.now() - Number(ctx.warRoomStartedAt.value)) / 1000);
      } else {
        const p = ctx.warRoomProgress?.value;
        if (p && p.elapsed_sec != null && p.elapsed_sec !== '' && Number.isFinite(Number(p.elapsed_sec))) {
          sec = Number(p.elapsed_sec);
        } else if (ctx.warRoomStartedAt?.value) {
          sec = Math.max(0, (Date.now() - Number(ctx.warRoomStartedAt.value)) / 1000);
        }
      }
      if (sec == null) return '-';
      return fmt ? fmt(sec) : `${Math.round(sec)}s`;
    });

    const warRoomEtaLabel = computed(() => {
      void ctx.warRoomTick?.value;
      const p = ctx.warRoomProgress?.value;
      const fmt = ctx.formatRunEta || G.formatRunEta;
      if (p && p.eta_sec != null && p.eta_sec !== '' && Number.isFinite(Number(p.eta_sec))) {
        return fmt ? fmt(Number(p.eta_sec)) : String(p.eta_sec);
      }
      // Throughput estimate when SSE omitted eta (common on enhance_round).
      const cur = Number(p?.current);
      const total = Number(p?.total);
      let elapsed = null;
      if (p && p.elapsed_sec != null && Number.isFinite(Number(p.elapsed_sec))) {
        elapsed = Number(p.elapsed_sec);
      } else if (ctx.warRoomStartedAt?.value) {
        elapsed = Math.max(0, (Date.now() - Number(ctx.warRoomStartedAt.value)) / 1000);
      }
      if (!(elapsed > 0) || !(cur > 0) || !(total > cur)) return '-';
      const eta = (elapsed / cur) * (total - cur);
      return fmt ? fmt(eta) : `${Math.round(eta)}s`;
    });

    const warRoomEnhancePhaseLabel = computed(() => {
      const p = ctx.warRoomProgress?.value;
      if (!p) return '';
      const phase = String(p.enhance_phase || p.enhancePhase || '').trim().toLowerCase();
      if (!phase) return '';
      const labels = ctx.ENHANCE_PHASE_LABELS || {};
      return labels[phase] || phase;
    });

    const warRoomSeverityCounts = computed(() => {
      const c = ctx.riskMetricsWindowCounts?.value;
      if (c && typeof c === 'object') return c;
      return ctx.warRoomRiskCounts?.value || {
        critical: 0,
        high: 0,
        medium: 0,
        low: 0,
        informational: 0,
        indeterminate: 0,
        other: 0,
      };
    });

    const warRoomRiskChips = computed(() => {
      const c = warRoomSeverityCounts.value || {};
      // Crit/High/Med/Low have dedicated tiles; chips cover Info/Other only.
      const order = [
        ['informational', 'Info'],
        ['other', 'Other'],
      ];
      return order
        .filter(([id]) => (Number(c[id]) || 0) > 0)
        .map(([id, label]) => ({ id, label, count: Number(c[id]) || 0 }));
    });

    const warRoomRiskTotal = computed(() => {
      const c = warRoomSeverityCounts.value || {};
      return (
        (Number(c.critical) || 0)
        + (Number(c.high) || 0)
        + (Number(c.medium) || 0)
        + (Number(c.low) || 0)
        + warRoomRiskChips.value.reduce((n, chip) => n + chip.count, 0)
      );
    });

    function warRoomFormatTs(ts) {
      try {
        const d = new Date(ts);
        if (Number.isNaN(d.getTime())) return '';
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      } catch (_e) {
        return '';
      }
    }

    function warRoomTruncateText(s, n = 280) {
      const t = String(s || '').replace(/\s+/g, ' ').trim();
      if (t.length <= n) return t;
      return `${t.slice(0, n - 1)}…`;
    }

    /** Seed Firing Range with TX text; do not Fire (avoids colliding with live jobs). */
    function warRoomOpenManualPrompt(row) {
      const prompt = String(row?.prompt || '').trim();
      if (!prompt) return;
      if (ctx.run) ctx.run.samplePrompt = prompt;
      if (ctx.manualNativeLanguage) ctx.manualNativeLanguage.value = 'human';
      if (ctx.manualNativePrevLanguage) ctx.manualNativePrevLanguage.value = 'human';
      if (ctx.manualHumanPromptBackup) ctx.manualHumanPromptBackup.value = prompt;
      if (ctx.manualNativeMsg) ctx.manualNativeMsg.value = '';
      if (typeof ctx.openManualCommandView === 'function') {
        ctx.openManualCommandView();
      }
    }

    Object.assign(ctx, {
      warRoomJobTypeLabel,
      warRoomStatusBadge,
      warRoomStatusLabel,
      warRoomPctLabel,
      warRoomCurrentTotal,
      warRoomElapsedLabel,
      warRoomEtaLabel,
      warRoomEnhancePhaseLabel,
      warRoomSeverityCounts,
      warRoomRiskChips,
      warRoomRiskTotal,
      warRoomFormatTs,
      warRoomTruncateText,
      warRoomOpenManualPrompt,
    });
  };
})(window.Genbounty = window.Genbounty || {});
