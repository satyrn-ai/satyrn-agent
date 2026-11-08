from django.http import HttpRequest, HttpResponse


def customer_list(request: HttpRequest) -> HttpResponse:
    raise NotImplementedError


def customer_detail(request: HttpRequest, customer_id: int) -> HttpResponse:
    raise NotImplementedError
