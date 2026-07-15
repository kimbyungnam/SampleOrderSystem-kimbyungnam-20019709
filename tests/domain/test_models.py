import dataclasses
from datetime import UTC, datetime
from enum import StrEnum

import pytest

from semi.domain.models import JobStatus, Order, OrderStatus, Sample


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


def _make_order(**overrides):
    fields = {
        "order_id": 1,
        "sample_id": "SMP-001",
        "customer_name": "Acme Labs",
        "quantity": 5,
        "status": OrderStatus.RESERVED,
        "created_at": datetime(2026, 7, 15, 9, 0, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    return Order(**fields)


def test_order_holds_all_fields():
    order = _make_order()
    assert order.order_id == 1
    assert order.sample_id == "SMP-001"
    assert order.customer_name == "Acme Labs"
    assert order.quantity == 5
    assert order.status == OrderStatus.RESERVED
    assert order.created_at == datetime(2026, 7, 15, 9, 0, 0, tzinfo=UTC)


def test_order_is_frozen():
    order = _make_order()
    with pytest.raises(dataclasses.FrozenInstanceError):
        order.status = OrderStatus.CONFIRMED


def test_order_created_at_is_datetime_not_str():
    order = _make_order()
    assert isinstance(order.created_at, datetime)
