from __future__ import annotations

from core.db import emit_event, get_conn, query_events


def test_schema_creation_in_temp_db(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("VOZ_DB_PATH", str(db_path))

    with get_conn() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('tenants', 'events')"
            ).fetchall()
        }

    assert db_path.exists()
    assert tables == {"tenants", "events"}


def test_insert_event_and_query(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "events.sqlite3"
    monkeypatch.setenv("VOZ_DB_PATH", str(db_path))

    event_id = emit_event(
        tenant_id="tenant_a",
        rid="r-1",
        event_type="call.started",
        payload_dict={"x": 1},
        trace_id="tr-1",
    )
    rows = query_events("tenant_a")

    assert len(rows) == 1
    assert rows[0]["event_id"] == event_id
    assert rows[0]["tenant_id"] == "tenant_a"
    assert rows[0]["event_type"] == "call.started"
    assert rows[0]["payload"] == {"x": 1}
    assert rows[0]["trace_id"] == "tr-1"


def test_tenant_isolation(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "tenant_isolation.sqlite3"
    monkeypatch.setenv("VOZ_DB_PATH", str(db_path))

    emit_event("tenant_a", "r-1", "a.evt", {"tenant": "a"})
    emit_event("tenant_b", "r-2", "b.evt", {"tenant": "b"})

    a_rows = query_events("tenant_a")
    b_rows = query_events("tenant_b")

    assert len(a_rows) == 1
    assert len(b_rows) == 1
    assert a_rows[0]["tenant_id"] == "tenant_a"
    assert b_rows[0]["tenant_id"] == "tenant_b"


def test_idempotency_key_returns_existing_event(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "idempotency.sqlite3"
    monkeypatch.setenv("VOZ_DB_PATH", str(db_path))

    event_id_1 = emit_event(
        tenant_id="tenant_a",
        rid="r-1",
        event_type="evt",
        payload_dict={"v": 1},
        idempotency_key="key-1",
    )
    event_id_2 = emit_event(
        tenant_id="tenant_a",
        rid="r-1",
        event_type="evt",
        payload_dict={"v": 999},
        idempotency_key="key-1",
    )
    rows = query_events("tenant_a")

    assert event_id_1 == event_id_2
    assert len(rows) == 1
    assert rows[0]["payload"] == {"v": 1}
