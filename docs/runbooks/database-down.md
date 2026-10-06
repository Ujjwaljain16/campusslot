# Runbook: Database not ready

**Alerts:** CampusSlotDatabaseDown (critical)

## What it means

The PostgreSQL StatefulSet has no ready pod.

## Impact

The backend answers 503 on `/ready` and receives no traffic, so the whole application is unavailable. Data is safe on the volume.

## Diagnose

1. `kubectl get pods,pvc -n campusslot`
2. `kubectl describe pod -n campusslot campusslot-postgres-0`
3. `kubectl logs -n campusslot campusslot-postgres-0 --tail=40`

## Mitigate

- Pod restarting or out of memory: check the limits, see the sizing document.
- Volume problem: check that the PersistentVolumeClaim is bound.
- Data lost or corrupted: restore the latest backup, see the backup drill document.

## Verify that it is fixed

The pod is 1/1 Ready, `/ready` returns 200 and the bookings are present.
