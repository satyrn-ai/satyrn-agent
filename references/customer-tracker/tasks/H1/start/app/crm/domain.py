from dataclasses import dataclass
from datetime import datetime
from typing import NewType

CustomerId = NewType("CustomerId", int)
type FirstName = str
type LastName = str
type EmailAddress = str
type PhoneNumber = str


@dataclass(frozen=True)
class Customer:
    id: CustomerId
    first_name: FirstName
    last_name: LastName
    email: EmailAddress
    phone: PhoneNumber
    notes: str
    created_at: datetime


@dataclass(frozen=True)
class CustomerPage:
    customers: tuple[Customer, ...]
    page_number: int
    page_count: int
    total_count: int
    has_previous: bool
    has_next: bool


class RuleViolation(ValueError):
    pass


def validate_customer_name(first_name: FirstName, last_name: LastName) -> None:
    for label, value in (("First name", first_name), ("Last name", last_name)):
        trimmed = value.strip()
        if not trimmed:
            raise RuleViolation(f"{label} is required.")
        if len(trimmed) > 100:
            raise RuleViolation(f"{label} must be 100 characters or fewer.")


def validate_contact(email: EmailAddress, phone: PhoneNumber) -> None:
    if not email.strip():
        raise RuleViolation("Email is required.")
    if len(email.strip()) > 254:
        raise RuleViolation("Email must be 254 characters or fewer.")
    if len(phone.strip()) > 40:
        raise RuleViolation("Phone must be 40 characters or fewer.")
