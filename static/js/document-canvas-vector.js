/* Tracés vectoriels de l'éditeur de documents : courbes de Bézier avec tangentes.
   Format stocké (shape « path ») : paths = [{ closed, nodes: [[x, y, inX, inY, outX, outY, smooth]] }]
   en coordonnées relatives à la boîte de l'élément (0–1), poignées en absolu dans le même repère.
   Rendu identique côté serveur : apps/documents/canvas_render.py (_path_d). Fonctions pures,
   sans état : l'interaction (plume, édition des points) vit dans document-canvas.js. */
(function () {
  'use strict';

  const EPS = 1e-6;
  const round4 = (v) => Math.round(v * 10000) / 10000;
  const fmt = (v) => (Math.round(v * 100) / 100).toString();

  // ------------------------------------------------------------------ nœuds
  // Nœud de travail : { x, y, ix, iy, ox, oy, smooth } (poignées absolues).
  const node = (x, y) => ({ x, y, ix: x, iy: y, ox: x, oy: y, smooth: false });

  function toStored(paths, w, h) {
    return paths.map((p) => ({
      closed: !!p.closed,
      nodes: p.nodes.map((n) => [round4(n.x / w), round4(n.y / h), round4(n.ix / w), round4(n.iy / h), round4(n.ox / w), round4(n.oy / h), n.smooth ? 1 : 0]),
    }));
  }
  function fromStored(paths, w, h) {
    return (paths || []).map((p) => ({
      closed: !!p.closed,
      nodes: (p.nodes || []).map((a) => ({ x: a[0] * w, y: a[1] * h, ix: a[2] * w, iy: a[3] * h, ox: a[4] * w, oy: a[5] * h, smooth: !!a[6] })),
    }));
  }

  // Attribut d de SVG pour des nœuds en px.
  function toD(paths) {
    return paths.filter((p) => p.nodes.length).map((p) => {
      const n = p.nodes;
      let d = `M${fmt(n[0].x)} ${fmt(n[0].y)}`;
      const seg = (a, b) => { d += `C${fmt(a.ox)} ${fmt(a.oy)} ${fmt(b.ix)} ${fmt(b.iy)} ${fmt(b.x)} ${fmt(b.y)}`; };
      for (let i = 1; i < n.length; i += 1) seg(n[i - 1], n[i]);
      if (p.closed && n.length > 1) { seg(n[n.length - 1], n[0]); d += 'Z'; }
      return d;
    }).join('');
  }

  // Segments [p0, c1, c2, p3] d'un sous-tracé.
  function segments(p) {
    const out = [];
    const n = p.nodes;
    const count = p.closed ? n.length : n.length - 1;
    for (let i = 0; i < count; i += 1) {
      const a = n[i]; const b = n[(i + 1) % n.length];
      out.push({ i, j: (i + 1) % n.length, pts: [[a.x, a.y], [a.ox, a.oy], [b.ix, b.iy], [b.x, b.y]] });
    }
    return out;
  }

  function cubicAt(pts, t) {
    const u = 1 - t;
    const [p0, p1, p2, p3] = pts;
    return [
      u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
      u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
    ];
  }

  // Boîte englobante exacte (extrema des cubiques), pas celle des poignées.
  function bounds(paths) {
    let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
    const add = (x, y) => { if (x < x0) x0 = x; if (y < y0) y0 = y; if (x > x1) x1 = x; if (y > y1) y1 = y; };
    paths.forEach((p) => {
      p.nodes.forEach((n) => add(n.x, n.y));
      segments(p).forEach(({ pts }) => {
        [0, 1].forEach((k) => {
          const a = -pts[0][k] + 3 * pts[1][k] - 3 * pts[2][k] + pts[3][k];
          const b = 2 * (pts[0][k] - 2 * pts[1][k] + pts[2][k]);
          const c = pts[1][k] - pts[0][k];
          const roots = [];
          if (Math.abs(a) < EPS) { if (Math.abs(b) > EPS) roots.push(-c / b); } else {
            const disc = b * b - 4 * a * c;
            if (disc >= 0) { const s = Math.sqrt(disc); roots.push((-b + s) / (2 * a), (-b - s) / (2 * a)); }
          }
          roots.filter((t) => t > 0 && t < 1).forEach((t) => { const q = cubicAt(pts, t); add(q[0], q[1]); });
        });
      });
    });
    if (x0 === Infinity) return { x: 0, y: 0, w: 0, h: 0 };
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  function mapPaths(paths, fn) {
    return paths.map((p) => ({
      closed: p.closed,
      nodes: p.nodes.map((n) => {
        const a = fn(n.x, n.y); const i = fn(n.ix, n.iy); const o = fn(n.ox, n.oy);
        return { x: a[0], y: a[1], ix: i[0], iy: i[1], ox: o[0], oy: o[1], smooth: n.smooth };
      }),
    }));
  }
  const translate = (paths, dx, dy) => mapPaths(paths, (x, y) => [x + dx, y + dy]);

  // Coupe un segment en t (de Casteljau) : renvoie le nœud inséré et les poignées voisines.
  function split(pts, t) {
    const lerp = (a, b) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    const [p0, p1, p2, p3] = pts;
    const a = lerp(p0, p1); const b = lerp(p1, p2); const c = lerp(p2, p3);
    const d = lerp(a, b); const e = lerp(b, c); const f = lerp(d, e);
    return { prevOut: a, nodeIn: d, node: f, nodeOut: e, nextIn: c };
  }

  // Paramètre t du point du segment le plus proche de (x, y).
  function nearestT(pts, x, y) {
    let best = 0; let bestD = Infinity;
    for (let i = 0; i <= 60; i += 1) {
      const t = i / 60; const q = cubicAt(pts, t); const d = (q[0] - x) ** 2 + (q[1] - y) ** 2;
      if (d < bestD) { bestD = d; best = t; }
    }
    let step = 1 / 120;
    for (let k = 0; k < 12; k += 1) {
      [best - step, best + step].forEach((t) => {
        if (t < 0 || t > 1) return;
        const q = cubicAt(pts, t); const d = (q[0] - x) ** 2 + (q[1] - y) ** 2;
        if (d < bestD) { bestD = d; best = t; }
      });
      step /= 2;
    }
    return { t: best, dist: Math.sqrt(bestD) };
  }

  // Nœud lisse : tangentes calculées depuis les voisins (Catmull-Rom).
  function smoothNode(p, i, tension = 1 / 6) {
    const n = p.nodes; const cur = n[i];
    const prev = n[i - 1] || (p.closed ? n[n.length - 1] : null);
    const next = n[i + 1] || (p.closed ? n[0] : null);
    if (!prev && !next) return;
    const a = prev || cur; const b = next || cur;
    let dx = (b.x - a.x) * tension * (prev && next ? 1 : 2); let dy = (b.y - a.y) * tension * (prev && next ? 1 : 2);
    if (Math.abs(dx) < EPS && Math.abs(dy) < EPS) { dx = 0; dy = 0; }
    cur.ix = prev ? cur.x - dx : cur.x; cur.iy = prev ? cur.y - dy : cur.y;
    cur.ox = next ? cur.x + dx : cur.x; cur.oy = next ? cur.y + dy : cur.y;
    cur.smooth = true;
  }
  function cornerNode(nd) { nd.ix = nd.x; nd.iy = nd.y; nd.ox = nd.x; nd.oy = nd.y; nd.smooth = false; }

  // Marque lisses les nœuds dont les deux poignées sont opposées (import, formes prêtes).
  function detectSmooth(paths) {
    paths.forEach((p) => p.nodes.forEach((n) => {
      const ax = n.ix - n.x; const ay = n.iy - n.y; const bx = n.ox - n.x; const by = n.oy - n.y;
      const la = Math.hypot(ax, ay); const lb = Math.hypot(bx, by);
      n.smooth = la > 0.01 && lb > 0.01 && (ax * bx + ay * by) / (la * lb) < -0.995;
    }));
    return paths;
  }

  // ------------------------------------------------------------------ lecture de l'attribut d
  function arcToCubics(x1, y1, rx, ry, phi, large, sweep, x2, y2) {
    // Conversion arc elliptique → cubiques (SVG 1.1, annexe F.6.5).
    if (rx === 0 || ry === 0) return [[x1, y1, x2, y2, x2, y2]];
    const sin = Math.sin(phi); const cos = Math.cos(phi);
    const dx = (x1 - x2) / 2; const dy = (y1 - y2) / 2;
    const x1p = cos * dx + sin * dy; const y1p = -sin * dx + cos * dy;
    rx = Math.abs(rx); ry = Math.abs(ry);
    const lambda = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry);
    if (lambda > 1) { rx *= Math.sqrt(lambda); ry *= Math.sqrt(lambda); }
    const num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p;
    const den = rx * rx * y1p * y1p + ry * ry * x1p * x1p;
    let coef = Math.sqrt(Math.max(0, num / den));
    if (large === sweep) coef = -coef;
    const cxp = (coef * rx * y1p) / ry; const cyp = (-coef * ry * x1p) / rx;
    const cx = cos * cxp - sin * cyp + (x1 + x2) / 2; const cy = sin * cxp + cos * cyp + (y1 + y2) / 2;
    const ang = (ux, uy, vx, vy) => {
      const a = Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
      return a;
    };
    let t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry);
    let dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry);
    if (!sweep && dt > 0) dt -= 2 * Math.PI;
    if (sweep && dt < 0) dt += 2 * Math.PI;
    const parts = Math.max(1, Math.ceil(Math.abs(dt) / (Math.PI / 2)));
    const step = dt / parts;
    const k = (4 / 3) * Math.tan(step / 4);
    const out = [];
    const pt = (t) => [cx + rx * Math.cos(t) * cos - ry * Math.sin(t) * sin, cy + rx * Math.cos(t) * sin + ry * Math.sin(t) * cos];
    const der = (t) => [-rx * Math.sin(t) * cos - ry * Math.cos(t) * sin, -rx * Math.sin(t) * sin + ry * Math.cos(t) * cos];
    for (let i = 0; i < parts; i += 1) {
      const a = t1; const b = t1 + step;
      const pa = pt(a); const pb = pt(b); const da = der(a); const db = der(b);
      out.push([pa[0] + k * da[0], pa[1] + k * da[1], pb[0] - k * db[0], pb[1] - k * db[1], pb[0], pb[1]]);
      t1 = b;
    }
    return out;
  }

  function parseD(d) {
    const tokens = String(d || '').match(/[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g) || [];
    const paths = [];
    let i = 0; let cmd = ''; let cur = null;
    let x = 0; let y = 0; let sx = 0; let sy = 0;
    let lastC = null; let lastQ = null;
    const isCmd = (t) => /^[a-z]$/i.test(t);
    const numv = () => parseFloat(tokens[i++]);
    const flag = () => {
      // Les drapeaux d'arc peuvent être collés (« 0 01 » ou « 1110 ») : on les lit chiffre par chiffre.
      const t = tokens[i];
      if (t.length > 1 && /^[01]/.test(t)) { tokens[i] = t.slice(1); return t[0] === '1'; }
      i += 1; return t === '1';
    };
    const start = () => { cur = { closed: false, nodes: [node(x, y)] }; paths.push(cur); };
    const cubic = (c1x, c1y, c2x, c2y, ex, ey) => {
      if (!cur) start();
      const last = cur.nodes[cur.nodes.length - 1];
      last.ox = c1x; last.oy = c1y;
      const n = node(ex, ey); n.ix = c2x; n.iy = c2y;
      cur.nodes.push(n);
      x = ex; y = ey;
    };
    const line = (ex, ey) => cubic(x, y, ex, ey, ex, ey);
    while (i < tokens.length) {
      if (isCmd(tokens[i])) cmd = tokens[i++];
      else if (!cmd) { i += 1; continue; }
      const rel = cmd === cmd.toLowerCase();
      const C = cmd.toUpperCase();
      const ox = rel ? x : 0; const oy = rel ? y : 0;
      try {
        if (C === 'Z') {
          if (cur && cur.nodes.length > 1) {
            const first = cur.nodes[0]; const last = cur.nodes[cur.nodes.length - 1];
            if (Math.abs(first.x - last.x) < 1e-3 && Math.abs(first.y - last.y) < 1e-3) {
              first.ix = last.ix; first.iy = last.iy; cur.nodes.pop();
            }
            cur.closed = true;
          }
          x = sx; y = sy; cur = null; lastC = null; lastQ = null;
          continue;
        }
        if (i >= tokens.length || isCmd(tokens[i])) continue;
        if (C === 'M') {
          x = ox + numv(); y = oy + numv(); sx = x; sy = y; start();
          cmd = rel ? 'l' : 'L'; lastC = null; lastQ = null;
        } else if (C === 'L') { line(ox + numv(), oy + numv()); lastC = null; lastQ = null; }
        else if (C === 'H') { line(ox + numv(), y); lastC = null; lastQ = null; }
        else if (C === 'V') { line(x, (rel ? y : 0) + numv()); lastC = null; lastQ = null; }
        else if (C === 'C') {
          const a = [ox + numv(), oy + numv(), ox + numv(), oy + numv(), ox + numv(), oy + numv()];
          cubic(...a); lastC = [a[2], a[3]]; lastQ = null;
        } else if (C === 'S') {
          const c1 = lastC ? [2 * x - lastC[0], 2 * y - lastC[1]] : [x, y];
          const a = [ox + numv(), oy + numv(), ox + numv(), oy + numv()];
          cubic(c1[0], c1[1], ...a); lastC = [a[0], a[1]]; lastQ = null;
        } else if (C === 'Q' || C === 'T') {
          let q;
          if (C === 'Q') q = [ox + numv(), oy + numv()];
          else q = lastQ ? [2 * x - lastQ[0], 2 * y - lastQ[1]] : [x, y];
          const ex = ox + numv(); const ey = oy + numv();
          cubic(x + (2 / 3) * (q[0] - x), y + (2 / 3) * (q[1] - y), ex + (2 / 3) * (q[0] - ex), ey + (2 / 3) * (q[1] - ey), ex, ey);
          lastQ = q; lastC = null;
        } else if (C === 'A') {
          const rx = numv(); const ry = numv(); const rot = (numv() * Math.PI) / 180;
          const large = flag(); const sweep = flag();
          const ex = ox + numv(); const ey = oy + numv();
          arcToCubics(x, y, rx, ry, rot, large, sweep, ex, ey).forEach((c) => cubic(...c));
          lastC = null; lastQ = null;
        } else { i += 1; }
      } catch (err) { break; }
      if ([x, y].some((v) => !Number.isFinite(v))) break;
    }
    return detectSmooth(paths.filter((p) => p.nodes.length > 1));
  }

  // ------------------------------------------------------------------ formes de base → tracés
  function primitiveD(tag, a) {
    const n = (k) => parseFloat(a(k)) || 0;
    switch (tag) {
      case 'path': return a('d') || '';
      case 'rect': {
        const x = n('x'); const y = n('y'); const w = n('width'); const h = n('height');
        let rx = a('rx') != null ? n('rx') : (a('ry') != null ? n('ry') : 0);
        let ry = a('ry') != null ? n('ry') : rx;
        rx = Math.min(rx, w / 2); ry = Math.min(ry, h / 2);
        if (!rx || !ry) return `M${x} ${y}H${x + w}V${y + h}H${x}Z`;
        return `M${x + rx} ${y}H${x + w - rx}A${rx} ${ry} 0 0 1 ${x + w} ${y + ry}V${y + h - ry}A${rx} ${ry} 0 0 1 ${x + w - rx} ${y + h}H${x + rx}A${rx} ${ry} 0 0 1 ${x} ${y + h - ry}V${y + ry}A${rx} ${ry} 0 0 1 ${x + rx} ${y}Z`;
      }
      case 'circle': case 'ellipse': {
        const cx = n('cx'); const cy = n('cy');
        const rx = tag === 'circle' ? n('r') : n('rx'); const ry = tag === 'circle' ? n('r') : n('ry');
        return `M${cx - rx} ${cy}A${rx} ${ry} 0 1 0 ${cx + rx} ${cy}A${rx} ${ry} 0 1 0 ${cx - rx} ${cy}Z`;
      }
      case 'line': return `M${n('x1')} ${n('y1')}L${n('x2')} ${n('y2')}`;
      case 'polyline': case 'polygon': {
        const pts = (a('points') || '').trim().split(/[\s,]+/).map(parseFloat).filter((v) => Number.isFinite(v));
        if (pts.length < 4) return '';
        let d = `M${pts[0]} ${pts[1]}`;
        for (let k = 2; k + 1 < pts.length; k += 2) d += `L${pts[k]} ${pts[k + 1]}`;
        return tag === 'polygon' ? `${d}Z` : d;
      }
      default: return '';
    }
  }

  // Formes simples de l'éditeur converties en tracé modifiable.
  function shapeToPaths(shape, w, h, radius = 0) {
    const attrs = {
      rect: { tag: 'rect', a: { x: 0, y: 0, width: w, height: h, rx: Math.min(radius, w / 2, h / 2) } },
      ellipse: { tag: 'ellipse', a: { cx: w / 2, cy: h / 2, rx: w / 2, ry: h / 2 } },
      triangle: { tag: 'polygon', a: { points: `${w / 2},0 ${w},${h} 0,${h}` } },
      diamond: { tag: 'polygon', a: { points: `${w / 2},0 ${w},${h / 2} ${w / 2},${h} 0,${h / 2}` } },
      line: { tag: 'line', a: { x1: 0, y1: h / 2, x2: w, y2: h / 2 } },
      arrow: { tag: 'line', a: { x1: 0, y1: h / 2, x2: w, y2: h / 2 } },
    }[shape];
    if (shape === 'star') {
      const pts = [];
      const outer = Math.min(w, h) / 2; const inner = outer * 0.45;
      for (let i = 0; i < 10; i += 1) {
        const r = i % 2 === 0 ? outer : inner; const ang = (Math.PI / 5) * i - Math.PI / 2;
        pts.push(`${w / 2 + r * Math.cos(ang)},${h / 2 + r * Math.sin(ang)}`);
      }
      return parseD(primitiveD('polygon', (k) => (k === 'points' ? pts.join(' ') : null)));
    }
    if (!attrs) return [];
    return parseD(primitiveD(attrs.tag, (k) => (attrs.a[k] !== undefined ? String(attrs.a[k]) : null)));
  }

  // ------------------------------------------------------------------ formes prêtes (boîte 100 × 100)
  const PRESETS = {
    heart: { label: 'Cœur', d: 'M50 88C22 68 6 52 6 32C6 17 17 7 30 7C39 7 46 12 50 20C54 12 61 7 70 7C83 7 94 17 94 32C94 52 78 68 50 88Z', fill: '#f43f5e' },
    cloud: { label: 'Nuage', d: 'M26 78C14 78 6 70 6 59C6 49 13 42 23 41C24 27 35 17 49 17C61 17 71 25 74 36C86 36 95 45 95 57C95 69 86 78 74 78Z', fill: '#e0f2fe' },
    bubble: { label: 'Bulle de dialogue', d: 'M18 10H82C89 10 94 15 94 22V60C94 67 89 72 82 72H44L24 90L28 72H18C11 72 6 67 6 60V22C6 15 11 10 18 10Z', fill: '#ede9fe' },
    blob: { label: 'Forme organique', d: 'M52 6C70 5 89 16 93 35C97 54 87 69 74 81C61 93 40 97 25 87C10 77 3 60 7 43C11 25 33 7 52 6Z', fill: '#c7d2fe' },
    wave: { label: 'Vague', d: 'M0 40C17 22 33 22 50 40C67 58 83 58 100 40V100H0Z', fill: '#6d28d9', w: 300, h: 90 },
    leaf: { label: 'Feuille', d: 'M10 90C10 45 40 10 90 10C90 60 55 90 10 90Z', fill: '#86efac' },
    drop: { label: 'Goutte', d: 'M50 4C50 4 16 44 16 64C16 83 31 96 50 96C69 96 84 83 84 64C84 44 50 4 50 4Z', fill: '#38bdf8' },
    badge: { label: 'Sceau', d: 'M50 3L59 12L71 8L75 20L88 22L86 35L96 44L88 54L94 66L82 72L82 85L69 84L62 95L50 89L38 95L31 84L18 85L18 72L6 66L12 54L4 44L14 35L12 22L25 20L29 8L41 12Z', fill: '#fbbf24' },
    sparkle: { label: 'Éclat', d: 'M50 2C53 33 67 47 98 50C67 53 53 67 50 98C47 67 33 53 2 50C33 47 47 33 50 2Z', fill: '#a78bfa' },
    moon: { label: 'Croissant', d: 'M62 6C40 10 24 29 24 52C24 75 40 92 62 96C38 100 8 82 8 51C8 21 36 1 62 6Z', fill: '#fde68a' },
    curvedArrow: { label: 'Flèche courbe', d: 'M10 80C14 42 42 20 76 22L74 10L96 30L72 48L74 36C48 36 28 52 22 82Z', fill: '#111827' },
    ribbon: { label: 'Ruban', d: 'M0 20H18V8H82V20H100L88 38L100 56H82V68H18V56H0L12 38Z', fill: '#6d28d9', w: 260, h: 120 },
    squiggle: { label: 'Trait libre', d: 'M4 60C16 30 28 30 36 50C44 70 56 70 64 48C72 26 84 26 96 44', fill: 'transparent', stroke: '#6d28d9', strokeWidth: 4, w: 240, h: 80 },
  };

  // ------------------------------------------------------------------ import SVG
  // Résout les couleurs (styles CSS, dégradés) et les transformations via le navigateur :
  // le SVG est monté hors écran, puis seuls des tracés et des couleurs sont gardés (rien d'autre n'est copié).
  function importSvg(text, { maxShapes = 150 } = {}) {
    const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
    const src = doc.documentElement;
    if (!src || src.nodeName.toLowerCase() !== 'svg' || doc.querySelector('parsererror')) throw new Error('Fichier SVG illisible.');
    src.querySelectorAll('script, foreignObject, image, use[href^="http"], use[*|href^="http"]').forEach((n) => n.remove());
    src.querySelectorAll('*').forEach((n) => Array.from(n.attributes).forEach((at) => { if (/^on/i.test(at.name)) n.removeAttribute(at.name); }));
    const host = document.createElement('div');
    host.style.cssText = 'position:absolute;left:-10000px;top:0;width:0;height:0;overflow:hidden;opacity:0;pointer-events:none';
    const svg = document.importNode(src, true);
    if (!svg.getAttribute('width') && !svg.getAttribute('viewBox')) svg.setAttribute('width', '600');
    host.appendChild(svg);
    document.body.appendChild(host);
    try {
      const shapes = [];
      const skip = 'defs, clipPath, mask, symbol, marker, pattern, linearGradient, radialGradient';
      const els = Array.from(svg.querySelectorAll('path, rect, circle, ellipse, line, polyline, polygon'))
        .filter((el) => !el.closest(skip));
      for (const el of els) {
        if (shapes.length >= maxShapes) break;
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        const tag = el.nodeName.toLowerCase();
        let paths = parseD(primitiveD(tag, (k) => el.getAttribute(k)));
        if (!paths.length) continue;
        const m = el.getCTM && el.getCTM();
        if (m) paths = mapPaths(paths, (x, y) => [m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f]);
        const scale = m ? Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) || 1 : 1;
        const paint = (value, opacity) => {
          if (!value || value === 'none') return { color: 'transparent' };
          const ref = value.match(/url\(["']?#([^"')]+)["']?\)/);
          if (ref) {
            const grad = svg.querySelector(`[id="${CSS.escape(ref[1])}"]`);
            const stops = grad ? Array.from(grad.querySelectorAll('stop')) : [];
            if (!stops.length) return { color: '#9ca3af' };
            const col = (s) => colorWithOpacity(getComputedStyle(s).stopColor, parseFloat(getComputedStyle(s).stopOpacity || '1') * opacity);
            const x1 = parseFloat(grad.getAttribute('x1') || '0'); const y1 = parseFloat(grad.getAttribute('y1') || '0');
            const x2 = parseFloat(grad.getAttribute('x2') || (grad.nodeName === 'linearGradient' ? '1' : '0'));
            const y2 = parseFloat(grad.getAttribute('y2') || '0');
            const angle = grad.nodeName === 'linearGradient' ? Math.round(((Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI + 360) % 360) : 90;
            return { color: col(stops[0]), color2: stops.length > 1 ? col(stops[stops.length - 1]) : '', angle };
          }
          return { color: colorWithOpacity(value, opacity) };
        };
        const fill = paint(cs.fill, parseFloat(cs.fillOpacity || '1'));
        const strokeW = cs.stroke && cs.stroke !== 'none' ? parseFloat(cs.strokeWidth || '1') * scale : 0;
        const stroke = paint(cs.stroke, parseFloat(cs.strokeOpacity || '1'));
        if (fill.color === 'transparent' && !strokeW) continue;
        shapes.push({
          paths,
          style: {
            fill: fill.color, fill2: fill.color2 || '', gradientAngle: fill.angle || 0,
            strokeColor: stroke.color === 'transparent' ? '#111827' : stroke.color,
            strokeWidth: Math.round(Math.min(40, strokeW) * 100) / 100,
            fillRule: cs.fillRule === 'evenodd' ? 'evenodd' : 'nonzero',
            opacity: Math.max(0.05, Math.min(1, parseFloat(cs.opacity || '1'))),
          },
        });
      }
      return shapes;
    } finally {
      host.remove();
    }
  }

  // « rgb(…) » du navigateur → rgba avec l'opacité du remplissage (format accepté par le serveur).
  function colorWithOpacity(value, opacity) {
    const m = String(value).match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+%?))?\s*\)/);
    if (!m) return /^#[0-9a-f]{3,8}$/i.test(value) ? value : '#111827';
    let alpha = m[4] === undefined ? 1 : (m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
    alpha *= Number.isFinite(opacity) ? opacity : 1;
    const [r, g, b] = [m[1], m[2], m[3]].map((v) => Math.round(parseFloat(v)));
    if (alpha >= 0.999) return `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`;
    return `rgba(${r}, ${g}, ${b}, ${Math.round(alpha * 100) / 100})`;
  }

  window.DcVector = {
    node, toStored, fromStored, toD, segments, cubicAt, bounds, mapPaths, translate, split, nearestT,
    smoothNode, cornerNode, detectSmooth, parseD, shapeToPaths, PRESETS, importSvg,
  };
})();
