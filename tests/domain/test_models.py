import dataclasses
from enum import StrEnum

import pytest

from semi.domain.models import JobStatus, OrderStatus, Sample


def test_order_status_is_str_enum():
    assert issubclass(OrderStatus, StrEnum)


def test_order_status_members_match_db_check_constraint():
    assert [member.value for member in OrderStatus] == [
        "RESERVED",
        "REJECTED",
        "PRODUCING",
        "CONFIRMED",
        "RELEASE",
    ]


def test_order_status_value_equals_member_name():
    assert OrderStatus.RESERVED.value == "RESERVED"
    assert OrderStatus.CONFIRMED == "CONFIRMED"


def test_job_status_is_str_enum():
    assert issubclass(JobStatus, StrEnum)


def test_job_status_members_match_db_check_constraint():
    assert [member.value for member in JobStatus] == ["QUEUED", "IN_PROGRESS", "DONE"]


def test_job_status_value_equals_member_name():
    assert JobStatus.QUEUED.value == "QUEUED"
    assert JobStatus.DONE == "DONE"


def _make_sample(**overrides):
    fields = {
        "sample_id": "SMP-001",
        "name": "Test Sample",
        "avg_production_seconds": 12.5,
        "yield_rate": 0.9,
        "stock_quantity": 10,
    }
    fields.update(overrides)
    return Sample(**fields)


def test_sample_holds_all_fields():
    sample = _make_sample()
    assert sample.sample_id == "SMP-001"
    assert sample.name == "Test Sample"
    assert sample.avg_production_seconds == 12.5
    assert sample.yield_rate == 0.9
    assert sample.stock_quantity == 10


def test_sample_is_frozen():
    sample = _make_sample()
    with pytest.raises(dataclasses.FrozenInstanceError):
        sample.stock_quantity = 999
