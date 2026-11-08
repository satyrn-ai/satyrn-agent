from crm.domain import Customer, CustomerId, FollowUp, FollowUpId
from crm.models import Customer as CustomerRecord
from crm.models import FollowUp as FollowUpRecord


def _to_customer(record: CustomerRecord) -> Customer:
    return Customer(
        id=record.pk,
        first_name=record.first_name,
        last_name=record.last_name,
        email=record.email,
        phone=record.phone,
        notes=record.notes,
        created_at=record.created_at,
    )


def _to_follow_up(record: FollowUpRecord) -> FollowUp:
    return FollowUp(
        id=record.pk,
        customer_id=record.customer_id,
        summary=record.summary,
        due_at=record.due_at,
        completed_at=record.completed_at,
    )


def list_customers() -> list[Customer]:
    return [_to_customer(record) for record in CustomerRecord.objects.order_by("id")]


def get_customer(customer_id: CustomerId) -> Customer:
    record = CustomerRecord.objects.get(pk=customer_id)
    return _to_customer(record)


def list_follow_ups(customer_id: CustomerId) -> list[FollowUp]:
    records = FollowUpRecord.objects.filter(customer_id=customer_id)
    follow_ups = [_to_follow_up(record) for record in records]
    return sorted(
        follow_ups,
        key=lambda follow_up: (
            follow_up.completed_at is not None,
            follow_up.due_at,
            follow_up.id,
        ),
    )


def get_follow_up(follow_up_id: FollowUpId) -> FollowUp:
    record = FollowUpRecord.objects.get(pk=follow_up_id)
    return _to_follow_up(record)
