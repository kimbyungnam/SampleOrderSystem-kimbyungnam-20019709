import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from semi.domain.models import OrderStatus, ProductionJob
from semi.services.transactional import TransactionalMixin


@dataclass(frozen=True)
class ProductionJobStatus:
    job: ProductionJob
    progress_ratio: float
    produced_so_far: int
    estimated_completion_at: datetime


class ProductionService(TransactionalMixin):
    def __init__(self, order_repo, job_repo, sample_repo, lock):
        assert order_repo.conn is sample_repo.conn, (
            "OrderRepository and SampleRepository must share the same connection"
        )
        assert order_repo.conn is job_repo.conn, (
            "OrderRepository and ProductionJobRepository must share the same connection"
        )
        self._order_repo = order_repo
        self._job_repo = job_repo
        self._sample_repo = sample_repo
        self._lock = lock

    def tick(self) -> None:
        with self._transaction():
            self._promote_if_idle()
            current = self._job_repo.get_current_in_progress()
            if current is not None:
                elapsed = (datetime.now() - current.started_at).total_seconds()
                if elapsed >= current.total_duration_seconds:
                    self._sample_repo.increment_stock(
                        current.sample_id, current.actual_quantity
                    )
                    self._order_repo.update_status(
                        current.order_id, OrderStatus.CONFIRMED
                    )
                    self._job_repo.mark_done(current.job_id)
                    self._promote_if_idle()

    def _promote_if_idle(self) -> None:
        if self._job_repo.get_current_in_progress() is not None:
            return
        queue = self._job_repo.list_queued_fifo()
        if queue:
            self._job_repo.mark_in_progress(queue[0].job_id, datetime.now())

    def get_current_status(self) -> ProductionJobStatus | None:
        job = self._job_repo.get_current_in_progress()
        if job is None:
            return None
        now = datetime.now()
        elapsed = (now - job.started_at).total_seconds()
        progress_ratio = min(1.0, elapsed / job.total_duration_seconds)
        produced_so_far = math.floor(progress_ratio * job.actual_quantity)
        estimated_completion_at = job.started_at + timedelta(
            seconds=job.total_duration_seconds
        )
        return ProductionJobStatus(
            job, progress_ratio, produced_so_far, estimated_completion_at
        )

    def list_queue_status(self) -> list[ProductionJobStatus]:
        now = datetime.now()
        current = self._job_repo.get_current_in_progress()
        cumulative_seconds = 0.0
        if current is not None:
            elapsed = (now - current.started_at).total_seconds()
            cumulative_seconds = max(0.0, current.total_duration_seconds - elapsed)

        statuses = []
        for job in self._job_repo.list_queued_fifo():
            cumulative_seconds += job.total_duration_seconds
            estimated_completion_at = now + timedelta(seconds=cumulative_seconds)
            statuses.append(ProductionJobStatus(job, 0.0, 0, estimated_completion_at))
        return statuses
