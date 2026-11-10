from crm.domain import Customer, CustomerId, FollowUp, FollowUpId
from crm.models import Customer as CustomerRecord
from crm.models import FollowUp as FollowUpRecord


def _to_customer(record: CustomerRecord) -> Customer:
    return Customer(
        id=CustomerId(record.pk),
        first_name=record.first_name,
        last_name=record.last_name,
        email=record.email,
        phone=record.phone,
        notes=record.notes,
        created_at=record.created_at,
        archived_at=record.archived_at,
    )


def _to_follow_up(record: FollowUpRecord) -> FollowUp:
    return FollowUp(
        id=FollowUpId(record.pk),
        customer_id=CustomerId(record.customer_id),
        summary=record.summary,
        due_at=record.due_at,
        completed_at=record.completed_at,
    )


def list_customers() -> list[Customer]:
    return [_to_customer(record) for record in CustomerRecord.objects.order_by("id")]


def get_customer(customer_id: CustomerId) -> Customer:
    return _to_customer(CustomerRecord.objects.get(pk=customer_id))


def list_follow_ups(customer_id: CustomerId) -> list[FollowUp]:
    records = FollowUpRecord.objects.filter(customer_id=customer_id).order_by("id")
    return [_to_follow_up(record) for record in records]
