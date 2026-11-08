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
    return CustomerRecord.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
    ).pk


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


def _validate_aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise RuleViolation("Date and time values must be timezone-aware.")


@transaction.atomic
def archive_customer(customer_id: CustomerId, *, now: datetime) -> None:
    _validate_aware(now)
    customer = CustomerRecord.objects.select_for_update().get(pk=customer_id)
    if customer.archived_at is not None:
        return
    customer.archived_at = now
    customer.save(update_fields=["archived_at"])


@transaction.atomic
def create_follow_up(
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
    _validate_aware(now)
    _validate_aware(due_at)
    if due_at < now:
        raise RuleViolation("Due time cannot be in the past.")

    customer = CustomerRecord.objects.select_for_update().get(pk=customer_id)
    if customer.archived_at is not None:
        raise RuleViolation("Cannot create a follow-up for an archived customer.")
    return FollowUpRecord.objects.create(
        customer=customer,
        summary=summary,
        due_at=due_at,
    ).pk
