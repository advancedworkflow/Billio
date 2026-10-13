/* Éditeur de facture : aperçu du modèle (rendu serveur via templates_app) rendu
   interactif + inspecteur contextuel (Client, Infos, Lignes, Notes, Apparence).

   Objets cliquables dans l'aperçu : les modèles sont du HTML arbitraire, on ne peut
   donc pas y poser d'attributs à l'avance. Pour l'aperçu uniquement, les valeurs
   texte envoyées au rendu (nom du client, numéro, dates, désignations…) sont préfixées
   d'un marqueur invisible (caractères Unicode à usage privé, qui survivent à
   l'échappement Django). Après le rendu, on retrouve ces marqueurs dans le DOM, on
   les retire et on pose `data-obj` sur le bloc qui les contient. Les totaux sont
   repérés par leur montant. Les champs `[data-field]` des modèles restent éditables
   en place comme avant. */
function invoiceEditor() {
  const readJson = (id, fallback) => {
    try {
      const el = document.getElementById(id);
      return el && el.textContent.trim() ? JSON.parse(el.textContent) : fallback;
    } catch (e) {
      console.warn(`${id} invalide`, e);
      return fallback;
    }
  };
  const urls = window.__invoiceEditorUrls || {};
  // Même éditeur pour la facture et le devis : le devis ajoute TVA / remise par ligne,
  // remise globale, projet, conditions et échéancier (voir templates/invoices/create.html).
  const IS_QUOTE = urls.mode === 'quote';
  const DUE_KEY = IS_QUOTE ? 'expiry_date' : 'due_date';
  const boot = readJson('invoice-editor-bootstrap', {});
  const bootData = Object.assign(IS_QUOTE ? {
    client_id: '', quote_number: 'AUTO-001', title: 'Devis', description: '', issue_date: '', expiry_date: '',
    currency: 'EUR', discount_amount: 0, notes: '', payment_terms: '', delivery_terms: '', terms_and_conditions: '',
    footer: '', project_name: '', project_reference: '', project_location: '', project_start_date: '',
    project_delivery_date: '', is_recurring: false, recurrence_interval: 'monthly', recurrence_count: 12,
    recurrence_start_date: '', items: [], milestones: [], status: '', converted_invoice_id: '',
  } : {
    client_id: '', invoice_number: 'AUTO-001', issue_date: '', due_date: '', currency: 'EUR',
    invoice_type: 'sale', notes: '', discount_amount: 0, items: [],
  }, boot.invoice_data || boot.quote_data || {});
  let keySeq = 0;
  // TVA par ligne pour la facture comme pour le devis ; la remise de ligne n'existe que sur le devis.
  const ITEM_DEFAULTS = IS_QUOTE
    ? { name: '', description: '', quantity: 1, unit_price: 0, unit: 'unité', tax_rate: 20, discount_percent: 0 }
    : { name: '', description: '', quantity: 1, unit_price: 0, unit: 'unité', tax_rate: 20 };
  const withKey = (item) => Object.assign({}, ITEM_DEFAULTS, item, { _key: `k${++keySeq}` });
  bootData.items = (Array.isArray(bootData.items) ? bootData.items : []).map(withKey);
  if (IS_QUOTE) bootData.milestones = (Array.isArray(bootData.milestones) ? bootData.milestones : []).map((m) => Object.assign({}, m));
  bootData.client_id = bootData.client_id ? String(bootData.client_id) : '';

  const DEFAULT_SCHEMA = [
    { name: 'document_title', type: 'text', label: 'Titre du document' },
    { name: 'accent_color', type: 'color', label: 'Couleur principale' },
    { name: 'accent_text_color', type: 'color', label: 'Texte sur la couleur principale' },
    { name: 'text_color', type: 'color', label: 'Couleur du texte' },
    { name: 'font_family', type: 'text', label: 'Police' },
    { name: 'logo_placeholder', type: 'text', label: 'Texte du logo' },
    { name: 'city_date_prefix', type: 'text', label: 'Lieu et date' },
    { name: 'legal_form_line', type: 'text', label: 'Forme juridique' },
    { name: 'tax_legal_mention', type: 'textarea', label: 'Mention TVA' },
    { name: 'offer_valid_text', type: 'textarea', label: 'Validité de l\'offre' },
    { name: 'signature_label', type: 'text', label: 'Libellé de signature' },
    { name: 'company_legal_footer', type: 'textarea', label: 'Pied de page légal' },
    { name: 'doc_padding', type: 'text', label: 'Marges intérieures' },
  ];
  const DEFAULT_VALUES = {
    document_title: 'Facture N°', font_family: 'Arial, Helvetica, sans-serif', text_color: '#111111',
    accent_color: '#1b28c1', accent_text_color: '#ffffff', doc_padding: '20px', logo_placeholder: 'LOGO',
    city_date_prefix: 'Ville, le', legal_form_line: 'Entrepreneur individuel',
    tax_legal_mention: 'TVA non applicable, article 293 B du CGI.',
    offer_valid_text: 'Offre valable jusqu\'à la date d\'échéance indiquée.', signature_label: 'Signature :',
    company_legal_footer: 'N° SIRET : à compléter — Capital social : à compléter',
  };

  const MARK_OPEN = '';
  const MARK_CLOSE = '';
  const MARK_RE = /([\w:.-]+)/g;
  const mark = (key, value) => `${MARK_OPEN}${key}${MARK_CLOSE}${value}`;
  const OBJ_SECTION = { client: 'client', meta: 'details', totals: 'items', notes: 'notes', org: 'org', logo: 'style' };
  const OBJ_LABEL = { client: 'Client', meta: 'Numéro et dates', totals: 'Totaux', notes: 'Notes', org: 'Votre entreprise', logo: 'Logo' };

  return {
    // --- état ---
    section: 'summary',
    isQuote: IS_QUOTE,
    dueKey: DUE_KEY,
    tabs: [
      { key: 'summary', short: 'Résumé', label: 'Résumé', icon: 'layout-list' },
      { key: 'client', short: 'Client', label: 'Client', icon: 'user-round' },
      { key: 'details', short: 'Infos', label: IS_QUOTE ? 'Objet, validité, projet' : 'Numéro, dates et devise', icon: 'calendar' },
      { key: 'items', short: IS_QUOTE ? 'Prestations' : 'Lignes', label: IS_QUOTE ? 'Prestations' : 'Lignes de facture', icon: 'list' },
      { key: 'notes', short: IS_QUOTE ? 'Conditions' : 'Notes', label: 'Notes et conditions', icon: 'sticky-note' },
      ...(IS_QUOTE ? [{ key: 'schedule', short: 'Échéances', label: 'Échéancier et récurrence', icon: 'calendar-range' }] : []),
      { key: 'style', short: 'Style', label: 'Apparence du modèle', icon: 'palette' },
    ].map((tab, index) => Object.assign(tab, { kbd: `Alt+${index + 1}` })),
    shortcuts: [
      ['Enregistrer', 'Ctrl+S'], ['Ajouter une ligne', 'Ctrl+Entrée'], ['Changer de modèle', '← / →'],
      ['Aperçu plein écran', 'P'], [IS_QUOTE ? 'Onglets du panneau' : 'Résumé · Client · Infos · Lignes · Notes · Style', IS_QUOTE ? 'Alt+1 … 7' : 'Alt+1 … 6'],
      ['Fermer / revenir', 'Échap'], ['Cette aide', '?'],
    ],
    noteSnippets: [
      { label: 'Paiement à 30 jours', text: 'Paiement à 30 jours à réception de facture, par virement bancaire.' },
      { label: 'Pénalités de retard', text: 'En cas de retard de paiement, une pénalité égale à trois fois le taux d\'intérêt légal sera appliquée, ainsi qu\'une indemnité forfaitaire de 40 € pour frais de recouvrement.' },
      { label: 'Pas d\'escompte', text: 'Aucun escompte consenti pour paiement anticipé.' },
      { label: 'TVA non applicable', text: 'TVA non applicable, article 293 B du CGI.' },
      { label: 'Remerciements', text: 'Merci pour votre confiance !' },
    ],
    invoiceData: bootData,
    selectedTemplate: boot.selected_template != null ? String(boot.selected_template) : '',
    templatesLibrary: readJson('invoice-editor-templates', []),
    clients: readJson('invoice-editor-clients', []),
    organization: readJson('invoice-editor-organization', {}),
    products: readJson('invoice-editor-products', []),
    dynamicVariables: {},
    activeSchemaFields: [],
    variablesJsonText: '',
    renderedPreviewHtml: '<p class="ie-loading">Chargement de l\'aperçu…</p>',
    renderedPreviewCss: '',
    subtotal: 0, taxAmount: 0, total: 0,
    activeItem: null,
    activeField: null,
    dragFrom: null,
    hoverObj: null, hoverLabel: '', hoverStyle: '',
    templatesOpen: false, moreOpen: false, fullscreenPreview: false, showHelp: false,
    clientQuery: '', clientHighlight: 0, clientCreate: false,
    newClient: { name: '', email: '', phone: '', error: '', submitting: false },
    saving: false, dirty: false, logoBusy: false, logoFocus: false,
    defineTpl: { open: false, name: '', isDefault: false, saving: false, error: '' },
    picker: { open: false, index: null, top: 0, left: 0, width: 300, hover: 0 },
    toast: { text: '', error: false },
    _previewSeq: 0, _previewTimer: null, _toastTimer: null, _fieldSnapshot: null,

    // --- initialisation ---
    init() {
      if (!this.invoiceData.issue_date) this.invoiceData.issue_date = this.isoDate(new Date());
      // Échéance passée par l'URL (ex. « Nouvelle facture ce jour » depuis le calendrier des factures).
      const dueParam = new URLSearchParams(window.location.search).get('due');
      if (!this.invoiceData[DUE_KEY] && /^\d{4}-\d{2}-\d{2}$/.test(dueParam || '')) this.invoiceData[DUE_KEY] = dueParam;
      if (!this.invoiceData[DUE_KEY]) this.setDueIn(IS_QUOTE ? 30 : (this.billing.payment_days || 30), false);
      // Franchise en base : les nouvelles lignes partent à 0 % de TVA.
      if (this.billing.vat_exempt) ITEM_DEFAULTS.tax_rate = 0;
      if (!this.selectedTemplate && this.templatesLibrary.length) this.selectedTemplate = String(this.templatesLibrary[0].id);
      try {
        const tid = localStorage.getItem('selected_template_id');
        if (tid && this.templatesLibrary.some((t) => String(t.id) === String(tid))) this.selectedTemplate = String(tid);
        localStorage.removeItem('selected_template_id');
        localStorage.removeItem('selected_template_type');
      } catch (e) { /* stockage indisponible */ }
      if (!this.invoiceData.client_id) this.section = 'client';
      this.calculateTotals();
      this.updatePreview(true);
      this.$watch('invoiceData', () => { this.calculateTotals(); this.schedulePreview(); }, { deep: true });
      this.$watch('selectedTemplate', () => this.updatePreview(true));
      this.$watch('section', () => this.refreshUi());
      this.$watch('activeItem', () => { this.highlightActive(); this.scrollActiveItem(); });
      this.$watch('clientQuery', () => { this.clientHighlight = 0; });
      // x-html remplace le contenu de l'aperçu de façon asynchrone : on décore à chaque remplacement.
      new MutationObserver(() => this.decoratePreview()).observe(document.getElementById('invoice-preview'), { childList: true });
      this.setupTooltips();
      window.addEventListener('beforeunload', (e) => { if (this.dirty) { e.preventDefault(); e.returnValue = ''; } });
      this.$nextTick(() => this.refreshUi());
    },

    refreshUi() {
      this.$nextTick(() => {
        if (typeof lucide !== 'undefined') lucide.createIcons();
        this.highlightActive();
      });
    },

    // --- étapes / sections ---
    steps() {
      return [
        { key: 'client', label: 'Client', done: !!this.currentClient() },
        { key: 'items', label: 'Lignes', done: this.validItems().length > 0 },
        { key: 'details', label: IS_QUOTE ? 'Validité' : 'Dates', done: !!(this.invoiceData.issue_date && this.invoiceData[DUE_KEY]) },
      ];
    },
    docLabel() {
      if (IS_QUOTE) return 'Devis';
      return this.invoiceData.invoice_type === 'purchase' ? 'Facture d\'achat' : 'Facture';
    },
    notesSummary() {
      const d = this.invoiceData;
      const text = [d.notes, IS_QUOTE ? d.payment_terms : '', IS_QUOTE ? d.delivery_terms : '', IS_QUOTE ? d.terms_and_conditions : ''].find((v) => (v || '').trim());
      return text ? text.trim().slice(0, 60) : '';
    },
    statusLabel() {
      return { draft: 'Brouillon', sent: 'Envoyé', viewed: 'Consulté', accepted: 'Accepté', rejected: 'Refusé', expired: 'Expiré' }[this.invoiceData.status] || '';
    },
    openSection(key, focus = true) {
      this.section = key;
      if (!focus) return;
      this.$nextTick(() => {
        if (key === 'client' && !this.clientCreate && this.$refs.clientSearch) this.$refs.clientSearch.focus();
        if (key === 'notes' && this.$refs.notes) this.$refs.notes.focus();
        if (key === 'items' && !this.invoiceData.items.length) this.addItem();
      });
    },
    validItems() { return this.invoiceData.items.filter((i) => (i.name || '').trim() && Number(i.unit_price) > 0); },
    touch() { this.dirty = true; },
    setData(key, value) { this.invoiceData[key] = value; this.touch(); },

    // --- client ---
    currentClient() { return this.clients.find((c) => String(c.id) === String(this.invoiceData.client_id)) || null; },
    filteredClients() {
      const q = this.clientQuery.trim().toLowerCase();
      if (!q) return this.clients;
      return this.clients.filter((c) => `${c.name || ''} ${c.email || ''}`.toLowerCase().includes(q));
    },
    chooseClient(c) {
      this.invoiceData.client_id = String(c.id);
      this.clientQuery = '';
      this.touch();
      this.showToast(`Client : ${c.name}`);
      if (!this.validItems().length) this.openSection('items');
    },
    clientListKeydown(e) {
      const list = this.filteredClients();
      if (e.key === 'ArrowDown') { e.preventDefault(); this.clientHighlight = Math.min(list.length - 1, this.clientHighlight + 1); }
      if (e.key === 'ArrowUp') { e.preventDefault(); this.clientHighlight = Math.max(0, this.clientHighlight - 1); }
      if (e.key === 'Enter') {
        e.preventDefault();
        if (list[this.clientHighlight]) this.chooseClient(list[this.clientHighlight]);
        else this.startClientCreate();
      }
    },
    startClientCreate() {
      this.clientCreate = true;
      this.newClient = { name: this.clientQuery.trim(), email: '', phone: '', error: '', submitting: false };
      this.$nextTick(() => this.$refs.newClientName && this.$refs.newClientName.focus());
    },
    async submitNewClient() {
      const name = this.newClient.name.trim();
      const email = this.newClient.email.trim();
      if (!name || !email) { this.newClient.error = 'Le nom et l\'email sont requis.'; return; }
      this.newClient.submitting = true;
      this.newClient.error = '';
      try {
        const body = new URLSearchParams({ name, email, phone: this.newClient.phone.trim() });
        const orgId = this.$root.dataset.invoiceOrgId;
        if (orgId) body.append('organization_id', orgId);
        const res = await fetch(urls.clientCreate, { method: 'POST', headers: { 'X-CSRFToken': this.csrf() }, body });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) { this.newClient.error = data.error || 'Impossible de créer le client.'; return; }
        const row = { id: data.id, name: data.name || name, email: data.email || email, phone: data.phone || '', address: '', registration_number: '', tax_id: '' };
        this.clients = [...this.clients, row];
        this.clientCreate = false;
        this.chooseClient(row);
      } catch (err) {
        this.newClient.error = 'Erreur réseau, réessayez.';
      } finally {
        this.newClient.submitting = false;
      }
    },

    // --- dates ---
    isoDate(d) { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10); },
    setDueIn(days, mark = true) {
      const base = this.invoiceData.issue_date ? new Date(`${this.invoiceData.issue_date}T12:00:00`) : new Date();
      base.setDate(base.getDate() + days);
      this.invoiceData[DUE_KEY] = this.isoDate(base);
      if (mark) this.touch();
    },
    dueInDays() {
      if (!this.invoiceData.issue_date || !this.invoiceData[DUE_KEY]) return null;
      return Math.round((new Date(this.invoiceData[DUE_KEY]) - new Date(this.invoiceData.issue_date)) / 86400000);
    },
    formatDate(s) { return s ? new Date(`${s}T12:00:00`).toLocaleDateString('fr-FR') : '—'; },

    get billing() { return (this.organization && this.organization.billing) || {}; },
    get tjm() { return Number(this.billing.tjm) || 0; },
    // Ligne au tarif enregistré dans le Centre de ressources (jour, demi-journée, heure).
    addRateItem(kind) {
      const hours = Number(this.billing.hours_per_day) || 7;
      const spec = {
        day: { name: 'Journée de prestation', unit: 'jour', unit_price: this.tjm },
        half: { name: 'Demi-journée de prestation', unit: 'demi-journée', unit_price: Math.round(this.tjm / 2 * 100) / 100 },
        hour: { name: 'Heure de prestation', unit: 'heure', unit_price: Math.round(this.tjm / hours * 100) / 100 },
      }[kind];
      this.invoiceData.items.push(withKey(spec));
      this.activeItem = this.invoiceData.items.length - 1;
      this.section = 'items';
      this.touch();
    },

    // --- lignes ---
    addItem() {
      this.invoiceData.items.push(withKey({}));
      this.activeItem = this.invoiceData.items.length - 1;
      this.section = 'items';
      this.touch();
      this.$nextTick(() => {
        const inputs = this.$refs.panel.querySelectorAll('.ie-item-name');
        const last = inputs[inputs.length - 1];
        if (last) last.focus();
        this.refreshUi();
      });
    },
    duplicateItem(index) {
      const copy = withKey(Object.assign({}, this.invoiceData.items[index]));
      this.invoiceData.items.splice(index + 1, 0, copy);
      this.activeItem = index + 1;
      this.touch();
      this.refreshUi();
    },
    removeItem(index) {
      this.invoiceData.items.splice(index, 1);
      this.activeItem = null;
      this.touch();
    },
    dropItem(index) {
      if (this.dragFrom === null || this.dragFrom === index) return;
      const [moved] = this.invoiceData.items.splice(this.dragFrom, 1);
      this.invoiceData.items.splice(index, 0, moved);
      this.activeItem = index;
      this.dragFrom = null;
      this.touch();
    },
    // --- catalogue produits d'une ligne (menu flottant) ---
    openPicker(index, el) {
      if (!this.products.length) return;
      this._pickerEl = el;
      this.picker.index = index;
      this.picker.open = true;
      this.picker.hover = 0;
      this.placePicker();
      if (!this._pickerScroll) {
        // Suit le défilement du panneau des lignes et de la page.
        this._pickerScroll = () => { if (this.picker.open) this.placePicker(); };
        window.addEventListener('scroll', this._pickerScroll, true);
        window.addEventListener('resize', this._pickerScroll);
      }
    },
    placePicker() {
      const el = this._pickerEl;
      if (!el || !el.isConnected) { this.picker.open = false; return; }
      const r = el.getBoundingClientRect();
      const width = Math.max(r.width, 300);
      const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
      Object.assign(this.picker, { top: r.bottom + 4, left, width });
      this.$nextTick(() => {
        const height = this.$refs.picker ? this.$refs.picker.offsetHeight : 0;
        if (height && r.bottom + 4 + height > window.innerHeight - 8 && r.top - height - 4 > 8) this.picker.top = r.top - height - 4;
      });
    },
    // Fermeture différée : un clic dans le menu passe avant ; on ne ferme pas si le focus est passé à une autre ligne.
    closePicker() { setTimeout(() => { if (document.activeElement !== this._pickerEl) this.picker.open = false; }, 120); },
    pickerItems() {
      if (!this.picker.open) return [];
      const item = this.invoiceData.items[this.picker.index];
      const q = ((item && item.name) || '').toLowerCase().trim();
      if (q && this.products.some((p) => p.name.toLowerCase() === q)) return []; // produit déjà choisi
      return this.products.filter((p) => !q || p.name.toLowerCase().includes(q) || String(p.reference || '').toLowerCase().includes(q)).slice(0, 8);
    },
    choosePick(product) {
      const item = this.invoiceData.items[this.picker.index];
      if (!item) return;
      item.name = product.name;
      this.applyProduct(item);
      this.touch();
      this.picker.open = false;
    },
    pickerKey(e) {
      const list = this.pickerItems();
      if (!this.picker.open || !list.length) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); this.picker.hover = (this.picker.hover + 1) % list.length; }
      else if (e.key === 'ArrowUp') { e.preventDefault(); this.picker.hover = (this.picker.hover - 1 + list.length) % list.length; }
      else if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); this.choosePick(list[this.picker.hover] || list[0]); }
      else if (e.key === 'Escape') { this.picker.open = false; }
    },
    applyProduct(item) {
      const product = this.products.find((p) => p.name === item.name);
      if (!product) return;
      item.unit_price = Number(product.unit_price) || 0;
      if (product.tax_rate !== undefined && product.tax_rate !== null) item.tax_rate = Number(product.tax_rate);
      if (product.unit) item.unit = product.unit;
      if (product.description && !item.description) item.description = product.description;
      if (IS_QUOTE) item.product_id = String(product.id);
      if (!item.quantity) item.quantity = 1;
      this.showToast(`Prix du catalogue appliqué : ${this.formatCurrency(item.unit_price)}`);
    },
    scrollActiveItem() {
      if (this.activeItem === null || this.section !== 'items') return;
      this.$nextTick(() => {
        const card = this.$refs.panel.querySelector(`[data-item-index="${this.activeItem}"]`);
        if (card) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      });
    },

    // --- totaux ---
    // Total HT d'une ligne (remise de ligne comprise en mode devis) — même calcul que save_quote.
    lineTotal(item) {
      const gross = (Number(item.quantity) || 0) * (Number(item.unit_price) || 0);
      return IS_QUOTE ? gross * (1 - (Number(item.discount_percent) || 0) / 100) : gross;
    },
    calculateTotals() {
      // Même calcul que save_invoice / save_quote : TVA ligne par ligne, puis remise globale.
      this.subtotal = this.invoiceData.items.reduce((s, i) => s + this.lineTotal(i), 0);
      this.taxAmount = this.invoiceData.items.reduce((s, i) => s + this.lineTotal(i) * (Number(i.tax_rate) || 0) / 100, 0);
      this.total = this.subtotal + this.taxAmount - (Number(this.invoiceData.discount_amount) || 0);
    },
    currencyFormats: readJson('invoice-editor-currencies', null) || {},
    currencyInfo() { return this.currencyFormats[this.invoiceData.currency] || { symbol: this.invoiceData.currency || '$', position: 'after', decimals: 2, style: 'fr' }; },
    currencySymbol() { return this.currencyInfo().symbol; },
    formatCurrency(amount) {
      // Même format que les documents (organizations.currencies) : « $1,234.56 », « 1 234,56 € », « 1 250 000 FCFA ».
      const info = this.currencyInfo();
      const value = Number(amount || 0);
      const parts = Math.abs(value).toFixed(info.decimals).split('.');
      const sep = info.style === 'en' ? [',', '.'] : ['\u202f', ','];
      const number = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, sep[0]) + (parts[1] ? sep[1] + parts[1] : '');
      const sym = info.symbol;
      const text = info.position === 'before' ? (sym.length <= 1 || sym.endsWith('$') ? sym + number : `${sym} ${number}`) : `${number}\u202f${sym}`;
      return value < 0 ? `-${text}` : text;
    },

    // --- notes ---
    appendNote(text) {
      const current = (this.invoiceData.notes || '').trim();
      if (current.includes(text)) return;
      this.invoiceData.notes = current ? `${current}\n${text}` : text;
      this.touch();
    },

    // --- modèles & variables ---
    getTemplate() { return this.templatesLibrary.find((t) => String(t.id) === String(this.selectedTemplate)) || null; },
    selectedTemplateName() { const t = this.getTemplate(); return t ? t.name : 'Aucun modèle'; },
    selectTemplate(id) { this.selectedTemplate = String(id); this.touch(); },
    selectAdjacentTemplate(delta) {
      const list = this.templatesLibrary;
      if (!list.length) return;
      let i = list.findIndex((t) => String(t.id) === String(this.selectedTemplate));
      i = Math.max(0, Math.min(list.length - 1, (i < 0 ? 0 : i) + delta));
      this.selectTemplate(list[i].id);
      this.showToast(`Modèle : ${list[i].name}`);
    },
    syncSchema() {
      const t = this.getTemplate();
      if (!t) { this.activeSchemaFields = []; return; }
      const schema = t.variable_schema && t.variable_schema.fields && t.variable_schema.fields.length ? t.variable_schema.fields : null;
      this.activeSchemaFields = (schema || DEFAULT_SCHEMA).filter((f) => f && f.name);
      const defaults = schema ? Object.assign({}, t.variables_defaults || {}) : Object.assign({}, DEFAULT_VALUES, t.variables_defaults || {});
      this.dynamicVariables = Object.assign(defaults, this.dynamicVariables);
      this.renderedPreviewCss = t.css_styles || '';
    },
    fieldValue(name) { const v = this.dynamicVariables[name]; return v == null ? '' : v; },
    setVariable(name, value) { this.dynamicVariables = Object.assign({}, this.dynamicVariables, { [name]: value }); this.schedulePreview(); },
    syncJsonFromVars() { this.variablesJsonText = JSON.stringify(this.dynamicVariables || {}, null, 2); },
    applyVariablesJson() {
      try {
        const parsed = JSON.parse(this.variablesJsonText || '{}');
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('le JSON doit être un objet');
        this.dynamicVariables = Object.assign({}, this.dynamicVariables, parsed);
        this.updatePreview(true);
        this.showToast('Variables appliquées');
      } catch (err) {
        this.showToast(`JSON invalide : ${err.message}`, true);
      }
    },

    // --- aperçu ---
    get cleanPreviewHtml() { return this.renderedPreviewHtml.replace(MARK_RE, ''); },
    previewContext() {
      const c = this.currentClient() || {};
      const org = this.organization || {};
      return {
        invoice_title: IS_QUOTE ? 'DEVIS' : (this.invoiceData.invoice_type === 'purchase' ? 'FACTURE ACHAT' : 'FACTURE'),
        document_kind: IS_QUOTE ? 'Devis' : 'Facture',
        document_type: IS_QUOTE ? 'quote' : 'invoice',
        organization_initial: (org.name || '?').trim().charAt(0).toUpperCase(),
        organization_logo_url: org.logo_url || '',
        invoice_number: mark('meta', (IS_QUOTE ? this.invoiceData.quote_number : this.invoiceData.invoice_number) || ''),
        issue_date: mark('meta', this.formatDate(this.invoiceData.issue_date)),
        due_date: mark('meta', this.formatDate(this.invoiceData[DUE_KEY])),
        client_name: mark('client', c.name || 'Choisir un client'),
        client_email: c.email || '', client_address: c.address || '', client_phone: c.phone || '',
        client_registration_number: c.registration_number || '', client_tax_id: c.tax_id || '',
        organization_name: mark('org', org.name || ''),
        organization_address: org.address || '', organization_city: org.city || '', organization_postal_code: org.postal_code || '',
        organization_phone: org.phone || '', organization_email: org.email || '',
        organization_registration_number: org.registration_number || '', organization_tax_id: org.tax_id || '',
        organization_bank_name: org.bank_name || '', organization_iban: org.iban || '', organization_bic_swift: org.bic_swift || '',
        organization_payment_instructions: org.payment_instructions || '',
        organization_preferred_payment_method: org.preferred_payment_method || 'bank_transfer',
        organization_payment_method_label: org.payment_method_label || '',
        subtotal: this.subtotal.toFixed(2), tax_amount: this.taxAmount.toFixed(2),
        discount_amount: (Number(this.invoiceData.discount_amount) || 0).toFixed(2),
        total_amount: this.total.toFixed(2), currency: this.invoiceData.currency || 'EUR',
        notes: this.invoiceData.notes ? mark('notes', this.invoiceData.notes) : '',
        items: this.invoiceData.items.map((item, i) => ({
          name: mark(`item:${i}`, item.name || 'Nouvelle ligne'),
          description: (item.description || '').trim(),
          quantity: item.quantity || 0,
          unit_price: Number(item.unit_price || 0).toFixed(2),
          unit: item.unit || 'unité',
          tax_rate: String(Number(item.tax_rate) || 0),
          total: this.lineTotal(item).toFixed(2),
        })),
      };
    },
    // Miroir de InvoiceTemplate._quote_text_overrides (rendu PDF).
    quoteTextOverrides() {
      if (!IS_QUOTE) return {};
      const d = this.invoiceData;
      const out = {};
      const title = (d.title || '').trim();
      const subject = [title.toLowerCase() === 'devis' ? '' : title, (d.project_name || '').trim()].filter(Boolean).join(' — ');
      if (subject) out.subject = subject;
      [['payment_terms', 'payment_terms'], ['delivery_terms', 'delivery_terms'], ['terms_and_conditions', 'legal_mentions'], ['footer', 'thank_you']]
        .forEach(([src, key]) => { if ((d[src] || '').trim()) out[key] = d[src]; });
      return out;
    },
    schedulePreview() {
      clearTimeout(this._previewTimer);
      this._previewTimer = setTimeout(() => this.updatePreview(), 220);
    },
    async updatePreview(syncSchema = false) {
      if (syncSchema || !this.activeSchemaFields.length) this.syncSchema();
      const t = this.getTemplate();
      if (!t) { this.renderedPreviewHtml = '<p class="ie-loading">Aucun modèle sélectionné.</p>'; return; }
      const variables = Object.assign(this.previewContext(), this.dynamicVariables, this.quoteTextOverrides());
      const seq = ++this._previewSeq;
      let html = null;
      try {
        const src = t.source === 'marketplace' ? 'marketplace' : 'personal';
        const rawId = String(t.id);
        const body = new URLSearchParams({
          source_type: src,
          template_id: src === 'marketplace' && rawId.startsWith('m-') ? rawId.slice(2) : rawId,
          variables: JSON.stringify(variables),
        });
        const res = await fetch(urls.preview, { method: 'POST', headers: { 'X-CSRFToken': this.csrf() }, body });
        const data = await res.json();
        if (res.ok && data.ok) {
          html = data.preview_html || '<p class="ie-loading">Aperçu vide.</p>';
          if (seq === this._previewSeq) this.renderedPreviewCss = data.preview_css || '';
        }
      } catch (err) {
        console.warn('Aperçu serveur indisponible, rendu local', err);
      }
      if (html === null) {
        html = t.html_structure || '';
        Object.entries(variables).forEach(([key, value]) => {
          if (typeof value === 'object') return;
          html = html.replace(new RegExp(`\\{\\{\\s*${key}\\s*\\}\\}`, 'g'), value ?? '');
        });
      }
      if (seq !== this._previewSeq) return; // une réponse plus récente est déjà affichée
      this.renderedPreviewHtml = html;
    },

    // Repère les objets (client, lignes, totaux…) dans le HTML rendu.
    decoratePreview() {
      const root = document.getElementById('invoice-preview');
      if (!root) return;
      const hits = [];
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        if (!node.nodeValue.includes(MARK_OPEN)) continue;
        const keys = [];
        node.nodeValue.replace(MARK_RE, (_, key) => { keys.push(key); return ''; });
        node.nodeValue = node.nodeValue.replace(MARK_RE, '');
        hits.push({ el: node.parentElement, key: keys[0] });
      }
      // Les marqueurs ont pu atterrir dans des attributs (title, alt…) : on les nettoie aussi.
      root.querySelectorAll('*').forEach((el) => {
        Array.from(el.attributes).forEach((a) => { if (a.value.includes(MARK_OPEN)) el.setAttribute(a.name, a.value.replace(MARK_RE, '')); });
      });
      hits.forEach(({ el, key }) => {
        if (!el || !root.contains(el)) return;
        const target = key.startsWith('item:') ? (el.closest('tr') || this.blockOf(el, root)) : this.blockOf(el, root);
        if (!target.dataset.obj) target.dataset.obj = key;
      });
      this.tagTotals(root);
      this.highlightActive();
    },
    blockOf(el, root) {
      const INLINE = /^(SPAN|STRONG|B|EM|I|SMALL|A|U|MARK|LABEL)$/;
      let target = el;
      while (target.parentElement && target.parentElement !== root && INLINE.test(target.tagName)) target = target.parentElement;
      // On élargit au petit bloc parent (ex. nom + adresse du client) tant qu'il reste compact.
      for (let depth = 0; depth < 2; depth += 1) {
        const p = target.parentElement;
        if (!p || p === root || /^(TABLE|TBODY|THEAD|TR|BODY|HTML)$/.test(p.tagName)) break;
        if (p.textContent.trim().length > 260 || p.children.length > 8) break;
        if (Array.from(p.querySelectorAll('[data-obj]')).some((x) => !target.contains(x))) break;
        target = p;
      }
      return target;
    },
    tagTotals(root) {
      if (this.total <= 0) return;
      const raw = this.total.toFixed(2);
      const variants = [raw, raw.replace('.', ','), new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(this.total)];
      const normalize = (s) => s.replace(/[\s  ]/g, '');
      const wanted = variants.map(normalize);
      let last = null;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const text = normalize(node.nodeValue);
        if (wanted.some((v) => text.includes(v))) last = node.parentElement;
      }
      if (!last) return;
      const target = last.closest('tr') || this.blockOf(last, root);
      if (!target.dataset.obj) target.dataset.obj = 'totals';
    },
    objSection(key) { return key.startsWith('item:') ? 'items' : (OBJ_SECTION[key] || 'summary'); },
    objLabel(key) { return key.startsWith('item:') ? `Ligne ${Number(key.split(':')[1]) + 1}` : (OBJ_LABEL[key] || key); },
    highlightActive() {
      const root = document.getElementById('invoice-preview');
      if (!root) return;
      root.querySelectorAll('.is-active-obj').forEach((el) => el.classList.remove('is-active-obj'));
      root.querySelectorAll('[data-obj]').forEach((el) => {
        const key = el.dataset.obj;
        const sec = this.objSection(key);
        let active = sec === this.section;
        if (active && key.startsWith('item:') && this.activeItem !== null) active = Number(key.split(':')[1]) === this.activeItem;
        if (active && key === 'totals' && this.activeItem !== null) active = false;
        el.classList.toggle('is-active-obj', active);
      });
    },

    // --- interactions dans l'aperçu ---
    onPreviewHover(e) {
      const t = e.target.closest('[data-obj], [data-field]');
      if (!t) { this.hoverObj = null; return; }
      const paper = t.closest('.ie-paper');
      const r = t.getBoundingClientRect();
      const pr = paper.getBoundingClientRect();
      this.hoverObj = t;
      this.hoverLabel = t.dataset.obj ? `${this.objLabel(t.dataset.obj)} — cliquer pour modifier` : 'Texte du modèle — modifiable ici';
      this.hoverStyle = `top:${Math.max(0, r.top - pr.top - 24)}px;left:${Math.max(0, r.left - pr.left)}px`;
    },
    onPreviewClick(e) {
      const del = e.target.closest('[data-field-delete]');
      if (del) { e.preventDefault(); this.setVariable(del.dataset.fieldDelete, ''); return; }
      const field = e.target.closest('[data-field]');
      if (field) { this.activeField = field.dataset.field; this.section = 'style'; return; }
      const obj = e.target.closest('[data-obj]');
      if (!obj) return;
      e.preventDefault();
      const key = obj.dataset.obj;
      this.activeItem = key.startsWith('item:') ? Number(key.split(':')[1]) : null;
      this.openSection(this.objSection(key), key !== 'client' || !this.currentClient());
      if (key === 'meta') this.$nextTick(() => this.$refs.issueDate && this.$refs.issueDate.focus());
      if (key === 'logo') this.focusLogo();
      if (key.startsWith('item:')) this.scrollActiveItem();
    },
    onPreviewDblClick(e) {
      const obj = e.target.closest('[data-obj^="item:"]');
      if (!obj) return;
      this.$nextTick(() => {
        const card = this.$refs.panel.querySelector(`[data-item-index="${this.activeItem}"] .ie-item-name`);
        if (card) { card.focus(); card.select(); }
      });
    },
    onFieldFocusIn(e) {
      const el = e.target.closest('[data-field]');
      if (el) this._fieldSnapshot = { name: el.dataset.field, html: el.innerHTML };
    },
    onFieldFocusOut(e) {
      const el = e.target.closest('[data-field]');
      if (!el) return;
      let value = el.innerText || '';
      value = el.dataset.fieldType === 'textarea' ? value.replace(/\r\n/g, '\n') : value.replace(/[\r\n]+/g, ' ');
      this._fieldSnapshot = null;
      this.setVariable(el.dataset.field, value);
      this.touch();
    },
    onFieldKeydown(e) {
      const el = e.target.closest('[data-field]');
      if (!el) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        if (this._fieldSnapshot && this._fieldSnapshot.name === el.dataset.field) el.innerHTML = this._fieldSnapshot.html;
        el.blur();
      } else if (e.key === 'Enter' && el.dataset.fieldType !== 'textarea') {
        e.preventDefault();
        el.blur();
      }
    },
    onFieldPaste(e) {
      if (!e.target.closest('[data-field]')) return;
      e.preventDefault();
      document.execCommand('insertText', false, (e.clipboardData || window.clipboardData).getData('text/plain'));
    },

    // --- clavier ---
    onKeydown(e) {
      const mod = e.ctrlKey || e.metaKey;
      const tag = (e.target && e.target.tagName) || '';
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || (e.target && e.target.isContentEditable);
      if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); this.saveInvoice(); return; }
      if (mod && e.key === 'Enter') { e.preventDefault(); this.addItem(); return; }
      if (e.altKey && !mod && /^Digit[1-9]$/.test(e.code) && this.tabs[Number(e.code.slice(5)) - 1]) { e.preventDefault(); this.openSection(this.tabs[Number(e.code.slice(5)) - 1].key); return; }
      if (e.key === 'Escape') {
        if (this.fullscreenPreview || this.showHelp || this.templatesOpen || this.moreOpen) {
          this.fullscreenPreview = false; this.showHelp = false; this.templatesOpen = false; this.moreOpen = false;
        } else if (this.clientCreate) { this.clientCreate = false; } else if (!typing) { this.activeItem = null; this.section = 'summary'; }
        return;
      }
      if (typing) return;
      if (e.key === '?') { this.showHelp = !this.showHelp; return; }
      if (e.key.toLowerCase() === 'p' && !mod) { this.fullscreenPreview = !this.fullscreenPreview; return; }
      if (e.key === 'ArrowLeft' && !mod) { e.preventDefault(); this.selectAdjacentTemplate(-1); }
      if (e.key === 'ArrowRight' && !mod) { e.preventDefault(); this.selectAdjacentTemplate(1); }
    },

    // --- infobulles ([data-tip] + [data-kbd]) ---
    setupTooltips() {
      const tip = this.$refs.tip;
      let timer = null;
      const hide = () => { clearTimeout(timer); tip.hidden = true; };
      this.$root.addEventListener('pointerover', (e) => {
        const t = e.target.closest('[data-tip]');
        if (!t || t.closest('#invoice-preview')) return;
        clearTimeout(timer);
        timer = setTimeout(() => {
          if (!t.isConnected) return;
          const kbd = t.dataset.kbd ? `<kbd>${t.dataset.kbd}</kbd>` : '';
          tip.innerHTML = `<span>${t.dataset.tip}</span>${kbd}`;
          tip.hidden = false;
          const r = t.getBoundingClientRect();
          const left = Math.max(8, Math.min(window.innerWidth - tip.offsetWidth - 8, r.left + r.width / 2 - tip.offsetWidth / 2));
          const top = r.bottom + tip.offsetHeight + 12 > window.innerHeight ? r.top - tip.offsetHeight - 8 : r.bottom + 8;
          tip.style.left = `${left}px`;
          tip.style.top = `${top}px`;
        }, 400);
      });
      this.$root.addEventListener('pointerout', (e) => { const t = e.target.closest('[data-tip]'); if (t && !t.contains(e.relatedTarget)) hide(); });
      this.$root.addEventListener('pointerdown', hide, true);
    },

    // --- enregistrement ---
    csrf() { const el = document.querySelector('[name=csrfmiddlewaretoken]'); return el ? el.value : ''; },
    showToast(text, error = false) {
      this.toast = { text, error };
      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => { this.toast = { text: '', error: false }; }, 2600);
    },
    async saveInvoice() {
      if (this.saving) return;
      if (!this.invoiceData.client_id) { this.openSection('client'); this.showToast('Choisissez d\'abord un client.', true); return; }
      this.saving = true;
      try {
        const form = new FormData();
        Object.entries(this.invoiceData).forEach(([key, value]) => {
          if (key === 'items') {
            form.append('items', JSON.stringify(value
              .filter((i) => (i.name || '').trim() || Number(i.unit_price))
              .map(({ _key, ...rest }) => rest)));
          } else if (key === 'milestones') {
            form.append('milestones', JSON.stringify(value.filter((m) => m.label || m.amount)));
          } else {
            form.append(key, value ?? '');
          }
        });
        form.append('template', this.selectedTemplate || '');
        const res = await fetch(urls.save, { method: 'POST', body: form, headers: { 'X-CSRFToken': this.csrf() } });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.success === false) throw new Error(data.error || data.message || 'Erreur lors de l\'enregistrement.');
        this.dirty = false;
        const newId = data.invoice_id || data.quote_id;
        if (urls.isNew && newId) {
          window.location.href = urls.edit.replace('00000000-0000-0000-0000-000000000000', newId);
          return true;
        }
        this.showToast(IS_QUOTE ? 'Devis enregistré' : 'Facture enregistrée');
        return true;
      } catch (err) {
        this.showToast(err.message || 'Erreur lors de l\'enregistrement.', true);
      } finally {
        this.saving = false;
      }
    },
    openDefineTemplate() {
      const t = this.getTemplate();
      if (!t) { this.showToast('Choisissez d\'abord un modèle.', true); return; }
      const base = (t.name || 'Modèle').replace(/^Copie - /, '');
      this.defineTpl = { open: true, name: `${base} — ${(this.organization && this.organization.name) || 'perso'}`.slice(0, 90), isDefault: false, saving: false, error: '' };
      this.$nextTick(() => { if (this.$refs.defineName) { this.$refs.defineName.focus(); this.$refs.defineName.select(); } });
    },
    async saveAsPersonalTemplate() {
      const t = this.getTemplate();
      if (!t || !this.defineTpl.name.trim()) return;
      this.defineTpl.saving = true;
      this.defineTpl.error = '';
      try {
        const src = t.source === 'marketplace' ? 'marketplace' : 'personal';
        const rawId = String(t.id);
        const body = new URLSearchParams({
          source_type: src,
          template_id: src === 'marketplace' && rawId.startsWith('m-') ? rawId.slice(2) : rawId,
          name: this.defineTpl.name.trim(),
          variables: JSON.stringify(this.dynamicVariables || {}),
          is_default: this.defineTpl.isDefault ? 'true' : 'false',
        });
        const res = await fetch(urls.saveTemplate, { method: 'POST', headers: { 'X-CSRFToken': this.csrf() }, body });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) throw new Error(data.error || 'Création impossible.');
        // Le nouveau modèle rejoint la bibliothèque et devient celui de ce document.
        if (data.template) {
          this.templatesLibrary = [data.template, ...this.templatesLibrary.filter((x) => String(x.id) !== String(data.template.id))];
          this.selectedTemplate = String(data.template.id);
          this.touch();
          this.updatePreview(true);
        }
        this.defineTpl.open = false;
        this.showToast(`Modèle « ${data.template_name} » créé${this.defineTpl.isDefault ? ' et utilisé par défaut' : ''}`);
      } catch (err) {
        this.defineTpl.error = err.message;
      } finally {
        this.defineTpl.saving = false;
      }
    },

    // --- devis : actions ---
    async postAction(url, body) {
      const res = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': this.csrf() }, body: body || new FormData() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.success === false) throw new Error(data.message || data.error || 'Action impossible.');
      return data;
    },
    async sendQuote() {
      try {
        if (this.dirty && !(await this.saveInvoice())) return;
        const data = await this.postAction(urls.send);
        this.invoiceData.status = 'sent';
        this.showToast(data.message || 'Devis envoyé au client');
      } catch (err) { this.showToast(err.message, true); }
    },
    async setQuoteStatus(status) {
      try {
        await this.postAction(status === 'accepted' ? urls.accept : urls.reject);
        this.invoiceData.status = status;
        this.showToast(status === 'accepted' ? 'Devis marqué comme accepté' : 'Devis marqué comme refusé');
      } catch (err) { this.showToast(err.message, true); }
    },
    async convertQuote() {
      try {
        if (this.dirty && !(await this.saveInvoice())) return;
        const data = await this.postAction(urls.convert);
        window.location.href = data.redirect;
      } catch (err) { this.showToast(err.message, true); }
    },
    convertedInvoiceUrl() {
      return this.invoiceData.converted_invoice_id ? urls.invoiceEdit.replace('00000000-0000-0000-0000-000000000000', this.invoiceData.converted_invoice_id) : '#';
    },
    async duplicateQuote() {
      try {
        const data = await this.postAction(urls.duplicate);
        window.location.href = urls.edit.replace('00000000-0000-0000-0000-000000000000', data.quote_id);
      } catch (err) { this.showToast(err.message, true); }
    },
    async uploadAttachment(evt) {
      const file = evt.target.files[0];
      if (!file) return;
      const body = new FormData();
      body.append('file', file);
      try {
        await this.postAction(urls.attachment, body);
        this.showToast(`« ${file.name} » ajouté au devis`);
      } catch (err) { this.showToast(err.message, true); } finally { evt.target.value = ''; }
    },
    async generateMilestoneInvoice(id) {
      try {
        if (this.dirty && !(await this.saveInvoice())) return;
        const data = await this.postAction(urls.milestoneInvoice.replace(/\/0\/generate-invoice\/$/, `/${id}/generate-invoice/`));
        window.location.href = data.redirect;
      } catch (err) { this.showToast(err.message, true); }
    },

    // --- devis : échéancier ---
    addMilestone() {
      const used = this.invoiceData.milestones.reduce((s, m) => s + (Number(m.percentage) || 0), 0);
      const pct = Math.max(0, 100 - used);
      const m = { label: this.invoiceData.milestones.length ? 'Échéance' : 'Acompte', due_date: '', percentage: pct || null, amount: 0 };
      this.milestoneFromPercent(m);
      this.invoiceData.milestones.push(m);
      this.touch();
      this.refreshUi();
    },
    applySchedulePreset(percents, labels) {
      const pending = this.invoiceData.milestones.filter((m) => m.id && m.status !== 'pending');
      this.invoiceData.milestones = [...pending, ...percents.map((p, i) => {
        const m = { label: labels[i], due_date: '', percentage: p, amount: 0 };
        this.milestoneFromPercent(m, false);
        return m;
      })];
      this.touch();
      this.refreshUi();
    },
    milestoneFromPercent(m, mark = true) {
      if (m.percentage !== null && m.percentage !== '' && !Number.isNaN(Number(m.percentage))) {
        m.amount = Math.round(this.total * Number(m.percentage)) / 100;
      }
      if (mark) this.touch();
    },
    milestonesSum() { return this.invoiceData.milestones.reduce((s, m) => s + (Number(m.amount) || 0), 0); },
    milestonesWarning() {
      if (!this.invoiceData.milestones.length) return '';
      const diff = Math.round((this.milestonesSum() - this.total) * 100) / 100;
      if (Math.abs(diff) < 0.01) return '';
      return `Les échéances totalisent ${this.formatCurrency(this.milestonesSum())} pour un devis de ${this.formatCurrency(this.total)} (écart ${this.formatCurrency(diff)}).`;
    },
    milestoneStatusLabel(status) {
      return { pending: 'À facturer', invoiced: 'Facturée', paid: 'Payée' }[status] || status || '';
    },

    // --- logo de l'organisation ---
    focusLogo() {
      this.section = 'style';
      this.logoFocus = true;
      this.$nextTick(() => this.$refs.logoBlock && this.$refs.logoBlock.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
      setTimeout(() => { this.logoFocus = false; }, 1600);
    },
    async uploadLogo(file) {
      if (!file) return;
      if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) { this.showToast('Format accepté : PNG, JPG, WEBP ou GIF.', true); return; }
      if (file.size > 2 * 1024 * 1024) { this.showToast('Le logo ne doit pas dépasser 2 Mo.', true); return; }
      await this.sendLogo(Object.assign(new FormData(), {}), file);
    },
    async removeLogo() { await this.sendLogo(new FormData(), null); },
    async sendLogo(body, file) {
      if (file) body.append('logo', file); else body.append('remove', '1');
      this.logoBusy = true;
      try {
        const res = await fetch(urls.logo, { method: 'POST', headers: { 'X-CSRFToken': this.csrf() }, body });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) throw new Error(data.error || 'Impossible de mettre à jour le logo.');
        this.organization = Object.assign({}, this.organization, { logo_url: data.url ? `${data.url}?v=${Date.now()}` : '' });
        this.updatePreview();
        this.refreshUi();
        this.showToast(file ? 'Logo mis à jour' : 'Logo retiré');
      } catch (err) {
        this.showToast(err.message, true);
      } finally {
        this.logoBusy = false;
      }
    },

    initials(name) {
      const parts = String(name || '?').trim().split(/\s+/).filter(Boolean);
      return ((parts[0] || '?')[0] + (parts[1] ? parts[1][0] : (parts[0] || '')[1] || '')).toUpperCase();
    },
  };
}
