# ADR 0018: Link metrics, traces and logs by one trace id

Status: accepted (v2)

## Context

In v1 there are three signals and no road between them. A latency alert says that the objective is breached. The dashboard shows a graph. The logs show lines. Nothing says **which** requests were slow, **where** their time went, or which lines belong to the same request, so finding the cause means guessing and searching by time. The burn rate alerts are good at saying *that* something is wrong, and say nothing about *what*.

## Options considered

- Keep the three signals apart and search by time stamp. It works for a quiet service and fails for a busy one.
- Put everything in one vendor's agent, which links the signals by itself. It is fast to set up and hides how the links work, and it needs an account and money.
- OpenTelemetry in the application, Tempo for the traces, and the **trace id as the key** that Grafana follows between Prometheus dashboards, Tempo and Loki.
- Exemplars on the latency histogram, so that a point of the graph links to a trace. It is the tightest link, and the metrics library of this application does not attach them, so it would mean replacing it. The dashboard links by search instead (a TraceQL query over the same period and the same threshold).

## Decision

- **The application writes the ids.** With `OTEL_EXPORTER_OTLP_ENDPOINT` set, every API request is a trace: a span for the request and one for each database statement. The trace id is added to every JSON log line of the request and to the `X-Trace-Id` response header. With nothing set, the code does not run, so CI and a laptop are unchanged.
- **The probes and the metrics endpoint are not traced.** They would be most of the traces and none of the interesting ones, and a database statement outside a request gets no span, because it would be an orphan trace.
- **Statements are traced with SQLAlchemy's own events**, not with the OpenTelemetry package for SQLAlchemy. That package supports only SQLAlchemy older than 2.1, this application runs 2.1, and the unit tests found it: the instrumentation switched itself off with a log line and no trace had a database span. Only the text of the statement is recorded, with its placeholders, never the bound values, so no booking data enters a trace.
- **Grafana does the linking.** The Loki data source has a derived field on `trace_id` that opens the trace in Tempo, and the Tempo data source opens the log lines of a span with a LogQL query on the same id. The SLO dashboard puts the three on one page: the objectives and the burn rate on top, then the slow and the failed traces of the same period, then the log lines of the failed or slow requests.
- **A drill proves the chain**: `scripts/trace-drill.sh` slows the application down and follows one request through all three.

## Consequences

- From a breached objective to the request, to where its time went, to its log lines: no guessing by time stamp. In the drill, the trace shows how much of a slow request was spent in the database, which points at the application or at the database.
- Tracing has a cost: a little CPU per request and a few extra dependencies in the image (all pinned and scanned). The sample ratio is a setting. The overhead is measured in the game day.
- Tempo keeps six hours of traces in memory, which is what a laptop can afford. A trace that is older than that cannot be opened from a log line.
- The link from a graph to a trace is by search and not by exemplar, so a graph point does not open its own trace. It opens the traces of the same period over the same threshold.
- The statement spans are written by this project and not by a library, so a change of SQLAlchemy that changes the events would need a change here. The tests cover it.

## What I would do in production

A collector in front of the store, for sampling rules that keep every failed or slow trace and a fraction of the rest, and for adding the same ids to the metrics as exemplars. The trace id in the logs would be kept in a field that Loki indexes as structured metadata, so the lookup is fast on a large volume.
