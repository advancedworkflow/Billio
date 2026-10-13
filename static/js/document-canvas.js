/* Éditeur de documents « canvas » : pages à éléments libres (textes, formes, images,
   tableaux) que l'on pose, déplace, redimensionne et fait pivoter, avec repères
   magnétiques, calques, pages multiples, variables de fusion, historique et autosave.
   Le format des données est re-validé côté serveur par apps/documents/canvas_render.py,
   qui produit aussi le rendu PDF — garder les deux en phase (styles, formes). */
(function () {
  'use strict';

  const root = document.querySelector('[data-dc-root]');
  if (!root) return;

  const cfg = JSON.parse(document.getElementById('dc-config').textContent);
  const meta = window.__dcMeta || {};
  const $ = (sel, ctx = root) => ctx.querySelector(sel);
  const $$ = (sel, ctx = root) => Array.from(ctx.querySelectorAll(sel));

  const SWATCHES = ['#111827', '#6b7280', '#ffffff', '#6d28d9', '#2563eb', '#0891b2', '#16a34a', '#eab308', '#ea580c', '#dc2626', '#db2777', '#f3f4f6'];
  const SNAP = 6;
  const GRID = 8;
  const TYPE_LABEL = { text: 'Texte', shape: 'Forme', image: 'Image', table: 'Tableau', field: 'Champ de formulaire', button: 'Bouton' };
  const TYPE_ICON = { text: 'type', shape: 'square', image: 'image', table: 'table', field: 'text-cursor-input', button: 'mouse-pointer-click' };
  const FORM_FIELD_TYPES = [
    ['text', 'Texte court'], ['textarea', 'Texte long'], ['email', 'Email'], ['phone', 'Téléphone'], ['number', 'Nombre'],
    ['date', 'Date'], ['select', 'Liste déroulante'], ['radio', 'Choix unique'], ['checkbox', 'Choix multiples'],
  ];
  const fieldStyle = (extra) => textStyle(Object.assign({
    fontSize: 13, labelColor: '#374151', fieldBg: '#ffffff', fieldBorder: '#d1d5db', fieldRadius: 8, accent: '#6d28d9',
  }, extra || {}));
  const SHAPE_LABEL = { rect: 'Rectangle', ellipse: 'Ellipse', triangle: 'Triangle', diamond: 'Losange', star: 'Étoile', line: 'Ligne', arrow: 'Flèche', path: 'Tracé vectoriel' };
  const V = window.DcVector; // tracés de Bézier : document-canvas-vector.js

  // ------------------------------------------------------------------ state
  const state = { pages: cfg.data.pages };
  const docMeta = {
    title: meta.title || '',
    document_type: meta.documentType || 'general',
    client_id: meta.clientId || '',
    status: meta.status || 'draft',
    page_format: meta.pageFormat || 'A4',
    page_orientation: meta.pageOrientation || 'portrait',
  };
  let pageW = cfg.pageWidth;
  let pageH = cfg.pageHeight;
  let zoom = 1;
  let selection = { pageId: state.pages[0].id, ids: [] };
  let editing = null; // { id }
  let pen = null;   // plume en cours : { pageId, nodes, cursor, dragging }
  let vedit = null; // tracé dont on modifie les points : { id, paths (px locaux), sel }
  let activeCell = null; // td/th en cours d'édition dans un tableau
  let clipboard = [];
  // Unité d'affichage des cotes et des champs X/Y/L/H (les données restent en px CSS,
  // 96 dpi, comme le rendu PDF) et cotes affichées en permanence ou seulement en déplacement.
  let unit = 'mm';
  let measuresOn = false;
  try {
    unit = localStorage.getItem('dc-unit') === 'px' ? 'px' : 'mm';
    measuresOn = localStorage.getItem('dc-measures') === '1';
  } catch (e) { /* stockage indisponible */ }
  const PX_TO_MM = 25.4 / 96;
  const toUnit = (px) => (unit === 'mm' ? px * PX_TO_MM : px);
  const fromUnit = (v) => (unit === 'mm' ? v / PX_TO_MM : v);
  const unitNumber = (px) => (unit === 'mm' ? (Math.round(px * PX_TO_MM * 10) / 10).toLocaleString('fr-FR') : String(Math.round(px)));
  const fmtLen = (px) => `${unitNumber(px)} ${unit}`;
  const ALIGN_KBD = { left: 'Alt+A', hcenter: 'Alt+H', right: 'Alt+D', top: 'Alt+W', vcenter: 'Alt+V', bottom: 'Alt+S' };
  let interacting = false; // déplacement / redimensionnement en cours
  let altDown = false;
  let gridOn = false;
  try { gridOn = localStorage.getItem('dc-grid') === '1'; } catch (e) { /* stockage indisponible */ }

  const uid = () => Math.random().toString(36).slice(2, 12);
  const clone = (obj) => JSON.parse(JSON.stringify(obj));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const round = (n) => Math.round(n * 100) / 100;

  function pageById(id) { return state.pages.find((p) => p.id === id); }
  function currentPage() { return pageById(selection.pageId) || state.pages[0]; }
  function findElement(id) {
    for (const page of state.pages) {
      const index = page.elements.findIndex((e) => e.id === id);
      if (index !== -1) return { page, el: page.elements[index], index };
    }
    return null;
  }
  function selectedElements() {
    const page = currentPage();
    return selection.ids.map((id) => page.elements.find((e) => e.id === id)).filter(Boolean);
  }

  // ------------------------------------------------------------- history
  const history = { stack: [JSON.stringify(state.pages)], index: 0 };
  function commit() {
    const snap = JSON.stringify(state.pages);
    if (history.stack[history.index] === snap) return;
    history.stack = history.stack.slice(0, history.index + 1);
    history.stack.push(snap);
    if (history.stack.length > 100) history.stack.shift();
    history.index = history.stack.length - 1;
    scheduleSave();
  }
  function restore(snap) {
    state.pages = JSON.parse(snap);
    vedit = null;
    if (!pageById(selection.pageId)) selection.pageId = state.pages[0].id;
    selection.ids = selection.ids.filter((id) => currentPage().elements.some((e) => e.id === id));
    editing = null;
    renderAll();
    scheduleSave();
  }
  function undo() { if (history.index > 0) { history.index -= 1; restore(history.stack[history.index]); } }
  function redo() { if (history.index < history.stack.length - 1) { history.index += 1; restore(history.stack[history.index]); } }

  // ------------------------------------------------------------- defaults
  function baseStyle(extra) {
    return Object.assign({
      opacity: 1, background: 'transparent', borderWidth: 0, borderColor: '#1f2937', borderStyle: 'solid',
      radius: 0, shadow: 'none', padding: 0,
    }, extra || {});
  }
  function textStyle(extra) {
    return baseStyle(Object.assign({
      fontFamily: 'Inter, sans-serif', fontSize: 14, fontWeight: 400, italic: false, underline: false, uppercase: false,
      color: '#1f2937', align: 'left', valign: 'top', lineHeight: 1.45, letterSpacing: 0,
    }, extra || {}));
  }
  function shapeStyle(extra) {
    return baseStyle(Object.assign({ fill: '#ede9fe', strokeColor: '#6d28d9', strokeWidth: 0, strokeStyle: 'solid' }, extra || {}));
  }
  function tableStyle(extra) {
    return textStyle(Object.assign({
      fontSize: 12, headerBg: '#111827', headerColor: '#ffffff', cellBorderColor: '#e5e7eb', stripe: '#f9fafb', cellPadding: 8,
      totalBg: 'transparent',
    }, extra || {}));
  }
  // Options avancées d'un tableau : type des colonnes, totaux, bordures, source des lignes, styles de cellule.
  function tableExtras(cols, extra) {
    return Object.assign({
      columns: Array.from({ length: cols }, () => ({ kind: 'text', align: '', field: '' })),
      totals: { mode: 'none', vatRate: 20, label: '' },
      borders: 'all', source: '', cellStyles: {},
    }, extra || {});
  }
  // ---- Variables : champs standard (client, entreprise, document) + champs personnalisés
  //      (« Formule », « Durée »…) remplis depuis l'onglet Variables. Dans la page, un jeton
  //      affiche la vraie valeur quand elle est connue, sinon son libellé.
  const customFields = Array.isArray(cfg.data.fields) ? cfg.data.fields : [];
  const PREVIEW = cfg.previewValues || { clients: {}, common: {} };
  const CUSTOM_GROUP = 'Champs à remplir';
  const allVariables = () => [
    ...cfg.variables,
    ...customFields.map((f) => ({ key: `champ.${f.id}`, label: f.label, group: CUSTOM_GROUP })),
  ];
  const varLabel = (key) => (allVariables().find((v) => v.key === key) || {}).label || (key.startsWith('champ.') ? 'Champ supprimé' : key);
  const varGroups = () => allVariables().reduce((acc, v) => { (acc[v.group || 'Autres'] = acc[v.group || 'Autres'] || []).push(v); return acc; }, {});
  const fmtDate = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ''); return m ? `${m[3]}/${m[2]}/${m[1]}` : (iso || ''); };
  function varValue(key) {
    if (key.startsWith('champ.')) {
      const f = customFields.find((x) => `champ.${x.id}` === key);
      if (!f) return '';
      if (f.type === 'date') return fmtDate(f.value);
      if ((f.type === 'money' || f.type === 'number') && f.value) { const n = parseNum(f.value); return n === null ? f.value : fmtNum(n, f.type); }
      return f.value || '';
    }
    if (key.startsWith('client.')) return ((PREVIEW.clients || {})[docMeta.client_id] || {})[key] || '';
    if (key.startsWith('quote.') || key.startsWith('invoice.')) {
      const data = sourceData(key.split('.')[0]);
      return data ? (data.vars[key] || '') : '';
    }
    if (key === 'document.title') return docMeta.title || '';
    return (PREVIEW.common || {})[key] || '';
  }
  const tokenText = (key) => varValue(key) || varLabel(key);

  // ---- Devis / facture reliés : remplissent les tableaux « source » et les variables « Devis / Facture du client ».
  //      '' = le plus récent du client ; sinon celui choisi dans l'inspecteur du tableau.
  const docSources = Object.assign({ quote: '', invoice: '' }, cfg.data.sources || {});
  const sourceList = (kind) => (((PREVIEW.sources || {})[docMeta.client_id] || {})[kind]) || [];
  function sourceData(kind) {
    if (docSources[kind]) {
      for (const perClient of Object.values(PREVIEW.sources || {})) {
        const hit = (perClient[kind] || []).find((x) => x.id === docSources[kind]);
        if (hit) return hit;
      }
      return null;
    }
    return sourceList(kind)[0] || null;
  }

  // ---- Nombres des tableaux au format français (miroir de parse_number / format_number côté serveur).
  function parseNum(fragment) {
    const div = document.createElement('div');
    div.innerHTML = String(fragment || '');
    let t = (div.textContent || '').replace(/[\s\u00a0\u202f€%]/g, '');
    if (!t || !/^-?[\d.,]+$/.test(t)) return null;
    if (t.includes(',')) t = t.replace(/\./g, '').replace(/,/g, '.');
    else if ((t.match(/\./g) || []).length > 1) t = t.replace(/\./g, '');
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  }
  function fmtNum(value, kind = 'number') {
    if (value === null || value === undefined) return '';
    const v = Math.round(value * 100) / 100;
    const [int, dec] = Math.abs(v).toFixed(2).split('.');
    const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
    const trimmed = dec.replace(/0+$/, '');
    let text = kind === 'money' ? `${grouped},${dec}` : (trimmed ? `${grouped},${trimmed}` : grouped);
    text = (v < 0 ? '-' : '') + text;
    return kind === 'money' ? `${text}\u00a0€` : (kind === 'percent' ? `${text}\u00a0%` : text);
  }
  const NUMERIC = ['number', 'money', 'calc'];
  const varToken = (key) => `<span class="doc-var-token" data-var="${key}" contenteditable="false">${esc(tokenText(key))}</span>`;
  // Seule la clé (data-var) compte à l'export : le texte affiché est recalculé à chaque rendu.
  const friendlyTokens = (html) => String(html || '').replace(
    /<span[^>]*class="doc-var-token"[^>]*data-var="([\w.]+)"[^>]*>[\s\S]*?<\/span>/g,
    (m, key) => {
      const value = varValue(key);
      return `<span class="doc-var-token" data-var="${key}" contenteditable="false"${value ? ` title="${esc(varLabel(key))}"` : ' data-empty="1"'}>${esc(value || varLabel(key))}</span>`;
    },
  );
  const varOptions = (selectedKey) => Object.entries(varGroups()).map(([group, list]) => `<optgroup label="${esc(group)}">${list.map((v) => `<option value="${esc(v.key)}"${v.key === selectedKey ? ' selected' : ''}>${esc(v.label)}</option>`).join('')}</optgroup>`).join('');

  function makePreset(key) {
    if (key.startsWith('vec:')) return vectorPreset(key.slice(4));
    const el = { id: uid(), name: '', x: 0, y: 0, w: 240, h: 60, rotation: 0, locked: false, hidden: false };
    switch (key) {
      case 'title':
        return Object.assign(el, { type: 'text', w: 460, h: 56, html: 'Titre du document', style: textStyle({ fontSize: 34, fontWeight: 700, color: '#111827', lineHeight: 1.15 }) });
      case 'subtitle':
        return Object.assign(el, { type: 'text', w: 420, h: 32, html: 'Un sous-titre pour présenter le document', style: textStyle({ fontSize: 17, fontWeight: 500, color: '#6b7280' }) });
      case 'paragraph':
        return Object.assign(el, { type: 'text', w: 460, h: 96, html: 'Double-cliquez pour modifier ce texte. Utilisez la barre d\'outils pour la mise en forme et l\'inspecteur à droite pour la police, les couleurs, l\'espacement et l\'encadrement.', style: textStyle({ fontSize: 13, lineHeight: 1.6 }) });
      case 'list':
        return Object.assign(el, { type: 'text', w: 360, h: 90, html: '<ul><li>Premier point</li><li>Deuxième point</li><li>Troisième point</li></ul>', style: textStyle({ fontSize: 13, lineHeight: 1.6 }) });
      case 'callout':
        return Object.assign(el, { type: 'text', w: 460, h: 80, html: '<strong>À noter</strong><br>Un encadré pour mettre une information en avant.', style: textStyle({ fontSize: 13, lineHeight: 1.5, background: '#f5f3ff', padding: 16, radius: 10, color: '#4c1d95', borderWidth: 1, borderColor: '#ddd6fe' }) });
      case 'rect': case 'rounded': case 'ellipse': case 'triangle': case 'diamond': case 'star': {
        const shape = key === 'rounded' ? 'rect' : key;
        return Object.assign(el, { type: 'shape', shape, w: 160, h: shape === 'rect' ? 110 : 160, style: shapeStyle({ radius: key === 'rounded' ? 18 : 0 }) });
      }
      case 'line': case 'arrow':
        return Object.assign(el, { type: 'shape', shape: key, w: 260, h: 16, style: shapeStyle({ strokeWidth: 2, strokeColor: '#111827' }) });
      case 'table':
        return Object.assign(el, { type: 'table', w: 520, h: 120, header: true, colWidths: [33.33, 33.33, 33.34], rows: [['Colonne 1', 'Colonne 2', 'Colonne 3'], ['', '', ''], ['', '', '']], style: tableStyle() }, tableExtras(3));
      case 'price_table':
        // Total de ligne = Qté × Prix, totaux HT / TVA / TTC recalculés automatiquement.
        return Object.assign(el, {
          type: 'table', w: 620, h: 160, header: true, colWidths: [46, 14, 20, 20],
          rows: [['Désignation', 'Qté', 'Prix unitaire', 'Total'], ['Prestation', '1', '500', ''], ['Option', '2', '120', '']],
          style: tableStyle({ headerBg: '#6d28d9', stripe: '#f5f3ff', cellBorderColor: '#ede9fe', totalBg: '#f5f3ff' }),
        }, tableExtras(4, {
          borders: 'rows',
          columns: [{ kind: 'text', align: '', field: 'name' }, { kind: 'number', align: 'center', field: 'quantity' }, { kind: 'money', align: '', field: 'unit_price' }, { kind: 'calc', align: '', field: 'total', a: 1, b: 2 }],
          totals: { mode: 'vat', vatRate: 20, label: '' },
        }));
      case 'quote_table':
        // Relié au devis du client : ses lignes remplacent les lignes d'exemple à l'export.
        return Object.assign(makePreset('price_table'), { name: 'Lignes du devis', source: 'quote' });
      case 'image':
        return Object.assign(el, { type: 'image', w: 280, h: 190, src: '', style: baseStyle({ fit: 'cover', radius: 8 }) });
      case 'banner':
        return Object.assign(el, { type: 'shape', shape: 'rect', name: 'Bandeau', x: 0, y: 0, w: pageW, h: 140, style: shapeStyle({ fill: '#6d28d9' }), _anchor: true });
      case 'client_block':
        return Object.assign(el, { type: 'text', name: 'Bloc client', w: 280, h: 96, html: `<strong>${varToken('client.name')}</strong><br>${varToken('client.address')}<br>${varToken('client.email')}<br>${varToken('client.phone')}`, style: textStyle({ fontSize: 12, lineHeight: 1.6 }) });
      case 'company_block':
        return Object.assign(el, { type: 'text', name: 'Bloc entreprise', w: 280, h: 60, html: `<strong>${varToken('organization.name')}</strong><br>${varToken('organization.email')}`, style: textStyle({ fontSize: 12, lineHeight: 1.6 }) });
      case 'signature':
        return Object.assign(el, { type: 'text', name: 'Signature', w: 260, h: 120, html: '<strong>Bon pour accord</strong><br>Nom :<br>Date :<br><br>Signature :', style: textStyle({ fontSize: 12, lineHeight: 1.6, padding: 14, borderWidth: 1, borderColor: '#d1d5db', borderStyle: 'dashed', radius: 8 }) });
      case 'footer':
        return Object.assign(el, { type: 'text', name: 'Pied de page', x: 56, y: pageH - 64, w: pageW - 112, h: 28, html: `${varToken('organization.name')} · ${varToken('document.number')} · ${varToken('document.date')}`, style: textStyle({ fontSize: 10, color: '#6b7280', align: 'center' }), _anchor: true });
      case 'field_text': case 'field_email': case 'field_phone': case 'field_date': case 'field_number': {
        const ft = key.slice(6);
        const labels = { text: 'Votre nom', email: 'Votre email', phone: 'Votre téléphone', date: 'Date souhaitée', number: 'Budget (€)' };
        return Object.assign(el, { type: 'field', fieldType: ft, label: labels[ft], placeholder: '', required: false, showLabel: true, options: [], w: 320, h: 64, style: fieldStyle() });
      }
      case 'field_textarea':
        return Object.assign(el, { type: 'field', fieldType: 'textarea', label: 'Votre message', placeholder: 'Décrivez votre besoin…', required: false, showLabel: true, options: [], w: 420, h: 130, style: fieldStyle() });
      case 'field_select':
        return Object.assign(el, { type: 'field', fieldType: 'select', label: 'Budget envisagé', placeholder: 'Choisir…', required: false, showLabel: true, options: ['Moins de 5 k€', '5 à 15 k€', 'Plus de 15 k€'], w: 320, h: 64, style: fieldStyle() });
      case 'field_radio':
        return Object.assign(el, { type: 'field', fieldType: 'radio', label: 'Délai souhaité', placeholder: '', required: false, showLabel: true, options: ['Urgent', 'Sous un mois', 'Pas pressé'], w: 280, h: 104, style: fieldStyle() });
      case 'field_checkbox':
        return Object.assign(el, { type: 'field', fieldType: 'checkbox', label: 'Services souhaités', placeholder: '', required: false, showLabel: true, options: ['Design', 'Développement', 'Rédaction'], w: 280, h: 104, style: fieldStyle() });
      case 'button_submit':
        return Object.assign(el, { type: 'button', text: 'Envoyer mes réponses', w: 220, h: 46, style: textStyle({ fontSize: 14, fontWeight: 600, color: '#ffffff', align: 'center', background: '#6d28d9', radius: 10 }) });
      default:
        return null;
    }
  }

  // Aperçu d'un champ de formulaire dans l'éditeur (le portail affiche de vrais contrôles).
  function fieldHtml(el) {
    const s = el.style;
    const label = el.showLabel && el.label
      ? `<div class="dc-fld-label" style="color:${s.labelColor}">${esc(el.label)}${el.required ? ` <span style="color:${s.accent}">*</span>` : ''}</div>` : '';
    const box = `background:${s.fieldBg};border:1px solid ${s.fieldBorder};border-radius:${s.fieldRadius}px`;
    if (el.fieldType === 'radio' || el.fieldType === 'checkbox') {
      const shape = el.fieldType === 'radio' ? '50%' : '4px';
      return label + `<div class="dc-fld-opts">${(el.options.length ? el.options : ['Option']).map((o) => `<div class="dc-fld-opt"><span style="border:1.5px solid ${s.fieldBorder};border-radius:${shape}"></span>${esc(o)}</div>`).join('')}</div>`;
    }
    const placeholder = el.fieldType === 'select' ? (el.placeholder || 'Choisir…') : (el.fieldType === 'date' ? 'jj/mm/aaaa' : el.placeholder);
    const caret = el.fieldType === 'select' ? '<i class="dc-fld-caret">▾</i>' : '';
    return label + `<div class="dc-fld-input${el.fieldType === 'textarea' ? ' is-area' : ''}" style="${box}"><span>${esc(placeholder || '')}</span>${caret}</div>`;
  }

  // ------------------------------------------------------------- rendering
  const pagesHost = $('[data-dc-pages]');
  const workspace = $('[data-dc-workspace]');

  function shapeSvg(el) {
    const s = el.style; const w = el.w; const h = el.h;
    const sw = s.strokeWidth || 0;
    const stroke = sw ? s.strokeColor : 'none';
    const dash = s.strokeStyle === 'dashed' ? `${sw * 3},${sw * 2}` : s.strokeStyle === 'dotted' ? `${sw},${sw * 1.5}` : '';
    const dashAttr = dash ? ` stroke-dasharray="${dash}"` : '';
    let fill = s.fill;
    let defs = '';
    if (s.fill2 && el.shape !== 'line' && el.shape !== 'arrow') {
      // Dégradé linéaire en unités de la boîte : angle 0 = de gauche à droite (comme le PDF).
      const a = ((s.gradientAngle || 0) * Math.PI) / 180;
      const dx = Math.cos(a) / 2; const dy = Math.sin(a) / 2;
      const gid = `dcg-${el.id}`;
      defs = `<defs><linearGradient id="${gid}" x1="${(0.5 - dx).toFixed(4)}" y1="${(0.5 - dy).toFixed(4)}" x2="${(0.5 + dx).toFixed(4)}" y2="${(0.5 + dy).toFixed(4)}"><stop offset="0" stop-color="${s.fill}"/><stop offset="1" stop-color="${s.fill2}"/></linearGradient></defs>`;
      fill = `url(#${gid})`;
    }
    const common = `fill="${fill}" stroke="${stroke}" stroke-width="${sw}"${dashAttr}`;
    const half = sw / 2;
    let body;
    switch (el.shape) {
      case 'path':
        body = `<path d="${V.toD(V.fromStored(el.paths, w, h))}" ${common} fill-rule="${s.fillRule || 'nonzero'}" stroke-linejoin="round" stroke-linecap="round"/>`; break;
      case 'ellipse':
        body = `<ellipse cx="${w / 2}" cy="${h / 2}" rx="${Math.max(0, w / 2 - half)}" ry="${Math.max(0, h / 2 - half)}" ${common}/>`; break;
      case 'triangle':
        body = `<polygon points="${w / 2},${half} ${w - half},${h - half} ${half},${h - half}" ${common}/>`; break;
      case 'diamond':
        body = `<polygon points="${w / 2},${half} ${w - half},${h / 2} ${w / 2},${h - half} ${half},${h / 2}" ${common}/>`; break;
      case 'star': {
        const cx = w / 2; const cy = h / 2; const outer = Math.min(w, h) / 2 - half; const inner = outer * 0.45;
        const pts = [];
        for (let i = 0; i < 10; i += 1) {
          const r = i % 2 === 0 ? outer : inner; const a = (Math.PI / 5) * i - Math.PI / 2;
          pts.push(`${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`);
        }
        body = `<polygon points="${pts.join(' ')}" ${common}/>`; break;
      }
      case 'line': case 'arrow': {
        const lw = Math.max(sw, 1); const color = s.strokeColor;
        const end = w - (el.shape === 'arrow' ? lw * 3 : 0);
        body = `<line x1="0" y1="${h / 2}" x2="${end}" y2="${h / 2}" stroke="${color}" stroke-width="${lw}"${dashAttr}/>`;
        if (el.shape === 'arrow') {
          const head = lw * 3.5;
          body += `<polygon points="${w},${h / 2} ${w - head},${h / 2 - head / 1.4} ${w - head},${h / 2 + head / 1.4}" fill="${color}"/>`;
        }
        break;
      }
      default:
        body = `<rect x="${half}" y="${half}" width="${Math.max(0, w - sw)}" height="${Math.max(0, h - sw)}" rx="${s.radius}" ry="${s.radius}" ${common}/>`;
    }
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${defs}${body}</svg>`;
  }

  function textCss(s) {
    return [
      `font-family:${s.fontFamily}`, `font-size:${s.fontSize}px`, `font-weight:${s.fontWeight}`, `color:${s.color}`,
      `text-align:${s.align}`, `line-height:${s.lineHeight}`, `letter-spacing:${s.letterSpacing || 0}px`,
      s.italic ? 'font-style:italic' : '', s.underline ? 'text-decoration:underline' : '', s.uppercase ? 'text-transform:uppercase' : '',
    ].filter(Boolean).join(';');
  }

  const SHADOWS = { none: 'none', sm: '0 1px 2px rgba(15,23,42,.12)', md: '0 4px 12px rgba(15,23,42,.14)', lg: '0 12px 32px rgba(15,23,42,.18)' };

  function applyBox(node, el, index) {
    const s = el.style;
    Object.assign(node.style, {
      left: `${el.x}px`, top: `${el.y}px`, width: `${el.w}px`, height: `${el.h}px`,
      transform: el.rotation ? `rotate(${el.rotation}deg)` : '',
      opacity: s.opacity, zIndex: String(index + 1),
      display: el.hidden ? 'none' : '',
    });
    if (el.type !== 'shape') {
      Object.assign(node.style, {
        background: s.background,
        border: s.borderWidth ? `${s.borderWidth}px ${s.borderStyle} ${s.borderColor}` : 'none',
        borderRadius: `${s.radius || 0}px`,
        padding: `${s.padding || 0}px`,
        boxShadow: SHADOWS[s.shadow] || 'none',
      });
    }
  }

  // Lignes affichées d'un tableau (miroir de table_rows() dans canvas_render.py).
  // raw = édition : lignes enregistrées telles quelles (pas de mise en forme des nombres ni de lignes du devis).
  function tableModel(el, raw) {
    const cols = el.columns;
    const count = cols.length;
    const out = [];
    if (el.header) out.push({ kind: 'header', cells: el.rows[0].map((h, c) => ({ html: friendlyTokens(h), r: 0, c })) });
    const offset = el.header ? 1 : 0;
    const data = !raw && el.source ? sourceData(el.source) : null;
    const body = data
      ? data.rows.map((item) => cols.map((col) => ({ html: esc(col.field ? (item[col.field] ?? '') : '') })))
      : el.rows.slice(offset).map((row, i) => row.map((h, c) => ({ html: friendlyTokens(h), r: i + offset, c })));
    const sums = new Array(count).fill(0);
    let amountCol = -1;
    for (let i = count - 1; i >= 0; i -= 1) if (cols[i].kind === 'money' || cols[i].kind === 'calc') { amountCol = i; break; }
    if (amountCol < 0) for (let i = count - 1; i >= 0; i -= 1) if (cols[i].kind === 'number') { amountCol = i; break; }
    let vatLines = 0;
    const rates = new Set();
    body.forEach((cells, index) => {
      const numbers = cells.map((c) => parseNum(c.html));
      cols.forEach((col, i) => {
        if (col.kind === 'calc') {
          const a = numbers[col.a]; const b = numbers[col.b];
          numbers[i] = a !== null && b !== null && a !== undefined && b !== undefined ? Math.round(a * b * 100) / 100 : null;
          cells[i].calc = true;
          cells[i].html = fmtNum(numbers[i], 'money');
        } else if (!raw && col.kind !== 'text' && numbers[i] !== null) {
          cells[i].html = esc(fmtNum(numbers[i], col.kind));
        }
        if (NUMERIC.includes(col.kind) && numbers[i] !== null) sums[i] += numbers[i];
      });
      if (data && amountCol >= 0 && numbers[amountCol] !== null) {
        const rate = data.rows[index]._rate;
        if (rate !== undefined && rate !== null) { rates.add(rate); vatLines += numbers[amountCol] * rate / 100; }
      }
      out.push({ kind: 'body', cells });
    });
    const totals = el.totals || { mode: 'none' };
    if (totals.mode === 'sum' && cols.some((c) => NUMERIC.includes(c.kind))) {
      out.push({ kind: 'total', cells: cols.map((col, i) => {
        if (NUMERIC.includes(col.kind)) return { html: esc(fmtNum(sums[i], col.kind === 'number' ? 'number' : 'money')) };
        return { html: i === 0 ? esc(totals.label || 'Total') : '' };
      }) });
    } else if (totals.mode === 'vat' && amountCol >= 0) {
      const ht = Math.round(sums[amountCol] * 100) / 100;
      let vat; let rateLabel;
      if (data && rates.size) {
        vat = Math.round(vatLines * 100) / 100;
        rateLabel = rates.size === 1 ? `TVA ${fmtNum([...rates][0], 'percent')}` : 'TVA';
      } else {
        vat = Math.round(ht * totals.vatRate) / 100;
        rateLabel = `TVA ${fmtNum(totals.vatRate, 'percent')}`;
      }
      [[totals.label || 'Total HT', ht, false], [rateLabel, vat, false], ['Total TTC', ht + vat, true]].forEach(([label, amount, strong]) => {
        const cells = [];
        if (amountCol > 0) {
          cells.push({ html: esc(label), colspan: amountCol, align: 'right' });
          cells.push({ html: esc(fmtNum(amount, 'money')), strong });
        } else cells.push({ html: esc(`${label} : ${fmtNum(amount, 'money')}`), strong });
        if (count - amountCol - 1 > 0) cells.push({ html: '', colspan: count - amountCol - 1 });
        out.push({ kind: 'total', cells });
      });
    }
    return { rows: out, linked: !!data };
  }

  function tableHtml(el, raw = false) {
    const s = el.style;
    const mode = el.borders || 'all';
    const cols = el.columns;
    let bodyIndex = 0;
    let firstTotal = true;
    const rows = tableModel(el, raw).rows.map((row) => {
      let pos = 0;
      const cells = row.cells.map((c) => {
        const col = cols[Math.min(pos, cols.length - 1)];
        const css = [`padding:${s.cellPadding}px`];
        if (mode === 'all') css.push(`border:1px solid ${s.cellBorderColor}`);
        else if (mode === 'rows') css.push(`border-bottom:1px solid ${s.cellBorderColor}`);
        let align = c.align || col.align || (col.kind !== 'text' && row.kind !== 'header' ? 'right' : s.align);
        if (row.kind === 'header') css.push(`background:${s.headerBg}`, `color:${s.headerColor}`, 'font-weight:600');
        else if (row.kind === 'body') { if (s.stripe !== 'transparent' && bodyIndex % 2 === 1) css.push(`background:${s.stripe}`); }
        else {
          css.push(c.strong ? 'font-weight:700' : 'font-weight:600');
          if (s.totalBg && s.totalBg !== 'transparent') css.push(`background:${s.totalBg}`);
          if (firstTotal) css.push(`border-top:1.5px solid ${s.color}`);
        }
        const custom = c.r !== undefined ? (el.cellStyles || {})[`${c.r}:${c.c}`] : null;
        if (custom) {
          if (custom.bg) css.push(`background:${custom.bg}`);
          if (custom.color) css.push(`color:${custom.color}`);
          if (custom.bold) css.push('font-weight:700');
          if (custom.italic) css.push('font-style:italic');
          align = custom.align || align;
        }
        css.push(`text-align:${align}`);
        const tag = row.kind === 'header' ? 'th' : 'td';
        const attrs = c.r !== undefined ? ` data-r="${c.r}" data-c="${c.c}"${c.calc ? ' data-calc="1"' : ''}` : ' data-gen="1"';
        pos += c.colspan || 1;
        return `<${tag}${attrs}${c.colspan > 1 ? ` colspan="${c.colspan}"` : ''} style="${css.join(';')}">${c.html}</${tag}>`;
      }).join('');
      if (row.kind === 'body') bodyIndex += 1;
      if (row.kind === 'total') firstTotal = false;
      return `<tr>${cells}</tr>`;
    }).join('');
    const colgroup = el.colWidths.map((w) => `<col style="width:${w}%">`).join('');
    return `<table class="dc-table" style="${textCss(s)}${mode === 'outer' ? `;border:1px solid ${s.cellBorderColor}` : ''}"><colgroup>${colgroup}</colgroup>${rows}</table>`;
  }
  const EDITABLE_CELLS = 'td[data-r]:not([data-calc]), th[data-r]';

  function buildElement(el, index) {
    const node = document.createElement('div');
    node.className = `dc-el dc-el--${el.type}`;
    node.dataset.id = el.id;
    if (el.locked) node.classList.add('is-locked');
    applyBox(node, el, index);
    if (el.type === 'text') {
      const justify = { top: 'flex-start', middle: 'center', bottom: 'flex-end' }[el.style.valign] || 'flex-start';
      node.innerHTML = `<div class="dc-text" style="justify-content:${justify};${textCss(el.style)}"><div class="dc-text-content">${friendlyTokens(el.html)}</div></div>`;
    } else if (el.type === 'shape') {
      node.innerHTML = shapeSvg(el);
    } else if (el.type === 'image') {
      node.innerHTML = el.src
        ? `<img src="${esc(el.src)}" alt="" draggable="false" style="object-fit:${el.style.fit};border-radius:${el.style.radius || 0}px">`
        : '<div class="dc-img-empty"><i data-lucide="image-plus"></i><span>Double-cliquez pour choisir une image</span></div>';
    } else if (el.type === 'table') {
      node.innerHTML = tableHtml(el);
    } else if (el.type === 'field') {
      node.innerHTML = `<div class="dc-fld" style="${textCss(el.style)}">${fieldHtml(el)}</div>`;
    } else if (el.type === 'button') {
      node.innerHTML = `<div class="dc-btn-el" style="${textCss(el.style)}">${esc(el.text)}</div>`;
    }
    return node;
  }

  function renderPages() {
    const existing = new Map($$('.dc-page-wrap', pagesHost).map((n) => [n.dataset.pageId, n]));
    const total = state.pages.length;
    state.pages.forEach((page, pi) => {
      let wrap = existing.get(page.id);
      if (!wrap) {
        wrap = document.createElement('div');
        wrap.className = 'dc-page-wrap';
        wrap.dataset.pageId = page.id;
        wrap.innerHTML = `
          <div class="dc-page-bar">
            <span class="dc-page-label"></span>
            <span class="dc-page-bar-actions">
              <button type="button" data-dc-page-cmd="up" title="Monter"><i data-lucide="chevron-up" class="w-3.5 h-3.5"></i></button>
              <button type="button" data-dc-page-cmd="down" title="Descendre"><i data-lucide="chevron-down" class="w-3.5 h-3.5"></i></button>
              <button type="button" data-dc-page-cmd="duplicate" title="Dupliquer la page"><i data-lucide="copy" class="w-3.5 h-3.5"></i></button>
              <button type="button" data-dc-page-cmd="add" title="Ajouter une page après"><i data-lucide="file-plus-2" class="w-3.5 h-3.5"></i></button>
              <button type="button" data-dc-page-cmd="delete" title="Supprimer la page"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button>
            </span>
          </div>
          <div class="dc-page-frame"><div class="dc-page" data-dc-page><div class="dc-page-elements"></div><div class="dc-overlay"></div></div></div>`;
      }
      pagesHost.appendChild(wrap); // remet dans l'ordre
      existing.delete(page.id);
      wrap.classList.toggle('is-current', page.id === selection.pageId);
      wrap.querySelector('.dc-page-label').textContent = `Page ${pi + 1} / ${total}`;
      const frame = wrap.querySelector('.dc-page-frame');
      frame.style.width = `${pageW * zoom}px`;
      frame.style.height = `${pageH * zoom}px`;
      const pageNode = wrap.querySelector('[data-dc-page]');
      Object.assign(pageNode.style, { width: `${pageW}px`, height: `${pageH}px`, transform: `scale(${zoom})`, background: page.background });
      pageNode.classList.toggle('has-grid', gridOn);
      pageNode.style.setProperty('--dc-inv', String(1 / zoom));

      const host = pageNode.querySelector('.dc-page-elements');
      const nodes = new Map($$('.dc-el', host).map((n) => [n.dataset.id, n]));
      page.elements.forEach((el, index) => {
        let node = nodes.get(el.id);
        if (editing && editing.id === el.id && node) {
          applyBox(node, el, index);
        } else {
          const fresh = buildElement(el, index);
          if (node) node.replaceWith(fresh); else host.appendChild(fresh);
          node = fresh;
        }
        host.appendChild(node);
        nodes.delete(el.id);
      });
      nodes.forEach((n) => n.remove());
    });
    existing.forEach((n) => n.remove());
    fitTables();
    refreshIcons(pagesHost);
  }

  function nodeFor(id) { return pagesHost.querySelector(`.dc-el[data-id="${id}"]`); }

  // Les tableaux prennent toujours la hauteur de leur contenu (pas de cellules coupées).
  function fitTables() {
    state.pages.forEach((page) => page.elements.forEach((el) => {
      if (el.type !== 'table' || el.hidden) return;
      const node = nodeFor(el.id);
      const table = node && node.querySelector('table');
      if (!table) return;
      const needed = Math.ceil(table.offsetHeight + 2 * (el.style.padding || 0) + 2 * (el.style.borderWidth || 0));
      if (needed && Math.abs(needed - el.h) > 1) { el.h = needed; node.style.height = `${needed}px`; }
    }));
  }

  // Les textes s'agrandissent automatiquement quand leur contenu dépasse.
  function growText(el) {
    if (!el || el.type !== 'text') return;
    const node = nodeFor(el.id);
    if (!node) return;
    const previous = node.style.height;
    node.style.height = 'auto';
    const needed = Math.ceil(node.offsetHeight);
    node.style.height = previous;
    if (needed > el.h) { el.h = needed; node.style.height = `${needed}px`; }
  }

  function renderSelection() {
    $$('.dc-overlay', pagesHost).forEach((o) => { o.innerHTML = ''; });
    if (pen) drawPen(); else if (vedit) drawVectorEdit(); else clearVecLayers();
    const pageWrap = pagesHost.querySelector(`.dc-page-wrap[data-page-id="${selection.pageId}"]`);
    if (!pageWrap) return;
    const overlay = pageWrap.querySelector('.dc-overlay');
    const els = selectedElements();
    if (!els.length) return;
    if (els.length === 1) {
      const el = els[0];
      const box = document.createElement('div');
      box.className = 'dc-sel dc-sel--single';
      box.dataset.selId = el.id;
      if ((editing && editing.id === el.id) || (vedit && vedit.id === el.id)) box.classList.add('is-editing');
      if (el.locked) box.classList.add('is-locked');
      Object.assign(box.style, { left: `${el.x}px`, top: `${el.y}px`, width: `${el.w}px`, height: `${el.h}px`, transform: el.rotation ? `rotate(${el.rotation}deg)` : '' });
      if (!el.locked && !(editing && editing.id === el.id) && !(vedit && vedit.id === el.id)) {
        const handles = el.type === 'shape' && (el.shape === 'line' || el.shape === 'arrow') ? ['w', 'e'] : ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];
        handles.forEach((dir) => {
          const h = document.createElement('span');
          h.className = `dc-handle dc-handle--${dir}`;
          h.dataset.handle = dir;
          box.appendChild(h);
        });
        const rot = document.createElement('span');
        rot.className = 'dc-handle dc-handle--rotate';
        rot.dataset.handle = 'rotate';
        rot.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12"><path d="M21 12a9 9 0 1 1-3-6.7L21 8" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/><path d="M21 3v5h-5" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>';
        box.appendChild(rot);
        const size = document.createElement('span');
        size.className = 'dc-size-badge';
        size.textContent = `${unitNumber(el.w)} × ${unitNumber(el.h)} ${unit}`;
        box.appendChild(size);
      }
      if (el.locked) {
        const lock = document.createElement('span');
        lock.className = 'dc-lock-badge';
        lock.innerHTML = '<i data-lucide="lock" class="w-3 h-3"></i>';
        box.appendChild(lock);
      }
      overlay.appendChild(box);
    } else {
      els.forEach((el) => {
        const box = document.createElement('div');
        box.className = 'dc-sel dc-sel--multi';
        Object.assign(box.style, { left: `${el.x}px`, top: `${el.y}px`, width: `${el.w}px`, height: `${el.h}px`, transform: el.rotation ? `rotate(${el.rotation}deg)` : '' });
        overlay.appendChild(box);
      });
      const b = bbox(els);
      const group = document.createElement('div');
      group.className = 'dc-sel dc-sel--group';
      Object.assign(group.style, { left: `${b.x}px`, top: `${b.y}px`, width: `${b.w}px`, height: `${b.h}px` });
      overlay.appendChild(group);
    }
    if ((measuresOn || altDown || interacting) && !editing) drawMeasures(pageWrap.querySelector('[data-dc-page]'), boxOf(els));
    refreshIcons(overlay);
  }

  // ------------------------------------------------------------- cotes
  // Boîte englobante réelle d'un élément pivoté (pour coter ce que l'on voit).
  function aabb(el) {
    const r = ((el.rotation || 0) * Math.PI) / 180;
    const c = Math.abs(Math.cos(r)); const s = Math.abs(Math.sin(r));
    const w = el.w * c + el.h * s; const h = el.w * s + el.h * c;
    return { x: el.x + el.w / 2 - w / 2, y: el.y + el.h / 2 - h / 2, w, h };
  }
  const boxOf = (els) => bbox(els.map(aabb));

  function clearMeasures(pageNode) {
    const scope = pageNode ? [pageNode] : $$('[data-dc-page]', pagesHost);
    scope.forEach((p) => p.querySelectorAll('.dc-measure, .dc-measure-target').forEach((m) => m.remove()));
  }

  function addMeasure(overlay, axis, from, to, at) {
    const length = to - from;
    if (Math.abs(length) < 0.5) return;
    const m = document.createElement('div');
    m.className = `dc-measure dc-measure--${axis}${length < 0 ? ' is-negative' : ''}`;
    const lo = Math.min(from, to); const size = Math.abs(length);
    if (axis === 'h') Object.assign(m.style, { left: `${lo}px`, top: `${at}px`, width: `${size}px` });
    else Object.assign(m.style, { top: `${lo}px`, left: `${at}px`, height: `${size}px` });
    m.innerHTML = `<span>${length < 0 ? '−' : ''}${fmtLen(size)}</span>`;
    overlay.appendChild(m);
  }

  // Cotes de `a` jusqu'aux bords de `container` (la page par défaut) : gauche, droite, haut, bas.
  function drawMeasures(pageNode, a, container) {
    if (!pageNode) return;
    clearMeasures(pageNode);
    const overlay = pageNode.querySelector('.dc-overlay');
    const c = container || { x: 0, y: 0, w: pageW, h: pageH };
    const midY = a.y + a.h / 2; const midX = a.x + a.w / 2;
    addMeasure(overlay, 'h', c.x, a.x, midY);
    addMeasure(overlay, 'h', a.x + a.w, c.x + c.w, midY);
    addMeasure(overlay, 'v', c.y, a.y, midX);
    addMeasure(overlay, 'v', a.y + a.h, c.y + c.h, midX);
  }

  // Alt + survol : écart entre la sélection et l'élément survolé (ou cotes intérieures
  // si l'un contient l'autre, ex. un titre posé dans un bandeau).
  function drawGap(pageNode, a, b) {
    const inside = (p, q) => p.x >= q.x && p.y >= q.y && p.x + p.w <= q.x + q.w && p.y + p.h <= q.y + q.h;
    if (inside(a, b)) { drawMeasures(pageNode, a, b); } else if (inside(b, a)) { drawMeasures(pageNode, b, a); } else {
      clearMeasures(pageNode);
      const overlay = pageNode.querySelector('.dc-overlay');
      const oy0 = Math.max(a.y, b.y); const oy1 = Math.min(a.y + a.h, b.y + b.h);
      const ox0 = Math.max(a.x, b.x); const ox1 = Math.min(a.x + a.w, b.x + b.w);
      const atY = oy1 > oy0 ? (oy0 + oy1) / 2 : a.y + a.h / 2;
      const atX = ox1 > ox0 ? (ox0 + ox1) / 2 : a.x + a.w / 2;
      if (b.x >= a.x + a.w) addMeasure(overlay, 'h', a.x + a.w, b.x, atY);
      else if (b.x + b.w <= a.x) addMeasure(overlay, 'h', b.x + b.w, a.x, atY);
      if (b.y >= a.y + a.h) addMeasure(overlay, 'v', a.y + a.h, b.y, atX);
      else if (b.y + b.h <= a.y) addMeasure(overlay, 'v', b.y + b.h, a.y, atX);
    }
    const target = document.createElement('div');
    target.className = 'dc-measure-target';
    Object.assign(target.style, { left: `${b.x}px`, top: `${b.y}px`, width: `${b.w}px`, height: `${b.h}px` });
    pageNode.querySelector('.dc-overlay').appendChild(target);
  }

  pagesHost.addEventListener('pointermove', (e) => {
    if (!e.altKey || interacting || editing || !selection.ids.length) return;
    const pageNode = e.target.closest('[data-dc-page]');
    if (!pageNode || pageNode.closest('.dc-page-wrap').dataset.pageId !== selection.pageId) return;
    const hovered = e.target.closest('.dc-el');
    const sel = selectedElements();
    const other = hovered && !selection.ids.includes(hovered.dataset.id) && currentPage().elements.find((x) => x.id === hovered.dataset.id);
    if (other) drawGap(pageNode, boxOf(sel), aabb(other));
    else drawMeasures(pageNode, boxOf(sel));
  });

  function bbox(els) {
    const xs = els.map((e) => e.x); const ys = els.map((e) => e.y);
    const xe = els.map((e) => e.x + e.w); const ye = els.map((e) => e.y + e.h);
    const x = Math.min(...xs); const y = Math.min(...ys);
    return { x, y, w: Math.max(...xe) - x, h: Math.max(...ye) - y };
  }

  function refreshIcons(scope) {
    if (scope && !scope.querySelector('i[data-lucide]')) return;
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  function renderAll() {
    renderPages();
    renderSelection();
    renderInspector();
    renderLayers();
    renderPagesPane();
    updateToolbar();
  }

  // ------------------------------------------------------------- selection
  function select(ids, pageId) {
    if (vedit && !(ids.length === 1 && ids[0] === vedit.id)) stopVectorEdit();
    if (pageId && pageId !== selection.pageId) {
      selection.pageId = pageId;
      $$('.dc-page-wrap', pagesHost).forEach((w) => w.classList.toggle('is-current', w.dataset.pageId === pageId));
    }
    selection.ids = ids;
    renderSelection();
    renderInspector();
    renderLayers();
    renderPagesPane();
    updateToolbar();
  }

  function addElement(el, page, at) {
    page = page || currentPage();
    if (!el._anchor) {
      if (at) {
        el.x = round(at.x - el.w / 2); el.y = round(at.y - el.h / 2);
      } else {
        const visible = visiblePageCenter(page);
        const offset = (page.elements.length % 6) * 14;
        el.x = round(visible.x - el.w / 2 + offset); el.y = round(visible.y - el.h / 2 + offset);
      }
      el.x = Math.max(-el.w + 20, Math.min(pageW - 20, el.x));
      el.y = Math.max(-el.h + 20, Math.min(pageH - 20, el.y));
    }
    delete el._anchor;
    page.elements.push(el);
    selection.pageId = page.id;
    renderPages();
    select([el.id], page.id);
    commit();
    return el;
  }

  function visiblePageCenter(page) {
    const wrap = pagesHost.querySelector(`.dc-page-wrap[data-page-id="${page.id}"] [data-dc-page]`);
    if (!wrap) return { x: pageW / 2, y: pageH / 3 };
    const rect = wrap.getBoundingClientRect();
    const ws = workspace.getBoundingClientRect();
    const top = Math.max(rect.top, ws.top); const bottom = Math.min(rect.bottom, ws.bottom);
    const cy = bottom > top ? ((top + bottom) / 2 - rect.top) / zoom : pageH / 3;
    return { x: pageW / 2, y: Math.max(60, Math.min(pageH - 60, cy)) };
  }

  // ------------------------------------------------------------- editing
  function startEditing(id) {
    const found = findElement(id);
    if (!found || found.el.locked) return;
    const { el } = found;
    if (el.type === 'image') { pickImage(el.id); return; }
    if (el.type === 'shape' && el.shape === 'path') { startVectorEdit(el.id); return; }
    if (el.type !== 'text' && el.type !== 'table') return;
    stopEditing();
    editing = { id };
    const node = nodeFor(id);
    node.classList.add('is-editing');
    if (el.type === 'text') {
      const content = node.querySelector('.dc-text-content');
      content.contentEditable = 'true';
      content.focus();
      const range = document.createRange();
      range.selectNodeContents(content);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } else {
      // En édition : lignes enregistrées brutes (les lignes du devis et les totaux restent calculés).
      node.innerHTML = tableHtml(el, true);
      fitTables();
      node.querySelectorAll(EDITABLE_CELLS).forEach((cell) => { cell.contentEditable = 'true'; });
      const first = node.querySelector(EDITABLE_CELLS);
      if (first) { first.focus(); activeCell = first; }
    }
    renderSelection();
    renderInspector();
    updateToolbar();
  }

  function stopEditing() {
    if (!editing) return;
    const found = findElement(editing.id);
    const node = nodeFor(editing.id);
    if (found && node) {
      const { el } = found;
      if (el.type === 'text') {
        const content = node.querySelector('.dc-text-content');
        content.contentEditable = 'false';
        el.html = content.innerHTML;
      } else if (el.type === 'table') {
        node.querySelectorAll(EDITABLE_CELLS).forEach((cell) => {
          cell.contentEditable = 'false';
          el.rows[+cell.dataset.r][+cell.dataset.c] = cell.innerHTML;
        });
      }
      node.classList.remove('is-editing');
    }
    editing = null;
    activeCell = null;
    window.getSelection().removeAllRanges();
    renderPages();
    renderSelection();
    renderInspector();
    renderLayers();
    updateToolbar();
    commit();
  }

  pagesHost.addEventListener('input', (e) => {
    if (!editing) return;
    const found = findElement(editing.id);
    if (!found) return;
    if (found.el.type === 'text') growText(found.el);
    if (found.el.type === 'table') {
      const cell = e.target.closest(EDITABLE_CELLS);
      if (cell) found.el.rows[+cell.dataset.r][+cell.dataset.c] = cell.innerHTML;
      fitTables();
    }
    renderSelection();
    scheduleSave();
  });
  pagesHost.addEventListener('focusin', (e) => {
    const cell = e.target.closest && e.target.closest('td[contenteditable="true"], th[contenteditable="true"]');
    if (cell && cell !== activeCell) {
      activeCell = cell;
      pagesHost.querySelectorAll('.is-active-cell').forEach((c) => c.classList.remove('is-active-cell'));
      cell.classList.add('is-active-cell');
      renderInspector(); // section « Cellule » : mise en forme de la cellule active
    }
  });

  // ------------------------------------------------------------- pointer: move / resize / rotate / marquee
  function pagePoint(pageNode, evt) {
    const rect = pageNode.getBoundingClientRect();
    return { x: (evt.clientX - rect.left) / zoom, y: (evt.clientY - rect.top) / zoom };
  }

  function snapTargets(page, excludeIds) {
    const xs = [0, pageW / 2, pageW]; const ys = [0, pageH / 2, pageH];
    page.elements.forEach((e) => {
      if (excludeIds.includes(e.id) || e.hidden) return;
      xs.push(e.x, e.x + e.w / 2, e.x + e.w);
      ys.push(e.y, e.y + e.h / 2, e.y + e.h);
    });
    return { xs, ys };
  }

  function bestSnap(values, targets) {
    let best = null;
    values.forEach((v) => targets.forEach((t) => {
      const d = t - v;
      if (Math.abs(d) <= SNAP / zoom && (!best || Math.abs(d) < Math.abs(best.d))) best = { d, line: t };
    }));
    return best;
  }

  function drawGuides(pageNode, guides) {
    const overlay = pageNode.querySelector('.dc-overlay');
    overlay.querySelectorAll('.dc-guide').forEach((g) => g.remove());
    guides.forEach((g) => {
      const line = document.createElement('div');
      line.className = `dc-guide dc-guide--${g.axis}`;
      if (g.axis === 'x') line.style.left = `${g.pos}px`; else line.style.top = `${g.pos}px`;
      overlay.appendChild(line);
    });
  }

  pagesHost.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const pageNode = e.target.closest('[data-dc-page]');
    if (!pageNode) return;
    // Le cadre de sélection peut être reconstruit pendant ce handler (cible détachée) :
    // on marque l'événement pour que le « clic hors page » du workspace l'ignore.
    e.dcOnPage = true;
    const pageId = pageNode.closest('.dc-page-wrap').dataset.pageId;
    const page = pageById(pageId);
    hideContext();

    const handle = e.target.closest('[data-handle]');
    if (handle) {
      e.preventDefault();
      const el = selectedElements()[0];
      if (!el) return;
      if (handle.dataset.handle === 'rotate') startRotate(e, pageNode, el);
      else startResize(e, pageNode, page, el, handle.dataset.handle);
      return;
    }

    // Le cadre de sélection est saisissable : on déplace l'élément sélectionné même
    // s'il est recouvert par un autre (comme dans Canva).
    const selFrame = e.target.closest('[data-sel-id]');
    const elNode = selFrame ? nodeFor(selFrame.dataset.selId) : e.target.closest('.dc-el');
    if (elNode && editing && editing.id === elNode.dataset.id) return; // sélection de texte native
    if (editing) stopEditing();

    if (!elNode) {
      if (!e.shiftKey) select([], pageId);
      else if (pageId !== selection.pageId) select([], pageId);
      startMarquee(e, pageNode, page, e.shiftKey ? [...selection.ids] : []);
      return;
    }

    e.preventDefault();
    const id = elNode.dataset.id;
    let ids = pageId === selection.pageId ? [...selection.ids] : [];
    if (e.shiftKey) {
      ids = ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
      select(ids, pageId);
      return;
    }
    if (!ids.includes(id)) select([id], pageId);
    startMove(e, pageNode, page);
  });

  function startMove(e, pageNode, page) {
    const els = selectedElements().filter((el) => !el.locked);
    if (!els.length) return;
    const start = pagePoint(pageNode, e);
    const origin = els.map((el) => ({ el, x: el.x, y: el.y }));
    const targets = snapTargets(page, els.map((el) => el.id));
    let moved = false;
    const box0 = bbox(els);

    function onMove(ev) {
      const p = pagePoint(pageNode, ev);
      let dx = p.x - start.x; let dy = p.y - start.y;
      if (!moved && Math.hypot(dx, dy) * zoom < 3) return;
      moved = true;
      interacting = true;
      if (ev.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
      const guides = [];
      if (!ev.altKey) {
        const bx = box0.x + dx; const by = box0.y + dy;
        const sx = bestSnap([bx, bx + box0.w / 2, bx + box0.w], targets.xs);
        const sy = bestSnap([by, by + box0.h / 2, by + box0.h], targets.ys);
        if (sx) { dx += sx.d; guides.push({ axis: 'x', pos: sx.line }); } else if (gridOn) dx = Math.round((box0.x + dx) / GRID) * GRID - box0.x;
        if (sy) { dy += sy.d; guides.push({ axis: 'y', pos: sy.line }); } else if (gridOn) dy = Math.round((box0.y + dy) / GRID) * GRID - box0.y;
      }
      origin.forEach((o) => {
        o.el.x = round(o.x + dx); o.el.y = round(o.y + dy);
        const node = nodeFor(o.el.id);
        if (node) { node.style.left = `${o.el.x}px`; node.style.top = `${o.el.y}px`; }
      });
      renderSelection();
      drawGuides(pageNode, guides);
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      drawGuides(pageNode, []);
      interacting = false;
      renderSelection();
      if (moved) { renderInspector(); commit(); }
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  function startResize(e, pageNode, page, el, dir) {
    const start = pagePoint(pageNode, e);
    const o = { x: el.x, y: el.y, w: el.w, h: el.h };
    const rad = (el.rotation || 0) * Math.PI / 180;
    const cos = Math.cos(rad); const sin = Math.sin(rad);
    const sx = dir.includes('e') ? 1 : dir.includes('w') ? -1 : 0;
    const sy = dir.includes('s') ? 1 : dir.includes('n') ? -1 : 0;
    const corner = sx !== 0 && sy !== 0;
    const isLine = el.type === 'shape' && (el.shape === 'line' || el.shape === 'arrow');
    const minW = 8; const minH = isLine ? 4 : 8;
    const targets = snapTargets(page, [el.id]);
    interacting = true;

    function onMove(ev) {
      const p = pagePoint(pageNode, ev);
      const gdx = p.x - start.x; const gdy = p.y - start.y;
      // Déplacement exprimé dans le repère (éventuellement pivoté) de l'élément.
      const ldx = gdx * cos + gdy * sin;
      const ldy = -gdx * sin + gdy * cos;
      let w = Math.max(minW, o.w + sx * ldx);
      let h = Math.max(minH, o.h + sy * ldy);
      const keepRatio = corner && (el.type === 'image' ? !ev.shiftKey : ev.shiftKey);
      if (keepRatio) {
        const ratio = o.w / o.h;
        if (w / h > ratio) h = w / ratio; else w = h * ratio;
      }
      const guides = [];
      if (!el.rotation && !ev.altKey && !keepRatio) {
        if (sx) {
          const edge = sx > 0 ? o.x + w : o.x + o.w - w;
          const snap = bestSnap([edge], targets.xs);
          if (snap) { w += sx * snap.d; guides.push({ axis: 'x', pos: snap.line }); }
        }
        if (sy) {
          const edge = sy > 0 ? o.y + h : o.y + o.h - h;
          const snap = bestSnap([edge], targets.ys);
          if (snap) { h += sy * snap.d; guides.push({ axis: 'y', pos: snap.line }); }
        }
      }
      // Le bord opposé reste fixe : on recalcule le centre dans le repère global.
      const dcx = sx * (w - o.w) / 2; const dcy = sy * (h - o.h) / 2;
      const cx = o.x + o.w / 2 + dcx * cos - dcy * sin;
      const cy = o.y + o.h / 2 + dcx * sin + dcy * cos;
      el.w = round(w); el.h = round(h); el.x = round(cx - w / 2); el.y = round(cy - h / 2);
      const node = nodeFor(el.id);
      const index = page.elements.indexOf(el);
      if (el.type === 'shape') { node.innerHTML = shapeSvg(el); }
      applyBox(node, el, index);
      if (el.type === 'table') fitTables();
      renderSelection();
      drawGuides(pageNode, guides);
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      drawGuides(pageNode, []);
      interacting = false;
      renderPages();
      renderSelection();
      renderInspector();
      commit();
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  function startRotate(e, pageNode, el) {
    const cx = el.x + el.w / 2; const cy = el.y + el.h / 2;
    interacting = true;
    function onMove(ev) {
      const p = pagePoint(pageNode, ev);
      let angle = Math.atan2(p.y - cy, p.x - cx) * 180 / Math.PI + 90;
      if (angle > 180) angle -= 360;
      if (ev.shiftKey) angle = Math.round(angle / 15) * 15;
      else [0, 90, -90, 180, -180].forEach((a) => { if (Math.abs(angle - a) < 3) angle = a; });
      el.rotation = round(angle === -180 ? 180 : angle);
      const node = nodeFor(el.id);
      node.style.transform = el.rotation ? `rotate(${el.rotation}deg)` : '';
      renderSelection();
      const box = pageNode.querySelector('.dc-sel .dc-size-badge');
      if (box) box.textContent = `${Math.round(el.rotation)}°`;
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      interacting = false;
      renderSelection();
      renderInspector();
      commit();
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  function startMarquee(e, pageNode, page, baseIds) {
    const start = pagePoint(pageNode, e);
    const overlay = pageNode.querySelector('.dc-overlay');
    const rect = document.createElement('div');
    rect.className = 'dc-marquee';
    let active = false;
    function onMove(ev) {
      const p = pagePoint(pageNode, ev);
      const x = Math.min(p.x, start.x); const y = Math.min(p.y, start.y);
      const w = Math.abs(p.x - start.x); const h = Math.abs(p.y - start.y);
      if (!active && w * zoom < 4 && h * zoom < 4) return;
      if (!active) { overlay.appendChild(rect); active = true; }
      Object.assign(rect.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });
      const hits = page.elements.filter((el) => !el.hidden && el.x < x + w && el.x + el.w > x && el.y < y + h && el.y + el.h > y).map((el) => el.id);
      selection.ids = Array.from(new Set([...baseIds, ...hits]));
      renderSelection();
      overlay.appendChild(rect);
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      rect.remove();
      if (active) select(selection.ids, page.id);
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  pagesHost.addEventListener('dblclick', (e) => {
    const selFrame = e.target.closest('[data-sel-id]');
    let elNode = selFrame ? nodeFor(selFrame.dataset.selId) : e.target.closest('.dc-el');
    if (!elNode && selection.ids.length === 1) {
      // Le cadre de sélection est reconstruit entre les deux clics : le dblclick peut
      // alors viser la page. On retrouve l'élément sélectionné par sa position.
      const pageNode = e.target.closest('[data-dc-page]');
      const el = selectedElements()[0];
      if (pageNode && el) {
        const p = pagePoint(pageNode, e);
        if (p.x >= el.x && p.x <= el.x + el.w && p.y >= el.y && p.y <= el.y + el.h) elNode = nodeFor(el.id);
      }
    }
    if (!elNode || (editing && editing.id === elNode.dataset.id)) return;
    startEditing(elNode.dataset.id);
  });

  // Clic sur la barre d'une page : commandes de page.
  pagesHost.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-dc-page-cmd]');
    if (!btn) return;
    const pageId = btn.closest('.dc-page-wrap').dataset.pageId;
    pageCommand(btn.dataset.dcPageCmd, pageId);
  });

  // Bibliothèque : une vignette par forme prête (même tracé que l'élément créé).
  const vecPresetHost = document.querySelector('[data-dc-vec-presets]');
  if (vecPresetHost && V) {
    vecPresetHost.innerHTML = Object.entries(V.PRESETS).map(([key, p]) => {
      const open = p.fill === 'transparent';
      return `<button type="button" class="dc-shape-btn dc-vec-preset" draggable="true" data-dc-preset="vec:${key}" data-tip="${esc(p.label)}"><svg viewBox="-4 -4 108 108"><path d="${p.d}" style="${open ? 'fill:none;stroke-width:7' : 'stroke-width:5'}"/></svg></button>`;
    }).join('');
  }

  // ------------------------------------------------------------- drag & drop depuis la bibliothèque
  $$('[data-dc-preset]').forEach((btn) => {
    btn.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/dc-preset', btn.dataset.dcPreset);
      e.dataTransfer.effectAllowed = 'copy';
    });
    btn.addEventListener('click', () => {
      if (editing) stopEditing();
      const el = makePreset(btn.dataset.dcPreset);
      if (!el) return;
      addElement(el);
      if (el.type === 'image') pickImage(el.id);
    });
  });

  pagesHost.addEventListener('dragover', (e) => {
    if (!e.target.closest('[data-dc-page]')) return;
    const types = Array.from(e.dataTransfer.types || []);
    if (types.includes('text/dc-preset') || types.includes('Files')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; }
  });
  pagesHost.addEventListener('drop', (e) => {
    const pageNode = e.target.closest('[data-dc-page]');
    if (!pageNode) return;
    e.preventDefault();
    const page = pageById(pageNode.closest('.dc-page-wrap').dataset.pageId);
    const at = pagePoint(pageNode, e);
    const preset = e.dataTransfer.getData('text/dc-preset');
    if (preset) {
      const el = makePreset(preset);
      if (!el) return;
      addElement(el, page, at);
      if (el.type === 'image') pickImage(el.id);
      return;
    }
    const svgFile = Array.from(e.dataTransfer.files || []).find((f) => f.type === 'image/svg+xml' || /\.svg$/i.test(f.name));
    if (svgFile) { importSvgFile(svgFile, page, at); return; }
    const file = Array.from(e.dataTransfer.files || []).find((f) => f.type.startsWith('image/'));
    if (file) {
      const el = addElement(makePreset('image'), page, at);
      uploadImage(file, el.id);
    }
  });

  // ------------------------------------------------------------- images
  const imageInput = $('[data-dc-image-input]');
  let imageTarget = null;
  function pickImage(id) { imageTarget = id; imageInput.value = ''; imageInput.click(); }
  imageInput.addEventListener('change', () => {
    const file = imageInput.files && imageInput.files[0];
    if (file && imageTarget) uploadImage(file, imageTarget);
  });

  async function uploadImage(file, id) {
    setStatus('Envoi de l\'image…');
    const body = new FormData();
    body.append('image', file);
    try {
      const res = await fetch(root.dataset.uploadUrl, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body });
      const data = await res.json();
      if (!res.ok || !data.url) throw new Error(data.message || 'upload');
      const found = findElement(id);
      if (!found) return;
      const img = new Image();
      img.onload = () => {
        const { el } = found;
        const ratio = img.naturalWidth / img.naturalHeight;
        if (ratio && isFinite(ratio)) {
          const cx = el.x + el.w / 2; const cy = el.y + el.h / 2;
          el.w = Math.min(Math.max(el.w, 160), pageW - 40);
          el.h = round(el.w / ratio);
          if (el.h > pageH - 40) { el.h = pageH - 40; el.w = round(el.h * ratio); }
          el.x = round(cx - el.w / 2); el.y = round(cy - el.h / 2);
        }
        el.src = data.url;
        renderAll();
        commit();
      };
      img.onerror = () => { found.el.src = data.url; renderAll(); commit(); };
      img.src = data.url;
    } catch (err) {
      setStatus('Échec de l\'envoi de l\'image', true);
    }
  }

  // ------------------------------------------------------------- commandes sur la sélection
  function deleteSelection() {
    const page = currentPage();
    const ids = selection.ids.filter((id) => { const el = page.elements.find((e) => e.id === id); return el && !el.locked; });
    if (!ids.length) return;
    page.elements = page.elements.filter((e) => !ids.includes(e.id));
    selection.ids = selection.ids.filter((id) => !ids.includes(id));
    renderAll();
    commit();
  }

  function duplicateSelection() {
    const page = currentPage();
    const copies = selectedElements().map((el) => Object.assign(clone(el), { id: uid(), x: el.x + 16, y: el.y + 16, locked: false }));
    if (!copies.length) return;
    page.elements.push(...copies);
    selection.ids = copies.map((c) => c.id);
    renderAll();
    commit();
  }

  function copySelection() { clipboard = selectedElements().map(clone); }
  function paste() {
    if (!clipboard.length) return;
    const page = currentPage();
    const copies = clipboard.map((el) => Object.assign(clone(el), { id: uid(), x: el.x + 20, y: el.y + 20 }));
    clipboard = copies.map(clone);
    page.elements.push(...copies);
    selection.ids = copies.map((c) => c.id);
    renderAll();
    commit();
  }

  function reorder(cmd) {
    const page = currentPage();
    const ids = selection.ids;
    if (!ids.length) return;
    const picked = page.elements.filter((e) => ids.includes(e.id));
    const rest = page.elements.filter((e) => !ids.includes(e.id));
    if (cmd === 'front') page.elements = [...rest, ...picked];
    else if (cmd === 'back') page.elements = [...picked, ...rest];
    else {
      const list = page.elements;
      const order = cmd === 'forward' ? [...list.keys()].reverse() : [...list.keys()];
      order.forEach((i) => {
        if (!ids.includes(list[i].id)) return;
        const j = cmd === 'forward' ? i + 1 : i - 1;
        if (j < 0 || j >= list.length || ids.includes(list[j].id)) return;
        [list[i], list[j]] = [list[j], list[i]];
      });
    }
    renderAll();
    commit();
  }

  function toggleLock() {
    const els = selectedElements();
    const lock = !els.every((e) => e.locked);
    els.forEach((e) => { e.locked = lock; });
    renderAll();
    commit();
  }

  function alignSelection(mode) {
    const els = selectedElements().filter((e) => !e.locked);
    if (!els.length) return;
    const ref = els.length > 1 ? bbox(els) : { x: 0, y: 0, w: pageW, h: pageH };
    els.forEach((el) => {
      if (mode === 'left') el.x = ref.x;
      if (mode === 'hcenter') el.x = round(ref.x + ref.w / 2 - el.w / 2);
      if (mode === 'right') el.x = round(ref.x + ref.w - el.w);
      if (mode === 'top') el.y = ref.y;
      if (mode === 'vcenter') el.y = round(ref.y + ref.h / 2 - el.h / 2);
      if (mode === 'bottom') el.y = round(ref.y + ref.h - el.h);
    });
    if (mode === 'hdist' || mode === 'vdist') {
      const horizontal = mode === 'hdist';
      const sorted = [...els].sort((a, b) => (horizontal ? a.x - b.x : a.y - b.y));
      if (sorted.length > 2) {
        const total = sorted.reduce((sum, el) => sum + (horizontal ? el.w : el.h), 0);
        const span = horizontal ? ref.w : ref.h;
        const gap = (span - total) / (sorted.length - 1);
        let cursor = horizontal ? ref.x : ref.y;
        sorted.forEach((el) => {
          if (horizontal) { el.x = round(cursor); cursor += el.w + gap; } else { el.y = round(cursor); cursor += el.h + gap; }
        });
      }
    }
    renderAll();
    commit();
  }

  function nudge(dx, dy) {
    const els = selectedElements().filter((e) => !e.locked);
    if (!els.length) return;
    els.forEach((el) => { el.x = round(el.x + dx); el.y = round(el.y + dy); });
    // Les cotes restent visibles un instant après chaque déplacement au clavier.
    interacting = true;
    renderPages();
    renderSelection();
    renderInspector();
    commit();
    clearTimeout(nudgeTimer);
    nudgeTimer = setTimeout(() => { interacting = false; renderSelection(); }, 900);
  }
  let nudgeTimer = null;

  function runCommand(cmd) {
    if (cmd === 'delete') deleteSelection();
    else if (cmd === 'duplicate') duplicateSelection();
    else if (cmd === 'copy') copySelection();
    else if (cmd === 'paste') paste();
    else if (cmd === 'lock') toggleLock();
    else if (['front', 'back', 'forward', 'backward'].includes(cmd)) reorder(cmd);
  }

  // ------------------------------------------------------------- pages
  function pageCommand(cmd, pageId) {
    if (editing) stopEditing();
    const index = state.pages.findIndex((p) => p.id === pageId);
    if (index === -1) return;
    const page = state.pages[index];
    if (cmd === 'add') {
      const fresh = { id: uid(), background: '#ffffff', elements: [] };
      state.pages.splice(index + 1, 0, fresh);
      selection = { pageId: fresh.id, ids: [] };
    } else if (cmd === 'duplicate') {
      const copy = clone(page);
      copy.id = uid();
      copy.elements.forEach((el) => { el.id = uid(); });
      state.pages.splice(index + 1, 0, copy);
      selection = { pageId: copy.id, ids: [] };
    } else if (cmd === 'delete') {
      if (state.pages.length === 1) { alert('Le document doit contenir au moins une page.'); return; }
      if (page.elements.length && !confirm('Supprimer cette page et tout son contenu ?')) return;
      state.pages.splice(index, 1);
      selection = { pageId: state.pages[Math.max(0, index - 1)].id, ids: [] };
    } else if (cmd === 'up' && index > 0) {
      [state.pages[index - 1], state.pages[index]] = [state.pages[index], state.pages[index - 1]];
    } else if (cmd === 'down' && index < state.pages.length - 1) {
      [state.pages[index + 1], state.pages[index]] = [state.pages[index], state.pages[index + 1]];
    } else if (cmd === 'goto') {
      selection = { pageId, ids: [] };
      renderAll();
      scrollToPage(pageId);
      return;
    } else {
      return;
    }
    renderAll();
    commit();
    if (cmd === 'add' || cmd === 'duplicate') scrollToPage(selection.pageId);
  }

  function scrollToPage(pageId) {
    const wrap = pagesHost.querySelector(`.dc-page-wrap[data-page-id="${pageId}"]`);
    if (wrap) wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  $('[data-dc-add-page]').addEventListener('click', () => pageCommand('add', state.pages[state.pages.length - 1].id));

  // ------------------------------------------------------------- tracés vectoriels (plume, points, tangentes)
  // Données : DcVector (document-canvas-vector.js). Deux modes exclusifs de l'édition de texte :
  //  - pen   : la plume pose des points (clic) et tire leurs tangentes (glisser) ;
  //  - vedit : un tracé existant expose ses points et poignées, déplaçables.
  const vecHint = document.createElement('div');
  vecHint.className = 'dc-vec-hint';
  vecHint.hidden = true;
  workspace.appendChild(vecHint);
  function showVecHint(html) { vecHint.innerHTML = html; vecHint.hidden = !html; }

  function vecLayer(pageId) {
    const page = pagesHost.querySelector(`.dc-page-wrap[data-page-id="${pageId}"] [data-dc-page]`);
    if (!page) return null;
    let layer = page.querySelector('.dc-vec-layer');
    if (!layer) {
      layer = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      layer.setAttribute('class', 'dc-vec-layer');
      page.appendChild(layer);
    }
    layer.setAttribute('width', pageW); layer.setAttribute('height', pageH);
    return layer;
  }
  function clearVecLayers() { $$('.dc-vec-layer', pagesHost).forEach((l) => { l.innerHTML = ''; }); }
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  // Contraint un point à des angles de 45° autour d'une origine (Maj).
  function constrain(origin, p) {
    const ang = Math.round(Math.atan2(p.y - origin.y, p.x - origin.x) / (Math.PI / 4)) * (Math.PI / 4);
    const len = dist(origin, p);
    return { x: origin.x + Math.cos(ang) * len, y: origin.y + Math.sin(ang) * len };
  }

  // Élément « tracé » à partir de sous-tracés en coordonnées de page.
  function pathElement(paths, style, name = '') {
    const b = V.bounds(paths);
    const w = Math.max(1, b.w); const h = Math.max(1, b.h);
    return {
      id: uid(), name, type: 'shape', shape: 'path', rotation: 0, locked: false, hidden: false,
      x: round(b.x), y: round(b.y), w: round(w), h: round(h),
      paths: V.toStored(V.translate(paths, -b.x, -b.y), w, h), style,
    };
  }

  // Forme prête : tracé de la bibliothèque (boîte 100 × 100) mis à la taille voulue.
  function vectorPreset(key) {
    const preset = V.PRESETS[key];
    if (!preset) return null;
    let paths = V.parseD(preset.d);
    const b = V.bounds(paths);
    const targetW = preset.w || 160;
    const targetH = preset.h || Math.round((160 * b.h) / Math.max(1, b.w));
    paths = V.mapPaths(paths, (x, y) => [((x - b.x) / Math.max(1, b.w)) * targetW, ((y - b.y) / Math.max(1, b.h)) * targetH]);
    const style = shapeStyle({
      fill: preset.fill || '#ede9fe', strokeWidth: preset.strokeWidth || 0, strokeColor: preset.stroke || '#6d28d9',
    });
    return Object.assign(pathElement(paths, style, preset.label), { x: 0, y: 0 });
  }

  // ---------------------------------------------------------- plume
  function startPen() {
    if (editing) stopEditing();
    if (vedit) stopVectorEdit();
    pen = { pageId: selection.pageId, nodes: [], cursor: null };
    root.classList.add('is-pen');
    showVecHint('<b>Plume</b> · clic : point · glisser : tangentes · Maj : angles à 45° · clic sur le 1<sup>er</sup> point : fermer · <kbd>Entrée</kbd> terminer · <kbd>Retour</kbd> annuler le dernier point · <kbd>Échap</kbd> quitter');
    updateToolbar();
  }
  function cancelPen() {
    pen = null;
    root.classList.remove('is-pen');
    showVecHint('');
    clearVecLayers();
    updateToolbar();
  }
  function finishPen(closed = false) {
    if (!pen) return;
    const nodes = pen.nodes;
    const page = pageById(pen.pageId);
    cancelPen();
    if (nodes.length < 2 || !page) return;
    const style = shapeStyle(closed
      ? { fill: '#ede9fe', strokeWidth: 2, strokeColor: '#6d28d9' }
      : { fill: 'transparent', strokeWidth: 3, strokeColor: '#111827' });
    const el = pathElement([{ closed, nodes }], style);
    el._anchor = true;
    addElement(el, page);
  }
  function drawPen() {
    clearVecLayers();
    if (!pen) return;
    const layer = vecLayer(pen.pageId);
    if (!layer) return;
    const z = 1 / zoom;
    let html = '';
    if (pen.nodes.length) {
      html += `<path class="dc-vec-preview" d="${V.toD([{ closed: false, nodes: pen.nodes }])}" style="stroke-width:${1.5 * z}"/>`;
      const last = pen.nodes[pen.nodes.length - 1];
      if (pen.cursor && !pen.dragging) {
        const c = pen.cursor;
        html += `<path class="dc-vec-rubber" d="M${last.x} ${last.y}C${last.ox} ${last.oy} ${c.x} ${c.y} ${c.x} ${c.y}" style="stroke-width:${z};stroke-dasharray:${4 * z} ${3 * z}"/>`;
      }
      pen.nodes.forEach((n, i) => {
        if (n.smooth) {
          html += `<line class="dc-vec-hline" x1="${n.ix}" y1="${n.iy}" x2="${n.ox}" y2="${n.oy}" style="stroke-width:${z}"/>`;
          [[n.ix, n.iy], [n.ox, n.oy]].forEach(([x, y]) => { html += `<circle class="dc-vec-handle" cx="${x}" cy="${y}" r="${3 * z}" style="stroke-width:${z}"/>`; });
        }
        const s = (i === 0 ? 5 : 4) * z;
        const closing = i === 0 && pen.nodes.length > 1 && pen.cursor && dist(pen.cursor, n) <= 8 * z;
        html += `<rect class="dc-vec-anchor${i === 0 ? ' is-first' : ''}${closing ? ' is-hot' : ''}" x="${n.x - s}" y="${n.y - s}" width="${2 * s}" height="${2 * s}" style="stroke-width:${1.2 * z}"/>`;
      });
    }
    layer.innerHTML = html;
  }
  function penDown(e, pageNode, pageId) {
    if (pen.nodes.length && pageId !== pen.pageId) return;
    pen.pageId = pageId;
    let p = pagePoint(pageNode, e);
    const z = 1 / zoom;
    const last = pen.nodes[pen.nodes.length - 1];
    if (pen.nodes.length >= 2 && dist(p, pen.nodes[0]) <= 8 * z) { finishPen(true); return; }
    if (last && dist(p, last) <= 3 * z) { finishPen(false); return; } // double-clic : terminer
    if (last && e.shiftKey) p = constrain(last, p);
    const n = V.node(round(p.x), round(p.y));
    pen.nodes.push(n);
    pen.dragging = true;
    const move = (ev) => {
      let q = pagePoint(pageNode, ev);
      if (ev.shiftKey) q = constrain(n, q);
      if (dist(q, n) < 3 * z) return;
      n.ox = q.x; n.oy = q.y; n.ix = 2 * n.x - q.x; n.iy = 2 * n.y - q.y; n.smooth = true;
      drawPen();
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (pen) { pen.dragging = false; drawPen(); }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    drawPen();
  }

  // ---------------------------------------------------------- édition des points
  function startVectorEdit(id) {
    const found = findElement(id);
    if (!found || found.el.locked || found.el.type !== 'shape' || found.el.shape !== 'path') return;
    if (editing) stopEditing();
    if (pen) cancelPen();
    const { el, page } = found;
    if (page.id !== selection.pageId || selection.ids.length !== 1 || selection.ids[0] !== id) select([id], page.id);
    vedit = { id, paths: V.fromStored(el.paths, el.w, el.h), sel: null };
    showVecHint('<b>Points</b> · glisser : déplacer · double-clic sur un point : angle ⇄ courbe · clic sur le trait : ajouter un point · <kbd>Alt</kbd> : tangentes indépendantes · <kbd>Suppr</kbd> retirer · <kbd>Échap</kbd> terminer');
    renderSelection();
    renderInspector();
    updateToolbar();
  }
  function stopVectorEdit() {
    if (!vedit) return;
    const found = findElement(vedit.id);
    const paths = vedit.paths;
    vedit = null;
    showVecHint('');
    clearVecLayers();
    if (found) {
      // La boîte de l'élément épouse à nouveau le tracé (même rendu, centre recalé si pivoté).
      const { el } = found;
      const b = V.bounds(paths);
      const w = Math.max(1, b.w); const h = Math.max(1, b.h);
      const r = ((el.rotation || 0) * Math.PI) / 180;
      const dx = b.x + w / 2 - el.w / 2; const dy = b.y + h / 2 - el.h / 2;
      const cx = el.x + el.w / 2 + dx * Math.cos(r) - dy * Math.sin(r);
      const cy = el.y + el.h / 2 + dx * Math.sin(r) + dy * Math.cos(r);
      el.paths = V.toStored(V.translate(paths, -b.x, -b.y), w, h);
      el.w = round(w); el.h = round(h); el.x = round(cx - w / 2); el.y = round(cy - h / 2);
    }
    renderPages();
    renderSelection();
    renderInspector();
    updateToolbar();
    commit();
  }
  function veditElement() { const f = vedit && findElement(vedit.id); return f ? f.el : null; }
  // Applique les points en cours d'édition à l'élément (boîte inchangée pendant l'édition).
  function veditApply() {
    const el = veditElement();
    if (!el) return;
    el.paths = V.toStored(vedit.paths, el.w, el.h);
    const node = nodeFor(el.id);
    if (node) node.innerHTML = shapeSvg(el);
    drawVectorEdit();
  }
  function localPoint(pageNode, e, el) {
    const p = pagePoint(pageNode, e);
    const r = (-(el.rotation || 0) * Math.PI) / 180;
    const cx = el.x + el.w / 2; const cy = el.y + el.h / 2;
    const dx = p.x - cx; const dy = p.y - cy;
    return { x: dx * Math.cos(r) - dy * Math.sin(r) + el.w / 2, y: dx * Math.sin(r) + dy * Math.cos(r) + el.h / 2 };
  }
  function drawVectorEdit() {
    clearVecLayers();
    const el = veditElement();
    if (!el) return;
    const found = findElement(el.id);
    const layer = vecLayer(found.page.id);
    if (!layer) return;
    const z = 1 / zoom;
    const sel = vedit.sel;
    let html = `<g transform="translate(${el.x} ${el.y}) rotate(${el.rotation || 0} ${el.w / 2} ${el.h / 2})">`;
    vedit.paths.forEach((p, pi) => {
      V.segments(p).forEach((sg, si) => {
        const [a, b, c, d] = sg.pts;
        html += `<path class="dc-vec-seg" data-vseg="${pi}:${si}" d="M${a[0]} ${a[1]}C${b[0]} ${b[1]} ${c[0]} ${c[1]} ${d[0]} ${d[1]}" style="stroke-width:${10 * z}"/>`;
      });
      html += `<path class="dc-vec-outline" d="${V.toD([p])}" style="stroke-width:${z}"/>`;
    });
    // Poignées : point sélectionné et ses voisins (comme dans Illustrator / Figma).
    const shown = new Set();
    if (sel) {
      const p = vedit.paths[sel.pi]; const n = p.nodes.length;
      [sel.ni - 1, sel.ni, sel.ni + 1].forEach((i) => { if (p.closed || (i >= 0 && i < n)) shown.add(`${sel.pi}:${(i + n) % n}`); });
    }
    vedit.paths.forEach((p, pi) => p.nodes.forEach((nd, ni) => {
      if (!shown.has(`${pi}:${ni}`)) return;
      [['in', nd.ix, nd.iy], ['out', nd.ox, nd.oy]].forEach(([side, x, y]) => {
        if (Math.abs(x - nd.x) < 0.01 && Math.abs(y - nd.y) < 0.01) return;
        html += `<line class="dc-vec-hline" x1="${nd.x}" y1="${nd.y}" x2="${x}" y2="${y}" style="stroke-width:${z}"/>`;
        html += `<circle class="dc-vec-handle" cx="${x}" cy="${y}" r="${4 * z}" style="stroke-width:${1.2 * z}"/>`;
        html += `<circle class="dc-vec-hit is-live" data-vh="${pi}:${ni}:${side}" cx="${x}" cy="${y}" r="${9 * z}"/>`;
      });
    }));
    vedit.paths.forEach((p, pi) => p.nodes.forEach((nd, ni) => {
      const active = sel && sel.pi === pi && sel.ni === ni;
      const s = 4.5 * z;
      // Zone de saisie large et invisible : le point reste facile à attraper.
      html += `<circle class="dc-vec-hit is-live" data-vnode="${pi}:${ni}" cx="${nd.x}" cy="${nd.y}" r="${10 * z}"/>`;
      html += nd.smooth
        ? `<circle class="dc-vec-anchor is-live${active ? ' is-active' : ''}" data-vnode="${pi}:${ni}" cx="${nd.x}" cy="${nd.y}" r="${s}" style="stroke-width:${1.3 * z}"/>`
        : `<rect class="dc-vec-anchor is-live${active ? ' is-active' : ''}" data-vnode="${pi}:${ni}" x="${nd.x - s}" y="${nd.y - s}" width="${2 * s}" height="${2 * s}" style="stroke-width:${1.3 * z}"/>`;
    }));
    layer.innerHTML = `${html}</g>`;
  }
  function vecDrag(e, pageNode, onPoint) {
    const el = veditElement();
    const move = (ev) => { onPoint(localPoint(pageNode, ev, el), ev); veditApply(); };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      commit();
      renderInspector();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }
  function veditDown(e, pageNode) {
    const el = veditElement();
    const t = e.target;
    const hv = t.closest && t.closest('[data-vh]');
    const nv = t.closest && t.closest('[data-vnode]');
    const sv = t.closest && t.closest('[data-vseg]');
    if (hv) {
      const [pi, ni, side] = hv.dataset.vh.split(':');
      const nd = vedit.paths[+pi].nodes[+ni];
      vedit.sel = { pi: +pi, ni: +ni };
      const other = side === 'in' ? 'o' : 'i';
      const own = side === 'in' ? 'i' : 'o';
      vecDrag(e, pageNode, (q, ev) => {
        if (ev.shiftKey) q = constrain(nd, q);
        nd[`${own}x`] = q.x; nd[`${own}y`] = q.y;
        if (ev.altKey) nd.smooth = false;
        if (nd.smooth) {
          // Tangentes alignées : l'autre poignée garde sa longueur, dans le prolongement.
          const len = Math.hypot(nd[`${other}x`] - nd.x, nd[`${other}y`] - nd.y) || Math.hypot(q.x - nd.x, q.y - nd.y);
          const dl = Math.hypot(q.x - nd.x, q.y - nd.y) || 1;
          nd[`${other}x`] = nd.x - ((q.x - nd.x) / dl) * len; nd[`${other}y`] = nd.y - ((q.y - nd.y) / dl) * len;
        }
      });
      return true;
    }
    if (nv) {
      const [pi, ni] = nv.dataset.vnode.split(':').map(Number);
      vedit.sel = { pi, ni };
      const nd = vedit.paths[pi].nodes[ni];
      const start = localPoint(pageNode, e, el);
      const orig = { ...nd };
      drawVectorEdit(); renderInspector();
      vecDrag(e, pageNode, (q, ev) => {
        let dx = q.x - start.x; let dy = q.y - start.y;
        if (ev.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
        Object.assign(nd, { x: orig.x + dx, y: orig.y + dy, ix: orig.ix + dx, iy: orig.iy + dy, ox: orig.ox + dx, oy: orig.oy + dy });
      });
      return true;
    }
    if (sv) {
      // Clic sur le trait : nouveau point à cet endroit, sans changer la courbe.
      const [pi, si] = sv.dataset.vseg.split(':').map(Number);
      const p = vedit.paths[pi];
      const sg = V.segments(p)[si];
      const q = localPoint(pageNode, e, el);
      const { t: tt } = V.nearestT(sg.pts, q.x, q.y);
      const cut = V.split(sg.pts, Math.min(0.98, Math.max(0.02, tt)));
      const a = p.nodes[sg.i]; const b = p.nodes[sg.j];
      a.ox = cut.prevOut[0]; a.oy = cut.prevOut[1];
      b.ix = cut.nextIn[0]; b.iy = cut.nextIn[1];
      const nd = { x: cut.node[0], y: cut.node[1], ix: cut.nodeIn[0], iy: cut.nodeIn[1], ox: cut.nodeOut[0], oy: cut.nodeOut[1], smooth: true };
      p.nodes.splice(sg.i + 1, 0, nd);
      vedit.sel = { pi, ni: sg.i + 1 };
      veditApply(); commit(); renderInspector();
      return true;
    }
    if (nodeFor(vedit.id) && nodeFor(vedit.id).contains(t)) { vedit.sel = null; drawVectorEdit(); renderInspector(); return true; }
    return false;
  }
  function vecCommand(cmd) {
    const el = selectedElements()[0];
    if (!el || el.type !== 'shape') return;
    if (cmd === 'edit') { startVectorEdit(el.id); return; }
    if (cmd === 'done') { stopVectorEdit(); return; }
    if (cmd === 'convert') {
      const paths = V.shapeToPaths(el.shape, el.w, el.h, el.style.radius || 0);
      if (!paths.length) return;
      if (el.shape === 'line' || el.shape === 'arrow') el.style.fill = 'transparent';
      el.shape = 'path';
      el.paths = V.toStored(paths, el.w, el.h);
      renderPages(); commit();
      startVectorEdit(el.id);
      return;
    }
    const editingThis = vedit && vedit.id === el.id;
    const paths = editingThis ? vedit.paths : V.fromStored(el.paths, el.w, el.h);
    const sel = editingThis ? vedit.sel : null;
    if (cmd === 'close') { const close = !paths.every((p) => p.closed); paths.forEach((p) => { p.closed = close; }); }
    if (cmd === 'smooth-all') paths.forEach((p) => p.nodes.forEach((_, i) => V.smoothNode(p, i)));
    if (cmd === 'corner-all') paths.forEach((p) => p.nodes.forEach(V.cornerNode));
    if (sel && (cmd === 'smooth' || cmd === 'corner')) {
      const p = paths[sel.pi];
      if (cmd === 'smooth') V.smoothNode(p, sel.ni); else V.cornerNode(p.nodes[sel.ni]);
    }
    if (sel && cmd === 'delete-node') deleteVecNode();
    if (editingThis) { veditApply(); commit(); renderInspector(); return; }
    el.paths = V.toStored(paths, el.w, el.h);
    renderPages(); renderSelection(); renderInspector(); commit();
  }
  function deleteVecNode() {
    if (!vedit || !vedit.sel) return;
    const { pi, ni } = vedit.sel;
    const p = vedit.paths[pi];
    if (p.nodes.length > 2) p.nodes.splice(ni, 1);
    else if (vedit.paths.length > 1) vedit.paths.splice(pi, 1);
    else return;
    vedit.sel = null;
    veditApply(); commit(); renderInspector();
  }
  function toggleVecNode(pi, ni) {
    const p = vedit.paths[pi];
    const nd = p.nodes[ni];
    if (nd.smooth) V.cornerNode(nd); else V.smoothNode(p, ni);
    vedit.sel = { pi, ni };
    veditApply(); commit(); renderInspector();
  }

  // Interactions prioritaires (phase de capture) : plume et points passent avant la sélection.
  pagesHost.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || (!pen && !vedit)) return;
    const pageNode = e.target.closest('[data-dc-page]');
    if (!pageNode) return;
    const pageId = pageNode.closest('.dc-page-wrap').dataset.pageId;
    if (pen) {
      e.preventDefault(); e.stopPropagation();
      penDown(e, pageNode, pageId);
      return;
    }
    if (veditDown(e, pageNode)) { e.preventDefault(); e.stopPropagation(); return; }
    stopVectorEdit(); // clic ailleurs : fin de l'édition, puis sélection normale
  }, true);
  pagesHost.addEventListener('pointermove', (e) => {
    if (!pen || pen.dragging) return;
    const pageNode = e.target.closest('[data-dc-page]');
    if (!pageNode || pageNode.closest('.dc-page-wrap').dataset.pageId !== pen.pageId) return;
    pen.cursor = pagePoint(pageNode, e);
    if (e.shiftKey && pen.nodes.length) pen.cursor = constrain(pen.nodes[pen.nodes.length - 1], pen.cursor);
    drawPen();
  });
  pagesHost.addEventListener('dblclick', (e) => {
    if (pen) { e.stopPropagation(); return; }
    if (!vedit) return;
    const nv = e.target.closest && e.target.closest('[data-vnode]');
    e.stopPropagation();
    if (nv) { const [pi, ni] = nv.dataset.vnode.split(':').map(Number); toggleVecNode(pi, ni); }
  }, true);

  // Clavier des modes vectoriels ; renvoie true si la touche est consommée.
  function vecKey(e) {
    if (pen) {
      if (e.key === 'Enter') { e.preventDefault(); finishPen(false); return true; }
      if (e.key === 'Escape') { e.preventDefault(); if (pen.nodes.length >= 2) finishPen(false); else cancelPen(); return true; }
      if (e.key === 'Backspace' || e.key === 'Delete') { e.preventDefault(); pen.nodes.pop(); drawPen(); return true; }
      if (e.key.toLowerCase() === 'p' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); cancelPen(); return true; }
      return true;
    }
    if (!vedit) return false;
    const mod = e.ctrlKey || e.metaKey;
    if (e.key === 'Escape' || e.key === 'Enter') { e.preventDefault(); stopVectorEdit(); return true; }
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteVecNode(); return true; }
    if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); stopVectorEdit(); if (e.shiftKey) redo(); else undo(); return true; }
    const step = e.shiftKey ? 10 : 1;
    const arrows = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (arrows[e.key] && vedit.sel) {
      e.preventDefault();
      const nd = vedit.paths[vedit.sel.pi].nodes[vedit.sel.ni];
      const [dx, dy] = arrows[e.key];
      ['x', 'ix', 'ox'].forEach((k) => { nd[k] += dx; });
      ['y', 'iy', 'oy'].forEach((k) => { nd[k] += dy; });
      veditApply(); commit();
      return true;
    }
    return true; // pas de raccourcis du canvas pendant l'édition des points
  }

  // Inspecteur : section « Tracé » et options de remplissage communes aux formes.
  function pathInspector(el) {
    const editingThis = vedit && vedit.id === el.id;
    const paths = editingThis ? vedit.paths : V.fromStored(el.paths, el.w, el.h);
    const count = paths.reduce((a, p) => a + p.nodes.length, 0);
    const allClosed = paths.every((p) => p.closed);
    const sel = editingThis && vedit.sel ? vedit.paths[vedit.sel.pi].nodes[vedit.sel.ni] : null;
    return section('Tracé', `
      <button type="button" class="dc-btn dc-btn--block${editingThis ? ' dc-btn--primary' : ''}" data-vec="${editingThis ? 'done' : 'edit'}"><i data-lucide="${editingThis ? 'check' : 'spline'}" class="w-3.5 h-3.5"></i> ${editingThis ? 'Terminer la modification' : 'Modifier les points et tangentes'}</button>
      ${editingThis ? `<p class="dc-note">Glissez un point ou une poignée. Double-clic sur un point : angle ⇄ courbe. Clic sur le trait : nouveau point. <kbd>Alt</kbd> : tangentes indépendantes.</p>` : ''}
      ${sel ? `<div class="dc-field"><span>Point sélectionné</span><div class="dc-seg dc-seg--text">
        <button type="button" class="${sel.smooth ? '' : 'is-active'}" data-vec="corner"><i data-lucide="corner-down-right" class="w-3.5 h-3.5"></i> Angle</button>
        <button type="button" class="${sel.smooth ? 'is-active' : ''}" data-vec="smooth"><i data-lucide="spline" class="w-3.5 h-3.5"></i> Courbe</button>
        <button type="button" data-vec="delete-node" data-tip="Supprimer le point"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button></div></div>` : ''}
      <div class="dc-grid-2">
        <button type="button" class="dc-btn" data-vec="smooth-all"><i data-lucide="waves" class="w-3.5 h-3.5"></i> Tout lisser</button>
        <button type="button" class="dc-btn" data-vec="corner-all"><i data-lucide="triangle" class="w-3.5 h-3.5"></i> Angles vifs</button>
      </div>
      <button type="button" class="dc-btn dc-btn--block" data-vec="close"><i data-lucide="${allClosed ? 'unlink' : 'link'}" class="w-3.5 h-3.5"></i> ${allClosed ? 'Ouvrir le tracé' : 'Fermer le tracé'}</button>
      <p class="dc-note"><span>${count} point${count > 1 ? 's' : ''}</span>${paths.length > 1 ? ` <span>· ${paths.length} sous-tracés</span>` : ''}</p>
    `);
  }
  function gradientFields(s) {
    if (!s.fill2) return `<button type="button" class="dc-btn dc-btn--block" data-set-prop="style.fill2" data-value="${s.fill === '#6d28d9' ? '#2563eb' : '#6d28d9'}"><i data-lucide="blend" class="w-3.5 h-3.5"></i> Ajouter un dégradé</button>`;
    return `${color('Couleur de fin du dégradé', 'style.fill2', s.fill2)}
      ${range('Direction du dégradé', 'style.gradientAngle', s.gradientAngle || 0, 0, 360, 15, (v) => `${v}°`)}
      <button type="button" class="dc-btn dc-btn--block" data-set-prop="style.fill2" data-value=""><i data-lucide="x" class="w-3.5 h-3.5"></i> Retirer le dégradé</button>`;
  }

  // Import d'un fichier SVG : chaque forme devient un tracé modifiable, avec ses couleurs.
  const svgInput = $('[data-dc-svg-input]');
  let svgDropAt = null;
  async function importSvgFile(file, page, at) {
    page = page || currentPage();
    const room = 200 - page.elements.length;
    if (room <= 0) { setStatus('Page pleine : 200 éléments au maximum.', true); return; }
    let shapes;
    try {
      shapes = V.importSvg(await file.text(), { maxShapes: room });
    } catch (err) {
      setStatus(err.message || 'SVG illisible.', true);
      return;
    }
    if (!shapes.length) { setStatus('Aucune forme vectorielle trouvée dans ce fichier.', true); return; }
    const all = V.bounds(shapes.flatMap((s) => s.paths));
    // Mise à l'échelle : tient dans 80 % de la page, et pas minuscule.
    let k = Math.min(1, (pageW * 0.8) / Math.max(1, all.w), (pageH * 0.6) / Math.max(1, all.h));
    if (Math.max(all.w, all.h) * k < 120) k = 120 / Math.max(1, all.w, all.h);
    const center = at || visiblePageCenter(page);
    const ox = center.x - (all.w * k) / 2; const oy = center.y - (all.h * k) / 2;
    const name = file.name.replace(/\.svg$/i, '').slice(0, 40);
    const ids = shapes.map((s, i) => {
      const paths = V.mapPaths(s.paths, (x, y) => [ox + (x - all.x) * k, oy + (y - all.y) * k]);
      const style = shapeStyle(Object.assign({}, s.style, { strokeWidth: Math.round(s.style.strokeWidth * k * 100) / 100 }));
      const el = pathElement(paths, style, shapes.length > 1 ? `${name} ${i + 1}` : name);
      page.elements.push(el);
      return el.id;
    });
    selection.pageId = page.id;
    renderPages();
    select(ids, page.id);
    commit();
    setStatus(`${ids.length} forme${ids.length > 1 ? 's' : ''} importée${ids.length > 1 ? 's' : ''} — double-cliquez une forme pour modifier ses points.`);
  }
  if (svgInput) {
    svgInput.addEventListener('change', () => {
      const file = svgInput.files && svgInput.files[0];
      if (file) importSvgFile(file, null, svgDropAt);
      svgDropAt = null;
    });
  }
  $$('[data-dc-tool]').forEach((btn) => btn.addEventListener('click', () => {
    if (btn.dataset.dcTool === 'pen') { if (pen) cancelPen(); else startPen(); }
    if (btn.dataset.dcTool === 'svg') { svgInput.value = ''; svgInput.click(); }
  }));

  // ------------------------------------------------------------- inspecteur
  const inspector = $('[data-dc-inspector]');

  function opts(list, value) {
    return list.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(value) ? ' selected' : ''}>${esc(l)}</option>`).join('');
  }
  function num(label, prop, value, { min = '', max = '', step = 1, suffix = '', length = false } = {}) {
    // `length` : valeur stockée en px, affichée/saisie dans l'unité choisie (mm ou px).
    if (length) {
      const shown = unit === 'mm' ? Math.round(toUnit(value) * 10) / 10 : Math.round(value);
      const lo = min === '' ? '' : Math.round(toUnit(min) * 10) / 10;
      return `<label class="dc-field dc-field--num"><span>${label}</span><span class="dc-num"><input type="number" data-prop="${prop}" data-kind="num" data-length="1" value="${shown}" min="${lo}" step="${unit === 'mm' ? 0.5 : 1}"><em>${unit}</em></span></label>`;
    }
    return `<label class="dc-field dc-field--num"><span>${label}</span><span class="dc-num"><input type="number" data-prop="${prop}" data-kind="num" value="${round(value)}" min="${min}" max="${max}" step="${step}">${suffix ? `<em>${suffix}</em>` : ''}</span></label>`;
  }
  function range(label, prop, value, min, max, step, fmt) {
    return `<label class="dc-field"><span class="dc-field-row"><span>${label}</span><output>${fmt ? fmt(value) : value}</output></span><input type="range" data-prop="${prop}" data-kind="num" min="${min}" max="${max}" step="${step}" value="${value}"></label>`;
  }
  function color(label, prop, value, { allowNone = false } = {}) {
    const none = value === 'transparent';
    const hex = /^#[0-9a-f]{6}$/i.test(value) ? value : (/^#[0-9a-f]{3}$/i.test(value) ? `#${value[1]}${value[1]}${value[2]}${value[2]}${value[3]}${value[3]}` : '#ffffff');
    const swatches = SWATCHES.map((c) => `<button type="button" class="dc-swatch" style="background:${c}" data-set-prop="${prop}" data-value="${c}" title="${c}"></button>`).join('');
    return `<div class="dc-field"><span class="dc-field-row"><span>${label}</span>${allowNone ? `<button type="button" class="dc-none-btn${none ? ' is-active' : ''}" data-set-prop="${prop}" data-value="transparent" title="Aucun">Aucun</button>` : ''}</span>
      <div class="dc-color-row"><label class="dc-color-input${none ? ' is-none' : ''}"><input type="color" data-prop="${prop}" data-kind="str" value="${hex}"><span>${none ? '—' : esc(value)}</span></label><div class="dc-swatches">${swatches}</div></div></div>`;
  }
  function select_(label, prop, list, value) {
    return `<label class="dc-field"><span>${label}</span><select data-prop="${prop}" data-kind="str">${opts(list, value)}</select></label>`;
  }
  function segmented(prop, list, value, kind = 'str') {
    return `<div class="dc-seg">${list.map(([v, icon, title]) => `<button type="button" class="${String(v) === String(value) ? 'is-active' : ''}" data-set-prop="${prop}" data-value="${v}" data-kind="${kind}" data-tip="${title}"><i data-lucide="${icon}" class="w-3.5 h-3.5"></i></button>`).join('')}</div>`;
  }
  function toggle(prop, value, icon, title) {
    return `<button type="button" class="dc-toggle${value ? ' is-active' : ''}" data-set-prop="${prop}" data-value="${value ? 'false' : 'true'}" data-kind="bool" data-tip="${title}"><i data-lucide="${icon}" class="w-3.5 h-3.5"></i></button>`;
  }
  const section = (title, body, open = true) => `<details class="dc-section"${open ? ' open' : ''}><summary>${title}</summary><div class="dc-section-body">${body}</div></details>`;

  const FONT_LABELS = {
    'Inter, sans-serif': 'Inter', 'Manrope, sans-serif': 'Manrope', 'Newsreader, serif': 'Newsreader',
    'Arial, sans-serif': 'Arial', 'Helvetica, Arial, sans-serif': 'Helvetica', 'Verdana, sans-serif': 'Verdana',
    'Georgia, serif': 'Georgia', "'Times New Roman', serif": 'Times New Roman', "'Courier New', monospace": 'Courier New',
    "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Helvetica, Arial, sans-serif": 'Apple (SF Pro)',
  };
  const fontList = () => cfg.fonts.map((f) => [f, FONT_LABELS[f] || f]);
  const WEIGHTS = [[300, 'Light'], [400, 'Regular'], [500, 'Medium'], [600, 'Semibold'], [700, 'Bold'], [800, 'Extra-bold']];
  const SHADOW_LIST = [['none', 'Aucune'], ['sm', 'Légère'], ['md', 'Moyenne'], ['lg', 'Forte']];
  const BORDER_LIST = [['solid', 'Continue'], ['dashed', 'Tirets'], ['dotted', 'Pointillés'], ['double', 'Double']];

  function typographySection(s) {
    return section('Typographie', `
      ${select_('Police', 'style.fontFamily', fontList(), s.fontFamily)}
      <div class="dc-grid-2">${num('Taille', 'style.fontSize', s.fontSize, { min: 6, max: 200, suffix: 'px' })}${select_('Graisse', 'style.fontWeight', WEIGHTS, s.fontWeight)}</div>
      ${color('Couleur', 'style.color', s.color)}
      <div class="dc-field"><span>Alignement</span><div class="dc-seg-row">
        ${segmented('style.align', [['left', 'align-left', 'Gauche'], ['center', 'align-center', 'Centre'], ['right', 'align-right', 'Droite'], ['justify', 'align-justify', 'Justifié']], s.align)}
        <span class="dc-toggles">${toggle('style.italic', s.italic, 'italic', 'Italique')}${toggle('style.underline', s.underline, 'underline', 'Souligné')}${toggle('style.uppercase', s.uppercase, 'case-upper', 'Majuscules')}</span>
      </div></div>
      ${s.valign !== undefined && !('headerBg' in s) ? `<div class="dc-field"><span>Position verticale</span>${segmented('style.valign', [['top', 'align-vertical-justify-start', 'Haut'], ['middle', 'align-vertical-justify-center', 'Milieu'], ['bottom', 'align-vertical-justify-end', 'Bas']], s.valign)}</div>` : ''}
      ${range('Interligne', 'style.lineHeight', s.lineHeight, 0.8, 3, 0.05, (v) => Number(v).toFixed(2))}
      ${range('Espacement des lettres', 'style.letterSpacing', s.letterSpacing, -2, 20, 0.5, (v) => `${v}px`)}
    `);
  }

  function boxSection(s, { padding = true } = {}) {
    return section('Fond & bordure', `
      ${color('Fond', 'style.background', s.background, { allowNone: true })}
      ${padding ? range('Marge intérieure', 'style.padding', s.padding, 0, 80, 1, (v) => `${v}px`) : ''}
      <div class="dc-grid-2">${num('Bordure', 'style.borderWidth', s.borderWidth, { min: 0, max: 40, suffix: 'px' })}${select_('Style', 'style.borderStyle', BORDER_LIST, s.borderStyle)}</div>
      ${s.borderWidth ? color('Couleur de bordure', 'style.borderColor', s.borderColor) : ''}
      ${range('Arrondi des coins', 'style.radius', s.radius, 0, 200, 1, (v) => `${v}px`)}
      ${select_('Ombre', 'style.shadow', SHADOW_LIST, s.shadow)}
    `, false);
  }

  function arrangeSection(el) {
    return section('Disposition', `
      <div class="dc-grid-2">${num('X', 'x', el.x, { length: true })}${num('Y', 'y', el.y, { length: true })}</div>
      <div class="dc-grid-2">${num('Largeur', 'w', el.w, { min: 4, length: true })}${num('Hauteur', 'h', el.h, { min: 1, length: true })}</div>
      <div class="dc-grid-2">${num('Rotation', 'rotation', el.rotation, { min: -360, max: 360, suffix: '°' })}${range('Opacité', 'style.opacity', el.style.opacity, 0, 1, 0.05, (v) => `${Math.round(v * 100)}%`)}</div>
      <div class="dc-field"><span>Aligner sur la page</span>${alignButtons()}</div>
      <div class="dc-action-row">
        <button type="button" class="dc-btn" data-cmd="front" data-tip="Premier plan" data-kbd="Ctrl+Maj+↑"><i data-lucide="bring-to-front" class="w-3.5 h-3.5"></i></button>
        <button type="button" class="dc-btn" data-cmd="forward" data-tip="Avancer" data-kbd="Ctrl+↑"><i data-lucide="arrow-up" class="w-3.5 h-3.5"></i></button>
        <button type="button" class="dc-btn" data-cmd="backward" data-tip="Reculer" data-kbd="Ctrl+↓"><i data-lucide="arrow-down" class="w-3.5 h-3.5"></i></button>
        <button type="button" class="dc-btn" data-cmd="back" data-tip="Arrière-plan" data-kbd="Ctrl+Maj+↓"><i data-lucide="send-to-back" class="w-3.5 h-3.5"></i></button>
        <button type="button" class="dc-btn" data-cmd="lock" data-tip="${el.locked ? 'Déverrouiller' : 'Verrouiller'}" data-kbd="Ctrl+Maj+L"><i data-lucide="${el.locked ? 'lock-open' : 'lock'}" class="w-3.5 h-3.5"></i></button>
        <button type="button" class="dc-btn" data-cmd="duplicate" data-tip="Dupliquer" data-kbd="Ctrl+D"><i data-lucide="copy" class="w-3.5 h-3.5"></i></button>
        <button type="button" class="dc-btn dc-btn--danger" data-cmd="delete" data-tip="Supprimer" data-kbd="Suppr"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button>
      </div>
    `);
  }

  function alignButtons() {
    return `<div class="dc-seg dc-seg--wide">${[
      ['left', 'align-start-vertical', 'Gauche'], ['hcenter', 'align-center-vertical', 'Centre horizontal'], ['right', 'align-end-vertical', 'Droite'],
      ['top', 'align-start-horizontal', 'Haut'], ['vcenter', 'align-center-horizontal', 'Centre vertical'], ['bottom', 'align-end-horizontal', 'Bas'],
    ].map(([m, icon, title]) => `<button type="button" data-align="${m}" data-tip="${title}" data-kbd="${ALIGN_KBD[m] || ''}"><i data-lucide="${icon}" class="w-3.5 h-3.5"></i></button>`).join('')}</div>`;
  }

  function renderInspector() {
    const els = selectedElements();
    let html = '';
    if (!els.length) {
      const page = currentPage();
      const pageIndex = state.pages.indexOf(page) + 1;
      html = `
        <div class="dc-inspector-head"><span class="dc-inspector-icon"><i data-lucide="file-text" class="w-4 h-4"></i></span><div><p class="dc-inspector-title">Document</p><p class="dc-inspector-sub">Aucun élément sélectionné</p></div></div>
        ${section('Informations', `
          <label class="dc-field"><span>Titre</span><input type="text" data-meta="title" value="${esc(docMeta.title)}"></label>
          <label class="dc-field"><span>Type</span><select data-meta="document_type">${opts(meta.documentTypes || [], docMeta.document_type)}</select></label>
          <label class="dc-field"><span>Client</span><select data-meta="client_id"><option value="">—</option>${opts(meta.clients || [], docMeta.client_id)}</select></label>
          <label class="dc-field"><span>Statut</span><select data-meta="status">${opts(meta.statuses || [], docMeta.status)}</select></label>
        `)}
        ${(cfg.responses || []).length ? section(`Réponses reçues (${cfg.responses.length})`, cfg.responses.map((r) => `
          <details class="dc-response"><summary><strong>${esc(r.client)}</strong><span>${esc(r.date)}</span></summary>
            <dl>${r.rows.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value || '—')}</dd></div>`).join('')}</dl>
          </details>`).join('')) : ''}
        ${section('Format', `
          <div class="dc-grid-2">
            <label class="dc-field"><span>Format</span><select data-meta="page_format">${opts(meta.pageFormats || [], docMeta.page_format)}</select></label>
            <label class="dc-field"><span>Orientation</span><select data-meta="page_orientation">${opts(meta.orientations || [], docMeta.page_orientation)}</select></label>
          </div>
          <p class="dc-note">${fmtLen(pageW)} × ${fmtLen(pageH)} · ${state.pages.length} page${state.pages.length > 1 ? 's' : ''}</p>
        `)}
        ${section(`Page ${pageIndex}`, `
          ${color('Couleur de fond', 'page.background', page.background)}
          <button type="button" class="dc-btn dc-btn--block" data-page-apply-all><i data-lucide="copy-check" class="w-3.5 h-3.5"></i> Appliquer ce fond à toutes les pages</button>
        `)}
        ${section('Raccourcis', `
          <ul class="dc-shortcuts">
            <li>${kbdHtml('T')} texte · ${kbdHtml('R')} rectangle · ${kbdHtml('O')} ellipse</li>
            <li>${kbdHtml('Alt')} + survol : cotes entre deux éléments</li>
            <li>${kbdHtml('M')} cotes permanentes · ${kbdHtml('U')} mm / px</li>
          </ul>
          <button type="button" class="dc-btn dc-btn--block" data-open-help>${kbdHtml('?')} Voir tous les raccourcis</button>
        `, false)}
        <div class="dc-inspector-foot">
          <a href="${meta.listUrl}" class="dc-btn dc-btn--block">← Retour aux documents</a>
          <button type="button" class="dc-btn dc-btn--block dc-btn--danger" data-delete-document>Supprimer le document</button>
        </div>`;
    } else if (els.length > 1) {
      html = `
        <div class="dc-inspector-head"><span class="dc-inspector-icon"><i data-lucide="group" class="w-4 h-4"></i></span><div><p class="dc-inspector-title">${els.length} éléments</p><p class="dc-inspector-sub">Sélection multiple</p></div></div>
        ${section('Aligner', `
          <div class="dc-seg dc-seg--wide">${[
            ['left', 'align-start-vertical', 'Gauche'], ['hcenter', 'align-center-vertical', 'Centre'], ['right', 'align-end-vertical', 'Droite'],
            ['top', 'align-start-horizontal', 'Haut'], ['vcenter', 'align-center-horizontal', 'Milieu'], ['bottom', 'align-end-horizontal', 'Bas'],
          ].map(([m, icon, title]) => `<button type="button" data-align="${m}" data-tip="${title}" data-kbd="${ALIGN_KBD[m] || ''}"><i data-lucide="${icon}" class="w-3.5 h-3.5"></i></button>`).join('')}</div>
          <div class="dc-grid-2 mt-2">
            <button type="button" class="dc-btn" data-align="hdist"><i data-lucide="align-horizontal-distribute-center" class="w-3.5 h-3.5"></i> Répartir ↔</button>
            <button type="button" class="dc-btn" data-align="vdist"><i data-lucide="align-vertical-distribute-center" class="w-3.5 h-3.5"></i> Répartir ↕</button>
          </div>
        `)}
        ${section('Apparence', range('Opacité', 'style.opacity', els[0].style.opacity, 0, 1, 0.05, (v) => `${Math.round(v * 100)}%`))}
        <div class="dc-action-row">
          <button type="button" class="dc-btn" data-cmd="front" data-tip="Premier plan" data-kbd="Ctrl+Maj+↑"><i data-lucide="bring-to-front" class="w-3.5 h-3.5"></i></button>
          <button type="button" class="dc-btn" data-cmd="back" data-tip="Arrière-plan" data-kbd="Ctrl+Maj+↓"><i data-lucide="send-to-back" class="w-3.5 h-3.5"></i></button>
          <button type="button" class="dc-btn" data-cmd="lock" data-tip="Verrouiller" data-kbd="Ctrl+Maj+L"><i data-lucide="lock" class="w-3.5 h-3.5"></i></button>
          <button type="button" class="dc-btn" data-cmd="duplicate" data-tip="Dupliquer" data-kbd="Ctrl+D"><i data-lucide="copy" class="w-3.5 h-3.5"></i></button>
          <button type="button" class="dc-btn dc-btn--danger" data-cmd="delete" data-tip="Supprimer" data-kbd="Suppr"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button>
        </div>`;
    } else {
      const el = els[0];
      const s = el.style;
      const label = el.type === 'shape' ? SHAPE_LABEL[el.shape] : TYPE_LABEL[el.type];
      html = `
        <div class="dc-inspector-head"><span class="dc-inspector-icon"><i data-lucide="${TYPE_ICON[el.type]}" class="w-4 h-4"></i></span>
          <div class="min-w-0 flex-1"><input class="dc-name-input" data-prop="name" data-kind="str" value="${esc(el.name)}" placeholder="${label}"><p class="dc-inspector-sub">${label}${editing ? ' · en édition' : ''}</p></div></div>`;
      if (el.type === 'text') {
        const keys = tokenKeys(el.html);
        if (keys.length && !editing) {
          html += section('Champs dynamiques', `
            <p class="dc-note">Remplacés par les vraies valeurs (client, entreprise…) à l'export et dans le portail.</p>
            ${keys.map((key, i) => `<div class="dc-var-row"><select data-var-swap="${i}">${varOptions(key)}</select><button type="button" class="dc-icon-btn" data-var-remove="${i}" data-tip="Retirer ce champ"><i data-lucide="x" class="w-3.5 h-3.5"></i></button></div>`).join('')}
          `);
        }
        html += typographySection(s) + boxSection(s);
      } else if (el.type === 'shape') {
        const isLine = el.shape === 'line' || el.shape === 'arrow';
        const isPath = el.shape === 'path';
        if (isPath) html += pathInspector(el);
        html += section(isPath ? 'Remplissage et contour' : 'Forme', `
          ${isPath ? '' : select_('Type', 'shape', Object.entries(SHAPE_LABEL).filter(([k]) => k !== 'path'), el.shape)}
          ${isLine ? '' : color('Remplissage', 'style.fill', s.fill, { allowNone: true })}
          ${isLine || s.fill === 'transparent' ? '' : gradientFields(s)}
          <div class="dc-grid-2">${num(isLine ? 'Épaisseur' : 'Contour', 'style.strokeWidth', s.strokeWidth, { min: 0, max: 40, suffix: 'px' })}${select_('Style', 'style.strokeStyle', BORDER_LIST.slice(0, 3), s.strokeStyle)}</div>
          ${s.strokeWidth || isLine ? color(isLine ? 'Couleur' : 'Couleur du contour', 'style.strokeColor', s.strokeColor) : ''}
          ${el.shape === 'rect' ? range('Arrondi des coins', 'style.radius', s.radius, 0, 200, 1, (v) => `${v}px`) : ''}
          ${isPath || el.shape === 'arrow' ? '' : '<button type="button" class="dc-btn dc-btn--block" data-vec="convert"><i data-lucide="spline" class="w-3.5 h-3.5"></i> Convertir en tracé (points et tangentes)</button>'}
        `);
      } else if (el.type === 'image') {
        html += section('Image', `
          <button type="button" class="dc-btn dc-btn--block" data-replace-image><i data-lucide="image-up" class="w-3.5 h-3.5"></i> ${el.src ? 'Remplacer l\'image' : 'Choisir une image'}</button>
          ${select_('Ajustement', 'style.fit', [['cover', 'Remplir (recadrer)'], ['contain', 'Contenir (sans recadrage)'], ['fill', 'Étirer']], s.fit)}
          ${range('Arrondi des coins', 'style.radius', s.radius, 0, 300, 1, (v) => `${v}px`)}
        `) + boxSection(s, { padding: false });
      } else if (el.type === 'table') {
        html += tableInspector(el) + typographySection(s) + boxSection(s);
      } else if (el.type === 'field') {
        const withOptions = ['select', 'radio', 'checkbox'].includes(el.fieldType);
        html += section('Champ de formulaire', `
          ${select_('Type de champ', 'fieldType', FORM_FIELD_TYPES, el.fieldType)}
          <label class="dc-field"><span>Question / libellé</span><input type="text" data-prop="label" data-kind="str" value="${esc(el.label)}" maxlength="160"></label>
          ${['radio', 'checkbox'].includes(el.fieldType) ? '' : `<label class="dc-field"><span>Texte d'aide dans le champ</span><input type="text" data-prop="placeholder" data-kind="str" value="${esc(el.placeholder)}" maxlength="160"></label>`}
          ${withOptions ? `<label class="dc-field"><span>Choix proposés <small>(un par ligne)</small></span><textarea rows="4" data-field-options>${esc(el.options.join('\n'))}</textarea></label>` : ''}
          <label class="dc-check"><input type="checkbox" data-prop="required" data-kind="bool" ${el.required ? 'checked' : ''}> Réponse obligatoire</label>
          <label class="dc-check"><input type="checkbox" data-prop="showLabel" data-kind="bool" ${el.showLabel ? 'checked' : ''}> Afficher le libellé</label>
          <p class="dc-note">Le client remplit ce champ dans son espace ; ses réponses arrivent dans le document (onglet Document).</p>
        `) + section('Style du champ', `
          ${color('Fond du champ', 'style.fieldBg', s.fieldBg)}
          ${color('Bordure du champ', 'style.fieldBorder', s.fieldBorder)}
          ${color('Libellé', 'style.labelColor', s.labelColor)}
          ${color('Accent (cases, astérisque)', 'style.accent', s.accent)}
          ${range('Arrondi du champ', 'style.fieldRadius', s.fieldRadius, 0, 30, 1, (v) => `${v}px`)}
        `) + typographySection(s) + boxSection(s);
      } else if (el.type === 'button') {
        html += section('Bouton', `
          <label class="dc-field"><span>Texte du bouton</span><input type="text" data-prop="text" data-kind="str" value="${esc(el.text)}" maxlength="60"></label>
          <p class="dc-note">Envoie les réponses du client depuis son espace. Il n'apparaît pas dans le PDF.</p>
        `) + typographySection(s) + boxSection(s);
      }
      html += arrangeSection(el);
    }
    inspector.innerHTML = html;
    refreshIcons(inspector);
  }

  // ------------------------------------------------------------- tableaux avancés (inspecteur)
  const TABLE_PRESETS = [
    ['classic', 'Classique', { headerBg: '#111827', headerColor: '#ffffff', stripe: '#f9fafb', cellBorderColor: '#e5e7eb', totalBg: 'transparent' }, 'all'],
    ['minimal', 'Minimal', { headerBg: 'transparent', headerColor: '#111827', stripe: 'transparent', cellBorderColor: '#e5e7eb', totalBg: 'transparent' }, 'rows'],
    ['accent', 'Couleur', { headerBg: '#6d28d9', headerColor: '#ffffff', stripe: '#f5f3ff', cellBorderColor: '#ede9fe', totalBg: '#f5f3ff' }, 'none'],
    ['soft', 'Doux', { headerBg: '#ede9fe', headerColor: '#4c1d95', stripe: 'transparent', cellBorderColor: '#ede9fe', totalBg: '#faf8ff' }, 'rows'],
    ['framed', 'Encadré', { headerBg: '#f3f4f6', headerColor: '#111827', stripe: 'transparent', cellBorderColor: '#d1d5db', totalBg: '#f9fafb' }, 'all'],
  ];
  const COLUMN_KINDS = [['text', 'Texte'], ['number', 'Nombre'], ['money', 'Montant (€)'], ['percent', 'Pourcentage'], ['calc', 'Calcul (A × B)']];
  const SOURCE_FIELDS = [['', '— Aucune —'], ['name', 'Désignation'], ['description', 'Description'], ['quantity', 'Quantité'], ['unit', 'Unité'], ['unit_price', 'Prix unitaire'], ['tax_rate', 'TVA (%)'], ['total', 'Total de la ligne']];
  const FIELD_KIND = { quantity: 'number', unit_price: 'money', total: 'money', tax_rate: 'percent' };
  const FIELD_GUESS = [[/d[ée]signation|libell|article|prestation|produit|^nom/i, 'name'], [/descr/i, 'description'], [/qt[ée]|quantit/i, 'quantity'], [/^unit[ée]s?$/i, 'unit'], [/prix|tarif|p\.?\s?u/i, 'unit_price'], [/tva|taxe/i, 'tax_rate'], [/total|montant/i, 'total']];
  const plainText = (h) => { const d = document.createElement('div'); d.innerHTML = h || ''; return (d.textContent || '').trim(); };
  const colName = (el, i) => (el.header && plainText(el.rows[0][i])) || `Colonne ${i + 1}`;

  // Relie les colonnes aux données du devis d'après leur titre (« Qté » → Quantité…).
  function guessFields(el) {
    const fallback = ['name', 'quantity', 'unit_price', 'total'];
    el.columns.forEach((col, i) => {
      if (col.field) return;
      const title = el.header ? plainText(el.rows[0][i]) : '';
      const hit = FIELD_GUESS.find(([re]) => re.test(title));
      col.field = hit ? hit[1] : (fallback[i] || '');
      if (col.kind === 'text' && FIELD_KIND[col.field]) col.kind = FIELD_KIND[col.field];
    });
  }

  function tableInspector(el) {
    const s = el.style;
    const cols = el.rows[0].length;
    const colOpts = (sel) => el.columns.map((_, i) => `<option value="${i}"${i === sel ? ' selected' : ''}>${esc(colName(el, i))}</option>`).join('');
    const linked = el.source ? sourceData(el.source) : null;
    const sourceName = el.source === 'invoice' ? 'facture' : 'devis';
    let html = section('Tableau', `
      <p class="dc-note">${el.rows.length} lignes × ${cols} colonnes${activeCell ? ' · actions relatives à la cellule active' : ''}</p>
      <div class="dc-grid-2">
        <button type="button" class="dc-btn" data-table="add-row"><i data-lucide="between-horizontal-end" class="w-3.5 h-3.5"></i> Ligne</button>
        <button type="button" class="dc-btn" data-table="add-col"><i data-lucide="between-vertical-end" class="w-3.5 h-3.5"></i> Colonne</button>
        <button type="button" class="dc-btn" data-table="del-row"><i data-lucide="minus" class="w-3.5 h-3.5"></i> Ligne</button>
        <button type="button" class="dc-btn" data-table="del-col"><i data-lucide="minus" class="w-3.5 h-3.5"></i> Colonne</button>
      </div>
      <label class="dc-check"><input type="checkbox" data-prop="header" data-kind="bool" ${el.header ? 'checked' : ''}> Ligne d'en-tête</label>
      <div class="dc-field"><span>Style</span><div class="dc-tpresets">${TABLE_PRESETS.map(([key, label, p, borders]) => `
        <button type="button" data-table-preset="${key}" title="${label}">
          <span class="dc-tpreset" style="--h:${p.headerBg === 'transparent' ? '#fff' : p.headerBg};--hc:${p.headerColor};--st:${p.stripe === 'transparent' ? '#fff' : p.stripe};--b:${p.cellBorderColor}" data-borders="${borders}"><i></i><i></i><i></i></span>
          <small>${label}</small></button>`).join('')}</div></div>
      ${select_('Bordures', 'borders', [['all', 'Toutes les cases'], ['rows', 'Lignes horizontales'], ['outer', 'Contour seulement'], ['none', 'Aucune']], el.borders)}
    `);
    html += section('Colonnes', `
      <p class="dc-note">Un type « Montant » ou « Nombre » met les valeurs au bon format (1&nbsp;200,00&nbsp;€) ; « Calcul » multiplie deux colonnes (Qté × Prix).</p>
      ${el.columns.map((col, i) => `
        <div class="dc-col-card">
          <div class="dc-col-head"><strong>${esc(colName(el, i))}</strong><span class="dc-num dc-num--sm"><input type="number" min="1" max="100" step="1" data-colwidth="${i}" value="${Math.round(el.colWidths[i])}"><em>%</em></span></div>
          <div class="dc-grid-2">
            <select data-col="${i}" data-col-key="kind" title="Type de contenu">${opts(COLUMN_KINDS, col.kind)}</select>
            <select data-col="${i}" data-col-key="align" title="Alignement">${opts([['', 'Alignement auto'], ['left', 'À gauche'], ['center', 'Centré'], ['right', 'À droite']], col.align)}</select>
          </div>
          ${col.kind === 'calc' ? `<div class="dc-calc"><select data-col="${i}" data-col-key="a">${colOpts(col.a)}</select><span>×</span><select data-col="${i}" data-col-key="b">${colOpts(col.b)}</select></div>` : ''}
          ${el.source ? `<label class="dc-col-field"><span>Donnée du ${sourceName}</span><select data-col="${i}" data-col-key="field">${opts(SOURCE_FIELDS, col.field)}</select></label>` : ''}
        </div>`).join('')}
      <button type="button" class="dc-none-btn" data-table="equal">Égaliser les largeurs</button>
    `);
    const pickList = el.source ? sourceList(el.source) : [];
    html += section('Données & totaux', `
      ${select_('Lignes du tableau', 'source', [['', 'Saisies à la main'], ['quote', 'Lignes d\'un devis du client'], ['invoice', 'Lignes d\'une facture du client']], el.source)}
      ${el.source ? `
        <label class="dc-field"><span>${el.source === 'quote' ? 'Devis utilisé' : 'Facture utilisée'}</span>
          <select data-source-pick="${el.source}"><option value="">Le plus récent du client</option>${pickList.map((x) => `<option value="${esc(x.id)}"${x.id === docSources[el.source] ? ' selected' : ''}>${esc(x.label)}</option>`).join('')}</select></label>
        <p class="dc-note">${linked ? `Aperçu avec ${esc(linked.label)}.` : (docMeta.client_id ? `Ce client n'a pas encore de ${sourceName} : les lignes d'exemple restent affichées.` : 'Choisissez un client (onglet Variables) pour voir ses lignes.')} Dans un modèle, les lignes saisies servent d'exemple : elles sont remplacées par celles du ${sourceName} du client, y compris quand un workflow crée le document.</p>` : ''}
      ${select_('Totaux en bas', 'totals.mode', [['none', 'Aucun'], ['sum', 'Somme des colonnes chiffrées'], ['vat', 'Total HT, TVA et TTC']], (el.totals || {}).mode)}
      ${(el.totals || {}).mode === 'vat' ? `<div class="dc-grid-2">${num('Taux de TVA', 'totals.vatRate', el.totals.vatRate, { min: 0, max: 100, step: 0.5, suffix: '%' })}<label class="dc-field"><span>Libellé</span><input type="text" data-prop="totals.label" data-kind="str" value="${esc(el.totals.label)}" placeholder="Total HT" maxlength="40"></label></div>${el.source ? '<p class="dc-note">Avec un devis relié, la TVA suit le taux de chaque ligne.</p>' : ''}` : ''}
      ${(el.totals || {}).mode === 'sum' ? `<label class="dc-field"><span>Libellé</span><input type="text" data-prop="totals.label" data-kind="str" value="${esc(el.totals.label)}" placeholder="Total" maxlength="40"></label>` : ''}
      ${(el.totals || {}).mode !== 'none' ? color('Fond des totaux', 'style.totalBg', s.totalBg, { allowNone: true }) : ''}
    `);
    html += cellSection(el);
    html += section('Couleurs', `
      ${el.header ? color('Fond de l\'en-tête', 'style.headerBg', s.headerBg, { allowNone: true }) + color('Texte de l\'en-tête', 'style.headerColor', s.headerColor) : ''}
      ${color('Lignes alternées', 'style.stripe', s.stripe, { allowNone: true })}
      ${color('Bordures des cellules', 'style.cellBorderColor', s.cellBorderColor)}
      ${range('Marge des cellules', 'style.cellPadding', s.cellPadding, 0, 30, 1, (v) => `${v}px`)}
    `, false);
    return html;
  }

  function cellSection(el) {
    if (!editing || editing.id !== el.id || !activeCell || activeCell.dataset.r === undefined) {
      return section('Cellule', '<p class="dc-note">Double-cliquez dans le tableau puis cliquez une case pour lui donner sa propre couleur, sa graisse ou son alignement.</p>', false);
    }
    const key = `${activeCell.dataset.r}:${activeCell.dataset.c}`;
    const cs = (el.cellStyles || {})[key] || {};
    const hex = (v, d) => (/^#[0-9a-f]{6}$/i.test(v || '') ? v : d);
    return section('Cellule', `
      <p class="dc-note">Ligne ${+activeCell.dataset.r + 1}, colonne ${+activeCell.dataset.c + 1}</p>
      <div class="dc-grid-2">
        <label class="dc-field"><span class="dc-field-row"><span>Fond</span>${cs.bg ? '<button type="button" class="dc-none-btn" data-cell-clear="bg">Aucun</button>' : ''}</span><input type="color" data-cell-prop="bg" value="${hex(cs.bg, '#ffffff')}"></label>
        <label class="dc-field"><span class="dc-field-row"><span>Texte</span>${cs.color ? '<button type="button" class="dc-none-btn" data-cell-clear="color">Auto</button>' : ''}</span><input type="color" data-cell-prop="color" value="${hex(cs.color, '#1f2937')}"></label>
      </div>
      <div class="dc-seg-row">
        <div class="dc-seg">${[['left', 'align-left', 'Gauche'], ['center', 'align-center', 'Centre'], ['right', 'align-right', 'Droite']].map(([v, icon, t]) => `<button type="button" class="${cs.align === v ? 'is-active' : ''}" data-cell-align="${v}" data-tip="${t}"><i data-lucide="${icon}" class="w-3.5 h-3.5"></i></button>`).join('')}</div>
        <span class="dc-toggles"><button type="button" class="dc-toggle${cs.bold ? ' is-active' : ''}" data-cell-toggle="bold" data-tip="Gras"><i data-lucide="bold" class="w-3.5 h-3.5"></i></button><button type="button" class="dc-toggle${cs.italic ? ' is-active' : ''}" data-cell-toggle="italic" data-tip="Italique"><i data-lucide="italic" class="w-3.5 h-3.5"></i></button></span>
      </div>
      ${Object.keys(cs).length ? '<button type="button" class="dc-none-btn" data-cell-reset>Réinitialiser la cellule</button>' : ''}
    `);
  }

  // Style d'une cellule : appliqué directement à la case (l'édition en cours garde son curseur).
  function setCellStyle(mutator) {
    const el = selectedElements()[0];
    if (!el || el.type !== 'table' || !activeCell || activeCell.dataset.r === undefined) return;
    const key = `${activeCell.dataset.r}:${activeCell.dataset.c}`;
    el.cellStyles = el.cellStyles || {};
    const cs = Object.assign({}, el.cellStyles[key]);
    mutator(cs);
    Object.keys(cs).forEach((k) => { if (!cs[k]) delete cs[k]; });
    if (Object.keys(cs).length) el.cellStyles[key] = cs; else delete el.cellStyles[key];
    syncEditingTable(el);
    const node = nodeFor(el.id);
    const r = activeCell.dataset.r; const c = activeCell.dataset.c;
    node.innerHTML = tableHtml(el, true);
    node.querySelectorAll(EDITABLE_CELLS).forEach((cell) => { cell.contentEditable = 'true'; });
    activeCell = node.querySelector(`[data-r="${r}"][data-c="${c}"]`);
    if (activeCell) activeCell.classList.add('is-active-cell');
    fitTables(); renderSelection(); renderInspector(); commit();
  }
  inspector.addEventListener('input', (e) => {
    const t = e.target.closest('[data-cell-prop]');
    if (!t || !activeCell) return;
    activeCell.style[t.dataset.cellProp === 'bg' ? 'background' : 'color'] = t.value; // aperçu immédiat
  });
  inspector.addEventListener('change', (e) => {
    const t = e.target;
    if (t.dataset.cellProp) { setCellStyle((cs) => { cs[t.dataset.cellProp] = t.value; }); return; }
    if (t.dataset.sourcePick !== undefined) {
      docSources[t.dataset.sourcePick] = t.value;
      refreshValues(); renderInspector(); renderVarPane(); scheduleSave();
      return;
    }
    if (t.dataset.col !== undefined) {
      const el = selectedElements()[0];
      if (!el || el.type !== 'table') return;
      const col = el.columns[+t.dataset.col];
      const key = t.dataset.colKey;
      col[key] = key === 'a' || key === 'b' ? +t.value : t.value;
      if (key === 'kind' && t.value === 'calc' && col.a === undefined) {
        const qty = el.columns.findIndex((c) => c.field === 'quantity' || c.kind === 'number');
        const price = el.columns.findIndex((c, i) => i !== +t.dataset.col && (c.field === 'unit_price' || c.kind === 'money'));
        col.a = Math.max(0, qty); col.b = Math.max(0, price);
      }
      if (key === 'field' && FIELD_KIND[t.value] && col.kind === 'text') col.kind = FIELD_KIND[t.value];
      if (editing) syncEditingTable(el);
      renderPages(); fitTables(); renderSelection(); renderInspector(); commit();
    }
  });
  inspector.addEventListener('click', (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.cellClear) setCellStyle((cs) => { delete cs[t.dataset.cellClear]; });
    else if (t.dataset.cellAlign) setCellStyle((cs) => { cs.align = cs.align === t.dataset.cellAlign ? '' : t.dataset.cellAlign; });
    else if (t.dataset.cellToggle) setCellStyle((cs) => { cs[t.dataset.cellToggle] = !cs[t.dataset.cellToggle]; });
    else if (t.hasAttribute('data-cell-reset')) setCellStyle((cs) => { Object.keys(cs).forEach((k) => delete cs[k]); });
    else if (t.dataset.tablePreset) {
      const el = selectedElements()[0];
      const preset = TABLE_PRESETS.find((p) => p[0] === t.dataset.tablePreset);
      if (!el || el.type !== 'table' || !preset) return;
      Object.assign(el.style, preset[2]);
      el.borders = preset[3];
      if (editing) syncEditingTable(el);
      const wasEditing = !!editing;
      editing = null; activeCell = null;
      renderPages();
      if (wasEditing) startEditing(el.id); else { renderSelection(); renderInspector(); }
      commit();
    }
  });

  // ------------------------------------------------------------- jetons de variables (remplacement par menu)
  function tokenKeys(html) {
    return [...String(html || '').matchAll(/class="doc-var-token"[^>]*data-var="([\w.]+)"/g)].map((m) => m[1]);
  }
  // Modifie le n-ième jeton d'un HTML : nouvelle clé, ou suppression si key === null.
  function editToken(html, index, key) {
    const tpl = document.createElement('template');
    tpl.innerHTML = html;
    const token = tpl.content.querySelectorAll('.doc-var-token')[index];
    if (!token) return html;
    if (key === null) token.remove();
    else { token.dataset.var = key; token.textContent = tokenText(key); }
    return tpl.innerHTML;
  }
  inspector.addEventListener('change', (e) => {
    const t = e.target.closest('[data-var-swap]');
    const el = selectedElements()[0];
    if (!t || !el || el.type !== 'text') return;
    el.html = editToken(el.html, +t.dataset.varSwap, t.value);
    renderPages(); growText(el); renderSelection(); commit();
  });
  inspector.addEventListener('click', (e) => {
    const t = e.target.closest('[data-var-remove]');
    const el = selectedElements()[0];
    if (!t || !el || el.type !== 'text') return;
    el.html = editToken(el.html, +t.dataset.varRemove, null);
    renderPages(); growText(el); renderSelection(); renderInspector(); commit();
  });

  // Clic sur un jeton dans la page : menu pour le remplacer par un autre champ.
  const varPop = document.createElement('div');
  varPop.className = 'dc-var-pop';
  varPop.hidden = true;
  document.body.appendChild(varPop);
  let varPopTarget = null;
  function openVarPop(token) {
    varPopTarget = token;
    const current = token.dataset.var;
    varPop.innerHTML = `<p class="dc-var-pop-title">Champ dynamique</p>${Object.entries(varGroups()).map(([group, list]) => `
      <p class="dc-var-group">${esc(group)}</p>
      ${list.map((v) => `<button type="button" data-var-pick="${esc(v.key)}" class="${v.key === current ? 'is-active' : ''}">${esc(v.label)}${v.key === current ? '<i data-lucide="check" class="w-3.5 h-3.5"></i>' : ''}</button>`).join('')}`).join('')}
      <button type="button" class="dc-var-pop-remove" data-var-pick=""><i data-lucide="trash-2" class="w-3.5 h-3.5"></i> Retirer ce champ</button>`;
    varPop.hidden = false;
    const r = token.getBoundingClientRect();
    const top = Math.min(window.innerHeight - varPop.offsetHeight - 8, r.bottom + 6);
    varPop.style.top = `${Math.max(8, top)}px`;
    varPop.style.left = `${Math.min(window.innerWidth - varPop.offsetWidth - 8, r.left)}px`;
    refreshIcons(varPop);
  }
  function closeVarPop() { varPop.hidden = true; varPopTarget = null; }
  // Le cadre de sélection recouvre l'élément sélectionné : on cherche le jeton sous le pointeur.
  document.addEventListener('click', (e) => {
    const token = (e.target.closest && e.target.closest('.doc-var-token'))
      || document.elementsFromPoint(e.clientX, e.clientY).find((n) => n.classList && n.classList.contains('doc-var-token'));
    if (!token || !pagesHost.contains(token)) return;
    const host = token.closest('.dc-el');
    const found = host && findElement(host.dataset.id);
    if (!found || found.el.locked) return;
    openVarPop(token);
  });
  varPop.addEventListener('mousedown', (e) => e.preventDefault());
  varPop.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-var-pick]');
    if (!btn || !varPopTarget) return;
    const token = varPopTarget;
    const key = btn.dataset.varPick || null;
    const host = token.closest('.dc-el');
    const found = host && findElement(host.dataset.id);
    closeVarPop();
    if (!found) return;
    const { el } = found;
    if (key) { token.dataset.var = key; token.textContent = tokenText(key); } else token.remove();
    if (editing && editing.id === el.id) return; // relu par stopEditing()
    if (el.type === 'text') el.html = host.querySelector('.dc-text-content').innerHTML;
    else if (el.type === 'table') {
      host.querySelectorAll(EDITABLE_CELLS).forEach((c) => { el.rows[+c.dataset.r][+c.dataset.c] = c.innerHTML; });
    }
    renderPages(); if (el.type === 'text') growText(el); renderSelection(); renderInspector(); commit();
  });
  document.addEventListener('pointerdown', (e) => {
    if (!varPop.hidden && !varPop.contains(e.target) && !e.target.closest('.doc-var-token')) closeVarPop();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !varPop.hidden) closeVarPop(); }, true);

  inspector.addEventListener('input', (e) => {
    const t = e.target.closest('[data-field-options]');
    const el = selectedElements()[0];
    if (!t || !el || el.type !== 'field') return;
    el.options = t.value.split('\n').map((o) => o.trim()).filter(Boolean).slice(0, 20);
    renderPages(); renderSelection();
    clearTimeout(t._c); t._c = setTimeout(() => commit(), 400);
  });

  function setPath(obj, path, value) {
    const keys = path.split('.');
    const last = keys.pop();
    const target = keys.reduce((o, k) => o[k], obj);
    target[last] = value;
  }
  function parseValue(raw, kind) {
    if (kind === 'num') { const n = parseFloat(raw); return Number.isFinite(n) ? n : 0; }
    if (kind === 'bool') return raw === true || raw === 'true';
    return raw;
  }

  function applyProp(prop, value, { final = true } = {}) {
    if (prop === 'page.background') {
      currentPage().background = value;
      renderPages();
      if (final) { renderInspector(); commit(); }
      return;
    }
    const els = selectedElements();
    if (!els.length) return;
    els.forEach((el) => {
      if (prop === 'shape' && (value === 'line' || value === 'arrow') && !(el.shape === 'line' || el.shape === 'arrow')) {
        el.h = 16; el.style.strokeWidth = Math.max(2, el.style.strokeWidth);
      }
      if (prop === 'shape' && !(value === 'line' || value === 'arrow') && (el.shape === 'line' || el.shape === 'arrow')) {
        el.h = Math.max(el.h, 100);
      }
      setPath(el, prop, value);
      if (prop === 'w' || prop === 'h') el[prop] = Math.max(prop === 'w' ? 4 : 1, el[prop]);
      if (prop === 'source' && value && el.type === 'table') guessFields(el);
    });
    if (editing && prop.startsWith('style.')) {
      // Rebâtir l'élément en édition perdrait le curseur : on applique juste le style.
      const el = els[0];
      const node = nodeFor(el.id);
      const page = currentPage();
      applyBox(node, el, page.elements.indexOf(el));
      const inner = node.querySelector('.dc-text') || node.querySelector('table');
      if (inner) inner.setAttribute('style', `${inner.classList.contains('dc-text') ? `justify-content:${{ top: 'flex-start', middle: 'center', bottom: 'flex-end' }[el.style.valign]};` : ''}${textCss(el.style)}`);
    } else {
      renderPages();
    }
    els.forEach(growText);
    renderSelection();
    if (final) { renderInspector(); renderLayers(); commit(); }
  }

  inspector.addEventListener('input', (e) => {
    const t = e.target;
    if (t.dataset.prop && (t.type === 'range' || t.type === 'color')) {
      const out = t.closest('.dc-field') && t.closest('.dc-field').querySelector('output');
      if (out) out.textContent = t.dataset.prop === 'style.opacity' ? `${Math.round(t.value * 100)}%` : t.value;
      applyProp(t.dataset.prop, parseValue(t.value, t.dataset.kind), { final: false });
    }
  });
  inspector.addEventListener('change', (e) => {
    const t = e.target;
    if (t.dataset.prop) {
      let value = t.type === 'checkbox' ? t.checked : parseValue(t.value, t.dataset.kind);
      if (t.dataset.length) value = round(fromUnit(value));
      applyProp(t.dataset.prop, t.dataset.prop === 'style.fontWeight' ? parseInt(value, 10) : value);
    } else if (t.dataset.meta) {
      setMeta(t.dataset.meta, t.value);
    } else if (t.dataset.colwidth !== undefined) {
      const el = selectedElements()[0];
      const inputs = $$('[data-colwidth]', inspector).map((i) => Math.max(1, parseFloat(i.value) || 1));
      const total = inputs.reduce((a, b) => a + b, 0);
      el.colWidths = inputs.map((w) => round((w / total) * 100));
      renderPages(); renderSelection(); renderInspector(); commit();
    }
  });
  inspector.addEventListener('click', (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.setProp) {
      applyProp(t.dataset.setProp, parseValue(t.dataset.value, t.dataset.kind || 'str'));
    } else if (t.dataset.vec) {
      vecCommand(t.dataset.vec);
    } else if (t.dataset.cmd) {
      runCommand(t.dataset.cmd);
    } else if (t.dataset.align) {
      alignSelection(t.dataset.align);
    } else if (t.dataset.table) {
      tableCommand(t.dataset.table);
    } else if (t.hasAttribute('data-replace-image')) {
      pickImage(selectedElements()[0].id);
    } else if (t.hasAttribute('data-page-apply-all')) {
      const bg = currentPage().background;
      state.pages.forEach((p) => { p.background = bg; });
      renderPages(); commit();
    } else if (t.hasAttribute('data-delete-document')) {
      deleteDocument();
    } else if (t.hasAttribute('data-open-help')) {
      toggleHelp(true);
    }
  });
  // Les boutons de l'inspecteur ne doivent pas voler le focus du texte en cours d'édition.
  inspector.addEventListener('mousedown', (e) => {
    if (editing && e.target.closest('button')) e.preventDefault();
  });

  function tableCommand(cmd) {
    const el = selectedElements()[0];
    if (!el || el.type !== 'table') return;
    if (editing) syncEditingTable(el);
    const r = activeCell ? +activeCell.dataset.r : el.rows.length - 1;
    const c = activeCell ? +activeCell.dataset.c : el.rows[0].length - 1;
    const cols = el.rows[0].length;
    if (cmd === 'add-row') { shiftTable(el, 'row', r + 1, 1); el.rows.splice(r + 1, 0, new Array(cols).fill('')); }
    if (cmd === 'del-row' && el.rows.length > 1) { shiftTable(el, 'row', r, -1); el.rows.splice(r, 1); }
    if (cmd === 'add-col' && cols < 12) {
      shiftTable(el, 'col', c + 1, 1);
      el.rows.forEach((row) => row.splice(c + 1, 0, ''));
      el.columns.splice(c + 1, 0, { kind: 'text', align: '', field: '' });
      el.colWidths = new Array(cols + 1).fill(round(100 / (cols + 1)));
    }
    if (cmd === 'del-col' && cols > 1) {
      shiftTable(el, 'col', c, -1);
      el.rows.forEach((row) => row.splice(c, 1));
      el.columns.splice(c, 1);
      el.colWidths = new Array(cols - 1).fill(round(100 / (cols - 1)));
    }
    if (cmd === 'equal') el.colWidths = new Array(cols).fill(round(100 / cols));
    const wasEditing = !!editing;
    editing = null;
    activeCell = null;
    renderPages();
    if (wasEditing) startEditing(el.id); else { renderSelection(); renderInspector(); }
    commit();
  }
  function syncEditingTable(el) {
    const node = nodeFor(el.id);
    node.querySelectorAll(EDITABLE_CELLS).forEach((cell) => { el.rows[+cell.dataset.r][+cell.dataset.c] = cell.innerHTML; });
  }
  // Décale les styles de cellule et les références des colonnes « Calcul » après ajout / suppression.
  function shiftTable(el, axis, at, delta) {
    const next = {};
    Object.entries(el.cellStyles || {}).forEach(([key, value]) => {
      let [r, c] = key.split(':').map(Number);
      const v = axis === 'row' ? r : c;
      if (delta < 0 && v === at) return;
      if (v >= at) { if (axis === 'row') r += delta; else c += delta; }
      next[`${r}:${c}`] = value;
    });
    el.cellStyles = next;
    if (axis === 'col') {
      el.columns.forEach((col) => {
        if (col.kind !== 'calc') return;
        ['a', 'b'].forEach((k) => {
          if (delta > 0 && col[k] >= at) col[k] += 1;
          else if (delta < 0) col[k] = col[k] === at ? 0 : (col[k] > at ? col[k] - 1 : col[k]);
        });
      });
    }
  }

  // ------------------------------------------------------------- calques
  const layerList = $('[data-dc-layer-list]');
  function layerLabel(el) {
    if (el.name) return el.name;
    if (el.type === 'text') {
      const div = document.createElement('div');
      div.innerHTML = el.html;
      const txt = (div.textContent || '').trim();
      return txt ? txt.slice(0, 32) : 'Texte vide';
    }
    if (el.type === 'shape') return SHAPE_LABEL[el.shape];
    return TYPE_LABEL[el.type];
  }
  function renderLayers() {
    const page = currentPage();
    if (!page.elements.length) {
      layerList.innerHTML = '<p class="dc-empty">Aucun élément sur cette page.</p>';
      return;
    }
    layerList.innerHTML = [...page.elements].reverse().map((el) => `
      <div class="dc-layer${selection.ids.includes(el.id) ? ' is-selected' : ''}${el.hidden ? ' is-hidden' : ''}" draggable="true" data-layer="${el.id}">
        <i data-lucide="grip-vertical" class="w-3 h-3 dc-layer-grip"></i>
        <i data-lucide="${TYPE_ICON[el.type]}" class="w-3.5 h-3.5"></i>
        <span class="dc-layer-name">${esc(layerLabel(el))}</span>
        <button type="button" data-layer-toggle="hidden" title="${el.hidden ? 'Afficher' : 'Masquer'}"><i data-lucide="${el.hidden ? 'eye-off' : 'eye'}" class="w-3.5 h-3.5"></i></button>
        <button type="button" data-layer-toggle="locked" title="${el.locked ? 'Déverrouiller' : 'Verrouiller'}" class="${el.locked ? 'is-on' : ''}"><i data-lucide="${el.locked ? 'lock' : 'lock-open'}" class="w-3.5 h-3.5"></i></button>
      </div>`).join('');
    refreshIcons(layerList);
  }
  layerList.addEventListener('click', (e) => {
    const row = e.target.closest('[data-layer]');
    if (!row) return;
    const id = row.dataset.layer;
    const toggleBtn = e.target.closest('[data-layer-toggle]');
    if (toggleBtn) {
      const el = currentPage().elements.find((x) => x.id === id);
      el[toggleBtn.dataset.layerToggle] = !el[toggleBtn.dataset.layerToggle];
      renderAll();
      commit();
      return;
    }
    if (editing) stopEditing();
    const ids = e.shiftKey ? Array.from(new Set([...selection.ids, id])) : [id];
    select(ids, selection.pageId);
  });
  let dragLayer = null;
  layerList.addEventListener('dragstart', (e) => { const row = e.target.closest('[data-layer]'); if (row) { dragLayer = row.dataset.layer; e.dataTransfer.effectAllowed = 'move'; } });
  layerList.addEventListener('dragover', (e) => { if (dragLayer) { e.preventDefault(); const row = e.target.closest('[data-layer]'); $$('.dc-layer', layerList).forEach((r) => r.classList.toggle('is-drop', r === row)); } });
  layerList.addEventListener('drop', (e) => {
    e.preventDefault();
    const row = e.target.closest('[data-layer]');
    if (!row || !dragLayer || row.dataset.layer === dragLayer) { dragLayer = null; renderLayers(); return; }
    const page = currentPage();
    const moving = page.elements.find((x) => x.id === dragLayer);
    page.elements = page.elements.filter((x) => x.id !== dragLayer);
    const targetIndex = page.elements.findIndex((x) => x.id === row.dataset.layer);
    // La liste est affichée à l'envers (premier plan en haut) : déposer sur une ligne = passer juste au-dessus.
    page.elements.splice(targetIndex + 1, 0, moving);
    dragLayer = null;
    renderAll();
    commit();
  });

  // ------------------------------------------------------------- pages (panneau)
  const pageList = $('[data-dc-page-list]');
  function renderPagesPane() {
    pageList.innerHTML = state.pages.map((p, i) => `
      <div class="dc-page-item${p.id === selection.pageId ? ' is-current' : ''}" data-page-item="${p.id}">
        <span class="dc-page-thumb" style="background:${p.background};aspect-ratio:${pageW}/${pageH}"></span>
        <span class="flex-1 min-w-0"><strong>Page ${i + 1}</strong><small>${p.elements.length} élément${p.elements.length > 1 ? 's' : ''}</small></span>
        <button type="button" data-dc-page-cmd="duplicate" title="Dupliquer"><i data-lucide="copy" class="w-3.5 h-3.5"></i></button>
        <button type="button" data-dc-page-cmd="delete" title="Supprimer"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button>
      </div>`).join('');
    refreshIcons(pageList);
  }
  pageList.addEventListener('click', (e) => {
    const item = e.target.closest('[data-page-item]');
    if (!item) return;
    const btn = e.target.closest('[data-dc-page-cmd]');
    pageCommand(btn ? btn.dataset.dcPageCmd : 'goto', item.dataset.pageItem);
  });

  // ------------------------------------------------------------- variables
  const varList = $('[data-dc-var-list]');
  const FIELD_TYPES = [['text', 'Texte'], ['choice', 'Liste de choix'], ['date', 'Date'], ['number', 'Nombre'], ['money', 'Montant (€)']];
  let newFieldOpen = false;
  let editFieldId = null; // champ en cours de paramétrage
  const insertBtn = (key) => `<button type="button" class="dc-fill-insert" data-var="${esc(key)}" data-tip="Insérer dans la page"><i data-lucide="plus" class="w-3.5 h-3.5"></i></button>`;
  function fieldControl(f) {
    if (f.type === 'choice') {
      return `<select data-field-value="${f.id}"><option value="">Choisir…</option>${f.options.map((o) => `<option${o === f.value ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
    }
    const type = { date: 'date', number: 'number' }[f.type] || 'text';
    return `<input type="${type}" data-field-value="${f.id}" value="${esc(f.value || '')}" placeholder="${f.type === 'money' ? 'ex. 1 200' : 'À remplir'}"${f.type === 'money' ? ' inputmode="decimal"' : ''}>`;
  }
  // Formulaire de paramétrage d'un champ (création ou modification).
  function fieldForm(f) {
    const isNew = !f;
    f = f || { label: '', type: 'text', options: [], required: false, help: '' };
    return `
      <div class="dc-fill-new" data-field-form="${isNew ? '' : f.id}">
        <label class="dc-fill-label">Nom du champ</label>
        <input type="text" data-new-field="label" placeholder="ex. Formule, Durée, Budget" maxlength="60" value="${esc(f.label)}">
        <label class="dc-fill-label">Type de réponse</label>
        <select data-new-field="type">${opts(FIELD_TYPES, f.type)}</select>
        <div data-new-field-options-wrap ${f.type === 'choice' ? '' : 'hidden'}>
          <label class="dc-fill-label">Choix proposés <small>(un par ligne)</small></label>
          <textarea data-new-field="options" rows="3" placeholder="Essentiel&#10;Confort&#10;Premium">${esc((f.options || []).join('\n'))}</textarea>
        </div>
        <label class="dc-fill-label">Aide pour la personne qui remplit <small>(facultatif)</small></label>
        <input type="text" data-new-field="help" maxlength="140" placeholder="ex. Durée en mois" value="${esc(f.help || '')}">
        <label class="dc-check"><input type="checkbox" data-new-field="required" ${f.required ? 'checked' : ''}> À remplir obligatoirement</label>
        <p class="dc-fill-hint">La valeur saisie dans un modèle sert de valeur par défaut. Ce champ est proposé à la création d'un document et dans les automatisations.</p>
        <div class="dc-fill-new-actions"><button type="button" class="dc-btn" data-new-field-cancel>Annuler</button><button type="button" class="dc-btn dc-btn--primary" data-new-field-add>${isNew ? 'Ajouter' : 'Enregistrer'}</button></div>
      </div>`;
  }
  function renderVarPane() {
    const groups = {};
    cfg.variables.forEach((v) => { (groups[v.group || 'Autres'] = groups[v.group || 'Autres'] || []).push(v); });
    varList.innerHTML = `
      <div class="dc-fill-block">
        <label class="dc-fill-label">Client du document</label>
        <select data-fill-client><option value="">Aucun client</option>${opts(meta.clients || [], docMeta.client_id)}</select>
        <p class="dc-fill-hint">Remplit automatiquement nom, email, téléphone et adresse.</p>
      </div>
      ${Object.entries(groups).map(([group, list]) => `
        <p class="dc-var-group">${esc(group)}</p>
        ${list.map((v) => {
          const value = varValue(v.key);
          return `<div class="dc-fill-row"><div class="dc-fill-main"><span class="dc-fill-name">${esc(v.label)}</span><span class="dc-fill-value${value ? '' : ' is-empty'}">${esc(value || (v.key.startsWith('client.') ? 'Choisissez un client' : 'Non renseigné'))}</span></div>${insertBtn(v.key)}</div>`;
        }).join('')}`).join('')}
      <p class="dc-var-group">${CUSTOM_GROUP}</p>
      ${customFields.length ? '' : '<p class="dc-fill-hint">Ajoutez vos propres champs (formule, durée, lieu…) puis remplissez-les ici.</p>'}
      ${customFields.map((f) => (editFieldId === f.id ? fieldForm(f) : `
        <div class="dc-fill-field${f.required && !f.value ? ' is-missing' : ''}">
          <div class="dc-fill-field-head"><span class="dc-fill-name">${esc(f.label)}${f.required ? ' <b class="dc-req" title="Obligatoire">*</b>' : ''} <small class="dc-fill-kind">${esc((FIELD_TYPES.find((t) => t[0] === f.type) || ['', ''])[1])}</small></span>
            <span class="dc-fill-actions">${insertBtn(`champ.${f.id}`)}<button type="button" class="dc-fill-insert" data-field-edit="${f.id}" data-tip="Paramétrer le champ"><i data-lucide="settings-2" class="w-3.5 h-3.5"></i></button><button type="button" class="dc-fill-insert" data-field-remove="${f.id}" data-tip="Supprimer le champ"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button></span></div>
          ${fieldControl(f)}
          ${f.help ? `<small class="dc-fill-help">${esc(f.help)}</small>` : ''}
        </div>`)).join('')}
      ${newFieldOpen ? fieldForm(null) : '<button type="button" class="dc-btn dc-btn--block mt-2" data-new-field-open><i data-lucide="plus" class="w-3.5 h-3.5"></i> Nouveau champ</button>'}`;
    refreshIcons(varList);
  }
  function refreshValues() {
    renderPages();
    if (editing) return;
    selectedElements().forEach((el) => { if (el.type === 'text') growText(el); });
    renderSelection();
  }
  renderVarPane();
  varList.addEventListener('mousedown', (e) => { if (editing && e.target.closest('[data-var]')) e.preventDefault(); });
  varList.addEventListener('change', (e) => {
    const t = e.target;
    if (t.matches('[data-fill-client]')) { setMeta('client_id', t.value); refreshValues(); renderVarPane(); renderInspector(); return; }
    if (t.matches('[data-new-field="type"]')) { t.closest('[data-field-form]').querySelector('[data-new-field-options-wrap]').hidden = t.value !== 'choice'; return; }
    if (t.dataset.fieldValue) {
      const f = customFields.find((x) => x.id === t.dataset.fieldValue);
      if (f) { f.value = t.value; refreshValues(); scheduleSave(); }
    }
  });
  varList.addEventListener('input', (e) => {
    const t = e.target;
    if (!t.dataset.fieldValue || t.tagName === 'SELECT') return;
    const f = customFields.find((x) => x.id === t.dataset.fieldValue);
    if (f) { f.value = t.value; clearTimeout(t._v); t._v = setTimeout(() => { refreshValues(); scheduleSave(); }, 250); }
  });
  varList.addEventListener('click', (e) => {
    if (e.target.closest('[data-new-field-open]')) { newFieldOpen = true; editFieldId = null; renderVarPane(); const i = varList.querySelector('[data-new-field="label"]'); if (i) i.focus(); return; }
    if (e.target.closest('[data-new-field-cancel]')) { newFieldOpen = false; editFieldId = null; renderVarPane(); return; }
    const editBtn = e.target.closest('[data-field-edit]');
    if (editBtn) { editFieldId = editBtn.dataset.fieldEdit; newFieldOpen = false; renderVarPane(); return; }
    if (e.target.closest('[data-new-field-add]')) {
      const form = e.target.closest('[data-field-form]');
      const q = (name) => form.querySelector(`[data-new-field="${name}"]`);
      const label = q('label').value.trim();
      const type = q('type').value;
      // Un choix par ligne (les virgules restent acceptées).
      const options = q('options').value.split(/\n|,/).map((o) => o.trim()).filter(Boolean).slice(0, 20);
      if (!label) { q('label').focus(); return; }
      if (type === 'choice' && !options.length) { q('options').focus(); return; }
      const settings = { label: label.slice(0, 60), type, options: type === 'choice' ? options : [], required: q('required').checked, help: q('help').value.trim().slice(0, 140) };
      const existing = customFields.find((x) => x.id === form.dataset.fieldForm);
      if (existing) {
        Object.assign(existing, settings);
        if (type === 'choice' && existing.value && !options.includes(existing.value)) existing.value = '';
      } else {
        customFields.push(Object.assign({ id: `f${Math.random().toString(36).slice(2, 9)}`, value: '' }, settings));
      }
      newFieldOpen = false; editFieldId = null;
      renderVarPane(); refreshValues(); scheduleSave();
      return;
    }
    const remove = e.target.closest('[data-field-remove]');
    if (remove) {
      const index = customFields.findIndex((x) => x.id === remove.dataset.fieldRemove);
      if (index >= 0) customFields.splice(index, 1);
      renderVarPane(); refreshValues(); scheduleSave();
    }
  });
  varList.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-var]');
    if (!btn) return;
    const token = `${varToken(btn.dataset.var)}&nbsp;`;
    if (editing) {
      document.execCommand('insertHTML', false, token);
      return;
    }
    const sel = selectedElements();
    if (sel.length === 1 && sel[0].type === 'text') {
      sel[0].html += ` ${token}`;
      renderPages(); growText(sel[0]); renderSelection(); commit();
      return;
    }
    const el = makePreset('paragraph');
    el.html = token; el.h = 28; el.w = 260;
    addElement(el);
  });

  // ------------------------------------------------------------- barre d'outils
  const richtext = $('[data-dc-richtext]');
  function updateToolbar() {
    const sel = selectedElements();
    const textish = editing || (sel.length === 1 && sel[0].type === 'text');
    richtext.classList.toggle('is-disabled', !textish);
    $('[data-dc-undo]').disabled = history.index <= 0;
    $('[data-dc-redo]').disabled = history.index >= history.stack.length - 1;
    $('[data-dc-toggle-grid]').classList.toggle('is-active', gridOn);
    $$('[data-dc-tool="pen"]').forEach((b) => b.classList.toggle('is-active', !!pen));
    $('[data-dc-toggle-measures]').classList.toggle('is-active', measuresOn);
    $('[data-dc-unit]').textContent = unit;
    $('[data-dc-zoom-fit]').textContent = `${Math.round(zoom * 100)}%`;
  }
  richtext.addEventListener('mousedown', (e) => { if (e.target.closest('button')) e.preventDefault(); });
  richtext.addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const sel = selectedElements();
    if (btn.dataset.dcExec) {
      if (editing) { document.execCommand(btn.dataset.dcExec, false, null); scheduleSave(); return; }
      if (sel.length === 1 && sel[0].type === 'text') {
        const s = sel[0].style;
        const map = { bold: ['style.fontWeight', s.fontWeight >= 600 ? 400 : 700], italic: ['style.italic', !s.italic], underline: ['style.underline', !s.underline] };
        if (map[btn.dataset.dcExec]) applyProp(...map[btn.dataset.dcExec]);
      }
    } else if (btn.hasAttribute('data-dc-link') && editing) {
      const url = prompt('Adresse du lien (https://…)', 'https://');
      if (url) document.execCommand('createLink', false, url);
    }
  });
  $$('[data-dc-exec-color]').forEach((input) => {
    let saved = null;
    input.addEventListener('pointerdown', () => { const s = window.getSelection(); saved = s.rangeCount ? s.getRangeAt(0).cloneRange() : null; });
    input.addEventListener('change', () => {
      if (editing && saved) {
        const s = window.getSelection(); s.removeAllRanges(); s.addRange(saved);
        document.execCommand('styleWithCSS', false, true);
        document.execCommand(input.dataset.dcExecColor, false, input.value);
        scheduleSave();
      } else if (input.dataset.dcExecColor === 'foreColor') {
        const sel = selectedElements();
        if (sel.length === 1 && sel[0].type === 'text') applyProp('style.color', input.value);
      }
    });
  });
  $('[data-dc-undo]').addEventListener('click', () => { if (editing) stopEditing(); undo(); });
  $('[data-dc-redo]').addEventListener('click', () => { if (editing) stopEditing(); redo(); });

  // ------------------------------------------------------------- zoom
  function setZoom(value) {
    zoom = Math.max(0.25, Math.min(3, Math.round(value * 100) / 100));
    renderPages();
    renderSelection();
    updateToolbar();
  }
  function fitZoom() { setZoom(Math.min(1.25, (workspace.clientWidth - 120) / pageW)); }
  $('[data-dc-zoom-in]').addEventListener('click', () => setZoom(zoom + 0.1));
  $('[data-dc-zoom-out]').addEventListener('click', () => setZoom(zoom - 0.1));
  $('[data-dc-zoom-fit]').addEventListener('click', fitZoom);
  workspace.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    setZoom(zoom * (e.deltaY > 0 ? 0.92 : 1.08));
  }, { passive: false });

  // ------------------------------------------------------------- onglets de la bibliothèque
  $$('[data-dc-tab]').forEach((tab) => tab.addEventListener('click', () => {
    $$('[data-dc-tab]').forEach((t) => t.classList.toggle('is-active', t === tab));
    $$('[data-dc-pane]').forEach((p) => p.classList.toggle('is-active', p.dataset.dcPane === tab.dataset.dcTab));
  }));

  // ------------------------------------------------------------- menu contextuel
  const ctxMenu = document.querySelector('[data-dc-context]');
  function hideContext() { ctxMenu.hidden = true; }
  pagesHost.addEventListener('contextmenu', (e) => {
    const elNode = e.target.closest('.dc-el');
    const pageNode = e.target.closest('[data-dc-page]');
    if (!pageNode || (editing && elNode && editing.id === elNode.dataset.id)) return;
    e.preventDefault();
    const pageId = pageNode.closest('.dc-page-wrap').dataset.pageId;
    if (elNode && !selection.ids.includes(elNode.dataset.id)) select([elNode.dataset.id], pageId);
    if (!elNode) select([], pageId);
    ctxMenu.querySelectorAll('button').forEach((b) => { b.disabled = b.dataset.dcCmd !== 'paste' && !selection.ids.length; });
    ctxMenu.querySelector('[data-dc-cmd="paste"]').disabled = !clipboard.length;
    ctxMenu.hidden = false;
    const { innerWidth, innerHeight } = window;
    const rect = ctxMenu.getBoundingClientRect();
    ctxMenu.style.left = `${Math.min(e.clientX, innerWidth - rect.width - 8)}px`;
    ctxMenu.style.top = `${Math.min(e.clientY, innerHeight - rect.height - 8)}px`;
    refreshIcons(ctxMenu);
  });
  ctxMenu.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-dc-cmd]');
    if (!btn || btn.disabled) return;
    hideContext();
    runCommand(btn.dataset.dcCmd);
  });
  document.addEventListener('pointerdown', (e) => { if (!ctxMenu.contains(e.target)) hideContext(); });

  // Clic hors des pages (zone grise) : quitter l'édition et désélectionner.
  workspace.addEventListener('pointerdown', (e) => {
    if (e.dcOnPage || e.target.closest('[data-dc-page]') || e.target.closest('.dc-page-bar')) return;
    if (editing) stopEditing();
    if (selection.ids.length) select([], selection.pageId);
  });

  // ------------------------------------------------------------- clavier
  // Outils d'insertion à une touche (sans modificateur), comme dans Figma / Canva.
  const TOOL_KEYS = { t: 'paragraph', r: 'rect', o: 'ellipse', l: 'line', b: 'table', i: 'image' };
  const TOOL_KEYS_SHIFT = { t: 'title', l: 'arrow' };
  const ALIGN_KEYS = { a: 'left', h: 'hcenter', d: 'right', w: 'top', v: 'vcenter', s: 'bottom' };

  function insertTool(preset) {
    const el = makePreset(preset);
    if (!el) return;
    addElement(el);
    if (el.type === 'image') pickImage(el.id);
  }

  function richShortcut(e, mod) {
    // Raccourcis de mise en forme pendant l'édition d'un texte ou d'une cellule
    // (Ctrl+B/I/U sont gérés nativement par le navigateur).
    if (!mod) return false;
    if (e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const url = prompt('Adresse du lien (https://…)', 'https://');
      if (url) document.execCommand('createLink', false, url);
      return true;
    }
    const map = {
      KeyX: e.shiftKey && 'strikeThrough', Digit7: e.shiftKey && 'insertOrderedList',
      Digit8: e.shiftKey && 'insertUnorderedList', Space: 'removeFormat',
    };
    const cmd = map[e.code];
    if (!cmd) return false;
    e.preventDefault();
    document.execCommand(cmd, false, null);
    scheduleSave();
    return true;
  }

  document.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (e.key === 'Alt' && !altDown) { altDown = true; if (selection.ids.length && !editing) renderSelection(); }
    if (editing) {
      if (e.key === 'Escape') { e.preventDefault(); stopEditing(); return; }
      richShortcut(e, mod);
      return;
    }
    const tag = (document.activeElement && document.activeElement.tagName) || '';
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(tag) || (document.activeElement && document.activeElement.isContentEditable)) return;
    if (!root.isConnected) return;
    if (vecKey(e)) return;
    const key = e.key.toLowerCase();
    hideTip();

    if (!helpPanel.hidden && e.key === 'Escape') { toggleHelp(false); return; }
    if (e.key === '?') { e.preventDefault(); toggleHelp(); return; }

    if (mod && key === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if (mod && key === 'y') { e.preventDefault(); redo(); return; }
    if (mod && key === 'v') { if (clipboard.length) { e.preventDefault(); paste(); } return; }
    if (mod && key === 'a') { e.preventDefault(); select(currentPage().elements.filter((x) => !x.hidden).map((x) => x.id), selection.pageId); return; }

    // Outils, affichage et zoom : touches simples.
    if (!mod && !e.altKey) {
      const tool = e.shiftKey ? TOOL_KEYS_SHIFT[key] : TOOL_KEYS[key];
      if (tool) { e.preventDefault(); insertTool(tool); return; }
      if (!e.shiftKey && key === 'g') { toggleGrid(); return; }
      if (!e.shiftKey && key === 'p') { e.preventDefault(); startPen(); return; }
      if (!e.shiftKey && key === 'm') { toggleMeasures(); return; }
      if (!e.shiftKey && key === 'u') { toggleUnit(); return; }
      if (e.key === '+' || e.key === '=' || e.code === 'NumpadAdd') { e.preventDefault(); setZoom(zoom + 0.1); return; }
      if (e.key === '-' || e.code === 'NumpadSubtract') { e.preventDefault(); setZoom(zoom - 0.1); return; }
      if (e.code === 'Digit0' && !e.shiftKey) { e.preventDefault(); setZoom(1); return; }
      if (e.code === 'Digit1' && e.shiftKey) { e.preventDefault(); fitZoom(); return; }
    }

    if (!selection.ids.length) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelection(); return; }
    if (mod && key === 'd') { e.preventDefault(); duplicateSelection(); return; }
    if (mod && key === 'c') { copySelection(); return; }
    if (mod && key === 'x') { copySelection(); deleteSelection(); return; }
    if (mod && e.shiftKey && key === 'l') { e.preventDefault(); toggleLock(); return; }
    if (mod && e.shiftKey && key === 'h') {
      e.preventDefault();
      const els = selectedElements();
      const hide = !els.every((x) => x.hidden);
      els.forEach((x) => { x.hidden = hide; });
      renderAll(); commit();
      return;
    }
    // Ctrl+B/I/U sur un texte sélectionné (hors édition) : style de tout le bloc.
    if (mod && !e.shiftKey && ['b', 'i', 'u'].includes(key)) {
      const sel = selectedElements();
      if (sel.length === 1 && sel[0].type === 'text') {
        e.preventDefault();
        const s = sel[0].style;
        if (key === 'b') applyProp('style.fontWeight', s.fontWeight >= 600 ? 400 : 700);
        if (key === 'i') applyProp('style.italic', !s.italic);
        if (key === 'u') applyProp('style.underline', !s.underline);
      }
      return;
    }
    // Alt+lettre : alignement (sur la page, ou entre eux si plusieurs éléments).
    if (e.altKey && !mod && ALIGN_KEYS[key]) { e.preventDefault(); alignSelection(ALIGN_KEYS[key]); return; }
    // Ctrl+↑/↓ : avancer/reculer ; avec Maj : premier plan / arrière-plan.
    if (mod && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      const up = e.key === 'ArrowUp';
      reorder(e.shiftKey ? (up ? 'front' : 'back') : (up ? 'forward' : 'backward'));
      return;
    }
    if (e.key === 'Escape') { select([], selection.pageId); return; }
    if (e.key === 'Enter' && selection.ids.length === 1) { e.preventDefault(); startEditing(selection.ids[0]); return; }
    const step = e.shiftKey ? 10 : 1;
    const arrows = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (arrows[e.key]) { e.preventDefault(); nudge(...arrows[e.key]); }
  });
  document.addEventListener('keyup', (e) => {
    if (e.key === 'Alt') {
      e.preventDefault(); // évite que Windows donne le focus au menu du navigateur
      altDown = false;
      renderSelection();
    }
  });
  window.addEventListener('blur', () => { if (altDown) { altDown = false; renderSelection(); } });

  // ------------------------------------------------------------- bascules d'affichage
  function toggleGrid() {
    gridOn = !gridOn;
    try { localStorage.setItem('dc-grid', gridOn ? '1' : '0'); } catch (e) { /* stockage indisponible */ }
    renderPages(); renderSelection(); updateToolbar();
  }
  function toggleMeasures() {
    measuresOn = !measuresOn;
    try { localStorage.setItem('dc-measures', measuresOn ? '1' : '0'); } catch (e) { /* stockage indisponible */ }
    renderSelection(); updateToolbar();
  }
  function toggleUnit() {
    unit = unit === 'mm' ? 'px' : 'mm';
    try { localStorage.setItem('dc-unit', unit); } catch (e) { /* stockage indisponible */ }
    renderSelection(); renderInspector(); updateToolbar();
  }
  $('[data-dc-toggle-grid]').addEventListener('click', toggleGrid);
  $('[data-dc-toggle-measures]').addEventListener('click', toggleMeasures);
  $('[data-dc-unit]').addEventListener('click', toggleUnit);
  $('[data-dc-help]').addEventListener('click', () => toggleHelp());

  // ------------------------------------------------------------- infobulles
  // Toute zone [data-tip] (ou [title], converti à la volée) affiche une infobulle
  // sobre avec son raccourci [data-kbd] après un court délai.
  const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform);
  const MAC_KEYS = { Ctrl: '⌘', Maj: '⇧', Alt: '⌥' };
  function kbdHtml(spec) {
    if (!spec) return '';
    const parts = spec === '+' ? ['+'] : spec.split('+');
    return `<span class="dc-kbd">${parts.map((k) => `<kbd>${esc(IS_MAC ? (MAC_KEYS[k] || k) : k)}</kbd>`).join('')}</span>`;
  }
  const tipEl = document.createElement('div');
  tipEl.className = 'dc-tip';
  tipEl.hidden = true;
  document.body.appendChild(tipEl);
  let tipTimer = null;
  let tipShownAt = 0;
  function hideTip() {
    clearTimeout(tipTimer);
    if (!tipEl.hidden) tipShownAt = Date.now();
    tipEl.hidden = true;
  }
  function showTip(target) {
    if (!target.isConnected) return;
    tipEl.innerHTML = `<span>${esc(target.dataset.tip)}</span>${kbdHtml(target.dataset.kbd)}`;
    tipEl.hidden = false;
    const r = target.getBoundingClientRect();
    const w = tipEl.offsetWidth; const h = tipEl.offsetHeight;
    let top = r.bottom + 8;
    if (top + h > window.innerHeight - 8) top = r.top - h - 8;
    const left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2));
    Object.assign(tipEl.style, { top: `${top}px`, left: `${left}px` });
  }
  function tipTargetFrom(node) {
    const t = node && node.closest && node.closest('[data-tip], [title]');
    if (!t || !(root.contains(t) || ctxMenu.contains(t))) return null;
    if (!t.dataset.tip && t.title) { t.dataset.tip = t.title; t.removeAttribute('title'); }
    return t.dataset.tip ? t : null;
  }
  document.addEventListener('pointerover', (e) => {
    if (interacting || e.buttons) return;
    const t = tipTargetFrom(e.target);
    if (!t) return;
    clearTimeout(tipTimer);
    // Enchaîner les survols d'une barre d'outils : l'infobulle suit sans nouveau délai.
    const delay = Date.now() - tipShownAt < 400 || !tipEl.hidden ? 0 : 450;
    tipTimer = setTimeout(() => showTip(t), delay);
  });
  document.addEventListener('pointerout', (e) => {
    const t = tipTargetFrom(e.target);
    if (t && !t.contains(e.relatedTarget)) hideTip();
  });
  document.addEventListener('pointerdown', hideTip, true);
  workspace.addEventListener('scroll', hideTip);

  // ------------------------------------------------------------- aide (tous les raccourcis)
  const HELP_GROUPS = [
    ['Insérer', [['Texte', 'T'], ['Titre', 'Maj+T'], ['Rectangle', 'R'], ['Ellipse', 'O'], ['Ligne', 'L'], ['Flèche', 'Maj+L'], ['Tableau', 'B'], ['Image', 'I']]],
    ['Édition', [['Annuler', 'Ctrl+Z'], ['Rétablir', 'Ctrl+Maj+Z'], ['Dupliquer', 'Ctrl+D'], ['Copier / coller', 'Ctrl+C'], ['Couper', 'Ctrl+X'], ['Tout sélectionner', 'Ctrl+A'], ['Supprimer', 'Suppr'], ['Modifier le texte', 'Entrée'], ['Quitter / désélectionner', 'Échap']]],
    ['Déplacer & organiser', [['Déplacer de 1 px', '←↑→↓'], ['Déplacer de 10 px', 'Maj+←↑→↓'], ['Avancer / reculer', 'Ctrl+↑'], ['Premier / arrière-plan', 'Ctrl+Maj+↑'], ['Verrouiller', 'Ctrl+Maj+L'], ['Masquer', 'Ctrl+Maj+H'], ['Sans magnétisme (en glissant)', 'Alt'], ['Garder les proportions', 'Maj']]],
    ['Aligner', [['À gauche', 'Alt+A'], ['Centre horizontal', 'Alt+H'], ['À droite', 'Alt+D'], ['En haut', 'Alt+W'], ['Centre vertical', 'Alt+V'], ['En bas', 'Alt+S']]],
    ['Texte (en édition)', [['Gras / italique / souligné', 'Ctrl+B'], ['Barré', 'Ctrl+Maj+X'], ['Liste à puces', 'Ctrl+Maj+8'], ['Liste numérotée', 'Ctrl+Maj+7'], ['Lien', 'Ctrl+K'], ['Effacer la mise en forme', 'Ctrl+Espace']]],
    ['Affichage', [['Cotes entre éléments (survol)', 'Alt'], ['Cotes permanentes', 'M'], ['Unité mm / px', 'U'], ['Grille magnétique', 'G'], ['Zoom + / −', '+'], ['Zoom 100 %', '0'], ['Ajuster à l\'écran', 'Maj+1'], ['Cette aide', '?']]],
  ];
  const helpPanel = document.createElement('div');
  helpPanel.className = 'dc-help';
  helpPanel.hidden = true;
  helpPanel.innerHTML = `
    <div class="dc-help-card" role="dialog" aria-label="Raccourcis clavier">
      <div class="dc-help-head"><strong>Raccourcis clavier</strong><button type="button" data-help-close aria-label="Fermer">×</button></div>
      <div class="dc-help-grid">${HELP_GROUPS.map(([title, rows]) => `
        <section><h4>${title}</h4>${rows.map(([label, k]) => `<p><span>${label}</span>${k.includes('←') ? `<span class="dc-kbd"><kbd>${k.replace('Maj+', IS_MAC ? '⇧ ' : 'Maj ')}</kbd></span>` : kbdHtml(k)}</p>`).join('')}</section>`).join('')}
      </div>
    </div>`;
  document.body.appendChild(helpPanel);
  function toggleHelp(force) {
    helpPanel.hidden = force === undefined ? !helpPanel.hidden : !force;
    hideTip();
  }
  helpPanel.addEventListener('click', (e) => {
    if (e.target === helpPanel || e.target.closest('[data-help-close]')) toggleHelp(false);
  });

  // ------------------------------------------------------------- méta & sauvegarde
  function setMeta(key, value) {
    docMeta[key] = value;
    if (key === 'client_id' || key === 'title') { clearTimeout(setMeta._t); setMeta._t = setTimeout(() => { refreshValues(); renderVarPane(); }, 200); }
    if (key === 'page_format' || key === 'page_orientation') {
      const size = cfg.pageSizes[`${docMeta.page_format}:${docMeta.page_orientation}`];
      if (size) { [pageW, pageH] = size; }
      renderAll();
      fitZoom();
    }
    scheduleSave();
  }

  function csrf() { const el = root.querySelector('[name=csrfmiddlewaretoken]'); return el ? el.value : ''; }
  const statusEl = document.querySelector('[data-dc-save-status]');
  function setStatus(text, isError) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.style.color = isError ? 'var(--billio-danger)' : 'var(--billio-muted)';
  }

  let saveTimer = null;
  let dirty = false;
  function payload() {
    const body = new FormData();
    body.append('csrfmiddlewaretoken', csrf());
    body.append('document_id', root.dataset.documentId);
    body.append('title', docMeta.title);
    body.append('document_type', docMeta.document_type);
    body.append('client_id', docMeta.client_id);
    body.append('status', docMeta.status);
    body.append('style_config', JSON.stringify({ page_format: docMeta.page_format, page_orientation: docMeta.page_orientation }));
    body.append('canvas_data', JSON.stringify({ pages: state.pages, fields: customFields, sources: docSources }));
    return body;
  }
  function scheduleSave() {
    dirty = true;
    setStatus('Modifications non enregistrées…');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 900);
  }
  async function save() {
    clearTimeout(saveTimer);
    if (editing) {
      // Capture le contenu en cours de frappe sans quitter le mode édition.
      const found = findElement(editing.id);
      const node = nodeFor(editing.id);
      if (found && node && found.el.type === 'text') found.el.html = node.querySelector('.dc-text-content').innerHTML;
      if (found && node && found.el.type === 'table') syncEditingTable(found.el);
    }
    dirty = false;
    setStatus('Enregistrement…');
    try {
      const res = await fetch(root.dataset.saveUrl, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: payload() });
      if (!res.ok) throw new Error('save');
      const t = new Date();
      setStatus(`Enregistré à ${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`);
      const titleEl = document.querySelector('.billio-page-title');
      if (titleEl && docMeta.title) titleEl.textContent = docMeta.title;
    } catch (err) {
      dirty = true;
      setStatus('Erreur d\'enregistrement — nouvel essai…', true);
      saveTimer = setTimeout(save, 4000);
    }
  }
  window.addEventListener('pagehide', () => {
    if (dirty && navigator.sendBeacon) navigator.sendBeacon(root.dataset.saveUrl, payload());
  });

  const saveTemplateBtn = document.querySelector('[data-dc-save-template]');
  if (saveTemplateBtn) {
    saveTemplateBtn.addEventListener('click', async () => {
      const name = prompt('Nom du modèle', docMeta.title);
      if (!name) return;
      await save();
      const body = new FormData();
      body.append('name', name);
      const res = await fetch(saveTemplateBtn.dataset.url, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body });
      setStatus(res.ok ? `Modèle « ${name} » enregistré` : 'Impossible d\'enregistrer le modèle', !res.ok);
    });
  }

  async function deleteDocument() {
    if (!confirm('Supprimer définitivement ce document ?')) return;
    const res = await fetch(meta.deleteUrl, { method: 'POST', headers: { 'X-CSRFToken': csrf() } });
    if (res.ok) window.location.href = meta.listUrl;
  }

  // ------------------------------------------------------------- init
  renderAll();
  requestAnimationFrame(() => {
    fitZoom();
    // Les textes des modèles ont une hauteur estimée : on l'ajuste au contenu réel.
    state.pages.forEach((p) => p.elements.forEach(growText));
    renderSelection();
    // Les tableaux ont pu être réajustés au premier rendu : on repart d'un historique propre.
    history.stack = [JSON.stringify(state.pages)];
    history.index = 0;
    updateToolbar();
  });
  window.addEventListener('resize', () => { if (zoom > (workspace.clientWidth - 120) / pageW) fitZoom(); });
})();
