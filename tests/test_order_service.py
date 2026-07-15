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
