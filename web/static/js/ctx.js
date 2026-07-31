/**
 * Shared Vue app context: Vue APIs + core refs used across tab modules.
 */
(function (G) {
  'use strict';

  /**
   * @param {{ ref: Function, reactive: Function, computed: Function, watch: Function, nextTick: Function, onMounted: Function }} Vue
   */
  G.createCtx = function createCtx(Vue) {
    const { ref, reactive, computed, watch, nextTick, onMounted } = Vue;
    const ctx = {
      ref,
      reactive,
      computed,
      watch,
      nextTick,
      onMounted,
      api: G.api,
      isAbortError: G.isAbortError,
      site: ref(''),
      component: ref(''),
      sites: ref([]),
      components: ref([]),
      tab: ref('discover'),
      settingsTab: ref('llm'),
      jobsOpen: ref(false),
      jobs: ref([]),
      showRunTroubleshoot: ref(false),
    };
    return ctx;
  };
})(window.Genbounty = window.Genbounty || {});
