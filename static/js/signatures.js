/*
 * Signature électronique : affichage du PDF (pdf.js, servi par Billio), éditeur de champs
 * (sgBuilder) et page du signataire (sgSign). Positions des champs en fraction de la page.
 */
(function () {
  'use strict';

  var PDFJS_BASE = (document.currentScript && document.currentScript.dataset.pdfjs) || '/static/vendor/pdfjs/';

  function csrf() {
    var input = document.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: 'Erreur du serveur (' + r.status + ').' }; });
    });
  }

  /* Rend chaque page du PDF dans `container` (un .sg-page par page, canvas à 100 % de largeur). */
  function renderPdf(url, container) {
    var lib = window.pdfjsLib;
    lib.GlobalWorkerOptions.workerSrc = PDFJS_BASE + 'pdf.worker.min.js';
    return lib.getDocument({ url: url, withCredentials: true }).promise.then(function (pdf) {
      var ratio = Math.min(window.devicePixelRatio || 1, 2);
      var target = Math.min(Math.max(container.clientWidth, 320), 1000) * ratio;
      var jobs = [];
      for (var i = 1; i <= pdf.numPages; i++) {
        jobs.push(pdf.getPage(i).then(function (page) {
          var base = page.getViewport({ scale: 1 });
          var viewport = page.getViewport({ scale: target / base.width });
          var holder = container.querySelector('[data-page="' + (page.pageNumber - 1) + '"] .sg-canvas');
          if (!holder) return;
          var canvas = document.createElement('canvas');
          canvas.width = Math.floor(viewport.width);
          canvas.height = Math.floor(viewport.height);
          holder.appendChild(canvas);
          return page.render({ canvasContext: canvas.getContext('2d'), viewport: viewport }).promise;
        }));
      }
      return Promise.all(jobs);
    });
  }

  /* Zone de dessin d'une signature (souris, doigt, stylet). */
  function Pad(canvas) {
    var ctx = canvas.getContext('2d');
    var drawing = false, last = null, dirty = false;
    function size() {
      var ratio = Math.min(window.devicePixelRatio || 1, 2);
      var rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(rect.width * ratio));
      canvas.height = Math.max(1, Math.round(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#0f172a'; ctx.lineWidth = 2.4;
      dirty = false;
    }
    function point(e) {
      var rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }
    canvas.addEventListener('pointerdown', function (e) {
      e.preventDefault(); canvas.setPointerCapture(e.pointerId);
      // Dimensionné à l'ouverture, la fenêtre pouvait encore être masquée : on recale au premier trait.
      var expected = Math.round(canvas.getBoundingClientRect().width * Math.min(window.devicePixelRatio || 1, 2));
      if (!dirty && Math.abs(canvas.width - expected) > 2) size();
      drawing = true; last = point(e);
      ctx.beginPath(); ctx.arc(last.x, last.y, 1.1, 0, Math.PI * 2); ctx.fillStyle = '#0f172a'; ctx.fill();
      dirty = true;
    });
    canvas.addEventListener('pointermove', function (e) {
      if (!drawing) return;
      var p = point(e);
      var mid = { x: (last.x + p.x) / 2, y: (last.y + p.y) / 2 };
      ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.quadraticCurveTo(last.x, last.y, mid.x, mid.y); ctx.lineTo(p.x, p.y); ctx.stroke();
      last = p; dirty = true;
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (name) {
      canvas.addEventListener(name, function () { drawing = false; });
    });
    this.size = size;
    this.clear = function () { ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.restore(); dirty = false; };
    this.isEmpty = function () { return !dirty; };
    this.canvas = canvas;
  }

  /* PNG recadré sur le tracé (marges transparentes retirées). */
  function trimmedPng(canvas) {
    var ctx = canvas.getContext('2d');
    var w = canvas.width, h = canvas.height;
    var data = ctx.getImageData(0, 0, w, h).data;
    var top = h, left = w, right = -1, bottom = -1;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        if (data[(y * w + x) * 4 + 3] > 8) {
          if (x < left) left = x; if (x > right) right = x;
          if (y < top) top = y; if (y > bottom) bottom = y;
        }
      }
    }
    if (right < 0) return '';
    var pad = 6;
    left = Math.max(0, left - pad); top = Math.max(0, top - pad);
    right = Math.min(w - 1, right + pad); bottom = Math.min(h - 1, bottom + pad);
    var out = document.createElement('canvas');
    out.width = right - left + 1; out.height = bottom - top + 1;
    out.getContext('2d').drawImage(canvas, left, top, out.width, out.height, 0, 0, out.width, out.height);
    return out.toDataURL('image/png');
  }

  /* Signature « écrite » : le nom tapé, rendu dans une police manuscrite. */
  function typedPng(text, font) {
    var canvas = document.createElement('canvas');
    var ctx = canvas.getContext('2d');
    var size = 96;
    ctx.font = size + 'px "' + font + '", cursive';
    var width = Math.ceil(ctx.measureText(text).width) + 40;
    canvas.width = Math.min(width, 2400); canvas.height = Math.round(size * 1.6);
    ctx.font = size + 'px "' + font + '", cursive';
    ctx.fillStyle = '#0f172a'; ctx.textBaseline = 'middle';
    ctx.fillText(text, 20, canvas.height / 2);
    return trimmedPng(canvas);
  }

  /* Image importée (photo d'une signature) : fond clair rendu transparent. */
  function imagePng(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () {
        var img = new Image();
        img.onload = function () {
          var scale = Math.min(1, 1200 / img.width, 600 / img.height);
          var canvas = document.createElement('canvas');
          canvas.width = Math.round(img.width * scale); canvas.height = Math.round(img.height * scale);
          var ctx = canvas.getContext('2d');
          ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
          var pixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
          for (var i = 0; i < pixels.data.length; i += 4) {
            var light = (pixels.data[i] + pixels.data[i + 1] + pixels.data[i + 2]) / 3;
            if (light > 200) pixels.data[i + 3] = 0;
          }
          ctx.putImageData(pixels, 0, 0);
          resolve(trimmedPng(canvas));
        };
        img.onerror = reject;
        img.src = reader.result;
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  // Taille par défaut des champs, en points PDF.
  var DEFAULT_SIZE = {
    signature: [170, 52], initials: [72, 40], name: [170, 22], date: [100, 22], text: [170, 22], checkbox: [16, 16]
  };
  var KIND_LABELS = {
    signature: 'Signature', initials: 'Initiales', name: 'Nom complet', date: 'Date', text: 'Texte', checkbox: 'Case'
  };

  /* ------------------------------------------------------------------ */
  /* Éditeur : placer les champs et choisir les signataires              */
  /* ------------------------------------------------------------------ */
  window.sgBuilder = function (initial, urls, colors, clients) {
    return {
      title: initial.title, message: initial.message, inOrder: initial.in_order, validDays: initial.valid_days || 30,
      pages: initial.pages, signers: initial.signers, fields: initial.fields.map(function (f, i) { return Object.assign({ uid: 'f' + i }, f); }),
      clients: clients, colors: colors, labels: KIND_LABELS,
      active: initial.signers.length ? initial.signers[0].key : null,
      selected: null, placing: null, drag: null, saving: false, savedAt: '', error: '', problems: [], loading: true, sending: false,
      nextKey: 1000, nextUid: initial.fields.length,
      timer: null,

      init: function () {
        var self = this;
        if (!this.signers.length) this.addSigner();
        this.$nextTick(function () {
          renderPdf(urls.pdf, self.$refs.pages).then(function () { self.loading = false; })
            .catch(function () { self.loading = false; self.error = 'Le PDF n’a pas pu être affiché.'; });
        });
        window.addEventListener('pointermove', function (e) { self.onMove(e); });
        window.addEventListener('pointerup', function () { self.endDrag(); });
        window.addEventListener('keydown', function (e) {
          if ((e.key === 'Delete' || e.key === 'Backspace') && self.selected && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
            e.preventDefault(); self.removeField(self.selected);
          }
          if (e.key === 'Escape') { self.placing = null; self.selected = null; }
        });
        ['title', 'message', 'inOrder', 'validDays'].forEach(function (key) { self.$watch(key, function () { self.queueSave(); }); });
      },

      color: function (key) {
        var index = this.signers.findIndex(function (s) { return s.key === key; });
        return this.colors[(index < 0 ? 0 : index) % this.colors.length];
      },
      signerLabel: function (key) {
        var index = this.signers.findIndex(function (s) { return s.key === key; });
        var s = this.signers[index];
        return s && s.name ? s.name : 'Signataire ' + (index + 1);
      },
      addSigner: function (client) {
        var key = 'n' + (this.nextKey++);
        this.signers.push({ key: key, name: client ? client.name : '', email: client ? client.email : '', client_id: client ? client.id : null });
        this.active = key;
        this.queueSave();
      },
      pickClient: function (signer, id) {
        var client = this.clients.find(function (c) { return String(c.id) === String(id); });
        if (!client) return;
        signer.name = client.name; signer.email = client.email; signer.client_id = client.id;
        this.queueSave();
      },
      removeSigner: function (key) {
        if (this.signers.length <= 1) return;
        this.signers = this.signers.filter(function (s) { return s.key !== key; });
        this.fields = this.fields.filter(function (f) { return f.signer !== key; });
        if (this.active === key) this.active = this.signers[0].key;
        this.queueSave();
      },
      fieldCount: function (key) { return this.fields.filter(function (f) { return f.signer === key; }).length; },

      startPlacing: function (kind) { this.placing = this.placing === kind ? null : kind; this.selected = null; },
      dragKind: function (e, kind) { e.dataTransfer.setData('text/plain', kind); e.dataTransfer.effectAllowed = 'copy'; },
      addField: function (kind, page, cx, cy) {
        var dims = this.pages[page];
        var size = DEFAULT_SIZE[kind];
        var w = Math.min(size[0] / dims[0], 1), h = Math.min(size[1] / dims[1], 1);
        var field = {
          uid: 'f' + (this.nextUid++), signer: this.active, kind: kind, page: page,
          x: Math.min(Math.max(cx - w / 2, 0), 1 - w), y: Math.min(Math.max(cy - h / 2, 0), 1 - h), w: w, h: h,
          required: kind !== 'checkbox', label: ''
        };
        this.fields.push(field);
        this.selected = field.uid;
        this.queueSave();
      },
      pageClick: function (e, page) {
        if (!this.placing) { this.selected = null; return; }
        var rect = e.currentTarget.getBoundingClientRect();
        this.addField(this.placing, page, (e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height);
        this.placing = null;
      },
      pageDrop: function (e, page) {
        var kind = e.dataTransfer.getData('text/plain');
        if (!DEFAULT_SIZE[kind]) return;
        var rect = e.currentTarget.getBoundingClientRect();
        this.addField(kind, page, (e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height);
      },
      pageFields: function (page) { return this.fields.filter(function (f) { return f.page === page; }); },
      fieldStyle: function (f) {
        var c = this.color(f.signer);
        return 'left:' + (f.x * 100) + '%;top:' + (f.y * 100) + '%;width:' + (f.w * 100) + '%;height:' + (f.h * 100) + '%;' +
          '--sg-color:' + c + ';';
      },
      current: function () { var uid = this.selected; return this.fields.find(function (f) { return f.uid === uid; }) || null; },
      removeField: function (uid) {
        this.fields = this.fields.filter(function (f) { return f.uid !== uid; });
        if (this.selected === uid) this.selected = null;
        this.queueSave();
      },

      startDrag: function (e, f, mode) {
        e.preventDefault(); e.stopPropagation();
        this.selected = f.uid;
        var rect = e.target.closest('.sg-page-inner').getBoundingClientRect();
        this.drag = { uid: f.uid, mode: mode, sx: e.clientX, sy: e.clientY, x: f.x, y: f.y, w: f.w, h: f.h, pw: rect.width, ph: rect.height, moved: false };
      },
      onMove: function (e) {
        var d = this.drag;
        if (!d) return;
        var f = this.fields.find(function (x) { return x.uid === d.uid; });
        if (!f) return;
        var dx = (e.clientX - d.sx) / d.pw, dy = (e.clientY - d.sy) / d.ph;
        if (Math.abs(e.clientX - d.sx) + Math.abs(e.clientY - d.sy) > 2) d.moved = true;
        if (d.mode === 'move') {
          f.x = Math.min(Math.max(d.x + dx, 0), 1 - f.w);
          f.y = Math.min(Math.max(d.y + dy, 0), 1 - f.h);
        } else {
          f.w = Math.min(Math.max(d.w + dx, 0.02), 1 - f.x);
          f.h = Math.min(Math.max(d.h + dy, 0.008), 1 - f.y);
          if (f.kind === 'checkbox') { var ratio = this.pages[f.page][0] / this.pages[f.page][1]; f.h = f.w * ratio; }
        }
      },
      endDrag: function () {
        if (this.drag && this.drag.moved) this.queueSave();
        this.drag = null;
      },

      payload: function (send) {
        return {
          title: this.title, message: this.message, in_order: this.inOrder, valid_days: this.validDays, send: !!send,
          signers: this.signers.map(function (s) { return { key: s.key, name: s.name, email: s.email, client_id: s.client_id }; }),
          fields: this.fields.map(function (f) {
            return { signer: f.signer, kind: f.kind, page: f.page, x: f.x, y: f.y, w: f.w, h: f.h, required: f.required, label: f.label };
          })
        };
      },
      queueSave: function () {
        var self = this;
        clearTimeout(this.timer);
        this.timer = setTimeout(function () { self.save(); }, 700);
      },
      save: function () {
        var self = this;
        clearTimeout(this.timer);
        this.saving = true;
        return postJSON(urls.save, this.payload(false)).then(function (data) {
          self.saving = false;
          if (data.ok) { self.error = ''; self.problems = data.problems || []; self.savedAt = new Date().toLocaleTimeString().slice(0, 5); }
          else self.error = data.error || 'Enregistrement impossible.';
          return data;
        }).catch(function () { self.saving = false; self.error = 'Connexion perdue : modifications non enregistrées.'; });
      },
      send: function () {
        var self = this;
        clearTimeout(this.timer);
        this.sending = true; this.error = '';
        postJSON(urls.save, this.payload(true)).then(function (data) {
          if (data.ok && data.next) { window.location.href = data.next; return; }
          self.sending = false;
          self.error = data.error || data.message || 'Envoi impossible.';
          if (data.upgrade_url) self.upgradeUrl = data.upgrade_url;
        }).catch(function () { self.sending = false; self.error = 'Connexion perdue.'; });
      },
      upgradeUrl: ''
    };
  };

  /* ------------------------------------------------------------------ */
  /* Page du signataire                                                  */
  /* ------------------------------------------------------------------ */
  window.sgSign = function (initial, urls) {
    var today = new Date();
    var todayText = ('0' + today.getDate()).slice(-2) + '/' + ('0' + (today.getMonth() + 1)).slice(-2) + '/' + today.getFullYear();
    return {
      pages: initial.pages, fields: initial.fields, others: initial.others, name: initial.name,
      values: {}, loading: true, consent: false, busy: false, error: '', done: false,
      modal: null, tab: 'draw', typed: initial.name, font: 'Dancing Script', pad: null, kept: { signature: '', initials: '' },
      declineOpen: false, reason: '', declined: false, fonts: ['Dancing Script', 'Caveat', 'Great Vibes'],

      init: function () {
        var self = this;
        this.fields.forEach(function (f) {
          if (f.kind === 'date') self.values[f.id] = todayText;
          else if (f.kind === 'name') self.values[f.id] = self.name;
          else if (f.kind === 'checkbox') self.values[f.id] = false;
          else self.values[f.id] = '';
        });
        if (!this.$refs.pages) return;
        this.$nextTick(function () {
          renderPdf(urls.pdf, self.$refs.pages).then(function () { self.loading = false; })
            .catch(function () { self.loading = false; self.error = 'Le document n’a pas pu être affiché. Rechargez la page.'; });
        });
      },
      pageFields: function (page) { return this.fields.filter(function (f) { return f.page === page; }); },
      pageOthers: function (page) { return this.others.filter(function (f) { return f.page === page && f.value; }); },
      box: function (f) { return 'left:' + (f.x * 100) + '%;top:' + (f.y * 100) + '%;width:' + (f.w * 100) + '%;height:' + (f.h * 100) + '%;'; },
      textSize: function (f) {
        var el = this.$refs.pages && this.$refs.pages.querySelector('.sg-page-inner');
        var width = el ? el.clientWidth : 800;
        var px = f.h * this.pages[f.page][1] * (width / this.pages[f.page][0]) * 0.62;
        return 'font-size:' + Math.max(8, Math.min(px, 18)) + 'px;';
      },
      filled: function (f) { var v = this.values[f.id]; return f.kind === 'checkbox' ? v === true : !!v; },
      missing: function () { var self = this; return this.fields.filter(function (f) { return f.required && !self.filled(f); }); },
      progress: function () { var self = this; return this.fields.filter(function (f) { return self.filled(f); }).length; },
      next: function () {
        var todo = this.missing()[0];
        if (!todo) return;
        var el = document.getElementById('sg-field-' + todo.id);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          if (todo.kind === 'signature' || todo.kind === 'initials') this.open(todo);
          else { var input = el.querySelector('input'); if (input) setTimeout(function () { input.focus(); }, 300); }
        }
      },

      open: function (f) {
        var self = this;
        this.modal = f;
        this.tab = 'draw'; this.modalError = ''; this.uploaded = '';
        this.typed = f.kind === 'initials' ? this.name.split(/\s+/).map(function (p) { return p.charAt(0).toUpperCase(); }).join('') : this.name;
        this.$nextTick(function () {
          if (!self.pad) self.pad = new Pad(self.$refs.pad);
          self.pad.size();
        });
      },
      apply: function () {
        var self = this, f = this.modal;
        var done = function (png) {
          if (!png) { self.modalError = f.kind === 'initials' ? 'Tracez vos initiales.' : 'Tracez votre signature.'; return; }
          self.modalError = '';
          self.kept[f.kind] = png;
          // La même signature remplit les autres champs du même type encore vides.
          self.fields.forEach(function (other) { if (other.kind === f.kind && (other.id === f.id || !self.values[other.id])) self.values[other.id] = png; });
          self.modal = null;
        };
        if (this.tab === 'draw') {
          done(this.pad && !this.pad.isEmpty() ? trimmedPng(this.pad.canvas) : '');
        } else if (this.tab === 'type') {
          var text = (this.typed || '').trim();
          if (!text) { this.modalError = 'Écrivez votre nom.'; return; }
          var font = this.font;
          (document.fonts ? document.fonts.load('96px "' + font + '"') : Promise.resolve()).then(function () { done(typedPng(text, font)); });
        } else if (this.tab === 'upload') {
          done(this.uploaded || '');
        }
      },
      modalError: '', uploaded: '',
      upload: function (e) {
        var self = this, file = e.target.files[0];
        if (!file) return;
        imagePng(file).then(function (png) { self.uploaded = png; }).catch(function () { self.modalError = 'Image illisible.'; });
      },
      reuse: function () { this.values[this.modal.id] = this.kept[this.modal.kind]; this.modal = null; },
      clearPad: function () { if (this.pad) this.pad.clear(); },

      submit: function () {
        var self = this;
        this.error = '';
        if (this.missing().length) { this.error = 'Il reste des champs à remplir.'; this.next(); return; }
        if (!this.consent) { this.error = 'Cochez la case d’accord pour signer électroniquement.'; return; }
        this.busy = true;
        postJSON(urls.submit, { consent: true, values: this.values }).then(function (data) {
          if (data.ok) { window.location.reload(); return; }
          self.busy = false; self.error = data.error || 'Signature impossible.';
        }).catch(function () { self.busy = false; self.error = 'Connexion perdue : réessayez.'; });
      },
      decline: function () {
        var self = this;
        this.busy = true;
        postJSON(urls.decline, { reason: this.reason }).then(function (data) {
          if (data.ok) { window.location.reload(); return; }
          self.busy = false; self.error = data.error || 'Action impossible.'; self.declineOpen = false;
        }).catch(function () { self.busy = false; self.error = 'Connexion perdue : réessayez.'; });
      }
    };
  };
})();
