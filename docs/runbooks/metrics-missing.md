# Runbook: Metrics missing

**Alerts:** CampusSlotMetricsMissing (warning)

## What it means

Prometheus has no healthy target for the backend Service.

## Impact

The other alerts depend on these metrics, so they cannot fire. An outage could go unnoticed.

## Diagnose

1. Open the Prometheus Targets page and look for the campusslot-backend pool.
2. `kubectl get servicemonitor,svc,pods -n campusslot`
3. `kubectl get endpoints -n campusslot campusslot-backend`

## Mitigate

- No ServiceMonitor: the chart was installed with serviceMonitor.enabled=false.
- Service without endpoints: the selector does not match the pods, see troubleshooting lab 2.
- Prometheus itself is down: `kubectl get pods -n monitoring`.

## Verify that it is fixed

The target shows UP on the Targets page.
