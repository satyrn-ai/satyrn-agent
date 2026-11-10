from crm import views
from django.urls import path

urlpatterns = [path("", views.CustomerListView.as_view())]
