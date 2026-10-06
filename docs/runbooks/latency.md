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

## Mitigate

- CPU near the limit and the autoscaler below its maximum: wait, it is scaling. If it is slow to scale, lower the CPU target.
- Autoscaler at its maximum: raise maxReplicas, see the autoscaler runbook.
- CPU is low but requests are slow: look at the database (slow queries, connections) before adding pods.

## Verify that it is fixed

The share of fast requests is above 95 percent for 10 minutes.
