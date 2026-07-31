/**
 * Community edition Premium CTA helpers.
 * Upsell: https://genbounty.com/llm-hunter
 */
(function (G) {
  'use strict';

  G.PREMIUM_URL = 'https://genbounty.com/llm-hunter';

  G.PREMIUM_FEATURES = Object.freeze({
    start_battle: 'Start Battle (Run pipeline)',
    adaptive: 'Adaptive strategy',
    multimodal_generate: 'Manual multimodal generation',
    intel: 'Intel',
    open_hunt: 'Open Hunt',
  });

  G.premiumFeatureLabel = function premiumFeatureLabel(feature) {
    return G.PREMIUM_FEATURES[feature] || String(feature || 'This feature');
  };

  G.premiumDetail = function premiumDetail(feature) {
    const label = G.premiumFeatureLabel(feature);
    const key = String(feature || '').trim();
    if (key === 'start_battle') {
      return (
        label
        + ' is available in Genbounty LLM Hunter Premium. '
        + 'In Community, use Run and Enhance (Auto-run) on the Attack tab. '
        + 'Upgrade at genbounty.com/llm-hunter'
      );
    }
    return (
      label
      + ' is available in Genbounty LLM Hunter Premium. '
      + 'Upgrade at genbounty.com/llm-hunter'
    );
  };

  /** Show a brief console/alert-style notice when a gated action is attempted. */
  G.notifyPremium = function notifyPremium(feature) {
    const msg = G.premiumDetail(feature);
    try {
      if (typeof window !== 'undefined' && window.alert) {
        window.alert(msg + '\n\n' + G.PREMIUM_URL);
        return;
      }
    } catch (_e) { /* ignore */ }
    console.warn('[premium]', msg, G.PREMIUM_URL);
  };
})(window.Genbounty = window.Genbounty || {});
