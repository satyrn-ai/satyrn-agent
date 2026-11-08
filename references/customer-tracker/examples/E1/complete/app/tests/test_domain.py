from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from crm.domain import Customer


def test_customer_is_an_immutable_domain_value() -> None:
    customer = Customer(
        id=1,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        phone="",
        notes="",
        created_at=datetime(2026, 11, 7, tzinfo=UTC),
    )

    with pytest.raises(FrozenInstanceError):
        customer.first_name = "Augusta"
