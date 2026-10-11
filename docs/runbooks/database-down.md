# Runbook: Database not ready

**Alerts:** CampusSlotDatabaseDown (critical), CampusSlotDatabaseReplicaMissing (warning, only with `postgres.operator.enabled`)

## What it means

The PostgreSQL StatefulSet has no ready pod. With the operator (`postgres.operator.enabled`), no instance of the cluster is ready (critical), or an instance is missing, so there is no replica to fail over to (warning).

## Impact

The backend answers 503 on `/ready` and receives no traffic, so the whole application is unavailable. Data is safe on the volume.

## Diagnose

1. `kubectl get pods,pvc -n campusslot`
2. `kubectl describe pod -n campusslot campusslot-postgres-0`
3. `kubectl logs -n campusslot campusslot-postgres-0 --tail=40`

### With the operator

1. `kubectl get cluster -n campusslot` (the phase, the primary, and the ready instances)
2. `kubectl get pods -n campusslot -l cnpg.io/cluster=campusslot-pg`
3. `kubectl describe cluster campusslot-pg -n campusslot` (events: a promotion, a failed instance, a backup problem)
4. `kubectl logs -n cnpg-system deploy/cnpg-cloudnative-pg --tail=50` (the operator's own decisions)

A lost primary is replaced by itself: a replica is promoted within seconds, and the `campusslot-pg-rw` Service follows. Do not delete pods by hand to "help". A warning that stays means that an instance cannot start: look at its events and its volume. If the whole cluster is lost or the data is wrong, recover to a chosen time ([database reliability](../engineering/database-reliability.md), `scripts/db-drill.sh pitr`).

## Mitigate

- Pod restarting or out of memory: check the limits, see the sizing document.
- Volume problem: check that the PersistentVolumeClaim is bound.
- Data lost or corrupted: restore the latest backup, see the backup drill document.

## Verify that it is fixed

The pod is 1/1 Ready, `/ready` returns 200 and the bookings are present.
