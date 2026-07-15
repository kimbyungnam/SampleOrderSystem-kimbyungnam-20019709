import sqlite3
from datetime import datetime

from semi.domain.models import Order, OrderStatus
from semi.storage._datetime import from_iso, to_iso
from semi.storage.exceptions import NotFoundError


class OrderRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, sample_id: str, customer_name: str, quantity: int) -> Order:
        cursor = self.conn.execute(
            "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                sample_id,
                customer_name,
                quantity,
                OrderStatus.RESERVED,
                to_iso(datetime.now()),
            ),
        )
        return self.get_by_id(cursor.lastrowid)

    def get_by_id(self, order_id: int) -> Order:
        row = self.conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"order_id={order_id!r} not found")
        return _row_to_order(row)

    def list_by_status(self, status: OrderStatus) -> list[Order]:
        rows = self.conn.execute(
            "SELECT * FROM orders WHERE status = ?", (status,)
        ).fetchall()
        return [_row_to_order(row) for row in rows]

    def update_status(self, order_id: int, status: OrderStatus) -> None:
        self.conn.execute(
            "UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id)
        )

    def sum_quantity_by_status(self, sample_id: str, status: OrderStatus) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
            "WHERE sample_id = ? AND status = ?",
            (sample_id, status),
        ).fetchone()
        return row["total"]

    def sum_quantity_by_statuses(
        self, sample_id: str, statuses: list[OrderStatus]
    ) -> int:
        placeholders = ",".join("?" for _ in statuses)
        row = self.conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
            f"WHERE sample_id = ? AND status IN ({placeholders})",
            (sample_id, *statuses),
        ).fetchone()
        return row["total"]


def _row_to_order(row: sqlite3.Row) -> Order:
    return Order(
        order_id=row["order_id"],
        sample_id=row["sample_id"],
        customer_name=row["customer_name"],
        quantity=row["quantity"],
        status=OrderStatus(row["status"]),
        created_at=from_iso(row["created_at"]),
    )
