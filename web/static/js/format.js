/**
 * Display formatters for console lines and slugs.
 */
(function (G) {
  'use strict';

  /** Normalize strategy slugs for compare (few_shot === few-shot). */
  G.normStratSlug = function normStratSlug(s) {
    return String(s || '').trim().toLowerCase().replace(/-/g, '_');
  };

  /** Disk / Run-tab form of a strategy slug (few_shot → few-shot). Keeps __all__ etc. */
  G.hyphenStratSlug = function hyphenStratSlug(s) {
    const raw = String(s || '').trim();
    if (!raw || raw.startsWith('__')) return raw;
    return G.normStratSlug(raw).replace(/_/g, '-');
  };

  /**
   * Find a strategy list entry matching want (underscore/hyphen agnostic).
   * @param {Array<string|{slug:string}>} list
   * @param {string} want
   * @returns {string} disk slug from list, or special (__all__), or ''
   */
  G.matchStrategySlug = function matchStrategySlug(list, want) {
    const w = String(want || '').trim();
    if (!w) return '';
    if (w.startsWith('__')) return w;
    const n = G.normStratSlug(w);
    const hit = (list || []).find((s) => {
      const slug = typeof s === 'string' ? s : s?.slug;
      return G.normStratSlug(slug) === n;
    });
    if (!hit) return '';
    return typeof hit === 'string' ? hit : String(hit.slug || '');
  };

  /** Metrics bar time windows (Risk + War Room). Default: last run.
   *  last_run: Risk = newest report (dropdown + table); period windows merge reports. */
  G.FINDINGS_METRICS_WINDOW_KEY = 'genbounty_findings_metrics_window';
  G.FINDINGS_METRICS_WINDOWS = Object.freeze([
    { id: 'last_run', label: 'Last run', seconds: null },
    { id: '1h', label: 'Last hour', seconds: 3600 },
    { id: '3h', label: 'Last 3 hours', seconds: 10800 },
    { id: 'all', label: 'All', seconds: null },
  ]);
  G.normalizeFindingsMetricsWindow = function normalizeFindingsMetricsWindow(v) {
    const id = String(v || '').trim();
    return G.FINDINGS_METRICS_WINDOWS.some((w) => w.id === id) ? id : 'last_run';
  };

  G.pretty = function pretty(slug) {
    const short = new Set(['eu', 'ai', 'uk', 'us', 'oecd', 'gdpr', 'iso']);
    return (slug || '').replace(/_/g, '-').split('-').filter(Boolean).map((p) =>
      short.has(p.toLowerCase()) ? p.toUpperCase() : p.charAt(0).toUpperCase() + p.slice(1)
    ).join(' ');
  };

  /** User-facing job type labels (internal ids like run_tests stay unchanged). */
  G.prettyJobType = function prettyJobType(type) {
    const aliases = { run_tests: 'attack', security_assess: 'analysis' };
    const key = String(type || 'job');
    return G.pretty((aliases[key] || key).replace(/_/g, '-'));
  };

  G.lineClass = function lineClass(line) {
    const raw = String(line ?? '');
    const t = raw.trimStart();
    const classes = ['console-line'];

    if (!t) {
      classes.push('line-dim');
      return classes.join(' ');
    }

    if (/^\[enhance\]\s+Round\s+\d+\s+worst severity:/i.test(t)) {
      classes.push('line-severity-highlight');
      return classes.join(' ');
    }

    if (/^\[sample\]\s+(Prompt|Response|Transport|Status|Timing)\b/i.test(t)) {
      classes.push('line-sample-meta');
      return classes.join(' ');
    }

    if (t.startsWith('[resilience]') || t.startsWith('[evasion]')) {
      classes.push('line-resilience');
      return classes.join(' ');
    }

    if (t.startsWith('[+]') || t.startsWith('[*]')) {
      classes.push('line-ok');
      return classes.join(' ');
    }

    if (t.startsWith('[!]') || t.startsWith('[-]') || t.startsWith('[error]')) {
      classes.push('line-err');
      return classes.join(' ');
    }

    if (t.startsWith('[enhance]')) {
      classes.push('line-tag-enhance');
      if (/^\[enhance\]\s+===/i.test(t) || /^\[enhance\]\s+End theory/i.test(t)) {
        classes.push('line-section');
      }
      return classes.join(' ');
    }

    if (t.startsWith('[generate]')) {
      classes.push('line-tag-generate');
      if (/^\[generate\]\s+Starting\b/i.test(t)) classes.push('line-section');
      return classes.join(' ');
    }

    if (t.startsWith('[playbook]')) {
      classes.push('line-tag-playbook');
      if (/Phase \d\/5:/i.test(t) || /started\./i.test(t)) classes.push('line-section');
      if (/^\[playbook\]\s+Failed:/i.test(t)) classes.push('line-err');
      if (/^\[playbook\]\s+Complete/i.test(t)) classes.push('line-ok');
      return classes.join(' ');
    }

    if (t.startsWith('[pipeline]')) {
      classes.push('line-tag-pipeline');
      return classes.join(' ');
    }

    if (t.startsWith('[sample]')) {
      classes.push('line-tag-sample');
      return classes.join(' ');
    }

    if (t.startsWith('[risk]')) {
      classes.push('line-tag-risk');
      return classes.join(' ');
    }

    if (t.startsWith('[recon]')) {
      classes.push('line-tag-recon');
      if (/^\[recon\]\s+Starting\b/i.test(t)) classes.push('line-section');
      return classes.join(' ');
    }

    if (t.startsWith('[intel]')) {
      classes.push('line-tag-intel');
      return classes.join(' ');
    }

    if (t.startsWith('[fleet]')) {
      classes.push('line-tag-fleet');
      if (/^\[fleet\]\s+Starting\b/i.test(t)) classes.push('line-section');
      return classes.join(' ');
    }

    if (t.startsWith('[attributes]') || t.startsWith('[transforms]')) {
      classes.push('line-tag-transforms');
      return classes.join(' ');
    }

    if (/^=+.*=+$/.test(t)) {
      classes.push('line-section');
      return classes.join(' ');
    }

    if (raw.startsWith('  ')) {
      classes.push('line-info');
      return classes.join(' ');
    }

    return classes.join(' ');
  };

  G.useFormat = function useFormat(ctx) {
    Object.assign(ctx, {
      pretty: G.pretty,
      prettyJobType: G.prettyJobType,
      lineClass: G.lineClass,
    });
    return {
      pretty: G.pretty,
      prettyJobType: G.prettyJobType,
      lineClass: G.lineClass,
    };
  };
})(window.Genbounty = window.Genbounty || {});
