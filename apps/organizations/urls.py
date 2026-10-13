"""
URLs for organizations app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .views import organization_list

app_name = 'organizations'

router = DefaultRouter()
router.register(r'organizations', views.OrganizationViewSet)
router.register(r'members', views.OrganizationMemberViewSet)

urlpatterns = [
    # API endpoints
    path('api/', include(router.urls)),
    path('my-organizations/', views.MyOrganizationsView.as_view(), name='my-organizations'),

    # HTML views
    path('list/', organization_list, name='organization-list'),
    path('create/', views.organization_create, name='organization-create'),
    path('automations/', views.automation_settings, name='automation-settings'),
    path('logo/', views.organization_logo, name='organization-logo'),
    path('invites/create/', views.invite_member_create, name='invite-member-create'),
    path('members/<int:member_id>/update/', views.member_update, name='member-update'),
    path('members/<int:member_id>/remove/', views.member_remove, name='member-remove'),
    path('invites/<int:invite_id>/cancel/', views.invite_cancel, name='invite-cancel'),
    path('invites/<uuid:token>/accept/', views.invite_accept, name='invite-accept'),
]
