/**
 * Domain module: useNotes
 */
(function (G) {
  'use strict';

  G.useNotes = function useNotes(ctx) {
    const {
      armConfirm,
      clearConfirmArmed,
      component,
      computed,
      isConfirmArmed,
      nextTick,
      onMounted,
      reactive,
      ref,
      site,
      watch
    } = ctx;
    const api = G.api;

// --- Notes tab (per site/component) ---
const notesViewMode = ref('notes');
const notesRecord = ref(null);
const notesJsonText = ref('');
const notesDirty = ref(false);
const notesExists = ref(false);
const notesLoading = ref(false);
const notesSaving = ref(false);
const notesMsg = ref('');
const notesError = ref('');
const notesDraftTitle = ref('');
const notesDraftBody = ref('');

function emptyNotesTemplate() {
  return { updated_at: '', notes: [] };
}

function notesSyncJsonFromRecord() {
  if (!notesRecord.value) {
    notesJsonText.value = JSON.stringify(emptyNotesTemplate(), null, 2);
    return;
  }
  notesJsonText.value = JSON.stringify(notesRecord.value, null, 2);
}

function notesApplyJsonToRecord() {
  const parsed = JSON.parse(notesJsonText.value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Notes JSON must be an object');
  }
  if (!Array.isArray(parsed.notes)) parsed.notes = [];
  notesRecord.value = parsed;
}

function notesMarkDirty() {
  notesDirty.value = true;
  notesMsg.value = '';
  notesSyncJsonFromRecord();
}

function notesOnJsonInput() {
  notesDirty.value = true;
  notesMsg.value = '';
}

function setNotesViewMode(mode) {
  const next = mode === 'json' ? 'json' : 'notes';
  if (next === notesViewMode.value) return;
  if (notesViewMode.value === 'json' && next === 'notes') {
    try {
      notesApplyJsonToRecord();
      notesError.value = '';
    } catch (e) {
      notesError.value = String(e.message || e);
      return;
    }
  } else if (notesViewMode.value === 'notes' && next === 'json') {
    notesSyncJsonFromRecord();
  }
  notesViewMode.value = next;
}

async function loadNotes() {
  notesError.value = '';
  notesMsg.value = '';
  if (!site.value || !component.value) {
    notesRecord.value = emptyNotesTemplate();
    notesSyncJsonFromRecord();
    notesExists.value = false;
    notesDirty.value = false;
    return;
  }
  notesLoading.value = true;
  try {
    const res = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/notes`
    );
    notesExists.value = !!res.exists;
    notesRecord.value = res.data || emptyNotesTemplate();
    if (!Array.isArray(notesRecord.value.notes)) notesRecord.value.notes = [];
    notesSyncJsonFromRecord();
    notesDirty.value = false;
  } catch (e) {
    notesError.value = String(e.message || e);
    notesRecord.value = emptyNotesTemplate();
    notesSyncJsonFromRecord();
    notesExists.value = false;
  } finally {
    notesLoading.value = false;
  }
}

async function saveNotes() {
  if (!site.value || !component.value || notesSaving.value) return;
  notesError.value = '';
  notesMsg.value = '';
  notesSaving.value = true;
  try {
    if (notesViewMode.value === 'json') {
      notesApplyJsonToRecord();
    } else {
      notesSyncJsonFromRecord();
    }
    const res = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/notes`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: notesRecord.value || emptyNotesTemplate() }),
      }
    );
    notesExists.value = true;
    notesRecord.value = res.data || notesRecord.value;
    notesSyncJsonFromRecord();
    notesDirty.value = false;
    notesMsg.value = 'Notes saved';
  } catch (e) {
    notesError.value = String(e.message || e);
  } finally {
    notesSaving.value = false;
  }
}

async function addNoteFromComposer() {
  const body = String(notesDraftBody.value || '').trim();
  if (!body || !site.value || !component.value || notesSaving.value) return;
  notesError.value = '';
  notesMsg.value = '';
  notesSaving.value = true;
  try {
    if (notesDirty.value) {
      if (notesViewMode.value === 'json') notesApplyJsonToRecord();
      await api(
        `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/notes`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ data: notesRecord.value || emptyNotesTemplate() }),
        }
      );
    }
    const res = await api(
      `/api/sites/${encodeURIComponent(site.value)}/${encodeURIComponent(component.value)}/notes/append`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: String(notesDraftTitle.value || '').trim(),
          body,
          source: 'manual',
        }),
      }
    );
    notesExists.value = true;
    notesRecord.value = res.data || notesRecord.value;
    notesSyncJsonFromRecord();
    notesDirty.value = false;
    notesDraftTitle.value = '';
    notesDraftBody.value = '';
    notesMsg.value = 'Note added';
    notesViewMode.value = 'notes';
  } catch (e) {
    notesError.value = String(e.message || e);
  } finally {
    notesSaving.value = false;
  }
}

function deleteNoteAt(idx) {
  const key = 'notes-del-' + ((notesRecord.value?.notes || [])[idx]?.id || idx);
  if (!isConfirmArmed(key)) {
    armConfirm(key);
    return;
  }
  clearConfirmArmed(key);
  if (!notesRecord.value || !Array.isArray(notesRecord.value.notes)) return;
  notesRecord.value.notes.splice(idx, 1);
  notesMarkDirty();
}

    const api_out = {
      notesViewMode,
      notesRecord,
      notesJsonText,
      notesDirty,
      notesExists,
      notesLoading,
      notesSaving,
      notesMsg,
      notesError,
      notesDraftTitle,
      notesDraftBody,
      emptyNotesTemplate,
      notesSyncJsonFromRecord,
      notesApplyJsonToRecord,
      notesMarkDirty,
      notesOnJsonInput,
      setNotesViewMode,
      loadNotes,
      saveNotes,
      addNoteFromComposer,
      deleteNoteAt
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
