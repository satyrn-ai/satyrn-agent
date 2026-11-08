import pytest
from crm.models import Customer
from django.test import Client
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


@pytest.mark.django_db
def test_customer_create_get_renders_csrf_form(client) -> None:
    response = client.get(reverse("crm:customer_create"))

    assert response.status_code == 200
    assert b'name="csrfmiddlewaretoken"' in response.content


@pytest.mark.django_db
def test_customer_create_rejects_invalid_form_without_writing(client) -> None:
    response = client.post(
        reverse("crm:customer_create"),
        {
            "first_name": " ",
            "last_name": "Lovelace",
            "email": "not-an-email",
            "phone": "",
        },
    )

    assert response.status_code == 200
    assert response.context["form"].errors
    assert Customer.objects.count() == 0


@pytest.mark.django_db
def test_customer_create_redirects_after_valid_post(client) -> None:
    response = client.post(
        reverse("crm:customer_create"),
        {
            "first_name": " Ada ",
            "last_name": " Lovelace ",
            "email": "ada@example.com",
            "phone": "",
        },
    )

    customer = Customer.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("crm:customer_detail", args=[customer.pk])
    assert customer.first_name == "Ada"
    assert customer.last_name == "Lovelace"
    assert customer.notes == ""


@pytest.mark.django_db
def test_customer_create_requires_csrf_token() -> None:
    client = Client(enforce_csrf_checks=True)

    response = client.post(
        reverse("crm:customer_create"),
        {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "phone": "",
        },
    )

    assert response.status_code == 403
    assert Customer.objects.count() == 0


@pytest.mark.django_db
def test_contact_edit_get_prefills_current_values(client) -> None:
    customer = Customer.objects.create(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        phone="555-0100",
    )

    response = client.get(reverse("crm:customer_contact_edit", args=[customer.pk]))

    assert response.status_code == 200
    assert b'value="ada@example.com"' in response.content
    assert b'value="555-0100"' in response.content


@pytest.mark.django_db
def test_contact_edit_post_changes_only_contact_fields(client) -> None:
    customer = Customer.objects.create(
        first_name="Ada",
        last_name="Lovelace",
        email="old@example.com",
        phone="555-0100",
        notes="Prefers email",
    )
    created_at = customer.created_at

    response = client.post(
        reverse("crm:customer_contact_edit", args=[customer.pk]),
        {"email": "new@example.com", "phone": "555-0101"},
    )
    customer.refresh_from_db()

    assert response.status_code == 302
    assert response.url == reverse("crm:customer_detail", args=[customer.pk])
    assert customer.email == "new@example.com"
    assert customer.phone == "555-0101"
    assert customer.first_name == "Ada"
    assert customer.last_name == "Lovelace"
    assert customer.notes == "Prefers email"
    assert customer.created_at == created_at


@pytest.mark.django_db
def test_contact_edit_rejects_invalid_input_without_partial_write(client) -> None:
    customer = Customer.objects.create(
        first_name="Ada",
        last_name="Lovelace",
        email="old@example.com",
        phone="555-0100",
    )

    response = client.post(
        reverse("crm:customer_contact_edit", args=[customer.pk]),
        {"email": "not-an-email", "phone": "555-0101"},
    )
    customer.refresh_from_db()

    assert response.status_code == 200
    assert response.context["form"].errors
    assert customer.email == "old@example.com"
    assert customer.phone == "555-0100"


@pytest.mark.django_db
def test_contact_edit_returns_404_for_missing_customer(client) -> None:
    response = client.get(reverse("crm:customer_contact_edit", args=[123]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_contact_edit_requires_csrf_token() -> None:
    client = Client(enforce_csrf_checks=True)
    customer = Customer.objects.create(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
    )

    response = client.post(
        reverse("crm:customer_contact_edit", args=[customer.pk]),
        {"email": "new@example.com", "phone": ""},
    )

    assert response.status_code == 403
    customer.refresh_from_db()
    assert customer.email == "ada@example.com"
