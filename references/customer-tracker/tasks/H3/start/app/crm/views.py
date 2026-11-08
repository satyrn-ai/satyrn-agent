from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from crm.domain import RuleViolation
from crm.forms import ContactEditForm, CustomerCreateForm
from crm.models import Customer as CustomerRecord
from crm.operations import (
    create_customer,
    update_contact,
)
from crm.queries import get_customer, list_customers


def customer_list(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "crm/customer_list.html",
        {"customers": list_customers()},
    )


def customer_detail(request: HttpRequest, customer_id: int) -> HttpResponse:
    try:
        customer = get_customer(customer_id)
    except CustomerRecord.DoesNotExist as error:
        raise Http404 from error

    return render(request, "crm/customer_detail.html", {"customer": customer})


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


def follow_up_create(request: HttpRequest, customer_id: int) -> HttpResponse:
    raise NotImplementedError


def customer_archive(request: HttpRequest, customer_id: int) -> HttpResponse:
    raise NotImplementedError
