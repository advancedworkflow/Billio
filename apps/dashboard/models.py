"""
Dashboard app models for analytics and reporting.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.utils import timezone


class DashboardMetric(models.Model):
    """
    Store calculated metrics for dashboard display.
    """
    METRIC_TYPES = [
        ('revenue_total', _('Total Revenue')),
        ('revenue_monthly', _('Monthly Revenue')),
        ('invoices_sent', _('Invoices Sent')),
        ('invoices_paid', _('Invoices Paid')),
        ('invoices_overdue', _('Overdue Invoices')),
        ('average_payment_time', _('Average Payment Time')),
        ('client_count', _('Total Clients')),
        ('payment_rate', _('Payment Rate %')),
    ]

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='dashboard_metrics'
    )

    metric_type = models.CharField(max_length=50, choices=METRIC_TYPES)
    value = models.DecimalField(max_digits=15, decimal_places=2)
    period = models.CharField(max_length=20, help_text=_('e.g., 2024-01, 2024-Q1, 2024'))

    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Dashboard Metric')
        verbose_name_plural = _('Dashboard Metrics')
        unique_together = ['organization', 'metric_type', 'period']
        ordering = ['-calculated_at']

    def __str__(self):
        return f"{self.organization.name} - {self.get_metric_type_display()} - {self.period}"


class Report(models.Model):
    """
    Generated reports for users.
    """
    REPORT_TYPES = [
        ('monthly_summary', _('Synthèse mensuelle')),
        ('client_analysis', _('Analyse clients')),
        ('revenue_report', _("Rapport de chiffre d'affaires")),
        ('overdue_report', _('Rapport des impayés')),
        ('tax_report', _('Rapport de TVA')),
    ]

    STATUS_CHOICES = [
        ('pending', _('En attente')),
        ('processing', _('En cours')),
        ('completed', _('Terminé')),
        ('failed', _('Échoué')),
    ]

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='reports'
    )

    report_type = models.CharField(max_length=50, choices=REPORT_TYPES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)

    # Date range
    start_date = models.DateField()
    end_date = models.DateField()

    # Generation
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    file = models.FileField(upload_to='reports/', blank=True, null=True)

    # Parameters (JSON for custom filters)
    parameters = models.JSONField(blank=True, null=True, default=dict)

    # Metadata
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_reports'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = _('Report')
        verbose_name_plural = _('Reports')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.organization.name})"


class Notification(models.Model):
    """
    Notifications for users about important events.
    """
    NOTIFICATION_TYPES = [
        ('invoice_overdue', _('Facture en retard')),
        ('payment_received', _('Paiement reçu')),
        ('invoice_sent', _('Facture envoyée')),
        ('invoice_viewed', _('Facture consultée')),
        ('subscription_expiring', _('Abonnement bientôt expiré')),
        ('system_maintenance', _('Maintenance')),
        ('quote_sent', _('Devis envoyé')),
        ('quote_viewed', _('Devis consulté')),
        ('quote_accepted', _('Devis accepté')),
        ('quote_rejected', _('Devis refusé')),
        ('quote_expiring', _('Devis bientôt expiré')),
        ('project_created', _('Projet créé')),
        ('deliverable_submitted', _('Deliverable Submitted')),
        ('deliverable_approved', _('Deliverable Approved')),
        ('deliverable_changes_requested', _('Deliverable Changes Requested')),
        ('integration_connected', _('Intégration connectée')),
        ('integration_disconnected', _('Intégration déconnectée')),
        ('client_created', _('Nouveau client')),
        ('automation_task', _('Tâche créée par automatisation')),
        ('proposal_accepted', _('Proposition acceptée')),
        ('proposal_rejected', _('Proposition refusée')),
        ('milestone_form_submitted', _('Formulaire de jalon soumis')),
    ]

    PRIORITY_CHOICES = [
        ('low', _('Faible')),
        ('medium', _('Moyenne')),
        ('high', _('Haute')),
        ('urgent', _('Urgente')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )

    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=200)
    message = models.TextField()

    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')

    # Related objects
    related_invoice = models.ForeignKey(
        'invoices.Invoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )
    related_payment = models.ForeignKey(
        'payments.Payment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )
    related_quote = models.ForeignKey(
        'invoices.Quote',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )
    related_project = models.ForeignKey(
        'dashboard.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )
    related_deliverable = models.ForeignKey(
        'dashboard.Deliverable',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )

    # Status
    is_read = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)

    # Actions (JSON for custom action buttons)
    actions = models.JSONField(blank=True, null=True, default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = _('Notification')
        verbose_name_plural = _('Notifications')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.user.email}"

    def mark_as_read(self):
        """Mark notification as read."""
        from django.utils import timezone
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class ActivityLog(models.Model):
    """
    Log of user activities for audit and analytics.
    """
    ACTIVITY_TYPES = [
        ('login', _('Connexion')),
        ('logout', _('Déconnexion')),
        ('invoice_created', _('Facture créée')),
        ('invoice_sent', _('Facture envoyée')),
        ('invoice_paid', _('Facture payée')),
        ('client_created', _('Client créé')),
        ('payment_processed', _('Paiement traité')),
        ('settings_updated', _('Paramètres modifiés')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='activity_logs'
    )
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='activity_logs'
    )

    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPES)
    description = models.TextField()

    # Related objects (JSON for flexibility)
    related_objects = models.JSONField(blank=True, null=True, default=dict)

    # IP and user agent for security
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Activity Log')
        verbose_name_plural = _('Activity Logs')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.get_activity_type_display()} - {self.created_at}"


DEFAULT_PROJECT_PHASES = [
    ('onboarding', 'Onboarding', '#0ea5e9'),
    ('discovery', 'Découverte', '#3b82f6'),
    ('planning', 'Planification', '#6366f1'),
    ('design', 'Design', '#9333ea'),
    ('development', 'Développement', '#f59e0b'),
    ('review', 'Revue', '#06b6d4'),
    ('delivery', 'Livraison', '#db2777'),
    ('completed', 'Terminé', '#16a34a'),
]


class ProjectPhase(models.Model):
    """
    Colonne du Kanban projets/jalons, personnalisable par organisation
    (créable/supprimable) — remplace l'ancienne liste figée de phases.
    """
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='project_phases'
    )
    key = models.SlugField(max_length=30)
    label = models.CharField(max_length=50)
    color = models.CharField(max_length=20, default='#6366f1')
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Project Phase')
        verbose_name_plural = _('Project Phases')
        ordering = ['order', 'id']
        unique_together = [('organization', 'key')]

    def __str__(self):
        return self.label

    @classmethod
    def for_organization(cls, organization):
        """Phases de l'organisation, en les initialisant avec les 7 phases par défaut au premier accès."""
        phases = list(cls.objects.filter(organization=organization))
        if phases:
            return phases
        return [
            cls.objects.create(organization=organization, key=key, label=label, color=color, order=i)
            for i, (key, label, color) in enumerate(DEFAULT_PROJECT_PHASES)
        ]


class ProjectProcess(models.Model):
    """
    Processus de travail : une suite d'étapes (phases de l'organisation) suivie par un projet.
    Une organisation en a plusieurs selon ses prestations (ex. BTP : « Chantier », « Dépannage »,
    « Entretien annuel »). Les étapes restent partagées (« Terminé » sert à tous les processus) ;
    `phase_keys` donne celles du processus, dans l'ordre.
    """

    organization = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE, related_name='project_processes')
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True, default='')
    phase_keys = models.JSONField(default=list, blank=True)
    is_default = models.BooleanField(default=False)
    # Étapes propres à un seul projet (personnalisées à sa création) : absent des listes et des onglets.
    is_private = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']
        unique_together = [('organization', 'name')]

    def __str__(self):
        return self.name

    @classmethod
    def for_organization(cls, organization):
        """Processus de l'organisation ; le premier accès crée « Processus principal » avec toutes les étapes."""
        processes = list(cls.objects.filter(organization=organization, is_private=False))
        if processes:
            return processes
        keys = [phase.key for phase in ProjectPhase.for_organization(organization)]
        return [cls.objects.create(organization=organization, name='Processus principal', phase_keys=keys, is_default=True)]

    @classmethod
    def default_for(cls, organization):
        processes = cls.for_organization(organization)
        return next((p for p in processes if p.is_default), processes[0])

    def phases(self, all_phases=None):
        """Étapes du processus dans son ordre (toutes celles de l'organisation s'il n'en liste aucune)."""
        all_phases = list(all_phases if all_phases is not None else ProjectPhase.for_organization(self.organization))
        by_key = {phase.key: phase for phase in all_phases}
        ordered = [by_key[key] for key in self.phase_keys or [] if key in by_key]
        return ordered or all_phases


class Project(models.Model):
    """
    Client project, tracked through named phases (Kanban board).
    """

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='projects'
    )
    client = models.ForeignKey(
        'clients.Client',
        on_delete=models.CASCADE,
        related_name='projects'
    )

    name = models.CharField(max_length=200)
    reference = models.CharField(max_length=100, blank=True, default='')
    description = models.TextField(blank=True, default='')

    status = models.CharField(max_length=30, default='discovery')
    # Processus suivi (étapes du projet) ; vide = processus par défaut de l'organisation.
    process = models.ForeignKey('dashboard.ProjectProcess', on_delete=models.SET_NULL, null=True, blank=True, related_name='projects')

    BILLING_MODE_CHOICES = [
        ('global', _('Facturation globale')),
        ('per_milestone', _('Paiement par jalon')),
    ]
    billing_mode = models.CharField(max_length=20, choices=BILLING_MODE_CHOICES, default='global')
    # Taux horaire du projet pour facturer le temps passé (sinon TJM de l'organisation ÷ heures par jour).
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Questionnaires de cadrage éditables, un par phase : {"<phase_key>": [{"label":
    # ..., "answer": ...}, ...]}. Chaque phase peut avoir son propre formulaire (créé/
    # modifié/supprimé en interne) ; le client ne fait que répondre depuis son portail
    # (voir Milestone.form_fields pour le même mécanisme au niveau d'un jalon).
    client_brief = models.JSONField(default=dict, blank=True)

    source_quote = models.ForeignKey(
        'invoices.Quote',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='projects'
    )

    start_date = models.DateField(blank=True, null=True)
    delivery_date = models.DateField(blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_projects'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Project')
        verbose_name_plural = _('Projects')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.client.name}"

    @property
    def status_label(self):
        phase = next((p for p in ProjectPhase.for_organization(self.organization) if p.key == self.status), None)
        return phase.label if phase else self.status

    @property
    def status_color(self):
        phase = next((p for p in ProjectPhase.for_organization(self.organization) if p.key == self.status), None)
        return phase.color if phase else '#9333ea'

    @property
    def progress_percent(self):
        """
        Pourcentage de complétion du projet : livrables approuvés + milestones
        complétés, comptés comme des unités équivalentes.
        """
        total = self.deliverables.count() + self.milestones.count()
        if not total:
            return 0
        completed = (
            self.deliverables.filter(status='approved').count()
            + self.milestones.filter(is_completed=True).count()
        )
        return round(completed * 100 / total)


class Milestone(models.Model):
    """
    Jalon clé d'un projet (ex. Brief validé, Design approuvé, Livraison finale).
    """
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='milestones'
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    start_date = models.DateField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    phase = models.CharField(max_length=30, default='discovery')

    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    # Montant à facturer pour ce jalon quand le projet est en paiement par jalon
    # (Project.billing_mode == 'per_milestone'). Le bouton "Payer" du portail client
    # n'apparaît que si un montant est défini.
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(blank=True, null=True)

    # Formulaire libre attaché au jalon : liste de {"label": ..., "answer": ...},
    # dans l'ordre d'affichage. Permet de construire un questionnaire ad hoc par jalon
    # (ex. cadrage, recette, retour client) sans passer par PROJECT_BRIEF_QUESTIONS.
    form_fields = models.JSONField(default=list, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_milestones'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Milestone')
        verbose_name_plural = _('Milestones')
        ordering = ['order', 'due_date', 'created_at']

    def __str__(self):
        return f"{self.title} - {self.project.name}"

    def toggle(self):
        """Bascule l'état terminé/non terminé du jalon."""
        self.is_completed = not self.is_completed
        self.completed_at = timezone.now() if self.is_completed else None
        self.save(update_fields=['is_completed', 'completed_at', 'updated_at'])


class MilestoneFile(models.Model):
    """
    File attached to a milestone (flat list, no folders).
    """
    milestone = models.ForeignKey(
        Milestone,
        on_delete=models.CASCADE,
        related_name='files'
    )
    file = models.FileField(upload_to='milestones/files/')
    name = models.CharField(max_length=255, blank=True, default='')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='+'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Milestone File')
        verbose_name_plural = _('Milestone Files')
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.name or self.file.name


class Meeting(models.Model):
    """
    Réunion planifiée avec le client sur un projet (visio, appel, rendez-vous).
    """
    STATUS_CHOICES = [
        ('scheduled', _('Planifiée')),
        ('completed', _('Terminée')),
        ('cancelled', _('Annulée')),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='meetings'
    )

    title = models.CharField(max_length=200)
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=30)
    location = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_meetings'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Meeting')
        verbose_name_plural = _('Meetings')
        ordering = ['scheduled_at']

    def __str__(self):
        return f"{self.title} - {self.project.name}"

    @property
    def is_past(self):
        return self.scheduled_at < timezone.now() and self.status == 'scheduled'


class Task(models.Model):
    """
    Tâche légère rattachée à un projet, assignable à un membre de l'organisation.
    """
    STATUS_CHOICES = [
        ('todo', _('À faire')),
        ('in_progress', _('En cours')),
        ('done', _('Terminée')),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='tasks'
    )
    milestone = models.ForeignKey(
        Milestone,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tasks'
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tasks'
    )
    start_date = models.DateField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='todo')
    order = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_tasks'
    )
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Task')
        verbose_name_plural = _('Tasks')
        ordering = ['order', 'due_date', 'created_at']

    def __str__(self):
        return f"{self.title} - {self.project.name}"

    @property
    def is_late(self):
        return bool(self.due_date and self.due_date < timezone.localdate() and self.status != 'done')


class Deliverable(models.Model):
    """
    A deliverable within a project, subject to client approval.
    """
    STATUS_CHOICES = [
        ('in_progress', _('En cours')),
        ('submitted', _('Soumis au client')),
        ('approved', _('Approuvé')),
        ('changes_requested', _('Modifications demandées')),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='deliverables'
    )
    milestone = models.ForeignKey(
        Milestone,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deliverables'
    )

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    due_date = models.DateField(blank=True, null=True)

    submitted_at = models.DateTimeField(blank=True, null=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    changes_requested_at = models.DateTimeField(blank=True, null=True)
    change_request_reason = models.TextField(blank=True, default='')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_deliverables'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Deliverable')
        verbose_name_plural = _('Deliverables')
        ordering = ['created_at']

    def __str__(self):
        return f"{self.title} - {self.project.name}"

    def submit(self):
        """Marque le livrable comme soumis au client pour validation."""
        self.status = 'submitted'
        self.submitted_at = timezone.now()
        self.save(update_fields=['status', 'submitted_at', 'updated_at'])

    def approve(self, *, client_name=''):
        """Action publique : le client approuve le livrable."""
        self.status = 'approved'
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_at', 'updated_at'])
        self._notify(
            'deliverable_approved',
            f"Livrable « {self.title} » approuvé",
            f"{client_name or self.project.client.name} a approuvé le livrable.",
        )

    def request_changes(self, *, reason='', client_name=''):
        """Action publique : le client demande des modifications."""
        self.status = 'changes_requested'
        self.changes_requested_at = timezone.now()
        self.change_request_reason = reason
        self.save(update_fields=[
            'status', 'changes_requested_at', 'change_request_reason', 'updated_at',
        ])
        self._notify(
            'deliverable_changes_requested',
            f"Modifications demandées — « {self.title} »",
            reason or f"{client_name or self.project.client.name} a demandé des modifications.",
        )

    def _notify(self, notification_type, title, message, priority='medium'):
        """Crée une notification pour le(s) responsable(s) de l'organisation."""
        recipients = {self.project.organization.owner}
        if self.project.created_by_id:
            recipients.add(self.project.created_by)
        for user in recipients:
            if not user:
                continue
            Notification.objects.create(
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                priority=priority,
                related_deliverable=self,
                related_project=self.project,
            )


class DeliverableFile(models.Model):
    """
    File attached to a deliverable (flat list, no folders).
    """
    deliverable = models.ForeignKey(
        Deliverable,
        on_delete=models.CASCADE,
        related_name='files'
    )
    file = models.FileField(upload_to='deliverables/files/')
    name = models.CharField(max_length=255, blank=True, default='')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='+'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Deliverable File')
        verbose_name_plural = _('Deliverable Files')
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.name or self.file.name


class ProjectFile(models.Model):
    """
    General file attached to a project (flat list, no folders).
    """
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='files'
    )
    file = models.FileField(upload_to='projects/files/')
    name = models.CharField(max_length=255, blank=True, default='')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='+'
    )
    uploaded_by_client = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Project File')
        verbose_name_plural = _('Project Files')
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.name or self.file.name


class Comment(models.Model):
    """
    Flat comment thread on a deliverable (org <-> client).
    """
    AUTHOR_TYPE_CHOICES = [
        ('org', _('Équipe')),
        ('client', _('Client')),
    ]

    deliverable = models.ForeignKey(
        Deliverable,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    author_type = models.CharField(max_length=10, choices=AUTHOR_TYPE_CHOICES)
    author_name = models.CharField(max_length=200)
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Comment')
        verbose_name_plural = _('Comments')
        ordering = ['created_at']

    def __str__(self):
        return f"{self.author_name} - {self.deliverable.title}"


class AutomationRule(models.Model):
    """
    Règle d'automatisation : déclencheur -> condition (optionnelle) -> action.
    Construite visuellement dans le Centre d'automatisation.
    """
    TRIGGER_CHOICES = [
        ('invoice_sent', _('Facture envoyée')),
        ('invoice_overdue', _('Facture en retard')),
        ('payment_received', _('Paiement reçu')),
        ('client_created', _('Nouveau client')),
        ('quote_sent', _('Devis envoyé')),
        ('quote_accepted', _('Devis accepté')),
        ('quote_rejected', _('Devis refusé')),
        ('quote_expired', _('Devis expiré')),
        ('task_completed', _('Tâche terminée')),
        ('task_overdue', _('Tâche en retard')),
        ('project_created', _('Projet créé')),
        ('milestone_created', _('Jalon créé')),
        ('deliverable_validated', _('Client valide un livrable')),
        ('invoice_viewed', _('Facture consultée')),
        ('quote_viewed', _('Devis consulté')),
        ('document_viewed', _('Document consulté')),
        ('form_submitted', _('Formulaire client envoyé')),
        ('meeting_created', _('Réunion planifiée')),
        ('meeting_updated', _('Réunion modifiée')),
        ('calendar_date', _('Date du calendrier')),
        ('appointment_booked', _('Rendez-vous réservé')),
        ('webhook_received', _('Webhook entrant')),
    ]
    CONDITION_CHOICES = [
        ('amount_above', _('Montant > seuil')),
        ('specific_client', _('Client spécifique')),
    ]
    WAIT_UNIT_CHOICES = [
        ('hours', _('Heures')),
        ('days', _('Jours')),
    ]
    ACTION_CHOICES = [
        ('send_email', _('Envoyer un email')),
        ('notify', _("M'notifier")),
        ('create_task', _('Créer une tâche')),
        ('mark_late', _('Marquer en retard')),
        ('create_document', _('Créer un document')),
        ('create_project', _('Créer un projet')),
        ('create_phase', _('Créer une phase')),
        ('create_milestone', _('Créer un jalon')),
        ('create_deliverable', _('Ajouter un livrable')),
        ('create_form', _('Envoyer un formulaire')),
        ('send_message', _('Envoyer un message')),
        ('create_meeting', _('Planifier une réunion')),
        ('drive_upload', _('Copier le PDF dans Google Drive')),
        ('app_action', _('Envoyer vers une app')),
    ]

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='automation_rules'
    )
    name = models.CharField(max_length=200, blank=True, default='')
    trigger_key = models.CharField(max_length=30, choices=TRIGGER_CHOICES)
    condition_key = models.CharField(max_length=30, choices=CONDITION_CHOICES, blank=True, default='')
    condition_value = models.CharField(max_length=255, blank=True, default='')
    wait_amount = models.PositiveIntegerField(blank=True, null=True)
    wait_unit = models.CharField(max_length=10, choices=WAIT_UNIT_CHOICES, blank=True, default='')
    action_key = models.CharField(max_length=30, choices=ACTION_CHOICES)
    document_template = models.ForeignKey(
        'documents.DocumentTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='automation_rules',
        help_text=_("Modèle utilisé quand l'action est « Créer un document »."),
    )
    action_value = models.CharField(
        max_length=255, blank=True, default='',
        help_text=_(
            "Paramètre libre de l'action (titre du jalon/de la phase/du livrable créé). "
            "Accepte les variables {{client}}, {{projet}}, {{produit}}, {{date}}."
        ),
    )
    email_subject = models.CharField(
        max_length=255, blank=True, default='',
        help_text=_("Objet personnalisé pour l'action « Envoyer un email » (sinon un objet par défaut est utilisé). Variables : {{client}}, {{projet}}, {{produit}}, {{date}}."),
    )
    email_body = models.TextField(
        blank=True, default='',
        help_text=_("Message personnalisé pour l'action « Envoyer un email » (sinon un message par défaut est utilisé). Variables : {{client}}, {{projet}}, {{produit}}, {{date}}."),
    )
    # Workflow complet construit dans le board (nœuds + liens). Quand il est
    # renseigné, il fait foi : les champs « à plat » ci-dessus ne servent plus qu'à
    # indexer le déclencheur et à garder la compatibilité des anciennes règles.
    graph = models.JSONField(blank=True, default=dict)
    description = models.CharField(max_length=255, blank=True, default='')
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_automation_rules'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_triggered_at = models.DateTimeField(blank=True, null=True)
    run_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _('Automation Rule')
        verbose_name_plural = _('Automation Rules')
        ordering = ['-created_at']

    def __str__(self):
        return self.name or f"{self.get_trigger_key_display()} -> {self.get_action_key_display()}"

    def condition_matches(self, *, amount=None, client_id=None):
        """Évalue la condition (le cas échéant) au moment du déclenchement."""
        if not self.condition_key:
            return True
        if self.condition_key == 'amount_above':
            if amount is None:
                return False
            try:
                threshold = Decimal(str(self.condition_value or '0'))
            except (InvalidOperation, ValueError):
                threshold = Decimal('0')
            return Decimal(str(amount)) > threshold
        if self.condition_key == 'specific_client':
            return client_id is not None and str(client_id) == str(self.condition_value)
        return True

    def wait_timedelta(self):
        """Durée d'attente configurée avant l'exécution de l'action (ou None)."""
        if not self.wait_amount or not self.wait_unit:
            return None
        if self.wait_unit == 'hours':
            return timedelta(hours=self.wait_amount)
        return timedelta(days=self.wait_amount)

    def get_graph(self):
        """
        Workflow sous forme de graphe `{nodes: [...], edges: [...]}`. Les règles créées
        avant le board (champs à plat) sont converties à la volée en une chaîne linéaire
        déclencheur → condition → attente → action, avec des ids de nœuds stables
        ('trigger', 'condition', 'wait', 'action') pour reprendre les attentes en cours.
        """
        if self.graph and self.graph.get('nodes'):
            return self.graph

        nodes = [{'id': 'trigger', 'type': 'trigger', 'key': self.trigger_key, 'x': 80, 'y': 160, 'params': {}}]
        edges = []
        previous, port, x = 'trigger', 'out', 80
        if self.condition_key:
            x += 300
            field = 'amount' if self.condition_key == 'amount_above' else 'client'
            op = 'gt' if self.condition_key == 'amount_above' else 'eq'
            nodes.append({
                'id': 'condition', 'type': 'condition', 'key': 'if', 'x': x, 'y': 160,
                'params': {'match': 'all', 'rules': [{
                    'field': field, 'op': op,
                    'value': self.condition_value or ('0' if field == 'amount' else ''),
                }]},
            })
            edges.append({'from': previous, 'port': port, 'to': 'condition'})
            previous, port = 'condition', 'true'
        if self.wait_amount and self.wait_unit:
            x += 300
            nodes.append({
                'id': 'wait', 'type': 'wait', 'key': 'delay', 'x': x, 'y': 160,
                'params': {'amount': self.wait_amount, 'unit': self.wait_unit},
            })
            edges.append({'from': previous, 'port': port, 'to': 'wait'})
            previous, port = 'wait', 'out'
        x += 300
        nodes.append({
            'id': 'action', 'type': 'action', 'key': self.action_key, 'x': x, 'y': 160,
            'params': {
                'recipient': 'owner',
                'subject': self.email_subject,
                'body': self.email_body,
                'value': self.action_value,
                'template_id': self.document_template_id or '',
            },
        })
        edges.append({'from': previous, 'port': port, 'to': 'action'})
        return {'nodes': nodes, 'edges': edges}


class AutomationRun(models.Model):
    """
    Trace d'exécution d'une règle sur une cible donnée (idempotence : une règle ne
    s'exécute qu'une fois par cible).
    """
    rule = models.ForeignKey(
        AutomationRule,
        on_delete=models.CASCADE,
        related_name='runs'
    )
    target_type = models.CharField(max_length=20)
    target_id = models.CharField(max_length=64)
    project_id = models.PositiveIntegerField(blank=True, null=True)
    variables = models.JSONField(blank=True, default=dict)
    ran_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    detail = models.CharField(max_length=255, blank=True, default='')
    # Bloc WAIT : si la règle a un délai, l'action est différée jusqu'à scheduled_for
    # (exécutée par automation_engine.run_pending_waits, appelé au chargement du dashboard).
    scheduled_for = models.DateTimeField(blank=True, null=True)
    executed = models.BooleanField(default=True)
    # Workflows en graphe : étapes en attente [{'node': id, 'at': iso}] (plusieurs
    # branches parallèles peuvent attendre en même temps) et journal d'exécution
    # nœud par nœud, affiché dans l'historique du workflow.
    pending_steps = models.JSONField(blank=True, default=list)
    log = models.JSONField(blank=True, default=list)

    class Meta:
        verbose_name = _('Automation Run')
        verbose_name_plural = _('Automation Runs')
        ordering = ['-ran_at']
        constraints = [
            models.UniqueConstraint(fields=['rule', 'target_type', 'target_id'], name='unique_automation_run_per_target')
        ]

    def __str__(self):
        return f"{self.rule} @ {self.target_type}:{self.target_id}"


class CalendarMark(models.Model):
    """
    Repère personnalisé posé sur un jour du calendrier Timeline (clic droit —
    « Marquer ce jour »), visible par toute l'organisation. Un seul repère par jour.
    """
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='calendar_marks'
    )
    date = models.DateField()
    label = models.CharField(max_length=120, blank=True, default='')
    color = models.CharField(max_length=20, default='#f59e0b')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Calendar Mark')
        verbose_name_plural = _('Calendar Marks')
        ordering = ['date']
        unique_together = [('organization', 'date')]

    def __str__(self):
        return f"{self.date} - {self.label or self.organization.name}"



class ClientForm(models.Model):
    """
    Formulaire envoyé à un client (par une automatisation « Envoyer un formulaire »),
    rempli depuis un lien public sans compte. Sa soumission déclenche les
    automatisations « Formulaire client envoyé ».

    `fields` : [{'id', 'label', 'type', 'required', 'options'}] où type ∈
    text, textarea, email, phone, number, date, select, checkbox.
    `answers` : {field_id: valeur}.
    """
    FIELD_TYPES = ['text', 'textarea', 'email', 'phone', 'number', 'date', 'select', 'checkbox']
    STATUS_CHOICES = [
        ('pending', _('En attente')),
        ('submitted', _('Envoyé')),
    ]

    organization = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE, related_name='client_forms')
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='forms')
    project = models.ForeignKey('dashboard.Project', on_delete=models.SET_NULL, null=True, blank=True, related_name='client_forms')
    title = models.CharField(max_length=200)
    intro = models.TextField(blank=True, default='')
    fields = models.JSONField(default=list, blank=True)
    answers = models.JSONField(default=dict, blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    submitted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Client Form')
        verbose_name_plural = _('Client Forms')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} — {self.client}"

    def answered_fields(self):
        """Questions + réponses, dans l'ordre du formulaire (affichage côté équipe)."""
        def _display(field, value):
            if field.get('type') == 'date' and value:
                try:
                    return date.fromisoformat(value).strftime('%d/%m/%Y')
                except ValueError:
                    return value
            return value

        return [
            {'label': f.get('label', ''), 'type': f.get('type', 'text'),
             'value': _display(f, (self.answers or {}).get(f.get('id'), ''))}
            for f in (self.fields or [])
        ]


class ClientNotification(models.Model):
    """
    Notification affichée au client dans son portail (cloche). Les changements
    majeurs lui sont aussi envoyés par email (voir client_notifications.notify_client).
    """
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='portal_notifications')
    project = models.ForeignKey('dashboard.Project', on_delete=models.CASCADE, null=True, blank=True,
                                related_name='client_notifications')
    event = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True, default='')
    link = models.CharField(max_length=300, blank=True, default='')
    is_major = models.BooleanField(default=False)
    emailed_at = models.DateTimeField(blank=True, null=True)
    read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['client', 'read_at'])]

    def __str__(self):
        return f"{self.client} — {self.title}"


class ProjectTemplate(models.Model):
    """
    Modèle de projet réutilisable : jalons (avec tâches et livrables) et dates relatives
    au début du projet. Créé par un pack métier, ou depuis un projet existant
    (« Enregistrer comme modèle »). Voir apps/dashboard/project_templates.py.
    """
    organization = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE, related_name='project_templates')
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=300, blank=True, default='')
    trade = models.CharField(max_length=30, blank=True, default='')
    # {'milestones': [{'title', 'phase', 'start', 'due', 'description', 'amount', 'tasks': [...], 'deliverables': [...]}],
    #  'client_brief': {...}, 'billing_mode': 'global' | 'per_milestone'}
    data = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = [('organization', 'name')]

    def __str__(self):
        return self.name

    @property
    def milestone_count(self):
        return len((self.data or {}).get('milestones') or [])


class TimeEntry(models.Model):
    """
    Temps passé sur un projet (saisie manuelle ou chrono). Les entrées facturables non
    facturées deviennent des lignes de facture « heure » (voir time_views.time_invoice).
    """
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='time_entries')
    task = models.ForeignKey('dashboard.Task', on_delete=models.SET_NULL, null=True, blank=True, related_name='time_entries')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='time_entries')
    date = models.DateField(default=timezone.localdate)
    minutes = models.PositiveIntegerField(default=0)
    description = models.CharField(max_length=255, blank=True, default='')
    billable = models.BooleanField(default=True)
    started_at = models.DateTimeField(blank=True, null=True, help_text=_('Chrono en cours depuis cette heure.'))
    invoice = models.ForeignKey('invoices.Invoice', on_delete=models.SET_NULL, null=True, blank=True, related_name='time_entries')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.project} — {self.minutes} min"

    @property
    def hours_label(self):
        h, m = divmod(self.minutes, 60)
        return f"{h} h {m:02d}" if h else f"{m} min"


class Appointment(models.Model):
    """
    Rendez-vous pris en ligne par un client ou un prospect depuis la page publique
    de réservation de l'organisation (voir apps/dashboard/booking.py).
    """
    STATUS_CHOICES = [('confirmed', _('Confirmé')), ('cancelled', _('Annulé'))]

    organization = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE, related_name='appointments')
    client = models.ForeignKey('clients.Client', on_delete=models.SET_NULL, null=True, blank=True, related_name='appointments')
    type_name = models.CharField(max_length=120)
    start = models.DateTimeField()
    end = models.DateTimeField()
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    cancel_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start']
        indexes = [models.Index(fields=['organization', 'start'])]

    def __str__(self):
        return f"{self.type_name} — {self.name} ({self.start:%d/%m/%Y %H:%M})"

