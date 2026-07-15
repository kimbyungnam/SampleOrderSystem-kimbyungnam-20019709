import pytest

from semi.domain.models import OrderStatus
from semi.services.exceptions import DomainError
from semi.services.order_service import OrderService
from semi.storage.exceptions import NotFoundError


@pytest.fixture
def order_service(order_repo, job_repo, sample_repo, lock):
    return OrderService(order_repo, job_repo, sample_repo, lock)


def test_constructor_asserts_shared_connection(job_repo, sample_repo, lock):
    from tests.conftest import FakeOrderRepository, FakeConnection

    mismatched_order_repo = FakeOrderRepository(FakeConnection())
    with pytest.raises(AssertionError):
        OrderService(mismatched_order_repo, job_repo, sample_repo, lock)


def test_create_order_rejects_non_positive_quantity(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    with pytest.raises(DomainError):
        order_service.create_order("S1", "ACME", 0)
    with pytest.raises(DomainError):
        order_service.create_order("S1", "ACME", -3)


def test_create_order_rejects_unknown_sample_id(order_service):
    with pytest.raises(DomainError):
        order_service.create_order("unknown", "ACME", 3)


def test_create_order_creates_reserved_order(order_service, sample_repo, order_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_service.create_order("S1", "ACME", 3)
    assert order.status == OrderStatus.RESERVED
    assert order.sample_id == "S1"
    assert order.quantity == 3
    assert order_repo.conn.committed is True


def test_reject_transitions_reserved_order_to_rejected(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_service.create_order("S1", "ACME", 3)
    rejected = order_service.reject(order.order_id)
    assert rejected.status == OrderStatus.REJECTED


def test_reject_non_reserved_order_raises_domain_error(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_service.create_order("S1", "ACME", 3)
    order_service.reject(order.order_id)
    with pytest.raises(DomainError):
        order_service.reject(order.order_id)


def test_reject_unknown_order_raises_not_found(order_service):
    with pytest.raises(NotFoundError):
        order_service.reject(999)


def test_approve_non_reserved_order_raises_domain_error(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_service.create_order("S1", "ACME", 3)
    order_service.reject(order.order_id)
    with pytest.raises(DomainError):
        order_service.approve(order.order_id)


def test_approve_confirms_order_when_stock_sufficient(order_service, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 10)
    order = order_service.create_order("S1", "ACME", 3)
    approved = order_service.approve(order.order_id)
    assert approved.status == OrderStatus.CONFIRMED
    assert (
        sample_repo.get_by_id("S1").stock_quantity == 10
    )  # stock untouched at approval


def test_approve_confirms_order_when_available_stock_exactly_matches_quantity(
    order_service, sample_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 3)
    order = order_service.create_order("S1", "ACME", 3)
    approved = order_service.approve(order.order_id)
    assert approved.status == OrderStatus.CONFIRMED


def test_approve_excludes_confirmed_orders_from_available_stock(
    order_service, sample_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 10)
    already_confirmed = order_service.create_order("S1", "ACME", 8)
    order_service.approve(already_confirmed.order_id)  # available 10 >= 8 -> CONFIRMED

    new_order = order_service.create_order("S1", "ACME", 3)
    approved = order_service.approve(new_order.order_id)  # available = 10 - 8 = 2 < 3
    assert approved.status == OrderStatus.PRODUCING


def test_approve_queues_production_job_when_stock_insufficient(
    order_service, sample_repo, job_repo
):
    sample_repo.create(
        "S1", "Wafer A", 10.0, 0.9
    )  # avg_production_seconds=10, yield_rate=0.9
    order = order_service.create_order("S1", "ACME", 5)  # available = 0 -> shortfall 5

    approved = order_service.approve(order.order_id)

    assert approved.status == OrderStatus.PRODUCING
    job = job_repo.get_by_order_id(order.order_id)
    assert job.shortfall_quantity == 5
    assert job.actual_quantity == 6  # ceil(5 / 0.9) == 6
    assert job.total_duration_seconds == 60.0  # 10 * 6


def test_approve_excludes_producing_orders_original_stock_claim_from_available_stock(
    order_service, sample_repo, job_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 1.0)
    sample_repo.increment_stock("S1", 3)
    first = order_service.create_order("S1", "ACME", 5)
    order_service.approve(first.order_id)
    # available = 3 -> shortfall = 5 - 3 = 2 -> PRODUCING
    # claim = quantity - shortfall = 5 - 2 = 3 (non-zero: this is what must be
    # subtracted from available stock for later approvals)
    first_job = job_repo.get_by_order_id(first.order_id)
    assert first_job.shortfall_quantity == 2

    second = order_service.create_order("S1", "ACME", 3)
    approved = order_service.approve(second.order_id)
    # available = stock(3) - confirmed(0) - producing_claim(3) = 0 < 3 -> PRODUCING
    # if the claim were not subtracted (e.g. bugged to 0), available would be
    # 3 >= 3 and this would incorrectly come out CONFIRMED instead.
    assert approved.status == OrderStatus.PRODUCING
