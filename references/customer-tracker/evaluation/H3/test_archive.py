from datetime import UTC, datetime

import pytest
from crm.domain import RuleViolation
from crm.models import Customer, FollowUp
from crm.operations import archive_customer, create_follow_up
from django.core.management import call_command
from django.test import Client
from django.urls import reverse


def _create_customer() -> Customer:
    return Customer.objects.create(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        notes="Keep this note",
    )


@pytest.mark.django_db
def test_archive_is_idempotent_and_preserves_customer_and_history() -> None:
    customer = _create_customer()
    due_at = datetime(2030, 1, 2, tzinfo=UTC)
    FollowUp.objects.create(customer=customer, summary="Old meeting", due_at=due_at)
    first_time = datetime(2030, 1, 3, tzinfo=UTC)

    archive_customer(customer.pk, now=first_time)
    archive_customer(customer.pk, now=datetime(2030, 1, 4, tzinfo=UTC))

    customer.refresh_from_db()
    assert customer.archived_at == first_time
    assert customer.first_name == "Ada"
    assert customer.last_name == "Lovelace"
    assert customer.notes == "Keep this note"
    assert FollowUp.objects.filter(customer=customer).count() == 1


@pytest.mark.django_db
def test_archive_rejects_naive_timestamp_without_mutation() -> None:
    customer = _create_customer()

    with pytest.raises(RuleViolation):
        archive_customer(customer.pk, now=datetime(2030, 1, 1))

    customer.refresh_from_db()
    assert customer.archived_at is None


@pytest.mark.django_db
def test_create_follow_up_trims_summary_and_allows_equal_due_time() -> None:
    customer = _create_customer()
    now = datetime(2030, 1, 1, tzinfo=UTC)

    follow_up_id = create_follow_up(
        customer.pk,
        summary=" Call back ",
        due_at=now,
        now=now,
    )

    follow_up = FollowUp.objects.get(pk=follow_up_id)
    assert follow_up.summary == "Call back"
    assert follow_up.due_at == now
    assert follow_up.customer_id == customer.pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("summary", "due_at", "now"),
    [
        (" ", datetime(2030, 1, 2, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC)),
        ("x" * 201, datetime(2030, 1, 2, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC)),
        ("Call", datetime(2029, 12, 31, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC)),
        ("Call", datetime(2030, 1, 2), datetime(2030, 1, 1, tzinfo=UTC)),
        ("Call", datetime(2030, 1, 2, tzinfo=UTC), datetime(2030, 1, 1)),
    ],
)
def test_create_follow_up_rejects_invalid_input_without_writing(
    summary: str,
    due_at: datetime,
    now: datetime,
) -> None:
    customer = _create_customer()

    with pytest.raises(RuleViolation):
        create_follow_up(customer.pk, summary=summary, due_at=due_at, now=now)

    assert FollowUp.objects.count() == 0


@pytest.mark.django_db
def test_create_follow_up_rejects_archived_customer_without_partial_write() -> None:
    customer = _create_customer()
    archive_customer(customer.pk, now=datetime(2030, 1, 1, tzinfo=UTC))

    with pytest.raises(RuleViolation):
        create_follow_up(
            customer.pk,
            summary="Call back",
            due_at=datetime(2030, 1, 2, tzinfo=UTC),
            now=datetime(2030, 1, 1, tzinfo=UTC),
        )

    assert FollowUp.objects.count() == 0


@pytest.mark.django_db
def test_archive_and_follow_up_creation_raise_model_does_not_exist() -> None:
    with pytest.raises(Customer.DoesNotExist):
        archive_customer(999, now=datetime(2030, 1, 1, tzinfo=UTC))
    with pytest.raises(Customer.DoesNotExist):
        create_follow_up(
            999,
            summary="Call back",
            due_at=datetime(2030, 1, 2, tzinfo=UTC),
            now=datetime(2030, 1, 1, tzinfo=UTC),
        )


@pytest.mark.django_db
def test_archive_view_is_post_only_and_keeps_customer_visible(client) -> None:
    customer = _create_customer()
    archive_url = reverse("crm:customer_archive", args=[customer.pk])

    assert client.get(archive_url).status_code == 405
    response = client.post(archive_url)

    assert response.status_code == 302
    assert client.get(reverse("crm:customer_list")).status_code == 200
    detail = client.get(reverse("crm:customer_detail", args=[customer.pk]))
    assert detail.status_code == 200
    assert b"Archived" in detail.content
    assert b"Keep this note" in detail.content


@pytest.mark.django_db
def test_archive_view_requires_csrf_and_returns_404_for_missing_customer() -> None:
    customer = _create_customer()
    client = Client(enforce_csrf_checks=True)
    response = client.post(reverse("crm:customer_archive", args=[customer.pk]))
    assert response.status_code == 403
    assert Client().post(reverse("crm:customer_archive", args=[999])).status_code == 404


@pytest.mark.django_db
def test_history_fixture_contains_active_and_archived_records() -> None:
    call_command("loaddata", "h3_history", verbosity=0)

    assert Customer.objects.count() == 2
    assert FollowUp.objects.count() == 2
    assert FollowUp.objects.filter(customer__archived_at__isnull=False).count() == 1
