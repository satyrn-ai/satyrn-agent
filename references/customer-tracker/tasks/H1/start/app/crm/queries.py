from crm.domain import Customer, CustomerId, CustomerPage
from crm.models import Customer as CustomerRecord


def _to_domain(record: CustomerRecord) -> Customer:
    return Customer(
        id=record.pk,
        first_name=record.first_name,
        last_name=record.last_name,
        email=record.email,
        phone=record.phone,
        notes=record.notes,
        created_at=record.created_at,
    )


def list_customers() -> list[Customer]:
    return [_to_domain(record) for record in CustomerRecord.objects.order_by("id")]


def get_customer(customer_id: CustomerId) -> Customer:
    record = CustomerRecord.objects.get(pk=customer_id)
    return _to_domain(record)


def search_customers(*, query: str, page: int) -> CustomerPage:
    raise NotImplementedError
