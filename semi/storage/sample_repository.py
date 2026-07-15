import sqlite3

from semi.domain.models import Sample
from semi.storage.exceptions import NotFoundError


class SampleRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(
        self,
        sample_id: str,
        name: str,
        avg_production_seconds: float,
        yield_rate: float,
    ) -> Sample:
        self.conn.execute(
            "INSERT INTO samples "
            "(sample_id, name, avg_production_seconds, yield_rate, stock_quantity) "
            "VALUES (?, ?, ?, ?, 0)",
            (sample_id, name, avg_production_seconds, yield_rate),
        )
        return self.get_by_id(sample_id)

    def get_by_id(self, sample_id: str) -> Sample:
        row = self.conn.execute(
            "SELECT * FROM samples WHERE sample_id = ?", (sample_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"sample_id={sample_id!r} not found")
        return _row_to_sample(row)

    def exists(self, sample_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM samples WHERE sample_id = ?", (sample_id,)
        ).fetchone()
        return row is not None

    def list_all(self) -> list[Sample]:
        rows = self.conn.execute("SELECT * FROM samples").fetchall()
        return [_row_to_sample(row) for row in rows]

    def search_by_name(self, query: str) -> list[Sample]:
        rows = self.conn.execute(
            "SELECT * FROM samples WHERE name LIKE ?", (f"%{query}%",)
        ).fetchall()
        return [_row_to_sample(row) for row in rows]

    def increment_stock(self, sample_id: str, amount: int) -> None:
        self.conn.execute(
            "UPDATE samples SET stock_quantity = stock_quantity + ? WHERE sample_id = ?",
            (amount, sample_id),
        )

    def decrement_stock(self, sample_id: str, amount: int) -> None:
        self.conn.execute(
            "UPDATE samples SET stock_quantity = stock_quantity - ? WHERE sample_id = ?",
            (amount, sample_id),
        )


def _row_to_sample(row: sqlite3.Row) -> Sample:
    return Sample(
        sample_id=row["sample_id"],
        name=row["name"],
        avg_production_seconds=row["avg_production_seconds"],
        yield_rate=row["yield_rate"],
        stock_quantity=row["stock_quantity"],
    )
