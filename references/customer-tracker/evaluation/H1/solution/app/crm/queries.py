from crm.domain import Customer, CustomerId, CustomerPage
from crm.models import Customer as CustomerRecord
from django.db.models import Q
from django.db.models.functions import Lower

PAGE_SIZE = 10


def _to_domain(record: CustomerRecord) -> Customer:
    return Customer(
        id=CustomerId(record.pk),
        first_name=record.first_name,
        last_name=record.last_name,
        email=record.email,
        phone=record.phone,
        notes=record.notes,
        created_at=record.created_at,
    )


def list_customers() -> list[Customer]:
    records = CustomerRecord.objects.order_by(
        Lower("last_name"),
        Lower("first_name"),
        "id",
    )
    return [_to_domain(record) for record in records]


def get_customer(customer_id: CustomerId) -> Customer:
    record = CustomerRecord.objects.get(pk=customer_id)
    return _to_domain(record)


def search_customers(*, query: str, page: int) -> CustomerPage:
    query = query.strip()
    records = CustomerRecord.objects.all()
    if query:
        records = records.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )

    records = records.order_by(Lower("last_name"), Lower("first_name"), "id")
    total_count = records.count()
    page_count = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)
    page_number = min(max(page, 1), page_count)
    start = (page_number - 1) * PAGE_SIZE
    customers = tuple(
        _to_domain(record) for record in records[start : start + PAGE_SIZE]
    )

    return CustomerPage(
        customers=customers,
        page_number=page_number,
        page_count=page_count,
        total_count=total_count,
        has_previous=page_number > 1,
        has_next=page_number < page_count,
    )
