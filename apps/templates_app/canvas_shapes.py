"""
Bibliothèque de formes décoratives des modèles libres (bandeaux, vagues, angles, taches…).

Chaque forme est un tracé SVG dans une boîte 100 × 100 étirée à la taille du bloc
(`preserveAspectRatio="none"`), sauf le rectangle, l'ellipse et le cadre qui sont dessinés à la
taille réelle (coins arrondis et épaisseur en pixels). Les mêmes définitions servent à l'éditeur
(JavaScript, via `editor_shapes()`), à l'aperçu et au PDF : le dessin est identique partout.
"""


def _dots():
    """Trame de points 5 × 5 (cercles tracés en arcs)."""
    parts = []
    for row in range(5):
        for col in range(5):
            cx, cy, r = 10 + col * 20, 10 + row * 20, 4
            parts.append(f'M{cx - r},{cy} a{r},{r} 0 1,0 {2 * r},0 a{r},{r} 0 1,0 {-2 * r},0 Z')
    return ' '.join(parts)


# clé : (libellé, tracé dans la boîte 100 × 100 ou None si dessiné à la taille réelle, taille par défaut)
SHAPES = {
    'rect': ('Rectangle', None, (220, 120)),
    'ellipse': ('Cercle', None, (140, 140)),
    'frame': ('Cadre', None, (794, 1120)),
    'line': ('Ligne', None, (300, 4)),
    'triangle': ('Angle', 'M0,0 H100 L0,100 Z', (260, 160)),
    'diagonal': ('Diagonale', 'M0,0 H100 V55 L0,100 Z', (794, 180)),
    'wave': ('Vague', 'M0,0 H100 V68 C82,96 62,52 42,70 C26,84 12,94 0,82 Z', (794, 160)),
    'wave_soft': ('Vague douce', 'M0,0 H100 V58 C72,100 34,38 0,86 Z', (794, 140)),
    'arc': ('Quart de cercle', 'M0,0 H100 A100,100 0 0 1 0,100 Z', (220, 220)),
    'blob': ('Tache', 'M52,3 C76,1 97,19 97,46 C97,74 80,97 50,97 C21,97 3,79 3,51 C3,24 26,5 52,3 Z', (200, 180)),
    'chevron': ('Chevron', 'M0,0 H72 L100,50 L72,100 H0 L28,50 Z', (160, 60)),
    'stripes': ('Rayures', 'M0,100 L32,0 H46 L14,100 Z M34,100 L66,0 H80 L48,100 Z M68,100 L100,0 V44 L82,100 Z', (220, 120)),
    'facets': ('Facettes', 'M100,0 V62 L64,28 Z M100,0 H52 L78,24 Z M64,28 L100,62 L58,70 Z M100,62 V100 H70 Z M40,0 H52 L64,28 L30,18 Z',
               (300, 260)),
    'ring': ('Anneau', 'M50,0 A50,50 0 1 0 50.01,0 Z M50,16 A34,34 0 1 1 49.99,16 Z', (160, 160)),
    'dots': ('Points', _dots(), (120, 120)),
    'pill': ('Pastille', None, (220, 56)),
}
DEFAULT_SHAPE = 'rect'


def svg(block, fill, fill2=None):
    """
    Dessin SVG d'un bloc forme. `fill` / `fill2` sont des couleurs déjà résolues (le gabarit peut
    contenir {{ accent_color }}). Dégradé si `block['gradient']` et une seconde couleur.
    """
    w, h = block['w'], block['h']
    kind = block.get('shape') if block.get('shape') in SHAPES else DEFAULT_SHAPE
    opacity = f'{(block.get("opacity") or 100) / 100:.2f}'
    defs, paint = '', fill
    if block.get('gradient') and fill2:
        gid = f'g{block["id"]}'
        defs = (f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
                f'<stop offset="0" stop-color="{fill}"/><stop offset="1" stop-color="{fill2}"/></linearGradient></defs>')
        paint = f'url(#{gid})'
    attrs = f'fill="{paint}" fill-opacity="{opacity}"'
    path = SHAPES[kind][1]
    if path:
        transform = []
        if block.get('flip_x'):
            transform.append('translate(100,0) scale(-1,1)')
        if block.get('flip_y'):
            transform.append('translate(0,100) scale(1,-1)')
        rule = ' fill-rule="evenodd"' if kind == 'ring' else ''
        group = f'<g transform="{" ".join(transform)}">' if transform else '<g>'
        body = f'{group}<path d="{path}" {attrs}{rule}/></g>'
        box = 'viewBox="0 0 100 100" preserveAspectRatio="none"'
    else:
        box = f'viewBox="0 0 {w} {h}" preserveAspectRatio="none"'
        if kind == 'ellipse':
            body = f'<ellipse cx="{w / 2}" cy="{h / 2}" rx="{w / 2}" ry="{h / 2}" {attrs}/>'
        elif kind == 'frame':
            t = max(1, min(block.get('thickness') or 6, min(w, h) / 2))
            radius = min(block.get('radius') or 0, w / 2, h / 2)
            body = (f'<rect x="{t / 2}" y="{t / 2}" width="{w - t}" height="{h - t}" rx="{radius}" fill="none" '
                    f'stroke="{paint}" stroke-opacity="{opacity}" stroke-width="{t}"/>')
        else:  # rect, line, pill
            radius = h / 2 if kind == 'pill' else min(block.get('radius') or 0, h / 2, w / 2)
            body = f'<rect width="{w}" height="{h}" rx="{radius}" {attrs}/>'
    return (f'<svg width="{w}" height="{h}" {box} xmlns="http://www.w3.org/2000/svg" '
            f'style="display:block">{defs}{body}</svg>')


def editor_shapes():
    """Définitions envoyées à l'éditeur (même dessin côté navigateur)."""
    return [{'kind': key, 'label': spec[0], 'path': spec[1], 'w': spec[2][0], 'h': spec[2][1]} for key, spec in SHAPES.items()]
