"""
URLs for clients app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .views import client_list

app_name = 'clients'

router = DefaultRouter()
router.register(r'clients', views.ClientViewSet)
router.register(r'contacts', views.ClientContactViewSet)

urlpatterns = [
    # API endpoints
    path('api/', include(router.urls)),

    # HTML views
    path('list/', client_list, name='client-list'),
    path('<int:client_id>/', views.client_detail, name='client-detail'),
    path('quick-create/', views.client_quick_create, name='client-quick-create'),
    path('quick-detail/<int:client_id>/', views.client_quick_detail, name='client-quick-detail'),
    path('quick-update/<int:client_id>/', views.client_quick_update, name='client-quick-update'),
]
