/**
 * localStorage helpers for per-site/component tab selections.
 */
(function (G) {
  'use strict';

  G.RUN_TAB_SELECTIONS_KEY = 'genbounty_run_tab_selections';
  G.TM_TAB_SELECTIONS_KEY = 'genbounty_test_mgmt_selections';
  G.ACTIVE_PLAYBOOK_KEY = 'genbounty_playbook';
  G.ACTIVE_VIEW_KEY = 'genbounty_active_view';
  G.DISCOVER_TRANSPORT_KEY = 'genbounty_discover_transport';

  /** Connect Target → Configure Component connection type.
   *  Empty/new components default to browser UI; loading a saved config syncs
   *  from submission.transport (see syncDiscoverTransportFromSubmission). */
  G.preferredDiscoverTransport = function preferredDiscoverTransport() {
    try {
      const v = (localStorage.getItem(G.DISCOVER_TRANSPORT_KEY) || '').trim();
      if (v === 'api' || v === 'browser') return v;
    } catch {
      /* quota / private browsing */
    }
    return 'browser';
  };

  G.persistDiscoverTransport = function persistDiscoverTransport(value) {
    const next = value === 'api' ? 'api' : 'browser';
    try {
      localStorage.setItem(G.DISCOVER_TRANSPORT_KEY, next);
    } catch {
      /* quota / private browsing */
    }
    return next;
  };

  G.tabSelectionsStorageKey = function tabSelectionsStorageKey(prefix, siteVal, componentVal) {
    return `${prefix}:${siteVal || ''}:${componentVal || ''}`;
  };

  G.readTabSelections = function readTabSelections(prefix, siteVal, componentVal) {
    if (!siteVal || !componentVal) return null;
    try {
      const raw = localStorage.getItem(G.tabSelectionsStorageKey(prefix, siteVal, componentVal));
      if (!raw) return null;
      const data = JSON.parse(raw);
      return data && typeof data === 'object' ? data : null;
    } catch {
      return null;
    }
  };

  G.writeTabSelections = function writeTabSelections(prefix, siteVal, componentVal, data) {
    if (!siteVal || !componentVal) return;
    try {
      localStorage.setItem(
        G.tabSelectionsStorageKey(prefix, siteVal, componentVal),
        JSON.stringify(data),
      );
    } catch {
      /* quota / private browsing */
    }
  };

  G.useStorage = function useStorage(ctx) {
    Object.assign(ctx, {
      RUN_TAB_SELECTIONS_KEY: G.RUN_TAB_SELECTIONS_KEY,
      TM_TAB_SELECTIONS_KEY: G.TM_TAB_SELECTIONS_KEY,
      ACTIVE_PLAYBOOK_KEY: G.ACTIVE_PLAYBOOK_KEY,
      ACTIVE_VIEW_KEY: G.ACTIVE_VIEW_KEY,
      DISCOVER_TRANSPORT_KEY: G.DISCOVER_TRANSPORT_KEY,
      preferredDiscoverTransport: G.preferredDiscoverTransport,
      persistDiscoverTransport: G.persistDiscoverTransport,
      readTabSelections: G.readTabSelections,
      writeTabSelections: G.writeTabSelections,
    });
    return {
      readTabSelections: G.readTabSelections,
      writeTabSelections: G.writeTabSelections,
      preferredDiscoverTransport: G.preferredDiscoverTransport,
      persistDiscoverTransport: G.persistDiscoverTransport,
    };
  };
})(window.Genbounty = window.Genbounty || {});
