/**
 * Vue setup orchestrator: calls Genbounty.use* domain factories in order and
 * returns ctx for Vue setup(). Domain UI logic lives in js/tabs/*, js/jobs.js,
 * and js/app-lifecycle.js.
 */
(function (G) {
  'use strict';

  G.useAppSetup = function useAppSetup(ctx) {
    const { ref, watch } = ctx;

    // Shared helpers for domain modules (createCtx already has api / isAbortError).
    Object.assign(ctx, {
      api: G.api,
      isAbortError: G.isAbortError,
      pretty: G.pretty,
      prettyJobType: G.prettyJobType,
      lineClass: G.lineClass,
      normStratSlug: G.normStratSlug,
      hyphenStratSlug: G.hyphenStratSlug,
      matchStrategySlug: G.matchStrategySlug,
      FINDINGS_METRICS_WINDOW_KEY: G.FINDINGS_METRICS_WINDOW_KEY,
      FINDINGS_METRICS_WINDOWS: G.FINDINGS_METRICS_WINDOWS,
      normalizeFindingsMetricsWindow: G.normalizeFindingsMetricsWindow,
      readTabSelections: G.readTabSelections,
      writeTabSelections: G.writeTabSelections,
      RUN_TAB_SELECTIONS_KEY: G.RUN_TAB_SELECTIONS_KEY,
      TM_TAB_SELECTIONS_KEY: G.TM_TAB_SELECTIONS_KEY,
      ACTIVE_PLAYBOOK_KEY: G.ACTIVE_PLAYBOOK_KEY,
      PREMIUM_URL: G.PREMIUM_URL,
      premiumFeatureLabel: G.premiumFeatureLabel,
      premiumDetail: G.premiumDetail,
      notifyPremium: G.notifyPremium,
    });

    // Community Premium upsell modal (Start Battle, etc.).
    if (!ctx.showPremiumModal) ctx.showPremiumModal = ref(false);
    if (!ctx.premiumActiveFeature) ctx.premiumActiveFeature = ref('start_battle');
    ctx.openPremiumModal = function openPremiumModal(feature) {
      ctx.premiumActiveFeature.value = feature || 'start_battle';
      ctx.showPremiumModal.value = true;
    };
    ctx.closePremiumModal = function closePremiumModal() {
      ctx.showPremiumModal.value = false;
    };
    ctx.isPremiumStrategy = function isPremiumStrategy(slug) {
      return G.normStratSlug(slug) === 'adaptive';
    };

    // Shared Risk/War Room metrics window (persisted; default last run).
    if (!ctx.findingsMetricsWindow) {
      ctx.findingsMetricsWindow = ref(
        G.normalizeFindingsMetricsWindow(
          localStorage.getItem(G.FINDINGS_METRICS_WINDOW_KEY),
        ),
      );
    }
    watch(
      () => ctx.findingsMetricsWindow.value,
      (v) => {
        const next = G.normalizeFindingsMetricsWindow(v);
        if (ctx.findingsMetricsWindow.value !== next) {
          ctx.findingsMetricsWindow.value = next;
          return;
        }
        try {
          localStorage.setItem(G.FINDINGS_METRICS_WINDOW_KEY, next);
        } catch (_e) { /* ignore */ }
      },
    );
    G.useConfirm(ctx);
    G.useRowDetail(ctx);
    G.useScope(ctx);
    G.useTests(ctx);
    G.usePlaybooks(ctx);
    G.useRun(ctx);
    G.useRisk(ctx);
    G.useExport(ctx);
    G.useSettings(ctx);

    // Connect Target / auth / loginRunning must exist before useJobs panelOutput reads them.
    G.useConnectTarget(ctx);

    // Prefill pipeline refs that useJobs panelOutput may read before usePipeline runs.
    if (!ctx.pipelineBusy) ctx.pipelineBusy = ref(false);
    if (!ctx.pipelinePromptOutput) ctx.pipelinePromptOutput = ref([]);
    if (!ctx.pipelinePhase) ctx.pipelinePhase = ref('idle');
    if (!ctx.pipelineStrategy) ctx.pipelineStrategy = ref('zero_shot');
    if (!ctx.pipelineActiveStrategyLabel) ctx.pipelineActiveStrategyLabel = ref('');

    G.useJobs(ctx);
    G.useWarRoom(ctx);
    G.useRecon(ctx);
    G.useNotes(ctx);
    G.usePromptTransforms(ctx);
    G.useDiscover(ctx);
    G.useRunStarters(ctx);
    G.usePipeline(ctx);
    G.useAppLifecycle(ctx);

    return ctx;
  };
})(window.Genbounty = window.Genbounty || {});
