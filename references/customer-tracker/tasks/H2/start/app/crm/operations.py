from datetime import datetime

from django.db import transaction

from crm.domain import (
    CustomerId,
    EmailAddress,
    FirstName,
    FollowUpId,
    LastName,
    PhoneNumber,
    validate_contact,
    validate_customer_name,
)
from crm.models import Customer as CustomerRecord


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


def schedule_follow_up(
    customer_id: CustomerId,
    *,
    summary: str,
    due_at: datetime,
    now: datetime,
) -> FollowUpId:
    raise NotImplementedError


def complete_follow_up(follow_up_id: FollowUpId, *, now: datetime) -> None:
    raise NotImplementedError
