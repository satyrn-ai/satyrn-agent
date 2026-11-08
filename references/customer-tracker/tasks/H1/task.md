# H1: search and paginate customers

Extend the customer directory with search and pagination. Keep E1–E3 detail,
create, and contact-edit behavior working.

- Read and strip `q`; match it as a case-insensitive substring in first name,
  last name, or email, using OR semantics. An empty query matches all
  customers.
- Order every directory result, filtered or not, by lowercase last name,
  lowercase first name, then customer ID.
- Use a fixed page size of 10. Missing, noninteger, zero, or negative `page`
  values select page 1. Positive out-of-range values select the last page.
  Empty results are page 1 of one empty page.
- Preserve the stripped search query in pagination links and URL-encode it.

Add `search_customers(*, query: str, page: int) -> CustomerPage`. The frozen
`CustomerPage` domain value must contain an eager tuple of domain customers,
the effective `page_number`, `page_count`, `total_count`, and `has_previous`
and `has_next` flags. Strip `query` and normalize nonpositive integer pages
inside this query operation; parse raw query-string page values at the web
boundary.

Do not expose querysets or ORM instances to templates. The directory must keep
its empty state, customer-creation link, and existing detail links. Its template
context must include `customer_page` (the `CustomerPage`) and `query` (the
stripped query).