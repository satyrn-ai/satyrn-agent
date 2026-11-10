from dataclasses import dataclass
from typing import NewType

CustomerId = NewType("CustomerId", int)
type FirstName = str
type LastName = str
type EmailAddress = str
type PhoneNumber = str


@dataclass(frozen=True)
class Customer:
    pass
