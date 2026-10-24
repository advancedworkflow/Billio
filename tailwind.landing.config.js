// Tailwind compilé pour les pages publiques (landing + pages légales) : python scripts/build_landing_assets.py
module.exports = {
  content: [
    './templates/landing/**/*.html',
    './templates/components/logo_mark.html',
    './templates/components/language_switcher.html',
    './templates/components/flags/*.html',
    './templates/integrations/icons/quickbooks.svg.html',
    './static/js/landing.js',
    './static/js/consent.js',
  ],
  theme: { extend: {} },
  plugins: [],
};
