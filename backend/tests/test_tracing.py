import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

import app.main as main_module
from app.db import get_db
from app.logging_config import JsonFormatter
from app.tracing import instrument_engine, setup_tracing


@pytest.fixture()
def traced(db_session):
    """A separate app with tracing on and an in-memory exporter, so that the shared app and the
    other tests are never instrumented."""
    exporter = InMemorySpanExporter()
    application = main_module.create_app()
    provider = setup_tracing(application, main_module.settings, exporter=exporter)
    instrument_engine(db_session.get_bind(), provider)

    def override_get_db():
        yield db_session

    application.dependency_overrides[get_db] = override_get_db
    with TestClient(application) as test_client:
        yield test_client, exporter


def test_tracing_is_off_without_an_endpoint():
    assert main_module.settings.otel_exporter_otlp_endpoint == ""
    assert setup_tracing(FastAPI(), main_module.settings) is None


def test_a_request_is_one_trace_with_the_route_and_its_database_statements(traced):
    client, exporter = traced
    assert client.get("/api/rooms").status_code == 200
    spans = exporter.get_finished_spans()

    server = [s for s in spans if s.attributes.get("http.route") == "/api/rooms"]
    assert server, [s.name for s in spans]
    server_span = server[0]
    database = [s for s in spans if s.attributes.get("db.system") == "sqlite"]
    assert database, "no database span: the engine was not instrumented"
    # The statements belong to the trace of the request that ran them.
    assert {s.context.trace_id for s in database} == {server_span.context.trace_id}
    # The resource names the service and the build, which is how a trace is found by version.
    assert server_span.resource.attributes["service.name"] == "campusslot-backend"
    assert "service.version" in server_span.resource.attributes


def test_the_probes_are_not_traced(traced):
    client, exporter = traced
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/metrics").status_code == 200
    assert exporter.get_finished_spans() == ()


def test_the_response_names_its_trace(traced):
    client, exporter = traced
    response = client.get("/api/rooms")
    server_span = next(
        s for s in exporter.get_finished_spans() if s.attributes.get("http.route") == "/api/rooms"
    )
    assert response.headers["X-Trace-Id"] == format(server_span.context.trace_id, "032x")


def test_a_failed_request_marks_its_span_as_an_error(traced, monkeypatch):
    client, exporter = traced
    monkeypatch.setattr(main_module.settings, "fault_error_rate", 1.0)
    assert client.get("/api/rooms").status_code == 500
    server_spans = [s for s in exporter.get_finished_spans() if s.kind == trace.SpanKind.SERVER]
    assert server_spans[-1].status.status_code == StatusCode.ERROR


def test_the_log_line_of_a_request_carries_the_trace_id(traced):
    client, _ = traced
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            lines.append(JsonFormatter().format(record))

    handler = Capture()
    logger = logging.getLogger("campusslot")
    logger.addHandler(handler)
    try:
        response = client.get("/api/rooms")
    finally:
        logger.removeHandler(handler)

    request_lines = [json.loads(line) for line in lines if '"message": "request"' in line]
    assert request_lines, lines
    assert request_lines[0]["trace_id"] == response.headers["X-Trace-Id"]
    assert len(request_lines[0]["span_id"]) == 16


def test_a_log_line_outside_a_trace_has_no_trace_id():
    record = logging.makeLogRecord({"msg": "outside", "levelname": "INFO", "name": "campusslot"})
    assert "trace_id" not in json.loads(JsonFormatter().format(record))
