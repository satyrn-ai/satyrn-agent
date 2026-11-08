from datetime import datetime

from crm.domain import (
    CustomerId,
    EmailAddress,
    FirstName,
    FollowUpId,
    LastName,
    PhoneNumber,
    RuleViolation,
    validate_contact,
    validate_customer_name,
)
from crm.models import Customer as CustomerRecord
from crm.models import FollowUp as FollowUpRecord
from django.db import transaction


@transaction.atomic
def create_customer(
    *,
    first_name: FirstName,
    last_name: LastName,
    email: EmailAddress,
    phone: PhoneNumber,
) -> CustomerId:
    first_name = first_name.strip()
    last_name = last_name.strip()
    email = email.strip()
    phone = phone.strip()
    validate_customer_name(first_name, last_name)
    validate_contact(email, phone)
    record = CustomerRecord.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
    )
    return record.pk


@transaction.atomic
def update_contact(
    customer_id: CustomerId,
    *,
    email: EmailAddress,
    phone: PhoneNumber,
) -> None:
    email = email.strip()
    phone = phone.strip()
    validate_contact(email, phone)
    record = CustomerRecord.objects.get(pk=customer_id)
    record.email = email
    record.phone = phone
    record.save(update_fields=["email", "phone"])


def _validate_clock(value: datetime) -> None:
    if value.utcoffset() is None:
        raise RuleViolation("Date and time values must be timezone-aware.")


@transaction.atomic
def schedule_follow_up(
    customer_id: CustomerId,
    *,
    summary: str,
    due_at: datetime,
    now: datetime,
) -> FollowUpId:
    summary = summary.strip()
    if not summary:
        raise RuleViolation("Summary is required.")
    if len(summary) > 200:
        raise RuleViolation("Summary must be 200 characters or fewer.")
    _validate_clock(now)
    _validate_clock(due_at)
    if due_at < now:
        raise RuleViolation("Due time cannot be in the past.")

    CustomerRecord.objects.get(pk=customer_id)
    record = FollowUpRecord.objects.create(
        customer_id=customer_id,
        summary=summary,
        due_at=due_at,
    )
    return record.pk


@transaction.atomic
def complete_follow_up(follow_up_id: FollowUpId, *, now: datetime) -> None:
    _validate_clock(now)
    record = FollowUpRecord.objects.get(pk=follow_up_id)
    if record.completed_at is not None:
        return
    record.completed_at = now
    record.save(update_fields=["completed_at"])
