from datetime import UTC, datetime

import pytest
from crm.domain import FollowUp, RuleViolation, follow_up_status
from crm.models import Customer
from crm.models import FollowUp as FollowUpRecord
from crm.operations import complete_follow_up, schedule_follow_up
from crm.queries import list_follow_ups
from django.test import Client
from django.urls import reverse


def _create_customer() -> Customer:
    return Customer.objects.create(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
    )


@pytest.mark.parametrize(
    ("due_at", "expected"),
    [
        (datetime(2030, 1, 1, tzinfo=UTC), "due"),
        (datetime(2029, 12, 31, 23, 59, tzinfo=UTC), "overdue"),
        (datetime(2030, 1, 1, 0, 1, tzinfo=UTC), "scheduled"),
    ],
)
def test_follow_up_status_handles_time_boundaries(
    due_at: datetime,
    expected: str,
) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    follow_up = FollowUp(
        id=1,
        customer_id=1,
        summary="Call back",
        due_at=due_at,
        completed_at=None,
    )

    assert follow_up_status(follow_up, now=now) == expected


def test_follow_up_status_prioritizes_completion_and_rejects_naive_clock() -> None:
    follow_up = FollowUp(
        id=1,
        customer_id=1,
        summary="Call back",
        due_at=datetime(2029, 1, 1, tzinfo=UTC),
        completed_at=datetime(2029, 1, 2, tzinfo=UTC),
    )

    assert (
        follow_up_status(follow_up, now=datetime(2030, 1, 1, tzinfo=UTC)) == "completed"
    )
    with pytest.raises(RuleViolation):
        follow_up_status(follow_up, now=datetime(2030, 1, 1))


@pytest.mark.django_db
def test_schedule_follow_up_trims_summary_and_accepts_due_time_equality() -> None:
    customer = _create_customer()
    now = datetime(2030, 1, 1, tzinfo=UTC)

    follow_up_id = schedule_follow_up(
        customer.pk,
        summary=" Call back ",
        due_at=now,
        now=now,
    )

    record = FollowUpRecord.objects.get(pk=follow_up_id)
    assert record.customer_id == customer.pk
    assert record.summary == "Call back"
    assert record.due_at == now
    assert record.completed_at is None


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
def test_schedule_rejects_invalid_values_without_writing(
    summary: str,
    due_at: datetime,
    now: datetime,
) -> None:
    customer = _create_customer()

    with pytest.raises(RuleViolation):
        schedule_follow_up(customer.pk, summary=summary, due_at=due_at, now=now)

    assert FollowUpRecord.objects.count() == 0


@pytest.mark.django_db
def test_schedule_missing_customer_raises_model_does_not_exist() -> None:
    with pytest.raises(Customer.DoesNotExist):
        schedule_follow_up(
            999,
            summary="Call back",
            due_at=datetime(2030, 1, 2, tzinfo=UTC),
            now=datetime(2030, 1, 1, tzinfo=UTC),
        )


@pytest.mark.django_db
def test_complete_follow_up_is_idempotent() -> None:
    customer = _create_customer()
    record = FollowUpRecord.objects.create(
        customer=customer,
        summary="Call back",
        due_at=datetime(2030, 1, 2, tzinfo=UTC),
    )
    first_time = datetime(2030, 1, 3, tzinfo=UTC)

    complete_follow_up(record.pk, now=first_time)
    complete_follow_up(record.pk, now=datetime(2030, 1, 4, tzinfo=UTC))

    record.refresh_from_db()
    assert record.completed_at == first_time


@pytest.mark.django_db
def test_list_follow_ups_puts_pending_before_completed_and_sorts_groups() -> None:
    customer = _create_customer()
    completed_late = FollowUpRecord.objects.create(
        customer=customer,
        summary="Completed late",
        due_at=datetime(2030, 1, 4, tzinfo=UTC),
        completed_at=datetime(2030, 1, 5, tzinfo=UTC),
    )
    pending_late = FollowUpRecord.objects.create(
        customer=customer,
        summary="Pending late",
        due_at=datetime(2030, 1, 3, tzinfo=UTC),
    )
    completed_early = FollowUpRecord.objects.create(
        customer=customer,
        summary="Completed early",
        due_at=datetime(2030, 1, 1, tzinfo=UTC),
        completed_at=datetime(2030, 1, 2, tzinfo=UTC),
    )
    pending_early = FollowUpRecord.objects.create(
        customer=customer,
        summary="Pending early",
        due_at=datetime(2030, 1, 2, tzinfo=UTC),
    )

    result = list_follow_ups(customer.pk)

    assert [follow_up.id for follow_up in result] == [
        pending_early.pk,
        pending_late.pk,
        completed_early.pk,
        completed_late.pk,
    ]


@pytest.mark.django_db
def test_follow_up_views_create_and_complete(client) -> None:
    customer = _create_customer()
    create_url = reverse("crm:follow_up_create", args=[customer.pk])

    get_response = client.get(create_url)
    assert get_response.status_code == 200
    assert b"in UTC" in get_response.content

    response = client.post(
        create_url,
        {"summary": "Call back", "due_at": "2030-01-02T12:00"},
    )
    record = FollowUpRecord.objects.get()
    assert response.status_code == 302
    assert record.due_at == datetime(2030, 1, 2, 12, tzinfo=UTC)

    completion_url = reverse("crm:follow_up_complete", args=[record.pk])
    assert client.get(completion_url).status_code == 405
    complete_response = client.post(completion_url)
    assert complete_response.status_code == 302
    record.refresh_from_db()
    assert record.completed_at is not None


@pytest.mark.django_db
def test_follow_up_views_reject_invalid_schedule_and_require_csrf() -> None:
    customer = _create_customer()
    url = reverse("crm:follow_up_create", args=[customer.pk])
    client = Client()
    response = client.post(url, {"summary": " ", "due_at": "2030-01-02T12:00"})
    assert response.status_code == 200
    assert FollowUpRecord.objects.count() == 0

    protected_client = Client(enforce_csrf_checks=True)
    response = protected_client.post(
        url,
        {"summary": "Call back", "due_at": "2030-01-02T12:00"},
    )
    assert response.status_code == 403
    assert FollowUpRecord.objects.count() == 0


@pytest.mark.django_db
def test_follow_up_views_return_404_for_missing_records(client) -> None:
    assert client.get(reverse("crm:follow_up_create", args=[999])).status_code == 404
    assert client.post(reverse("crm:follow_up_complete", args=[999])).status_code == 404
