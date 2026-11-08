from crm import views
from django.urls import path

app_name = "crm"

urlpatterns = [
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/new/", views.customer_create, name="customer_create"),
    path(
        "customers/<int:customer_id>/",
        views.customer_detail,
        name="customer_detail",
    ),
    path(
        "customers/<int:customer_id>/contact/",
        views.customer_contact_edit,
        name="customer_contact_edit",
    ),
    path(
        "customers/<int:customer_id>/follow-ups/new/",
        views.follow_up_create,
        name="follow_up_create",
    ),
    path(
        "customers/<int:customer_id>/archive/",
        views.customer_archive,
        name="customer_archive",
    ),
]
