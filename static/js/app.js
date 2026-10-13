// Billio Frontend JavaScript
// Global HTMX and Alpine.js configurations

/**
 * Liste pays + drapeaux (emoji) pour menus profil et formulaires.
 * Clé = libellé exact stocké en base (UserProfile.country).
 */
window.BILLIO_COUNTRY_OPTIONS = [
    { name: 'France', flag: '🇫🇷' },
    { name: 'Belgique', flag: '🇧🇪' },
    { name: 'Suisse', flag: '🇨🇭' },
    { name: 'Luxembourg', flag: '🇱🇺' },
    { name: 'Canada', flag: '🇨🇦' },
    { name: 'Maroc', flag: '🇲🇦' },
    { name: 'Sénégal', flag: '🇸🇳' },
    { name: "Côte d'Ivoire", flag: '🇨🇮' },
    { name: 'Tunisie', flag: '🇹🇳' },
    { name: 'Algérie', flag: '🇩🇿' },
    { name: 'Cameroun', flag: '🇨🇲' },
    { name: 'Allemagne', flag: '🇩🇪' },
    { name: 'Espagne', flag: '🇪🇸' },
    { name: 'Italie', flag: '🇮🇹' },
    { name: 'Portugal', flag: '🇵🇹' },
    { name: 'Pays-Bas', flag: '🇳🇱' },
    { name: 'Royaume-Uni', flag: '🇬🇧' },
    { name: 'États-Unis', flag: '🇺🇸' },
    { name: 'Brésil', flag: '🇧🇷' },
    { name: 'Mali', flag: '🇲🇱' },
    { name: 'Burkina Faso', flag: '🇧🇫' },
    { name: 'Gabon', flag: '🇬🇦' },
    { name: 'République démocratique du Congo', flag: '🇨🇩' },
    { name: 'Congo', flag: '🇨🇬' },
    { name: 'Madagascar', flag: '🇲🇬' },
    { name: 'Maurice', flag: '🇲🇺' },
    { name: 'Haïti', flag: '🇭🇹' },
    { name: 'Guadeloupe', flag: '🇬🇵' },
    { name: 'Martinique', flag: '🇲🇶' },
    { name: 'Guyane', flag: '🇬🇫' },
    { name: 'La Réunion', flag: '🇷🇪' },
];

window.countryFlagEmoji = function countryFlagEmoji(countryName) {
    if (!countryName || !String(countryName).trim()) return '🌍';
    const key = String(countryName).trim();
    const hit = window.BILLIO_COUNTRY_OPTIONS.find((c) => c.name === key);
    return hit ? hit.flag : '🌍';
};

// HTMX Configuration
document.addEventListener('DOMContentLoaded', function() {
    // Configure HTMX
    htmx.config.globalViewTransitions = true;
    htmx.config.useTemplateFragments = true;

    // Add CSRF token to all HTMX requests
    document.body.addEventListener('htmx:configRequest', function(evt) {
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');
        if (csrfToken) {
            evt.detail.headers['X-CSRFToken'] = csrfToken.value;
        }
    });

    // Handle HTMX errors
    document.body.addEventListener('htmx:responseError', function(evt) {
        console.error('HTMX Error:', evt.detail);
        showNotification('Une erreur est survenue. Veuillez réessayer.', 'error');
    });

    // Handle successful requests
    document.body.addEventListener('htmx:afterRequest', function(evt) {
        if (evt.detail.successful) {
            // Re-initialize Alpine components after HTMX swaps
            if (window.Alpine) {
                Alpine.initTree(document.body);
            }
        }
    });

    // Handle loading states
    document.body.addEventListener('htmx:beforeRequest', function(evt) {
        // Add loading indicators
        const target = evt.detail.target;
        if (target) {
            target.style.opacity = '0.7';
        }
    });

    document.body.addEventListener('htmx:afterRequest', function(evt) {
        const target = evt.detail.target;
        if (target) {
            target.style.opacity = '1';
        }
    });
});

// Notification system
function showNotification(message, type = 'info', duration = 5000) {
    // Remove existing notifications
    const existingNotifications = document.querySelectorAll('.notification');
    existingNotifications.forEach(notification => notification.remove());

    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification fixed top-4 right-4 z-50 p-4 rounded-md shadow-lg max-w-sm ${getNotificationClasses(type)}`;

    notification.innerHTML = `
        <div class="flex">
            <div class="flex-shrink-0">
                ${getNotificationIcon(type)}
            </div>
            <div class="ml-3">
                <p class="text-sm font-medium">${message}</p>
            </div>
            <div class="ml-auto pl-3">
                <button class="inline-flex rounded-md p-1.5 focus:outline-none focus:ring-2 focus:ring-offset-2 ${getNotificationCloseClasses(type)}" onclick="this.parentElement.parentElement.parentElement.remove()">
                    <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                    </svg>
                </button>
            </div>
        </div>
    `;

    // Add to page
    document.body.appendChild(notification);

    // Auto-remove after duration
    if (duration > 0) {
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, duration);
    }
}

function getNotificationClasses(type) {
    const classes = {
        'success': 'bg-green-50 border border-green-200 text-green-800',
        'error': 'bg-red-50 border border-red-200 text-red-800',
        'warning': 'bg-yellow-50 border border-yellow-200 text-yellow-800',
        'info': 'bg-blue-50 border border-blue-200 text-blue-800'
    };
    return classes[type] || classes.info;
}

function getNotificationIcon(type) {
    const icons = {
        'success': '<svg class="h-5 w-5 text-green-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" /></svg>',
        'error': '<svg class="h-5 w-5 text-red-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" /></svg>',
        'warning': '<svg class="h-5 w-5 text-yellow-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" /></svg>',
        'info': '<svg class="h-5 w-5 text-blue-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" /></svg>'
    };
    return icons[type] || icons.info;
}

function getNotificationCloseClasses(type) {
    const classes = {
        'success': 'text-green-400 hover:text-green-600 focus:ring-green-600',
        'error': 'text-red-400 hover:text-red-600 focus:ring-red-600',
        'warning': 'text-yellow-400 hover:text-yellow-600 focus:ring-yellow-600',
        'info': 'text-blue-400 hover:text-blue-600 focus:ring-blue-600'
    };
    return classes[type] || classes.info;
}

// Utility functions
function formatCurrency(amount, currency = 'EUR') {
    return new Intl.NumberFormat('fr-FR', {
        style: 'currency',
        currency: currency
    }).format(amount);
}

function formatDate(date, options = {}) {
    const defaultOptions = {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    };
    return new Date(date).toLocaleDateString('fr-FR', { ...defaultOptions, ...options });
}

// Modal management
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('hidden');
        document.body.classList.add('overflow-hidden');
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('hidden');
        document.body.classList.remove('overflow-hidden');
    }
}

// Form validation helpers
function validateForm(form) {
    const inputs = form.querySelectorAll('input, select, textarea');
    let isValid = true;

    inputs.forEach(input => {
        if (input.hasAttribute('required') && !input.value.trim()) {
            input.classList.add('border-red-500');
            isValid = false;
        } else {
            input.classList.remove('border-red-500');
        }
    });

    return isValid;
}

// Live editing tools for development
function enableLiveEditing() {
    if (window.location.search.includes('edit=1')) {
        // Add visual indicators for editable elements
        document.querySelectorAll('[data-editable]').forEach(element => {
            element.style.outline = '2px dashed #3b82f6';
            element.style.position = 'relative';

            // Add edit button
            const editBtn = document.createElement('button');
            editBtn.innerHTML = '✏️';
            editBtn.style.position = 'absolute';
            editBtn.style.top = '-10px';
            editBtn.style.right = '-10px';
            editBtn.style.background = '#3b82f6';
            editBtn.style.color = 'white';
            editBtn.style.border = 'none';
            editBtn.style.borderRadius = '50%';
            editBtn.style.width = '24px';
            editBtn.style.height = '24px';
            editBtn.style.cursor = 'pointer';
            editBtn.style.zIndex = '1000';
            editBtn.title = 'Modifier cet élément';

            editBtn.onclick = () => openEditModal(element);
            element.appendChild(editBtn);
        });

        // Add dev toolbar
        const toolbar = document.createElement('div');
        toolbar.id = 'dev-toolbar';
        toolbar.innerHTML = `
            <div class="fixed top-0 left-0 right-0 bg-blue-600 text-white p-2 text-sm z-50 flex justify-between items-center">
                <div class="flex items-center space-x-4">
                    <span class="font-bold">🛠️ Mode Édition - Billio</span>
                    <button onclick="toggleGrid()" class="bg-blue-700 px-2 py-1 rounded text-xs">Grille</button>
                    <button onclick="toggleOutlines()" class="bg-blue-700 px-2 py-1 rounded text-xs">Contours</button>
                    <button onclick="showElementInfo()" class="bg-blue-700 px-2 py-1 rounded text-xs">Info</button>
                    <a href="/dev-tools/" target="_blank" class="bg-green-600 px-2 py-1 rounded text-xs hover:bg-green-700">📖 Docs</a>
                </div>
                <div class="flex items-center space-x-2">
                    <span id="page-info" class="text-xs"></span>
                    <a href="?edit=0" class="bg-red-600 px-2 py-1 rounded text-xs">Quitter</a>
                </div>
            </div>
            <div id="grid-overlay" class="fixed inset-0 pointer-events-none z-40 hidden" style="background-image: linear-gradient(rgba(0,0,255,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,255,0.1) 1px, transparent 1px); background-size: 20px 20px;"></div>
        `;
        document.body.appendChild(toolbar);
        document.body.style.marginTop = '40px';

        // Update page info
        updatePageInfo();
    }
}

function openEditModal(element) {
    const modal = document.createElement('div');
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-white rounded-lg p-6 max-w-lg w-full mx-4">
            <h3 class="text-lg font-bold mb-4">Modifier l'élément</h3>
            <div class="mb-4">
                <label class="block text-sm font-medium text-gray-700 mb-2">Type d'élément</label>
                <select id="element-type" class="w-full border border-gray-300 rounded-md px-3 py-2">
                    <option value="text">Texte</option>
                    <option value="background">Arrière-plan</option>
                    <option value="border">Bordure</option>
                </select>
            </div>
            <div class="mb-4">
                <label class="block text-sm font-medium text-gray-700 mb-2">Contenu actuel</label>
                <div id="current-content" class="bg-gray-100 p-2 rounded text-sm">${element.textContent || element.innerHTML}</div>
            </div>
            <div class="flex justify-end space-x-2">
                <button onclick="this.closest('.fixed').remove()" class="px-4 py-2 text-gray-600 border border-gray-300 rounded-md">Annuler</button>
                <button onclick="saveElementChanges(this.closest('.fixed'), '${element.id}')" class="px-4 py-2 bg-blue-600 text-white rounded-md">Sauvegarder</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}

function saveElementChanges(modal, elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        // Ici on pourrait sauvegarder les changements via AJAX
        showNotification('Changements sauvegardés (simulation)', 'success');
    }
    modal.remove();
}

function toggleGrid() {
    const grid = document.getElementById('grid-overlay');
    grid.classList.toggle('hidden');
}

function toggleOutlines() {
    document.querySelectorAll('*').forEach(el => {
        if (el.id !== 'dev-toolbar' && !el.closest('#dev-toolbar')) {
            el.style.outline = el.style.outline ? '' : '1px solid red';
        }
    });
}

function showElementInfo() {
    document.addEventListener('mouseover', (e) => {
        if (e.target.id !== 'page-info' && !e.target.closest('#dev-toolbar')) {
            document.getElementById('page-info').textContent =
                `${e.target.tagName.toLowerCase()}${e.target.className ? '.' + e.target.className.split(' ').join('.') : ''}${e.target.id ? '#' + e.target.id : ''}`;
        }
    });
}

function updatePageInfo() {
    const info = document.getElementById('page-info');
    if (info) {
        info.textContent = `Page: ${window.location.pathname} | User: ${document.querySelector('span:contains("Bienvenue")')?.textContent || 'Anonyme'}`;
    }
}

// Initialize live editing on page load
document.addEventListener('DOMContentLoaded', function() {
    enableLiveEditing();
});

// Export functions for global use
window.BillioUtils = {
    showNotification,
    formatCurrency,
    formatDate,
    openModal,
    closeModal,
    validateForm,
    enableLiveEditing,
    toggleGrid,
    toggleOutlines,
    showElementInfo,
    countryFlagEmoji: window.countryFlagEmoji,
};

// ---------------------------------------------------------------------------
// Menus déroulants (.dropdown-panel) dans un conteneur qui rogne son contenu
// (tableaux en overflow, cartes) ou recouvert par la carte suivante : à l'ouverture,
// le menu passe en position fixe sous son bouton, se retourne vers le haut s'il manque
// de place et suit le défilement. Aucun changement de balisage nécessaire.
// ---------------------------------------------------------------------------
(function floatingDropdowns() {
    // offsetParent vaut null pour un élément en position fixe : on ne s'en sert pas ici.
    const isVisible = (el) => el.style.display !== 'none' && getComputedStyle(el).display !== 'none' && el.getClientRects().length > 0;
    const clips = (el) => {
        for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
            const cs = getComputedStyle(node);
            if (/(hidden|auto|scroll|clip)/.test(cs.overflow + cs.overflowX + cs.overflowY)) return true;
            if (node.matches('.billio-card, .dash-panel, .billio-table-wrap, table, [class*="card"]')) return true;
        }
        return false;
    };
    // Un ancêtre transformé devient le repère des éléments « fixed » : on compense son décalage.
    const containingBlockOffset = (el) => {
        for (let node = el.parentElement; node && node !== document.documentElement; node = node.parentElement) {
            const cs = getComputedStyle(node);
            if (cs.transform !== 'none' || cs.filter !== 'none' || cs.perspective !== 'none' || /paint|layout/.test(cs.contain)) {
                const r = node.getBoundingClientRect();
                return { x: r.left, y: r.top };
            }
        }
        return { x: 0, y: 0 };
    };
    const place = (panel) => {
        const anchor = panel.parentElement;
        if (!anchor) return;
        const a = anchor.getBoundingClientRect();
        const width = panel.offsetWidth;
        const height = panel.offsetHeight;
        const alignRight = panel.classList.contains('right-0');
        let left = alignRight ? a.right - width : a.left;
        left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
        let top = a.bottom + 6;
        if (top + height > window.innerHeight - 8 && a.top - height - 6 > 8) top = a.top - height - 6;
        const offset = containingBlockOffset(panel);
        Object.assign(panel.style, {
            position: 'fixed', left: `${left - offset.x}px`, top: `${top - offset.y}px`,
            right: 'auto', bottom: 'auto', marginTop: '0', zIndex: '80',
        });
    };
    const reset = (panel) => {
        ['position', 'left', 'top', 'right', 'bottom', 'marginTop', 'zIndex'].forEach((p) => { panel.style[p] = ''; });
        delete panel.dataset.floating;
    };
    const openPanels = new Set();
    const check = (panel) => {
        // Garde-fou : plus de 30 changements en une seconde = on laisse le menu tel quel.
        const now = Date.now();
        if (!panel._fdT || now - panel._fdT > 1000) { panel._fdT = now; panel._fdN = 0; }
        if (++panel._fdN > 30) return;
        if (isVisible(panel)) {
            // Déjà flottant : on ne repositionne que si une transition Alpine a effacé nos styles.
            if (panel.dataset.floating) { if (panel.style.position !== 'fixed') place(panel); return; }
            if (!clips(panel)) return;
            panel.dataset.floating = '1';
            openPanels.add(panel);
            place(panel); // tout de suite (rAF est suspendu dans un onglet en arrière-plan)…
            requestAnimationFrame(() => place(panel)); // …puis une fois la taille définitive connue
        } else if (panel.dataset.floating) {
            reset(panel);
            openPanels.delete(panel);
        }
    };
    new MutationObserver((mutations) => {
        mutations.forEach((m) => {
            if (m.target.classList && m.target.classList.contains('dropdown-panel')) check(m.target);
        });
    }).observe(document.documentElement, { attributes: true, attributeFilter: ['style', 'class'], subtree: true });
    const follow = () => openPanels.forEach((panel) => (isVisible(panel) ? place(panel) : (reset(panel), openPanels.delete(panel))));
    window.addEventListener('scroll', follow, true);
    window.addEventListener('resize', follow);
})();

/**
 * Bouton flottant « Actions rapides » déplaçable (souris + tactile).
 * Un glisser de plus de 5 px déplace le bouton au lieu d'ouvrir le menu ; la position
 * (distance aux bords droit/bas) est mémorisée par navigateur dans localStorage.
 */
window.quickDock = function () {
    const KEY = 'billio_quick_dock_pos';
    const MARGIN = 8;
    return {
        open: false,
        pos: null, // { right, bottom } en px ; null = position par défaut (CSS)
        drag: null,
        justDragged: false,
        init() {
            try { this.pos = JSON.parse(localStorage.getItem(KEY)) || null; } catch (e) { this.pos = null; }
            this.clamp();
            window.addEventListener('resize', () => this.clamp());
        },
        fabSize() {
            return (this.$refs.fab && this.$refs.fab.offsetWidth) || 52;
        },
        isTop() {
            return this.pos && window.innerHeight - this.pos.bottom - this.fabSize() / 2 < window.innerHeight / 2;
        },
        isLeft() {
            return this.pos && window.innerWidth - this.pos.right - this.fabSize() / 2 < window.innerWidth / 2;
        },
        // Ancré du côté le plus proche du bouton : ouvrir le menu ne déplace jamais le bouton.
        get style() {
            if (!this.pos) return '';
            const size = this.fabSize();
            const v = this.isTop()
                ? `top:${window.innerHeight - this.pos.bottom - size}px;bottom:auto`
                : `bottom:${this.pos.bottom}px;top:auto`;
            const h = this.isLeft()
                ? `left:${window.innerWidth - this.pos.right - size}px;right:auto`
                : `right:${this.pos.right}px;left:auto`;
            return `${v};${h}`;
        },
        // Le menu s'ouvre vers le bas / s'aligne à gauche quand le bouton est en haut / à gauche de l'écran.
        get placement() {
            return [this.isTop() ? 'is-top' : '', this.isLeft() ? 'is-left' : ''].join(' ');
        },
        clamp() {
            if (!this.pos) return;
            const fab = this.$refs.fab;
            const size = fab ? fab.offsetWidth : 52;
            this.pos = {
                right: Math.min(Math.max(this.pos.right, MARGIN), window.innerWidth - size - MARGIN),
                bottom: Math.min(Math.max(this.pos.bottom, MARGIN), window.innerHeight - size - MARGIN),
            };
        },
        startDrag(e) {
            if (e.button !== undefined && e.button !== 0) return;
            const rect = this.$refs.fab.getBoundingClientRect();
            this.drag = {
                x: e.clientX, y: e.clientY, moved: false,
                right: window.innerWidth - rect.right, bottom: window.innerHeight - rect.bottom,
            };
            this.$refs.fab.setPointerCapture(e.pointerId);
        },
        onDrag(e) {
            if (!this.drag) return;
            const dx = e.clientX - this.drag.x;
            const dy = e.clientY - this.drag.y;
            if (!this.drag.moved && Math.hypot(dx, dy) < 5) return;
            if (!this.drag.moved) { this.drag.moved = true; this.open = false; }
            this.pos = { right: this.drag.right - dx, bottom: this.drag.bottom - dy };
            this.clamp();
        },
        endDrag() {
            if (!this.drag) return;
            if (this.drag.moved) {
                this.justDragged = true; // le « click » qui suit le relâchement ne doit pas ouvrir le menu
                try { localStorage.setItem(KEY, JSON.stringify(this.pos)); } catch (e) {}
            }
            this.drag = null;
        },
        toggle() {
            if (this.justDragged) { this.justDragged = false; return; }
            this.open = !this.open;
        },
        resetPosition() {
            this.pos = null;
            this.open = false;
            try { localStorage.removeItem(KEY); } catch (e) {}
        },
    };
};

/*
 * Fenêtre de confirmation Billio (remplace window.confirm).
 * Usage : if (!(await billioConfirm({ title, message, confirmLabel, tone: 'danger' }))) return;
 * Résout true sur « Confirmer » / Entrée, false sur « Annuler » / Échap / clic à l'extérieur.
 * Avec `input: { value, placeholder, type }`, affiche un champ et résout son texte (ou false si annulé / vide).
 * Avec `choices: [{ value, label }]` (+ `value` initiale), affiche une liste et résout la valeur choisie.
 * Avec `alert: true`, un seul bouton (information).
 */
window.billioConfirm = function (options) {
    const opts = typeof options === 'string' ? { message: options } : (options || {});
    const tone = opts.tone || 'primary';
    const icon = opts.icon || (tone === 'danger' ? 'trash-2' : 'check-circle-2');
    return new Promise((resolve) => {
        const previousFocus = document.activeElement;
        const overlay = document.createElement('div');
        overlay.className = 'billio-confirm';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.innerHTML = `
            <div class="billio-confirm-card billio-confirm--${tone}">
                <span class="billio-confirm-icon"><i data-lucide="${icon}"></i></span>
                <h3 class="billio-confirm-title"></h3>
                <p class="billio-confirm-message"></p>
                <input type="text" class="billio-confirm-input" hidden>
                <select class="billio-confirm-input billio-confirm-select" hidden></select>
                <div class="billio-confirm-actions">
                    <button type="button" class="billio-confirm-cancel"></button>
                    <button type="button" class="billio-confirm-ok"></button>
                </div>
            </div>`;
        overlay.querySelector('.billio-confirm-title').textContent = opts.title || 'Confirmer l\'action';
        const message = overlay.querySelector('.billio-confirm-message');
        if (opts.message) message.textContent = opts.message; else message.remove();
        overlay.querySelector('.billio-confirm-cancel').textContent = opts.cancelLabel || 'Annuler';
        const ok = overlay.querySelector('.billio-confirm-ok');
        ok.textContent = opts.confirmLabel || 'Confirmer';
        const field = overlay.querySelector('.billio-confirm-input');
        if (opts.input) {
            field.hidden = false;
            field.value = opts.input.value || '';
            field.placeholder = opts.input.placeholder || '';
            field.maxLength = opts.input.maxLength || 200;
            if (opts.input.type) field.type = opts.input.type;
        }
        const select = overlay.querySelector('.billio-confirm-select');
        if (opts.choices) {
            select.hidden = false;
            opts.choices.forEach((choice) => {
                const option = document.createElement('option');
                option.value = choice.value;
                option.textContent = choice.label;
                select.appendChild(option);
            });
            if (opts.value !== undefined) select.value = opts.value;
        } else {
            select.remove();
        }
        if (opts.alert) overlay.querySelector('.billio-confirm-cancel').remove();

        const close = (result) => {
            document.removeEventListener('keydown', onKey, true);
            overlay.classList.remove('is-open');
            setTimeout(() => overlay.remove(), 150);
            if (previousFocus && previousFocus.focus) previousFocus.focus();
            if (opts.choices) resolve(result ? select.value : false);
            else if (opts.input) resolve(result ? (field.value.trim() || (opts.input.allowEmpty ? '' : false)) : false);
            else resolve(result);
        };
        const onKey = (e) => {
            if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(false); }
            else if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); close(true); }
        };
        overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(false); });
        const cancel = overlay.querySelector('.billio-confirm-cancel');
        if (cancel) cancel.addEventListener('click', () => close(false));
        ok.addEventListener('click', () => close(true));
        document.addEventListener('keydown', onKey, true);

        document.body.appendChild(overlay);
        if (window.lucide) lucide.createIcons();
        requestAnimationFrame(() => overlay.classList.add('is-open'));
        if (opts.choices) select.focus();
        else if (opts.input) { field.focus(); if (field.select) field.select(); } else ok.focus();
    });
};

/* Message d'information (remplace window.alert). */
window.billioAlert = function (message, title) {
    return window.billioConfirm({ title: title || 'Information', message, confirmLabel: 'OK', icon: 'info', alert: true });
};

/* Formulaires <form data-confirm="Titre" data-confirm-message="…"> : confirmation Billio avant envoi. */
document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.dataset.confirm || form.dataset.confirmed) return;
    event.preventDefault();
    const ok = await window.billioConfirm({ title: form.dataset.confirm, message: form.dataset.confirmMessage || '', confirmLabel: form.dataset.confirmLabel || 'Confirmer', tone: form.dataset.confirmTone || 'primary' });
    if (ok) { form.dataset.confirmed = '1'; form.requestSubmit ? form.requestSubmit() : form.submit(); }
}, true);
