"""
URLs for dashboard app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import automation_webhooks, booking, time_views, views
from . import process_views, project_views, support_views
from . import portal_views

app_name = 'dashboard'

router = DefaultRouter()
router.register(r'metrics', views.DashboardMetricViewSet)
router.register(r'reports', views.ReportViewSet)
router.register(r'notifications', views.NotificationViewSet)

urlpatterns = [
    # API endpoints
    path('api/', include(router.urls)),
    path('api/stats/', views.dashboard_stats_api, name='dashboard-stats-api'),

    # HTMX views
    path('', views.dashboard_home, name='dashboard-home'),
    path('stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),

    # Analytics page
    path('analytics/', views.analytics_home, name='analytics-home'),

    # New IA — vagues Kanban / Builders / Documents / Client Portal
    path('deliverables/', project_views.deliverables_list, name='deliverables-list'),
    path('projects/', project_views.project_board, name='project-board'),
    path('projects/milestones/', project_views.milestones_board, name='milestones-board'),
    path('projects/processes/', process_views.process_list, name='process-list'),
    path('projects/processes/save/', process_views.process_save, name='process-save'),
    path('projects/processes/suggestion/', process_views.process_add_suggestion, name='process-add-suggestion'),
    path('projects/processes/<int:process_id>/default/', process_views.process_default, name='process-default'),
    path('projects/processes/<int:process_id>/delete/', process_views.process_delete, name='process-delete'),
    path('projects/<int:project_id>/process/', process_views.project_update_process, name='project-update-process'),
    path('projects/phases/create/', project_views.phase_create, name='phase-create'),
    path('projects/phases/<int:phase_id>/delete/', project_views.phase_delete, name='phase-delete'),
    path('projects/phases/<int:phase_id>/move/', project_views.phase_move, name='phase-move'),
    path('projects/create/', project_views.project_create, name='project-create'),
    path('projects/<int:project_id>/', project_views.project_detail, name='project-detail'),
    path('projects/<int:project_id>/gantt/', project_views.project_gantt, name='project-gantt'),
    path('projects/<int:project_id>/save-as-template/', project_views.project_save_as_template, name='project-save-as-template'),
    path('projects/templates/<int:template_id>/delete/', project_views.project_template_delete, name='project-template-delete'),
    path('projects/<int:project_id>/time/', time_views.time_entry_create, name='time-entry-create'),
    path('projects/<int:project_id>/time/start/', time_views.time_timer_start, name='time-timer-start'),
    path('projects/<int:project_id>/time/invoice/', time_views.time_invoice, name='time-invoice'),
    path('projects/<int:project_id>/time/rate/', time_views.time_rate_update, name='time-rate-update'),
    path('search/', views.global_search, name='global-search'),
    path('aide/', views.help_center, name='help'),
    path('support/', support_views.support_list, name='support'),
    path('support/<int:ticket_id>/', support_views.support_ticket, name='support-ticket'),
    path('support/<int:ticket_id>/status/', support_views.support_ticket_status, name='support-ticket-status'),
    path('support/fichier/<int:message_id>/', support_views.support_attachment, name='support-attachment'),
    path('time/status/', time_views.time_timer_status, name='time-timer-status'),
    path('time/widget/', time_views.time_widget, name='time-widget'),
    path('time/<int:entry_id>/stop/',time_views.time_timer_stop, name='time-timer-stop'),
    path('time/<int:entry_id>/delete/', time_views.time_entry_delete, name='time-entry-delete'),
    path('projects/<int:project_id>/status/', project_views.project_update_status, name='project-update-status'),
    path('projects/<int:project_id>/billing/', project_views.project_update_billing, name='project-billing-update'),
    path('projects/<int:project_id>/brief/', project_views.project_brief_update, name='project-brief-update'),
    path('projects/<int:project_id>/duplicate/', project_views.project_duplicate, name='project-duplicate'),
    path('projects/<int:project_id>/delete/', project_views.project_delete, name='project-delete'),
    path('projects/<int:project_id>/milestones/create/', project_views.milestone_create, name='milestone-create'),
    path('milestones/<int:milestone_id>/toggle/', project_views.milestone_toggle, name='milestone-toggle'),
    path('milestones/<int:milestone_id>/update/', project_views.milestone_update, name='milestone-update'),
    path('milestones/<int:milestone_id>/form/', project_views.milestone_form_update, name='milestone-form-update'),
    path('milestones/<int:milestone_id>/phase/', project_views.milestone_update_phase, name='milestone-update-phase'),
    path('milestones/<int:milestone_id>/delete/', project_views.milestone_delete, name='milestone-delete'),
    path('milestones/<int:milestone_id>/files/upload/', project_views.milestone_file_upload, name='milestone-file-upload'),
    path('projects/<int:project_id>/tasks/create/', project_views.task_create, name='task-create'),
    path('tasks/<int:task_id>/status/', project_views.task_update_status, name='task-update-status'),
    path('tasks/<int:task_id>/update/', project_views.task_update, name='task-update'),
    path('tasks/<int:task_id>/delete/', project_views.task_delete, name='task-delete'),
    path('projects/<int:project_id>/meetings/create/', project_views.meeting_create, name='meeting-create'),
    path('meetings/<int:meeting_id>/update/', project_views.meeting_update, name='meeting-update'),
    path('meetings/<int:meeting_id>/status/', project_views.meeting_update_status, name='meeting-update-status'),
    path('meetings/<int:meeting_id>/delete/', project_views.meeting_delete, name='meeting-delete'),
    path('projects/<int:project_id>/deliverables/create/', project_views.deliverable_create, name='deliverable-create'),
    path('deliverables/<int:deliverable_id>/submit/', project_views.deliverable_submit, name='deliverable-submit'),
    path('deliverables/<int:deliverable_id>/files/upload/', project_views.deliverable_file_upload, name='deliverable-file-upload'),
    path('projects/<int:project_id>/files/upload/', project_views.project_file_upload, name='project-file-upload'),
    path('deliverables/<int:deliverable_id>/comments/create/', project_views.comment_create_org, name='deliverable-comment-create'),

    # Portail client public (lien à jeton, sans authentification)
    path('book/<uuid:token>/', booking.public_booking, name='public-booking'),
    path('book/<uuid:token>/submit/', booking.public_booking_submit, name='public-booking-submit'),
    path('book/rendez-vous/<uuid:token>/', booking.public_booking_done, name='public-booking-done'),
    path('appointments/<int:appointment_id>/cancel/', booking.appointment_cancel, name='appointment-cancel'),
    path('public/<uuid:portal_token>/', portal_views.portal_overview, name='public-portal-overview'),
    path('public/<uuid:portal_token>/notifications/read/', portal_views.portal_notifications_read, name='public-portal-notifications-read'),
    path('public/forms/<uuid:token>/', portal_views.public_client_form, name='public-client-form'),
    path('public/<uuid:portal_token>/documents/<uuid:document_id>/', portal_views.portal_document_view, name='public-portal-document-view'),
    path('public/<uuid:portal_token>/projects/<int:project_id>/', portal_views.portal_project_detail, name='public-portal-project-detail'),
    path('public/<uuid:portal_token>/projects/<int:project_id>/brief/', portal_views.portal_project_brief_update, name='public-portal-project-brief-update'),
    path('public/<uuid:portal_token>/milestones/<int:milestone_id>/form/', portal_views.portal_milestone_form_update, name='public-portal-milestone-form-update'),
    path('public/<uuid:portal_token>/milestones/<int:milestone_id>/pay/', portal_views.portal_milestone_pay, name='public-portal-milestone-pay'),
    path('public/<uuid:portal_token>/milestones/<int:milestone_id>/pay/return/', portal_views.portal_milestone_pay_return, name='public-portal-milestone-pay-return'),
    path('public/<uuid:portal_token>/projects/<int:project_id>/files/upload/', portal_views.portal_project_file_upload, name='public-portal-project-file-upload'),
    path('public/<uuid:portal_token>/deliverables/<int:deliverable_id>/approve/', portal_views.portal_deliverable_approve, name='public-portal-deliverable-approve'),
    path('public/<uuid:portal_token>/deliverables/<int:deliverable_id>/request-changes/', portal_views.portal_deliverable_request_changes, name='public-portal-deliverable-request-changes'),
    path('public/<uuid:portal_token>/deliverables/<int:deliverable_id>/comments/', portal_views.portal_comment_create, name='public-portal-comment-create'),
    path('documents/', views.documents_list, name='documents-list'),
    path('client-portal/', views.client_portal_preview, name='client-portal-preview'),
    path('timeline/', views.activity_timeline, name='activity-timeline'),
    path('timeline/marks/create/', views.calendar_mark_create, name='calendar-mark-create'),
    path('timeline/marks/<int:mark_id>/delete/', views.calendar_mark_delete, name='calendar-mark-delete'),
    path('automations/builder/', views.automation_builder, name='automation-builder'),
    path('automations/rules/save/', views.automation_rule_save, name='automation-rule-save'),
    path('automations/hook/<str:token>/', automation_webhooks.receive_webhook, name='automation-webhook'),
    path('automations/rules/test/', views.automation_rule_test, name='automation-rule-test'),
    path('automations/rules/<int:rule_id>/toggle/', views.automation_rule_toggle, name='automation-rule-toggle'),
    path('automations/rules/<int:rule_id>/delete/', views.automation_rule_delete, name='automation-rule-delete'),
    path('resources/', views.resources_center, name='resources-center'),
    path('resources/billing/', views.resources_save_billing, name='resources-save-billing'),
]
