from django.urls import path

from . import views

app_name = 'translations'

urlpatterns = [
    path('set/<str:lang>/', views.set_language, name='set-language'),
    path('catalog/<str:lang>.js', views.catalog_js, name='catalog-js'),
]
