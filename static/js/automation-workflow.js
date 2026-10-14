/* Centre d'automatisation : liste des workflows + board de nœuds reliés
   (déclencheur → Si/Sinon → Attendre → actions chaînées). Le graphe produit ici est
   validé côté serveur par apps/dashboard/automation_graph.py et exécuté par
   apps/dashboard/automation_engine.py — garder les clés de paramètres en phase. */
(function () {
  'use strict';

  const app = document.querySelector('[data-wf-app]');
  if (!app) return;

  const cfg = JSON.parse(document.getElementById('wf-config').textContent);
  let workflows = JSON.parse(document.getElementById('wf-workflows').textContent);
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const uid = () => `n${Math.random().toString(36).slice(2, 9)}`;
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const csrf = () => { const el = $('[name=csrfmiddlewaretoken]'); return el ? el.value : ''; };
  const icons = () => { if (typeof lucide !== 'undefined') lucide.createIcons(); };
  const rulesBase = cfg.saveUrl.replace(/save\/$/, '');

  // ------------------------------------------------------------------ catalogue
  const TRIGGER_META = {
    invoice_sent: { icon: 'send', group: 'Factures', desc: "Une facture est envoyée au client." },
    invoice_overdue: { icon: 'clock-alert', group: 'Factures', desc: "Une facture dépasse son échéance sans être payée." },
    payment_received: { icon: 'wallet-cards', group: 'Paiements', desc: 'Un paiement (facture ou jalon) est encaissé.' },
    client_created: { icon: 'user-plus', group: 'Clients', desc: 'Un nouveau client est créé.' },
    quote_sent: { icon: 'send-horizontal', group: 'Devis', desc: 'Un devis est envoyé au client.' },
    quote_accepted: { icon: 'circle-check', group: 'Devis', desc: 'Le client accepte un devis.' },
    quote_rejected: { icon: 'circle-x', group: 'Devis', desc: 'Le client refuse un devis.' },
    quote_expired: { icon: 'calendar-x', group: 'Devis', desc: "La validité d'un devis est dépassée sans réponse." },
    task_completed: { icon: 'check-check', group: 'Projets', desc: 'Une tâche de projet passe à « Terminée ».' },
    task_overdue: { icon: 'alarm-clock', group: 'Projets', desc: 'Une tâche non terminée dépasse son échéance.' },
    project_created: { icon: 'folder-plus', group: 'Projets', desc: 'Un nouveau projet est créé.' },
    milestone_created: { icon: 'flag', group: 'Projets', desc: 'Un jalon est ajouté à un projet.' },
    deliverable_validated: { icon: 'badge-check', group: 'Projets', desc: 'Le client valide un livrable depuis son portail.' },
    invoice_viewed: { icon: 'eye', group: 'Factures', desc: 'Le client ouvre la page de paiement de sa facture.' },
    quote_viewed: { icon: 'eye', group: 'Devis', desc: 'Le client ouvre le devis envoyé.' },
    document_viewed: { icon: 'file-search', group: 'Documents', desc: 'Le client consulte un document dans son portail.' },
    form_submitted: { icon: 'clipboard-check', group: 'Formulaires', desc: 'Le client envoie un formulaire que vous lui avez transmis.' },
    meeting_created: { icon: 'calendar-plus', group: 'Réunions', desc: 'Une réunion est planifiée sur un projet.' },
    meeting_updated: { icon: 'calendar-clock', group: 'Réunions', desc: 'Une réunion change : date, lieu, notes ou statut (terminée, annulée).' },
    appointment_booked: { icon: 'calendar-check', group: 'Calendrier', desc: 'Un client ou prospect réserve un créneau sur votre page de prise de rendez-vous.' },
    webhook_received: { icon: 'webhook', group: 'Intégrations', desc: "Un outil externe (site, Typeform, Calendly, Shopify, Zapier…) appelle l'adresse secrète du workflow." },
    calendar_date: { icon: 'calendar-days', group: 'Calendrier', desc: "À une date précise (répétable), ou avant / après une date de vos projets, jalons, factures ou réunions." },
  };
  // Déclencheur « Date du calendrier » : d'où vient la date (garder en phase avec automation_calendar.SOURCES).
  const CAL_SOURCES = [['fixed', 'Une date fixe'], ['project_delivery', 'La livraison d\'un projet'], ['project_start', 'Le début d\'un projet'],
    ['milestone_due', 'L\'échéance d\'un jalon'], ['invoice_due', 'L\'échéance d\'une facture'], ['meeting', 'Une réunion']];
  const CAL_REPEATS = [['none', 'Une seule fois'], ['daily', 'Tous les jours'], ['weekly', 'Toutes les semaines'], ['monthly', 'Tous les mois'], ['yearly', 'Tous les ans']];
  const CAL_SOURCE_LABEL = Object.fromEntries(CAL_SOURCES);
  // Déclencheur « Paiement reçu » : origine (garder en phase avec automation_engine.PAYMENT_ORIGINS).
  const PAYMENT_ORIGINS = [['any', 'Tous les paiements'], ['invoice_online', 'Facture payée en ligne'], ['milestone', "Jalon payé depuis l'espace client"], ['manual', 'Paiement enregistré manuellement']];
  const PAYMENT_ORIGIN_LABEL = Object.fromEntries(PAYMENT_ORIGINS);
  const CAL_REPEAT_LABEL = Object.fromEntries(CAL_REPEATS);
  const frDate = (iso) => (iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split('-').reverse().join('/') : '…');
  function calendarSummary(p) {
    if (p.source === 'fixed') return `Le ${frDate(p.date)} à ${p.time || '09:00'}${p.repeat && p.repeat !== 'none' ? ` · ${CAL_REPEAT_LABEL[p.repeat].toLowerCase()}` : ''}`;
    const unit = p.unit === 'hours' ? (p.offset > 1 ? 'heures' : 'heure') : (p.offset > 1 ? 'jours' : 'jour');
    const when = +p.offset ? `${p.offset} ${unit} ${p.direction === 'after' ? 'après' : 'avant'}` : 'Le jour de';
    return `${when} : ${(CAL_SOURCE_LABEL[p.source] || '').toLowerCase()}${p.source !== 'meeting' ? ` (à ${p.time || '09:00'})` : ''}`;
  }
  function todayIso() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
  const ACTION_META = {
    send_email: { icon: 'mail', desc: 'Envoie un email (à vous, au client ou à une adresse).' },
    notify: { icon: 'bell', desc: 'Crée une notification dans Billio.' },
    create_task: { icon: 'list-checks', desc: 'Ajoute une tâche « À faire » à votre liste.' },
    mark_late: { icon: 'flag', desc: 'Passe la facture concernée au statut « En retard ».' },
    create_document: { icon: 'file-text', desc: "Génère un document à partir d'un modèle." },
    create_project: { icon: 'folder-plus', desc: 'Crée un projet pour le client concerné.' },
    create_phase: { icon: 'columns-3', desc: 'Ajoute une colonne de phase au Kanban projets.' },
    create_milestone: { icon: 'milestone', desc: 'Ajoute un jalon au projet de l\'événement.' },
    create_deliverable: { icon: 'package-plus', desc: 'Ajoute un livrable au projet de l\'événement.' },
    create_form: { icon: 'clipboard-list', desc: 'Crée un formulaire pour le client (lien par email + portail).' },
    send_message: { icon: 'message-circle', desc: 'Envoie un message sur Slack, Telegram ou WhatsApp.' },
    create_meeting: { icon: 'calendar-plus', desc: 'Planifie une réunion sur le projet de l\'événement.' },
    drive_upload: { icon: 'hard-drive-upload', desc: 'Copie le PDF de la facture ou du devis dans votre Google Drive.' },
    app_action: { icon: 'plug-zap', desc: 'Crée une tâche, un contact, un ticket… dans un outil connecté (Trello, HubSpot, Brevo, Zapier…).' },
  };
  // Action « Envoyer vers une app » : outils et opérations (apps/integrations/app_actions.py).
  const APPS = Object.fromEntries((cfg.appActions || []).map((a) => [a.key, a]));
  const appOp = (p) => ((APPS[p.app] || {}).operations || []).find((o) => o.key === p.operation);
  const opDefaults = (o) => Object.fromEntries(((o && o.fields) || []).map((f) => [f.name, f.default || '']));
  function appActionDefaults(appKey) {
    const app = APPS[appKey] || (cfg.appActions || []).find((a) => a.connected) || (cfg.appActions || [])[0] || { operations: [] };
    const o = app.operations[0];
    return { app: app.key || '', operation: o ? o.key : '', values: opDefaults(o) };
  }
  const webhookUrl = (p) => (p.token ? `${cfg.webhookBase}${p.token}/` : '');
  const CHANNELS = Object.fromEntries((cfg.messagingChannels || []).map((c) => [c.key, c]));
  const FORM_TYPES = [['text', 'Texte court'], ['textarea', 'Texte long'], ['email', 'Email'], ['phone', 'Téléphone'], ['number', 'Nombre'], ['date', 'Date'], ['select', 'Liste de choix'], ['checkbox', 'Case à cocher']];
  const GROUP_COLORS = [['violet', '#7c3aed'], ['blue', '#2563eb'], ['green', '#16a34a'], ['amber', '#d97706'], ['rose', '#e11d48'], ['slate', '#475569']];
  const TRIGGER_LABEL = Object.fromEntries(cfg.triggers.map((t) => [t.key, t.label]));
  const ACTION_LABEL = Object.fromEntries(cfg.actions.map((a) => [a.key, a.label]));
  const TYPE_LABEL = { trigger: 'Déclencheur', condition: 'Condition', wait: 'Attente', action: 'Action' };

  const FIELD_LABEL = {
    amount: 'Montant', client: 'Client', client_name: 'Nom du client', client_email: 'Email du client', client_city: 'Ville du client',
    projet: 'Nom du projet', produit: 'Nom du livrable', weekday: 'Jour de la semaine', hour: 'Heure', day_of_month: 'Jour du mois',
    formulaire: 'Titre du formulaire',
  };
  const OP_ORDER = ['eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'contains', 'not_contains', 'starts_with', 'empty', 'not_empty'];
  const OP_LABEL = {
    eq: 'est égal à', neq: 'est différent de', gt: 'est supérieur à', gte: 'est supérieur ou égal à', lt: 'est inférieur à',
    lte: 'est inférieur ou égal à', contains: 'contient', not_contains: 'ne contient pas', starts_with: 'commence par', empty: 'est vide', not_empty: "n'est pas vide",
  };
  const OP_SHORT = { eq: '=', neq: '≠', gt: '>', gte: '≥', lt: '<', lte: '≤', contains: 'contient', not_contains: 'ne contient pas', starts_with: 'commence par', empty: 'vide', not_empty: 'renseigné' };
  const WEEKDAYS = [['1', 'Lundi'], ['2', 'Mardi'], ['3', 'Mercredi'], ['4', 'Jeudi'], ['5', 'Vendredi'], ['6', 'Samedi'], ['7', 'Dimanche']];
  const UNIT_LABEL = { minutes: ['minute', 'minutes'], hours: ['heure', 'heures'], days: ['jour', 'jours'] };
  // Variables proposées dans les messages : stockées en {{cle}}, affichées en pastilles lisibles.
  const VAR_DEFS = [
    ['client', 'Client'], ['montant', 'Montant'], ['numero', 'N° du document'], ['projet', 'Projet'], ['produit', 'Livrable'],
    ['date', 'Date du jour'], ['evenement', "Résumé de l'événement"], ['formulaire', 'Formulaire'], ['lien_formulaire', 'Lien du formulaire'], ['document', 'Document'], ['lien_document', 'Lien du document'],
    ['reunion', 'Réunion'], ['date_reunion', 'Date de la réunion'], ['lieu', 'Lieu'],
    ['jalon', 'Jalon'], ['date_echeance', "Date d'échéance"], ['origine', 'Origine du paiement'],
  ];
  const VARIABLES = VAR_DEFS.map(([k]) => k);
  const VAR_NAME = Object.fromEntries(VAR_DEFS);
  const TOKEN_RE = /\{\{\s*([a-z_]+)\s*\}\}/g;
  // Texte lisible (cartes du board, aperçus) : {{client}} -> [Client]
  const humanize = (text) => String(text ?? '').replace(TOKEN_RE, (m, k) => (VAR_NAME[k] ? `[${VAR_NAME[k]}]` : m));
  const tokenChip = (k) => `<span class="wf-tok" contenteditable="false" data-key="${k}">${esc(VAR_NAME[k] || k)}</span>`;
  const tokensHtml = (text) => esc(text || '').replace(TOKEN_RE, (m, k) => (VAR_NAME[k] ? tokenChip(k) : m)).replace(/\n/g, '<br>');
  function serializeTokens(el) {
    let out = '';
    el.childNodes.forEach((n) => {
      if (n.nodeType === 3) out += n.textContent.replace(/\u00a0/g, ' ');
      else if (n.nodeName === 'BR') out += '\n';
      else if (n.classList && n.classList.contains('wf-tok')) out += `{{${n.dataset.key}}}`;
      else if (n.nodeType === 1) out += (/^(DIV|P)$/.test(n.nodeName) && out && !out.endsWith('\n') ? '\n' : '') + serializeTokens(n);
    });
    return out;
  }
  // Champ de saisie avec pastilles de variables (remplace input / textarea).
  const tokenField = (param, value, multiline, placeholder = '', rows = 3) => `<div class="wf-tokens${multiline ? ' is-multi' : ''}" contenteditable="true" role="textbox"
      data-param="${param}" data-text data-tokens${multiline ? ' data-multiline' : ''} data-placeholder="${esc(humanize(placeholder))}"
      style="${multiline ? `min-height:${Math.max(2, rows) * 1.45 + 1}em` : ''}">${tokensHtml(value)}</div>`;
  const NODE_W = 284;

  function libraryItems() {
    const items = cfg.triggers.map((t) => ({ type: 'trigger', key: t.key, label: t.label, icon: TRIGGER_META[t.key]?.icon || 'zap', desc: TRIGGER_META[t.key]?.desc || '', group: 'Déclencheurs' }));
    items.push({ type: 'condition', key: 'if', label: 'Si / Sinon', icon: 'split', desc: 'Sépare le flux selon une ou plusieurs règles (ET / OU).', group: 'Logique' });
    items.push({ type: 'wait', key: 'delay', label: 'Attendre', icon: 'hourglass', desc: 'Met le flux en pause pendant une durée.', group: 'Logique' });
    cfg.actions.forEach((a) => items.push({ type: 'action', key: a.key, label: a.label, icon: ACTION_META[a.key]?.icon || 'play', desc: ACTION_META[a.key]?.desc || '', group: 'Actions' }));
    return items;
  }

  function defaultParams(type, key) {
    if (type === 'trigger' && key === 'payment_received') return { origin: 'any' };
    if (type === 'trigger' && key === 'webhook_received') return { create_client: false };
    if (type === 'trigger' && key === 'calendar_date') {
      return { source: 'fixed', date: todayIso(), time: '09:00', repeat: 'none', offset: 1, unit: 'days', direction: 'before' };
    }
    if (type === 'condition') return { match: 'all', rules: [{ field: 'amount', op: 'gt', value: '1000' }] };
    if (type === 'wait') return { amount: 1, unit: 'days' };
    if (type !== 'action') return {};
    return {
      send_email: { recipient: 'client', to: '', subject: '', body: '', attachments: [] },
      notify: { title: '', message: '', priority: 'medium' },
      create_task: { title: '', message: '', priority: 'high' },
      create_document: { template_id: '', title: '', field_values: {}, var_values: {}, share: false },
      create_project: { value: '', template_id: '', process_id: '', client: 'event' }, create_phase: { value: '' }, create_milestone: { value: '' }, create_deliverable: { value: '' },
      create_form: {
        title: 'Questionnaire de démarrage', intro: 'Quelques questions pour bien lancer votre projet.', notify_client: true,
        fields: [
          { label: 'Quels sont vos objectifs principaux ?', type: 'textarea', required: true, options: '' },
          { label: 'Date de lancement souhaitée', type: 'date', required: false, options: '' },
        ],
      },
      send_message: {
        channel: ((cfg.messagingChannels || []).find((c) => c.connected) || (cfg.messagingChannels || [])[0] || {}).key || 'slack',
        recipient_mode: 'default', recipient: '', text: '{{evenement}}',
      },
      create_meeting: { title: 'Réunion de lancement — {{client}}', in_days: 2, time: '10:00', duration: 45, location: '', notes: '' },
      drive_upload: { include_created: false },
      app_action: appActionDefaults(),
    }[key] || {};
  }

  function nodeIcon(node) {
    if (node.type === 'trigger') return TRIGGER_META[node.key]?.icon || 'zap';
    if (node.type === 'condition') return 'split';
    if (node.type === 'wait') return 'hourglass';
    return ACTION_META[node.key]?.icon || 'play';
  }
  function nodeTitle(node) {
    if (node.label) return node.label;
    if (node.type === 'trigger') return TRIGGER_LABEL[node.key] || 'Déclencheur';
    if (node.type === 'condition') return 'Si / Sinon';
    if (node.type === 'wait') return 'Attendre';
    return ACTION_LABEL[node.key] || 'Action';
  }
  function ruleSummary(r) {
    let value = r.value;
    if (r.field === 'client') value = (cfg.clients.find((c) => c.id === r.value) || {}).name || '…';
    if (r.field === 'weekday') value = (WEEKDAYS.find(([k]) => k === String(r.value)) || [])[1] || r.value;
    if (r.field === 'amount' && value) value = `${value} €`;
    if (r.field === 'hour' && value) value = `${value} h`;
    const needsValue = !['empty', 'not_empty'].includes(r.op);
    return `${FIELD_LABEL[r.field]} ${OP_SHORT[r.op]}${needsValue ? ` ${value || '…'}` : ''}`;
  }
  function nodeSummary(node) {
    const p = node.params || {};
    if (node.type === 'trigger') {
      if (node.key === 'calendar_date') return calendarSummary(p);
      if (node.key === 'payment_received') return PAYMENT_ORIGIN_LABEL[p.origin || 'any'];
      if (node.key === 'webhook_received') return p.token ? 'Adresse prête à coller dans votre outil' : "Enregistrez pour obtenir l'adresse";
      return TRIGGER_META[node.key]?.desc || '';
    }
    if (node.type === 'condition') {
      const rules = (p.rules || []).map(ruleSummary);
      const join = p.match === 'any' ? ' OU ' : ' ET ';
      return rules.length > 2 ? `${rules.slice(0, 2).join(join)} +${rules.length - 2}` : rules.join(join);
    }
    if (node.type === 'wait') {
      const [one, many] = UNIT_LABEL[p.unit] || ['', ''];
      return `${p.amount} ${p.amount > 1 ? many : one}`;
    }
    switch (node.key) {
      case 'send_email': {
        const to = { owner: 'vous', client: 'le client', custom: p.to || '…' }[p.recipient];
        return `À ${to}${p.subject ? ` · ${p.subject}` : ''}`;
      }
      case 'notify': case 'create_task': return p.title || ({ high: 'Priorité haute', medium: 'Priorité normale', low: 'Priorité basse' }[p.priority]);
      case 'create_document': return (cfg.documentTemplates.find((t) => String(t.id) === String(p.template_id)) || {}).name || 'Aucun modèle choisi';
      case 'mark_late': return 'Facture → En retard';
      case 'app_action': return `${(APPS[p.app] || {}).label || 'Outil'} › ${(appOp(p) || {}).label || '…'}`;
      default: return p.value || 'Nom par défaut';
    }
  }

  const cut = (text, n = 38) => { const t = String(text || '').replace(/\s+/g, ' ').trim(); return t.length > n ? `${t.slice(0, n - 1)}…` : t; };
  // Lignes « paramètre : valeur » affichées sur la carte de chaque bloc.
  function nodeParamRows(node) {
    const p = node.params || {};
    if (node.type === 'trigger') {
      if (node.key === 'payment_received') return [['Origine', PAYMENT_ORIGIN_LABEL[p.origin || 'any']]];
      if (node.key === 'webhook_received') return [['Adresse', p.token ? 'Prête (voir le panneau)' : "Générée à l'enregistrement"], ['Client', p.create_client ? 'Créé si inconnu' : 'Rapproché par email']];
      if (node.key !== 'calendar_date') return [];
      if (p.source === 'fixed') return [['Date', `${frDate(p.date)} à ${p.time || '09:00'}`], ['Répétition', CAL_REPEAT_LABEL[p.repeat] || 'Une seule fois']];
      return [['Date de', CAL_SOURCE_LABEL[p.source] || '…'], ['Quand', calendarSummary(p).split(' : ')[0]]];
    }
    if (node.type === 'condition') {
      return (p.rules || []).slice(0, 4).map((r, i) => [i === 0 ? 'Si' : (p.match === 'any' ? 'Ou' : 'Et'), ruleSummary(r)]);
    }
    if (node.type === 'wait') {
      const [one, many] = UNIT_LABEL[p.unit] || ['', ''];
      return [['Durée', `${p.amount} ${p.amount > 1 ? many : one}`]];
    }
    const priority = { high: 'Haute', medium: 'Normale', low: 'Basse' };
    switch (node.key) {
      case 'send_email':
        return [['À', { owner: 'Vous', client: 'Le client', custom: p.to || '…' }[p.recipient] || 'Vous'], ['Objet', p.subject || 'Par défaut'], ['Message', p.body || 'Par défaut'],
          ...((p.attachments || []).length ? [['Pièces jointes', (p.attachments || []).map(attachmentLabel).join(', ')]] : [])];
      case 'notify': case 'create_task':
        return [['Titre', p.title || 'Par défaut'], ['Priorité', priority[p.priority] || 'Normale']];
      case 'create_document':
        return [['Modèle', docTemplate(p.template_id).name || 'À choisir'], ['Titre', p.title || 'Nom du modèle'],
          ...(filledCount(p.template_id, p.field_values) ? [['Champs', `${filledCount(p.template_id, p.field_values)} rempli(s)`]] : []),
          ...(Object.keys(p.var_values || {}).length ? [['Variables', `${Object.keys(p.var_values).length} personnalisée(s)`]] : []),
          ...(p.share ? [['Client', "Partagé dans l'espace client"]] : [])];
      case 'mark_late': return [['Effet', 'Facture → En retard']];
      case 'app_action': {
        const app = APPS[p.app] || {};
        const o = appOp(p);
        const main = o && o.fields.find((f) => ['title', 'name'].includes(f.name));
        return [['Outil', app.label ? `${app.label}${app.connected ? '' : ' (non connecté)'}` : '—'], ['Opération', o ? o.label : '—'],
          ...(main && (p.values || {})[main.name] ? [[main.label, p.values[main.name]]] : [])];
      }
      case 'drive_upload': return [['Copie', p.include_created ? 'PDF + documents créés' : 'PDF facture / devis'], ['Dossier', 'Billio (Google Drive)']];
      case 'create_form':
        return [['Titre', p.title], ['Questions', String((p.fields || []).length)], ['Email au client', p.notify_client === false ? 'Non' : 'Oui']];
      case 'send_message': {
        const ch = CHANNELS[p.channel];
        const to = { default: 'Conversation par défaut', client: 'Téléphone du client', custom: p.recipient || '…' }[p.recipient_mode] || '';
        return [['Canal', ch ? `${ch.label}${ch.connected ? '' : ' (non connecté)'}` : '—'], ...(p.channel === 'slack' ? [] : [['Vers', to]]), ['Message', p.text]];
      }
      case 'create_meeting': {
        const days = Number(p.in_days) || 0;
        const when = days === 0 ? "Aujourd'hui" : (days === 1 ? 'Demain' : `Dans ${days} jours`);
        return [['Titre', p.title], ['Quand', `${when} à ${p.time}`], ['Durée', `${p.duration} min`], ...(p.location ? [['Lieu', p.location]] : [])];
      }
      case 'create_project': {
        const tpl = (cfg.projectTemplates || []).find((t) => String(t.id) === String(p.template_id));
        const client = p.client && p.client !== 'event' ? (cfg.clients.find((c) => String(c.id) === String(p.client)) || {}).name : '';
        return [['Projet', p.value || (tpl ? `${tpl.name} — {{client}}` : 'Par défaut')], ...(tpl ? [['Modèle', tpl.name]] : []),
                ['Client', client || "Celui de l'événement"]];
      }
      default: return [[{ create_project: 'Projet', create_phase: 'Phase', create_milestone: 'Jalon', create_deliverable: 'Livrable' }[node.key] || 'Nom', p.value || 'Par défaut']];
    }
  }

  // ------------------------------------------------------------------ documents & pièces jointes
  const docTemplate = (id) => cfg.documentTemplates.find((t) => String(t.id) === String(id)) || { fields: [] };
  const filledCount = (id, values) => (docTemplate(id).fields || []).filter((f) => (values || {})[f.id]).length;
  const attachmentLabel = (a) => (a.kind === 'event' ? 'PDF facture / devis' : a.kind === 'created' ? 'Documents du workflow' : (docTemplate(a.template_id).name || 'Document'));
  // Formulaire des champs d'un modèle de document ; `prefix` = chemin du paramètre (fv: ou att:<i>:).
  function docFieldsForm(templateId, values, prefix, varValues = {}) {
    const fields = docTemplate(templateId).fields || [];
    if (!templateId) return '';
    const vars = docVarsForm(templateId, varValues, prefix === 'fv:' ? 'vv:' : `${prefix}vv:`);
    if (!fields.length) return vars || '<p class="wf-help">Ce modèle n\'utilise aucune variable : rien à paramétrer.</p>';
    return `<div class="wf-docfields"><p class="wf-docfields-title">Champs du document</p>${fields.map((f) => {
      const v = (values || {})[f.id] || '';
      let control;
      if (f.type === 'choice') control = `<select data-param="${prefix}${f.id}"><option value="">${f.value ? `Par défaut : ${esc(f.value)}` : '— À choisir —'}</option>${opt((f.options || []).map((o) => [o, o]), v)}</select>`;
      else if (f.type === 'date') control = `<input type="date" data-param="${prefix}${f.id}" value="${esc(v)}">`;
      // Nombres et montants acceptent une variable du workflow (ex. Montant).
      else control = tokenField(`${prefix}${f.id}`, v, false, f.value ? `Par défaut : ${f.value}` : ({ number: 'Nombre ou variable', money: 'Montant ou variable' }[f.type] || 'Texte ou variable'));
      const kind = { choice: 'liste', date: 'date', number: 'nombre', money: 'montant' }[f.type];
      return `<label class="wf-field"><span>${esc(f.label)}${f.required ? ' <b class="wf-req">*</b>' : ''}${kind ? ` <small class="wf-kind">${kind}</small>` : ''}</span>${control}${f.help ? `<small class="wf-help">${esc(f.help)}</small>` : ''}</label>`;
    }).join('')}<p class="wf-help">Laissés vides, les champs gardent la valeur par défaut du modèle. Créé depuis un devis ou une facture, le document remplit aussi ses tableaux reliés avec leurs lignes.</p></div>${vars}`;
  }
  // Variables automatiques utilisées par le modèle : remplies seules, ou personnalisées ici.
  const VAR_SOURCE = {
    Client: 'fiche du client de l\'événement', 'Votre entreprise': 'vos paramètres', Document: 'le document créé',
    'Devis du client': 'devis de l\'événement ou dernier devis', 'Facture du client': 'facture de l\'événement ou dernière facture',
  };
  function docVarsForm(templateId, varValues, prefix) {
    const vars = docTemplate(templateId).variables || [];
    if (!vars.length) return '';
    varValues = varValues || {};
    const custom = vars.filter((v) => v.key in varValues).length;
    return `<div class="wf-docfields wf-docvars"><p class="wf-docfields-title">Variables du document
        <small>${custom ? `${custom} personnalisée(s)` : 'toutes automatiques'}</small></p>
      ${vars.map((v) => {
        const on = v.key in varValues;
        return `<div class="wf-docvar${on ? ' is-custom' : ''}">
          <div class="wf-docvar-head">
            <span class="wf-docvar-name"><b>${esc(v.label)}</b><small>${on ? 'Valeur personnalisée' : `Auto · <span>${esc(VAR_SOURCE[v.group] || v.group)}</span>`}</small></span>
            ${on ? `<button type="button" class="wf-docvar-btn" data-var-reset="${esc(prefix + v.key)}" title="Revenir à la valeur automatique"><i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i> Auto</button>`
              : `<button type="button" class="wf-docvar-btn" data-var-custom="${esc(prefix + v.key)}"><i data-lucide="pencil" class="w-3.5 h-3.5"></i> Personnaliser</button>`}
          </div>
          ${on ? tokenField(prefix + v.key, varValues[v.key], false, 'Texte ou variable du workflow') : ''}
        </div>`;
      }).join('')}
      <p class="wf-help">Une variable personnalisée remplace la valeur automatique dans ce document. Vide, elle reste automatique.</p></div>`;
  }
  // Écrit un paramètre, y compris les chemins imbriqués (champs de document, pièces jointes).
  function setParam(node, path, value) {
    const p = node.params;
    if (path.startsWith('fv:')) { p.field_values = p.field_values || {}; p.field_values[path.slice(3)] = value; return; }
    if (path.startsWith('vv:')) { p.var_values = p.var_values || {}; p.var_values[path.slice(3)] = value; return; }
    if (path.startsWith('av:')) { p.values = p.values || {}; p.values[path.slice(3)] = value; return; }
    if (path.startsWith('att:')) {
      const [, index, ...rest] = path.split(':');
      const key = rest.join(':');
      const item = (p.attachments || [])[+index];
      if (!item) return;
      if (key === 'template_id') { item.template_id = value; item.field_values = {}; item.var_values = {}; }
      else if (key.startsWith('vv:')) { item.var_values = item.var_values || {}; item.var_values[key.slice(3)] = value; }
      else { item.field_values = item.field_values || {}; item.field_values[key] = value; }
      return;
    }
    p[path] = value;
  }

  // ------------------------------------------------------------------ état de l'éditeur
  let current = null; // { id, name, description, is_active, graph }
  let selected = null; // { kind: 'node'|'edge', id }
  let view = { x: 60, y: 60, zoom: 1 };
  let dirty = false;
  let testLog = null; // { nodeId: entry }
  let history = { stack: [], index: -1 };
  let lastFocusedText = null;
  let lastTokenRange = null; // position du curseur dans le dernier champ à pastilles

  const board = $('[data-wf-board]');
  const inner = $('[data-wf-board-inner]');
  const nodesHost = $('[data-wf-nodes]');
  const edgesSvg = $('[data-wf-edges]');
  const inspector = $('[data-wf-inspector]');

  const graph = () => current.graph;
  const nodeById = (id) => graph().nodes.find((n) => n.id === id);
  const triggerNode = () => graph().nodes.find((n) => n.type === 'trigger');

  function snapshot() {
    const snap = JSON.stringify(graph());
    if (history.stack[history.index] === snap) return;
    history.stack = history.stack.slice(0, history.index + 1);
    history.stack.push(snap);
    if (history.stack.length > 80) history.stack.shift();
    history.index = history.stack.length - 1;
  }
  function change({ rerender = true } = {}) {
    dirty = true;
    if (!liveMode) testLog = null;
    snapshot();
    updateDirty();
    if (rerender) renderBoard();
    updateHistoryButtons();
    scheduleLive();
  }
  function undo() { if (history.index > 0) { history.index -= 1; current.graph = JSON.parse(history.stack[history.index]); afterHistory(); } }
  function redo() { if (history.index < history.stack.length - 1) { history.index += 1; current.graph = JSON.parse(history.stack[history.index]); afterHistory(); } }
  function afterHistory() {
    dirty = true; if (!liveMode) testLog = null;
    if (selected && selected.kind === 'node' && !nodeById(selected.id)) selected = null;
    scheduleLive();
    renderBoard(); renderInspector(); updateDirty(); updateHistoryButtons();
  }
  function updateHistoryButtons() {
    $('[data-wf-undo]').disabled = history.index <= 0;
    $('[data-wf-redo]').disabled = history.index >= history.stack.length - 1;
  }
  function updateDirty() { $('[data-wf-dirty]').textContent = dirty ? 'Modifications non enregistrées' : ''; }

  // ------------------------------------------------------------------ validation côté client
  function reachableIds() {
    const start = triggerNode();
    const seen = new Set();
    if (!start) return seen;
    const stack = [start.id];
    while (stack.length) {
      const id = stack.pop();
      if (seen.has(id)) continue;
      seen.add(id);
      graph().edges.filter((e) => e.from === id).forEach((e) => stack.push(e.to));
    }
    return seen;
  }
  function nodeWarnings(node, reachable) {
    const w = [];
    const p = node.params || {};
    if (node.type !== 'trigger' && !reachable.has(node.id)) w.push('Bloc non relié au déclencheur');
    if (node.type === 'condition') {
      if (!(p.rules || []).length) w.push('Ajoutez au moins une règle');
      (p.rules || []).forEach((r) => { if (!['empty', 'not_empty'].includes(r.op) && !String(r.value ?? '').trim()) w.push(`Valeur manquante : ${FIELD_LABEL[r.field]}`); });
      if (!graph().edges.some((e) => e.from === node.id)) w.push('Reliez la sortie « Oui » ou « Non »');
    }
    if (node.key === 'create_document' && !p.template_id) w.push('Choisissez un modèle de document');
    if (node.key === 'send_message' && CHANNELS[p.channel] && !CHANNELS[p.channel].connected) w.push(`${CHANNELS[p.channel].label} n'est pas connecté (page Intégrations)`);
    if (node.key === 'send_message' && !(p.text || '').trim()) w.push('Le message est vide');
    if (node.key === 'app_action') {
      const o = appOp(p);
      if (!o) w.push('Choisissez un outil et une opération');
      else {
        if (!APPS[p.app].connected) w.push(`${APPS[p.app].label} n'est pas connecté (page Intégrations)`);
        o.fields.filter((f) => f.required && !String((p.values || {})[f.name] || '').trim()).forEach((f) => w.push(`À renseigner : ${f.label}`));
      }
    }
    if (node.key === 'send_email' && (p.attachments || []).some((a) => a.kind === 'template' && !a.template_id)) w.push('Choisissez le document à joindre');
    if (node.key === 'create_form' && !(p.fields || []).some((f) => (f.label || '').trim())) w.push('Ajoutez au moins une question');
    if (node.key === 'send_email' && p.recipient === 'custom' && !p.to) w.push("Indiquez l'adresse du destinataire");
    if (node.type === 'wait' && !graph().edges.some((e) => e.from === node.id)) w.push('Rien ne suit cette attente');
    return w;
  }

  // ------------------------------------------------------------------ rendu du board
  function applyView() {
    inner.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`;
    board.style.backgroundSize = `${20 * view.zoom}px ${20 * view.zoom}px`;
    board.style.backgroundPosition = `${view.x}px ${view.y}px`;
    $('[data-wf-zoom-reset]').textContent = `${Math.round(view.zoom * 100)}%`;
  }

  function portsHtml(node) {
    const outgoing = (port) => graph().edges.some((e) => e.from === node.id && e.port === port);
    const out = (port, label, cls = '') => `
      <span class="wf-port wf-port--out ${cls}${outgoing(port) ? ' is-connected' : ''}" data-port="${port}" title="Tirer pour relier">
        ${label ? `<em>${label}</em>` : ''}
      </span>
      ${outgoing(port) ? '' : `<button type="button" class="wf-port-add ${cls}" data-port-add="${port}" title="Ajouter un bloc après"><i data-lucide="plus" class="w-3 h-3"></i></button>`}`;
    const input = node.type === 'trigger' ? '' : '<span class="wf-port wf-port--in" data-port-in></span>';
    if (node.type === 'condition') {
      return `${input}<div class="wf-branch-ports"><div class="wf-branch wf-branch--true">${out('true', 'Oui', 'is-true')}</div><div class="wf-branch wf-branch--false">${out('false', 'Non', 'is-false')}</div></div>`;
    }
    return `${input}<div class="wf-single-port">${out('out', '')}</div>`;
  }

  function renderNodes() {
    const reachable = reachableIds();
    nodesHost.innerHTML = graph().nodes.map((node) => {
      const warnings = nodeWarnings(node, reachable);
      const test = testLog && testLog[node.id];
      const testCls = testLog ? (test ? ` is-run is-run--${test.status}` : ' is-skipped') : '';
      return `
      <div class="wf-node wf-node--${node.type}${selected && selected.kind === 'node' && selected.id === node.id ? ' is-selected' : ''}${testCls}"
           data-node="${node.id}" style="left:${node.x}px;top:${node.y}px;width:${NODE_W}px">
        <div class="wf-node-head">
          <span class="wf-node-icon"><i data-lucide="${nodeIcon(node)}" class="w-4 h-4"></i></span>
          <div class="wf-node-titles">
            <span class="wf-node-type">${TYPE_LABEL[node.type]}</span>
            <span class="wf-node-title">${esc(nodeTitle(node))}</span>
          </div>
          ${warnings.length ? `<span class="wf-node-warn" title="${esc(warnings.join('\n'))}"><i data-lucide="triangle-alert" class="w-3.5 h-3.5"></i></span>` : ''}
          ${test ? `<span class="wf-node-status" title="${esc(test.detail)}">${{ ok: '✓', true: 'Oui', false: 'Non', error: '!', waiting: '⏸' }[test.status] || ''}</span>` : ''}
        </div>
        ${node.type === 'trigger'
          ? `<div class="wf-node-body">${esc(nodeSummary(node))}</div>`
          : `<dl class="wf-node-params">${nodeParamRows(node).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(cut(humanize(v)))}</dd></div>`).join('')}</dl>`}
        ${test && test.detail && node.type === 'action' ? `<div class="wf-node-test">${esc(test.detail)}</div>` : ''}
        ${portsHtml(node)}
      </div>`;
    }).join('');
    icons();
  }

  function portPoint(nodeId, port, side) {
    const node = nodeById(nodeId);
    const el = nodesHost.querySelector(`[data-node="${nodeId}"]`);
    if (!node || !el) return { x: 0, y: 0 };
    const portEl = side === 'in' ? el.querySelector('[data-port-in]') : el.querySelector(`[data-port="${port}"]`);
    if (!portEl) return { x: node.x, y: node.y };
    let x = portEl.offsetWidth / 2; let y = portEl.offsetHeight / 2;
    let cur = portEl;
    while (cur && cur !== el) { x += cur.offsetLeft; y += cur.offsetTop; cur = cur.offsetParent; }
    return { x: node.x + x, y: node.y + y };
  }

  function curve(a, b) {
    const dx = Math.max(50, Math.abs(b.x - a.x) / 2);
    return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
  }

  function edgeTaken(edge) {
    if (!testLog) return false;
    const from = testLog[edge.from];
    if (!from || !testLog[edge.to]) return false;
    if (from.status === 'true' || from.status === 'false') return edge.port === from.status;
    return true;
  }

  function renderEdges() {
    const parts = [];
    graph().edges.forEach((edge, index) => {
      const a = portPoint(edge.from, edge.port, 'out');
      const b = portPoint(edge.to, null, 'in');
      const d = curve(a, b);
      const isSel = selected && selected.kind === 'edge' && selected.id === index;
      const cls = ['wf-edge', `wf-edge--${edge.port}`, isSel ? 'is-selected' : '', testLog ? (edgeTaken(edge) ? 'is-taken' : 'is-idle') : ''].join(' ');
      parts.push(`<g class="${cls}" data-edge="${index}"><path class="wf-edge-hit" d="${d}"/><path class="wf-edge-line" d="${d}"/></g>`);
      if (isSel) {
        const mx = (a.x + b.x) / 2; const my = (a.y + b.y) / 2;
        parts.push(`<foreignObject x="${mx - 13}" y="${my - 13}" width="26" height="26"><button xmlns="http://www.w3.org/1999/xhtml" type="button" class="wf-edge-delete" data-edge-delete="${index}" title="Supprimer le lien">×</button></foreignObject>`);
      }
    });
    edgesSvg.innerHTML = parts.join('') + '<path class="wf-edge-temp" data-wf-temp d=""/>';
  }

  function renderBoard() {
    renderGroups();
    renderNodes();
    renderEdges();
    $('[data-wf-board-empty]').hidden = graph().nodes.length > 0;
  }

  // ------------------------------------------------------------------ coordonnées
  function boardPoint(evt) {
    const rect = board.getBoundingClientRect();
    return { x: (evt.clientX - rect.left - view.x) / view.zoom, y: (evt.clientY - rect.top - view.y) / view.zoom };
  }
  const snap20 = (v) => Math.round(v / 20) * 20;

  // ------------------------------------------------------------------ ajout de nœuds
  function createNode(type, key, at) {
    if (type === 'trigger' && triggerNode()) {
      const trig = triggerNode();
      trig.key = key;
      trig.label = '';
      selected = { kind: 'node', id: trig.id };
      toast('Un seul déclencheur par workflow : il a été remplacé.');
      change();
      renderInspector();
      return trig;
    }
    const node = { id: uid(), type, key, x: snap20(at.x), y: snap20(at.y), label: '', params: defaultParams(type, key) };
    graph().nodes.push(node);
    selected = { kind: 'node', id: node.id };
    return node;
  }

  function freePortOf(node) {
    const ports = node.type === 'condition' ? ['true', 'false'] : ['out'];
    return ports.find((p) => !graph().edges.some((e) => e.from === node.id && e.port === p));
  }

  // Place un nouveau bloc à droite d'une sortie, en évitant de recouvrir un bloc existant.
  function placeAfter(source, port) {
    const siblings = graph().edges.filter((e) => e.from === source.id).length;
    let y = source.y + (port === 'false' ? 140 : 0) + siblings * 20;
    const x = source.x + NODE_W + 90;
    while (graph().nodes.some((n) => Math.abs(n.x - x) < NODE_W && Math.abs(n.y - y) < 110)) y += 130;
    return { x, y };
  }

  function addFromLibrary(item, at, connectFrom) {
    let source = connectFrom ? nodeById(connectFrom.id) : null;
    let port = connectFrom ? connectFrom.port : null;
    if (!source && !at && selected && selected.kind === 'node' && item.type !== 'trigger') {
      source = nodeById(selected.id);
      port = source && freePortOf(source);
      if (!port) source = null;
    }
    let position = at;
    if (!position && source) position = placeAfter(source, port);
    if (!position) {
      const rect = board.getBoundingClientRect();
      position = { x: (rect.width / 2 - view.x) / view.zoom - NODE_W / 2, y: (rect.height / 2 - view.y) / view.zoom - 40 };
      if (item.type === 'trigger' && !graph().nodes.length) position = { x: 40, y: 120 };
    }
    const node = createNode(item.type, item.key, position);
    if (source && node.type !== 'trigger' && source.id !== node.id) {
      graph().edges = graph().edges.filter((e) => !(e.from === source.id && e.port === port && connectFrom && connectFrom.replace));
      graph().edges.push({ from: source.id, port, to: node.id });
    }
    change();
    renderInspector();
  }

  // ------------------------------------------------------------------ bibliothèque
  const libraryHost = $('[data-wf-library]');
  function renderLibrary(filter = '') {
    const q = filter.trim().toLowerCase();
    const items = libraryItems().filter((i) => !q || `${i.label} ${i.desc}`.toLowerCase().includes(q));
    const groups = {};
    items.forEach((i) => { (groups[i.group] = groups[i.group] || []).push(i); });
    libraryHost.innerHTML = Object.entries(groups).map(([group, list]) => `
      <div class="wf-lib-group">
        <p class="wf-lib-title">${group}</p>
        ${list.map((i) => `
          <button type="button" class="wf-lib-item wf-lib-item--${i.type}" draggable="true" data-lib="${i.type}:${i.key}" title="${esc(i.desc)}">
            <span class="wf-lib-icon"><i data-lucide="${i.icon}" class="w-3.5 h-3.5"></i></span>
            <span class="wf-lib-text"><strong>${esc(i.label)}</strong><small>${esc(i.desc)}</small></span>
          </button>`).join('')}
      </div>`).join('') || '<p class="wf-empty">Aucun bloc ne correspond.</p>';
    icons();
  }
  const libItem = (ref) => { const [type, key] = ref.split(':'); return libraryItems().find((i) => i.type === type && i.key === key); };
  $('[data-wf-library-search]').addEventListener('input', (e) => renderLibrary(e.target.value));
  libraryHost.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-lib]');
    if (btn) addFromLibrary(libItem(btn.dataset.lib));
  });
  libraryHost.addEventListener('dragstart', (e) => {
    const btn = e.target.closest('[data-lib]');
    if (btn) { e.dataTransfer.setData('text/wf-node', btn.dataset.lib); e.dataTransfer.effectAllowed = 'copy'; }
  });
  board.addEventListener('dragover', (e) => { if (Array.from(e.dataTransfer.types).includes('text/wf-node')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
  board.addEventListener('drop', (e) => {
    const ref = e.dataTransfer.getData('text/wf-node');
    if (!ref) return;
    e.preventDefault();
    const p = boardPoint(e);
    addFromLibrary(libItem(ref), { x: p.x - NODE_W / 2, y: p.y - 30 });
  });

  // ------------------------------------------------------------------ ajout rapide (popover)
  const quick = $('[data-wf-quick]');
  let quickContext = null;
  function openQuick(clientX, clientY, context) {
    quickContext = context;
    quick.hidden = false;
    const input = $('[data-wf-quick-search]');
    input.value = '';
    renderQuick('');
    const w = quick.offsetWidth; const h = quick.offsetHeight;
    quick.style.left = `${Math.min(clientX, window.innerWidth - w - 12)}px`;
    quick.style.top = `${Math.min(clientY, window.innerHeight - h - 12)}px`;
    input.focus();
  }
  function closeQuick() { quick.hidden = true; quickContext = null; }
  function renderQuick(filter) {
    const q = filter.trim().toLowerCase();
    const items = libraryItems().filter((i) => i.type !== 'trigger' && (!q || i.label.toLowerCase().includes(q)));
    $('[data-wf-quick-list]').innerHTML = items.map((i) => `
      <button type="button" class="wf-quick-item wf-lib-item--${i.type}" data-quick="${i.type}:${i.key}">
        <span class="wf-lib-icon"><i data-lucide="${i.icon}" class="w-3.5 h-3.5"></i></span>${esc(i.label)}
      </button>`).join('') || '<p class="wf-empty">Aucun résultat</p>';
    icons();
  }
  $('[data-wf-quick-search]').addEventListener('input', (e) => renderQuick(e.target.value));
  $('[data-wf-quick-search]').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { const first = $('[data-quick]', quick); if (first) first.click(); }
    if (e.key === 'Escape') closeQuick();
  });
  quick.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-quick]');
    if (!btn || !quickContext) return;
    const ctx = quickContext;
    closeQuick();
    addFromLibrary(libItem(btn.dataset.quick), ctx.at, ctx.from);
  });
  document.addEventListener('pointerdown', (e) => { if (!quick.hidden && !quick.contains(e.target)) closeQuick(); });

  // ------------------------------------------------------------------ interactions du board
  board.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 && e.button !== 1) return;
    const addBtn = e.target.closest('[data-port-add]');
    if (addBtn) {
      e.preventDefault();
      e.stopPropagation();
      const nodeId = addBtn.closest('[data-node]').dataset.node;
      const source = nodeById(nodeId);
      openQuick(e.clientX + 8, e.clientY - 20, { from: { id: nodeId, port: addBtn.dataset.portAdd }, at: placeAfter(source, addBtn.dataset.portAdd) });
      return;
    }
    if (e.target.closest('[data-edge-delete]')) {
      e.stopPropagation();
      graph().edges.splice(+e.target.closest('[data-edge-delete]').dataset.edgeDelete, 1);
      selected = null;
      change();
      renderInspector();
      return;
    }
    const port = e.target.closest('[data-port]');
    if (port) { e.preventDefault(); startConnect(e, port.closest('[data-node]').dataset.node, port.dataset.port); return; }
    const nodeEl = e.target.closest('[data-node]');
    if (nodeEl) { e.preventDefault(); startNodeDrag(e, nodeEl.dataset.node); return; }
    const edgeEl = e.target.closest('[data-edge]');
    if (edgeEl) {
      selected = { kind: 'edge', id: +edgeEl.dataset.edge };
      renderEdges();
      renderNodes();
      renderInspector();
      return;
    }
    const groupHandle = e.target.closest('[data-group-drag], [data-group-resize]');
    if (groupHandle) {
      e.preventDefault();
      startGroupDrag(e, groupHandle.closest('[data-group]').dataset.group, groupHandle.hasAttribute('data-group-resize') ? 'resize' : 'move');
      return;
    }
    if (e.target.closest('.wf-board-controls, .wf-sim-alerts')) return;
    startPan(e);
  });

  // Glisser le fond (clic gauche ou molette) ne doit ni sélectionner de texte ni lancer
  // le défilement automatique du clic molette : on bloque l'action par défaut du mousedown.
  board.addEventListener('mousedown', (e) => {
    if (e.button !== 0 && e.button !== 1) return;
    if (e.target.closest('input, textarea, select, [contenteditable="true"], .wf-board-controls')) return;
    e.preventDefault();
  });
  board.addEventListener('auxclick', (e) => { if (e.button === 1) e.preventDefault(); });

  function startPan(e) {
    const start = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    let moved = false;
    if (e.button === 1) e.preventDefault();
    const selection = window.getSelection && window.getSelection();
    if (selection && !selection.isCollapsed) selection.removeAllRanges();
    board.classList.add('is-panning');
    document.body.classList.add('wf-no-select');
    function onMove(ev) {
      const dx = ev.clientX - start.x; const dy = ev.clientY - start.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
      view.x = start.vx + dx; view.y = start.vy + dy;
      applyView();
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      board.classList.remove('is-panning');
      document.body.classList.remove('wf-no-select');
      if (!moved && selected) { selected = null; renderGroups(); renderNodes(); renderEdges(); renderInspector(); }
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  function startNodeDrag(e, nodeId) {
    const node = nodeById(nodeId);
    const start = boardPoint(e);
    const origin = { x: node.x, y: node.y };
    let moved = false;
    if (!selected || selected.kind !== 'node' || selected.id !== nodeId) {
      selected = { kind: 'node', id: nodeId };
      $$('.wf-node', nodesHost).forEach((n) => n.classList.toggle('is-selected', n.dataset.node === nodeId));
      renderGroups();
      renderEdges();
      renderInspector();
    }
    const el = nodesHost.querySelector(`[data-node="${nodeId}"]`);
    function onMove(ev) {
      const p = boardPoint(ev);
      const dx = p.x - start.x; const dy = p.y - start.y;
      if (!moved && Math.hypot(dx, dy) * view.zoom < 3) return;
      moved = true;
      node.x = ev.altKey ? Math.round(origin.x + dx) : snap20(origin.x + dx);
      node.y = ev.altKey ? Math.round(origin.y + dy) : snap20(origin.y + dy);
      el.style.left = `${node.x}px`; el.style.top = `${node.y}px`;
      el.classList.add('is-dragging');
      renderEdges();
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      el.classList.remove('is-dragging');
      if (moved) change({ rerender: false });
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  function createsCycle(from, to) {
    // Un lien from → to crée une boucle si `from` est déjà atteignable depuis `to`.
    const stack = [to]; const seen = new Set();
    while (stack.length) {
      const id = stack.pop();
      if (id === from) return true;
      if (seen.has(id)) continue;
      seen.add(id);
      graph().edges.filter((e) => e.from === id).forEach((e) => stack.push(e.to));
    }
    return false;
  }

  function startConnect(e, fromId, port) {
    const temp = $('[data-wf-temp]', edgesSvg);
    const a = portPoint(fromId, port, 'out');
    board.classList.add('is-connecting');
    let hoverId = null;
    function onMove(ev) {
      const p = boardPoint(ev);
      temp.setAttribute('d', curve(a, p));
      const under = document.elementFromPoint(ev.clientX, ev.clientY);
      const target = under && under.closest('[data-node]');
      hoverId = target && target.dataset.node !== fromId ? target.dataset.node : null;
      $$('.wf-node', nodesHost).forEach((n) => n.classList.toggle('is-drop-target', n.dataset.node === hoverId));
    }
    function onUp(ev) {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      board.classList.remove('is-connecting');
      temp.setAttribute('d', '');
      $$('.wf-node', nodesHost).forEach((n) => n.classList.remove('is-drop-target'));
      if (hoverId) {
        const target = nodeById(hoverId);
        if (target.type === 'trigger') { toast('Un déclencheur ne peut pas recevoir de lien.'); return; }
        if (createsCycle(fromId, hoverId)) { toast('Ce lien créerait une boucle.'); return; }
        if (graph().edges.some((x) => x.from === fromId && x.port === port && x.to === hoverId)) return;
        graph().edges.push({ from: fromId, port, to: hoverId });
        change();
        return;
      }
      const p = boardPoint(ev);
      if (Math.hypot(p.x - a.x, p.y - a.y) < 20) return;
      openQuick(ev.clientX, ev.clientY, { from: { id: fromId, port }, at: { x: p.x, y: p.y - 30 } });
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  board.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      const rect = board.getBoundingClientRect();
      const mx = e.clientX - rect.left; const my = e.clientY - rect.top;
      const next = Math.max(0.3, Math.min(1.8, view.zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
      view.x = mx - ((mx - view.x) * next) / view.zoom;
      view.y = my - ((my - view.y) * next) / view.zoom;
      view.zoom = next;
    } else {
      view.x -= e.deltaX; view.y -= e.deltaY;
    }
    applyView();
  }, { passive: false });

  function zoomBy(factor) {
    const rect = board.getBoundingClientRect();
    const mx = rect.width / 2; const my = rect.height / 2;
    const next = Math.max(0.3, Math.min(1.8, view.zoom * factor));
    view.x = mx - ((mx - view.x) * next) / view.zoom;
    view.y = my - ((my - view.y) * next) / view.zoom;
    view.zoom = next;
    applyView();
  }
  function fitView() {
    const nodes = graph().nodes;
    if (!nodes.length) { view = { x: 60, y: 60, zoom: 1 }; applyView(); return; }
    const els = nodes.map((n) => ({ n, el: nodesHost.querySelector(`[data-node="${n.id}"]`) }));
    const minX = Math.min(...nodes.map((n) => n.x)); const minY = Math.min(...nodes.map((n) => n.y));
    const maxX = Math.max(...els.map(({ n }) => n.x + NODE_W));
    const maxY = Math.max(...els.map(({ n, el }) => n.y + (el ? el.offsetHeight : 120)));
    const rect = board.getBoundingClientRect();
    // Pas en dessous de 60 % : au-delà les cartes deviennent illisibles, on préfère
    // cadrer le début du workflow (déclencheur) et laisser défiler.
    const zoom = Math.max(0.6, Math.min(1.1, Math.min((rect.width - 120) / (maxX - minX), (rect.height - 140) / (maxY - minY))));
    view.zoom = zoom;
    const overflow = (maxX - minX) * zoom > rect.width - 60;
    view.x = overflow ? 40 - minX * zoom : (rect.width - (maxX - minX) * zoom) / 2 - minX * zoom;
    view.y = (rect.height - (maxY - minY) * zoom) / 2 - minY * zoom - 10;
    applyView();
  }
  $('[data-wf-zoom-in]').addEventListener('click', () => zoomBy(1.15));
  $('[data-wf-zoom-out]').addEventListener('click', () => zoomBy(1 / 1.15));
  $('[data-wf-zoom-reset]').addEventListener('click', () => { view.zoom = 1; applyView(); });
  $('[data-wf-fit]').addEventListener('click', fitView);
  $('[data-wf-undo]').addEventListener('click', undo);
  $('[data-wf-redo]').addEventListener('click', redo);
  $('[data-wf-layout]').addEventListener('click', () => { autoLayout(graph()); change(); requestAnimationFrame(fitView); });

  // Rangement automatique : colonnes par profondeur depuis le déclencheur, branche
  // « Oui » au-dessus de « Non ».
  function autoLayout(g) {
    const trig = g.nodes.find((n) => n.type === 'trigger');
    const depth = {};
    const order = [];
    if (trig) {
      depth[trig.id] = 0;
      const queue = [trig.id];
      while (queue.length) {
        const id = queue.shift();
        order.push(id);
        const outs = g.edges.filter((e) => e.from === id).sort((a, b) => (a.port === 'false') - (b.port === 'false'));
        outs.forEach((e) => {
          const d = depth[id] + 1;
          if (depth[e.to] === undefined || depth[e.to] < d) { depth[e.to] = d; queue.push(e.to); }
        });
      }
    }
    const maxDepth = Math.max(0, ...Object.values(depth));
    g.nodes.forEach((n) => { if (depth[n.id] === undefined) depth[n.id] = maxDepth + 1; });
    const columns = {};
    const seen = new Set();
    [...order, ...g.nodes.map((n) => n.id)].forEach((id) => {
      if (seen.has(id)) return;
      seen.add(id);
      (columns[depth[id]] = columns[depth[id]] || []).push(id);
    });
    Object.entries(columns).forEach(([d, ids]) => {
      const total = ids.length;
      ids.forEach((id, i) => {
        const node = g.nodes.find((n) => n.id === id);
        node.x = 40 + Number(d) * (NODE_W + 70);
        node.y = 160 + (i - (total - 1) / 2) * 150;
      });
    });
  }

  // ------------------------------------------------------------------ clavier
  document.addEventListener('keydown', (e) => {
    if ($('[data-wf-view="editor"]').hidden || (picker && !picker.hidden)) return;
    const active = document.activeElement;
    const tag = active && active.tagName;
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || !!(active && active.isContentEditable);
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); save(); return; }
    if (typing) return;
    if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return; }
    if (!mod && !e.altKey && e.key.toLowerCase() === 'g') { e.preventDefault(); addGroup(); return; }
    if (!mod && !e.altKey && e.key.toLowerCase() === 'f') { e.preventDefault(); toggleFullscreen(); return; }
    if (e.key === 'Escape') { selected = null; closeQuick(); renderGroups(); renderNodes(); renderEdges(); renderInspector(); return; }
    if (!selected) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelected(); return; }
    if (mod && e.key.toLowerCase() === 'd' && selected.kind === 'node') { e.preventDefault(); duplicateNode(selected.id); }
  });

  function deleteSelected() {
    if (!selected) return;
    if (selected.kind === 'group') graph().groups = (graph().groups || []).filter((g) => g.id !== selected.id);
    else if (selected.kind === 'edge') graph().edges.splice(selected.id, 1);
    else {
      graph().nodes = graph().nodes.filter((n) => n.id !== selected.id);
      graph().edges = graph().edges.filter((e) => e.from !== selected.id && e.to !== selected.id);
    }
    selected = null;
    change();
    renderInspector();
  }
  function duplicateNode(id) {
    const node = nodeById(id);
    if (!node || node.type === 'trigger') return;
    const copy = Object.assign(clone(node), { id: uid(), x: node.x + 40, y: node.y + 60 });
    graph().nodes.push(copy);
    selected = { kind: 'node', id: copy.id };
    change();
    renderInspector();
  }

  // ------------------------------------------------------------------ inspecteur
  const opt = (list, value) => list.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(value) ? ' selected' : ''}>${esc(l)}</option>`).join('');
  const varChips = () => `<div class="wf-vars"><span class="wf-vars-label">Insérer :</span>${VAR_DEFS.map(([v, l]) => `<button type="button" class="wf-var" data-insert-var="${v}" title="Insérer « ${esc(l)} » à l'emplacement du curseur"><span aria-hidden="true">+ </span><span>${esc(l)}</span></button>`).join('')}</div>`;

  function triggerOptions(value) {
    const groups = {};
    cfg.triggers.forEach((t) => { const g = TRIGGER_META[t.key]?.group || 'Autres'; (groups[g] = groups[g] || []).push(t); });
    return Object.entries(groups).map(([g, list]) => `<optgroup label="${g}">${opt(list.map((t) => [t.key, t.label]), value)}</optgroup>`).join('');
  }

  function ruleRow(rule, index) {
    const kind = cfg.conditionFields[rule.field] || 'text';
    const ops = OP_ORDER.filter((o) => (cfg.conditionOps[kind] || []).includes(o));
    const needsValue = !['empty', 'not_empty'].includes(rule.op);
    let valueInput = '';
    if (needsValue) {
      if (rule.field === 'client') valueInput = `<select data-rule="${index}" data-rule-prop="value"><option value="">Choisir un client…</option>${opt(cfg.clients.map((c) => [c.id, c.name]), rule.value)}</select>`;
      else if (rule.field === 'weekday') valueInput = `<select data-rule="${index}" data-rule-prop="value">${opt(WEEKDAYS, rule.value)}</select>`;
      else valueInput = `<input type="${kind === 'number' ? 'number' : 'text'}" data-rule="${index}" data-rule-prop="value" value="${esc(rule.value)}" placeholder="Valeur">`;
    }
    return `
      <div class="wf-rule">
        <div class="wf-rule-head"><span>${index === 0 ? 'Si' : (current._match === 'any' ? 'Ou' : 'Et')}</span><button type="button" data-rule-remove="${index}" title="Retirer"><i data-lucide="x" class="w-3.5 h-3.5"></i></button></div>
        <select data-rule="${index}" data-rule-prop="field">${opt(Object.keys(FIELD_LABEL).map((f) => [f, FIELD_LABEL[f]]), rule.field)}</select>
        <select data-rule="${index}" data-rule-prop="op">${opt(ops.map((o) => [o, OP_LABEL[o]]), rule.op)}</select>
        ${valueInput}
      </div>`;
  }

  function calendarFields(p) {
    const fixed = p.source === 'fixed';
    const timeField = `<label class="wf-field"><span>Heure</span><input type="time" data-param="time" value="${esc(p.time || '09:00')}"></label>`;
    const past = fixed && (p.repeat || 'none') === 'none' && p.date && new Date(`${p.date}T${p.time || '09:00'}`) < new Date();
    return `
      <label class="wf-field"><span>Déclencher à</span><select data-param="source">${opt(CAL_SOURCES, p.source)}</select></label>
      ${fixed ? `
        <div class="wf-grid-2">
          <label class="wf-field"><span>Date</span><input type="date" data-param="date" value="${esc(p.date)}"></label>
          ${timeField}
        </div>
        <label class="wf-field"><span>Répétition</span><select data-param="repeat">${opt(CAL_REPEATS, p.repeat || 'none')}</select></label>
        ${past ? '<p class="wf-help wf-help--warn">Cette date est déjà passée : le workflow ne se déclenchera pas.</p>' : ''}` : `
        <div class="wf-grid-2">
          <label class="wf-field"><span>Décalage</span><input type="number" min="0" data-param="offset" data-kind="int0" value="${esc(p.offset ?? 0)}"></label>
          <label class="wf-field"><span>Unité</span><select data-param="unit">${opt([['days', 'Jours'], ['hours', 'Heures']], p.unit || 'days')}</select></label>
        </div>
        <div class="wf-field"><span>Moment</span><div class="wf-seg">
          ${[['before', 'Avant'], ['after', 'Après']].map(([v, l]) => `<button type="button" class="${(p.direction || 'before') === v ? 'is-active' : ''}" data-param="direction" data-value="${v}">${l}</button>`).join('')}
        </div></div>
        ${p.source !== 'meeting' ? timeField : ''}
        <p class="wf-help">Déclenché une fois par ${{ project_delivery: 'projet', project_start: 'projet', milestone_due: 'jalon non atteint', invoice_due: 'facture non payée', meeting: 'réunion planifiée' }[p.source]} ; si la date change, il se redéclenche pour la nouvelle date. Mettre 0 pour le jour même.</p>`}
      <p class="wf-help">Vérifié à chaque ouverture du tableau de bord (et par la commande <code>run_automations</code> si elle est planifiée sur le serveur).</p>`;
  }

  function webhookFields(p) {
    const url = webhookUrl(p);
    return `
      <div class="wf-field"><span>Adresse du webhook (POST)</span>
        ${url ? `<input type="text" readonly value="${esc(url)}">
          <button type="button" class="wf-btn wf-btn--ghost wf-btn--block" data-copy="${esc(url)}"><i data-lucide="copy" class="w-3.5 h-3.5"></i> Copier l'adresse</button>`
        : '<p class="wf-help wf-warn-text">Enregistrez le workflow pour générer son adresse secrète.</p>'}
      </div>
      <label class="wf-check"><input type="checkbox" data-param="create_client" ${p.create_client ? 'checked' : ''}> Créer le client s'il n'existe pas (d'après l'email reçu)</label>
      <p class="wf-help">Collez cette adresse dans l'outil qui doit déclencher le workflow (formulaire de site, Typeform, Calendly, Shopify, Zapier, Make…). Les données JSON ou de formulaire deviennent des variables : <code>{"customer": {"email": "…"}}</code> donne <code>{{customer_email}}</code>, à écrire tel quel dans vos messages. Un champ email est rapproché de vos clients ; un champ <code>amount</code>, <code>montant</code> ou <code>total</code> remplit « Montant ». L'en-tête <code>Idempotency-Key</code> (ou un champ <code>id</code>) évite les doublons. Gardez cette adresse secrète.</p>`;
  }

  function appActionFields(p) {
    const apps = cfg.appActions || [];
    const app = APPS[p.app] || {};
    const o = appOp(p);
    const values = p.values || {};
    const fieldHtml = (f) => {
      const label = `${esc(f.label)}${f.required ? ' *' : ''}`;
      const help = f.help ? `<p class="wf-help">${esc(f.help)}</p>` : '';
      if (f.kind === 'select') return `<label class="wf-field"><span>${label}</span><select data-param="av:${f.name}">${opt(f.options, values[f.name] || f.default)}</select>${help}</label>`;
      if (f.kind === 'id') return `<label class="wf-field"><span>${label}</span><input type="text" data-param="av:${f.name}" value="${esc(values[f.name] || '')}" placeholder="${esc(f.placeholder || '')}">${help}</label>`;
      return `<label class="wf-field"><span>${label}</span>${tokenField(`av:${f.name}`, values[f.name] || '', f.kind === 'textarea', f.placeholder || '', 4)}${help}</label>`;
    };
    return `
      <div class="wf-field"><span>Outil</span>
        <select data-app-pick>${apps.map((a) => `<option value="${esc(a.key)}"${a.key === p.app ? ' selected' : ''}>${esc(a.label)}${a.connected ? ' — connecté' : ''}</option>`).join('')}</select>
        ${app.connected === false ? `<p class="wf-help wf-warn-text">${esc(app.label)} n'est pas encore connecté : <a href="${cfg.integrationsUrl}" class="wf-link">le connecter</a>. La simulation reste possible.</p>` : ''}
      </div>
      ${(app.operations || []).length > 1 ? `<label class="wf-field"><span>Opération</span><select data-op-pick>${opt(app.operations.map((x) => [x.key, x.label]), p.operation)}</select></label>` : ''}
      ${o && o.desc ? `<p class="wf-help">${esc(o.desc)}</p>` : ''}
      ${o ? o.fields.map(fieldHtml).join('') : ''}
      ${o && o.fields.some((f) => f.kind === 'text' || f.kind === 'textarea') ? varChips() : ''}
      ${o && o.needs_email ? "<p class=\"wf-help\">Utilise le client de l'événement : il doit avoir une adresse email.</p>" : ''}`;
  }

  function nodeFields(node) {
    const p = node.params;
    if (node.type === 'trigger') {
      return `
        <label class="wf-field"><span>Événement</span><select data-node-key>${triggerOptions(node.key)}</select></label>
        <p class="wf-help">${esc(TRIGGER_META[node.key]?.desc || '')}</p>
        ${node.key === 'calendar_date' ? calendarFields(p) : ''}
        ${node.key === 'webhook_received' ? webhookFields(p) : ''}
        ${node.key === 'payment_received' ? `
          <label class="wf-field"><span>Origine du paiement</span><select data-param="origin">${opt(PAYMENT_ORIGINS, p.origin || 'any')}</select></label>
          <p class="wf-help">« En ligne » : le client paie sa facture via le lien de paiement · « Jalon » : il règle un jalon depuis son espace · « Manuel » : vous enregistrez un virement, chèque ou espèces. La variable « Origine du paiement » l'indique dans vos messages.</p>` : ''}
        <div class="wf-field"><span>Variables disponibles dans les actions</span>${varChips()}<p class="wf-help">« Montant » et « N° du document » pour les factures, devis et paiements · « Projet » / « Livrable » pour les événements de projet. Ils sont remplacés par les vraies valeurs à l'envoi.</p></div>`;
    }
    if (node.type === 'condition') {
      current._match = p.match;
      return `
        <div class="wf-field"><span>Le flux passe par « Oui » quand</span>
          <div class="wf-seg"><button type="button" class="${p.match !== 'any' ? 'is-active' : ''}" data-param="match" data-value="all">Toutes les règles</button><button type="button" class="${p.match === 'any' ? 'is-active' : ''}" data-param="match" data-value="any">Au moins une</button></div>
        </div>
        <div class="wf-rules">${(p.rules || []).map(ruleRow).join('')}</div>
        <button type="button" class="wf-btn wf-btn--ghost wf-btn--block" data-rule-add><i data-lucide="plus" class="w-3.5 h-3.5"></i> Ajouter une règle</button>
        <p class="wf-help">Reliez la sortie <strong class="wf-yes">Oui</strong> et/ou <strong class="wf-no">Non</strong> à la suite du workflow. Une sortie non reliée arrête simplement le flux.</p>`;
    }
    if (node.type === 'wait') {
      return `
        <div class="wf-grid-2">
          <label class="wf-field"><span>Durée</span><input type="number" min="1" data-param="amount" data-kind="int" value="${p.amount}"></label>
          <label class="wf-field"><span>Unité</span><select data-param="unit">${opt([['minutes', 'Minutes'], ['hours', 'Heures'], ['days', 'Jours']], p.unit)}</select></label>
        </div>
        <p class="wf-help">Le workflow reprend automatiquement après ce délai (vérifié à chaque ouverture du tableau de bord).</p>`;
    }
    const priority = `<label class="wf-field"><span>Priorité</span><select data-param="priority">${opt([['low', 'Basse'], ['medium', 'Normale'], ['high', 'Haute']], p.priority)}</select></label>`;
    switch (node.key) {
      case 'send_email':
        return `
          <div class="wf-field"><span>Destinataire</span><div class="wf-seg">
            ${[['client', 'Le client'], ['owner', 'Moi'], ['custom', 'Autre']].map(([v, l]) => `<button type="button" class="${p.recipient === v ? 'is-active' : ''}" data-param="recipient" data-value="${v}">${l}</button>`).join('')}
          </div></div>
          ${p.recipient === 'custom' ? `<label class="wf-field"><span>Adresse(s), séparées par des virgules</span><input type="text" data-param="to" value="${esc(p.to)}" placeholder="compta@exemple.fr"></label>` : ''}
          <label class="wf-field"><span>Objet</span>${tokenField('subject', p.subject, false, `Objet par défaut si vide`)}</label>
          <label class="wf-field"><span>Message</span>${tokenField('body', p.body, true, `Bonjour {{client}},…`, 6)}</label>
          ${varChips()}
          <div class="wf-field"><span>Pièces jointes</span>
            <label class="wf-check"><input type="checkbox" data-att-toggle="event" ${(p.attachments || []).some((a) => a.kind === 'event') ? 'checked' : ''}> PDF de la facture ou du devis concerné</label>
            <label class="wf-check"><input type="checkbox" data-att-toggle="created" ${(p.attachments || []).some((a) => a.kind === 'created') ? 'checked' : ''}> Documents créés plus tôt dans ce workflow</label>
            ${(p.attachments || []).map((a, i) => a.kind !== 'template' ? '' : `
              <div class="wf-attach">
                <div class="wf-attach-head"><i data-lucide="paperclip" class="w-3.5 h-3.5"></i>
                  ${templatePickButton(`att:${i}:template_id`, a.template_id, 'Choisir un document…', true)}
                  <button type="button" data-att-remove="${i}" title="Retirer"><i data-lucide="x" class="w-3.5 h-3.5"></i></button></div>
                ${docFieldsForm(a.template_id, a.field_values, `att:${i}:`, a.var_values)}
              </div>`).join('')}
            ${(p.attachments || []).filter((a) => a.kind === 'template').length < 3 ? '<button type="button" class="wf-btn wf-btn--ghost wf-btn--block" data-att-add><i data-lucide="file-plus" class="w-3.5 h-3.5"></i> Joindre un de mes documents</button>' : ''}
            <p class="wf-help">Les documents joints sont générés en PDF pour le client de l'événement, avec ses infos et les champs remplis ici. Utilisez « Document » / « Lien du document » dans le message.</p>
          </div>`;
      case 'notify': case 'create_task':
        return `
          <label class="wf-field"><span>Titre</span>${tokenField('title', p.title, false, `${node.key === 'create_task' ? 'Relancer {{client}}' : 'Paiement de {{client}}'}`)}</label>
          <label class="wf-field"><span>Message</span>${tokenField('message', p.message, true, ``, 3)}</label>
          ${varChips()}${priority}`;
      case 'create_document':
        return `
          <div class="wf-field"><span>Modèle</span>${templatePickButton('template_id', p.template_id, 'Choisir un modèle…')}</div>
          <label class="wf-field"><span>Titre du document</span>${tokenField('title', p.title, false, `Nom du modèle si vide`)}</label>
          ${docFieldsForm(p.template_id, p.field_values, 'fv:', p.var_values)}
          <label class="wf-check"><input type="checkbox" data-param="share" ${p.share ? 'checked' : ''}> Le partager dans l'espace client</label>
          ${varChips()}
          <p class="wf-help">Ensuite, « Document » et « Lien du document » sont utilisables dans les actions suivantes (email, message…).</p>`;
      case 'mark_late':
        return '<p class="wf-help">S\'applique uniquement quand l\'événement concerne une facture envoyée.</p>';
      case 'drive_upload':
        return `
          <label class="wf-check"><input type="checkbox" data-param="include_created" data-kind="bool" ${p.include_created ? 'checked' : ''}> Copier aussi les documents créés plus tôt dans ce workflow</label>
          <p class="wf-help">Le PDF de la facture ou du devis de l'événement est rangé dans le dossier « Billio » de votre Google Drive.${cfg.driveConnected ? '' : ' <strong>Google Drive n\'est pas encore connecté</strong> : page Intégrations.'}</p>`;
      case 'create_form':
        return `
          <label class="wf-field"><span>Titre du formulaire</span>${tokenField('title', p.title, false, ``)}</label>
          <label class="wf-field"><span>Introduction</span>${tokenField('intro', p.intro, true, ``, 2)}</label>
          <label class="wf-check"><input type="checkbox" data-param="notify_client" data-kind="bool" ${p.notify_client === false ? '' : 'checked'}> Envoyer le lien au client par email</label>
          <div class="wf-field"><span>Questions</span>
            <div class="wf-questions">${(p.fields || []).map((f, i) => `
              <div class="wf-question">
                <div class="wf-question-head"><span>${i + 1}</span><input type="text" data-q="${i}" data-qprop="label" value="${esc(f.label)}" placeholder="Intitulé de la question"><button type="button" data-q-remove="${i}" title="Retirer"><i data-lucide="x" class="w-3.5 h-3.5"></i></button></div>
                <div class="wf-question-row">
                  <select data-q="${i}" data-qprop="type">${opt(FORM_TYPES, f.type)}</select>
                  <label class="wf-check wf-check--sm"><input type="checkbox" data-q="${i}" data-qprop="required" ${f.required ? 'checked' : ''}> Obligatoire</label>
                </div>
                ${f.type === 'select' ? `<input type="text" data-q="${i}" data-qprop="options" value="${esc(f.options)}" placeholder="Choix séparés par des virgules">` : ''}
              </div>`).join('')}
            </div>
            <button type="button" class="wf-btn wf-btn--ghost wf-btn--block" data-q-add><i data-lucide="plus" class="w-3.5 h-3.5"></i> Ajouter une question</button>
          </div>
          <p class="wf-help">Le client répond depuis un lien public (aussi listé dans son portail). L'envoi déclenche « Formulaire client envoyé » ; {{lien_formulaire}} est disponible pour les actions suivantes.</p>`;
      case 'send_message': {
        const channels = cfg.messagingChannels || [];
        const ch = CHANNELS[p.channel] || {};
        const recipientKind = ch.recipient || (p.channel === 'whatsapp' ? 'phone' : p.channel === 'telegram' ? 'chat' : 'none');
        const modes = recipientKind === 'phone' ? [['client', 'Téléphone du client'], ['custom', 'Autre numéro']] : [['default', 'Conversation du bot'], ['custom', 'Autre chat ID']];
        return `
          <div class="wf-field"><span>Messagerie</span>
            <div class="wf-channels">${channels.map((c) => `
              <button type="button" class="wf-channel${p.channel === c.key ? ' is-active' : ''}${c.connected ? '' : ' is-off'}" data-param="channel" data-value="${c.key}">
                <strong>${esc(c.label)}</strong><small>${c.connected ? 'Connecté' : 'Non connecté'}</small>
              </button>`).join('')}
            </div>
            ${ch.connected === false ? `<p class="wf-help wf-warn-text">${esc(ch.label)} n'est pas encore connecté : <a href="${cfg.integrationsUrl}" class="wf-link">le connecter</a>. La simulation reste possible.</p>` : ''}
          </div>
          ${recipientKind !== 'none' ? `
          <div class="wf-field"><span>Destinataire</span><div class="wf-seg">${modes.map(([v, l]) => `<button type="button" class="${p.recipient_mode === v ? 'is-active' : ''}" data-param="recipient_mode" data-value="${v}">${l}</button>`).join('')}</div></div>
          ${p.recipient_mode === 'custom' ? `<label class="wf-field"><span>${recipientKind === 'phone' ? 'Numéro (format international)' : 'Chat ID'}</span><input type="text" data-param="recipient" value="${esc(p.recipient)}" placeholder="${recipientKind === 'phone' ? '+33612345678' : '-1001234567890'}"></label>` : ''}` : `<p class="wf-help">Le message est publié via le webhook ${esc(ch.label || '')} connecté.</p>`}
          <label class="wf-field"><span>Message</span>${tokenField('text', p.text, true, `Nouveau paiement de {{client}} : {{montant}}`, 5)}</label>
          ${varChips()}`;
      }
      case 'app_action': return appActionFields(p);
      case 'create_meeting':
        return `
          <label class="wf-field"><span>Titre</span>${tokenField('title', p.title, false, ``)}</label>
          <div class="wf-grid-2">
            <label class="wf-field"><span>Dans (jours)</span><input type="number" min="0" max="365" data-param="in_days" data-kind="int0" value="${p.in_days}"></label>
            <label class="wf-field"><span>Heure</span><input type="time" data-param="time" value="${esc(p.time)}"></label>
          </div>
          <label class="wf-field"><span>Durée</span><select data-param="duration">${opt([[15, '15 min'], [30, '30 min'], [45, '45 min'], [60, '1 h'], [90, '1 h 30'], [120, '2 h']], p.duration)}</select></label>
          <label class="wf-field"><span>Lieu ou lien de visio</span>${tokenField('location', p.location, false, `https://meet… ou adresse`)}</label>
          <label class="wf-field"><span>Ordre du jour</span>${tokenField('notes', p.notes, true, ``, 3)}</label>
          ${varChips()}
          <p class="wf-help">Nécessite un projet : déclencheur de projet, ou « Créer un projet » placé avant. La réunion apparaît dans le projet et le portail client.</p>`;
      case 'create_project': {
        const templates = cfg.projectTemplates || [], processes = cfg.processes || [];
        const tpl = templates.find((t) => String(t.id) === String(p.template_id));
        return `
          <label class="wf-field"><span>Modèle de projet</span><select data-param="template_id">${opt([['', 'Aucun : projet vide'], ...templates.map((t) => [String(t.id), `${t.name} (${t.milestones} jalon${t.milestones > 1 ? 's' : ''})`])], String(p.template_id || ''))}</select></label>
          ${templates.length ? '' : '<p class="wf-help">Aucun modèle pour l\'instant : depuis un projet, « Enregistrer comme modèle ».</p>'}
          <label class="wf-field"><span>Client du projet</span><select data-param="client">${opt([['event', "Le client de l'événement"], ...cfg.clients.map((c) => [String(c.id), c.name])], String(p.client || 'event'))}</select></label>
          <label class="wf-field"><span>Processus (étapes)</span><select data-param="process_id">${opt([['', tpl && tpl.process ? `Celui du modèle (${tpl.process})` : 'Processus par défaut'], ...processes.map((x) => [String(x.id), x.name])], String(p.process_id || ''))}</select></label>
          <label class="wf-field"><span>Nom du projet</span>${tokenField('value', p.value, false, tpl ? `${tpl.name} — {{client}}` : 'Ex. Projet {{client}}')}</label>
          ${varChips()}
          <p class="wf-help">Le projet démarre aujourd'hui : jalons, tâches et livrables du modèle sont datés à partir de cette date. Les actions suivantes (jalon, réunion, formulaire…) visent ce projet.</p>`;
      }
      default: {
        const labels = { create_project: 'Nom du projet', create_phase: 'Nom de la phase', create_milestone: 'Titre du jalon', create_deliverable: 'Titre du livrable' };
        return `
          <label class="wf-field"><span>${labels[node.key] || 'Valeur'}</span>${tokenField('value', p.value, false, `Ex. Projet {{client}}`)}</label>
          ${varChips()}
          ${['create_milestone', 'create_deliverable'].includes(node.key) ? '<p class="wf-help">Nécessite un projet : déclencheur de projet, ou action « Créer un projet » placée avant.</p>' : ''}`;
      }
    }
  }

  function runsHtml(runs) {
    if (!runs || !runs.length) return '<p class="wf-empty">Aucune exécution pour l\'instant.</p>';
    return runs.map((run) => `
      <details class="wf-run">
        <summary>
          <span class="wf-run-dot ${run.waiting ? 'is-waiting' : run.success ? 'is-ok' : 'is-error'}"></span>
          <span class="wf-run-date">${esc(run.ran_at)}</span>
          <span class="wf-run-label">${esc(run.label || run.target)}</span>
        </summary>
        <ol class="wf-run-log">${(run.log || []).map((entry) => logLine(entry, run.graph || (current && current.graph))).join('') || '<li>Exécution antérieure aux workflows (pas de détail).</li>'}</ol>
      </details>`).join('');
  }
  function logLine(entry, g) {
    const node = g && g.nodes.find((n) => n.id === entry.node);
    const name = node ? nodeTitle(node) : entry.node;
    const badge = { ok: '✓', true: 'Oui', false: 'Non', error: 'Erreur', waiting: 'En attente' }[entry.status] || entry.status;
    return `<li class="wf-log wf-log--${entry.status}"><span class="wf-log-badge">${badge}</span><span><strong>${esc(name)}</strong>${entry.detail ? `<small>${esc(entry.detail)}</small>` : ''}</span></li>`;
  }

  // ------------------------------------------------------------------ choix du modèle de document
  // Vignette de la première page, mise à l'échelle de `width` px (la vignette serveur fait 168 px).
  function templateThumb(t, width) {
    const th = t.thumb || {};
    if (!th.html) return `<span class="wf-tpl-thumb" style="width:${width}px;height:${Math.round(width * 1.414)}px"></span>`;
    const ratio = width / 168;
    return `<span class="wf-tpl-thumb" translate="no" style="width:${width}px;height:${Math.round(th.height * ratio)}px">`
      + `<span class="wf-tpl-thumb-scale" style="transform:scale(${(parseFloat(th.scale) * ratio).toFixed(4)})">${th.html}</span></span>`;
  }
  function templatePickButton(param, id, placeholder, compact = false) {
    const t = cfg.documentTemplates.find((x) => String(x.id) === String(id));
    if (!t) {
      return `<button type="button" class="wf-tpl-pick is-empty${compact ? ' is-compact' : ''}" data-tpl-pick="${esc(param)}">
        <i data-lucide="layout-template" class="w-4 h-4"></i><span>${esc(placeholder)}</span></button>`;
    }
    return `<button type="button" class="wf-tpl-pick${compact ? ' is-compact' : ''}" data-tpl-pick="${esc(param)}" title="Changer de modèle">
      ${templateThumb(t, compact ? 30 : 44)}
      <span class="wf-tpl-pick-text"><strong>${esc(t.name)}</strong><small>${esc(t.category)} · ${t.pages} page${t.pages > 1 ? 's' : ''}</small></span>
      <span class="wf-tpl-pick-change">Changer</span></button>`;
  }

  let picker = null;
  const pickerState = { nodeId: null, param: '', query: '', filter: 'all' };
  function ensurePicker() {
    if (picker) return picker;
    picker = document.createElement('div');
    picker.className = 'wf-tpl-modal';
    picker.hidden = true;
    picker.innerHTML = `
      <div class="wf-tpl-backdrop" data-tpl-close></div>
      <div class="wf-tpl-dialog" role="dialog" aria-modal="true" aria-label="Choisir un modèle de document">
        <div class="wf-tpl-head">
          <div><h3>Choisir un modèle de document</h3><p>Le document est généré pour le client de l'événement, avec ses informations.</p></div>
          <button type="button" class="wf-tpl-x" data-tpl-close title="Fermer"><i data-lucide="x" class="w-4 h-4"></i></button>
        </div>
        <div class="wf-tpl-tools">
          <label class="wf-tpl-search"><i data-lucide="search" class="w-4 h-4"></i><input type="search" data-tpl-search placeholder="Rechercher un modèle…"></label>
          <div class="wf-tpl-filters" data-tpl-filters></div>
        </div>
        <div class="wf-tpl-grid" data-tpl-grid></div>
        <div class="wf-tpl-foot"><a href="/dashboard/documents/" class="wf-tpl-link" target="_blank" rel="noopener"><i data-lucide="external-link" class="w-3.5 h-3.5"></i> Gérer mes modèles</a></div>
      </div>`;
    document.body.appendChild(picker);
    picker.addEventListener('click', (e) => {
      if (e.target.closest('[data-tpl-close]')) { closePicker(); return; }
      const f = e.target.closest('[data-tpl-filter]');
      if (f) { pickerState.filter = f.dataset.tplFilter; renderPicker(); return; }
      const card = e.target.closest('[data-tpl-id]');
      if (card) choosePicker(card.dataset.tplId);
    });
    picker.addEventListener('input', (e) => {
      if (e.target.matches('[data-tpl-search]')) { pickerState.query = e.target.value; renderPicker(); }
    });
    // Le clavier de la fenêtre ne doit pas atteindre le board (Suppr, Échap…).
    picker.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); closePicker(); }
      if (e.key === 'Enter' && e.target.matches('[data-tpl-search]')) {
        const first = picker.querySelector('[data-tpl-id]');
        if (first) { e.preventDefault(); choosePicker(first.dataset.tplId); }
      }
    });
    return picker;
  }
  function pickParamValue(node, param) {
    if (param.startsWith('att:')) { const [, i] = param.split(':'); return ((node.params.attachments || [])[+i] || {}).template_id || ''; }
    return node.params[param] || '';
  }
  function renderPicker() {
    const node = nodeById(pickerState.nodeId);
    const currentId = node ? String(pickParamValue(node, pickerState.param)) : '';
    const cats = [...new Set(cfg.documentTemplates.map((t) => t.category).filter(Boolean))];
    const filters = [['all', 'Tous'], ['mine', 'Mes modèles'], ['system', 'Modèles Billio'], ...cats.map((c) => [`cat:${c}`, c])]
      .filter(([key]) => key !== 'mine' || cfg.documentTemplates.some((t) => !t.system));
    picker.querySelector('[data-tpl-filters]').innerHTML = filters.map(([key, label]) =>
      `<button type="button" class="wf-tpl-chip${pickerState.filter === key ? ' is-active' : ''}" data-tpl-filter="${esc(key)}">${esc(label)}</button>`).join('');
    const q = pickerState.query.trim().toLowerCase();
    const f = pickerState.filter;
    const list = cfg.documentTemplates.filter((t) => {
      if (f === 'mine' && t.system) return false;
      if (f === 'system' && !t.system) return false;
      if (f.startsWith('cat:') && t.category !== f.slice(4)) return false;
      return !q || `${t.name} ${t.description || ''} ${t.category || ''}`.toLowerCase().includes(q);
    });
    picker.querySelector('[data-tpl-grid]').innerHTML = list.length ? list.map((t) => {
      const chosen = String(t.id) === currentId;
      return `
      <button type="button" class="wf-tpl-card${chosen ? ' is-active' : ''}" data-tpl-id="${t.id}">
        <span class="wf-tpl-card-thumb">${templateThumb(t, 150)}
          ${chosen ? '<span class="wf-tpl-badge"><i data-lucide="check" class="w-3 h-3"></i> Choisi</span>' : ''}
          <span class="wf-tpl-cta">Utiliser ce modèle</span></span>
        <span class="wf-tpl-card-body">
          <strong>${esc(t.name)}</strong>
          <small>${t.system ? 'Billio' : 'Mon modèle'} · ${esc(t.category)} · ${t.pages} page${t.pages > 1 ? 's' : ''}</small>
          ${t.fields.length ? `<small class="wf-tpl-fields"><i data-lucide="text-cursor-input" class="w-3 h-3"></i> ${t.fields.length} champ${t.fields.length > 1 ? 's' : ''} à remplir</small>` : ''}
        </span>
      </button>`;
    }).join('') : '<p class="wf-tpl-empty">Aucun modèle ne correspond à votre recherche.</p>';
    icons();
  }
  function openTemplatePicker(node, param) {
    ensurePicker();
    Object.assign(pickerState, { nodeId: node.id, param, query: '', filter: 'all' });
    picker.querySelector('[data-tpl-search]').value = '';
    renderPicker();
    picker.hidden = false;
    document.body.classList.add('wf-tpl-open');
    requestAnimationFrame(() => {
      const active = picker.querySelector('.wf-tpl-card.is-active');
      if (active) active.scrollIntoView({ block: 'nearest' });
      picker.querySelector('[data-tpl-search]').focus();
    });
  }
  function closePicker() {
    if (!picker) return;
    picker.hidden = true;
    document.body.classList.remove('wf-tpl-open');
  }
  function choosePicker(id) {
    const node = nodeById(pickerState.nodeId);
    closePicker();
    if (!node) return;
    if (String(pickParamValue(node, pickerState.param)) !== String(id)) {
      setParam(node, pickerState.param, String(id));
      if (pickerState.param === 'template_id') { node.params.field_values = {}; node.params.var_values = {}; }
      change();
    }
    renderInspector();
  }

  function renderInspector() {
    if (!current) return;
    let html;
    if (selected && selected.kind === 'node' && nodeById(selected.id)) {
      const node = nodeById(selected.id);
      const warnings = nodeWarnings(node, reachableIds());
      html = `
        <div class="wf-insp-head wf-insp-head--${node.type}">
          <span class="wf-node-icon"><i data-lucide="${nodeIcon(node)}" class="w-4 h-4"></i></span>
          <div class="min-w-0 flex-1"><p class="wf-insp-type">${TYPE_LABEL[node.type]}</p>
            <input class="wf-insp-title" data-node-label value="${esc(node.label)}" placeholder="${esc(nodeTitle(Object.assign({}, node, { label: '' })))}"></div>
        </div>
        ${warnings.length ? `<div class="wf-warnings">${warnings.map((w) => `<p><i data-lucide="triangle-alert" class="w-3.5 h-3.5"></i>${esc(w)}</p>`).join('')}</div>` : ''}
        <div class="wf-insp-body">${nodeFields(node)}</div>
        <div class="wf-insp-foot">
          ${node.type !== 'trigger' ? '<button type="button" class="wf-btn wf-btn--ghost" data-node-duplicate><i data-lucide="copy" class="w-3.5 h-3.5"></i> Dupliquer</button>' : ''}
          <button type="button" class="wf-btn wf-btn--danger" data-node-delete><i data-lucide="trash-2" class="w-3.5 h-3.5"></i> Supprimer</button>
        </div>`;
    } else if (selected && selected.kind === 'group' && groupById(selected.id)) {
      const g = groupById(selected.id);
      const members = nodesInGroup(g);
      html = `
        <div class="wf-insp-head"><span class="wf-node-icon"><i data-lucide="group" class="w-4 h-4"></i></span>
          <div class="min-w-0 flex-1"><p class="wf-insp-type">Groupe</p><input class="wf-insp-title" data-group-label value="${esc(g.label)}" placeholder="Nom du groupe"></div></div>
        <div class="wf-insp-body">
          <div class="wf-field"><span>Couleur</span><div class="wf-swatches">${GROUP_COLORS.map(([k, hex]) => `<button type="button" class="wf-swatch${g.color === k ? ' is-active' : ''}" data-group-color="${k}" style="--c:${hex}" aria-label="${k}"></button>`).join('')}</div></div>
          <div class="wf-field"><span>Blocs dans le groupe (${members.length})</span>${members.length ? `<ul class="wf-group-list">${members.map((n) => `<li><i data-lucide="${nodeIcon(n)}" class="w-3.5 h-3.5"></i>${esc(nodeTitle(n))}</li>`).join('')}</ul>` : '<p class="wf-empty">Placez des blocs dans le cadre pour les regrouper.</p>'}</div>
          <p class="wf-help">Faites glisser l'en-tête pour déplacer le groupe avec tous ses blocs, le coin pour le redimensionner. Le groupe est visuel : il ne change pas l'exécution.</p>
        </div>
        <div class="wf-insp-foot"><button type="button" class="wf-btn wf-btn--danger" data-group-delete><i data-lucide="trash-2" class="w-3.5 h-3.5"></i> Retirer le groupe</button></div>`;
    } else if (selected && selected.kind === 'edge' && graph().edges[selected.id]) {
      const edge = graph().edges[selected.id];
      html = `
        <div class="wf-insp-head"><span class="wf-node-icon"><i data-lucide="spline" class="w-4 h-4"></i></span><div><p class="wf-insp-type">Lien</p><p class="wf-insp-name">${esc(nodeTitle(nodeById(edge.from)))} → ${esc(nodeTitle(nodeById(edge.to)))}</p></div></div>
        <div class="wf-insp-body">${edge.port !== 'out' ? `<p class="wf-help">Branche <strong class="${edge.port === 'true' ? 'wf-yes' : 'wf-no'}">${edge.port === 'true' ? 'Oui' : 'Non'}</strong> de la condition.</p>` : ''}
        <button type="button" class="wf-btn wf-btn--danger wf-btn--block" data-edge-remove><i data-lucide="unlink" class="w-3.5 h-3.5"></i> Supprimer le lien</button></div>`;
    } else {
      const saved = workflows.find((w) => w.id === current.id);
      const nodes = graph().nodes;
      html = `
        <div class="wf-insp-head"><span class="wf-node-icon"><i data-lucide="workflow" class="w-4 h-4"></i></span><div><p class="wf-insp-type">Workflow</p><p class="wf-insp-name">${nodes.length} bloc${nodes.length > 1 ? 's' : ''} · ${graph().edges.length} lien${graph().edges.length > 1 ? 's' : ''}</p></div></div>
        <div class="wf-insp-body">
          <label class="wf-field"><span>Description</span><textarea rows="3" data-wf-description placeholder="À quoi sert ce workflow ?">${esc(current.description)}</textarea></label>
          ${testLog ? `<div class="wf-field"><span>Résultat du test</span><ol class="wf-run-log">${current._testEntries.map((entry) => logLine(entry, graph())).join('')}</ol>
            <button type="button" class="wf-btn wf-btn--ghost wf-btn--block" data-test-clear>Effacer le résultat</button></div>` : ''}
          <div class="wf-field"><span>Historique d'exécution</span>${saved ? runsHtml(saved.runs.map((r) => Object.assign({ graph: saved.graph }, r))) : '<p class="wf-empty">Enregistrez le workflow pour suivre ses exécutions.</p>'}</div>
          <div class="wf-field"><span>Raccourcis</span><ul class="wf-shortcuts">
            <li>Tirer depuis un port <span class="wf-port-mini"></span> vers un bloc pour relier</li>
            <li>Lâcher un lien dans le vide pour créer le bloc suivant</li>
            <li><kbd>Suppr</kbd> supprimer · <kbd>Ctrl D</kbd> dupliquer</li>
            <li><kbd>G</kbd> grouper · <kbd>F</kbd> plein écran</li>
            <li><kbd>Ctrl Z</kbd> annuler · <kbd>Ctrl S</kbd> enregistrer</li>
          </ul></div>
        </div>`;
    }
    inspector.innerHTML = html;
    icons();
  }

  function updateNodeCard() {
    renderNodes();
    renderEdges();
  }

  inspector.addEventListener('focusin', (e) => { if (e.target.matches('[data-text]')) lastFocusedText = e.target; });
  document.addEventListener('selectionchange', () => {
    const sel = window.getSelection();
    if (sel.rangeCount && lastFocusedText && lastFocusedText.matches('[data-tokens]') && lastFocusedText.contains(sel.anchorNode)) {
      lastTokenRange = sel.getRangeAt(0).cloneRange();
    }
  });
  // Champs à pastilles : collage en texte brut, Entrée interdite sur une ligne.
  inspector.addEventListener('paste', (e) => {
    const field = e.target.closest && e.target.closest('[data-tokens]');
    if (!field) return;
    e.preventDefault();
    document.execCommand('insertText', false, (e.clipboardData || window.clipboardData).getData('text/plain'));
  });
  inspector.addEventListener('keydown', (e) => {
    const field = e.target.closest && e.target.closest('[data-tokens]');
    if (field && e.key === 'Enter' && field.dataset.multiline === undefined) e.preventDefault();
  });
  inspector.addEventListener('input', (e) => {
    const t = e.target;
    const node = selected && selected.kind === 'node' ? nodeById(selected.id) : null;
    if (t.matches && t.matches('[data-tokens]') && node) {
      setParam(node, t.dataset.param, t.dataset.multiline !== undefined ? serializeTokens(t) : serializeTokens(t).replace(/\n/g, ' '));
      updateNodeCard(); markDirty();
      return;
    }
    if (t.matches('[data-group-label]')) { const g = groupById(selected.id); if (g) { g.label = t.value.slice(0, 80); renderGroups(); markDirty(); } return; }
    if (t.matches('[data-node-label]') && node) { node.label = t.value.slice(0, 80); updateNodeCard(); markDirty(); return; }
    if (t.matches('[data-wf-description]')) { current.description = t.value; markDirty(); return; }
    if (node && t.dataset.q !== undefined && t.type !== 'checkbox' && t.tagName !== 'SELECT') {
      node.params.fields[+t.dataset.q][t.dataset.qprop] = t.value;
      updateNodeCard(); markDirty();
      return;
    }
    if (node && t.dataset.param && t.tagName !== 'SELECT' && t.type !== 'checkbox') {
      const kind = t.dataset.kind;
      setParam(node, t.dataset.param, kind === 'int' ? Math.max(1, parseInt(t.value, 10) || 1) : (kind === 'int0' ? Math.max(0, parseInt(t.value, 10) || 0) : t.value));
      updateNodeCard(); markDirty();
      return;
    }
    if (node && t.dataset.rule !== undefined && t.tagName === 'INPUT') {
      node.params.rules[+t.dataset.rule].value = t.value;
      updateNodeCard(); markDirty();
    }
  });
  inspector.addEventListener('change', (e) => {
    const t = e.target;
    const node = selected && selected.kind === 'node' ? nodeById(selected.id) : null;
    if (!node) { if (t.matches('[data-wf-description]')) change({ rerender: false }); return; }
    if (t.matches('[data-app-pick]')) { node.params = appActionDefaults(t.value); change(); renderInspector(); return; }
    if (t.matches('[data-op-pick]')) {
      const o = ((APPS[node.params.app] || {}).operations || []).find((x) => x.key === t.value);
      node.params.operation = t.value; node.params.values = opDefaults(o);
      change(); renderInspector(); return;
    }
    if (t.matches('[data-node-key]')) { node.key = t.value; if (node.type === 'trigger') node.params = defaultParams('trigger', t.value); change(); renderInspector(); return; }
    if (t.dataset.q !== undefined && (t.type === 'checkbox' || t.tagName === 'SELECT')) {
      node.params.fields[+t.dataset.q][t.dataset.qprop] = t.type === 'checkbox' ? t.checked : t.value;
      change(); renderInspector();
      return;
    }
    if (t.dataset.attToggle) {
      const list = (node.params.attachments || []).filter((a) => a.kind !== t.dataset.attToggle);
      if (t.checked) list.unshift({ kind: t.dataset.attToggle });
      node.params.attachments = list;
      change(); renderInspector();
      return;
    }
    if (t.dataset.param && t.type === 'checkbox') { setParam(node, t.dataset.param, t.checked); change(); return; }
    if (t.dataset.param && t.tagName === 'SELECT') {
      setParam(node, t.dataset.param, t.value);
      if (t.dataset.param === 'template_id') { node.params.field_values = {}; node.params.var_values = {}; }
      change(); renderInspector();
      return;
    }
    if (t.dataset.param && (t.type === 'date' || t.type === 'time')) {
      setParam(node, t.dataset.param, t.value); change({ rerender: false }); updateNodeCard();
      if (node.type === 'trigger') renderInspector();
      return;
    }
    if (t.dataset.rule !== undefined && t.tagName === 'SELECT') {
      const rule = node.params.rules[+t.dataset.rule];
      rule[t.dataset.ruleProp] = t.value;
      if (t.dataset.ruleProp === 'field') {
        const kind = cfg.conditionFields[t.value];
        const ops = cfg.conditionOps[kind] || [];
        if (!ops.includes(rule.op)) rule.op = kind === 'number' ? 'gt' : 'eq';
        rule.value = t.value === 'weekday' ? '1' : '';
      }
      change(); renderInspector();
      return;
    }
    change({ rerender: false });
  });
  inspector.addEventListener('mousedown', (e) => { if (e.target.closest('[data-insert-var]')) e.preventDefault(); });
  inspector.addEventListener('click', (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    const node = selected && selected.kind === 'node' ? nodeById(selected.id) : null;
    if (node && t.dataset.tplPick) { openTemplatePicker(node, t.dataset.tplPick); return; }
    if (t.dataset.copy) {
      navigator.clipboard.writeText(t.dataset.copy).then(() => toast('Adresse copiée'), () => toast("Copie impossible : sélectionnez l'adresse", true));
      return;
    }
    if (node && (t.dataset.varCustom || t.dataset.varReset)) {
      const path = t.dataset.varCustom || t.dataset.varReset;
      if (t.dataset.varCustom) setParam(node, path, '');
      else {
        // Supprime la clé : la variable redevient automatique.
        const [head, ...rest] = path.split(':');
        const holder = head === 'att' ? (node.params.attachments || [])[+rest[0]] : node.params;
        const key = head === 'att' ? rest.slice(2).join(':') : rest.join(':');
        if (holder && holder.var_values) delete holder.var_values[key];
      }
      change(); renderInspector();
      if (t.dataset.varCustom) {
        const field = inspector.querySelector(`[data-param="${CSS.escape(path)}"]`);
        if (field) field.focus();
      }
      return;
    }
    if (t.dataset.insertVar) {
      const field = lastFocusedText && inspector.contains(lastFocusedText) ? lastFocusedText : inspector.querySelector('[data-text]');
      if (!field || !node) return;
      if (field.matches('[data-tokens]')) {
        const tpl = document.createElement('template');
        tpl.innerHTML = tokenChip(t.dataset.insertVar);
        const chip = tpl.content.firstChild;
        const space = document.createTextNode('\u00a0');
        const range = lastTokenRange && field.contains(lastTokenRange.startContainer) ? lastTokenRange : null;
        if (range) { range.deleteContents(); range.insertNode(space); range.insertNode(chip); } else { field.append(chip, space); }
        const after = document.createRange();
        after.setStartAfter(space); after.collapse(true);
        field.focus();
        const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(after);
        lastTokenRange = after.cloneRange();
        setParam(node, field.dataset.param, serializeTokens(field));
        updateNodeCard(); change({ rerender: false });
        return;
      }
      const token = `{{${t.dataset.insertVar}}}`;
      const start = field.selectionStart ?? field.value.length; const end = field.selectionEnd ?? field.value.length;
      field.value = field.value.slice(0, start) + token + field.value.slice(end);
      field.focus();
      field.setSelectionRange(start + token.length, start + token.length);
      node.params[field.dataset.param] = field.value;
      updateNodeCard(); change({ rerender: false });
      return;
    }
    if (node && t.dataset.param && t.dataset.value !== undefined) { node.params[t.dataset.param] = t.dataset.value; change(); renderInspector(); return; }
    if (node && t.hasAttribute('data-att-add')) { node.params.attachments = [...(node.params.attachments || []), { kind: 'template', template_id: '', field_values: {} }]; change(); renderInspector(); return; }
    if (node && t.dataset.attRemove !== undefined) { node.params.attachments.splice(+t.dataset.attRemove, 1); change(); renderInspector(); return; }
    if (node && t.hasAttribute('data-q-add')) { node.params.fields = [...(node.params.fields || []), { label: '', type: 'text', required: false, options: '' }]; change(); renderInspector(); return; }
    if (node && t.dataset.qRemove !== undefined) { node.params.fields.splice(+t.dataset.qRemove, 1); change(); renderInspector(); return; }
    if (t.hasAttribute('data-group-delete')) { deleteSelected(); return; }
    if (t.dataset.groupColor) { const g = groupById(selected.id); if (g) { g.color = t.dataset.groupColor; change(); renderInspector(); } return; }
    if (node && t.hasAttribute('data-rule-add')) { node.params.rules.push({ field: 'client_name', op: 'contains', value: '' }); change(); renderInspector(); return; }
    if (node && t.dataset.ruleRemove !== undefined) { node.params.rules.splice(+t.dataset.ruleRemove, 1); change(); renderInspector(); return; }
    if (t.hasAttribute('data-node-delete') || t.hasAttribute('data-edge-remove')) { deleteSelected(); return; }
    if (t.hasAttribute('data-node-duplicate') && node) { duplicateNode(node.id); return; }
    if (t.hasAttribute('data-test-clear')) { testLog = null; renderBoard(); renderInspector(); }
  });

  let dirtyTimer = null;
  function markDirty() {
    dirty = true;
    updateDirty();
    clearTimeout(dirtyTimer);
    dirtyTimer = setTimeout(() => snapshot(), 500);
    scheduleLive();
  }

  // ------------------------------------------------------------------ test (simulation)
  const testPop = $('[data-wf-test-pop]');
  $('[data-wf-test-client]').innerHTML = '<option value="">—</option>' + opt(cfg.clients.map((c) => [c.id, c.name]), '');
  $('[data-wf-test]').addEventListener('click', (e) => {
    testPop.hidden = !testPop.hidden;
    if (!testPop.hidden) {
      const rect = e.currentTarget.getBoundingClientRect();
      testPop.style.top = `${rect.bottom + 8}px`;
      testPop.style.left = `${Math.max(12, rect.right - testPop.offsetWidth)}px`;
      icons();
    }
  });
  $('[data-wf-test-cancel]').addEventListener('click', () => { testPop.hidden = true; });
  $('[data-wf-test-run]').addEventListener('click', () => { testPop.hidden = true; runSimulation({ animate: true }); });
  $('[data-wf-test-live]').addEventListener('change', (e) => {
    liveMode = e.target.checked;
    $('[data-wf-test]').classList.toggle('is-live', liveMode);
    if (liveMode) { testPop.hidden = true; runSimulation({ animate: true }); return; }
    clearTimeout(liveTimer); simSeq += 1;
    testLog = null; renderBoard(); renderInspector();
  });
  document.addEventListener('pointerdown', (e) => {
    if (!testPop.hidden && !testPop.contains(e.target) && !e.target.closest('[data-wf-test]')) testPop.hidden = true;
  });

  // ------------------------------------------------------------------ simulation animée / en direct
  let liveMode = false;
  let liveTimer = null;
  let simTimer = null;
  let simSeq = 0;
  const simAlerts = $('[data-wf-sim-alerts]');
  const SIM_ICON = { ok: 'circle-check', true: 'check', false: 'x', error: 'circle-alert', waiting: 'hourglass' };
  const SIM_BADGE = { ok: 'Exécuté', true: 'Oui', false: 'Non', error: 'Erreur', waiting: 'En pause' };

  function testPayload() {
    return new URLSearchParams({
      graph: JSON.stringify(graph()),
      amount: $('[data-wf-test-amount]').value,
      client_id: $('[data-wf-test-client]').value,
      projet: $('[data-wf-test-projet]').value,
      produit: $('[data-wf-test-produit]').value,
      formulaire: $('[data-wf-test-formulaire]').value,
    });
  }
  function scheduleLive() {
    if (!liveMode || !current) return;
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => runSimulation({ animate: false }), 650);
  }
  function pushAlert(entry, title) {
    const node = entry.node && nodeById(entry.node);
    const el = document.createElement('div');
    el.className = `wf-sim-alert wf-sim-alert--${entry.status}`;
    el.innerHTML = `<i data-lucide="${SIM_ICON[entry.status] || 'dot'}" class="w-4 h-4"></i>
      <div><p><strong>${esc(title || (node ? nodeTitle(node) : 'Workflow'))}</strong><span>${SIM_BADGE[entry.status] || ''}</span></p>${entry.detail ? `<small>${esc(entry.detail)}</small>` : ''}</div>`;
    simAlerts.prepend(el);
    while (simAlerts.children.length > 4) simAlerts.lastChild.remove();
    icons();
    setTimeout(() => { el.classList.add('is-leaving'); setTimeout(() => el.remove(), 350); }, 4500);
  }
  async function runSimulation({ animate }) {
    if (!current || !triggerNode()) { if (animate) toast('Ajoutez un déclencheur pour simuler.', true); return; }
    const seq = ++simSeq;
    clearTimeout(simTimer);
    let res; let data = {};
    try {
      res = await fetch(cfg.testUrl, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: testPayload() });
      data = await res.json().catch(() => ({}));
    } catch (err) { res = { ok: false }; data = { message: 'Serveur injoignable.' }; }
    if (seq !== simSeq || !current) return;
    if (!res.ok) {
      if (animate) toast(data.message || 'Simulation impossible.', true);
      else pushAlert({ status: 'error', detail: data.message || 'Workflow incomplet.' }, 'Workflow incomplet');
      return;
    }
    current._testEntries = data.log;
    if (!animate) {
      const before = JSON.stringify(testLog || {});
      testLog = Object.fromEntries(data.log.map((entry) => [entry.node, entry]));
      renderNodes(); renderEdges();
      if (!selected) renderInspector();
      if (before !== JSON.stringify(testLog)) data.log.filter((x) => x.status === 'error').forEach((x) => pushAlert(x));
      return;
    }
    testLog = {};
    simAlerts.innerHTML = '';
    selected = null;
    renderBoard(); renderInspector();
    board.classList.add('is-simulating');
    let i = 0;
    const step = () => {
      if (seq !== simSeq || !current) { board.classList.remove('is-simulating'); return; }
      if (i >= data.log.length) {
        board.classList.remove('is-simulating');
        renderInspector();
        const actions = data.log.filter((x) => (nodeById(x.node) || {}).type === 'action').length;
        const errors = data.log.filter((x) => x.status === 'error').length;
        toast(errors ? `Simulation : ${errors} erreur${errors > 1 ? 's' : ''} détectée${errors > 1 ? 's' : ''}.` : `Simulation terminée : ${actions} action${actions > 1 ? 's' : ''} atteinte${actions > 1 ? 's' : ''}.`, !!errors);
        return;
      }
      const entry = data.log[i++];
      testLog[entry.node] = entry;
      renderNodes(); renderEdges();
      const el = nodesHost.querySelector(`[data-node="${entry.node}"]`);
      if (el) el.classList.add('is-pulse');
      pushAlert(entry);
      simTimer = setTimeout(step, entry.status === 'waiting' ? 900 : 650);
    };
    step();
  }

  // ------------------------------------------------------------------ groupes
  const groupsHost = $('[data-wf-groups]');
  const GROUP_HEX = Object.fromEntries(GROUP_COLORS);
  const groupById = (id) => (graph().groups || []).find((g) => g.id === id);
  const nodeHeight = (n) => (nodesHost.querySelector(`[data-node="${n.id}"]`) || {}).offsetHeight || 110;
  function nodesInGroup(g) {
    return graph().nodes.filter((n) => {
      const cx = n.x + NODE_W / 2; const cy = n.y + 30;
      return cx >= g.x && cx <= g.x + g.w && cy >= g.y && cy <= g.y + g.h;
    });
  }
  function renderGroups() {
    if (!current) return;
    graph().groups = graph().groups || [];
    groupsHost.innerHTML = graph().groups.map((g) => `
      <div class="wf-group${selected && selected.kind === 'group' && selected.id === g.id ? ' is-selected' : ''}" data-group="${g.id}"
           style="left:${g.x}px;top:${g.y}px;width:${g.w}px;height:${g.h}px;--group:${GROUP_HEX[g.color] || GROUP_HEX.violet}">
        <div class="wf-group-head" data-group-drag title="Glisser pour déplacer le groupe"><i data-lucide="group" class="w-3.5 h-3.5"></i><span>${esc(g.label)}</span><em>${nodesInGroup(g).length}</em></div>
        <span class="wf-group-resize" data-group-resize title="Redimensionner"></span>
      </div>`).join('');
  }
  function addGroup() {
    if (!current) return;
    graph().groups = graph().groups || [];
    const pad = 30;
    const node = selected && selected.kind === 'node' ? nodeById(selected.id) : null;
    let box;
    if (node) {
      box = { x: node.x - pad, y: node.y - pad - 20, w: NODE_W + pad * 2, h: nodeHeight(node) + pad * 2 + 20 };
    } else {
      const rect = board.getBoundingClientRect();
      const cx = (rect.width / 2 - view.x) / view.zoom; const cy = (rect.height / 2 - view.y) / view.zoom;
      box = { x: cx - 200, y: cy - 130, w: 400, h: 260 };
    }
    const g = {
      id: `g${Math.random().toString(36).slice(2, 9)}`, label: 'Nouveau groupe',
      color: GROUP_COLORS[graph().groups.length % GROUP_COLORS.length][0],
      x: Math.round(box.x), y: Math.round(box.y), w: Math.round(box.w), h: Math.round(box.h),
    };
    graph().groups.push(g);
    selected = { kind: 'group', id: g.id };
    change();
    renderInspector();
  }
  function startGroupDrag(e, groupId, mode) {
    const g = groupById(groupId);
    if (!g) return;
    const start = boardPoint(e);
    const origin = { x: g.x, y: g.y, w: g.w, h: g.h };
    const members = mode === 'move' ? nodesInGroup(g).map((n) => ({ n, x: n.x, y: n.y })) : [];
    let moved = false;
    if (!selected || selected.kind !== 'group' || selected.id !== groupId) {
      selected = { kind: 'group', id: groupId };
      renderGroups(); renderNodes(); renderEdges(); renderInspector();
    }
    const el = groupsHost.querySelector(`[data-group="${groupId}"]`);
    function onMove(ev) {
      const p = boardPoint(ev);
      const dx = p.x - start.x; const dy = p.y - start.y;
      if (!moved && Math.hypot(dx, dy) * view.zoom < 3) return;
      moved = true;
      if (mode === 'move') {
        g.x = snap20(origin.x + dx); g.y = snap20(origin.y + dy);
        members.forEach((m) => {
          m.n.x = m.x + (g.x - origin.x); m.n.y = m.y + (g.y - origin.y);
          const ne = nodesHost.querySelector(`[data-node="${m.n.id}"]`);
          if (ne) { ne.style.left = `${m.n.x}px`; ne.style.top = `${m.n.y}px`; }
        });
        renderEdges();
      } else {
        g.w = Math.max(160, snap20(origin.w + dx)); g.h = Math.max(120, snap20(origin.h + dy));
      }
      Object.assign(el.style, { left: `${g.x}px`, top: `${g.y}px`, width: `${g.w}px`, height: `${g.h}px` });
      el.classList.add('is-dragging');
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      if (moved) { change(); renderInspector(); }
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }
  $('[data-wf-group-add]').addEventListener('click', () => addGroup());

  // ------------------------------------------------------------------ plein écran
  const editorEl = $('[data-wf-view="editor"]');
  function toggleFullscreen(force) {
    const on = typeof force === 'boolean' ? force : !editorEl.classList.contains('is-fullscreen');
    editorEl.classList.toggle('is-fullscreen', on);
    document.documentElement.classList.toggle('wf-noscroll', on);
    // Plein écran du navigateur sur toute la page : les popovers restent visibles.
    if (on && document.documentElement.requestFullscreen && !document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
    if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
    const btn = $('[data-wf-fullscreen]');
    btn.title = on ? 'Quitter le plein écran (F)' : 'Plein écran (F)';
    btn.innerHTML = `<i data-lucide="${on ? 'minimize-2' : 'maximize-2'}" class="w-4 h-4"></i>`;
    icons();
    requestAnimationFrame(() => renderEdges());
  }
  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement && editorEl.classList.contains('is-fullscreen')) toggleFullscreen(false);
  });
  $('[data-wf-fullscreen]').addEventListener('click', () => toggleFullscreen());

  // ------------------------------------------------------------------ enregistrement
  async function save() {
    if (!current) return;
    const body = new URLSearchParams({
      graph: JSON.stringify(graph()),
      name: $('[data-wf-name]').value.trim(),
      description: current.description || '',
      is_active: $('[data-wf-active]').checked ? 'true' : 'false',
    });
    if (current.id) body.append('rule_id', current.id);
    const btn = $('[data-wf-save]');
    btn.disabled = true;
    try {
      const res = await fetch(cfg.saveUrl, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) { toast(data.message || "Impossible d'enregistrer le workflow.", true); return; }
      const isNew = !current.id;
      current.id = data.id;
      current.graph = data.graph;
      current.name = body.get('name');
      current.is_active = body.get('is_active') === 'true';
      const existing = workflows.find((w) => w.id === data.id);
      const record = {
        id: data.id, name: current.name || nodeTitle(triggerNode()), description: current.description, is_active: current.is_active,
        trigger_key: triggerNode().key, graph: clone(data.graph),
        run_count: existing ? existing.run_count : 0, last_triggered_at: existing ? existing.last_triggered_at : '', runs: existing ? existing.runs : [],
      };
      if (existing) Object.assign(existing, record); else workflows.unshift(record);
      dirty = false;
      updateDirty();
      renderBoard();
      renderList();
      toast(isNew ? 'Workflow créé et enregistré.' : 'Workflow enregistré.');
    } finally {
      btn.disabled = false;
    }
  }
  $('[data-wf-save]').addEventListener('click', save);
  $('[data-wf-name]').addEventListener('input', () => { dirty = true; updateDirty(); });
  $('[data-wf-active]').addEventListener('change', (e) => {
    $('[data-wf-active-label]').textContent = e.target.checked ? 'Actif' : 'En pause';
    dirty = true; updateDirty();
  });

  // ------------------------------------------------------------------ navigation liste / éditeur
  function openEditor(record) {
    current = {
      id: record.id || null,
      name: record.name || '',
      description: record.description || '',
      is_active: record.is_active !== false,
      graph: clone(record.graph || { nodes: [], edges: [] }),
    };
    if (current.graph.nodes.some((n) => n.x === undefined)) autoLayout(current.graph);
    selected = null; testLog = null; dirty = !record.id && current.graph.nodes.length > 0;
    history = { stack: [], index: -1 };
    snapshot();
    $('[data-wf-name]').value = current.name;
    $('[data-wf-active]').checked = current.is_active;
    $('[data-wf-active-label]').textContent = current.is_active ? 'Actif' : 'En pause';
    $('[data-wf-view="list"]').hidden = true;
    $('[data-wf-view="editor"]').hidden = false;
    renderLibrary($('[data-wf-library-search]').value);
    renderBoard();
    renderInspector();
    updateDirty();
    updateHistoryButtons();
    requestAnimationFrame(() => { renderEdges(); fitView(); });
  }
  function closeEditor() {
    toggleFullscreen(false);
    clearTimeout(liveTimer); simSeq += 1;
    if (dirty && !confirm('Quitter sans enregistrer les modifications ?')) return;
    dirty = false;
    current = null;
    $('[data-wf-view="editor"]').hidden = true;
    $('[data-wf-view="list"]').hidden = false;
    renderList();
  }
  $('[data-wf-back]').addEventListener('click', closeEditor);
  $('[data-wf-new]').addEventListener('click', () => openEditor({ graph: { nodes: [], edges: [] } }));
  window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

  // ------------------------------------------------------------------ vue liste
  const listHost = $('[data-wf-list]');
  function flowPreview(g) {
    const trig = g.nodes.find((n) => n.type === 'trigger');
    if (!trig) return '';
    const chain = [trig];
    let cursor = trig;
    for (let i = 0; i < 4; i += 1) {
      const edge = g.edges.find((e) => e.from === cursor.id && e.port !== 'false');
      if (!edge) break;
      cursor = g.nodes.find((n) => n.id === edge.to);
      if (!cursor) break;
      chain.push(cursor);
    }
    const rest = g.nodes.length - chain.length;
    return `<span class="wf-flow">${chain.map((n) => `<span class="wf-flow-step wf-flow-step--${n.type}"><i data-lucide="${nodeIcon(n)}" class="w-3 h-3"></i>${esc(nodeTitle(n))}</span>`).join('<i data-lucide="chevron-right" class="w-3 h-3 wf-flow-sep"></i>')}${rest > 0 ? `<span class="wf-flow-more">+${rest}</span>` : ''}</span>`;
  }
  function renderList() {
    const total = workflows.reduce((sum, w) => sum + (w.run_count || 0), 0);
    $('[data-wf-total-runs]').textContent = total;
    $('[data-wf-count]').textContent = workflows.length;
    $('[data-wf-active-count]').textContent = workflows.filter((w) => w.is_active).length;
    if (!workflows.length) {
      listHost.innerHTML = `<div class="wf-list-empty"><i data-lucide="workflow" class="w-6 h-6"></i><p>Aucun workflow pour l'instant.</p><p class="wf-help">Créez-en un de zéro ou partez d'un modèle ci-dessous.</p></div>`;
      icons();
      return;
    }
    listHost.innerHTML = workflows.map((w) => `
      <div class="wf-row${w.is_active ? '' : ' is-paused'}" data-wf-row="${w.id}">
        <div class="wf-row-main" data-wf-edit="${w.id}">
          <p class="wf-row-name">${esc(w.name)}</p>
          ${flowPreview(w.graph)}
        </div>
        <div class="wf-row-meta">
          <span>${w.run_count} exécution${w.run_count > 1 ? 's' : ''}</span>
          <small>${w.last_triggered_at ? `Dernière : ${esc(w.last_triggered_at)}` : 'Jamais déclenché'}</small>
        </div>
        <label class="wf-switch wf-switch--sm" title="Activer / mettre en pause"><input type="checkbox" data-wf-toggle="${w.id}" ${w.is_active ? 'checked' : ''}><span class="wf-switch-track"></span></label>
        <div class="wf-row-actions">
          <button type="button" class="wf-icon-btn" data-wf-history="${w.id}" title="Historique"><i data-lucide="history" class="w-4 h-4"></i></button>
          <button type="button" class="wf-icon-btn" data-wf-edit="${w.id}" title="Modifier"><i data-lucide="pencil" class="w-4 h-4"></i></button>
          <button type="button" class="wf-icon-btn wf-icon-btn--danger" data-wf-delete="${w.id}" title="Supprimer"><i data-lucide="trash-2" class="w-4 h-4"></i></button>
        </div>
        <div class="wf-row-history" data-wf-history-panel="${w.id}" hidden>${runsHtml(w.runs.map((r) => Object.assign({ graph: w.graph }, r)))}</div>
      </div>`).join('');
    icons();
  }
  listHost.addEventListener('click', async (e) => {
    const edit = e.target.closest('[data-wf-edit]');
    if (edit) { openEditor(workflows.find((w) => String(w.id) === edit.dataset.wfEdit)); return; }
    const hist = e.target.closest('[data-wf-history]');
    if (hist) { const panel = $(`[data-wf-history-panel="${hist.dataset.wfHistory}"]`); panel.hidden = !panel.hidden; return; }
    const del = e.target.closest('[data-wf-delete]');
    if (del) {
      const w = workflows.find((x) => String(x.id) === del.dataset.wfDelete);
      if (!confirm(`Supprimer le workflow « ${w.name} » ?`)) return;
      const res = await fetch(`${rulesBase}${w.id}/delete/`, { method: 'POST', headers: { 'X-CSRFToken': csrf() } });
      if (res.ok) { workflows = workflows.filter((x) => x.id !== w.id); renderList(); toast('Workflow supprimé.'); }
    }
  });
  listHost.addEventListener('change', async (e) => {
    const toggleInput = e.target.closest('[data-wf-toggle]');
    if (!toggleInput) return;
    const w = workflows.find((x) => String(x.id) === toggleInput.dataset.wfToggle);
    const res = await fetch(`${rulesBase}${w.id}/toggle/`, { method: 'POST', headers: { 'X-CSRFToken': csrf() } });
    const data = await res.json().catch(() => ({}));
    if (res.ok) { w.is_active = data.is_active; renderList(); toast(w.is_active ? 'Workflow activé.' : 'Workflow en pause.'); }
  });

  // ------------------------------------------------------------------ modèles
  const n = (id, type, key, params = {}, label = '') => ({ id, type, key, label, params: Object.assign(defaultParams(type, key), params) });
  const TEMPLATES = [
    {
      name: 'Relance de facture en retard', desc: 'Attend 3 jours, relance le client, et crée une tâche si le montant est important.',
      graph: {
        nodes: [
          n('t', 'trigger', 'invoice_overdue'),
          n('w', 'wait', 'delay', { amount: 3, unit: 'days' }),
          n('c', 'condition', 'if', { rules: [{ field: 'amount', op: 'gt', value: '1000' }] }, 'Montant important ?'),
          n('e1', 'action', 'send_email', { recipient: 'client', subject: 'Rappel : facture en attente de règlement', body: 'Bonjour {{client}},\n\nSauf erreur de notre part, la facture d\'un montant de {{montant}} reste impayée. Pourriez-vous nous indiquer la date de règlement prévue ?\n\nBien cordialement' }),
          n('k', 'action', 'create_task', { title: 'Appeler {{client}} — facture de {{montant}}', priority: 'high' }),
          n('e2', 'action', 'send_email', { recipient: 'client', subject: 'Petit rappel concernant votre facture', body: 'Bonjour {{client}},\n\nUn petit rappel amical : votre facture de {{montant}} est arrivée à échéance.\n\nMerci et belle journée' }),
        ],
        edges: [{ from: 't', port: 'out', to: 'w' }, { from: 'w', port: 'out', to: 'c' }, { from: 'c', port: 'true', to: 'e1' }, { from: 'e1', port: 'out', to: 'k' }, { from: 'c', port: 'false', to: 'e2' }],
      },
    },
    {
      name: 'Onboarding nouveau client', desc: 'Email de bienvenue, puis tâche de suivi deux jours plus tard.',
      graph: {
        nodes: [
          n('t', 'trigger', 'client_created'),
          n('e', 'action', 'send_email', { recipient: 'client', subject: 'Bienvenue {{client}} !', body: 'Bonjour {{client}},\n\nRavi de démarrer cette collaboration. Je reviens vers vous très vite pour organiser la suite.\n\nÀ bientôt' }),
          n('w', 'wait', 'delay', { amount: 2, unit: 'days' }),
          n('k', 'action', 'create_task', { title: 'Appel de lancement avec {{client}}', priority: 'medium' }),
        ],
        edges: [{ from: 't', port: 'out', to: 'e' }, { from: 'e', port: 'out', to: 'w' }, { from: 'w', port: 'out', to: 'k' }],
      },
    },
    {
      name: 'Devis accepté → lancement du projet', desc: 'Crée le projet, son premier jalon et vous prévient.',
      graph: {
        nodes: [
          n('t', 'trigger', 'quote_accepted'),
          n('p', 'action', 'create_project', { value: 'Projet {{client}}' }),
          n('m', 'action', 'create_milestone', { value: 'Kick-off' }),
          n('no', 'action', 'notify', { title: 'Devis accepté par {{client}}', message: 'Le projet a été créé automatiquement.', priority: 'high' }),
        ],
        edges: [{ from: 't', port: 'out', to: 'p' }, { from: 'p', port: 'out', to: 'm' }, { from: 'm', port: 'out', to: 'no' }],
      },
    },
    {
      name: 'Paiement reçu', desc: 'Remercie le client et signale les gros encaissements.',
      graph: {
        nodes: [
          n('t', 'trigger', 'payment_received'),
          n('e', 'action', 'send_email', { recipient: 'client', subject: 'Merci pour votre règlement', body: 'Bonjour {{client}},\n\nNous avons bien reçu votre paiement de {{montant}}. Merci !\n\nBien cordialement' }),
          n('c', 'condition', 'if', { rules: [{ field: 'amount', op: 'gte', value: '5000' }] }, 'Gros encaissement ?'),
          n('no', 'action', 'notify', { title: '{{montant}} encaissés de {{client}}', priority: 'high' }),
        ],
        edges: [{ from: 't', port: 'out', to: 'e' }, { from: 't', port: 'out', to: 'c' }, { from: 'c', port: 'true', to: 'no' }],
      },
    },
    {
      name: 'Relance de devis sans réponse', desc: 'Relance le client 5 jours après l\'envoi d\'un devis.',
      graph: {
        nodes: [
          n('t', 'trigger', 'quote_sent'),
          n('w', 'wait', 'delay', { amount: 5, unit: 'days' }),
          n('e', 'action', 'send_email', { recipient: 'client', subject: 'Avez-vous pu consulter notre devis ?', body: 'Bonjour {{client}},\n\nJe me permets de revenir vers vous au sujet du devis envoyé récemment. Avez-vous des questions ?\n\nBien cordialement' }),
        ],
        edges: [{ from: 't', port: 'out', to: 'w' }, { from: 'w', port: 'out', to: 'e' }],
      },
    },
    {
      name: 'Tâche en retard', desc: 'En semaine : tâche immédiate. Le week-end : attend lundi.',
      graph: {
        nodes: [
          n('t', 'trigger', 'task_overdue'),
          n('c', 'condition', 'if', { rules: [{ field: 'weekday', op: 'lte', value: '5' }] }, 'En semaine ?'),
          n('k1', 'action', 'create_task', { title: 'Tâche en retard à reprendre', priority: 'high' }),
          n('w', 'wait', 'delay', { amount: 2, unit: 'days' }),
          n('k2', 'action', 'create_task', { title: 'Tâche en retard à reprendre', priority: 'high' }),
        ],
        edges: [{ from: 't', port: 'out', to: 'c' }, { from: 'c', port: 'true', to: 'k1' }, { from: 'c', port: 'false', to: 'w' }, { from: 'w', port: 'out', to: 'k2' }],
      },
    },
  ];
  TEMPLATES.forEach((t) => autoLayout(t.graph));
  $('[data-wf-templates]').innerHTML = TEMPLATES.map((t, i) => `
    <button type="button" class="wf-template" data-wf-template="${i}">
      <span class="wf-template-name">${esc(t.name)}</span>
      <span class="wf-template-desc">${esc(t.desc)}</span>
      ${flowPreview(t.graph)}
      <span class="wf-template-meta">${t.graph.nodes.length} blocs</span>
    </button>`).join('');
  $('[data-wf-templates]').addEventListener('click', (e) => {
    const card = e.target.closest('[data-wf-template]');
    if (!card) return;
    const t = TEMPLATES[+card.dataset.wfTemplate];
    const g = clone(t.graph);
    const ids = {};
    g.nodes.forEach((node) => { ids[node.id] = uid(); node.id = ids[node.id]; });
    g.edges.forEach((edge) => { edge.from = ids[edge.from]; edge.to = ids[edge.to]; });
    openEditor({ name: t.name, description: t.desc, graph: g });
  });

  // ------------------------------------------------------------------ toast
  const toastEl = $('[data-wf-toast]');
  let toastTimer = null;
  function toast(message, isError) {
    toastEl.textContent = message;
    toastEl.classList.toggle('is-error', !!isError);
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, 3200);
  }

  // ------------------------------------------------------------------ init
  renderList();
  applyView();
  window.addEventListener('resize', () => { if (current) renderEdges(); });
})();
