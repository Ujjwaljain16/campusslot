import json
import logging

from app.logging_config import JsonFormatter


def _record(message: str, **extra) -> logging.LogRecord:
    record = logging.LogRecord("campusslot", logging.INFO, __file__, 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_writes_one_json_object_with_extra_fields():
    line = JsonFormatter().format(_record("request", method="GET", status=200))

    data = json.loads(line)
    assert data["message"] == "request"
    assert data["level"] == "INFO"
    assert data["method"] == "GET"
    assert data["status"] == 200
    assert data["time"].endswith("+00:00")


def test_json_formatter_does_not_leak_logging_internals():
    data = json.loads(JsonFormatter().format(_record("hello")))

    assert set(data) == {"time", "level", "logger", "message"}


def test_requests_are_logged_but_probe_endpoints_are_not(client, caplog):
    with caplog.at_level(logging.INFO, logger="campusslot"):
        client.get("/health")
        client.get("/ready")
        client.get("/api/rooms")

    logged_paths = [r.path for r in caplog.records if r.getMessage() == "request"]
    assert logged_paths == ["/api/rooms"]


def test_rejected_booking_is_logged_with_the_layer(client, room, caplog):
    body = {
        "room_id": room["id"],
        "purpose": "First",
        "booked_by": "Prof. Rao",
        "start_time": "2030-05-01T10:00:00Z",
        "end_time": "2030-05-01T11:00:00Z",
    }
    assert client.post("/api/bookings", json=body).status_code == 201

    with caplog.at_level(logging.WARNING, logger="campusslot"):
        assert client.post("/api/bookings", json=body).status_code == 409

    rejected = [r for r in caplog.records if r.getMessage().startswith("booking rejected")]
    assert len(rejected) == 1
    assert rejected[0].layer == "application"
    assert rejected[0].blocking_booking_id is not None
