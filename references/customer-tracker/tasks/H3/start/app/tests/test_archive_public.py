from datetime import UTC, datetime

import pytest
from crm.models import Customer
from crm.operations import archive_customer


@pytest.mark.django_db
def test_archive_customer_preserves_the_first_timestamp() -> None:
    customer = Customer.objects.create(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
    )
    first_time = datetime(2030, 1, 1, tzinfo=UTC)

    archive_customer(customer.pk, now=first_time)
    archive_customer(customer.pk, now=datetime(2030, 1, 2, tzinfo=UTC))

    customer.refresh_from_db()
    assert customer.archived_at == first_time
