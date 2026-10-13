(function () {
  'use strict';

  function invoiceListCsrfToken() {
    const el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  function refreshInvoiceList() {
    if (typeof htmx !== 'undefined') htmx.trigger('body', 'invoiceListUpdated');
    else window.location.reload();
  }

  // POST d'une action de la liste des factures ; affiche l'erreur dans une fenêtre Billio.
  function invoiceAction(url, body, failMessage) {
    return fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': invoiceListCsrfToken(),
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
      },
      credentials: 'same-origin',
      body: body || '',
    })
      .then((r) => r.json().catch(() => ({})).then((data) => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (ok && data.success) { refreshInvoiceList(); return; }
        billioAlert(data.message || data.detail || failMessage, 'Action impossible');
      })
      .catch(() => billioAlert('Erreur réseau : vérifiez votre connexion et réessayez.', 'Action impossible'));
  }

  window.scheduleInvoiceSend = async function scheduleInvoiceSend(invoiceId, currentValue) {
    const value = await billioConfirm({
      title: 'Programmer l’envoi',
      message: 'La facture partira automatiquement à cette date. Laissez vide pour annuler la programmation.',
      input: { type: 'datetime-local', value: (currentValue || '').slice(0, 16), allowEmpty: true },
      confirmLabel: 'Enregistrer', icon: 'clock',
    });
    if (value === false) return;
    invoiceAction(`/invoices/${invoiceId}/schedule-send/`, `scheduled_send_at=${encodeURIComponent(value)}`,
      'Impossible de programmer l’envoi.');
  };

  window.sendInvoice = async function sendInvoice(invoiceId) {
    if (!(await billioConfirm({
      title: 'Envoyer la facture ?',
      message: 'Le client la reçoit par email avec le lien de paiement. Une fois envoyée, la facture ne peut plus être modifiée (correction par avoir).',
      confirmLabel: 'Envoyer', icon: 'send',
    }))) return;
    invoiceAction(`/invoices/${invoiceId}/send/`, '', 'Impossible d’envoyer la facture.');
  };

  window.duplicateInvoice = async function duplicateInvoice(invoiceId) {
    if (!(await billioConfirm({ title: 'Dupliquer la facture ?', message: 'Une copie est créée en brouillon.', confirmLabel: 'Dupliquer', icon: 'copy' }))) return;
    invoiceAction(`/invoices/${invoiceId}/duplicate/`, '', 'Impossible de dupliquer.');
  };

  window.markInvoicePaid = async function markInvoicePaid(invoiceId) {
    const method = await billioConfirm({
      title: 'Marquer comme payée',
      message: 'Paiement reçu en dehors du lien en ligne ? Indiquez comment le client a réglé.',
      choices: [
        { value: 'bank_transfer', label: 'Virement bancaire' },
        { value: 'check', label: 'Chèque' },
        { value: 'cash', label: 'Espèces' },
        { value: 'credit_card', label: 'Carte bancaire' },
        { value: 'paypal', label: 'PayPal' },
      ],
      value: 'bank_transfer', confirmLabel: 'Marquer payée', icon: 'badge-check',
    });
    if (!method) return;
    invoiceAction(`/invoices/${invoiceId}/mark-paid/`, `payment_method=${encodeURIComponent(method)}`,
      'Impossible de marquer la facture comme payée.');
  };

  window.copyShareLink = function copyShareLink(relativeUrl) {
    const fullUrl = `${window.location.origin}${relativeUrl}`;
    navigator.clipboard.writeText(fullUrl)
      .then(() => billioAlert('Le lien de paiement est copié : collez-le dans votre message au client.', 'Lien copié'))
      .catch(() => billioConfirm({ title: 'Copiez ce lien', input: { value: fullUrl }, confirmLabel: 'Fermer', alert: true }));
  };

  function initKanbanBoard() {
    const board = document.getElementById('kanban-board');
    if (!board) return;
    let draggedCard = null;

    function updateCount(column) {
      const countEl = column.querySelector('.kanban-column-count');
      const dropzone = column.querySelector('[data-kanban-dropzone]');
      if (countEl && dropzone) countEl.textContent = dropzone.children.length;
    }

    board.querySelectorAll('[data-kanban-card]').forEach((card) => {
      card.addEventListener('dragstart', () => {
        draggedCard = card;
        setTimeout(() => card.classList.add('is-dragging'), 0);
      });
      card.addEventListener('dragend', () => {
        card.classList.remove('is-dragging');
        draggedCard = null;
        board.querySelectorAll('[data-kanban-column]').forEach(updateCount);
      });
    });

    function getCsrfToken() {
      const el = document.querySelector('[name=csrfmiddlewaretoken]');
      return el ? el.value : '';
    }

    board.querySelectorAll('[data-kanban-dropzone]').forEach((zone) => {
      zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('is-dragover');
      });
      zone.addEventListener('dragleave', () => zone.classList.remove('is-dragover'));
      zone.addEventListener('drop', async (e) => {
        e.preventDefault();
        zone.classList.remove('is-dragover');
        if (!draggedCard) return;

        const card = draggedCard;
        const originZone = card.parentElement;
        const projectId = card.dataset.projectId;
        const newStatus = zone.dataset.kanbanDropzone;

        if (zone === originZone) return;
        zone.appendChild(card);
        board.querySelectorAll('[data-kanban-column]').forEach(updateCount);

        if (!projectId) return;
        const columnTitle = zone.closest('[data-kanban-column]')?.querySelector('h2, h3, .kanban-column-title')?.textContent.trim();
        const confirmed = window.billioConfirm ? await window.billioConfirm({
          title: columnTitle ? `Passer le projet en « ${columnTitle} » ?` : 'Changer la phase du projet ?',
          message: 'Le client verra la nouvelle étape dans son espace.',
          confirmLabel: 'Changer de phase', icon: 'flag',
        }) : true;
        if (!confirmed) {
          originZone.appendChild(card);
          board.querySelectorAll('[data-kanban-column]').forEach(updateCount);
          return;
        }
        fetch(`/dashboard/projects/${projectId}/status/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCsrfToken(),
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: `status=${encodeURIComponent(newStatus)}`,
        }).then((response) => {
          if (!response.ok) throw new Error('save failed');
        }).catch(() => {
          originZone.appendChild(card);
          board.querySelectorAll('[data-kanban-column]').forEach(updateCount);
        });
      });
    });
  }

  function initMilestonesKanbanBoard() {
    const board = document.getElementById('milestones-kanban-board');
    if (!board) return;
    let draggedCard = null;

    function updateCount(column) {
      const countEl = column.querySelector('.kanban-column-count');
      const dropzone = column.querySelector('[data-milestone-dropzone]');
      if (countEl && dropzone) countEl.textContent = dropzone.querySelectorAll('[data-milestone-card]').length;
    }

    function getCsrfToken() {
      const el = document.querySelector('[name=csrfmiddlewaretoken]');
      return el ? el.value : '';
    }

    board.querySelectorAll('[data-milestone-card]').forEach((card) => {
      card.addEventListener('dragstart', () => {
        draggedCard = card;
        setTimeout(() => card.classList.add('is-dragging'), 0);
      });
      card.addEventListener('dragend', () => {
        card.classList.remove('is-dragging');
        draggedCard = null;
        board.querySelectorAll('[data-kanban-column]').forEach(updateCount);
      });
    });

    board.querySelectorAll('[data-milestone-dropzone]').forEach((zone) => {
      zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('is-dragover');
      });
      zone.addEventListener('dragleave', () => zone.classList.remove('is-dragover'));
      zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('is-dragover');
        if (!draggedCard) return;

        const card = draggedCard;
        const originZone = card.parentElement;
        const milestoneId = card.dataset.milestoneId;
        const newPhase = zone.dataset.milestoneDropzone;
        const footer = zone.querySelector('[data-milestone-footer]');

        if (footer) zone.insertBefore(card, footer);
        else zone.appendChild(card);
        board.querySelectorAll('[data-kanban-column]').forEach(updateCount);

        if (!milestoneId) return;
        fetch(`/dashboard/milestones/${milestoneId}/phase/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCsrfToken(),
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: `phase=${encodeURIComponent(newPhase)}`,
        }).then((response) => {
          if (!response.ok) throw new Error('save failed');
        }).catch(() => {
          originZone.appendChild(card);
          board.querySelectorAll('[data-kanban-column]').forEach(updateCount);
        });
      });
    });
  }

  const CMD_RECENTS_KEY = 'billio-cmd-recents';

  function getCmdRecents() {
    try {
      return JSON.parse(localStorage.getItem(CMD_RECENTS_KEY) || '[]');
    } catch (e) {
      return [];
    }
  }

  function pushCmdRecent(href, label) {
    if (!href || href === '#') return;
    try {
      let recents = getCmdRecents().filter((r) => r.href !== href);
      recents.unshift({ href, label });
      recents = recents.slice(0, 3);
      localStorage.setItem(CMD_RECENTS_KEY, JSON.stringify(recents));
    } catch (e) { /* ignore storage errors */ }
  }

  function initDashboardWidgets() {
    const container = document.querySelector('[data-widget-container]');
    if (!container) return;
    const STORAGE_KEY = 'billio-dashboard-widget-order';
    let draggedWidget = null;

    function applyStoredOrder() {
      let order;
      try {
        order = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
      } catch (e) {
        order = null;
      }
      if (!Array.isArray(order) || !order.length) return;
      order.forEach((id) => {
        const el = container.querySelector(`[data-widget="${id}"]`);
        if (el) container.appendChild(el);
      });
    }

    function saveOrder() {
      const order = Array.from(container.querySelectorAll('[data-widget]')).map((el) => el.dataset.widget);
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(order)); } catch (e) { /* ignore storage errors */ }
    }

    function getDragAfterWidget(y) {
      const widgets = Array.from(container.querySelectorAll('[data-widget]:not(.is-dragging)'));
      return widgets.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) return { offset, element: child };
        return closest;
      }, { offset: -Infinity, element: null }).element;
    }

    applyStoredOrder();

    container.querySelectorAll('[data-widget]').forEach((widget) => {
      widget.addEventListener('dragstart', () => {
        draggedWidget = widget;
        setTimeout(() => widget.classList.add('is-dragging'), 0);
      });
      widget.addEventListener('dragend', () => {
        widget.classList.remove('is-dragging');
        draggedWidget = null;
        saveOrder();
      });
    });

    container.addEventListener('dragover', (e) => {
      if (!draggedWidget) return;
      e.preventDefault();
      const after = getDragAfterWidget(e.clientY);
      if (after) container.insertBefore(draggedWidget, after);
      else container.appendChild(draggedWidget);
    });

    document.querySelector('[data-widget-reset]')?.addEventListener('click', () => {
      try { localStorage.removeItem(STORAGE_KEY); } catch (e) { /* ignore storage errors */ }
      window.location.reload();
    });
  }

  function initCommandPalette() {
    const palette = document.getElementById('cmd-palette');
    if (!palette) return;

    const input = palette.querySelector('[data-cmd-input]');
    const list = palette.querySelector('[data-cmd-list]');
    const resultsWrap = palette.querySelector('[data-cmd-results]');
    const recentsWrap = palette.querySelector('[data-cmd-recents]');
    const emptyMsg = palette.querySelector('[data-cmd-empty]');
    const staticItems = Array.from(list.querySelectorAll('[data-cmd-item]'));
    const esc = (t) => String(t || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    let activeIndex = 0;
    let searchTimer = null;
    let searchToken = 0;

    const row = (href, icon, title, sub, extra = '') => `<a href="${esc(href)}" class="cmd-palette-item" data-cmd-dynamic ${extra}>
        <span class="cmd-ico"><i data-lucide="${esc(icon)}" class="w-4 h-4"></i></span>
        <span class="cmd-text"><strong>${esc(title)}</strong>${sub ? `<small>${esc(sub)}</small>` : ''}</span>
        <i data-lucide="corner-down-left" class="cmd-enter w-3.5 h-3.5"></i></a>`;

    function renderRecents(show) {
      const recents = show ? getCmdRecents() : [];
      recentsWrap.innerHTML = recents.length
        ? '<p class="cmd-palette-section-label">Récents</p>' + recents.map((r) => row(r.href, 'history', r.label, '')).join('')
        : '';
    }

    function visibleItems() {
      return Array.from(palette.querySelectorAll('.cmd-palette-item')).filter((el) => !el.classList.contains('hidden') && el.offsetParent !== null);
    }

    function highlight(scroll = true) {
      const vis = visibleItems();
      activeIndex = Math.max(0, Math.min(activeIndex, vis.length - 1));
      vis.forEach((el, i) => el.classList.toggle('is-active', i === activeIndex));
      if (scroll && vis[activeIndex]) vis[activeIndex].scrollIntoView({ block: 'nearest' });
    }

    function refreshSections() {
      list.querySelectorAll('[data-cmd-section]').forEach((label) => {
        let el = label.nextElementSibling;
        let any = false;
        while (el && !el.hasAttribute('data-cmd-section')) {
          if (el.matches('[data-cmd-item]') && !el.classList.contains('hidden')) any = true;
          el = el.nextElementSibling;
        }
        label.classList.toggle('hidden', !any);
      });
      emptyMsg.hidden = visibleItems().length > 0;
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    function filter(q) {
      const query = (q || '').trim().toLowerCase();
      staticItems.forEach((item) => {
        const label = (item.getAttribute('data-cmd-label') || item.textContent || '').toLowerCase();
        item.classList.toggle('hidden', !!query && !label.includes(query));
      });
      renderRecents(!query);
      if (query.length < 2) resultsWrap.innerHTML = '';
      refreshSections();
      activeIndex = 0;
      highlight(false);
      clearTimeout(searchTimer);
      if (query.length >= 2) searchTimer = setTimeout(() => search(query), 160);
    }

    async function search(query) {
      const token = ++searchToken;
      resultsWrap.innerHTML = '<p class="cmd-palette-section-label">Recherche…</p>';
      try {
        const response = await fetch(`/dashboard/search/?q=${encodeURIComponent(query)}`, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        const data = await response.json();
        if (token !== searchToken) return;
        const results = data.results || [];
        const groups = {};
        results.forEach((r) => { (groups[r.type] = groups[r.type] || []).push(r); });
        resultsWrap.innerHTML = Object.entries(groups).map(([type, rows]) =>
          `<p class="cmd-palette-section-label">${esc(type === 'Devis' ? 'Devis' : type + 's')}</p>` +
          rows.map((r) => row(r.url, r.icon, r.label, r.sub)).join('')).join('');
      } catch (e) {
        if (token === searchToken) resultsWrap.innerHTML = '';
      }
      refreshSections();
      activeIndex = 0;
      highlight(false);
    }

    function open() {
      palette.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
      input.value = '';
      filter('');
      setTimeout(() => input.focus(), 10);
    }

    function close() {
      palette.classList.add('hidden');
      document.body.style.overflow = '';
    }

    palette.addEventListener('click', (e) => {
      const item = e.target.closest('.cmd-palette-item');
      if (item) {
        pushCmdRecent(item.getAttribute('href'), item.querySelector('strong')?.textContent.trim() || '');
      }
    });
    palette.addEventListener('mousemove', (e) => {
      const item = e.target.closest('.cmd-palette-item');
      if (!item) return;
      const index = visibleItems().indexOf(item);
      if (index !== -1 && index !== activeIndex) { activeIndex = index; highlight(false); }
    });

    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (palette.classList.contains('hidden')) open(); else close();
        return;
      }
      if (palette.classList.contains('hidden')) return;
      if (e.key === 'Escape') { close(); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); activeIndex += 1; highlight(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); activeIndex -= 1; highlight(); }
      if (e.key === 'Enter') {
        const vis = visibleItems();
        if (vis[activeIndex]) {
          e.preventDefault();
          const item = vis[activeIndex];
          pushCmdRecent(item.getAttribute('href'), item.querySelector('strong')?.textContent.trim() || '');
          window.location.href = item.getAttribute('href');
          close();
        }
      }
    });

    document.querySelectorAll('[data-cmd-open]').forEach((btn) => btn.addEventListener('click', open));
    palette.querySelector('[data-cmd-backdrop]')?.addEventListener('click', close);
    input.addEventListener('input', () => filter(input.value));
  }

  function initScrollReveal() {
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add('is-visible');
          const goal = e.target.querySelector('.goal-progress-fill');
          if (goal) goal.style.width = goal.getAttribute('data-width') || '0%';
        }
      });
    }, { threshold: 0.1 });
    document.querySelectorAll('.dash-reveal').forEach((el) => obs.observe(el));
  }

  document.addEventListener('DOMContentLoaded', () => {
    initCommandPalette();
    initScrollReveal();
    initKanbanBoard();
    initMilestonesKanbanBoard();
    initDashboardWidgets();
    if (typeof lucide !== 'undefined') lucide.createIcons();
  });
})();
