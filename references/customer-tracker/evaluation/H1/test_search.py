import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from crm.models import Customer as CustomerRecord
from crm.queries import search_customers
from django.urls import reverse


def _create_customer(
    first_name: str,
    last_name: str,
    email: str,
) -> CustomerRecord:
    return CustomerRecord.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
    )


@pytest.mark.django_db
def test_search_matches_case_insensitive_substrings_in_any_customer_field() -> None:
    first_name_match = _create_customer("Alice", "Jones", "first@example.com")
    last_name_match = _create_customer("Bob", "ALICE", "last@example.com")
    email_match = _create_customer("Carol", "Brown", "alice@example.com")
    _create_customer("Daisy", "Smith", "other@example.com")

    result = search_customers(query="  aLiCe  ", page=1)

    assert result.total_count == 3
    assert {customer.id for customer in result.customers} == {
        first_name_match.pk,
        last_name_match.pk,
        email_match.pk,
    }


@pytest.mark.django_db
def test_search_orders_filtered_and_unfiltered_results_stably() -> None:
    zara = _create_customer("Zara", "Smith", "zara@example.com")
    amy_first = _create_customer("Amy", "smith", "amy1@example.com")
    amy_second = _create_customer("amy", "Smith", "amy2@example.com")
    alice = _create_customer("Alice", "Jones", "alice@example.com")

    result = search_customers(query="", page=1)

    assert [customer.id for customer in result.customers] == [
        alice.pk,
        amy_first.pk,
        amy_second.pk,
        zara.pk,
    ]
    filtered_result = search_customers(query="smith", page=1)
    assert [customer.id for customer in filtered_result.customers] == [
        amy_first.pk,
        amy_second.pk,
        zara.pk,
    ]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("customer_count", "expected_page_count", "expected_first_page_size"),
    [(1, 1, 1), (10, 1, 10), (11, 2, 10)],
)
def test_search_page_count_at_record_boundaries(
    customer_count: int,
    expected_page_count: int,
    expected_first_page_size: int,
) -> None:
    for index in range(customer_count):
        _create_customer(f"Name {index:02d}", "Smith", f"{index}@example.com")

    result = search_customers(query="", page=1)

    assert result.page_count == expected_page_count
    assert len(result.customers) == expected_first_page_size


@pytest.mark.django_db
def test_search_paginates_and_normalizes_integer_pages() -> None:
    created = [
        _create_customer(f"Name {index:02d}", "Smith", f"{index}@example.com")
        for index in range(11)
    ]

    first_page = search_customers(query="", page=1)
    second_page = search_customers(query="", page=2)
    zero_page = search_customers(query="", page=0)
    negative_page = search_customers(query="", page=-8)
    beyond_last_page = search_customers(query="", page=1000)

    assert first_page.total_count == 11
    assert first_page.page_count == 2
    assert first_page.page_number == 1
    assert len(first_page.customers) == 10
    assert first_page.has_next
    assert not first_page.has_previous
    assert second_page.page_number == 2
    assert [customer.id for customer in second_page.customers] == [created[-1].pk]
    assert second_page.has_previous
    assert not second_page.has_next
    assert zero_page.page_number == negative_page.page_number == 1
    assert beyond_last_page.page_number == 2


@pytest.mark.django_db
def test_search_empty_results_has_one_empty_first_page() -> None:
    result = search_customers(query="missing", page=50)

    assert result.customers == ()
    assert result.page_number == 1
    assert result.page_count == 1
    assert result.total_count == 0
    assert not result.has_previous
    assert not result.has_next


@pytest.mark.django_db
def test_search_result_contains_eager_domain_tuple() -> None:
    _create_customer("Ada", "Lovelace", "ada@example.com")

    result = search_customers(query="", page=1)

    assert isinstance(result.customers, tuple)
    assert result.customers[0].__class__.__module__ == "crm.domain"
    assert not isinstance(result.customers[0], CustomerRecord)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("raw_page", "expected_page"),
    [(None, 1), ("not-a-number", 1), ("0", 1), ("-3", 1), ("50", 2)],
)
def test_directory_parses_page_values_at_web_boundary(
    client,
    raw_page: str | None,
    expected_page: int,
) -> None:
    for index in range(11):
        _create_customer(f"Name {index:02d}", "Smith", f"{index}@example.com")
    url = reverse("crm:customer_list")
    if raw_page is not None:
        url += f"?page={raw_page}"

    response = client.get(url)

    assert response.status_code == 200
    assert response.context["customer_page"].page_number == expected_page


@pytest.mark.django_db
def test_directory_preserves_and_url_encodes_query_in_pagination_links(client) -> None:
    for index in range(11):
        _create_customer(f"Ada & Co {index:02d}", "Smith", f"{index}@example.com")

    response = client.get(reverse("crm:customer_list"), {"q": "  Ada &  "})
    html = unescape(response.content.decode())
    links = re.findall(r'href="([^"]+)"', html)
    page_two = next(
        link for link in links if parse_qs(urlsplit(link).query).get("page") == ["2"]
    )

    assert response.context["query"] == "Ada &"
    assert parse_qs(urlsplit(page_two).query)["q"] == ["Ada &"]
    assert "%26" in page_two
