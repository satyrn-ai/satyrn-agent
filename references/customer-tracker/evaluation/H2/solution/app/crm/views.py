from crm.domain import RuleViolation, follow_up_status
from crm.forms import ContactEditForm, CustomerCreateForm, FollowUpCreateForm
from crm.models import Customer as CustomerRecord
from crm.models import FollowUp as FollowUpRecord
from crm.operations import (
    complete_follow_up,
    create_customer,
    schedule_follow_up,
    update_contact,
)
from crm.queries import get_customer, get_follow_up, list_customers, list_follow_ups
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

    now = timezone.now()
    follow_ups = [
        (follow_up, follow_up_status(follow_up, now=now))
        for follow_up in list_follow_ups(customer_id)
    ]
    return render(
        request,
        "crm/customer_detail.html",
        {"customer": customer, "follow_ups": follow_ups},
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
                schedule_follow_up(
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
def follow_up_complete(request: HttpRequest, follow_up_id: int) -> HttpResponse:
    try:
        follow_up = get_follow_up(follow_up_id)
    except FollowUpRecord.DoesNotExist as error:
        raise Http404 from error

    complete_follow_up(follow_up_id, now=timezone.now())
    return redirect("crm:customer_detail", customer_id=follow_up.customer_id)
