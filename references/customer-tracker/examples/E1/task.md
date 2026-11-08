# E1: customer directory and detail

Implement the first slice of a server-rendered Django customer tracker.

Add a `Customer` persistence model with an integer ID, first and last names
(maximum 100 characters each), required email (maximum 254), optional phone
(maximum 40), notes (maximum 2,000, initially empty), and an immutable creation
timestamp. Duplicate names and email addresses are allowed. Add and apply a
migration.

Define semantic aliases and a frozen, plain-Python `Customer` domain object.
Implement `list_customers()` and `get_customer(customer_id)` so they eagerly
convert ORM rows to domain objects. Missing IDs should raise the model's
`DoesNotExist` exception.

Add function views and templates for `GET /customers/` and
`GET /customers/<int:customer_id>/`. The directory must show an empty state
when it has no records. The detail view must return 404 for an unknown ID.
Keep ORM instances out of template context; do not add create/edit workflows
in this phase.

Run the public tests with pytest and confirm a fresh SQLite database can apply
the migrations.