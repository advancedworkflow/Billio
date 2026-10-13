/* Actions des plugins utilisables partout dans l'application :
   - billioPlugins.driveUpload(kind, id, button)  : copie le PDF d'une facture / d'un devis / d'un document dans Drive ;
   - billioPlugins.exportTable(table, target)     : exporte factures ou paiements (csv, drive, notion) ;
   - billioPlugins.driveImport(projectId)         : choisit un fichier Drive et l'ajoute aux fichiers du projet.
   Les boutons ne sont rendus que si le plugin est connecté (context processor connected_plugins). */
(function () {
  'use strict';

  const csrf = () => {
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    if (input) return input.value;
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  };
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function toast(text, ok = true, link = '') {
    const el = document.createElement('div');
    el.className = `bp-toast${ok ? '' : ' is-error'}`;
    el.innerHTML = `<span>${esc(text)}</span>${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">Ouvrir</a>` : ''}`;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add('is-out'), 4200);
    setTimeout(() => el.remove(), 4700);
  }

  async function post(url, body, json = true) {
    const res = await fetch(url, {
      method: 'POST',
      headers: json ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() } : { 'X-CSRFToken': csrf() },
      body: json ? JSON.stringify(body) : new URLSearchParams(body),
    });
    return res.json().catch(() => ({ ok: false, error: 'Réponse illisible du serveur.' }));
  }

  function busy(button, on, label) {
    if (!button) return;
    if (on) { button.dataset.label = button.innerHTML; button.disabled = true; button.innerHTML = label; }
    else { button.disabled = false; if (button.dataset.label) button.innerHTML = button.dataset.label; }
  }

  async function driveUpload(kind, id, button) {
    busy(button, true, 'Envoi vers Drive…');
    try {
      const data = await post('/integrations/drive/upload/', { kind, id });
      if (data.ok) toast(`« ${data.name} » copié dans votre Drive.`, true, data.link);
      else toast(data.error || 'Envoi impossible.', false);
    } finally { busy(button, false); }
  }

  async function exportTable(table, target, button) {
    if (target === 'csv') { window.location.href = `/integrations/export/${table}/?target=csv`; return; }
    busy(button, true, 'Export…');
    try {
      const data = await post(`/integrations/export/${table}/`, { target }, false);
      if (data.ok) toast(data.detail, true, data.link);
      else toast(data.error || 'Export impossible.', false);
    } finally { busy(button, false); }
  }

  // Sélecteur de fichier Drive (fenêtre construite à la volée).
  function driveImport(projectId) {
    const modal = document.createElement('div');
    modal.className = 'bp-modal';
    modal.innerHTML = `
      <div class="bp-modal-card" role="dialog" aria-label="Importer depuis Google Drive">
        <header><strong>Importer depuis Google Drive</strong><button type="button" data-close aria-label="Fermer">✕</button></header>
        <div class="bp-modal-search"><input type="search" placeholder="Rechercher un fichier…" autofocus></div>
        <div class="bp-modal-list"><p class="bp-muted">Chargement…</p></div>
        <p class="bp-muted bp-modal-foot">Les documents Google sont importés en PDF (tableurs en Excel).</p>
      </div>`;
    document.body.appendChild(modal);
    const list = modal.querySelector('.bp-modal-list');
    const input = modal.querySelector('input');
    const close = () => modal.remove();
    modal.addEventListener('click', (e) => { if (e.target === modal || e.target.closest('[data-close]')) close(); });
    document.addEventListener('keydown', function onKey(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); } });

    async function load() {
      const res = await fetch(`/integrations/drive/files/?q=${encodeURIComponent(input.value.trim())}`);
      const data = await res.json().catch(() => ({ ok: false }));
      if (!data.ok) { list.innerHTML = `<p class="bp-error">${esc(data.error || 'Drive indisponible.')}</p>`; return; }
      if (!data.files.length) { list.innerHTML = '<p class="bp-muted">Aucun fichier trouvé.</p>'; return; }
      list.innerHTML = data.files.map((f) => `
        <button type="button" class="bp-file" data-id="${esc(f.id)}">
          ${f.iconLink ? `<img src="${esc(f.iconLink)}" alt="">` : ''}
          <span><strong>${esc(f.name)}</strong><small>${esc((f.modifiedTime || '').slice(0, 10))}</small></span>
        </button>`).join('');
    }
    let timer;
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 350); });
    list.addEventListener('click', async (e) => {
      const btn = e.target.closest('.bp-file');
      if (!btn) return;
      btn.disabled = true;
      btn.classList.add('is-loading');
      const data = await post('/integrations/drive/import/', { project_id: projectId, file_id: btn.dataset.id });
      if (data.ok) { toast(`« ${data.name} » ajouté au projet.`); close(); setTimeout(() => window.location.reload(), 700); }
      else { toast(data.error || 'Import impossible.', false); btn.disabled = false; btn.classList.remove('is-loading'); }
    });
    load();
  }

  window.billioPlugins = { driveUpload, exportTable, driveImport, toast };
})();
