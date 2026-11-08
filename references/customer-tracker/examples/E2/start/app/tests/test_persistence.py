from datetime import UTC, datetime

import pytest
from crm.domain import Customer
from crm.models import Customer as CustomerRecord
from crm.operations import create_customer
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


@pytest.mark.django_db
def test_create_customer_trims_values_and_returns_id() -> None:
    customer_id = create_customer(
        first_name=" Ada ",
        last_name=" Lovelace ",
        email=" ada@example.com ",
        phone=" 555-0100 ",
    )

    record = CustomerRecord.objects.get(pk=customer_id)
    assert record.first_name == "Ada"
    assert record.last_name == "Lovelace"
    assert record.email == "ada@example.com"
    assert record.phone == "555-0100"
    assert record.notes == ""


@pytest.mark.django_db
def test_create_customer_rejects_invalid_data_without_writing() -> None:
    with pytest.raises(ValueError):
        create_customer(
            first_name=" ",
            last_name="Lovelace",
            email="ada@example.com",
            phone="",
        )

    assert CustomerRecord.objects.count() == 0
