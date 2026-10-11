# Runbook: Latency objective breached

**Alerts:** CampusSlotLatencySLOBreach (warning)

## What it means

Fewer than 95 percent of requests finish within 0.25 seconds, over 10 minutes and with real traffic.

## Impact

Pages feel slow. This usually comes before errors.

## Diagnose

1. In Grafana, check the latency percentiles panel and the CPU per pod panel.
2. `kubectl top pods -n campusslot`
3. `kubectl get hpa -n campusslot`
4. With tracing on (`tracing.enabled`), open the **CampusSlot SLO** dashboard: the table of slow traces and the log lines of the slow requests are on the same page. Open a trace and read where the time went: a long database span points at the database, a long request span with a short database part points at the application, and a gap in front of the handler points at a queue or a pause. The same `trace_id` opens the log lines of that request ([linked signals](../engineering/linked-signals.md)).

## Mitigate

- CPU near the limit and the autoscaler below its maximum: wait, it is scaling. If it is slow to scale, lower the CPU target.
- Autoscaler at its maximum: raise maxReplicas, see the autoscaler runbook.
- CPU is low but requests are slow: look at the database (slow queries, connections) before adding pods.

## Verify that it is fixed

The share of fast requests is above 95 percent for 10 minutes.
