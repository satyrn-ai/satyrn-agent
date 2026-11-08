from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from crm.domain import (
    Customer,
    RuleViolation,
    validate_contact,
    validate_customer_name,
)


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


def test_validate_customer_name_accepts_trimmed_values() -> None:
    validate_customer_name(" Ada ", " Lovelace ")


@pytest.mark.parametrize("first_name", ["", "   ", "A" * 101])
def test_validate_customer_name_rejects_invalid_first_name(first_name: str) -> None:
    with pytest.raises(RuleViolation):
        validate_customer_name(first_name, "Lovelace")


def test_validate_contact_accepts_optional_phone() -> None:
    validate_contact("ada@example.com", "   ")


@pytest.mark.parametrize(
    ("email", "phone"),
    [("", ""), ("a" * 255, ""), ("ada@example.com", "1" * 41)],
)
def test_validate_contact_rejects_missing_or_overlength_values(
    email: str,
    phone: str,
) -> None:
    with pytest.raises(RuleViolation):
        validate_contact(email, phone)
