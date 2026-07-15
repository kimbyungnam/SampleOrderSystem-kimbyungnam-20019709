import dataclasses
from datetime import datetime

import pytest

from semi.domain.models import JobStatus, Order, OrderStatus, ProductionJob, Sample


def test_order_status_values():
    assert list(OrderStatus) == [
        OrderStatus.RESERVED,
        OrderStatus.REJECTED,
        OrderStatus.PRODUCING,
        OrderStatus.CONFIRMED,
        OrderStatus.RELEASE,
    ]
    assert OrderStatus.RESERVED == "RESERVED"


def test_job_status_values():
    assert list(JobStatus) == [JobStatus.QUEUED, JobStatus.IN_PROGRESS, JobStatus.DONE]
    assert JobStatus.QUEUED == "QUEUED"


def test_sample_is_frozen():
    sample = Sample(
        sample_id="S1",
        name="Wafer A",
        avg_production_seconds=10.0,
        yield_rate=0.9,
        stock_quantity=5,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        sample.stock_quantity = 6


def test_order_is_frozen():
    order = Order(
        order_id=1,
        sample_id="S1",
        customer_name="ACME",
        quantity=3,
        status=OrderStatus.RESERVED,
        created_at=datetime.now(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        order.status = OrderStatus.REJECTED


def test_production_job_is_frozen_and_allows_none_started_at():
    job = ProductionJob(
        job_id=1,
        order_id=1,
        sample_id="S1",
        shortfall_quantity=2,
        actual_quantity=3,
        total_duration_seconds=30.0,
        status=JobStatus.QUEUED,
        enqueued_at=datetime.now(),
        started_at=None,
    )
    assert job.started_at is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        job.status = JobStatus.IN_PROGRESS
