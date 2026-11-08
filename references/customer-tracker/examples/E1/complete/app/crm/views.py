from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from crm.models import Customer as CustomerRecord
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
