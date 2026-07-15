import sqlite3
from pathlib import Path

import pytest

from semi.storage.db import connect_db


def test_connect_db_creates_schema(tmp_path: Path) -> None:
    conn = connect_db(tmp_path / "test.db")
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"samples", "orders", "production_jobs"} <= tables
    conn.close()


def test_connect_db_sets_wal_mode(tmp_path: Path) -> None:
    conn = connect_db(tmp_path / "test.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    conn.close()


def test_connect_db_is_idempotent_and_reopens_existing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn1 = connect_db(db_path)
    conn1.execute(
        "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate) "
        "VALUES ('S1', 'wafer', 10.0, 0.9)"
    )
    conn1.commit()
    conn1.close()

    conn2 = connect_db(db_path)
    row = conn2.execute("SELECT * FROM samples WHERE sample_id = 'S1'").fetchone()
    assert row["name"] == "wafer"
    conn2.close()


def test_samples_check_constraints_reject_invalid_values(tmp_path: Path) -> None:
    conn = connect_db(tmp_path / "test.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate, stock_quantity) "
            "VALUES ('S1', 'wafer', 0, 0.9, 0)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate, stock_quantity) "
            "VALUES ('S2', 'wafer', 10.0, 1.5, 0)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate, stock_quantity) "
            "VALUES ('S3', 'wafer', 10.0, 0.9, -1)"
        )
    conn.close()


def test_orders_check_constraints_reject_invalid_values(tmp_path: Path) -> None:
    conn = connect_db(tmp_path / "test.db")
    conn.execute(
        "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate) "
        "VALUES ('S1', 'wafer', 10.0, 0.9)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
            "VALUES ('S1', 'acme', 0, 'RESERVED', '2026-01-01T00:00:00')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
            "VALUES ('S1', 'acme', 5, 'BOGUS', '2026-01-01T00:00:00')"
        )
    conn.close()


def test_production_jobs_check_constraint_rejects_invalid_status(
    tmp_path: Path,
) -> None:
    conn = connect_db(tmp_path / "test.db")
    conn.execute(
        "INSERT INTO samples (sample_id, name, avg_production_seconds, yield_rate) "
        "VALUES ('S1', 'wafer', 10.0, 0.9)"
    )
    conn.execute(
        "INSERT INTO orders (sample_id, customer_name, quantity, status, created_at) "
        "VALUES ('S1', 'acme', 5, 'RESERVED', '2026-01-01T00:00:00')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO production_jobs "
            "(order_id, sample_id, shortfall_quantity, actual_quantity, "
            "total_duration_seconds, status, enqueued_at) "
            "VALUES (1, 'S1', 2, 3, 30.0, 'BOGUS', '2026-01-01T00:00:00')"
        )
    conn.close()
