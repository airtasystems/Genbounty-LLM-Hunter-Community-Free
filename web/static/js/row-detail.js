/**
 * Shared row-detail modal: expand any table row into a consistent read-only dialog.
 */
(function (G) {
  'use strict';

  function _str(v) {
    if (v == null) return '';
    if (typeof v === 'string') return v;
    if (typeof v === 'number' || typeof v === 'boolean') return String(v);
    try {
      return JSON.stringify(v, null, 2);
    } catch (_e) {
      return String(v);
    }
  }

  function _field(label, value, opts) {
    const o = opts || {};
    const raw = value == null || value === '' ? '' : _str(value);
    return {
      label: String(label || ''),
      value: raw,
      mono: o.mono !== false,
    };
  }

  G.useRowDetail = function useRowDetail(ctx) {
    const { ref } = ctx;

    const showRowDetailModal = ref(false);
    const rowDetailTitle = ref('');
    const rowDetailSubtitle = ref('');
    const rowDetailFields = ref([]);

    function closeRowDetailModal() {
      showRowDetailModal.value = false;
      rowDetailTitle.value = '';
      rowDetailSubtitle.value = '';
      rowDetailFields.value = [];
    }

    function _onRowDetailKeydown(ev) {
      if (!showRowDetailModal.value) return;
      if (ev.key === 'Escape') {
        ev.preventDefault();
        closeRowDetailModal();
      }
    }

    if (typeof window !== 'undefined') {
      window.addEventListener('keydown', _onRowDetailKeydown);
    }

    /**
     * @param {{ title?: string, subtitle?: string, fields?: Array<{label:string,value?:*,mono?:boolean}> }} opts
     */
    function openRowDetailModal(opts) {
      const o = opts || {};
      const fields = Array.isArray(o.fields) ? o.fields : [];
      rowDetailTitle.value = String(o.title || 'Row detail').trim() || 'Row detail';
      rowDetailSubtitle.value = String(o.subtitle || '').trim();
      rowDetailFields.value = fields
        .filter((f) => f && f.label)
        .map((f) => _field(f.label, f.value, { mono: f.mono }));
      showRowDetailModal.value = true;
    }

    function openRunResultRowDetail(r) {
      const row = r || {};
      const fields = [
        _field('# / Turn', row.isMultiTurn ? (row.turnFraction || row.label) : row.label),
        _field('Prompt', row.input),
        _field('Response', row.response),
      ];
      if (row.submissionOutcome && row.submissionOutcome !== 'executed') {
        fields.splice(1, 0, _field(
          'Outcome',
          typeof ctx.runOutcomeLabel === 'function'
            ? ctx.runOutcomeLabel(row.submissionOutcome)
            : row.submissionOutcome,
        ));
      }
      if (Array.isArray(row.rejectionSignals) && row.rejectionSignals.length) {
        fields.push(_field('Rejection signals', row.rejectionSignals.join(', ')));
      }
      if (row.batchLabel) fields.push(_field('Batch', row.batchLabel));
      openRowDetailModal({
        title: row.isMultiTurn
          ? `Run result · ${row.turnFraction || row.label || ''}`
          : `Run result · ${row.label || ''}`,
        fields,
      });
    }

    function openRunArtifactRowDetail(row) {
      const r = row || {};
      openRowDetailModal({
        title: `Artifact · ${r.id || 'prompt'}`,
        fields: [
          _field('Prompt id', r.id),
          _field('Status', r.status),
          _field('Path', r.path),
          _field('Generator', r.generator),
        ],
      });
    }

    function openRiskRowDetail(r) {
      const row = r || {};
      const fields = [
        _field('#', row.label),
        _field('Risk', row.riskLevel),
        _field('Category', row.category || row.id),
        _field('Confidence', row.confidence),
        _field('Evidence strength', row.evidenceStrength != null ? row.evidenceStrength : ''),
        _field(
          'Evidence signals',
          Array.isArray(row.evidenceSignals) ? row.evidenceSignals.join(', ') : '',
        ),
        _field('Prompt', row.prompt),
        _field('Response', row.response),
        _field('Reasoning', row.reasoning),
      ];
      openRowDetailModal({
        title: `Risk finding · ${row.label || row.id || ''}`,
        subtitle: [row.riskLevel, row.category || row.id].filter(Boolean).join(' · '),
        fields,
      });
    }

    function openCapEntryRowDetail(entry) {
      const e = entry || {};
      const source = typeof ctx.formatCapSource === 'function'
        ? ctx.formatCapSource(e.source_report)
        : (e.source_report || '');
      openRowDetailModal({
        title: `Intel · ${e.kind || 'entry'}`,
        fields: [
          _field('Kind', e.kind),
          _field('Value', e.value),
          _field('Context', e.context),
          _field('Risk', e.risk_level),
          _field('Source', source),
          _field('Last seen', e.last_seen_at),
        ],
      });
    }

    function openPayloadRowDetail(f) {
      const file = f || {};
      openRowDetailModal({
        title: 'Payload artifact',
        fields: [
          _field('File', file.relative_path),
          _field('Size (bytes)', file.size),
        ],
      });
    }

    function openJobRowDetail(j) {
      const job = j || {};
      const typeLabel = typeof G.prettyJobType === 'function'
        ? G.prettyJobType(job.type)
        : job.type;
      openRowDetailModal({
        title: `Job · ${job.id || ''}`,
        fields: [
          _field('Id', job.id),
          _field('Type', typeLabel),
          _field('Site', job.site),
          _field('Component', job.component),
          _field('Status', job.status),
          _field('Params', job.params != null ? job.params : ''),
          _field('Error', job.error || job.message || ''),
        ],
      });
    }

    function openTestPromptRowDetail(p) {
      const prompt = p || {};
      const kind = Array.isArray(prompt.prompts) && prompt.prompts.length
        ? 'multi_turn'
        : (Array.isArray(prompt.examples) && prompt.examples.length
          ? 'few_shot'
          : (prompt.payload || (prompt.vector_type && prompt.vector_type !== 'text_direct')
            ? 'multimodal'
            : 'text'));
      const fields = [
        _field('Id', prompt.id),
        _field('Description', prompt.description),
        _field('Kind', kind),
      ];
      if (kind === 'multi_turn') {
        (prompt.prompts || []).forEach((t, i) => {
          fields.push(_field(`Turn ${i + 1}`, t));
        });
      } else if (kind === 'few_shot') {
        (prompt.examples || []).forEach((ex, i) => {
          fields.push(_field(`Example ${i + 1} prompt`, ex?.prompt));
          fields.push(_field(`Example ${i + 1} expected`, ex?.expected_behavior));
        });
        if (prompt.prompt) fields.push(_field('Final prompt', prompt.prompt));
      } else if (kind === 'multimodal') {
        fields.push(_field('Vector type', prompt.vector_type));
        fields.push(_field('Payload', prompt.payload));
        fields.push(_field('Prompt', prompt.prompt));
      } else {
        fields.push(_field('Prompt', prompt.prompt));
      }
      openRowDetailModal({
        title: `Probe · ${prompt.id || 'prompt'}`,
        fields,
      });
    }

    const api_out = {
      showRowDetailModal,
      rowDetailTitle,
      rowDetailSubtitle,
      rowDetailFields,
      openRowDetailModal,
      closeRowDetailModal,
      openRunResultRowDetail,
      openRunArtifactRowDetail,
      openRiskRowDetail,
      openCapEntryRowDetail,
      openPayloadRowDetail,
      openJobRowDetail,
      openTestPromptRowDetail,
    };
    Object.assign(ctx, api_out);
    return api_out;
  };
})(window.Genbounty = window.Genbounty || {});
