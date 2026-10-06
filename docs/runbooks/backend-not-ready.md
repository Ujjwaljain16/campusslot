# Runbook: Backend pods unavailable

**Alerts:** CampusSlotBackendReplicasUnavailable (warning), CampusSlotBackendDown (critical)

## What it means

Backend pods are running but fail the readiness probe, or none is available at all. `/ready` fails when the database is unreachable or the schema is not migrated.

## Impact

Traffic is sent only to ready pods. With one pod unavailable the service has less capacity. With none available, every request fails.

## Diagnose

1. `kubectl get pods -n campusslot`
2. `kubectl describe pod -n campusslot -l app.kubernetes.io/component=backend | grep -E 'Ready:|Unhealthy|Readiness'`
3. `kubectl port-forward -n campusslot deploy/campusslot-backend 8001:8000   # leave it running, then in another terminal: curl -s localhost:8001/ready`

## Mitigate

- The answer `{"detail":"database unreachable"}` means a connection problem: check the DATABASE_URL in the Secret and the database pod (database runbook).
- The answer `{"detail":"database schema is not migrated yet"}` means the migration Job has not finished: `kubectl get jobs -n campusslot` and read its logs.
- The pod is not running at all: `kubectl describe pod`, see troubleshooting lab 1 or 3.

## Verify that it is fixed

All backend pods show 1/1 Ready and the alert resolves.
