/* Bandeau de consentement aux cookies (UE : RGPD/ePrivacy ; États-Unis : CCPA/CPRA, signal GPC).
 * Ajouté à toutes les pages par apps.landing.consent.ConsentMiddleware. Règles :
 * - rien de facultatif avant un choix ; « Tout refuser » aussi simple que « Tout accepter » ;
 * - choix gardé 6 mois (cookie billio_consent), modifiable via tout élément [data-consent-open] ;
 * - Global Privacy Control = refus automatique ;
 * - scripts facultatifs : <script type="text/plain" data-consent="analytics"> activés après accord ;
 * - API : window.billioConsent.has('analytics'), .open(), évènement « billio:consent ».
 */
(function () {
  'use strict';
  if (window.billioConsent) return;
  var VERSION = 1;
  var COOKIE = 'billio_consent';
  var MAX_AGE = 182 * 24 * 3600;
  var CATEGORIES = ['analytics'];
  var gpc = navigator.globalPrivacyControl === true;
  var inFrame = window.self !== window.top;
  var choice = read();
  var root = null;

  function read() {
    var match = document.cookie.match(/(?:^|;\s*)billio_consent=([^;]+)/);
    if (!match) return null;
    var parts = decodeURIComponent(match[1]).split('.');
    if (parts[0] !== 'v' + VERSION) return null;
    var result = {};
    parts.slice(1).forEach(function (p) {
      var kv = p.split('-');
      if (CATEGORIES.indexOf(kv[0]) !== -1) result[kv[0]] = kv[1] === '1';
    });
    return result;
  }

  function consentId() {
    var id = null;
    try { id = localStorage.getItem('billio_consent_id'); } catch (e) { /* stockage indisponible */ }
    if (!id) {
      id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, function () { return (Math.random() * 16 | 0).toString(16); });
      try { localStorage.setItem('billio_consent_id', id); } catch (e) { /* idem */ }
    }
    return id;
  }

  function save(next, action) {
    if (gpc) next.analytics = false;
    choice = next;
    var value = 'v' + VERSION + CATEGORIES.map(function (c) { return '.' + c + '-' + (next[c] ? '1' : '0'); }).join('');
    document.cookie = COOKIE + '=' + value + '; Max-Age=' + MAX_AGE + '; Path=/; SameSite=Lax' + (location.protocol === 'https:' ? '; Secure' : '');
    try {
      fetch('/cookies/consent/', {
        method: 'POST', keepalive: true, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: consentId(), choices: next, action: action, gpc: gpc, page: location.pathname }),
      }).catch(function () {});
    } catch (e) { /* journal facultatif */ }
    apply();
    close();
    document.dispatchEvent(new CustomEvent('billio:consent', { detail: next }));
  }

  function apply() {
    document.querySelectorAll('script[type="text/plain"][data-consent]').forEach(function (old) {
      if (!choice || !choice[old.dataset.consent]) return;
      var s = document.createElement('script');
      Array.prototype.forEach.call(old.attributes, function (a) { if (a.name !== 'type') s.setAttribute(a.name, a.value); });
      s.text = old.text;
      old.replaceWith(s);
    });
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function button(label, cls, onClick) {
    var b = el('button', 'bc-btn ' + (cls || ''), label);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }

  function all(value, action) {
    var next = {};
    CATEGORIES.forEach(function (c) { next[c] = value; });
    save(next, action);
  }

  function close() {
    if (root) { root.remove(); root = null; }
  }

  function render(detailed) {
    close();
    root = el('div', 'bc' + (detailed ? ' bc--panel' : ''));
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-labelledby', 'bc-title');
    var box = el('div', 'bc-box');
    var title = el('h2', 'bc-title', 'Vos choix de cookies');
    title.id = 'bc-title';
    box.appendChild(title);
    box.appendChild(el('p', 'bc-text', 'Billio utilise des cookies indispensables au fonctionnement du site. Avec votre accord, nous mesurons aussi la fréquentation, sans publicité et sans partage avec des tiers. Vous pouvez changer d’avis à tout moment.'));
    if (gpc) box.appendChild(el('p', 'bc-note', 'Signal Global Privacy Control détecté : la mesure d’audience reste désactivée.'));

    var toggles = {};
    if (detailed) {
      var list = el('div', 'bc-list');
      var rows = [
        { key: null, name: 'Strictement nécessaires', desc: 'Connexion, sécurité des formulaires, langue et mémorisation de vos choix. Toujours actifs.' },
        { key: 'analytics', name: 'Mesure d’audience', desc: 'Compter les visiteurs uniques du site, sans cookie supplémentaire ni partage avec des tiers. Données effacées après 90 jours.' },
      ];
      rows.forEach(function (row) {
        var item = el('label', 'bc-item');
        var text = el('span', 'bc-item-text');
        text.appendChild(el('strong', '', row.name));
        text.appendChild(el('small', '', row.desc));
        var input = el('input');
        input.type = 'checkbox';
        input.className = 'bc-switch';
        if (row.key) {
          input.checked = !!(choice && choice[row.key]) && !gpc;
          input.disabled = gpc;
          toggles[row.key] = input;
        } else {
          input.checked = true;
          input.disabled = true;
        }
        item.appendChild(text);
        item.appendChild(input);
        list.appendChild(item);
      });
      box.appendChild(list);
      var us = el('p', 'bc-note', 'Billio ne vend pas et ne partage pas vos informations personnelles.');
      box.appendChild(us);
    }

    var actions = el('div', 'bc-actions');
    actions.appendChild(button('Tout refuser', '', function () { all(false, 'reject_all'); }));
    if (detailed) {
      actions.appendChild(button('Enregistrer mes choix', '', function () {
        var next = {};
        CATEGORIES.forEach(function (c) { next[c] = !!(toggles[c] && toggles[c].checked); });
        save(next, 'custom');
      }));
    } else {
      actions.appendChild(button('Personnaliser', '', function () { render(true); }));
    }
    actions.appendChild(button('Tout accepter', '', function () { all(true, 'accept_all'); }));
    box.appendChild(actions);

    var links = el('p', 'bc-links');
    var policy = el('a', '', 'Politique cookies');
    policy.href = '/cookies/';
    links.appendChild(policy);
    box.appendChild(links);
    if (detailed && choice) {
      var dismiss = button('Fermer', 'bc-close', close);
      dismiss.setAttribute('aria-label', 'Fermer');
      dismiss.textContent = '×';
      box.appendChild(dismiss);
    }
    root.appendChild(box);
    document.body.appendChild(root);
    var first = root.querySelector('.bc-btn');
    if (detailed && first) first.focus();
  }

  window.billioConsent = {
    get: function () { return choice; },
    has: function (category) { return !gpc && !!(choice && choice[category]); },
    open: function () { render(true); },
  };

  function start() {
    document.addEventListener('click', function (event) {
      var trigger = event.target.closest && event.target.closest('[data-consent-open]');
      if (!trigger) return;
      event.preventDefault();
      render(true);
    });
    if (inFrame) return;  // aperçus intégrés (emails, documents) : pas de bandeau
    if (choice) { apply(); return; }
    if (gpc) { all(false, 'gpc'); return; }
    render(false);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
