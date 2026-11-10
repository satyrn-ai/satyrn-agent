from typing import Any

from django.views.generic import TemplateView


class CustomerListView(TemplateView):
    template_name = "crm/customer_list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError


class CustomerDetailView(TemplateView):
    template_name = "crm/customer_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError
