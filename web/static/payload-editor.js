/**
 * DVAIA-parity payload generator editor (Vue 3 component).
 * Register via registerPayloadEditor(app) before mount.
 */
(function (global) {
  'use strict';

  const POSITION_OPTIONS = [
    'top_left', 'top_center', 'top_right',
    'center_left', 'center', 'center_right',
    'bottom_left', 'bottom_center', 'bottom_right',
  ];

  const GENERATOR_TO_ASSET = {
    text: 'text', csv: 'csv', pdf: 'pdf', pdf_visible: 'pdf_visible',
    pdf_hidden: 'pdf_hidden', pdf_metadata: 'pdf_metadata',
    image: 'image', image_text: 'image', qr: 'qr',
    audio_synthetic: 'audio_synthetic', audio_tts: 'audio_tts',
  };

  const ASSET_TO_GENERATOR = {
    text: 'text', csv: 'csv', pdf: 'pdf', pdf_visible: 'pdf_visible',
    pdf_hidden: 'pdf_hidden', pdf_metadata: 'pdf_metadata',
    image: 'image_text', qr: 'qr', audio_synthetic: 'audio_synthetic', audio_tts: 'audio_tts',
  };

  function parseColor(str) {
    if (!str || typeof str !== 'string') return { r: 0, g: 0, b: 0 };
    str = str.trim();
    if (str.startsWith('#')) {
      let hex = str.slice(1);
      if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
      if (hex.length === 6) {
        const n = parseInt(hex, 16);
        return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
      }
    }
    const names = { black: '#000', white: '#fff', red: '#f00', gray: '#808080', grey: '#808080' };
    if (names[str.toLowerCase()]) return parseColor(names[str.toLowerCase()]);
    return { r: 0, g: 0, b: 0 };
  }

  function colorToHex(str) {
    if (!str || !str.trim()) return '#000000';
    const c = parseColor(str.trim());
    return '#' + [c.r, c.g, c.b].map(x => ('0' + Math.max(0, Math.min(255, x)).toString(16)).slice(-2)).join('');
  }

  function positionToXY(position, width, height, blockWidth, blockHeight, padding) {
    padding = padding || 20;
    let pos = (position || 'top_left').toLowerCase().replace(/ /g, '_');
    let posV = 'top', posH = 'left';
    if (pos.indexOf('_') >= 0) {
      const parts = pos.split('_');
      if (['top', 'center', 'bottom'].indexOf(parts[0]) >= 0) posV = parts[0];
      if (parts.length > 1 && ['left', 'center', 'right'].indexOf(parts[1]) >= 0) posH = parts[1];
    }
    let startY = padding;
    if (posV === 'bottom') startY = Math.max(padding, height - padding - blockHeight);
    else if (posV === 'center') startY = Math.max(0, (height - blockHeight) / 2);
    let startX = padding;
    if (posH === 'right') startX = Math.max(padding, width - padding - blockWidth);
    else if (posH === 'center') startX = Math.max(0, (width - blockWidth) / 2);
    return { x: Math.round(startX), y: Math.round(startY) };
  }

  function flattenDefaults(schema) {
    const out = {};
    function walk(fields) {
      (fields || []).forEach(f => {
        if (f.type === 'tab_group') {
          (f.tabs || []).forEach(t => walk(t.fields));
        } else if (f.name && f.default !== undefined) {
          out[f.name] = f.default;
        }
      });
    }
    walk(schema?.fields || []);
    return out;
  }

  function fieldVisible(f, form) {
    const sw = f.show_when;
    if (!sw) return true;
    return Object.entries(sw).every(([k, v]) => form[k] === v);
  }

  function argsToForm(assetType, args, schema) {
    const form = flattenDefaults(schema);
    form.asset_type = assetType;
    if (!args || typeof args !== 'object') return form;
    const gen = ASSET_TO_GENERATOR[assetType] || assetType;
    if (gen === 'pdf_visible') form.content = args.visible_text || args.content || form.content;
    else if (gen === 'pdf_hidden') {
      form.visible_content = args.visible_text || args.visible_content || '';
      form.hidden_content = args.hidden_text || args.hidden_content || '';
    } else if (gen === 'pdf_metadata') {
      form.body_content = args.body || args.body_content || '';
      form.subject = args.subject || '';
      form.author = args.author || '';
      if (args.source_pdf) form.source_pdf = String(args.source_pdf).split(/[/\\]/).pop();
    } else if (gen === 'pdf') {
      if (args.hidden_content || args.hidden_text) form.pdf_hidden_content = args.hidden_content || args.hidden_text;
      if (args.source_pdf) form.source_pdf = String(args.source_pdf).split(/[/\\]/).pop();
      const lines = args.text_lines;
      if (Array.isArray(lines)) {
        lines.slice(0, 3).forEach((line, i) => {
          const n = i + 1;
          if (line && typeof line === 'object') {
            form['pdf_line' + n + '_text'] = line.text || '';
            form['pdf_line' + n + '_font_size'] = line.font_size || 12;
            form['pdf_line' + n + '_color'] = line.color || '#000000';
            const al = line.alpha != null ? line.alpha : 255;
            form['pdf_line' + n + '_alpha'] = al <= 255 ? Math.round(al * 100 / 255) : al;
            form['pdf_line' + n + '_position'] = line.position || 'top_left';
          }
        });
      }
    } else if (gen === 'image_text' || assetType === 'image') {
      if (args.source_image) form.source_image = String(args.source_image).split(/[/\\]/).pop();
      form.width = args.width ?? form.width;
      form.height = args.height ?? form.height;
      if (args.background_color) form.background_color = args.background_color;
      const lines = args.text_lines;
      if (Array.isArray(lines) && lines.length) {
        lines.slice(0, 3).forEach((line, i) => {
          const n = i + 1;
          form['line' + n + '_text'] = line.text || '';
          form['line' + n + '_font_size'] = line.font_size || 14;
          form['line' + n + '_color'] = line.color || '#000000';
          const al = line.alpha != null ? line.alpha : 255;
          form['line' + n + '_alpha'] = al <= 255 ? Math.round(al * 100 / 255) : al;
          form['line' + n + '_position'] = line.position || 'top_left';
          form['line' + n + '_low_contrast'] = !!line.low_contrast;
          form['line' + n + '_text_rotation'] = line.text_rotation || 0;
          form['line' + n + '_blur_radius'] = line.blur_radius || 0;
          form['line' + n + '_noise_level'] = line.noise_level || 0;
        });
      } else {
        form.line1_text = args.text || args.content || form.line1_text;
        form.line1_low_contrast = !!args.low_contrast;
        form.line1_text_rotation = args.text_rotation || args.rotation || 0;
        if (args.text_color) form.line1_color = args.text_color;
      }
    } else if (gen === 'text') form.content = args.content || args.hidden_text || form.content;
    else if (gen === 'csv') {
      if (args.content) { form.csv_mode = 'custom'; form.csv_content = args.content; }
    } else if (gen === 'qr') form.payload = args.data || args.payload || form.payload;
    else if (gen === 'audio_tts') {
      ['text', 'overlay_text', 'overlay_level', 'noise_level', 'background_tone_hz',
        'background_tone_level', 'pitch_semitones', 'speed_factor', 'echo_delay_ms',
        'echo_decay', 'distortion', 'gain_db', 'low_pass_hz', 'high_pass_hz', 'lang'].forEach(k => {
        if (args[k] != null && args[k] !== '') form[k] = args[k];
      });
    } else if (gen === 'audio_synthetic') {
      form.frequency = args.frequency ?? 440;
      form.duration_sec = args.duration_sec || args.duration_s || 1;
    }
    Object.keys(args).forEach(k => {
      if (k in form || k.startsWith('line') || k.startsWith('pdf_line')) form[k] = args[k];
    });
    return form;
  }

  function formToArgs(assetType, form) {
    const gen = ASSET_TO_GENERATOR[assetType] || assetType;
    const args = {};
    if (gen === 'text') args.content = form.content || '';
    else if (gen === 'csv') {
      if (form.csv_mode === 'custom') args.content = form.csv_content || '';
      else {
        args.columns = form.csv_columns;
        args.num_rows = form.csv_num_rows;
        args.use_faker = form.csv_use_faker;
      }
    } else if (gen === 'pdf_visible') args.visible_text = form.content || '';
    else if (gen === 'pdf_hidden') {
      args.visible_text = form.visible_content || '';
      args.hidden_text = form.hidden_content || '';
    } else if (gen === 'pdf_metadata') {
      args.body = form.body_content || '';
      args.subject = form.subject || '';
      args.author = form.author || '';
      if (form.source_pdf) args.source_pdf = form.source_pdf;
    } else if (gen === 'pdf') {
      const lines = [];
      for (let i = 1; i <= 3; i++) {
        const t = (form['pdf_line' + i + '_text'] || '').trim();
        if (t) lines.push({
          text: t,
          font_size: form['pdf_line' + i + '_font_size'] || 12,
          color: form['pdf_line' + i + '_color'],
          alpha: Math.round(Number(form['pdf_line' + i + '_alpha'] ?? 100) * 2.55),
          position: form['pdf_line' + i + '_position'] || 'top_left',
        });
      }
      if (lines.length) args.text_lines = lines;
      const hidden = form.pdf_hidden_content || form.hidden_content;
      if (hidden) args.hidden_content = hidden;
      if (form.source_pdf) args.source_pdf = form.source_pdf;
    } else if (gen === 'image_text') {
      const lines = [];
      for (let i = 1; i <= 3; i++) {
        const t = (form['line' + i + '_text'] || '').trim();
        if (t) lines.push({
          text: t,
          font_size: form['line' + i + '_font_size'] || 14,
          color: form['line' + i + '_color'],
          alpha: Math.round(Number(form['line' + i + '_alpha'] ?? 100) * 2.55),
          position: form['line' + i + '_position'] || 'top_left',
          low_contrast: !!form['line' + i + '_low_contrast'],
          text_rotation: Number(form['line' + i + '_text_rotation'] || 0),
          blur_radius: Number(form['line' + i + '_blur_radius'] || 0),
          noise_level: Number(form['line' + i + '_noise_level'] || 0),
        });
      }
      if (lines.length) args.text_lines = lines;
      else if (form.line1_text) {
        args.text = form.line1_text;
        args.low_contrast = !!form.line1_low_contrast;
      }
      args.width = form.width;
      args.height = form.height;
      if (form.background_color) args.background_color = form.background_color;
      if (form.source_image) args.source_image = form.source_image;
    } else if (gen === 'qr') {
      args.data = form.payload || '';
      if (form.composite_width != null && form.composite_width !== '') args.composite_width = form.composite_width;
      if (form.composite_height != null && form.composite_height !== '') args.composite_height = form.composite_height;
    } else if (gen === 'audio_synthetic') {
      args.frequency = form.frequency;
      args.duration_sec = form.duration_sec;
    } else if (gen === 'audio_tts') {
      ['text', 'overlay_text', 'overlay_level', 'noise_level', 'background_tone_hz',
        'background_tone_level', 'pitch_semitones', 'speed_factor', 'echo_delay_ms',
        'echo_decay', 'distortion', 'gain_db', 'low_pass_hz', 'high_pass_hz', 'lang'].forEach(k => {
        if (form[k] != null && form[k] !== '') args[k] = form[k];
      });
    }
    if (form.filename) args.filename = form.filename;
    return { generator: gen, args };
  }

  function buildGenerateBody(assetType, form, fileBlobs) {
    const body = { asset_type: assetType };
    Object.assign(body, form);
    delete body.asset_type;
    body.asset_type = assetType;
    const hasFiles = fileBlobs && (fileBlobs.file || fileBlobs.payload_pdf_file || fileBlobs.payload_pdf_metadata_file);
    if (!hasFiles) return { json: body };
    const fd = new FormData();
    fd.append('asset_type', assetType);
    Object.entries(form).forEach(([k, v]) => {
      if (v == null || v === '') return;
      if (typeof v === 'boolean') fd.append(k, v ? 'true' : 'false');
      else fd.append(k, String(v));
    });
    if (fileBlobs.file) fd.append('file', fileBlobs.file);
    if (fileBlobs.payload_pdf_file) fd.append('payload_pdf_file', fileBlobs.payload_pdf_file);
    if (fileBlobs.payload_pdf_metadata_file) fd.append('payload_pdf_metadata_file', fileBlobs.payload_pdf_metadata_file);
    return { formData: fd };
  }

  function argsJson(args) {
    try {
      return JSON.stringify(args || {});
    } catch (_) {
      return '';
    }
  }

  const PayloadEditor = {
    name: 'PayloadEditor',
    props: {
      mode: { type: String, default: 'standalone' },
      generator: { type: String, default: '' },
      args: { type: Object, default: () => ({}) },
      compact: { type: Boolean, default: false },
      showGenerate: { type: Boolean, default: true },
      outDir: { type: String, default: '' },
    },
    emits: ['generated', 'update:args', 'update:generator', 'error'],
    data() {
      return {
        types: [],
        bgAssets: { pdfs: [], images: [] },
        ffmpegAvailable: null,
        assetType: 'text',
        form: {},
        activeTab: 'line1',
        activePdfTab: 'pdf_line1',
        busy: false,
        statusMsg: '',
        statusError: false,
        result: null,
        showRawJson: false,
        rawJson: '{}',
        fileBlobs: { file: null, payload_pdf_file: null, payload_pdf_metadata_file: null },
        previewTimer: null,
        suiteSyncDepth: 0,
        lastAppliedArgsJson: '',
      };
    },
    computed: {
      schema() {
        return this.types.find(t => t.asset_type === this.assetType) || null;
      },
      isAudio() {
        return this.assetType === 'audio_synthetic' || this.assetType === 'audio_tts';
      },
      downloadUrl() {
        if (!this.result?.relative_path) return '';
        return '/api/payloads/file/' + encodeURIComponent(this.result.relative_path) + '?v=' + Date.now();
      },
    },
    watch: {
      generator: { immediate: true, handler(g) {
        if (this.mode === 'suite' && g) {
          const at = GENERATOR_TO_ASSET[g] || g;
          if (at !== this.assetType) {
            this.runSuiteSync(() => { this.assetType = at; });
          }
        }
      }},
      args: { deep: true, immediate: true, handler(a) {
        this.syncFormFromArgs(a);
      }},
      types: {
        handler() {
          if (this.mode === 'suite' && this.schema) {
            this.syncFormFromArgs(this.args);
          }
        },
      },
      assetType(newAt, oldAt) {
        if (this.isSuiteSyncing()) return;
        if (this.mode === 'suite') {
          if (oldAt != null && oldAt !== newAt && this.schema) {
            this.runSuiteSync(() => {
              this.form = { ...flattenDefaults(this.schema), asset_type: this.assetType };
            });
            this.emitArgsIfChanged();
          }
          return;
        }
        this.resetFormFromSchema();
      },
      form: { deep: true, handler() {
        this.schedulePreview();
        this.emitArgsIfChanged();
      }},
    },
    async mounted() {
      await this.loadTypes();
      await this.loadBackgroundAssets();
      if (this.mode === 'standalone') {
        this.resetFormFromSchema();
      } else if (this.generator) {
        this.runSuiteSync(() => {
          this.assetType = GENERATOR_TO_ASSET[this.generator] || this.generator;
        });
        this.syncFormFromArgs(this.args);
      }
    },
    methods: {
      isSuiteSyncing() {
        return this.suiteSyncDepth > 0;
      },
      runSuiteSync(fn) {
        this.suiteSyncDepth += 1;
        try {
          fn();
        } finally {
          this.suiteSyncDepth -= 1;
        }
      },
      syncFormFromArgs(a) {
        if (this.mode !== 'suite' || !this.schema) return;
        const incoming = argsJson(a);
        if (incoming === this.lastAppliedArgsJson) return;
        this.runSuiteSync(() => {
          this.form = argsToForm(this.assetType, a, this.schema);
          const { args } = formToArgs(this.assetType, this.form);
          this.rawJson = JSON.stringify(args, null, 2);
          this.lastAppliedArgsJson = argsJson(args);
        });
      },
      async loadTypes() {
        try {
          const r = await fetch('/api/payloads/types');
          const data = await r.json();
          this.types = data.types || [];
          this.ffmpegAvailable = data.ffmpeg_available ?? null;
        } catch (_) { this.types = []; }
      },
      async loadBackgroundAssets() {
        try {
          const r = await fetch('/api/payloads/background-assets');
          this.bgAssets = await r.json();
        } catch (_) { this.bgAssets = { pdfs: [], images: [] }; }
      },
      setAssetType(at, emitGen) {
        this.assetType = at;
        if (emitGen !== false && this.mode === 'suite') {
          this.$emit('update:generator', ASSET_TO_GENERATOR[at] || at);
        }
      },
      resetFormFromSchema() {
        if (!this.schema) return;
        this.form = { ...flattenDefaults(this.schema), asset_type: this.assetType };
        this.activeTab = 'line1';
        this.activePdfTab = 'pdf_line1';
        this.fileBlobs = { file: null, payload_pdf_file: null, payload_pdf_metadata_file: null };
        this.schedulePreview();
      },
      emitArgsIfChanged() {
        if (this.mode !== 'suite' || this.isSuiteSyncing()) return;
        const { generator, args } = formToArgs(this.assetType, this.form);
        const nextArgsJson = argsJson(args);
        const prevArgsJson = argsJson(this.args);
        if (generator !== this.generator) {
          this.$emit('update:generator', generator);
        }
        if (nextArgsJson !== prevArgsJson) {
          this.$emit('update:args', args);
          this.lastAppliedArgsJson = nextArgsJson;
        }
        this.rawJson = JSON.stringify(args, null, 2);
      },
      emitArgs() {
        this.emitArgsIfChanged();
      },
      onFileChange(field, ev) {
        const f = ev.target.files && ev.target.files[0];
        this.fileBlobs[field] = f || null;
        if (field === 'file') this.schedulePreview();
      },
      fieldShow(f) { return fieldVisible(f, this.form); },
      positionOptions() { return POSITION_OPTIONS; },
      colorHex(name) { return colorToHex(this.form[name] || '#000000'); },
      onColorPicker(name, ev) { this.form[name] = ev.target.value; },
      schedulePreview() {
        if (this.assetType !== 'image') return;
        clearTimeout(this.previewTimer);
        this.previewTimer = setTimeout(() => this.drawPreview(), 120);
      },
      getPreviewState() {
        const w = Math.max(100, Math.min(2000, Number(this.form.width) || 400));
        const h = Math.max(50, Math.min(2000, Number(this.form.height) || 200));
        const bgColor = parseColor(this.form.background_color || '#ffffff');
        const bgAlpha = Math.max(0, Math.min(100, Number(this.form.background_alpha ?? 100))) / 100;
        const lines = [];
        for (let i = 1; i <= 3; i++) {
          const text = (this.form['line' + i + '_text'] || '').trim().substring(0, 80);
          if (!text) continue;
          lines.push({
            text,
            fontSize: Math.max(8, Math.min(120, Number(this.form['line' + i + '_font_size']) || 14)),
            color: parseColor(this.form['line' + i + '_color'] || '#000000'),
            alpha: Math.max(0, Math.min(100, Number(this.form['line' + i + '_alpha'] ?? 100))) / 100,
            position: this.form['line' + i + '_position'] || 'top_left',
            lowContrast: !!this.form['line' + i + '_low_contrast'],
            textRotation: Number(this.form['line' + i + '_text_rotation'] || 0),
          });
        }
        return { width: w, height: h, bgColor, bgAlpha, lines, file: this.fileBlobs.file };
      },
      drawPreview() {
        const canvas = this.$refs.previewCanvas;
        if (!canvas) return;
        const state = this.getPreviewState();
        canvas.width = state.width;
        canvas.height = state.height;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        const drawBg = () => {
          ctx.fillStyle = 'rgba(' + state.bgColor.r + ',' + state.bgColor.g + ',' + state.bgColor.b + ',' + state.bgAlpha + ')';
          ctx.fillRect(0, 0, state.width, state.height);
        };
        const drawLines = () => {
          state.lines.forEach(line => {
            const fs = line.fontSize;
            ctx.font = fs + 'px sans-serif';
            const metrics = ctx.measureText(line.text);
            const blockWidth = Math.min(metrics.width, state.width - 40);
            const pos = positionToXY(line.position, state.width, state.height, blockWidth, fs + 6, 20);
            let r = line.color.r, g = line.color.g, b = line.color.b;
            if (line.lowContrast) { r = g = b = 180; }
            ctx.fillStyle = 'rgba(' + r + ',' + g + ',' + b + ',' + line.alpha + ')';
            const rot = line.textRotation || 0;
            if (Math.abs(rot) >= 0.5) {
              ctx.save();
              const cx = pos.x + blockWidth / 2, cy = pos.y + fs / 2;
              ctx.translate(cx, cy);
              ctx.rotate(-rot * Math.PI / 180);
              ctx.translate(-cx, -cy);
              ctx.fillText(line.text, pos.x, pos.y + fs);
              ctx.restore();
            } else {
              ctx.fillText(line.text, pos.x, pos.y + fs);
            }
          });
        };
        if (state.file) {
          const url = URL.createObjectURL(state.file);
          const img = new Image();
          img.onload = () => {
            ctx.drawImage(img, 0, 0, state.width, state.height);
            URL.revokeObjectURL(url);
            drawLines();
          };
          img.onerror = () => { URL.revokeObjectURL(url); drawBg(); drawLines(); };
          img.src = url;
        } else {
          drawBg();
          drawLines();
        }
      },
      applyRawJson() {
        try {
          const args = JSON.parse(this.rawJson);
          this.form = argsToForm(this.assetType, args, this.schema);
          this.emitArgs();
        } catch (e) {
          this.statusMsg = 'Invalid JSON';
          this.statusError = true;
        }
      },
      async generate() {
        this.busy = true;
        this.statusMsg = '';
        this.statusError = false;
        this.result = null;
        try {
          const payload = buildGenerateBody(this.assetType, this.form, this.fileBlobs);
          const opts = { method: 'POST' };
          if (payload.formData) {
            if (this.outDir) payload.formData.append('out_dir', this.outDir);
            opts.body = payload.formData;
          } else {
            opts.headers = { 'Content-Type': 'application/json' };
            const body = { ...payload.json };
            if (this.outDir) body.out_dir = this.outDir;
            opts.body = JSON.stringify(body);
          }
          const r = await fetch('/api/payloads/generate', opts);
          const data = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(data.detail || data.error || r.statusText);
          this.result = data;
          this.statusMsg = data.effects_applied?.length
            ? 'Generated with effects: ' + data.effects_applied.join(', ')
            : (data.warning || 'Generated successfully.');
          this.statusError = false;
          this.$emit('generated', data);
        } catch (e) {
          this.statusMsg = e.message || 'Generation failed';
          this.statusError = true;
          this.$emit('error', e);
        } finally {
          this.busy = false;
        }
      },
      lineFields(prefix, pdf) {
        const fields = [
          { name: prefix + '_text', type: 'text', label: 'Text' },
          { name: prefix + '_font_size', type: 'number', label: 'Font size', min: 8, max: pdf ? 72 : 120 },
          { name: prefix + '_color', type: 'color', label: 'Color' },
          { name: prefix + '_alpha', type: 'number', label: 'Opacity (0–100)', min: 0, max: 100 },
          { name: prefix + '_position', type: 'position', label: 'Position' },
        ];
        if (!pdf) {
          fields.push(
            { name: prefix + '_low_contrast', type: 'bool', label: 'Low contrast' },
            { name: prefix + '_text_rotation', type: 'number', label: 'Rotation (°)', min: -45, max: 45 },
            { name: prefix + '_blur_radius', type: 'number', label: 'Blur', min: 0, max: 25, step: 0.5 },
            { name: prefix + '_noise_level', type: 'number', label: 'Noise (0–1)', min: 0, max: 1, step: 0.1 },
          );
        }
        return fields;
      },
    },
    template: `
<div class="payload-editor" :class="{ 'payload-editor-compact': compact }">
  <div class="form-row" v-if="mode === 'standalone'">
    <label>Asset type</label>
    <select v-model="assetType" @change="setAssetType(assetType)" style="max-width:320px;">
      <option v-for="t in types" :key="t.asset_type" :value="t.asset_type">{{ t.label }}</option>
    </select>
  </div>
  <div class="form-row" v-else>
    <label>Payload type</label>
    <select v-model="assetType" @change="setAssetType(assetType)" style="max-width:320px;">
      <option v-for="t in types" :key="t.asset_type" :value="t.asset_type">{{ t.label }}</option>
    </select>
  </div>

  <template v-if="assetType === 'image'">
    <div class="form-row">
      <label>Stock image</label>
      <select v-model="form.source_image" style="max-width:280px;">
        <option value="">- none -</option>
        <option v-for="n in bgAssets.images" :key="n" :value="n">{{ n }}</option>
      </select>
    </div>
    <div class="form-row">
      <label>Upload image</label>
      <input type="file" accept="image/*" @change="onFileChange('file', $event)">
    </div>
    <div class="payload-line-tabs">
      <button type="button" v-for="i in 3" :key="'lt'+i" :class="{ active: activeTab === 'line'+i }" @click="activeTab = 'line'+i">Line {{ i }}</button>
      <button type="button" :class="{ active: activeTab === 'preview' }" @click="activeTab = 'preview'; $nextTick(drawPreview)">Preview</button>
    </div>
    <div v-for="i in 3" :key="'lp'+i" v-show="activeTab === 'line'+i" class="payload-tab-panel">
      <div v-for="f in lineFields('line'+i, false)" :key="f.name" class="form-row payload-field-row">
        <label>{{ f.label }}</label>
        <input v-if="f.type === 'text'" v-model="form[f.name]" style="flex:1;">
        <input v-else-if="f.type === 'number'" type="number" v-model.number="form[f.name]" :min="f.min" :max="f.max" :step="f.step || 1" style="width:100px;">
        <template v-else-if="f.type === 'color'">
          <input type="color" :value="colorHex(f.name)" @input="onColorPicker(f.name, $event)" style="width:2.5em;height:1.8em;">
          <input v-model="form[f.name]" style="width:8em;margin-left:8px;">
        </template>
        <select v-else-if="f.type === 'position'" v-model="form[f.name]">
          <option v-for="p in positionOptions()" :key="p" :value="p">{{ p }}</option>
        </select>
        <label v-else-if="f.type === 'bool'" class="checkbox-row"><input type="checkbox" v-model="form[f.name]"> Yes</label>
      </div>
    </div>
    <div v-show="activeTab === 'preview'" class="payload-tab-panel">
      <p class="text-muted" style="font-size:12px;">Live canvas preview</p>
      <canvas ref="previewCanvas" style="max-width:100%;max-height:280px;border:1px solid var(--border);border-radius:4px;"></canvas>
    </div>
    <div class="form-row"><label>Width</label><input type="number" v-model.number="form.width" style="width:6em;"></div>
    <div class="form-row"><label>Height</label><input type="number" v-model.number="form.height" style="width:6em;"></div>
    <div class="form-row">
      <label>Background</label>
      <input type="color" :value="colorHex('background_color')" @input="onColorPicker('background_color', $event)">
      <input v-model="form.background_color" style="width:8em;margin-left:8px;">
      <label style="margin-left:12px;">Opacity</label>
      <input type="number" v-model.number="form.background_alpha" min="0" max="100" style="width:5em;">
    </div>
  </template>

  <template v-else-if="assetType === 'pdf'">
    <div class="form-row">
      <label>Stock PDF</label>
      <select v-model="form.source_pdf" style="max-width:280px;">
        <option value="">- none -</option>
        <option v-for="n in bgAssets.pdfs" :key="n" :value="n">{{ n }}</option>
      </select>
    </div>
    <div class="form-row">
      <label>Upload PDF</label>
      <input type="file" accept=".pdf" @change="onFileChange('payload_pdf_file', $event)">
    </div>
    <div class="payload-line-tabs">
      <button type="button" v-for="i in 3" :key="'pt'+i" :class="{ active: activePdfTab === 'pdf_line'+i }" @click="activePdfTab = 'pdf_line'+i">Line {{ i }}</button>
      <button type="button" :class="{ active: activePdfTab === 'pdf_hidden' }" @click="activePdfTab = 'pdf_hidden'">Hidden</button>
    </div>
    <div v-for="i in 3" :key="'pp'+i" v-show="activePdfTab === 'pdf_line'+i" class="payload-tab-panel">
      <div v-for="f in lineFields('pdf_line'+i, true)" :key="f.name" class="form-row payload-field-row">
        <label>{{ f.label }}</label>
        <input v-if="f.type === 'text'" v-model="form[f.name]" style="flex:1;">
        <input v-else-if="f.type === 'number'" type="number" v-model.number="form[f.name]" style="width:100px;">
        <template v-else-if="f.type === 'color'">
          <input type="color" :value="colorHex(f.name)" @input="onColorPicker(f.name, $event)">
          <input v-model="form[f.name]" style="width:8em;margin-left:8px;">
        </template>
        <select v-else-if="f.type === 'position'" v-model="form[f.name]">
          <option v-for="p in positionOptions()" :key="p" :value="p">{{ p }}</option>
        </select>
      </div>
    </div>
    <div v-show="activePdfTab === 'pdf_hidden'" class="payload-tab-panel">
      <div class="form-row" style="align-items:flex-start;">
        <label>Hidden (white-on-white)</label>
        <textarea v-model="form.pdf_hidden_content" rows="3" style="flex:1;"></textarea>
      </div>
    </div>
  </template>

  <template v-else-if="assetType === 'pdf_metadata'">
    <div class="form-row">
      <label>Stock PDF</label>
      <select v-model="form.source_pdf" style="max-width:280px;">
        <option value="">- none -</option>
        <option v-for="n in bgAssets.pdfs" :key="n" :value="n">{{ n }}</option>
      </select>
    </div>
    <div class="form-row">
      <label>Upload PDF</label>
      <input type="file" accept=".pdf" @change="onFileChange('payload_pdf_metadata_file', $event)">
    </div>
    <div class="form-row" style="align-items:flex-start;"><label>Body</label><textarea v-model="form.body_content" rows="2" style="flex:1;"></textarea></div>
    <div class="form-row"><label>Subject</label><input v-model="form.subject" style="flex:1;"></div>
    <div class="form-row"><label>Author</label><input v-model="form.author" style="flex:1;"></div>
  </template>

  <template v-else-if="assetType === 'pdf_visible'">
    <div class="form-row" style="align-items:flex-start;"><label>Content</label><textarea v-model="form.content" rows="4" style="flex:1;"></textarea></div>
  </template>

  <template v-else-if="assetType === 'pdf_hidden'">
    <div class="form-row" style="align-items:flex-start;"><label>Visible</label><textarea v-model="form.visible_content" rows="2" style="flex:1;"></textarea></div>
    <div class="form-row" style="align-items:flex-start;"><label>Hidden</label><textarea v-model="form.hidden_content" rows="2" style="flex:1;"></textarea></div>
  </template>

  <template v-else-if="assetType === 'csv'">
    <div class="form-row">
      <label>Mode</label>
      <label class="checkbox-row"><input type="radio" v-model="form.csv_mode" value="custom"> Custom CSV</label>
      <label class="checkbox-row" style="margin-left:12px;"><input type="radio" v-model="form.csv_mode" value="dummy"> Dummy data</label>
    </div>
    <div v-if="form.csv_mode === 'custom'" class="form-row" style="align-items:flex-start;">
      <label>CSV content</label><textarea v-model="form.csv_content" rows="5" style="flex:1;font-family:var(--mono);font-size:12px;"></textarea>
    </div>
    <template v-else>
      <div class="form-row"><label>Columns</label><input v-model="form.csv_columns" style="flex:1;" placeholder="id:integer,name:text,email:email"></div>
      <div class="form-row"><label>Rows</label><input type="number" v-model.number="form.csv_num_rows" min="1" max="10000" style="width:6em;"></div>
      <div class="form-row"><label>Faker</label><label class="checkbox-row"><input type="checkbox" v-model="form.csv_use_faker"> Realistic data</label></div>
    </template>
  </template>

  <template v-else-if="assetType === 'audio_tts'">
    <div class="form-row" style="align-items:flex-start;"><label>Speech</label><textarea v-model="form.text" rows="2" style="flex:1;"></textarea></div>
    <div class="form-row" style="align-items:flex-start;"><label>Overlay / whisper</label><textarea v-model="form.overlay_text" rows="2" style="flex:1;" placeholder="Hidden instruction mixed under the main speech…"></textarea></div>
    <p class="payload-tts-hint" style="margin:0 0 8px;font-size:12px;color:var(--text-dim);">
      Plain speech works without ffmpeg (saved as MP3). WAV conversion and post-processing below require ffmpeg on PATH.
      <span v-if="ffmpegAvailable === false"> ffmpeg is not currently available on this server.</span>
    </p>
    <div class="payload-tts-grid">
      <div v-for="key in ['overlay_level','noise_level','background_tone_hz','background_tone_level','pitch_semitones','speed_factor','echo_delay_ms','echo_decay','distortion','gain_db','low_pass_hz','high_pass_hz']" :key="key" class="form-row">
        <label>{{ key.replace(/_/g, ' ') }}</label>
        <input type="number" v-model.number="form[key]" step="0.05" style="width:100px;">
      </div>
    </div>
  </template>

  <template v-else-if="schema">
    <div v-for="f in schema.fields" :key="f.name" v-show="fieldShow(f) && f.type !== 'tab_group' && f.type !== 'file' && f.type !== 'select_background'" class="form-row payload-field-row">
      <label>{{ f.label }}</label>
      <textarea v-if="f.type === 'textarea'" v-model="form[f.name]" rows="3" style="flex:1;"></textarea>
      <label v-else-if="f.type === 'bool'" class="checkbox-row"><input type="checkbox" v-model="form[f.name]"> Yes</label>
      <input v-else-if="f.type === 'number'" type="number" v-model.number="form[f.name]" :min="f.min" :max="f.max" :step="f.step || 1" style="width:120px;">
      <input v-else v-model="form[f.name]" style="flex:1;">
    </div>
  </template>

  <div class="form-row"><label>Filename</label><input v-model="form.filename" placeholder="optional" style="flex:1;max-width:280px;"></div>

  <div v-if="mode === 'suite'" class="payload-raw-json">
    <button type="button" class="btn btn-ghost btn-sm" @click="showRawJson = !showRawJson">{{ showRawJson ? 'Hide' : 'Advanced:' }} raw JSON args</button>
    <div v-if="showRawJson" style="margin-top:8px;">
      <textarea v-model="rawJson" rows="6" style="width:100%;font-family:var(--mono);font-size:12px;"></textarea>
      <button type="button" class="btn btn-ghost btn-sm" @click="applyRawJson">Apply JSON</button>
    </div>
  </div>

  <div v-if="showGenerate" style="margin-top:12px;display:flex;gap:8px;align-items:center;">
    <button class="btn btn-primary" @click="generate" :disabled="busy">{{ busy ? 'Generating…' : 'Generate' }}</button>
    <span v-if="statusMsg" :style="{ fontSize: '13px', color: statusError ? 'var(--red)' : 'var(--text-dim)' }">{{ statusMsg }}</span>
  </div>

  <div v-if="result && mode === 'standalone'" style="margin-top:12px;font-size:13px;">
    <div><strong>Saved:</strong> <code>{{ result.relative_path || result.path }}</code></div>
    <a v-if="result.relative_path" :href="downloadUrl" target="_blank" rel="noopener">Download</a>
    <audio v-if="isAudio && downloadUrl" :src="downloadUrl" controls style="display:block;margin-top:8px;max-width:100%;"></audio>
  </div>
</div>
    `,
  };

  function registerPayloadEditor(app) {
    // Kebab-case required for in-DOM templates (HTML lowercases PascalCase tags).
    app.component('payload-editor', PayloadEditor);
    app.component('PayloadEditor', PayloadEditor);
  }

  global.registerPayloadEditor = registerPayloadEditor;
  global.PayloadEditorUtils = { argsToForm, formToArgs, GENERATOR_TO_ASSET, ASSET_TO_GENERATOR };
})(typeof window !== 'undefined' ? window : globalThis);
