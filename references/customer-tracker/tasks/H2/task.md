# H2: schedule and complete follow-ups

Starting from the E3 customer tracker plus the supplied follow-up schema,
implement follow-up scheduling and completion. Do not add H1 search or
pagination behavior.

A follow-up belongs to a customer whose deletion is protected. Its summary is
trimmed and 1–200 characters; `due_at` is aware; `completed_at` is nullable
and aware. `schedule_follow_up(customer_id, *, summary, due_at, now) ->
FollowUpId` accepts a due time equal to or later than `now`; naive dates and
earlier due times are rejected. `complete_follow_up(follow_up_id, *, now) ->
None` stores the first completion time and is idempotent on repeated calls.

Implement pure `follow_up_status(follow_up, *, now) -> str`: `completed`
first; otherwise `overdue` when `due_at < now`, `due` at equality, and
`scheduled` afterward. Reject naive clock inputs. Capture one aware clock
value per view operation. The form interprets entered date/time values as UTC
and labels that convention with the text `in UTC`.

Show pending follow-ups before completed ones, sorting each group by
`(due_at, id)`. Add GET/POST `/customers/<id>/follow-ups/new/` and POST-only
`/follow-ups/<id>/complete/`; non-POST completion returns 405. Invalid writes
must not partially change data, and existing E3 behavior must remain intact.