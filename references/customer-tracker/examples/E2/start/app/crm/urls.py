from django.urls import path

from crm import views

app_name = "crm"

urlpatterns = [
    path("customers/", views.CustomerListView.as_view(), name="customer_list"),
    path(
        "customers/<int:customer_id>/",
        views.CustomerDetailView.as_view(),
        name="customer_detail",
    ),
]
