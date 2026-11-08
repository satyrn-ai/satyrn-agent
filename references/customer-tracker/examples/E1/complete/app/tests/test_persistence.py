from datetime import UTC, datetime

import pytest
from crm.domain import Customer
from crm.models import Customer as CustomerRecord
from crm.queries import get_customer, list_customers


@pytest.mark.django_db
def test_list_customers_returns_eager_domain_objects() -> None:
    created_at = datetime(2026, 11, 7, tzinfo=UTC)
    record = CustomerRecord.objects.create(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        created_at=created_at,
    )

    result = list_customers()

    assert result == [
        Customer(
            id=record.pk,
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            phone="",
            notes="",
            created_at=created_at,
        )
    ]
    assert not isinstance(result[0], CustomerRecord)


@pytest.mark.django_db
def test_get_customer_raises_model_does_not_exist_for_missing_id() -> None:
    with pytest.raises(CustomerRecord.DoesNotExist):
        get_customer(123)
