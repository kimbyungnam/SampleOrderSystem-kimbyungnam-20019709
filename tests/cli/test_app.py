import threading

from semi.cli.app import main
from semi.storage.db import connect_db


def test_main_initializes_db_starts_worker_and_exits_cleanly_on_zero(tmp_path, mocker):
    db_path = tmp_path / "app.db"
    mocker.patch("builtins.input", return_value="0")
    threads_before = set(threading.enumerate())

    main(db_path=db_path)

    new_daemon_threads = [
        t for t in set(threading.enumerate()) - threads_before if t.daemon
    ]
    assert len(new_daemon_threads) == 1
    assert new_daemon_threads[0].is_alive()

    conn = connect_db(db_path)
    assert conn.execute("SELECT * FROM samples").fetchall() == []
    conn.close()
