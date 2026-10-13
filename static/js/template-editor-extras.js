/* Éditeur de modèle de facture / devis — compléments :
   1. Tableau des lignes : style prêt à l'emploi, couleurs, densité, colonnes visibles, total mis en avant.
   2. Blocs (widgets) insérés dans le HTML du modèle à un emplacement choisi.
   3. Déplacement visuel des éléments (glisser dans l'aperçu, flèches, largeur, espacements).
   Tout est stocké dans le HTML / CSS du modèle (blocs repérés par des marqueurs) : l'aperçu
   et le PDF (WeasyPrint) utilisent exactement le même rendu, sans code serveur dédié.
   Fusionné dans le composant Alpine `templateEditor()` (templates/templates_app/editor.html). */
(function () {
  'use strict';

  const ACCENT = '{{ accent_color|default:"#111827" }}';
  const TABLE_START = '/* billio:tableau ';
  const TABLE_END = '/* billio:fin-tableau */';
  const BLOCKS_START = '/* billio:blocs */';
  const BLOCKS_END = '/* billio:fin-blocs */';

  // ------------------------------------------------------------------ tableau des lignes
  const TABLE_PRESETS = [
    { key: '', label: "D'origine", head: '', headText: '', stripe: '', border: '', borders: '' },
    { key: 'lines', label: 'Lignes', head: 'transparent', headText: '#6b7280', stripe: '', border: '#e5e7eb', borders: 'rows' },
    { key: 'striped', label: 'Rayé', head: 'accent', headText: '#ffffff', stripe: '#f8fafc', border: 'transparent', borders: 'none' },
    { key: 'grid', label: 'Grille', head: '#f3f4f6', headText: '#111827', stripe: '', border: '#d1d5db', borders: 'all' },
    { key: 'minimal', label: 'Minimal', head: 'transparent', headText: '#111827', stripe: '', border: 'transparent', borders: 'none' },
    { key: 'soft', label: 'Doux', head: '#f5f3ff', headText: 'accent', stripe: '#fafafa', border: '#ede9fe', borders: 'rows' },
  ];
  const DENSITY = { compact: '5px 8px', normal: '', comfy: '15px 12px' };
  const tableDefaults = () => ({
    preset: '', head: '', headText: '', stripe: '', border: '', borders: '', density: 'normal', fontSize: '',
    upper: '', hideCols: [], hideDesc: false, totalBg: '', totalText: '', numbersRight: false,
  });

  // ------------------------------------------------------------------ blocs (widgets)
  // html(id) : HTML inséré ; vars : variables du modèle créées pour ses textes (modifiables ensuite).
  const BLOCKS = [
    { type: 'note', label: 'Encadré / note', icon: 'sticky-note', desc: 'Une information mise en avant (délais, garantie…).',
      vars: [['text', 'textarea', 'Texte', 'Les travaux démarrent à réception de l\'acompte.']],
      html: (v) => `<div class="bw-note">{{ ${v.text}|linebreaksbr }}</div>` },
    { type: 'text', label: 'Texte libre', icon: 'type', desc: 'Un paragraphe à l\'endroit de votre choix.',
      vars: [['title', 'text', 'Titre', 'À propos'], ['text', 'textarea', 'Texte', 'Présentez votre activité ou votre démarche en quelques lignes.']],
      html: (v) => `<div class="bw-text">{% if ${v.title} %}<p class="bw-title">{{ ${v.title} }}</p>{% endif %}<p>{{ ${v.text}|linebreaksbr }}</p></div>` },
    { type: 'banner', label: 'Bandeau', icon: 'megaphone', desc: 'Une bande colorée avec un message court.',
      vars: [['text', 'text', 'Message', 'Merci pour votre confiance — à très bientôt !']],
      html: (v) => `<div class="bw-banner">{{ ${v.text} }}</div>` },
    { type: 'due', label: 'Échéance mise en avant', icon: 'calendar-clock', desc: 'Montant et date de paiement bien visibles.',
      vars: [['label', 'text', 'Libellé', 'À régler avant le']],
      html: (v) => `<div class="bw-due"><span>{{ ${v.label} }} <strong>{{ due_date }}</strong></span><strong class="bw-due-amount">{{ total_amount|money:currency }}</strong></div>` },
    { type: 'bank', label: 'Coordonnées bancaires', icon: 'landmark', desc: 'IBAN et BIC de votre organisation.',
      vars: [['title', 'text', 'Titre', 'Paiement par virement']],
      html: (v) => `<div class="bw-bank"><p class="bw-title">{{ ${v.title} }}</p>{% if organization_bank_name %}<p>{{ organization_bank_name }}</p>{% endif %}{% if organization_iban %}<p><span class="bw-muted">IBAN</span> {{ organization_iban }}</p>{% else %}<p class="bw-muted">Renseignez votre IBAN dans Paramètres › Coordonnées de paiement.</p>{% endif %}{% if organization_bic_swift %}<p><span class="bw-muted">BIC</span> {{ organization_bic_swift }}</p>{% endif %}</div>` },
    { type: 'signature', label: 'Signatures', icon: 'pen-line', desc: 'Deux zones de signature côte à côte.',
      vars: [['left', 'text', 'Zone de gauche', 'Le prestataire'], ['right', 'text', 'Zone de droite', 'Le client — « Bon pour accord »']],
      html: (v) => `<table class="bw-sign"><tr><td><p class="bw-title">{{ ${v.left} }}</p><div class="bw-sign-box"></div></td><td><p class="bw-title">{{ ${v.right} }}</p><div class="bw-sign-box"></div></td></tr></table>` },
    { type: 'stamp', label: 'Tampon', icon: 'stamp', desc: '« Payé », « Copie »… en diagonale. Option : seulement si la facture est payée.',
      vars: [['text', 'text', 'Texte du tampon', 'PAYÉ'], ['only_paid', 'text', 'Seulement si payée (oui / non)', 'oui']],
      html: (v) => `{% if ${v.only_paid} != "oui" or is_paid %}<div class="bw-stamp-wrap"><span class="bw-stamp">{{ ${v.text} }}</span></div>{% endif %}` },
    { type: 'contact', label: 'Contact', icon: 'contact', desc: 'Votre email et téléphone pour toute question.',
      vars: [['title', 'text', 'Titre', 'Une question ?']],
      html: (v) => `<div class="bw-contact"><p class="bw-title">{{ ${v.title} }}</p><p>{{ organization_name }}{% if organization_email %} · {{ organization_email }}{% endif %}{% if organization_phone %} · {{ organization_phone }}{% endif %}</p></div>` },
    { type: 'terms', label: 'Conditions générales', icon: 'scroll-text', desc: 'Un texte long en petits caractères.',
      vars: [['text', 'textarea', 'Texte', 'Conditions générales de vente disponibles sur demande. Toute commande vaut acceptation des présentes conditions.']],
      html: (v) => `<div class="bw-terms">{{ ${v.text}|linebreaksbr }}</div>` },
    { type: 'divider', label: 'Séparateur', icon: 'minus', desc: 'Une ligne horizontale.', vars: [],
      html: () => '<hr class="bw-divider">' },
    { type: 'spacer', label: 'Espace', icon: 'move-vertical', desc: 'De l\'air entre deux parties (hauteur en px).',
      vars: [['height', 'number', 'Hauteur (px)', '24']],
      html: (v) => `<div class="bw-spacer" style="height:{{ ${v.height}|default:"24" }}px"></div>` },
  ];
  const POSITIONS = [
    ['top', 'Tout en haut'], ['before_items', 'Avant le tableau'], ['after_items', 'Après le tableau'],
    ['after_totals', 'Après les totaux'], ['before_footer', 'Avant le pied de page'], ['bottom', 'Tout en bas'],
  ];

  const BLOCKS_CSS = `
.bw-note { margin: 16px 0; padding: 12px 14px; border-left: 3px solid ${ACCENT}; background: #f8fafc; border-radius: 0 8px 8px 0; font-size: 12px; color: #374151; }
.bw-text { margin: 16px 0; font-size: 12px; color: #374151; }
.bw-title { font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #6b7280; margin: 0 0 5px !important; }
.bw-muted { color: #6b7280; }
.bw-banner { margin: 16px 0; padding: 11px 16px; background: ${ACCENT}; color: #fff; border-radius: 8px; font-weight: 600; text-align: center; font-size: 12.5px; }
.bw-due { margin: 16px 0; padding: 12px 16px; border: 1.5px solid ${ACCENT}; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; font-size: 12.5px; }
.bw-due-amount { font-size: 17px; color: ${ACCENT}; }
.bw-bank, .bw-contact { margin: 16px 0; padding: 12px 14px; background: #f9fafb; border-radius: 8px; font-size: 11.5px; }
.bw-bank p, .bw-contact p, .bw-text p { margin: 0; }
.bw-sign { width: 100%; border-collapse: separate; border-spacing: 14px 0; margin: 18px -14px; }
.bw-sign td { width: 50%; vertical-align: top; padding: 0; border: none; }
.bw-sign-box { height: 80px; border: 1px dashed #9ca3af; border-radius: 8px; }
.bw-stamp-wrap { text-align: right; margin: 10px 0; }
.bw-stamp { display: inline-block; padding: 6px 18px; border: 3px solid #16a34a; color: #16a34a; font-weight: 800; font-size: 20px; letter-spacing: .12em; border-radius: 8px; transform: rotate(-8deg); opacity: .85; }
.bw-terms { margin: 16px 0; font-size: 9px; line-height: 1.5; color: #6b7280; text-align: justify; }
.bw-divider { border: none; border-top: 1px solid #e5e7eb; margin: 16px 0; }
.bw-spacer { display: block; }
`;

  // ------------------------------------------------------------------ mixin
  window.templateEditorExtras = function () {
    return {
      tableSettings: tableDefaults(),
      tableInfo: { found: false, selector: '', cols: [], descSelector: '', totalSelector: '' },
      tablePresets: TABLE_PRESETS,
      blockTypes: BLOCKS,
      blockPositions: POSITIONS,
      blockPosition: 'after_totals',
      drag: null,

      // ---------------- découpe / reconstitution du CSS
      splitExtraCss(css) {
        let table = tableDefaults();
        const ts = css.indexOf(TABLE_START);
        const te = css.indexOf(TABLE_END);
        if (ts >= 0 && te > ts) {
          const header = css.slice(ts + TABLE_START.length, css.indexOf('*/', ts));
          try { table = Object.assign(tableDefaults(), JSON.parse(header)); } catch (e) { /* bloc ancien */ }
          css = css.slice(0, ts) + css.slice(te + TABLE_END.length);
        }
        const bs = css.indexOf(BLOCKS_START);
        const be = css.indexOf(BLOCKS_END);
        if (bs >= 0 && be > bs) css = css.slice(0, bs) + css.slice(be + BLOCKS_END.length);
        return { css: css.trimEnd(), table };
      },
      extraCss() {
        let out = '';
        const rules = this.tableRules();
        if (rules) out += `\n\n${TABLE_START}${JSON.stringify(this.tableSettings)} */\n${rules}\n${TABLE_END}\n`;
        if (this.blocks().length) out += `\n${BLOCKS_START}${BLOCKS_CSS}${BLOCKS_END}\n`;
        return out;
      },

      // ---------------- tableau : détection dans l'aperçu
      detectTable(doc) {
        const tables = [...doc.querySelectorAll('table')].filter((t) => !t.closest('.bw-sign'));
        const items = tables.find((t) => [...t.classList].some((c) => /items?$/.test(c)))
          || tables.filter((t) => t.querySelector('thead th')).sort((a, b) => b.querySelectorAll('tbody tr').length - a.querySelectorAll('tbody tr').length)[0];
        if (!items) { this.tableInfo = { found: false, selector: '', cols: [], descSelector: '', totalSelector: '' }; return; }
        const selector = this.selectorFor(items);
        const cols = [...items.querySelectorAll('thead th')].map((th, i) => ({ index: i + 1, label: (th.textContent || '').trim().replace(/\s+/g, ' ') || `Colonne ${i + 1}` }));
        const desc = items.querySelector('[class*="item-desc"], [class*="desc"] small');
        const totals = tables.find((t) => [...t.classList].some((c) => /totals?$/.test(c)));
        const grand = totals && (totals.querySelector('[class*="grand"], tr:last-child'));
        this.tableInfo = {
          found: true, selector, cols,
          descSelector: desc ? this.selectorFor(desc) : '',
          totalSelector: grand ? this.selectorFor(grand) : '',
        };
      },

      // ---------------- tableau : règles CSS
      tableRules() {
        const t = this.tableSettings;
        const s = this.tableInfo.selector;
        if (!s) return '';
        const r = [];
        // « accent » = couleur principale du modèle (variable rendue par Django dans le CSS).
        const imp = (v) => `${v === 'accent' ? ACCENT : v} !important`;
        if (t.head) r.push(`${s} th { background: ${imp(t.head)}; }`);
        if (t.headText) r.push(`${s} th { color: ${imp(t.headText)}; }`);
        if (t.upper === 'yes') r.push(`${s} th { text-transform: uppercase !important; letter-spacing: .06em !important; }`);
        if (t.upper === 'no') r.push(`${s} th { text-transform: none !important; letter-spacing: 0 !important; }`);
        const line = (v, d) => (v === 'accent' ? ACCENT : (v || d));
        if (t.borders === 'rows') r.push(`${s} th, ${s} td { border: none !important; border-bottom: 1px solid ${line(t.border, '#e5e7eb')} !important; }`);
        if (t.borders === 'all') r.push(`${s} { border-collapse: collapse !important; } ${s} th, ${s} td { border: 1px solid ${line(t.border, '#d1d5db')} !important; }`);
        if (t.borders === 'none') r.push(`${s} th, ${s} td { border: none !important; }`);
        if (t.stripe) r.push(`${s} tbody tr:nth-child(even) td { background: ${imp(t.stripe)}; }`);
        if (DENSITY[t.density]) r.push(`${s} th, ${s} td { padding: ${imp(DENSITY[t.density])}; }`);
        if (t.fontSize) r.push(`${s} td, ${s} th { font-size: ${imp(`${t.fontSize}px`)}; }`);
        if (t.numbersRight) r.push(`${s} td:not(:first-child), ${s} th:not(:first-child) { text-align: right !important; }`);
        (t.hideCols || []).forEach((i) => r.push(`${s} th:nth-child(${i}), ${s} td:nth-child(${i}) { display: none !important; }`));
        if (t.hideDesc && this.tableInfo.descSelector) r.push(`${this.tableInfo.descSelector} { display: none !important; }`);
        if (this.tableInfo.totalSelector && (t.totalBg || t.totalText)) {
          const g = this.tableInfo.totalSelector;
          r.push(`${g}, ${g} td { ${t.totalBg ? `background: ${imp(t.totalBg)};` : ''} ${t.totalText ? `color: ${imp(t.totalText)};` : ''} }`);
        }
        return r.join('\n');
      },
      setTable(patch) {
        this.tableSettings = Object.assign({}, this.tableSettings, patch);
        this.touch();
        this.refresh();
      },
      applyTablePreset(p) {
        this.setTable({ preset: p.key, head: p.head, headText: p.headText, stripe: p.stripe, border: p.border, borders: p.borders });
      },
      toggleCol(index) {
        const hide = new Set(this.tableSettings.hideCols || []);
        if (hide.has(index)) hide.delete(index); else hide.add(index);
        this.setTable({ hideCols: [...hide].sort((a, b) => a - b) });
      },
      resetTable() { this.tableSettings = tableDefaults(); this.touch(); this.refresh(true); },
      colorValue(v, fallback) { return /^#[0-9a-f]{6}$/i.test(v || '') ? v : fallback; },

      // ---------------- blocs : liste, insertion, déplacement, suppression
      blocks() {
        const out = [];
        const re = /<!-- bw:(\w+):(\w+):(\w+) -->/g;
        let m;
        while ((m = re.exec(this.html))) {
          const def = BLOCKS.find((b) => b.type === m[2]);
          out.push({ id: m[1], type: m[2], position: m[3], label: def ? def.label : m[2], icon: def ? def.icon : 'square' });
        }
        return out;
      },
      blockVars(id) { return this.schema.filter((f) => f.name && f.name.startsWith(`bw_${id}_`)); },
      anchorIndex(html, position) {
        const find = (re) => { const m = re.exec(html); return m ? m.index : -1; };
        const endOfTable = (start) => (start < 0 ? -1 : html.indexOf('</table>', start) + '</table>'.length);
        const itemsStart = find(/<table[^>]*class="[^"]*items?\b[^"]*"/);
        if (position === 'before_items' && itemsStart >= 0) return itemsStart;
        if (position === 'after_items' && itemsStart >= 0) return endOfTable(itemsStart);
        if (position === 'after_totals') {
          const totalsStart = find(/<table[^>]*class="[^"]*totals?\b[^"]*"/);
          if (totalsStart >= 0) {
            let end = endOfTable(totalsStart);
            // Totaux rangés dans une grille (<table class="grid">…<td>TOTAUX</td></tr></table>) : après la grille.
            const rest = html.slice(end).match(/^\s*<\/td>\s*<\/tr>\s*<\/table>/);
            if (rest) end += rest[0].length;
            return end;
          }
          if (itemsStart >= 0) return endOfTable(itemsStart);
        }
        if (position === 'before_footer') {
          const footer = find(/<div[^>]*class="[^"]*footer[^"]*"/);
          if (footer >= 0) return footer;
        }
        if (position === 'top') {
          const root = /<div[^>]*>/.exec(html);
          if (root) return root.index + root[0].length;
          return 0;
        }
        const last = html.lastIndexOf('</div>');
        return last >= 0 ? last : html.length;
      },
      insertBlock(type, position) {
        const def = BLOCKS.find((b) => b.type === type);
        if (!def) return;
        const id = Math.random().toString(36).slice(2, 8);
        const vars = {};
        def.vars.forEach(([key, kind, label, value]) => {
          const name = `bw_${id}_${key}`;
          vars[key] = name;
          this.schema.push({ name, type: kind, label: `${def.label} — ${label}` });
          this.defaults[name] = value;
        });
        const pos = position || this.blockPosition;
        const chunk = `\n<!-- bw:${id}:${type}:${pos} -->\n${def.html(vars)}\n<!-- /bw:${id} -->\n`;
        const at = this.anchorIndex(this.html, pos);
        this.html = this.html.slice(0, at) + chunk + this.html.slice(at);
        this.layoutId = null;
        this.touch();
        this.refresh(true);
        // La carte du nouveau bloc (icône, ↑ ↓, corbeille) est ajoutée par x-for : ses icônes
        // Lucide doivent être dessinées, sinon les boutons apparaissent vides.
        this.$nextTick(() => window.lucide && lucide.createIcons());
      },
      blockChunk(id) {
        const re = new RegExp(`\\n?<!-- bw:${id}:\\w+:\\w+ -->[\\s\\S]*?<!-- /bw:${id} -->\\n?`);
        const m = re.exec(this.html);
        return m ? { start: m.index, end: m.index + m[0].length, text: m[0] } : null;
      },
      removeBlock(id) {
        const chunk = this.blockChunk(id);
        if (!chunk) return;
        this.html = this.html.slice(0, chunk.start) + this.html.slice(chunk.end);
        this.schema = this.schema.filter((f) => !(f.name || '').startsWith(`bw_${id}_`));
        Object.keys(this.defaults).forEach((k) => { if (k.startsWith(`bw_${id}_`)) delete this.defaults[k]; });
        this.touch();
        this.refresh(true);
      },
      moveBlock(id, position) {
        const chunk = this.blockChunk(id);
        if (!chunk) return;
        let html = this.html.slice(0, chunk.start) + this.html.slice(chunk.end);
        const text = chunk.text.replace(/<!-- bw:(\w+):(\w+):\w+ -->/, `<!-- bw:$1:$2:${position} -->`);
        const at = this.anchorIndex(html, position);
        html = html.slice(0, at) + text + html.slice(at);
        this.html = html;
        this.touch();
        this.refresh(true);
      },
      shiftBlock(id, dir) {
        const list = this.blocks();
        const i = list.findIndex((b) => b.id === id);
        const order = POSITIONS.map((p) => p[0]);
        const next = order[Math.max(0, Math.min(order.length - 1, order.indexOf(list[i].position) + dir))];
        if (next !== list[i].position) this.moveBlock(id, next);
      },
      positionLabel(key) { return (POSITIONS.find((p) => p[0] === key) || ['', key])[1]; },

      // ---------------- déplacement visuel
      offsetOf(axis) { return parseFloat(this.styleOf(axis === 'x' ? 'left' : 'top')) || 0; },
      setStyles(props) {
        if (!this.sel) return;
        const current = { ...(this.overrides[this.sel.selector] || {}) };
        Object.entries(props).forEach(([k, v]) => { if (v === null || v === '') delete current[k]; else current[k] = v; });
        this.overrides = { ...this.overrides, [this.sel.selector]: current };
        const doc = this.frameDoc();
        if (doc) doc.querySelectorAll(this.sel.selector).forEach((n) => Object.entries(props).forEach(([k, v]) => (v === null || v === '' ? n.style.removeProperty(k) : n.style.setProperty(k, v, 'important'))));
        this.touch();
        this.refresh();
      },
      moveBy(dx, dy) {
        const x = Math.round(this.offsetOf('x') + dx);
        const y = Math.round(this.offsetOf('y') + dy);
        this.setStyles({ position: 'relative', left: `${x}px`, top: `${y}px` });
      },
      setOffset(axis, value) {
        const n = Math.round(parseFloat(value) || 0);
        this.setStyles({ position: 'relative', [axis === 'x' ? 'left' : 'top']: `${n}px` });
      },
      resetPosition() { this.setStyles({ position: null, left: null, top: null }); },
      bindDrag(doc) {
        doc.addEventListener('mousedown', (e) => {
          const el = e.target.closest && e.target.closest('[data-te-sel]');
          if (!el || !this.sel || e.button !== 0) return;
          e.preventDefault();
          this.drag = { x: e.clientX, y: e.clientY, left: this.offsetOf('x'), top: this.offsetOf('y'), moved: false };
          doc.body.style.userSelect = 'none';
        });
        doc.addEventListener('mousemove', (e) => {
          if (!this.drag) return;
          const dx = e.clientX - this.drag.x;
          const dy = e.clientY - this.drag.y;
          if (Math.abs(dx) + Math.abs(dy) > 3) this.drag.moved = true;
          if (!this.drag.moved) return;
          doc.querySelectorAll(this.sel.selector).forEach((n) => {
            n.style.setProperty('position', 'relative', 'important');
            n.style.setProperty('left', `${Math.round(this.drag.left + dx)}px`, 'important');
            n.style.setProperty('top', `${Math.round(this.drag.top + dy)}px`, 'important');
          });
        });
        doc.addEventListener('mouseup', (e) => {
          if (!this.drag) return;
          const { moved, left, top, x, y } = this.drag;
          this.drag = null;
          doc.body.style.userSelect = '';
          if (!moved) return;
          this._justDragged = true;
          setTimeout(() => { this._justDragged = false; }, 50);
          this.setStyles({ position: 'relative', left: `${Math.round(left + e.clientX - x)}px`, top: `${Math.round(top + e.clientY - y)}px` });
        });
      },
    };
  };
})();
