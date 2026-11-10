from django.db import transaction

from crm.domain import (
    CustomerId,
    EmailAddress,
    FirstName,
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
    return CustomerId(record.pk)
