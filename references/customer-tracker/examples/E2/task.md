# E2: create a customer

Starting from E1, add a customer-creation workflow at `GET` and `POST
/customers/new/`.

Define pure `validate_customer_name(first_name, last_name)` and
`validate_contact(email, phone)` rules in `domain.py`; do not import Django
there. Names are trimmed and must each contain 1–100 characters. Email is
required and may contain at most 254 characters. Phone is optional, trimmed
text of at most 40 characters. The form boundary must also validate email
syntax using Django's email field. Do not invent phone-number validation.

Implement `create_customer(*, first_name, last_name, email, phone) -> int` in
`operations.py`. It must apply the pure rules, persist trimmed values, leave
notes empty, and return the new customer ID. Keep the write atomic.

Invalid submissions must render the form with useful errors and HTTP 200,
without writing a customer. A valid submission redirects to that customer's
detail page. The form must include CSRF protection. Preserve E1 directory and
detail behavior.