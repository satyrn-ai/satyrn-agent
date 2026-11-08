from crm.domain import Customer, CustomerId


def list_customers() -> list[Customer]:
    raise NotImplementedError


def get_customer(customer_id: CustomerId) -> Customer:
    raise NotImplementedError
