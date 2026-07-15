import pytest

from semi.domain.models import JobStatus, OrderStatus
from semi.storage.exceptions import NotFoundError


def test_sample_repo_create_and_get(sample_repo):
    created = sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    assert created.stock_quantity == 0
    fetched = sample_repo.get_by_id("S1")
    assert fetched == created


def test_sample_repo_get_missing_raises_not_found(sample_repo):
    with pytest.raises(NotFoundError):
        sample_repo.get_by_id("missing")


def test_sample_repo_exists(sample_repo):
    assert sample_repo.exists("S1") is False
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    assert sample_repo.exists("S1") is True


def test_sample_repo_increment_and_decrement_stock(sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 5)
    assert sample_repo.get_by_id("S1").stock_quantity == 5
    sample_repo.decrement_stock("S1", 2)
    assert sample_repo.get_by_id("S1").stock_quantity == 3


def test_sample_repo_search_by_name(sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.create("S2", "Die B", 5.0, 0.8)
    assert [s.sample_id for s in sample_repo.search_by_name("Wafer")] == ["S1"]


def test_order_repo_create_assigns_incrementing_ids(order_repo):
    first = order_repo.create("S1", "ACME", 3)
    second = order_repo.create("S1", "ACME", 4)
    assert first.order_id == 1
    assert second.order_id == 2
    assert first.status == OrderStatus.RESERVED


def test_order_repo_get_missing_raises_not_found(order_repo):
    with pytest.raises(NotFoundError):
        order_repo.get_by_id(999)


def test_order_repo_update_status_and_list_by_status(order_repo):
    order = order_repo.create("S1", "ACME", 3)
    order_repo.update_status(order.order_id, OrderStatus.CONFIRMED)
    assert order_repo.get_by_id(order.order_id).status == OrderStatus.CONFIRMED
    assert [o.order_id for o in order_repo.list_by_status(OrderStatus.CONFIRMED)] == [
        order.order_id
    ]
    assert order_repo.list_by_status(OrderStatus.RESERVED) == []


def test_order_repo_sum_quantity_by_status(order_repo):
    a = order_repo.create("S1", "ACME", 3)
    b = order_repo.create("S1", "ACME", 4)
    order_repo.create("S2", "ACME", 100)
    order_repo.update_status(a.order_id, OrderStatus.CONFIRMED)
    order_repo.update_status(b.order_id, OrderStatus.CONFIRMED)
    assert order_repo.sum_quantity_by_status("S1", OrderStatus.CONFIRMED) == 7


def test_order_repo_sum_quantity_by_statuses(order_repo):
    a = order_repo.create("S1", "ACME", 3)
    b = order_repo.create("S1", "ACME", 4)
    order_repo.update_status(b.order_id, OrderStatus.CONFIRMED)
    total = order_repo.sum_quantity_by_statuses(
        "S1", (OrderStatus.RESERVED, OrderStatus.CONFIRMED)
    )
    assert total == 7
    assert a.status == OrderStatus.RESERVED


def test_job_repo_create_and_get_by_order_id(order_repo, job_repo):
    order = order_repo.create("S1", "ACME", 10)
    job = job_repo.create(
        order.order_id,
        "S1",
        shortfall_quantity=4,
        actual_quantity=5,
        total_duration_seconds=50.0,
    )
    assert job.status == JobStatus.QUEUED
    assert job.started_at is None
    assert job_repo.get_by_order_id(order.order_id) == job


def test_job_repo_get_by_order_id_missing_raises_not_found(job_repo):
    with pytest.raises(NotFoundError):
        job_repo.get_by_order_id(999)


def test_job_repo_list_producing_with_shortfall_joins_order_status(
    order_repo, job_repo
):
    producing_order = order_repo.create("S1", "ACME", 10)
    order_repo.update_status(producing_order.order_id, OrderStatus.PRODUCING)
    job_repo.create(
        producing_order.order_id,
        "S1",
        shortfall_quantity=4,
        actual_quantity=5,
        total_duration_seconds=50.0,
    )

    reserved_order = order_repo.create("S1", "ACME", 3)
    job_repo.create(
        reserved_order.order_id,
        "S1",
        shortfall_quantity=1,
        actual_quantity=1,
        total_duration_seconds=10.0,
    )

    pairs = job_repo.list_producing_with_shortfall("S1")
    assert pairs == [(10, 4)]


def test_job_repo_mark_in_progress_and_get_current_in_progress(order_repo, job_repo):
    order = order_repo.create("S1", "ACME", 10)
    job = job_repo.create(order.order_id, "S1", 4, 5, 50.0)
    assert job_repo.get_current_in_progress() is None
    import datetime as dt

    started_at = dt.datetime.now()
    job_repo.mark_in_progress(job.job_id, started_at)
    current = job_repo.get_current_in_progress()
    assert current.job_id == job.job_id
    assert current.status == JobStatus.IN_PROGRESS
    assert current.started_at == started_at


def test_job_repo_list_queued_fifo_orders_by_enqueued_at_then_job_id(
    order_repo, job_repo
):
    o1 = order_repo.create("S1", "ACME", 1)
    o2 = order_repo.create("S1", "ACME", 1)
    job_repo.create(o1.order_id, "S1", 1, 1, 10.0)
    job_repo.create(o2.order_id, "S1", 1, 1, 10.0)
    queued = job_repo.list_queued_fifo()
    assert [j.order_id for j in queued] == [o1.order_id, o2.order_id]


def test_job_repo_mark_done(order_repo, job_repo):
    order = order_repo.create("S1", "ACME", 10)
    job = job_repo.create(order.order_id, "S1", 4, 5, 50.0)
    job_repo.mark_done(job.job_id)
    assert job_repo.get_by_order_id(order.order_id).status == JobStatus.DONE


def test_repos_share_the_same_connection(conn, sample_repo, order_repo, job_repo):
    assert sample_repo.conn is conn
    assert order_repo.conn is conn
    assert job_repo.conn is conn
