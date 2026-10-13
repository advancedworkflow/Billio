/*
 * Chrono Billio : un seul chrono par utilisateur, visible partout.
 * - pastille dans la barre du haut ([data-bt-chip]) + panneau ([data-bt-mount]) ;
 * - durée dans le titre de l'onglet tant que le chrono tourne ;
 * - mini-fenêtre détachée (/dashboard/time/widget/) qui survit à la navigation, d'où l'on peut
 *   ouvrir un widget « toujours au premier plan » (Document Picture-in-Picture, Chrome / Edge).
 * Les onglets et fenêtres se synchronisent par BroadcastChannel.
 */
(function () {
    if (window.BillioTimer) return;

    const STATUS_URL = '/dashboard/time/status/';
    const WIDGET_URL = '/dashboard/time/widget/';
    const CSS_URL = document.currentScript ? new URL('../css/time-widget.css?v=1.0', document.currentScript.src).href : '';
    const state = { loaded: false, running: null, projects: [], offset: 0, startMs: 0 };
    const mounts = new Set();
    const chips = new Set();
    const channel = 'BroadcastChannel' in window ? new BroadcastChannel('billio-timer') : null;
    let baseTitle = document.title;
    let pipWindow = null;

    const csrf = () => (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';

    function fmt(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor(seconds / 60) % 60;
        const s = seconds % 60;
        return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    function elapsed() {
        return state.running ? Math.max(0, Math.floor((Date.now() + state.offset - state.startMs) / 1000)) : 0;
    }

    async function refresh() {
        try {
            const response = await fetch(STATUS_URL, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
            if (!response.ok) return;
            const data = await response.json();
            const before = state.loaded ? (state.running && state.running.id) || null : undefined;
            state.loaded = true;
            state.running = data.running;
            state.projects = data.projects || [];
            state.locked = data.locked || '';
            state.upgradeUrl = data.upgrade_url || '';
            state.offset = new Date(data.now).getTime() - Date.now();
            state.startMs = data.running ? new Date(data.running.started_at).getTime() : 0;
            render();
            const after = (data.running && data.running.id) || null;
            if (before !== undefined && before !== after) window.dispatchEvent(new CustomEvent('billio-timer:change', { detail: state }));
        } catch (e) { /* hors ligne : on garde l'état connu */ }
    }

    async function post(url, body) {
        const response = await fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrf(), Accept: 'application/json' }, body: body || new URLSearchParams(),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.message || 'Action impossible, réessayez.');
        return data;
    }

    async function start(projectId, description) {
        await post(`/dashboard/projects/${projectId}/time/start/`, new URLSearchParams({ description: description || '' }));
        await refresh();
        if (channel) channel.postMessage('changed');
    }

    async function stop() {
        if (!state.running) return;
        try {
            await post(`/dashboard/time/${state.running.id}/stop/`);
        } finally {
            await refresh();
            if (channel) channel.postMessage('changed');
        }
    }

    /* ---------- Rendu ---------- */

    function el(doc, tag, attrs, children) {
        const node = doc.createElement(tag);
        Object.entries(attrs || {}).forEach(([key, value]) => {
            if (key === 'text') node.textContent = value;
            else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
            else node.setAttribute(key, value);
        });
        (children || []).forEach((child) => child && node.append(child));
        return node;
    }

    function renderMount(root) {
        const opts = root._btOptions || {};
        const key = !state.loaded ? 'loading' : (state.running ? `run-${state.running.id}` : (state.locked ? 'locked' : `idle-${state.projects.length}`));
        if (root._btKey === key) return;
        root._btKey = key;
        const doc = root.ownerDocument;
        const message = el(doc, 'p', { class: 'bt-msg', role: 'status' });
        const fail = (error) => { message.textContent = error.message; };
        root.replaceChildren();

        if (!state.loaded) {
            root.append(el(doc, 'div', { class: 'bt-widget' }, [el(doc, 'p', { class: 'bt-muted', text: 'Chargement…' })]));
            return;
        }
        const widget = el(doc, 'div', { class: `bt-widget${state.running ? ' is-running' : ''}` });
        widget.append(el(doc, 'div', { class: 'bt-head' }, [
            el(doc, 'span', { class: 'bt-dot' }),
            el(doc, 'span', { class: 'bt-label', text: state.running ? 'Chrono en cours' : 'Chrono' }),
        ]));

        if (state.running) {
            const r = state.running;
            const target = opts.external ? '_blank' : '_self';
            widget.append(
                el(doc, 'div', { class: 'bt-time', 'data-bt-elapsed': '', text: fmt(elapsed()) }),
                el(doc, 'a', { class: 'bt-project', href: r.url, target, translate: 'no', title: 'Ouvrir le projet' }, [
                    el(doc, 'strong', { text: r.project }),
                    r.client ? el(doc, 'span', { text: ` · ${r.client}` }) : null,
                ]),
                (r.task || r.description) ? el(doc, 'p', { class: 'bt-desc', translate: 'no', text: [r.task, r.description].filter(Boolean).join(' — ') }) : null,
                el(doc, 'button', { type: 'button', class: 'bt-btn bt-btn--stop', onclick: () => stop().catch(fail) }, [
                    el(doc, 'span', { class: 'bt-icon-stop', 'aria-hidden': 'true' }), doc.createTextNode(' Arrêter'),
                ]),
            );
        } else if (state.locked) {
            widget.append(
                el(doc, 'p', { class: 'bt-muted', text: state.locked }),
                el(doc, 'a', { class: 'bt-link', href: state.upgradeUrl, target: opts.external ? '_blank' : '_self', text: 'Voir les forfaits →' }),
            );
        } else if (!state.projects.length) {
            widget.append(el(doc, 'p', { class: 'bt-muted', text: 'Créez d’abord un projet pour chronométrer votre temps.' }));
        } else {
            const select = el(doc, 'select', { class: 'bt-input', 'aria-label': 'Projet', translate: 'no' },
                state.projects.map((p) => el(doc, 'option', { value: p.id, text: p.client ? `${p.name} · ${p.client}` : p.name })));
            const description = el(doc, 'input', { class: 'bt-input', type: 'text', maxlength: '255', placeholder: 'Sur quoi travaillez-vous ?' });
            const form = el(doc, 'form', {
                class: 'bt-form',
                onsubmit: (event) => { event.preventDefault(); start(select.value, description.value).catch(fail); },
            }, [select, description, el(doc, 'button', { type: 'submit', class: 'bt-btn bt-btn--start' }, [
                el(doc, 'span', { class: 'bt-icon-play', 'aria-hidden': 'true' }), doc.createTextNode(' Démarrer'),
            ])]);
            widget.append(form);
        }

        if (opts.detach && !state.locked) {
            widget.append(el(doc, 'button', { type: 'button', class: 'bt-link', onclick: () => detach() }, [doc.createTextNode('Détacher en widget ↗')]));
        }
        if (opts.pin && 'documentPictureInPicture' in window) {
            widget.append(el(doc, 'button', { type: 'button', class: 'bt-link', onclick: () => pin().catch(fail) }, [doc.createTextNode('Toujours au premier plan 📌')]));
        }
        widget.append(message);
        root.append(widget);
    }

    function render() {
        mounts.forEach((root) => (root.isConnected ? renderMount(root) : mounts.delete(root)));
        chips.forEach((chip) => {
            chip.classList.toggle('is-running', !!state.running);
            const label = chip.querySelector('[data-bt-chip-time]');
            if (label) label.textContent = state.running ? fmt(elapsed()) : '';
        });
        tick();
    }

    function tick() {
        const text = fmt(elapsed());
        mounts.forEach((root) => root.querySelectorAll('[data-bt-elapsed]').forEach((node) => { node.textContent = text; }));
        chips.forEach((chip) => {
            const label = chip.querySelector('[data-bt-chip-time]');
            if (label && state.running) label.textContent = text;
        });
        const title = state.running ? `⏱ ${text} · ${baseTitle}` : baseTitle;
        if (document.title !== title) document.title = title;
        if (pipWindow) pipWindow.document.title = state.running ? `⏱ ${text}` : 'Chrono Billio';
    }

    function mount(root, options) {
        root._btOptions = options || {};
        root._btKey = null;
        mounts.add(root);
        renderMount(root);
    }

    /* ---------- Fenêtres ---------- */

    function detach() {
        const win = window.open(WIDGET_URL, 'billio-chrono', 'popup,width=340,height=300');
        if (win) win.focus();
    }

    async function pin() {
        if (pipWindow) { pipWindow.focus(); return; }
        pipWindow = await window.documentPictureInPicture.requestWindow({ width: 300, height: 220 });
        const doc = pipWindow.document;
        doc.head.append(el(doc, 'link', { rel: 'stylesheet', href: CSS_URL }));
        doc.body.className = 'bt-standalone bt-pip';
        const root = el(doc, 'div');
        doc.body.append(root);
        mount(root, { external: true });
        tick();
        pipWindow.addEventListener('pagehide', () => { mounts.delete(root); pipWindow = null; render(); });
        document.body.classList.add('bt-pinned');
        pipWindow.addEventListener('pagehide', () => document.body.classList.remove('bt-pinned'));
    }

    /* ---------- Démarrage ---------- */

    function init() {
        baseTitle = document.title;
        document.querySelectorAll('[data-bt-chip]').forEach((chip) => chips.add(chip));
        document.querySelectorAll('[data-bt-mount]').forEach((root) => mount(root, {
            detach: root.hasAttribute('data-bt-detach'),
            pin: root.hasAttribute('data-bt-pin'),
            external: root.hasAttribute('data-bt-external'),
        }));
        if (!chips.size && !mounts.size) return;
        refresh();
        setInterval(tick, 1000);
        setInterval(refresh, 60000);
        document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
        if (channel) channel.onmessage = () => refresh();
    }

    // Prévenir les autres onglets / fenêtres après une action faite ailleurs (ex. page projet).
    const notify = () => { if (channel) channel.postMessage('changed'); };

    window.BillioTimer = { state, refresh, start, stop, mount, detach, pin, notify };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
