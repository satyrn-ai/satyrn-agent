from functools import cached_property
from typing import Any

from django.http import Http404, HttpResponse
from django.urls import reverse
from django.views.generic import FormView, TemplateView

from crm.domain import Customer, CustomerId, RuleViolation
from crm.forms import ContactEditForm, CustomerCreateForm
from crm.models import Customer as CustomerRecord
from crm.operations import create_customer, update_contact
from crm.queries import get_customer


def _customer_or_404(customer_id: CustomerId) -> Customer:
    try:
        return get_customer(customer_id)
    except CustomerRecord.DoesNotExist as error:
        raise Http404 from error


class CustomerListView(TemplateView):
    template_name = "crm/customer_list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError


class CustomerDetailView(TemplateView):
    template_name = "crm/customer_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["customer"] = _customer_or_404(CustomerId(self.kwargs["customer_id"]))
        return context


class CustomerCreateView(FormView):
    form_class = CustomerCreateForm
    template_name = "crm/customer_form.html"
    http_method_names = ["get", "post"]
    customer_id: CustomerId

    def form_valid(self, form: CustomerCreateForm) -> HttpResponse:
        try:
            self.customer_id = create_customer(**form.cleaned_data)
        except RuleViolation as error:
            form.add_error(None, str(error))
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return reverse("crm:customer_detail", kwargs={"customer_id": self.customer_id})


class CustomerContactEditView(FormView):
    form_class = ContactEditForm
    template_name = "crm/contact_form.html"
    http_method_names = ["get", "post"]

    @cached_property
    def customer(self) -> Customer:
        return _customer_or_404(CustomerId(self.kwargs["customer_id"]))

    def get_initial(self) -> dict[str, Any]:
        return {"email": self.customer.email, "phone": self.customer.phone}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["customer"] = self.customer
        return context

    def form_valid(self, form: ContactEditForm) -> HttpResponse:
        try:
            update_contact(self.customer.id, **form.cleaned_data)
        except RuleViolation as error:
            form.add_error(None, str(error))
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return reverse("crm:customer_detail", kwargs={"customer_id": self.customer.id})
