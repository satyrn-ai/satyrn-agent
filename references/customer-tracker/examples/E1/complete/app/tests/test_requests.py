import pytest
from crm.models import Customer
from django.urls import reverse


@pytest.mark.django_db
def test_customer_list_shows_empty_state(client) -> None:
    response = client.get(reverse("crm:customer_list"))

    assert response.status_code == 200
    assert b"No customers yet." in response.content


@pytest.mark.django_db
def test_customer_list_shows_customer_link(client) -> None:
    customer = Customer.objects.create(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
    )

    response = client.get(reverse("crm:customer_list"))

    assert response.status_code == 200
    assert b"Ada Lovelace" in response.content
    assert f'href="/customers/{customer.pk}/"'.encode() in response.content


@pytest.mark.django_db
def test_customer_detail_returns_404_for_missing_customer(client) -> None:
    response = client.get(reverse("crm:customer_detail", args=[123]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_customer_detail_displays_contact_and_notes(client) -> None:
    customer = Customer.objects.create(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        phone="555-0100",
        notes="Prefers email",
    )

    response = client.get(reverse("crm:customer_detail", args=[customer.pk]))

    assert response.status_code == 200
    assert b"ada@example.com" in response.content
    assert b"555-0100" in response.content
    assert b"Prefers email" in response.content
