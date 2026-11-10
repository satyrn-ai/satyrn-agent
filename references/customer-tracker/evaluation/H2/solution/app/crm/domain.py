from dataclasses import dataclass
from datetime import datetime
from typing import NewType

CustomerId = NewType("CustomerId", int)
type FirstName = str
type LastName = str
type EmailAddress = str
type PhoneNumber = str
FollowUpId = NewType("FollowUpId", int)


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
class FollowUp:
    id: FollowUpId
    customer_id: CustomerId
    summary: str
    due_at: datetime
    completed_at: datetime | None


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


def _require_aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise RuleViolation("Date and time values must be timezone-aware.")


def follow_up_status(follow_up: FollowUp, *, now: datetime) -> str:
    _require_aware(now)
    _require_aware(follow_up.due_at)
    if follow_up.completed_at is not None:
        return "completed"
    if follow_up.due_at < now:
        return "overdue"
    if follow_up.due_at == now:
        return "due"
    return "scheduled"
