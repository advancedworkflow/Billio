from django.urls import path
from . import views

app_name = 'landing'

urlpatterns = [
    path('', views.LandingPageView.as_view(), name='home'),
    path('mentions-legales/', views.legal_page, {'page': 'mentions'}, name='legal-notice'),
    path('cgu/', views.legal_page, {'page': 'cgu'}, name='terms'),
    path('confidentialite/', views.legal_page, {'page': 'confidentialite'}, name='privacy'),
]


