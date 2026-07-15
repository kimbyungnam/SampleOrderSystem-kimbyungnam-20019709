import sqlite3
from datetime import datetime

from semi.domain.models import JobStatus, OrderStatus, ProductionJob
from semi.storage._datetime import from_iso, to_iso
from semi.storage.exceptions import NotFoundError


class ProductionJobRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(
        self,
        order_id: int,
        sample_id: str,
        shortfall_quantity: int,
        actual_quantity: int,
        total_duration_seconds: float,
    ) -> ProductionJob:
        self.conn.execute(
            "INSERT INTO production_jobs "
            "(order_id, sample_id, shortfall_quantity, actual_quantity, "
            "total_duration_seconds, status, enqueued_at, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                order_id,
                sample_id,
                shortfall_quantity,
                actual_quantity,
                total_duration_seconds,
                JobStatus.QUEUED,
                to_iso(datetime.now()),
            ),
        )
        return self.get_by_order_id(order_id)

    def get_by_order_id(self, order_id: int) -> ProductionJob:
        row = self.conn.execute(
            "SELECT * FROM production_jobs WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"order_id={order_id!r} has no production job")
        return _row_to_job(row)

    def list_producing_with_shortfall(self, sample_id: str) -> list[tuple[int, int]]:
        rows = self.conn.execute(
            "SELECT o.quantity, pj.shortfall_quantity FROM production_jobs pj "
            "JOIN orders o ON o.order_id = pj.order_id "
            "WHERE o.sample_id = ? AND o.status = ?",
            (sample_id, OrderStatus.PRODUCING),
        ).fetchall()
        return [(row["quantity"], row["shortfall_quantity"]) for row in rows]

    def get_current_in_progress(self) -> ProductionJob | None:
        row = self.conn.execute(
            "SELECT * FROM production_jobs WHERE status = ?", (JobStatus.IN_PROGRESS,)
        ).fetchone()
        return _row_to_job(row) if row is not None else None

    def list_queued_fifo(self) -> list[ProductionJob]:
        rows = self.conn.execute(
            "SELECT * FROM production_jobs WHERE status = ? ORDER BY enqueued_at, job_id",
            (JobStatus.QUEUED,),
        ).fetchall()
        return [_row_to_job(row) for row in rows]

    def mark_in_progress(self, job_id: int, started_at: datetime) -> None:
        self.conn.execute(
            "UPDATE production_jobs SET status = ?, started_at = ? WHERE job_id = ?",
            (JobStatus.IN_PROGRESS, to_iso(started_at), job_id),
        )

    def mark_done(self, job_id: int) -> None:
        self.conn.execute(
            "UPDATE production_jobs SET status = ? WHERE job_id = ?",
            (JobStatus.DONE, job_id),
        )


def _row_to_job(row: sqlite3.Row) -> ProductionJob:
    return ProductionJob(
        job_id=row["job_id"],
        order_id=row["order_id"],
        sample_id=row["sample_id"],
        shortfall_quantity=row["shortfall_quantity"],
        actual_quantity=row["actual_quantity"],
        total_duration_seconds=row["total_duration_seconds"],
        status=JobStatus(row["status"]),
        enqueued_at=from_iso(row["enqueued_at"]),
        started_at=from_iso(row["started_at"])
        if row["started_at"] is not None
        else None,
    )
