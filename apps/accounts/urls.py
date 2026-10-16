"""
URLs for accounts app.
"""
from django.contrib.auth import views as auth_views
from django.urls import path, include, reverse_lazy
from django.shortcuts import redirect
from rest_framework.routers import DefaultRouter
from . import views
from .views import login_view, register_view, logout_view, profile_view

app_name = 'accounts'

router = DefaultRouter()
router.register(r'users', views.UserViewSet)
router.register(r'profiles', views.UserProfileViewSet)

urlpatterns = [
    # API endpoints
    path('api/', include(router.urls)),
    path('api/auth/login/', views.LoginView.as_view(), name='api-login'),
    path('api/auth/logout/', views.LogoutView.as_view(), name='api-logout'),
    path('api/auth/register/', views.RegisterView.as_view(), name='api-register'),
    path('api/auth/google/', views.GoogleLoginView.as_view(), name='api-google-login'),
    path('api/profile/', views.UserProfileView.as_view(), name='api-user-profile'),

    # HTML views
    path('login/', views.login_view, name='login'),
    path('login/verification/', views.login_2fa_view, name='login-2fa'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('google/login/', views.GoogleLoginView.as_view(), name='google-login'),
    path('password-reset/', views.BillioPasswordResetView.as_view(), name='password-reset'),
    path('password-reset/sent/', auth_views.PasswordResetDoneView.as_view(
        template_name='auth/password_reset/done.html'), name='password-reset-done'),
    path('password-reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='auth/password_reset/confirm.html',
        success_url=reverse_lazy('accounts:password-reset-complete')), name='password-reset-confirm'),
    path('password-reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='auth/password_reset/complete.html'), name='password-reset-complete'),
    path('profile/', views.profile_view, name='user-profile'),
    path('settings/', views.settings_view, name='user-settings'),
    path('settings/token/generate/', views.generate_api_token, name='api-token-generate'),
    path('settings/token/revoke/', views.revoke_api_token, name='api-token-revoke'),

    # Legacy URL redirects (for backward compatibility)
    path('auth/login/', lambda request: redirect('accounts:login')),
    path('auth/logout/', lambda request: redirect('accounts:logout')),
    path('auth/register/', lambda request: redirect('accounts:register')),
    path('auth/google/', lambda request: redirect('accounts:google-login')),
]
