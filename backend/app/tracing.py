"""Distributed tracing with OpenTelemetry.

Off unless an OTLP endpoint is configured (OTEL_EXPORTER_OTLP_ENDPOINT), so a laptop, the unit
tests and the CI cluster run exactly as before. When it is on, every API request becomes a trace:
one span for the request, and one span for each database statement under it. The trace id is
written into every log line of the request and returned in the X-Trace-Id header, so a slow
request can be followed from a user's report or a latency alert to the trace in Tempo and to its
log lines in Loki.

A provider is created for the application and passed to the instrumentation explicitly, instead
of being installed as the global provider. That keeps the tests independent of each other,
because OpenTelemetry allows the global provider to be set only once per process.
"""

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import SpanKind, Status, StatusCode
from sqlalchemy import Engine, event

from .config import Settings

logger = logging.getLogger("campusslot")

# The probes and the metrics endpoint would only add noise: a trace of every readiness check is
# not a trace of a user.
EXCLUDED_URLS = "health,ready,metrics"


def build_provider(settings: Settings, exporter: SpanExporter | None = None) -> TracerProvider:
    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": settings.git_sha,
            "deployment.environment": settings.app_env,
        }
    )
    # The decision of a caller is respected (ParentBased), and otherwise a share of the traces
    # is kept.
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.otel_traces_sampler_arg)),
    )
    if exporter is not None:
        # Tests: no network, and the spans are available at once.
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
    return provider


def setup_tracing(
    app: FastAPI, settings: Settings, exporter: SpanExporter | None = None
) -> TracerProvider | None:
    """Instrument the app, and return the provider, or None when tracing is off."""
    if not settings.otel_exporter_otlp_endpoint and exporter is None:
        return None
    provider = build_provider(settings, exporter)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls=EXCLUDED_URLS)
    app.state.tracer_provider = provider
    logger.info(
        "tracing is on: service %s, %.0f percent of the traces are kept",
        settings.otel_service_name,
        settings.otel_traces_sampler_arg * 100,
    )
    return provider


def instrument_engine(engine: Engine, provider: TracerProvider) -> None:
    """One span per database statement, as a child of the request that ran it.

    It uses the events of SQLAlchemy itself and not the opentelemetry-instrumentation-sqlalchemy
    package, which only supports SQLAlchemy older than 2.1 while this application runs 2.1. The
    statement text is recorded with its placeholders, never with the values that were bound to
    them, so no booking data ends up in a trace. A statement outside a traced request (the
    readiness check, a migration) gets no span, because it would be a trace of its own.
    """
    tracer = provider.get_tracer("campusslot.database")

    @event.listens_for(engine, "before_cursor_execute")
    def start(conn, cursor, statement, parameters, context, executemany):
        stack = conn.info.setdefault("campusslot_spans", [])
        if not trace.get_current_span().get_span_context().is_valid:
            stack.append(None)  # keeps the start and the end of the statements paired
            return
        stack.append(
            tracer.start_span(
                statement.split(None, 1)[0].upper() if statement.strip() else "SQL",
                kind=SpanKind.CLIENT,
                attributes={"db.system": engine.dialect.name, "db.statement": statement[:1000]},
            )
        )

    @event.listens_for(engine, "after_cursor_execute")
    def finish(conn, cursor, statement, parameters, context, executemany):
        stack = conn.info.get("campusslot_spans")
        span = stack.pop() if stack else None
        if span is not None:
            span.end()

    @event.listens_for(engine, "handle_error")
    def failed(exception_context):
        connection = exception_context.connection
        stack = connection.info.get("campusslot_spans") if connection is not None else None
        span = stack.pop() if stack else None
        if span is not None:
            error = exception_context.original_exception
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            span.end()
