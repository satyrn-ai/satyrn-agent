from dataclasses import dataclass

type CustomerId = int
type FirstName = str
type LastName = str
type EmailAddress = str
type PhoneNumber = str


@dataclass(frozen=True)
class Customer:
    pass
