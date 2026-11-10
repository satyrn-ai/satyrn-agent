from typing import Any

from django.http import Http404
from django.views.generic import TemplateView

from crm.domain import Customer, CustomerId
from crm.models import Customer as CustomerRecord
from crm.queries import get_customer, list_customers


def _customer_or_404(customer_id: CustomerId) -> Customer:
    try:
        return get_customer(customer_id)
    except CustomerRecord.DoesNotExist as error:
        raise Http404 from error


class CustomerListView(TemplateView):
    template_name = "crm/customer_list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["customers"] = list_customers()
        return context


class CustomerDetailView(TemplateView):
    template_name = "crm/customer_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["customer"] = _customer_or_404(CustomerId(self.kwargs["customer_id"]))
        return context
