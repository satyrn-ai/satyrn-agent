from django.views.generic import TemplateView


class CustomerListView(TemplateView):
    template_name = "crm/customer_list.html"
