"""
Refonte des abonnements : forfaits avec limites et options en JSON, un abonnement par compte.
Les anciennes tables étaient vides (aucune logique ne les utilisait) : on les remplace.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('subscriptions', '0002_french_choice_labels'),
    ]

    operations = [
        migrations.DeleteModel(name='InvoiceLimit'),
        migrations.DeleteModel(name='Subscription'),
        migrations.DeleteModel(name='Plan'),
        migrations.CreateModel(
            name='Plan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=30, unique=True)),
                ('name', models.CharField(max_length=60)),
                ('tagline', models.CharField(blank=True, default='', max_length=200)),
                ('price_monthly', models.DecimalField(decimal_places=2, default=0, help_text='Prix mensuel HT, en euros.', max_digits=8)),
                ('limits', models.JSONField(blank=True, default=dict, help_text='Limites chiffrées ; null = illimité.')),
                ('features', models.JSONField(blank=True, default=dict, help_text='Options incluses (vrai/faux ou niveau).')),
                ('stripe_price_id', models.CharField(blank=True, default='', max_length=100)),
                ('is_active', models.BooleanField(default=True)),
                ('is_popular', models.BooleanField(default=False)),
                ('order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'Forfait', 'verbose_name_plural': 'Forfaits', 'ordering': ['order', 'price_monthly']},
        ),
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('free', 'Gratuit'), ('active', 'Actif'), ('trialing', "En période d'essai"), ('past_due', 'Paiement en retard'), ('unpaid', 'Impayé'), ('canceled', 'Résilié'), ('incomplete', 'Paiement à finaliser'), ('incomplete_expired', 'Paiement expiré')], default='free', max_length=20)),
                ('stripe_customer_id', models.CharField(blank=True, default='', max_length=100)),
                ('stripe_subscription_id', models.CharField(blank=True, db_index=True, default='', max_length=100)),
                ('current_period_end', models.DateTimeField(blank=True, null=True)),
                ('cancel_at_period_end', models.BooleanField(default=False)),
                ('past_due_since', models.DateTimeField(blank=True, null=True)),
                ('comped', models.BooleanField(default=False, help_text='Forfait offert, attribué à la main (sans Stripe).')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='subscriptions', to='subscriptions.plan')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='subscription', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'Abonnement', 'verbose_name_plural': 'Abonnements'},
        ),
    ]
