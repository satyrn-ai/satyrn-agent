from crm.domain import RuleViolation
from crm.forms import ContactEditForm, CustomerCreateForm, FollowUpCreateForm
from crm.models import Customer as CustomerRecord
from crm.operations import (
    archive_customer,
    create_customer,
    create_follow_up,
    update_contact,
)
from crm.queries import get_customer, list_customers, list_follow_ups
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST


def customer_list(request: HttpRequest) -> HttpResponse:
    return render(request, "crm/customer_list.html", {"customers": list_customers()})


def customer_detail(request: HttpRequest, customer_id: int) -> HttpResponse:
    try:
        customer = get_customer(customer_id)
    except CustomerRecord.DoesNotExist as error:
        raise Http404 from error
    return render(
        request,
        "crm/customer_detail.html",
        {"customer": customer, "follow_ups": list_follow_ups(customer_id)},
    )


@require_http_methods(["GET", "POST"])
def customer_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = CustomerCreateForm(request.POST)
        if form.is_valid():
            try:
                customer_id = create_customer(**form.cleaned_data)
            except RuleViolation as error:
                form.add_error(None, str(error))
            else:
                return redirect("crm:customer_detail", customer_id=customer_id)
    else:
        form = CustomerCreateForm()
    return render(request, "crm/customer_form.html", {"form": form})


@require_http_methods(["GET", "POST"])
def customer_contact_edit(
    request: HttpRequest,
    customer_id: int,
) -> HttpResponse:
    try:
        customer = get_customer(customer_id)
    except CustomerRecord.DoesNotExist as error:
        raise Http404 from error
    if request.method == "POST":
        form = ContactEditForm(request.POST)
        if form.is_valid():
            try:
                update_contact(customer_id, **form.cleaned_data)
            except RuleViolation as error:
                form.add_error(None, str(error))
            else:
                return redirect("crm:customer_detail", customer_id=customer_id)
    else:
        form = ContactEditForm(
            initial={"email": customer.email, "phone": customer.phone}
        )
    return render(
        request,
        "crm/contact_form.html",
        {"customer": customer, "form": form},
    )


@require_http_methods(["GET", "POST"])
def follow_up_create(request: HttpRequest, customer_id: int) -> HttpResponse:
    try:
        customer = get_customer(customer_id)
    except CustomerRecord.DoesNotExist as error:
        raise Http404 from error
    if request.method == "POST":
        form = FollowUpCreateForm(request.POST)
        if form.is_valid():
            try:
                create_follow_up(
                    customer_id,
                    **form.cleaned_data,
                    now=timezone.now(),
                )
            except RuleViolation as error:
                form.add_error(None, str(error))
            else:
                return redirect("crm:customer_detail", customer_id=customer_id)
    else:
        form = FollowUpCreateForm()
    return render(
        request,
        "crm/follow_up_form.html",
        {"customer": customer, "form": form},
    )


@require_POST
def customer_archive(request: HttpRequest, customer_id: int) -> HttpResponse:
    try:
        archive_customer(customer_id, now=timezone.now())
    except CustomerRecord.DoesNotExist as error:
        raise Http404 from error
    return redirect("crm:customer_detail", customer_id=customer_id)
