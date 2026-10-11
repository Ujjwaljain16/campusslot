# Linked signals: from a breached objective to the request

Status: **written and tested where it can be without a cluster (60 backend tests, the script's failure handling against a local backend, the dashboard JSON, the chart renders). The drill has not been run on a cluster yet.** The measured results are added next to the predictions below after the first run. The decision is in [ADR 0018](../adr/0018-link-metrics-traces-and-logs-by-trace-id.md).

## The problem

An alert says that an objective is breached. Finding out which requests were slow, where their time went, and what they logged meant searching by time stamp in three places.

## What was built

| Part | File | What it does |
|---|---|---|
| Tracing in the application | `backend/app/tracing.py`, `main.py`, `db.py` | A trace per API request, a span per database statement. Off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set |
| The trace id in the logs and the response | `backend/app/logging_config.py`, `main.py` | `trace_id` and `span_id` in every JSON log line of a request, and an `X-Trace-Id` header |
| Chart settings | `helm/campusslot` (`tracing.*`) | Sets the standard OTEL variables, and lets the backend reach Tempo through the network policy |
| Trace store | `monitoring/tempo-values.yaml`, `scripts/install-tracing.sh` | Tempo, 6 hours of traces |
| The links | `monitoring/kube-prometheus-stack-values.yaml` | Loki: a derived field on `trace_id` opens the trace. Tempo: the logs of a span |
| The dashboard | `monitoring/slo-dashboard.json` | Availability, error budget, fast requests, burn rate, p95, firing alerts, then the slow and failed traces and the log lines of the same period |
| The drill | `scripts/trace-drill.sh`, `scripts/trace_chain.py` | Slows the application down, then follows one request through the metric, the trace and the log |

Tested without a cluster: the 7 new tests in `backend/tests/test_tracing.py` check that a request is one trace with its route, that its database statements are spans of the same trace, that the probes are not traced, that the response names its trace, that a failed request marks its span as an error, and that the log line carries the same id. One test failed on the first run and found a real problem: the OpenTelemetry package for SQLAlchemy supports only versions older than 2.1, and the application runs 2.1.3, so it switched itself off. Statements are now traced with SQLAlchemy's own events (ADR 0018).

## How to run the drill

About 400 MB more than the application and Prometheus alone. Close heavy applications first.

```bash
scripts/install-monitoring.sh                    # Prometheus, Grafana and Loki (the stack with Grafana and the log shipper)
scripts/install-tracing.sh                       # Tempo, the links between the data sources, and the dashboard
scripts/deploy-local.sh <sha>                    # the application as a plain Deployment
# the port forwards listed at the top of scripts/trace-drill.sh
scripts/trace-drill.sh
```

Then open the **CampusSlot SLO** dashboard in Grafana, look at the failed or slow requests at the bottom, click `trace_id` on a line, and read the spans.

## Predictions, written before the first run

Every API request is delayed by 400 ms, and 40 requests are sent.

| Link | Expected | Why |
|---|---|---|
| The slowest request | 400 to 450 ms | The injected delay plus the normal handling of a few milliseconds |
| The metric | The share of fast requests of the last 10 minutes is below 95 percent | None of the 40 requests is within 0.25 s. How far it drops depends on how much healthy traffic is in the same window |
| The trace is found by a TraceQL search | Within 15 seconds of the request | Recent traces are searchable from the ingester almost at once |
| The spans of the trace | One span for the request and one to three for the database statements | The room list is a single query, plus the connection check |
| The time in the database | Under 10 ms of about 400 | The delay is in the application, in front of the handler, so the trace shows a long request with a short database part. That is how a trace tells the application from the database |
| The log line | Found by `trace_id` alone within 30 seconds | The log shipper tails the pod, and Loki makes a line searchable after a short delay |

If a link is missing, the script says which, and the missing link is the finding.

## Results

Not measured yet.

## Limits that are already known

- The Tempo chart is configured from its documentation and has not run yet. The chart for a single binary may be deprecated in favour of the distributed chart, and if the first run shows that, the values move there.
- Tempo keeps the traces in memory and on the pod's own disk. A restart starts empty.
- A graph point does not open its own trace (there are no exemplars). The dashboard links by a search over the same period and threshold.
- The cost of tracing is not measured yet. It is part of the game day: the same load with tracing off, at a ratio of 0.1, and at 1.
