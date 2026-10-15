(function () {
  'use strict';

  const header = document.getElementById('header');
  if (header) {
    window.addEventListener('scroll', () => {
      header.classList.toggle('is-scrolled', window.scrollY > 24);
    }, { passive: true });
  }

  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener('click', function (e) {
      const href = this.getAttribute('href');
      if (!href || href === '#') return;
      const target = document.querySelector(href);
      if (!target) return;
      e.preventDefault();
      const top = target.getBoundingClientRect().top + window.scrollY - (header?.offsetHeight || 0) - 16;
      window.scrollTo({ top, behavior: 'smooth' });
    });
  });

  const fadeObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        entry.target.querySelectorAll('[data-stagger]').forEach((el, i) => {
          el.style.transitionDelay = `${i * 0.08}s`;
          el.classList.add('is-visible');
        });
      }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

  document.querySelectorAll('.reveal, .reveal-stagger').forEach((el) => fadeObserver.observe(el));

  function animateCounter(el, target, duration = 1400) {
    const suffix = el.getAttribute('data-suffix') || '';
    const prefix = el.getAttribute('data-prefix') || '';
    const start = 0;
    const startTime = performance.now();
    function tick(now) {
      const p = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      const val = Math.floor(start + (target - start) * eased);
      el.textContent = prefix + val.toLocaleString('fr-FR') + suffix;
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  const counterObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.querySelectorAll('[data-count]').forEach((counter) => {
        if (counter.dataset.animated) return;
        counter.dataset.animated = '1';
        const target = parseInt(counter.getAttribute('data-count'), 10);
        if (!isNaN(target)) animateCounter(counter, target);
      });
    });
  }, { threshold: 0.35 });
  document.querySelectorAll('.stats-section, .analytics-dashboard, .pb-dash, .cp-dash').forEach((el) => counterObserver.observe(el));

  document.querySelectorAll('.tilt-card').forEach((card) => {
    card.addEventListener('mousemove', (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const cx = rect.width / 2;
      const cy = rect.height / 2;
      const rotateX = ((y - cy) / cy) * -6;
      const rotateY = ((x - cx) / cx) * 6;
      card.style.transform = `perspective(900px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(1.02)`;
      card.style.setProperty('--mouse-x', `${(x / rect.width) * 100}%`);
      card.style.setProperty('--mouse-y', `${(y / rect.height) * 100}%`);
    });
    card.addEventListener('mouseleave', () => {
      card.style.transform = '';
    });
  });

  const showcase = document.getElementById('product-showcase');
  if (showcase) {
    const tabs = showcase.querySelectorAll('[data-showcase-tab]');
    const panels = showcase.querySelectorAll('[data-showcase-panel]');
    function activate(id) {
      tabs.forEach((t) => t.classList.toggle('is-active', t.dataset.showcaseTab === id));
      panels.forEach((p) => p.classList.toggle('is-active', p.dataset.showcasePanel === id));
    }
    tabs.forEach((tab) => {
      tab.addEventListener('mouseenter', () => activate(tab.dataset.showcaseTab));
      tab.addEventListener('focus', () => activate(tab.dataset.showcaseTab));
      tab.addEventListener('click', (e) => {
        e.preventDefault();
        activate(tab.dataset.showcaseTab);
      });
    });
  }

  document.querySelectorAll('.schema').forEach((schema) => {
    const nodes = schema.querySelectorAll('[data-schema]');
    const detailEl = schema.querySelector('[data-schema-detail]');
    const defaultDetail = detailEl ? detailEl.textContent : '';
    nodes.forEach((node) => {
      const line = schema.querySelector(`[data-schema-line="${node.dataset.schema}"]`);
      const setActive = (active) => {
        node.classList.toggle('is-active', active);
        if (line) line.classList.toggle('is-active', active);
        if (detailEl) detailEl.textContent = active ? node.dataset.detail : defaultDetail;
      };
      node.addEventListener('mouseenter', () => setActive(true));
      node.addEventListener('focus', () => setActive(true));
      node.addEventListener('mouseleave', () => setActive(false));
      node.addEventListener('blur', () => setActive(false));
    });
  });

  document.querySelectorAll('[data-payment-pending]').forEach((row) => {
    const icon = row.querySelector('.bento-payment-icon');
    const amount = row.querySelector('.bento-payment-amount');
    setTimeout(() => {
      if (icon) icon.classList.remove('bento-payment-icon--pending');
      if (amount) {
        amount.textContent = row.dataset.finalAmount || amount.textContent;
        amount.classList.remove('bento-payment-amount--pending');
      }
    }, 2600);
  });

  const pricingToggle = document.getElementById('pricing-toggle');
  if (pricingToggle) {
    const monthly = document.querySelectorAll('[data-price-monthly]');
    const yearly = document.querySelectorAll('[data-price-yearly]');
    pricingToggle.addEventListener('change', () => {
      const isYearly = pricingToggle.checked;
      monthly.forEach((el) => el.classList.toggle('hidden', isYearly));
      yearly.forEach((el) => el.classList.toggle('hidden', !isYearly));
    });
  }

  const heroMock = document.getElementById('hero-mock');
  if (heroMock) {
    const statusEl = heroMock.querySelector('[data-hero-status]');
    const notifEl = heroMock.querySelector('[data-hero-notif]');
    const revenueEl = heroMock.querySelector('[data-hero-revenue]');
    const cursorEl = heroMock.querySelector('[data-hero-cursor]');
    const sendBtn = heroMock.querySelector('[data-hero-send]');
    const bars = heroMock.querySelectorAll('[data-hero-bar]');
    const invoiceLines = heroMock.querySelectorAll('[data-hero-line]');

    let phase = 0;
    function runHeroLoop() {
      phase = (phase + 1) % 4;
      if (phase === 0) {
        if (statusEl) {
          statusEl.textContent = 'En attente';
          statusEl.className = 'hero-status hero-status--pending';
        }
        notifEl?.classList.remove('is-visible');
        invoiceLines.forEach((l) => l.classList.remove('is-visible'));
      } else if (phase === 1) {
        cursorEl?.classList.add('is-visible');
        sendBtn?.classList.add('is-highlight');
        setTimeout(() => {
          cursorEl?.classList.remove('is-visible');
          sendBtn?.classList.remove('is-highlight');
          invoiceLines.forEach((l, i) => setTimeout(() => l.classList.add('is-visible'), i * 200));
        }, 1200);
      } else if (phase === 2) {
        if (statusEl) {
          statusEl.textContent = 'Payée';
          statusEl.className = 'hero-status hero-status--paid';
        }
        bars.forEach((b, i) => {
          b.style.height = '0%';
          setTimeout(() => { b.style.height = b.dataset.heroBar + '%'; }, i * 80);
        });
        if (revenueEl) animateCounter(revenueEl, 2450, 1000);
      } else if (phase === 3) {
        notifEl?.classList.add('is-visible');
      }
    }
    setInterval(runHeroLoop, 4500);
    runHeroLoop();
    bars.forEach((b) => { b.style.height = b.dataset.heroBar + '%'; });
  }

  const aiChat = document.getElementById('ai-chat');
  if (aiChat) {
    const lines = aiChat.querySelectorAll('[data-ai-line]');
    const aiFlow = document.getElementById('ai-flow');
    const flowSteps = aiFlow ? aiFlow.querySelectorAll('[data-ai-flow-step]') : [];
    let idx = 0;
    function showNextFlowStep(sIdx) {
      if (sIdx < flowSteps.length) {
        flowSteps[sIdx].classList.add('is-visible');
        setTimeout(() => showNextFlowStep(sIdx + 1), 450);
      }
    }
    function showNextAiLine() {
      if (idx < lines.length) {
        lines[idx].classList.add('is-visible');
        idx += 1;
        setTimeout(showNextAiLine, 900);
      } else if (flowSteps.length) {
        setTimeout(() => showNextFlowStep(0), 300);
      }
    }
    const aiObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && idx === 0) {
          setTimeout(showNextAiLine, 400);
          aiObserver.disconnect();
        }
      });
    }, { threshold: 0.3 });
    aiObserver.observe(aiChat);
  }

  const templatesTrack = document.querySelector('[data-templates-track]');
  if (templatesTrack) {
    const carousel = templatesTrack.parentElement;
    const prevBtn = document.querySelector('[data-carousel-prev]');
    const nextBtn = document.querySelector('[data-carousel-next]');
    const scrollStep = () => (templatesTrack.querySelector('.template-card-mock')?.offsetWidth || 220) + 20;
    prevBtn?.addEventListener('click', () => carousel.scrollBy({ left: -scrollStep(), behavior: 'smooth' }));
    nextBtn?.addEventListener('click', () => carousel.scrollBy({ left: scrollStep(), behavior: 'smooth' }));
    templatesTrack.querySelectorAll('.template-card-mock').forEach((card) => {
      card.addEventListener('click', () => {
        templatesTrack.querySelectorAll('.template-card-mock').forEach((c) => c.classList.remove('is-selected'));
        card.classList.add('is-selected');
      });
    });
  }

  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }

  window.toggleFAQ = function (button) {
    const item = button.closest('.landing-faq-item');
    const content = item.querySelector('.faq-content');
    const icon = item.querySelector('.faq-icon');
    const open = content.classList.contains('hidden');
    document.querySelectorAll('.landing-faq-item .faq-content').forEach((el) => el.classList.add('hidden'));
    document.querySelectorAll('.landing-faq-item .faq-icon').forEach((el) => { el.textContent = '+'; });
    if (open) {
      content.classList.remove('hidden');
      icon.textContent = '−';
    }
  };
})();
