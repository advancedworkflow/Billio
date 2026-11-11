// Landing (templates/landing/home.html) : en-tête au défilement, liste du hero, onglets produit, apparitions.
(function () {
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var header = document.querySelector('.lp-header');
  if (header) {
    var onScroll = function () { header.classList.toggle('is-scrolled', window.scrollY > 8); };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  var list = document.querySelector('[data-rotate]');
  if (list && !reduceMotion) {
    var items = list.querySelectorAll('li');
    var index = 0;
    setInterval(function () {
      items[index].classList.remove('is-active');
      index = (index + 1) % items.length;
      items[index].classList.add('is-active');
    }, 2200);
  }

  var tabs = document.querySelectorAll('.lp-tabs [data-tab]');
  function activate(tab) {
    tabs.forEach(function (other) {
      var on = other === tab;
      other.classList.toggle('is-active', on);
      other.setAttribute('aria-selected', on ? 'true' : 'false');
      other.tabIndex = on ? 0 : -1;
    });
    document.querySelectorAll('.lp-panel[data-panel]').forEach(function (panel) {
      var on = panel.getAttribute('data-panel') === tab.getAttribute('data-tab');
      panel.hidden = !on;
      panel.classList.toggle('is-active', on);
    });
  }
  if (tabs.length) activate(tabs[0]);
  tabs.forEach(function (tab, i) {
    tab.addEventListener('click', function () { activate(tab); });
    tab.addEventListener('keydown', function (event) {
      var step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      var next = tabs[(i + step + tabs.length) % tabs.length];
      next.focus();
      activate(next);
    });
  });

  if (!reduceMotion && 'IntersectionObserver' in window) {
    var targets = document.querySelectorAll('main .lp-head, main .lp-panel.is-active, .lp-sources, .lp-bento, .lp-wf-board, .lp-recipes, .lp-audiences, .lp-plans, .lp-faq, .lp-final');
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -60px 0px' });
    targets.forEach(function (el) { el.classList.add('lp-reveal'); observer.observe(el); });
  }
})();
