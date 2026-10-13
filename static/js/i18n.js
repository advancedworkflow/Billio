/* Traduction des textes créés par le JavaScript (Alpine, éditeurs, menus, notifications).
   La page arrive déjà traduite par le serveur (apps/translations/middleware.py) ; ce script
   traduit ce qui apparaît ensuite, avec le même catalogue (window.__billioI18n).
   Les zones de contenu (documents, aperçus de factures, saisies) ne sont jamais touchées. */
(function () {
  'use strict';

  const data = window.__billioI18n;
  if (!data || (!Object.keys(data.exact).length && !data.patterns.length)) return;

  const exact = data.exact;
  const patterns = data.patterns.map(([source, target, lead, trail, glued]) => {
    const literals = source.replace(/^\^|\$$/g, '').split('(.*?)').map((p) => p.replace(/\\(.)/g, '$1'));
    const anchor = literals.reduce((a, b) => (b.length > a.length ? b : a), '');
    return { regex: new RegExp(source, 's'), target, anchor, lead, trail, glued: glued || [] };
  });
  const words = (s) => s.trim().split(/\s+/).filter(Boolean).length;
  const DT_TEST = /(\d{1,2}\/\d{1,2}(?:\/\d{2,4})?) à (\d{1,2}[:h]\d{2})/;
  const DT_ALL = new RegExp(DT_TEST.source, 'g');
  const DT_JOIN = { en: '$1 at $2', de: '$1 um $2', es: '$1 a las $2' }[data.lang];
  const cache = new Map();
  const SKIP = '[translate="no"], [data-no-translate], textarea, script, style, code, pre, [contenteditable="true"], [contenteditable=""]';
  const ATTRS = ['placeholder', 'title', 'aria-label', 'alt', 'data-tip', 'data-kbd'];

  function fill(template, groups) {
    if (/\{\d+\}/.test(template)) return template.replace(/\{(\d+)\}/g, (m, i) => groups[+i] ?? '');
    let i = 0;
    return template.replace(/\{\}/g, () => groups[i++] ?? '');
  }

  function lookup(key) {
    if (cache.has(key)) return cache.get(key);
    let out = exact[key];
    if (out === undefined && /\p{L}/u.test(key)) {
      for (const p of patterns) {
        if (p.anchor && !key.includes(p.anchor)) continue;
        const m = p.regex.exec(key);
        if (!m) continue;
        const groups = m.slice(1);
        // Partie variable en tête / en fin : courte (nombre, nom, pluriel), comme côté serveur.
        if ((p.lead && words(groups[0]) > 3) || (p.trail && words(groups[groups.length - 1]) > 3)) continue;
        // Partie variable collée à un mot (« facture{} ») : simple suffixe court.
        if (groups.some((g, i) => p.glued[i] && g && !/^\w{1,3}$/u.test(g))) continue;
        out = fill(p.target, groups.map((g) => exact[g.trim()] ?? g));
        break;
      }
    }
    // « 09/10/2026 à 10:40 » : le « à » des dates-heures suit la langue (comme côté serveur).
    if (DT_JOIN && DT_TEST.test(out ?? key)) out = (out ?? key).replace(DT_ALL, DT_JOIN);
    if (out === undefined) out = null;
    if (cache.size < 20000) cache.set(key, out);
    return out;
  }

  // Traduction d'un texte entier, espaces de début et de fin conservés.
  function t(text) {
    if (typeof text !== 'string') return text;
    const key = text.replace(/\s+/g, ' ').trim();
    if (!key) return text;
    const out = lookup(key);
    if (out === null) return text;
    return text.slice(0, text.length - text.trimStart().length) + out + text.slice(text.trimEnd().length);
  }
  window.billioT = t;

  const skipped = (el) => !el || (el.closest && el.closest(SKIP));

  function translateTextNode(node) {
    const value = node.data;
    if (node.__i18nOut === value || !/\p{L}/u.test(value)) return;
    if (skipped(node.parentElement)) return;
    const out = t(value);
    node.__i18nOut = out;
    if (out !== value) node.data = out;
  }

  function translateAttrs(el) {
    if (skipped(el)) return;
    for (const name of ATTRS) {
      const value = el.getAttribute(name);
      if (!value) continue;
      const out = t(value);
      if (out !== value) el.setAttribute(name, out);
    }
    if ((el.tagName === 'INPUT' && /^(submit|button)$/i.test(el.type)) && el.value) {
      const out = t(el.value);
      if (out !== el.value) el.value = out;
    }
  }

  function translateTree(root) {
    if (root.nodeType === 3) { translateTextNode(root); return; }
    if (root.nodeType !== 1 || skipped(root)) return;
    translateAttrs(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.nodeType === 1 && n.matches(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    let n = walker.nextNode();
    while (n) {
      if (n.nodeType === 3) translateTextNode(n); else translateAttrs(n);
      n = walker.nextNode();
    }
  }

  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === 'childList') m.addedNodes.forEach(translateTree);
      else if (m.type === 'characterData') translateTextNode(m.target);
      else if (m.type === 'attributes' && m.target.nodeType === 1) translateAttrs(m.target);
    }
  });
  observer.observe(document.documentElement, {
    childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS,
  });
  // Contenus des <template> (Alpine x-for / x-if) : traduits avant d'être clonés.
  document.addEventListener('DOMContentLoaded', () => {
    translateTree(document.body);
    document.querySelectorAll('template').forEach((tpl) => translateTree(tpl.content));
  });

  // Boîtes de dialogue natives.
  const nativeConfirm = window.confirm.bind(window);
  const nativeAlert = window.alert.bind(window);
  const nativePrompt = window.prompt.bind(window);
  window.confirm = (msg) => nativeConfirm(t(String(msg ?? '')));
  window.alert = (msg) => nativeAlert(t(String(msg ?? '')));
  window.prompt = (msg, def) => nativePrompt(t(String(msg ?? '')), def);
})();
