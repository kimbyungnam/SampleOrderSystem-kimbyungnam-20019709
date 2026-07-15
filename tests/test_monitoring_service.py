from semi.domain.models import OrderStatus
from semi.services.monitoring_service import MonitoringService, StockStatus


def make_service(order_repo, sample_repo):
    return MonitoringService(order_repo, sample_repo)


def test_count_by_status_excludes_rejected(order_repo, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order_repo.create("S1", "ACME", 1)
    confirmed = order_repo.create("S1", "ACME", 1)
    order_repo.update_status(confirmed.order_id, OrderStatus.CONFIRMED)
    rejected = order_repo.create("S1", "ACME", 1)
    order_repo.update_status(rejected.order_id, OrderStatus.REJECTED)

    service = make_service(order_repo, sample_repo)
    counts = service.count_by_status()

    assert counts == {
        OrderStatus.RESERVED: 1,
        OrderStatus.CONFIRMED: 1,
        OrderStatus.PRODUCING: 0,
        OrderStatus.RELEASE: 0,
    }
    assert OrderStatus.REJECTED not in counts


def test_list_by_status_delegates_to_repo(order_repo, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    order = order_repo.create("S1", "ACME", 1)
    service = make_service(order_repo, sample_repo)
    assert [o.order_id for o in service.list_by_status(OrderStatus.RESERVED)] == [
        order.order_id
    ]


def test_stock_status_depleted_takes_priority_over_outstanding(order_repo, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)  # stock stays 0

    service = make_service(order_repo, sample_repo)
    statuses = {s.sample.sample_id: s for s in service.stock_status()}

    assert statuses["S1"].status == StockStatus.DEPLETED
    assert statuses["S1"].outstanding == 0


def test_stock_status_sufficient_when_stock_covers_outstanding(order_repo, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 5)
    order_repo.create("S1", "ACME", 5)  # RESERVED, counts toward outstanding

    service = make_service(order_repo, sample_repo)
    status = next(s for s in service.stock_status() if s.sample.sample_id == "S1")

    assert status.outstanding == 5
    assert status.status == StockStatus.SUFFICIENT


def test_stock_status_short_when_stock_below_outstanding(order_repo, sample_repo):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 2)
    order_repo.create("S1", "ACME", 5)  # RESERVED

    service = make_service(order_repo, sample_repo)
    status = next(s for s in service.stock_status() if s.sample.sample_id == "S1")

    assert status.outstanding == 5
    assert status.status == StockStatus.SHORT


def test_stock_status_outstanding_includes_reserved_confirmed_and_producing_only(
    order_repo, sample_repo
):
    sample_repo.create("S1", "Wafer A", 10.0, 0.9)
    sample_repo.increment_stock("S1", 100)
    order_repo.create("S1", "ACME", 1)
    confirmed = order_repo.create("S1", "ACME", 2)
    order_repo.update_status(confirmed.order_id, OrderStatus.CONFIRMED)
    producing = order_repo.create("S1", "ACME", 3)
    order_repo.update_status(producing.order_id, OrderStatus.PRODUCING)
    released = order_repo.create("S1", "ACME", 4)
    order_repo.update_status(released.order_id, OrderStatus.RELEASE)
    rejected = order_repo.create("S1", "ACME", 5)
    order_repo.update_status(rejected.order_id, OrderStatus.REJECTED)

    service = make_service(order_repo, sample_repo)
    status = next(s for s in service.stock_status() if s.sample.sample_id == "S1")

    assert status.outstanding == 1 + 2 + 3
