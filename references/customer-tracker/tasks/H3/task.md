# H3: archive customers and preserve follow-up history

Starting from the E3 customer tracker plus the supplied minimal follow-up
schema, history fixtures, and unfinished follow-up creation interface,
implement customer archiving. This is an independent task: do not copy H2's
scheduling/completion workflow.

Add nullable `archived_at`. Implement
`archive_customer(customer_id, *, now) -> None` as an idempotent operation
that preserves the first archive timestamp. Add POST-only
`/customers/<int:customer_id>/archive/`; no unarchive behavior is required.
Archived customers remain visible in directory and detail pages with a clear
status marker containing the text `Archived`. Preserve all customer data and follow-up history.

Complete `create_follow_up(customer_id, *, summary, due_at, now) -> FollowUpId`
with trimmed 1–200 character summary validation, aware timestamps, and
rejection of due times earlier than `now`. Reject creation for archived
customers without partial writes. Coordinate archive and follow-up creation
inside transactions using the same customer-row lock (`select_for_update`
where supported).

The scaffold contains history data but no scheduling, completion, status, or
H2 workflow implementation. SQLite tests do not establish production
concurrency guarantees.