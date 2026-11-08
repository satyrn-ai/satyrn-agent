from django.urls import path

from crm import views

app_name = "crm"

urlpatterns = [
    path("customers/", views.customer_list, name="customer_list"),
    path(
        "customers/<int:customer_id>/",
        views.customer_detail,
        name="customer_detail",
    ),
]
