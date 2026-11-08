from dataclasses import dataclass
from datetime import datetime

type CustomerId = int
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
