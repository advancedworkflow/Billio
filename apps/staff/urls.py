from django.urls import path

from . import views

app_name = 'staff'

urlpatterns = [
    path('', views.overview, name='overview'),
    path('users/', views.users, name='users'),
    path('users/<int:user_id>/action/', views.user_action, name='user-action'),
    path('keys/', views.keys, name='keys'),
    path('traffic/', views.traffic, name='traffic'),
    path('traffic/live/', views.traffic_live, name='traffic-live'),
    path('usage/', views.usage, name='usage'),
]
