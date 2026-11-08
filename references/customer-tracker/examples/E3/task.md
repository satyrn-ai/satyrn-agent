# E3: edit customer contact details

Starting from E2, add `GET` and `POST
/customers/<int:customer_id>/contact/` to edit a customer's email and optional
phone number.

Add `update_contact(customer_id, *, email, phone) -> None` in
`operations.py`. Reuse the pure contact rules, trim persisted values, and
update only the email and phone fields. Preserve the customer ID, first and
last names, notes, and original creation timestamp.

The form boundary must validate email syntax and field lengths. Invalid input
must render with useful errors and HTTP 200 without partial writes; a missing
customer returns 404; successful POST redirects to the customer detail page.
Include CSRF protection and keep both GET and POST views side effects scoped
to the successful update.