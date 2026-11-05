/*
 * Inscription Stripe Connect affichée dans Billio (Paramètres › Paiement).
 * Le formulaire reste celui de Stripe (iframe sécurisée : identité, entreprise, IBAN) ; Billio ne
 * fait qu'en régler l'apparence. À la sortie, on relit l'état du compte (connect-return).
 *
 * <div data-connect-onboarding data-publishable-key="pk_…" data-session-url="…" data-return-url="…"
 *      data-locale="fr-FR"></div>
 */
(function () {
  const SCRIPT = 'https://connect-js.stripe.com/v1.0/connect.js';

  function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[1]);
    const input = document.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function loadConnect() {
    if (window.StripeConnect && window.StripeConnect.init) return Promise.resolve(window.StripeConnect);
    return new Promise((resolve, reject) => {
      window.StripeConnect = window.StripeConnect || {};
      window.StripeConnect.onLoad = () => resolve(window.StripeConnect);
      const script = document.createElement('script');
      script.src = SCRIPT;
      script.async = true;
      script.onerror = () => reject(new Error('Stripe indisponible'));
      document.head.appendChild(script);
    });
  }

  function showError(container, message) {
    container.innerHTML = '';
    const p = document.createElement('p');
    p.className = 'st-connect-error';
    p.textContent = message || "L'inscription n'a pas pu s'ouvrir. Réessayez dans un instant.";
    container.appendChild(p);
  }

  async function mount(container) {
    if (container.dataset.mounted) return;
    container.dataset.mounted = '1';
    const { publishableKey, sessionUrl, returnUrl, locale } = container.dataset;
    try {
      const StripeConnect = await loadConnect();
      const instance = StripeConnect.init({
        publishableKey,
        locale: ({ fr: 'fr-FR', en: 'en-US', de: 'de-DE', es: 'es-ES' })[(locale || 'fr').slice(0, 2)] || 'fr-FR',
        fetchClientSecret: async () => {
          const response = await fetch(sessionUrl, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken(), 'Accept': 'application/json' },
            credentials: 'same-origin',
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok || !data.client_secret) throw new Error(data.error || 'session');
          return data.client_secret;
        },
        // Couleurs de Billio : vert profond, citron vert, crème.
        appearance: {
          overlays: 'dialog',
          variables: {
            fontFamily: 'Inter, system-ui, sans-serif',
            colorPrimary: '#1d3b31',
            colorText: '#10241d',
            colorSecondaryText: '#5f6b65',
            colorBackground: '#ffffff',
            colorBorder: '#dcd8cd',
            colorDanger: '#9a3b22',
            buttonPrimaryColorBackground: '#c8f25a',
            buttonPrimaryColorBorder: '#c8f25a',
            buttonPrimaryColorText: '#10241d',
            buttonSecondaryColorBackground: '#ffffff',
            buttonSecondaryColorText: '#10241d',
            badgeSuccessColorBackground: '#dff3d2',
            badgeSuccessColorText: '#2f6b3a',
            borderRadius: '10px',
            spacingUnit: '10px',
          },
        },
      });
      const onboarding = instance.create('account-onboarding');
      onboarding.setOnExit(() => { window.location.href = returnUrl; });
      container.innerHTML = '';
      container.appendChild(onboarding);
    } catch (error) {
      delete container.dataset.mounted;
      showError(container, error && error.message && error.message !== 'session' && error.message !== 'Stripe indisponible' ? error.message : '');
    }
  }

  window.billioConnectOnboarding = function (root) {
    const container = (root || document).querySelector('[data-connect-onboarding]');
    if (container) mount(container);
  };
})();
