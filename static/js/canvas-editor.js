/*
 * Éditeur de modèles en mise en page libre (templates/templates_app/canvas_editor.html).
 * La mise en page est un objet JSON (blocs, formes, images, tableau, couleurs) validé et
 * transformé en HTML/CSS côté serveur (apps/templates_app/canvas.py) : ce fichier ne fait
 * qu'éditer cet objet et en montrer un aperçu fidèle.
 */
function canvasEditor() {
    const cfg = JSON.parse(document.getElementById('canvas-editor-config').textContent);
    const URLS = window.CANVAS_EDITOR_URLS;
    const SNAP = 4, GUIDE = 6;
    const clone = (o) => JSON.parse(JSON.stringify(o));
    const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const uid = () => 'b' + Math.random().toString(16).slice(2, 10);
    const MODE_KEY = 'billio_editor_mode';
    let storedMode = null;
    try { storedMode = localStorage.getItem(MODE_KEY); } catch (e) { /* stockage indisponible */ }

    // Petites pages schématiques des décors prêts à l'emploi (30 × 42).
    const pg = (inner) => `<rect width="30" height="42" rx="2" class="pg"/>${inner}`;

    return {
        name: cfg.name, isDefault: cfg.isDefault, accent: cfg.accent, font: cfg.font, fonts: cfg.fonts, fontStacks: cfg.fontStacks,
        texts: cfg.texts, palette: cfg.palette, previews: cfg.previews, canvas: clone(cfg.canvas),
        pageWidth: cfg.pageWidth, documentType: 'invoice', selectedId: null, scale: 1, guide: null,
        history: [], future: [], dirty: false, saving: false, error: '', warning: '', dragNew: null, dropHint: null,
        advanced: storedMode === 'advanced', libTab: 'blocks', shapeTarget: 'header',
        shapes: cfg.shapes, tableVars: cfg.tableVariables || [], tablePresets: cfg.tablePresets || [], docVars: cfg.docVariables || [],
        assets: cfg.assets || [], uploading: false, uploadError: '', activeCol: null, colEdges: [], itemsHeight: 260,
        icons: { logo: 'image', title: 'heading-1', issuer: 'building-2', client: 'user', meta: 'calendar', total_due: 'badge-euro',
                 subject: 'text-quote', totals: 'sigma', payment: 'landmark', legal: 'scale', text: 'type', divider: 'minus' },
        colorTokens: ['', 'accent', 'secondary', 'ink', 'white', 'black', 'muted'],
        colorNames: { '': 'Automatique', accent: 'Accent', secondary: 'Secondaire', ink: 'Texte', white: 'Blanc', black: 'Noir', muted: 'Gris' },
        decorPresets: [
            { key: 'bands', label: 'Filets haut et bas', icon: pg('<rect width="30" height="2.5" class="a"/><rect y="39.5" width="30" height="2.5" class="a"/>') },
            { key: 'banner', label: 'Bandeau d\'en-tête', icon: pg('<rect width="30" height="9" class="a"/>') },
            { key: 'wave', label: 'Vagues', icon: pg('<path d="M0,0H30V6C24,10 18,4 12,7C7,9.5 3,10 0,8Z" class="a"/><path d="M0,42H30V37C22,33 10,40 0,36Z" class="b"/>') },
            { key: 'diagonal', label: 'Diagonale', icon: pg('<path d="M0,0H30V5L0,11Z" class="a"/>') },
            { key: 'facets', label: 'Facettes en coin', icon: pg('<path d="M30,0V9L21,4ZM30,0H17L24,4Z" class="a"/><path d="M0,42V35L8,39ZM0,42H11L5,39Z" class="b"/>') },
            { key: 'side', label: 'Bande latérale', icon: pg('<rect width="3" height="42" class="a"/>') },
            { key: 'frame', label: 'Cadre de page', icon: pg('<rect x="1.5" y="1.5" width="27" height="39" rx="1" fill="none" class="s"/>') },
            { key: 'card', label: 'Page colorée + carte', icon: '<rect width="30" height="42" rx="2" class="a"/><rect x="2" y="2" width="26" height="38" rx="2.5" fill="#fff"/>' },
            { key: 'blobs', label: 'Taches douces', icon: pg('<ellipse cx="25" cy="4" rx="7" ry="6" class="a" opacity=".35"/><ellipse cx="27" cy="9" rx="4" ry="3.5" class="a" opacity=".55"/>') },
        ],

        init() {
            if (!this.canvas.colors.page) this.canvas.colors.page = '#ffffff';
            this.fit();
            this.$nextTick(() => { this.fitBands(); this.measureCols(); });
            window.addEventListener('resize', () => this.fit());
            // La largeur de la zone n'est définitive qu'une fois la page posée (panneaux, polices) : on réajuste à chaque changement.
            if (window.ResizeObserver && this.$refs.stage) new ResizeObserver(() => this.fit()).observe(this.$refs.stage);
            window.addEventListener('beforeunload', (e) => { if (this.dirty) { e.preventDefault(); e.returnValue = ''; } });
            this.$watch('selectedId', () => { this.icons_(); this.measureCols(); });
            this.$watch('advanced', () => this.icons_());
            this.icons_();
        },
        icons_() { this.$nextTick(() => window.lucide && lucide.createIcons()); },
        setMode(advanced) {
            this.advanced = advanced;
            try { localStorage.setItem(MODE_KEY, advanced ? 'advanced' : 'simple'); } catch (e) { /* stockage indisponible */ }
        },
        fit() {
            const width = this.$refs.stage ? this.$refs.stage.clientWidth - 48 : this.pageWidth;
            this.scale = Math.min(1, Math.max(0.45, width / this.pageWidth));
        },
        refit() { this.$nextTick(() => requestAnimationFrame(() => { this.fitBands(); this.measureCols(); })); },
        bottomOf(band) {
            let bottom = 24;
            // Les décors passent derrière : un nouveau bloc se pose par-dessus, pas en dessous.
            this.$refs.page.querySelectorAll(`[data-band=${band}] .ed-block:not(.is-decor)`).forEach((el) => { bottom = Math.max(bottom, el.offsetTop + el.offsetHeight + 16); });
            return bottom;
        },
        fitBands() {
            if (!this.$refs.page) return;
            for (const band of ['header', 'footer']) {
                let needed = 60;
                this.$refs.page.querySelectorAll(`[data-band=${band}] .ed-block:not(.is-decor)`).forEach((el) => {
                    needed = Math.max(needed, el.offsetTop + el.offsetHeight + 16);
                });
                if (needed > this.canvas.heights[band]) this.canvas.heights[band] = Math.min(900, Math.ceil(needed / SNAP) * SNAP);
            }
            if (this.$refs.items) this.itemsHeight = this.canvas.items === false ? 90 : this.$refs.items.offsetHeight;
        },

        // --- Couleurs-variables ---
        swatchTokens(auto) { return auto ? this.colorTokens : this.colorTokens.filter((t) => t); },
        previewColor(token) {
            const c = this.canvas.colors;
            return { accent: this.accent, secondary: c.secondary, ink: c.ink, white: '#ffffff', black: '#111827', muted: '#6b7280' }[token] || token || '';
        },
        cssColor(token) {
            return { accent: 'var(--accent)', secondary: 'var(--c2)', ink: 'var(--ink)', white: '#ffffff', black: '#111827', muted: '#6b7280' }[token] || (/^#[0-9a-f]{6}$/i.test(token || '') ? token : '');
        },
        colorTarget() { return this.selectedId === 'table' ? this.canvas.table : this.selected(); },
        getColor(prop) { const t = this.colorTarget(); return (t && t[prop]) || ''; },
        setColor(prop, value, record = true) {
            if (this.selectedId === 'table') { this.canvas.table[prop] = value; this.tableChanged(record); return; }
            this.update({ [prop]: value }, record);
        },

        // --- Formes et images ---
        isDecor(b) { return !!b && (b.type === 'shape' || (b.type === 'image' && b.behind)); },
        shapeDef(kind) { return this.shapes.find((s) => s.kind === kind) || this.shapes[0]; },
        shapeIcon(sh) {
            if (sh.path) return `<svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="${sh.path}" fill-rule="evenodd"/></svg>`;
            const body = { rect: '<rect x="8" y="22" width="84" height="56" rx="6"/>', ellipse: '<circle cx="50" cy="50" r="40"/>',
                           frame: '<rect x="10" y="10" width="80" height="80" rx="4" fill="none" stroke="currentColor" stroke-width="10"/>',
                           line: '<rect x="4" y="45" width="92" height="10" rx="3"/>', pill: '<rect x="4" y="30" width="92" height="40" rx="20"/>' }[sh.kind] || '';
            return `<svg viewBox="0 0 100 100">${body}</svg>`;
        },
        shapeSvg(b) {
            const w = b.w, h = b.h, kind = this.shapeDef(b.shape);
            const fill = this.previewColor(b.fill || 'accent'), op = (b.opacity || 100) / 100;
            let defs = '', paint = esc(fill);
            if (b.gradient) {
                const gid = `eg${b.id}`;
                defs = `<defs><linearGradient id="${gid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${esc(fill)}"/><stop offset="1" stop-color="${esc(this.previewColor(b.fill2 || 'secondary'))}"/></linearGradient></defs>`;
                paint = `url(#${gid})`;
            }
            let body, box;
            if (kind.path) {
                const t = [];
                if (b.flip_x) t.push('translate(100,0) scale(-1,1)');
                if (b.flip_y) t.push('translate(0,100) scale(1,-1)');
                body = `<g${t.length ? ` transform="${t.join(' ')}"` : ''}><path d="${kind.path}" fill="${paint}" fill-opacity="${op}"${b.shape === 'ring' ? ' fill-rule="evenodd"' : ''}/></g>`;
                box = 'viewBox="0 0 100 100"';
            } else {
                box = `viewBox="0 0 ${w} ${h}"`;
                if (b.shape === 'ellipse') body = `<ellipse cx="${w / 2}" cy="${h / 2}" rx="${w / 2}" ry="${h / 2}" fill="${paint}" fill-opacity="${op}"/>`;
                else if (b.shape === 'frame') {
                    const th = Math.max(1, Math.min(b.thickness || 6, Math.min(w, h) / 2));
                    body = `<rect x="${th / 2}" y="${th / 2}" width="${w - th}" height="${h - th}" rx="${Math.min(b.radius || 0, w / 2, h / 2)}" fill="none" stroke="${paint}" stroke-opacity="${op}" stroke-width="${th}"/>`;
                } else {
                    const r = b.shape === 'pill' ? h / 2 : Math.min(b.radius || 0, h / 2, w / 2);
                    body = `<rect width="${w}" height="${h}" rx="${r}" fill="${paint}" fill-opacity="${op}"/>`;
                }
            }
            return `<svg width="${w}" height="${h}" ${box} preserveAspectRatio="none" style="display:block">${defs}${body}</svg>`;
        },
        imageHtml(b) {
            const asset = this.assets.find((a) => a.id === b.asset);
            if (!asset) return '<span class="ed-placeholder">Image introuvable : choisissez-en une dans les réglages.</span>';
            const css = [`height:${b.h}px`, `object-fit:${b.fit}`, 'width:100%', 'display:block'];
            if (b.radius) css.push(`border-radius:${b.radius}px`);
            if (b.opacity < 100) css.push(`opacity:${b.opacity / 100}`);
            return `<img src="${esc(asset.url)}" alt="" style="${css.join(';')}">`;
        },
        targetFor(where) {
            if (where === 'page-top') return { band: 'page', anchor: 'top' };
            if (where === 'page-bottom') return { band: 'page', anchor: 'bottom' };
            return { band: where };
        },
        decorDefaults() {
            return { align: 'left', size: 'm', accent: false, color: '', bg: '', border: '', bw: 1, pad: 0, radius: 0, font: '', upper: false, tracking: 0 };
        },
        newShape(kind, where, patch = {}) {
            const def = this.shapeDef(kind);
            const w = Math.min(def.w, this.pageWidth);
            const x = w >= this.pageWidth - 40 ? 0 : Math.round((this.pageWidth - w) / 2);
            return Object.assign({ id: uid(), type: 'shape', x, y: 0, w, h: def.h, shape: kind, fill: 'accent', fill2: 'secondary',
                                   gradient: false, flip_x: false, flip_y: false, opacity: 100, thickness: 6 },
                                 this.decorDefaults(), this.targetFor(where), patch);
        },
        insertDecor(block) {
            // Après les décors existants (donc devant eux), mais avant les blocs de contenu.
            let at = 0;
            this.canvas.blocks.forEach((x, i) => { if (this.isDecor(x)) at = i + 1; });
            this.canvas.blocks.splice(at, 0, block);
        },
        addShape(kind, patch = {}) {
            this.snapshot();
            const block = this.newShape(kind, this.shapeTarget, patch);
            this.clamp(block);
            this.insertDecor(block);
            this.selectedId = block.id;
            this.refit();
        },
        addDecor(key) {
            this.snapshot();
            const W = this.pageWidth, H = cfg.pageHeight, add = (kind, where, patch) => { const b = this.newShape(kind, where, patch); this.clamp(b); this.insertDecor(b); return b; };
            let last;
            if (key === 'bands') { add('rect', 'page-top', { x: 0, w: W, h: 14 }); last = add('rect', 'page-bottom', { x: 0, w: W, h: 14 }); }
            else if (key === 'banner') last = add('rect', 'page-top', { x: 0, w: W, h: 150 });
            else if (key === 'wave') { add('wave', 'page-top', { x: 0, w: W, h: 130, fill: 'accent' }); last = add('wave_soft', 'page-bottom', { x: 0, w: W, h: 100, fill: 'secondary', flip_y: true }); }
            else if (key === 'diagonal') last = add('diagonal', 'page-top', { x: 0, w: W, h: 190 });
            else if (key === 'facets') { add('facets', 'page-top', { x: W - 300, w: 300, h: 250 }); last = add('facets', 'page-bottom', { x: 0, w: 260, h: 200, flip_x: true, flip_y: true, fill: 'secondary' }); }
            else if (key === 'side') last = add('rect', 'page-top', { x: 0, w: 48, h: H });
            else if (key === 'frame') last = add('frame', 'page-top', { x: 12, y: 12, w: W - 24, h: H - 24, thickness: 6 });
            else if (key === 'card') {
                this.canvas.colors.page = this.accent;
                last = add('rect', 'page-top', { x: 24, y: 24, w: W - 48, h: H - 48, fill: 'white', radius: 26 });
            } else if (key === 'blobs') { add('blob', 'page-top', { x: W - 200, y: 0, w: 260, h: 230, opacity: 20 }); last = add('blob', 'page-top', { x: W - 120, y: 60, w: 140, h: 130, opacity: 35, flip_x: true }); }
            this.selectedId = last ? last.id : null;
            this.refit();
        },
        addImage(asset) {
            this.snapshot();
            const w = Math.min(220, asset.w || 220);
            const h = asset.w ? Math.max(20, Math.round(w * (asset.h || asset.w) / asset.w)) : 120;
            const band = 'header';
            const bottom = Math.ceil(this.bottomOf(band) / SNAP) * SNAP;
            if (bottom + h + 20 > this.canvas.heights[band]) this.canvas.heights[band] = Math.min(900, bottom + h + 40);
            const block = Object.assign({ id: uid(), type: 'image', band, x: cfg.padding, y: bottom, w, h, asset: asset.id, fit: 'contain', opacity: 100, behind: false },
                                        this.decorDefaults());
            this.canvas.blocks.push(block);
            this.selectedId = block.id;
            this.refit();
        },
        async upload(event) {
            const file = event.target.files && event.target.files[0];
            event.target.value = '';
            if (!file) return;
            this.uploading = true; this.uploadError = '';
            const body = new FormData();
            body.append('file', file);
            const response = await fetch(URLS.upload, { method: 'POST', headers: { 'X-CSRFToken': this.csrf() }, body }).catch(() => null);
            const data = response ? await response.json().catch(() => ({})) : {};
            this.uploading = false;
            if (!response || !response.ok || !data.ok) { this.uploadError = data.error || 'Import impossible.'; return; }
            this.assets.unshift(data.asset);
            this.addImage(data.asset);
            this.icons_();
        },
        async deleteAsset(asset) {
            const used = this.canvas.blocks.some((b) => b.type === 'image' && b.asset === asset.id);
            const ok = typeof billioConfirm === 'function'
                ? await billioConfirm({ title: 'Supprimer cette image de la bibliothèque ?', message: used ? 'Elle est utilisée sur cette page : elle en sera retirée. Les modèles déjà enregistrés gardent leur copie.' : 'Les modèles déjà enregistrés gardent leur copie.', confirmLabel: 'Supprimer', icon: 'trash-2' })
                : true;
            if (!ok) return;
            const response = await fetch(URLS.assetDelete.replace('/0/', `/${asset.id}/`), { method: 'POST', headers: { 'X-CSRFToken': this.csrf() } });
            if (!response.ok) return;
            this.assets = this.assets.filter((a) => a.id !== asset.id);
            if (used) { this.snapshot(); this.canvas.blocks = this.canvas.blocks.filter((b) => !(b.type === 'image' && b.asset === asset.id)); }
        },
        layerOf(b) { return b.band === 'page' ? `page-${b.anchor || 'top'}` : b.band; },
        setLayer(where) {
            const b = this.selected();
            if (!b) return;
            this.snapshot();
            const target = this.targetFor(where);
            b.band = target.band;
            if (target.anchor) b.anchor = target.anchor; else delete b.anchor;
            b.y = 0;
            if (b.type === 'image' && b.band === 'page') b.behind = true;
            this.clamp(b);
            this.refit();
        },
        arrange(direction) {
            const list = this.canvas.blocks, i = list.findIndex((b) => b.id === this.selectedId);
            if (i < 0) return;
            const decor = list.map((b, k) => (this.isDecor(b) ? k : -1)).filter((k) => k >= 0);
            const pos = decor.indexOf(i), j = decor[pos + direction];
            if (j === undefined) return;
            this.snapshot();
            [list[i], list[j]] = [list[j], list[i]];
        },
        pageLayer() { return this.canvas.blocks.filter((b) => b.band === 'page'); },
        decorStyle(b) {
            // Même calcul que le serveur : accroché en bas = depuis le bas de la première page A4.
            const top = b.anchor === 'bottom' ? cfg.pageHeight - b.y - b.h : b.y;
            return `left:${b.x}px;top:${top}px;width:${b.w}px;height:${b.h}px`;
        },

        // --- Conformité ---
        missing() {
            const present = new Set(this.canvas.blocks.map((b) => b.type));
            const out = Object.entries(cfg.mandatory || {}).filter(([key]) => !present.has(key)).map(([key, label]) => ({ key, label }));
            if (this.canvas.items === false) out.unshift({ key: 'items', label: 'Tableau des lignes' });
            return out;
        },

        // --- Tableau des lignes ---
        varLabel(key) { return (this.tableVars.find((v) => v.key === key) || {}).label || key; },
        tableChanged(record = false) {
            if (record) this.snapshot(); else this.dirty = true;
            clearTimeout(this._tableTimer);
            this._tableTimer = setTimeout(() => this.refreshPreviews(), record ? 30 : 350);
        },
        presetActive(p) { return Object.entries(p.set).every(([k, v]) => this.canvas.table[k] === v); },
        presetStyle(p) {
            const s = p.set;
            const th = s.th_bg ? this.previewColor(s.th_bg) : (s.header === 'accent' ? this.accent : (s.header === 'soft' ? '#e5e7eb' : 'transparent'));
            const line = s.header === 'line' && !s.th_bg ? '#111827' : 'transparent';
            const zebra = s.stripes ? (s.stripe_color ? this.previewColor(s.stripe_color) : '#f3f4f6') : 'transparent';
            const border = s.borders === 'none' ? 'transparent' : (s.border_color ? this.previewColor(s.border_color) : '#e5e7eb');
            return `--th:${th};--line:${line};--zebra:${zebra};--bd:${border};--r:${s.radius ? 4 : 0}px;--grid:${s.borders === 'grid' ? 1 : 0}`;
        },
        applyTablePreset(p) { this.snapshot(); Object.assign(this.canvas.table, clone(p.set)); this.tableChanged(); },
        addColumn(key) {
            if (!key || this.canvas.table.columns.length >= 10) return;
            this.snapshot();
            const col = { key, label: key === 'perso' ? 'Colonne' : this.varLabel(key), align: 'auto', width: 0, strong: false };
            if (key === 'perso') col.text = '';
            this.canvas.table.columns.push(col);
            this.activeCol = this.canvas.table.columns.length - 1;
            this.tableChanged();
            this.icons_();
        },
        moveColumn(i, delta) {
            const cols = this.canvas.table.columns, j = i + delta;
            if (j < 0 || j >= cols.length) return;
            this.snapshot();
            [cols[i], cols[j]] = [cols[j], cols[i]];
            if (this.activeCol === i) this.activeCol = j;
            this.tableChanged();
        },
        removeColumn(i) {
            if (this.canvas.table.columns.length <= 1) return;
            this.snapshot();
            this.canvas.table.columns.splice(i, 1);
            this.activeCol = null;
            this.tableChanged();
        },
        insertVar(i, key) {
            const col = this.canvas.table.columns[i];
            const input = this.$root.querySelector(`input[data-col="${i}"]`);
            const token = `{${key}}`, text = col.text || '';
            const at = input && document.activeElement === input ? input.selectionStart : text.length;
            col.text = (text.slice(0, at) + token + text.slice(at)).slice(0, 200);
            this.tableChanged();
            this.$nextTick(() => { if (input) { input.focus(); input.setSelectionRange(at + token.length, at + token.length); } });
        },
        onTableClick(event) {
            const cell = event.target.closest('th, td');
            this.select('table');
            if (!cell || cell.colSpan > 1) return;
            this.activeCol = cell.cellIndex;
            this.icons_();
            this.$nextTick(() => {
                const card = this.$root.querySelector(`[data-col-card="${cell.cellIndex}"]`);
                if (card) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            });
        },
        measureCols() {
            this.$nextTick(() => requestAnimationFrame(() => {
                const wrap = this.$refs.items, table = wrap && wrap.querySelector('table');
                if (!table) { this.colEdges = []; return; }
                const heads = [...table.querySelectorAll('thead th')];
                this.tableBox = { left: table.offsetLeft, width: table.offsetWidth };
                this.colEdges = heads.slice(0, -1).map((th, i) => ({ i, x: table.offsetLeft + th.offsetLeft + th.offsetWidth, left: table.offsetLeft + th.offsetLeft, top: table.offsetTop, h: table.offsetHeight }));
            }));
        },
        startColResize(event, edge) {
            const col = this.canvas.table.columns[edge.i];
            if (!col) return;
            const before = clone(this.canvas), startX = event.clientX, startW = edge.x - edge.left, total = this.tableBox.width;
            this.activeCol = edge.i;
            const move = (e) => {
                const width = startW + (e.clientX - startX) / this.scale;
                col.width = Math.max(4, Math.min(70, Math.round(width / total * 100)));
                this.colEdges = this.colEdges.map((c) => (c.i === edge.i ? Object.assign({}, c, { x: c.left + width }) : c));
            };
            const up = () => {
                document.removeEventListener('pointermove', move);
                document.removeEventListener('pointerup', up);
                this.history.push(before); this.future = []; this.dirty = true;
                this.refreshPreviews();
            };
            document.addEventListener('pointermove', move);
            document.addEventListener('pointerup', up);
        },
        setItems(on) {
            this.snapshot();
            this.canvas.items = on;
            this.refit();
            this.icons_();
        },

        // --- Page ---
        pageHeight() {
            return Math.max(cfg.pageHeight, this.canvas.heights.header + this.canvas.heights.footer + this.itemsHeight);
        },
        pageStyle() {
            const font = this.font && this.fontStacks[this.font] ? `font-family:${this.fontStacks[this.font]};` : '';
            const c = this.canvas.colors;
            return `transform:scale(${this.scale});min-height:${this.pageHeight()}px;--accent:${this.accent};--c2:${c.secondary};--ink:${c.ink};--page:${c.page};`
                + `background:${c.page};color:var(--ink);--logo-h:52px;${font}`;
        },
        previewUrl() { return `${URLS.preview}?type=${this.documentType}`; },
        labelOf(b) {
            if (!b) return '';
            if (b.type === 'shape') return `Forme · ${this.shapeDef(b.shape).label}`;
            if (b.type === 'image') return b.behind ? 'Image (décor)' : 'Image';
            return (this.palette.find((p) => p.type === b.type) || {}).label || b.type;
        },
        blocksIn(band) { return this.canvas.blocks.filter((b) => b.band === band); },
        selected() { return this.canvas.blocks.find((b) => b.id === this.selectedId) || null; },
        select(id) { this.selectedId = id; if (id !== 'table') this.activeCol = null; },
        blockClasses(b) {
            return [`cv-b-${b.type}`, `al-${b.align}`, `sz-${b.size}`, b.accent ? 'is-accent' : '', this.isDecor(b) ? 'is-decor' : '',
                    b.id === this.selectedId ? 'is-selected' : ''].join(' ');
        },
        textHtml(text) {
            const vars = this.previews.vars || {};
            return esc(text).replace(/\{(\w+)\}/g, (m, key) => (key in vars ? `<span class="ed-varval">${esc(vars[key]) || '…'}</span>` : m));
        },
        blockHtml(b) {
            if (b.type === 'shape') return this.shapeSvg(b);
            if (b.type === 'image') return this.imageHtml(b);
            let html;
            if (b.type === 'text') html = `<p class="cv-text">${this.textHtml(b.text) || '<span class="ed-placeholder">Votre texte…</span>'}</p>`;
            else {
                html = this.previews[b.type] || '';
                if (!html.trim()) html = '<span class="ed-placeholder">(vide sur ce document)</span>';
            }
            const css = [], classes = ['cv-box'];
            if (b.color) { css.push(`color:${this.cssColor(b.color)}`); classes.push('has-color'); }
            if (b.bg) css.push(`background:${this.cssColor(b.bg)}`);
            if (b.border) css.push(`border:${b.bw || 1}px solid ${this.cssColor(b.border)}`);
            if (b.pad) css.push(`padding:${b.pad}px`);
            if (b.radius) css.push(`border-radius:${b.radius}px`);
            if (b.font && this.fontStacks[b.font]) css.push(`font-family:${this.fontStacks[b.font]}`);
            if (b.tracking) css.push(`letter-spacing:${(b.tracking / 100).toFixed(2)}em`);
            if (b.upper) classes.push('upper');
            if (b.type === 'totals' && b.hl) { css.push(`--hl:${this.cssColor(b.hl)}`); classes.push('hl'); }
            return classes.length > 1 || css.length ? `<div class="${classes.join(' ')}" style="${esc(css.join(';'))}">${html}</div>` : html;
        },
        insertTextVar(key) {
            const b = this.selected(), area = this.$refs.text;
            if (!b) return;
            const token = `{${key}}`, text = b.text || '';
            const at = area && document.activeElement === area ? area.selectionStart : text.length;
            this.update({ text: (text.slice(0, at) + token + text.slice(at)).slice(0, 1500) });
            this.$nextTick(() => { if (area) { area.value = b.text; area.focus(); area.setSelectionRange(at + token.length, at + token.length); } });
        },
        focusText() { this.$nextTick(() => this.$refs.text && this.$refs.text.focus()); },

        // --- Historique ---
        snapshot() { this.history.push(clone(this.canvas)); if (this.history.length > 80) this.history.shift(); this.future = []; this.dirty = true; },
        commit() { this.dirty = true; },
        undo() { if (!this.history.length) return; this.future.push(clone(this.canvas)); this.canvas = this.history.pop(); this.dirty = true; this.icons_(); this.refit(); this.refreshPreviews(); },
        redo() { if (!this.future.length) return; this.history.push(clone(this.canvas)); this.canvas = this.future.pop(); this.dirty = true; this.icons_(); this.refit(); this.refreshPreviews(); },

        // --- Blocs ---
        newBlock(type, band, x, y) {
            const spec = this.palette.find((p) => p.type === type);
            const w = Math.min(spec ? spec.w : 200, this.pageWidth - x);
            const block = Object.assign({ id: uid(), type, band, x, y, w }, this.decorDefaults());
            if (type === 'text') block.text = 'Votre texte';
            if (type === 'totals') block.hl = '';
            return block;
        },
        addBlock(type) {
            const spec = this.palette.find((p) => p.type === type);
            const band = spec.band;
            const bottom = Math.ceil(this.bottomOf(band) / SNAP) * SNAP;  // sous le dernier bloc, d'après sa vraie hauteur
            this.snapshot();
            if (bottom + 60 > this.canvas.heights[band]) this.canvas.heights[band] = Math.min(900, bottom + 90);
            const block = this.newBlock(type, band, cfg.padding, bottom);
            this.canvas.blocks.push(block);
            this.selectedId = block.id;
            this.icons_();
            this.refit();
        },
        dropNew(event, band) {
            this.dropHint = null;
            const type = this.dragNew || event.dataTransfer.getData('text/plain');
            if (!type || !this.palette.find((p) => p.type === type)) return;
            const rect = event.currentTarget.getBoundingClientRect();
            const x = Math.max(0, Math.round((event.clientX - rect.left) / this.scale / SNAP) * SNAP - 20);
            const y = Math.max(0, Math.round((event.clientY - rect.top) / this.scale / SNAP) * SNAP - 12);
            this.snapshot();
            const block = this.newBlock(type, band, Math.min(x, this.pageWidth - 60), Math.min(y, this.canvas.heights[band] - 20));
            this.canvas.blocks.push(block);
            this.selectedId = block.id;
            this.dragNew = null;
            this.refit();
        },
        update(patch, record = true) {
            const b = this.selected();
            if (!b) return;
            if (record) this.snapshot(); else this.dirty = true;
            Object.assign(b, patch);
            this.clamp(b);
            this.refit();
        },
        clamp(b) {
            const decor = b.type === 'shape' || b.type === 'image';
            if (decor) b.h = Math.max(2, Math.min(cfg.pageHeight, Math.round(b.h || 0)));
            b.w = Math.max(decor ? 2 : 40, Math.min(this.pageWidth, Math.round(b.w)));
            b.x = Math.max(0, Math.min(this.pageWidth - b.w, Math.round(b.x)));
            const maxY = b.band === 'page' ? cfg.pageHeight : this.canvas.heights[b.band] - 10;
            b.y = Math.max(0, Math.min(maxY, Math.round(b.y)));
        },
        duplicate() {
            const b = this.selected();
            if (!b) return;
            this.snapshot();
            const copy = Object.assign(clone(b), { id: uid(), y: b.y + 24, x: b.x + (this.isDecor(b) ? 24 : 0) });
            this.clamp(copy);
            if (this.isDecor(copy)) this.insertDecor(copy); else this.canvas.blocks.push(copy);
            this.selectedId = copy.id;
            this.refit();
        },
        remove() {
            if (!this.selectedId || this.selectedId === 'table') return;
            this.snapshot();
            this.canvas.blocks = this.canvas.blocks.filter((b) => b.id !== this.selectedId);
            this.selectedId = null;
            this.refit();
        },

        // --- Glisser / redimensionner ---
        bandAt(clientY) {
            for (const el of this.$refs.page.querySelectorAll('[data-band]')) {
                const r = el.getBoundingClientRect();
                if (clientY >= r.top && clientY <= r.bottom) return { band: el.dataset.band, rect: r };
            }
            return null;
        },
        snapX(b) {
            const candidates = [cfg.padding, this.pageWidth - cfg.padding - b.w, (this.pageWidth - b.w) / 2, 0, this.pageWidth - b.w];
            const lines = [cfg.padding, this.pageWidth - cfg.padding, this.pageWidth / 2, 0, this.pageWidth];
            for (let i = 0; i < candidates.length; i += 1) {
                if (Math.abs(candidates[i] - b.x) <= GUIDE) { b.x = Math.round(candidates[i]); this.guide = lines[i]; return; }
            }
            this.guide = null;
        },
        startMove(event, b) {
            if (event.button !== 0) return;
            this.select(b.id);
            const start = { x: event.clientX, y: event.clientY, bx: b.x, by: b.y, band: b.band, moved: false };
            const before = clone(this.canvas);
            const move = (e) => {
                const dx = (e.clientX - start.x) / this.scale, dy = (e.clientY - start.y) / this.scale;
                if (!start.moved && Math.abs(dx) + Math.abs(dy) < 3) return;
                start.moved = true;
                b.x = Math.round((start.bx + dx) / SNAP) * SNAP;
                if (b.band === 'page') {
                    // Décor de page : se déplace sur toute la feuille, sans changer de plan.
                    b.y = Math.round((start.by + (b.anchor === 'bottom' ? -dy : dy)) / SNAP) * SNAP;
                } else {
                    const over = this.bandAt(e.clientY);
                    if (over && over.band !== b.band) {
                        b.band = over.band;
                        b.y = Math.round((e.clientY - over.rect.top) / this.scale / SNAP) * SNAP;
                    } else if (b.band === start.band) {
                        b.y = Math.round((start.by + dy) / SNAP) * SNAP;
                    } else if (over) {
                        b.y = Math.round((e.clientY - over.rect.top) / this.scale / SNAP) * SNAP;
                    }
                }
                this.clamp(b);
                this.snapX(b);
            };
            const up = () => {
                document.removeEventListener('pointermove', move);
                document.removeEventListener('pointerup', up);
                this.guide = null;
                if (start.moved) { this.history.push(before); this.future = []; this.dirty = true; this.refit(); }
            };
            document.addEventListener('pointermove', move);
            document.addEventListener('pointerup', up);
        },
        startResize(event, b) {
            this.select(b.id);
            const start = { x: event.clientX, y: event.clientY, w: b.w, h: b.h, ratio: b.h && b.w ? b.h / b.w : 0 };
            const before = clone(this.canvas);
            const move = (e) => {
                b.w = Math.round((start.w + (e.clientX - start.x) / this.scale) / SNAP) * SNAP;
                if (b.type === 'shape') {
                    const dy = (e.clientY - start.y) / this.scale;
                    b.h = Math.round((start.h + (b.band === 'page' && b.anchor === 'bottom' ? -dy : dy)) / SNAP) * SNAP;
                } else if (b.type === 'image') {
                    // Image : proportions gardées (Maj pour les libérer).
                    b.h = e.shiftKey ? Math.round((start.h + (e.clientY - start.y) / this.scale) / SNAP) * SNAP : Math.round(b.w * start.ratio);
                }
                this.clamp(b);
            };
            const up = () => {
                document.removeEventListener('pointermove', move);
                document.removeEventListener('pointerup', up);
                this.history.push(before); this.future = []; this.dirty = true;
                this.refit();
            };
            document.addEventListener('pointermove', move);
            document.addEventListener('pointerup', up);
        },
        startBandResize(event, band) {
            const start = { y: event.clientY, h: this.canvas.heights[band] };
            const before = clone(this.canvas);
            const lowest = this.blocksIn(band).filter((b) => !this.isDecor(b)).reduce((max, b) => Math.max(max, b.y + 20), 60);
            const move = (e) => {
                this.canvas.heights[band] = Math.max(lowest, Math.min(900, Math.round((start.h + (e.clientY - start.y) / this.scale) / SNAP) * SNAP));
            };
            const up = () => {
                document.removeEventListener('pointermove', move);
                document.removeEventListener('pointerup', up);
                this.history.push(before); this.future = []; this.dirty = true;
                this.refit();
            };
            document.addEventListener('pointermove', move);
            document.addEventListener('pointerup', up);
        },

        // --- Clavier ---
        onKey(e) {
            const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName);
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !typing) { e.preventDefault(); e.shiftKey ? this.redo() : this.undo(); return; }
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y' && !typing) { e.preventDefault(); this.redo(); return; }
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); this.save(); return; }
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd' && !typing && this.selected()) { e.preventDefault(); this.duplicate(); return; }
            if (e.key === 'Escape' && !typing) { this.select(null); return; }
            const b = this.selected();
            if (!b || typing) return;
            const step = e.shiftKey ? 10 : 1;
            const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
            if (moves[e.key]) {
                e.preventDefault();
                const dy = b.band === 'page' && b.anchor === 'bottom' ? -moves[e.key][1] : moves[e.key][1];
                this.update({ x: b.x + moves[e.key][0], y: b.y + dy });
            } else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); this.remove(); }
        },

        // --- Aperçus et enregistrement ---
        csrf() {
            const el = document.querySelector('[name=csrfmiddlewaretoken]');
            if (el) return el.value;
            const m = document.cookie.match(/csrftoken=([^;]+)/);
            return m ? m[1] : '';
        },
        async refreshPreviews() {
            const response = await fetch(URLS.previews, {
                method: 'POST', headers: { 'X-CSRFToken': this.csrf(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ texts: this.texts, document_type: this.documentType, table: this.canvas.table }),
            }).catch(() => null);
            const data = response ? await response.json().catch(() => ({})) : {};
            if (data.ok) { this.previews = data.previews; this.refit(); }
        },
        textsChanged() {
            this.dirty = true;
            clearTimeout(this._textTimer);
            this._textTimer = setTimeout(() => this.refreshPreviews(), 500);
        },
        setDocType(type) { this.documentType = type; this.refreshPreviews(); },
        async save(thenPreview = false) {
            this.saving = true; this.error = '';
            const response = await fetch(URLS.save, {
                method: 'POST', headers: { 'X-CSRFToken': this.csrf(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: this.name, canvas: this.canvas, accent: this.accent, font: this.font, texts: this.texts, is_default: this.isDefault }),
            }).catch(() => null);
            const data = response ? await response.json().catch(() => ({})) : {};
            this.saving = false;
            if (!response || !response.ok || !data.ok) { this.error = data.error || data.message || 'Enregistrement impossible.'; return; }
            const gaps = this.missing();
            this.warning = gaps.length ? `Enregistré, mais il manque des mentions obligatoires : ${gaps.map((m) => m.label).join(', ')}.` : '';
            this.dirty = false;
            if (thenPreview) window.open(this.previewUrl(), '_blank', 'noopener');
        },
    };
}
