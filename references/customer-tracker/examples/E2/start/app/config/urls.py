from django.urls import include, path

urlpatterns = [path("", include("crm.urls", namespace="crm"))]
