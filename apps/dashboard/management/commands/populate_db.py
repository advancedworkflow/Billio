from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.organizations.models import Organization

User = get_user_model()
from apps.clients.models import Client
from apps.invoices.models import Invoice, InvoiceItem, Tax
from apps.templates_app.models import InvoiceTemplate
from django.utils import timezone
from datetime import timedelta
import random

class Command(BaseCommand):
    help = 'Populate database with sample data'

    def handle(self, *args, **options):
        self.stdout.write('Création des données de test...')

        # Create a superuser if it doesn't exist
        try:
            admin_user = User.objects.get(username='admin')
            self.stdout.write('Utilisateur admin existe déjà.')
        except User.DoesNotExist:
            admin_user = User.objects.create_superuser(
                username='admin',
                email='admin@billio.com',
                password='admin123',
                first_name='Admin',
                last_name='Billio'
            )
            self.stdout.write('Utilisateur admin créé.')

        # Create test user if it doesn't exist
        try:
            test_user = User.objects.get(username='testuser')
            self.stdout.write('Utilisateur test existe déjà.')
        except User.DoesNotExist:
            test_user = User.objects.create_user(
                username='testuser',
                email='test@example.com',
                password='test123',
                first_name='Test',
                last_name='User'
            )
            self.stdout.write('Utilisateur test créé.')

        # Create sample organizations for admin user
        admin_organizations = []
        for i in range(2):
            org, created = Organization.objects.get_or_create(
                name=f'Entreprise {i+1} SARL',
                defaults={
                    'address': f'{random.randint(1, 999)} Rue de la Business, {random.randint(75000, 75999)} Paris',
                    'phone': f'+33{random.randint(100000000, 999999999)}',
                    'email': f'contact@entreprise{i+1}.com',
                    'registration_number': f'{random.randint(10000000000000, 99999999999999)}',
                    'tax_id': f'FR{random.randint(10000000000, 99999999999)}',
                    'owner': admin_user
                }
            )
            if created:
                self.stdout.write(f'Organisation "{org.name}" créée pour admin.')
            admin_organizations.append(org)

        # Create sample organizations for test user
        test_organizations = []
        for i in range(2):
            org, created = Organization.objects.get_or_create(
                name=f'Test Company {i+1} Ltd',
                defaults={
                    'address': f'{random.randint(1, 999)} Test Street, {random.randint(75000, 75999)} Paris',
                    'phone': f'+33{random.randint(100000000, 999999999)}',
                    'email': f'contact@testcompany{i+1}.com',
                    'registration_number': f'{random.randint(10000000000000, 99999999999999)}',
                    'tax_id': f'FR{random.randint(10000000000, 99999999999)}',
                    'owner': test_user
                }
            )
            if created:
                self.stdout.write(f'Organisation "{org.name}" créée pour testuser.')
            test_organizations.append(org)

        # Create sample clients for admin organizations
        admin_clients = []
        client_names = [
            'TechCorp SA', 'WebSolutions', 'Digital Agency', 'Consulting Plus',
            'Innovate Solutions', 'DataSystems', 'Cloud Services', 'IT Consulting',
            'Marketing Digital', 'Finance Corp', 'Construction Plus', 'Retail Store'
        ]

        for org in admin_organizations:
            for i in range(3):
                client, created = Client.objects.get_or_create(
                    organization=org,
                    name=client_names[(org.id * 3 + i) % len(client_names)],
                    defaults={
                        'email': f'contact@client{org.id}{i+1}.com',
                        'phone': f'+33{random.randint(100000000, 999999999)}',
                        'address': f'{random.randint(1, 999)} Avenue des Clients\n{random.randint(75000, 75999)} Paris\nFrance'
                    }
                )
                if created:
                    self.stdout.write(f'Client "{client.name}" créé pour {org.name} (admin).')
                admin_clients.append(client)

        # Create sample clients for test organizations
        test_clients = []
        for org in test_organizations:
            for i in range(3):
                client, created = Client.objects.get_or_create(
                    organization=org,
                    name=f'Test Client {i+1} Ltd',
                    defaults={
                        'email': f'contact@testclient{i+1}.com',
                        'phone': f'+33{random.randint(100000000, 999999999)}',
                        'address': f'{random.randint(1, 999)} Test Client Street\n{random.randint(75000, 75999)} Paris\nFrance'
                    }
                )
                if created:
                    self.stdout.write(f'Client "{client.name}" créé pour {org.name} (testuser).')
                test_clients.append(client)

        # Create sample invoice templates for admin organizations
        admin_templates = []
        template_data = [
            {
                'name': 'Template Classique',
                'template_type': 'classic',
                'description': 'Template classique pour les factures professionnelles',
                'is_default': True
            },
            {
                'name': 'Template Moderne',
                'template_type': 'modern',
                'description': 'Design moderne avec couleurs vives',
                'is_default': False
            }
        ]

        for org in admin_organizations:
            for template_info in template_data:
                template, created = InvoiceTemplate.objects.get_or_create(
                    organization=org,
                    name=template_info['name'],
                    defaults={
                        'template_type': template_info['template_type'],
                        'description': template_info['description'],
                        'is_active': True,
                        'is_default': template_info['is_default']
                    }
                )
                if created:
                    self.stdout.write(f'Template "{template.name}" créé pour {org.name} (admin).')
                admin_templates.append(template)

        # Create sample invoice templates for test organizations
        test_templates = []
        for org in test_organizations:
            for template_info in template_data:
                template, created = InvoiceTemplate.objects.get_or_create(
                    organization=org,
                    name=template_info['name'],
                    defaults={
                        'template_type': template_info['template_type'],
                        'description': template_info['description'],
                        'is_active': True,
                        'is_default': template_info['is_default']
                    }
                )
                if created:
                    self.stdout.write(f'Template "{template.name}" créé pour {org.name} (testuser).')
                test_templates.append(template)

        # Create sample invoices for admin organizations
        invoice_descriptions = [
            'Développement Web', 'Configuration Serveur', 'Support Technique',
            'Audit Sécurité', 'Formation Équipe', 'Maintenance Système',
            'Conseil Stratégique', 'Développement Mobile', 'Intégration API',
            'Migration Données', 'Optimisation Performance', 'Tests Automatisés'
        ]

        for org in admin_organizations:
            # Get clients for this organization
            org_clients = [c for c in admin_clients if c.organization == org]
            if not org_clients:  # Create a client if none exists
                org_clients = [Client.objects.create(
                    organization=org,
                    name=f'Client {org.name}',
                    email=f'client@{org.name.lower().replace(" ", "")}.com',
                    phone='+33123456789'
                )]

            for i in range(8):  # 8 invoices per organization
                # Create invoice
                invoice_date = timezone.now() - timedelta(days=random.randint(0, 90))
                due_date = invoice_date + timedelta(days=30)

                invoice, created = Invoice.objects.get_or_create(
                    organization=org,
                    invoice_number=f'INV-{org.id:02d}-{i+1:03d}',
                    defaults={
                        'client': random.choice(org_clients),
                        'issue_date': invoice_date.date(),
                        'due_date': due_date.date(),
                        'currency': 'EUR',
                        'status': random.choice(['draft', 'sent', 'paid', 'overdue']),
                        'notes': f'Facture pour services prestés en {invoice_date.strftime("%B %Y")}'
                    }
                )

                if created:
                    # Add invoice items
                    num_items = random.randint(1, 4)
                    for j in range(num_items):
                        quantity = random.randint(1, 20)
                        unit_price = round(random.uniform(50, 500), 2)

                        InvoiceItem.objects.create(
                            invoice=invoice,
                            name=random.choice(invoice_descriptions),
                            description=f'Service professionnel - {random.choice(["Standard", "Premium", "Express"])}',
                            quantity=quantity,
                            unit_price=unit_price
                        )

                    self.stdout.write(f'Facture "{invoice.invoice_number}" créée pour {org.name} (admin).')

        # Create sample invoices for test organizations
        for org in test_organizations:
            # Get clients for this organization
            org_clients = [c for c in test_clients if c.organization == org]
            if not org_clients:  # Create a client if none exists
                org_clients = [Client.objects.create(
                    organization=org,
                    name=f'Test Client {org.name}',
                    email=f'client@{org.name.lower().replace(" ", "").replace("ltd", "com")}',
                    phone='+33123456789'
                )]

            for i in range(6):  # 6 invoices per test organization
                # Create invoice
                invoice_date = timezone.now() - timedelta(days=random.randint(0, 60))
                due_date = invoice_date + timedelta(days=30)

                invoice, created = Invoice.objects.get_or_create(
                    organization=org,
                    invoice_number=f'TEST-{org.id:02d}-{i+1:03d}',
                    defaults={
                        'client': random.choice(org_clients),
                        'title': f'Facture Test {i+1}',
                        'issue_date': invoice_date,
                        'due_date': due_date,
                        'status': random.choice(['draft', 'sent', 'paid', 'overdue']),
                        'notes': 'Facture de test générée automatiquement'
                    }
                )

                if created:
                    # Create invoice items
                    for j in range(random.randint(1, 3)):
                        quantity = random.randint(1, 10)
                        unit_price = round(random.uniform(50, 500), 2)

                        InvoiceItem.objects.create(
                            invoice=invoice,
                            name=random.choice(invoice_descriptions),
                            description=f'Service professionnel - {random.choice(["Standard", "Premium", "Express"])}',
                            quantity=quantity,
                            unit_price=unit_price
                        )

                    self.stdout.write(f'Facture "{invoice.invoice_number}" créée pour {org.name} (testuser).')

        # Create sample taxes for admin organizations
        tax_rates = [0, 5.5, 10, 20]
        for org in admin_organizations:
            for rate in tax_rates:
                tax, created = Tax.objects.get_or_create(
                    organization=org,
                    name=f'TVA {rate}%',
                    defaults={
                        'rate': rate,
                        'is_default': rate == 20
                    }
                )
                if created:
                    self.stdout.write(f'Taxe "{tax.name}" créée pour {org.name} (admin).')

        # Create sample taxes for test organizations
        for org in test_organizations:
            for rate in tax_rates:
                tax, created = Tax.objects.get_or_create(
                    organization=org,
                    name=f'TVA {rate}%',
                    defaults={
                        'rate': rate,
                        'is_default': rate == 20
                    }
                )
                if created:
                    self.stdout.write(f'Taxe "{tax.name}" créée pour {org.name} (testuser).')

        # Count all objects
        total_orgs = len(admin_organizations) + len(test_organizations)
        total_clients = len(admin_clients) + len(test_clients)
        total_templates = len(admin_templates) + len(test_templates)
        total_invoices = Invoice.objects.filter(organization__in=admin_organizations).count() + Invoice.objects.filter(organization__in=test_organizations).count()

        self.stdout.write(
            self.style.SUCCESS('[SUCCESS] Base de donnees peuplee avec succes !')
        )
        self.stdout.write('=== Statistiques creees ===')
        self.stdout.write(f'   - {total_orgs} organisations')
        self.stdout.write(f'   - {total_clients} clients')
        self.stdout.write(f'   - {total_templates} templates')
        self.stdout.write(f'   - {total_invoices} factures')
        self.stdout.write(f'   - {len(Invoice.objects.all())} factures')
        self.stdout.write(f'   - {len(InvoiceItem.objects.all())} articles de facture')
        self.stdout.write(f'   - {len(Tax.objects.all())} taxes')
