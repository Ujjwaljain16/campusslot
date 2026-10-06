# Runbook: Autoscaler at its maximum

**Alerts:** CampusSlotAutoscalerAtMaximum (warning)

## What it means

The backend autoscaler has been at maxReplicas for 10 minutes.

## Impact

Demand needs more pods than the autoscaler may create, so latency rises and the node may run out of room.

## Diagnose

1. `kubectl get hpa -n campusslot`
2. `kubectl top pods -n campusslot`
3. In Grafana, compare current and desired replicas and the request rate.

## Mitigate

- Real growth in traffic: raise `hpa.maxReplicas` in the values, after checking that the node has room (`kubectl top nodes`).
- A burst or a test: wait, the autoscaler scales down after its stabilisation window.
- CPU per request grew after a change: look at the latest release.

## Verify that it is fixed

Current replicas are below the maximum again.
