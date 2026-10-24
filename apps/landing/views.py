from django.shortcuts import render
from django.views.generic import TemplateView

from .icons import inline_icons_callback


class LandingPageView(TemplateView):
    """Vue pour la page d'accueil publique (landing page)."""
    template_name = 'landing/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Ajouter des données contextuelles si nécessaire
        context.update({
            'page_title': 'Billio — Facturez vite, soyez payé',
            'meta_description': 'Créez une facture en moins de 2 minutes. Envoyez, suivez, encaissez.',
        })
        from apps.subscriptions.marketing import plan_cards
        from apps.subscriptions.models import Plan
        context['plan_cards'] = plan_cards(Plan.objects.filter(is_active=True).order_by('order', 'price_monthly'))
        return context

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        response.add_post_render_callback(inline_icons_callback)
        return response




LEGAL_PAGES = {
    'mentions': 'Mentions légales',
    'cgu': "Conditions générales d'utilisation",
    'confidentialite': 'Politique de confidentialité',
    'cookies': 'Cookies et traceurs',
}


def legal_page(request, page):
    """Mentions légales, CGU et politique de confidentialité (informations éditeur : apps.landing.legal)."""
    from .legal import legal_info

    return render(request, 'landing/legal.html', {
        'page': page, 'page_title': LEGAL_PAGES[page], 'legal': legal_info(), 'legal_pages': LEGAL_PAGES,
    })
