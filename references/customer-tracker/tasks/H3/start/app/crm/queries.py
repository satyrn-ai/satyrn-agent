from crm.domain import Customer, CustomerId, FollowUp, FollowUpId
from crm.models import Customer as CustomerRecord
from crm.models import FollowUp as FollowUpRecord


def _to_domain(record: CustomerRecord) -> Customer:
    return Customer(
        id=record.pk,
        first_name=record.first_name,
        last_name=record.last_name,
        email=record.email,
        phone=record.phone,
        notes=record.notes,
        created_at=record.created_at,
        archived_at=record.archived_at,
    )


def list_customers() -> list[Customer]:
    return [_to_domain(record) for record in CustomerRecord.objects.order_by("id")]


def get_customer(customer_id: CustomerId) -> Customer:
    record = CustomerRecord.objects.get(pk=customer_id)
    return _to_domain(record)


def list_follow_ups(customer_id: CustomerId) -> list[FollowUp]:
    records = FollowUpRecord.objects.filter(customer_id=customer_id).order_by("id")
    return [
        FollowUp(
            id=record.pk,
            customer_id=record.customer_id,
            summary=record.summary,
            due_at=record.due_at,
            completed_at=record.completed_at,
        )
        for record in records
    ]


def get_follow_up(follow_up_id: FollowUpId) -> FollowUp:
    record = FollowUpRecord.objects.get(pk=follow_up_id)
    return FollowUp(
        id=record.pk,
        customer_id=record.customer_id,
        summary=record.summary,
        due_at=record.due_at,
        completed_at=record.completed_at,
    )
