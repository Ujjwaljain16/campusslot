# Linked signals: from a breached objective to the request

Status: **built, and the drill has run** on a kind cluster of a GitHub-hosted runner (20 October 2026, [run 39498371341](https://github.com/Ujjwaljain16/campusslot/actions/runs/39498371341)). All five links held. The results are below, next to the predictions. The decision is in [ADR 0018](../adr/0018-link-metrics-traces-and-logs-by-trace-id.md).

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

The route that was used, with no laptop: push the branch `drill/phase4` (`git push -f origin v2:refs/heads/drill/phase4`), and the job `phase4` of `.github/workflows/drills.yml` installs the monitoring stack, Tempo and the application on a kind cluster and runs the drill. On a laptop:

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

Environment ([environment.txt](../evidence/v2/phase4/environment.txt)): a GitHub-hosted runner, 4 vCPU, 16 GB, one kind node with Kubernetes v1.35.0, the full monitoring stack (Prometheus, Grafana, Loki, Alloy) and Tempo, the images of commit `2ca20e4`, two backend replicas. Every API request delayed by 400 ms, 40 requests sent ([trace-drill.txt](../evidence/v2/phase4/trace-drill.txt)).

| Link | Predicted | Measured |
|---|---|---|
| The slowest request | 400 to 450 ms | **417 ms** |
| The metric | below 95 percent fast | **80.9 percent** of the requests of the last 10 minutes within 0.25 s, **20 s** after the requests were sent (see below) |
| The trace is found by a TraceQL search | within 15 s | **found** within the 45 s that the script waits (it polls every 3 s; the delay itself was not recorded) |
| The spans of the trace | one for the request, one to three for the database | **5 spans**: the request (`/api/rooms`) and **1 database statement**. The other three were not looked at by the script and are not named here |
| The time in the database | under 10 ms of about 400 | **3.2 ms of 415 ms**, so **412 ms were spent outside the database**: the trace says "the application, not the database" |
| The log line | found by `trace_id` alone within 30 s | **found**, with the same `trace_id`, a `span_id`, the path, the status and the duration |

The chain works from the objective to the request: the metric says that the fast share dropped, the trace of the slowest request says that 412 of its 415 ms were outside the database, and the log line of the same request is found with nothing but the trace id.

### What the run showed that the predictions did not

1. **The metric lags behind the requests.** The first run of the drill read the metric right after sending the requests, and it still said 100 percent: the share of fast requests comes from a recording rule that Prometheus evaluates every 30 s over data that it scrapes every 15 s. The script was wrong to read it at once, and it now waits for the breach and reports how long that took. In the second run the breach showed **20 s** after the last request. A person looking at the dashboard right after an incident starts sees the old value for up to about 45 s. This is a property of the design (scrape interval plus rule evaluation interval), not of this run.
2. **The Tempo chart is deprecated, as suspected.** `helm install` prints "This chart is deprecated", and it works: the single binary ran, accepted the OTLP traffic and answered the TraceQL searches. Moving to the distributed chart or to Grafana Alloy plus a managed store stays on the list for a production version. It was not needed for this drill.
3. **Grafana accepted the `$$` escapes.** The Loki data source has the derived field with the URL `${__value.raw}` and points to Tempo, and the Tempo data source has the logs query with `${__trace.traceId}` ([grafana.txt](../evidence/v2/phase4/grafana.txt)). Both data sources report healthy, and the SLO dashboard is loaded. Whether a click in the Grafana interface opens the trace was **not tested**: the script checks the provisioned settings and the three queries, and not the browser.

## Limits that are already known

- The Tempo chart (single binary) is deprecated, and it works (see the results). A production version would use the distributed chart.
- Tempo keeps the traces in memory and on the pod's own disk. A restart starts empty.
- A graph point does not open its own trace (there are no exemplars). The dashboard links by a search over the same period and threshold.
- The cost of tracing is not measured yet. It is part of the game day: the same load with tracing off, at a ratio of 0.1, and at 1.
