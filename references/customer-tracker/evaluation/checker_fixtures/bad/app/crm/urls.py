from crm import views as crm_views
from django.urls import path as route

urlpatterns = [route("", crm_views.customer_list)]
