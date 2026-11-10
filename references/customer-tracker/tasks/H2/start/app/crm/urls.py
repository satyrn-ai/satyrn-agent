from django.urls import path

from crm import views

app_name = "crm"

urlpatterns = [
    path("customers/", views.CustomerListView.as_view(), name="customer_list"),
    path("customers/new/", views.CustomerCreateView.as_view(), name="customer_create"),
    path(
        "customers/<int:customer_id>/",
        views.CustomerDetailView.as_view(),
        name="customer_detail",
    ),
    path(
        "customers/<int:customer_id>/contact/",
        views.CustomerContactEditView.as_view(),
        name="customer_contact_edit",
    ),
    path(
        "customers/<int:customer_id>/follow-ups/new/",
        views.FollowUpCreateView.as_view(),
        name="follow_up_create",
    ),
    path(
        "follow-ups/<int:follow_up_id>/complete/",
        views.FollowUpCompleteView.as_view(),
        name="follow_up_complete",
    ),
]
