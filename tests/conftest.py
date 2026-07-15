from dataclasses import replace
from datetime import datetime

import pytest

from semi.domain.models import JobStatus, Order, OrderStatus, ProductionJob, Sample
from semi.storage.exceptions import NotFoundError


class FakeConnection:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeSampleRepository:
    def __init__(self, conn):
        self.conn = conn
        self._samples: dict[str, Sample] = {}

    def create(self, sample_id, name, avg_production_seconds, yield_rate) -> Sample:
        sample = Sample(sample_id, name, avg_production_seconds, yield_rate, 0)
        self._samples[sample_id] = sample
        return sample

    def get_by_id(self, sample_id) -> Sample:
        try:
            return self._samples[sample_id]
        except KeyError:
            raise NotFoundError(sample_id) from None

    def exists(self, sample_id) -> bool:
        return sample_id in self._samples

    def list_all(self) -> list[Sample]:
        return list(self._samples.values())

    def search_by_name(self, query) -> list[Sample]:
        return [s for s in self._samples.values() if query in s.name]

    def increment_stock(self, sample_id, amount) -> None:
        sample = self.get_by_id(sample_id)
        self._samples[sample_id] = replace(
            sample, stock_quantity=sample.stock_quantity + amount
        )

    def decrement_stock(self, sample_id, amount) -> None:
        sample = self.get_by_id(sample_id)
        self._samples[sample_id] = replace(
            sample, stock_quantity=sample.stock_quantity - amount
        )


class FakeOrderRepository:
    def __init__(self, conn):
        self.conn = conn
        self._orders: dict[int, Order] = {}
        self._next_id = 1

    def create(self, sample_id, customer_name, quantity) -> Order:
        order = Order(
            order_id=self._next_id,
            sample_id=sample_id,
            customer_name=customer_name,
            quantity=quantity,
            status=OrderStatus.RESERVED,
            created_at=datetime.now(),
        )
        self._orders[order.order_id] = order
        self._next_id += 1
        return order

    def get_by_id(self, order_id) -> Order:
        try:
            return self._orders[order_id]
        except KeyError:
            raise NotFoundError(order_id) from None

    def list_by_status(self, status) -> list[Order]:
        return [o for o in self._orders.values() if o.status == status]

    def update_status(self, order_id, status) -> None:
        order = self.get_by_id(order_id)
        self._orders[order_id] = replace(order, status=status)

    def sum_quantity_by_status(self, sample_id, status) -> int:
        return sum(
            o.quantity
            for o in self._orders.values()
            if o.sample_id == sample_id and o.status == status
        )

    def sum_quantity_by_statuses(self, sample_id, statuses) -> int:
        return sum(
            o.quantity
            for o in self._orders.values()
            if o.sample_id == sample_id and o.status in statuses
        )


class FakeProductionJobRepository:
    def __init__(self, conn, order_repo):
        self.conn = conn
        self._order_repo = order_repo
        self._jobs: dict[int, ProductionJob] = {}
        self._next_id = 1

    def create(
        self,
        order_id,
        sample_id,
        shortfall_quantity,
        actual_quantity,
        total_duration_seconds,
    ) -> ProductionJob:
        job = ProductionJob(
            job_id=self._next_id,
            order_id=order_id,
            sample_id=sample_id,
            shortfall_quantity=shortfall_quantity,
            actual_quantity=actual_quantity,
            total_duration_seconds=total_duration_seconds,
            status=JobStatus.QUEUED,
            enqueued_at=datetime.now(),
            started_at=None,
        )
        self._jobs[job.job_id] = job
        self._next_id += 1
        return job

    def get_by_order_id(self, order_id) -> ProductionJob:
        for job in self._jobs.values():
            if job.order_id == order_id:
                return job
        raise NotFoundError(order_id)

    def list_producing_with_shortfall(self, sample_id) -> list[tuple[int, int]]:
        pairs = []
        for job in self._jobs.values():
            if job.sample_id != sample_id:
                continue
            order = self._order_repo.get_by_id(job.order_id)
            if order.status == OrderStatus.PRODUCING:
                pairs.append((order.quantity, job.shortfall_quantity))
        return pairs

    def get_current_in_progress(self) -> ProductionJob | None:
        for job in self._jobs.values():
            if job.status == JobStatus.IN_PROGRESS:
                return job
        return None

    def list_queued_fifo(self) -> list[ProductionJob]:
        queued = [j for j in self._jobs.values() if j.status == JobStatus.QUEUED]
        return sorted(queued, key=lambda j: (j.enqueued_at, j.job_id))

    def mark_in_progress(self, job_id, started_at) -> None:
        job = self._jobs[job_id]
        self._jobs[job_id] = replace(
            job, status=JobStatus.IN_PROGRESS, started_at=started_at
        )

    def mark_done(self, job_id) -> None:
        job = self._jobs[job_id]
        self._jobs[job_id] = replace(job, status=JobStatus.DONE)


@pytest.fixture
def conn():
    return FakeConnection()


@pytest.fixture
def sample_repo(conn):
    return FakeSampleRepository(conn)


@pytest.fixture
def order_repo(conn):
    return FakeOrderRepository(conn)


@pytest.fixture
def job_repo(conn, order_repo):
    return FakeProductionJobRepository(conn, order_repo)


@pytest.fixture
def lock():
    import threading

    return threading.Lock()
