/**
 * Domain module: useScope
 */
(function (G) {
  'use strict';

  G.useScope = function useScope(ctx) {
    const {
      computed,
      nextTick,
      onMounted,
      reactive,
      ref,
      watch
    } = ctx;
    const api = G.api;

const site = ref('');
const component = ref('');
const sites = ref([]);
const components = ref([]);
const tab = ref('discover');
const settingsTab = ref('llm');
const jobsOpen = ref(false);
const jobs = ref([]);
const showRunTroubleshoot = ref(false);

const SIDEBAR_WIDTH_KEY = 'genbounty_sidebar_width';
const SIDEBAR_WIDTH_MIN = 168;
const SIDEBAR_WIDTH_MAX = 480;
const SIDEBAR_WIDTH_DEFAULT = 189;

function _clampSidebarWidth(px) {
  const n = Math.round(Number(px) || SIDEBAR_WIDTH_DEFAULT);
  return Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, n));
}

function _readStoredSidebarWidth() {
  try {
    const raw = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    if (raw == null || raw === '') return SIDEBAR_WIDTH_DEFAULT;
    return _clampSidebarWidth(raw);
  } catch (_) {
    return SIDEBAR_WIDTH_DEFAULT;
  }
}

const sidebarWidth = ref(_readStoredSidebarWidth());
const sidebarWidthPx = computed(() => `${sidebarWidth.value}px`);

function _persistSidebarWidth(px) {
  const next = _clampSidebarWidth(px);
  sidebarWidth.value = next;
  try {
    localStorage.setItem(SIDEBAR_WIDTH_KEY, String(next));
  } catch (_) { /* private browsing */ }
  return next;
}

function startSidebarResize(ev) {
  if (typeof window !== 'undefined' && window.matchMedia
      && window.matchMedia('(max-width: 700px)').matches) {
    return;
  }
  const startX = ev.clientX;
  const startW = sidebarWidth.value;
  const pointerId = ev.pointerId;
  const handle = ev.currentTarget;
  document.body.classList.add('sidebar-resizing');
  try {
    handle.setPointerCapture(pointerId);
  } catch (_) { /* ignore */ }

  function onMove(e) {
    _persistSidebarWidth(startW + (e.clientX - startX));
  }
  function onUp() {
    document.body.classList.remove('sidebar-resizing');
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
  }
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onUp);
}

function onSidebarResizeKeydown(ev) {
  const step = ev.shiftKey ? 24 : 12;
  if (ev.key === 'ArrowLeft') {
    ev.preventDefault();
    _persistSidebarWidth(sidebarWidth.value - step);
  } else if (ev.key === 'ArrowRight') {
    ev.preventDefault();
    _persistSidebarWidth(sidebarWidth.value + step);
  } else if (ev.key === 'Home') {
    ev.preventDefault();
    _persistSidebarWidth(SIDEBAR_WIDTH_DEFAULT);
  }
}

const OUTPUT_WIDTH_KEY = 'genbounty_output_panel_width';
const OUTPUT_WIDTH_MIN = 220;
const OUTPUT_WIDTH_MAX = 640;
const OUTPUT_WIDTH_DEFAULT = 289;

function _clampOutputPanelWidth(px) {
  const n = Math.round(Number(px) || OUTPUT_WIDTH_DEFAULT);
  return Math.min(OUTPUT_WIDTH_MAX, Math.max(OUTPUT_WIDTH_MIN, n));
}

function _readStoredOutputPanelWidth() {
  try {
    const raw = localStorage.getItem(OUTPUT_WIDTH_KEY);
    if (raw == null || raw === '') return OUTPUT_WIDTH_DEFAULT;
    return _clampOutputPanelWidth(raw);
  } catch (_) {
    return OUTPUT_WIDTH_DEFAULT;
  }
}

const outputPanelWidth = ref(_readStoredOutputPanelWidth());
const outputPanelWidthPx = computed(() => `${outputPanelWidth.value}px`);

function _persistOutputPanelWidth(px) {
  const next = _clampOutputPanelWidth(px);
  outputPanelWidth.value = next;
  try {
    localStorage.setItem(OUTPUT_WIDTH_KEY, String(next));
  } catch (_) { /* private browsing */ }
  return next;
}

function startOutputPanelResize(ev) {
  if (typeof window !== 'undefined' && window.matchMedia
      && window.matchMedia('(max-width: 1120px)').matches) {
    return;
  }
  const startX = ev.clientX;
  const startW = outputPanelWidth.value;
  const pointerId = ev.pointerId;
  const handle = ev.currentTarget;
  document.body.classList.add('output-resizing');
  try {
    handle.setPointerCapture(pointerId);
  } catch (_) { /* ignore */ }

  function onMove(e) {
    // Handle is on the left edge: drag left → wider, drag right → narrower.
    _persistOutputPanelWidth(startW + (startX - e.clientX));
  }
  function onUp() {
    document.body.classList.remove('output-resizing');
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
  }
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onUp);
}

function onOutputPanelResizeKeydown(ev) {
  const step = ev.shiftKey ? 24 : 12;
  if (ev.key === 'ArrowLeft') {
    ev.preventDefault();
    _persistOutputPanelWidth(outputPanelWidth.value + step);
  } else if (ev.key === 'ArrowRight') {
    ev.preventDefault();
    _persistOutputPanelWidth(outputPanelWidth.value - step);
  } else if (ev.key === 'Home') {
    ev.preventDefault();
    _persistOutputPanelWidth(OUTPUT_WIDTH_DEFAULT);
  }
}

/** Grouped Ops sidebar sections (Firing Range is Operations tab `manual`). */
const sidebarGroups = [
  {
    id: 'connect',
    label: 'Connect Target',
    tabs: [{ id: 'discover', label: 'Connect Target' }],
  },
  {
    id: 'recon',
    label: 'Recon',
    tabs: [
      { id: 'recon', label: 'Recon' },
      { id: 'intel', label: 'Intel' },
    ],
  },
  {
    id: 'operations',
    label: 'Operations',
    tabs: [
      { id: 'war-room', label: 'War Room' },
      { id: 'playbooks', label: 'Missions' },
      { id: 'generate', label: 'Forge' },
      { id: 'tests', label: 'Armory' },
      { id: 'run', label: 'Attack' },
      { id: 'risk', label: 'Analysis' },
      { id: 'manual', label: 'Firing Range' },
    ],
  },
  {
    id: 'report',
    label: 'Report',
    tabs: [
      { id: 'export', label: 'Report' },
      { id: 'notes', label: 'Notes' },
    ],
  },
  {
    id: 'artifacts',
    label: 'Artifacts',
    tabs: [{ id: 'payloads', label: 'Multimodal' }],
  },
  {
    id: 'settings',
    label: 'Settings',
    tabs: [{ id: 'settings', label: 'Settings' }],
  },
];
const tabs = sidebarGroups.flatMap((g) => g.tabs);
const KNOWN_TAB_IDS = new Set(tabs.map((t) => t.id));
const KNOWN_SETTINGS_TABS = new Set([
  'llm', 'pipeline', 'component', 'browser', 'defaults', 'cache', 'theory',
]);
const ACTIVE_VIEW_KEY = G.ACTIVE_VIEW_KEY || 'genbounty_active_view';

function readActiveView() {
  try {
    const raw = localStorage.getItem(ACTIVE_VIEW_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    return data && typeof data === 'object' ? data : null;
  } catch {
    return null;
  }
}

function writeActiveView() {
  try {
    localStorage.setItem(ACTIVE_VIEW_KEY, JSON.stringify({
      tab: tab.value,
      settingsTab: settingsTab.value,
    }));
  } catch {
    /* quota / private browsing */
  }
}

(function restoreActiveView() {
  const saved = readActiveView();
  if (!saved) return;
  const savedTab = String(saved.tab || '').trim();
  if (savedTab && KNOWN_TAB_IDS.has(savedTab)) {
    tab.value = savedTab;
  }
  const savedSettings = String(saved.settingsTab || '').trim();
  if (savedSettings && KNOWN_SETTINGS_TABS.has(savedSettings)) {
    settingsTab.value = savedSettings;
  }
})();

/** Ops menu + independent group panels (all groups open by default). */
const sidebarMenuOpen = ref(true);
const sidebarOpenGroupIds = ref(sidebarGroups.map((g) => g.id));
const activeSidebarGroupId = computed(() => {
  const t = tab.value;
  const group = sidebarGroups.find((g) => (g.tabs || []).some((x) => x.id === t));
  return group ? group.id : '';
});

// Keep the restored tab's sidebar group expanded.
(() => {
  const group = sidebarGroups.find((g) => (g.tabs || []).some((x) => x.id === tab.value));
  if (group && !sidebarOpenGroupIds.value.includes(group.id)) {
    sidebarOpenGroupIds.value = [...sidebarOpenGroupIds.value, group.id];
  }
})();

watch([tab, settingsTab], () => {
  writeActiveView();
});

function isSidebarGroupOpen(g) {
  return !!(g && g.id && sidebarOpenGroupIds.value.includes(g.id));
}
function toggleSidebarMenu() {
  sidebarMenuOpen.value = !sidebarMenuOpen.value;
}
/** Open Firing Range in the main view (Operations tab). */
function openManualCommandView() {
  selectSidebarTab('manual');
}
function toggleSidebarGroup(g) {
  if (!g || !g.id) return;
  sidebarMenuOpen.value = true;
  if ((g.tabs || []).length === 1) {
    tab.value = g.tabs[0].id;
  }
  const open = sidebarOpenGroupIds.value.includes(g.id);
  sidebarOpenGroupIds.value = open
    ? sidebarOpenGroupIds.value.filter((id) => id !== g.id)
    : [...sidebarOpenGroupIds.value, g.id];
}
function selectSidebarTab(id) {
  const next = String(id || '').trim();
  if (!next) return;
  tab.value = next;
  sidebarMenuOpen.value = true;
  const group = sidebarGroups.find((g) => (g.tabs || []).some((x) => x.id === next));
  if (group && !sidebarOpenGroupIds.value.includes(group.id)) {
    sidebarOpenGroupIds.value = [...sidebarOpenGroupIds.value, group.id];
  }
}

const PAYLOAD_GENERATORS = [
  'text', 'csv', 'pdf', 'pdf_visible', 'pdf_hidden', 'pdf_metadata',
  'image', 'image_text', 'qr', 'audio_synthetic', 'audio_tts',
];

const allStrategies = ref([]);
const allPlaybooks = ref([]);
const activePlaybookId = ref('');
const activeCategoryL1 = ref('');
// Shared mutable flag - keep on ctx only (Object.assign would copy a boolean by value).
ctx._skipActivePlaybookSync = false;
const runStrategies = ref([]);
const runTestFiles = ref([]);
const logs = reactive({ runs: [], attacks: [], reports: [] });

    const api_out = {
      site,
      component,
      sites,
      components,
      tab,
      settingsTab,
      jobsOpen,
      jobs,
      showRunTroubleshoot,
      sidebarGroups,
      tabs,
      sidebarMenuOpen,
      sidebarOpenGroupIds,
      sidebarWidth,
      sidebarWidthPx,
      startSidebarResize,
      onSidebarResizeKeydown,
      outputPanelWidth,
      outputPanelWidthPx,
      startOutputPanelResize,
      onOutputPanelResizeKeydown,
      activeSidebarGroupId,
      isSidebarGroupOpen,
      toggleSidebarMenu,
      openManualCommandView,
      toggleSidebarGroup,
      selectSidebarTab,
      PAYLOAD_GENERATORS,
      allStrategies,
      allPlaybooks,
      activePlaybookId,
      activeCategoryL1,
      runStrategies,
      runTestFiles,
      logs
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
