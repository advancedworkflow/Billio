"""
Crée (ou retrouve) dans le compte Stripe de Billio un produit et un prix mensuel par forfait payant.
À relancer après un changement de prix dans l'admin : un nouveau prix est créé, les abonnés
existants gardent l'ancien jusqu'à ce qu'ils changent de forfait.

    python manage.py stripe_sync_plans
"""
from django.core.management.base import BaseCommand, CommandError

from apps.subscriptions import billing
from apps.subscriptions.models import Plan


class Command(BaseCommand):
    help = 'Synchronise les forfaits payants avec les produits et prix Stripe de Billio.'

    def handle(self, *args, **options):
        if not billing.is_configured():
            raise CommandError('STRIPE_SECRET_KEY manquante : renseignez la clé secrète du compte Stripe de Billio.')
        for plan in Plan.objects.filter(is_active=True).order_by('order'):
            if plan.is_free:
                self.stdout.write(f'  {plan.name:<10} gratuit, rien à créer')
                continue
            try:
                price_id = billing.ensure_price(plan)
            except billing.BillingError as exc:
                raise CommandError(f'{plan.name} : {exc}') from None
            self.stdout.write(self.style.SUCCESS(f'  {plan.name:<10} {plan.price_monthly} € HT/mois → {price_id}'))
        self.stdout.write('Webhook à déclarer dans Stripe : <SITE_URL>/subscriptions/webhooks/stripe/ '
                          '(checkout.session.completed, customer.subscription.*, invoice.paid, invoice.payment_failed)')
