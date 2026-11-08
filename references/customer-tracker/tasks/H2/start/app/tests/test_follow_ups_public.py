from datetime import UTC, datetime

import pytest
from crm.domain import FollowUp, follow_up_status


def test_follow_up_status_uses_explicit_clock_boundaries() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    follow_up = FollowUp(
        id=1,
        customer_id=1,
        summary="Call back",
        due_at=now,
        completed_at=None,
    )

    assert follow_up_status(follow_up, now=now) == "due"


def test_follow_up_status_rejects_naive_clock() -> None:
    follow_up = FollowUp(
        id=1,
        customer_id=1,
        summary="Call back",
        due_at=datetime(2030, 1, 1, tzinfo=UTC),
        completed_at=None,
    )

    with pytest.raises(ValueError):
        follow_up_status(follow_up, now=datetime(2030, 1, 1))
