from functools import cached_property
from typing import Any

from crm.domain import Customer, CustomerId, FollowUpId, RuleViolation, follow_up_status
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
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import FormView, TemplateView, View


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
        customer = _customer_or_404(CustomerId(self.kwargs["customer_id"]))
        now = timezone.now()
        context["customer"] = customer
        context["follow_ups"] = [
            (follow_up, follow_up_status(follow_up, now=now))
            for follow_up in list_follow_ups(customer.id)
        ]
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


class FollowUpCreateView(FormView):
    form_class = FollowUpCreateForm
    template_name = "crm/follow_up_form.html"
    http_method_names = ["get", "post"]

    @cached_property
    def customer(self) -> Customer:
        return _customer_or_404(CustomerId(self.kwargs["customer_id"]))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["customer"] = self.customer
        return context

    def form_valid(self, form: FollowUpCreateForm) -> HttpResponse:
        try:
            schedule_follow_up(
                self.customer.id,
                **form.cleaned_data,
                now=timezone.now(),
            )
        except RuleViolation as error:
            form.add_error(None, str(error))
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return reverse("crm:customer_detail", kwargs={"customer_id": self.customer.id})


class FollowUpCompleteView(View):
    http_method_names = ["post"]

    def post(self, request: HttpRequest, follow_up_id: int) -> HttpResponse:
        try:
            follow_up = get_follow_up(FollowUpId(follow_up_id))
        except FollowUpRecord.DoesNotExist as error:
            raise Http404 from error

        complete_follow_up(follow_up.id, now=timezone.now())
        return redirect("crm:customer_detail", customer_id=follow_up.customer_id)
