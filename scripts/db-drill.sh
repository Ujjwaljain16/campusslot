#!/usr/bin/env bash
# Two drills for the database that the CloudNativePG operator runs.
#
#   scripts/db-drill.sh failover     # kill the primary while the users keep writing
#   scripts/db-drill.sh pitr         # delete the data by mistake, and bring it back to the minute before
#
# Needs the application deployed with postgres.operator.enabled=true (and, for pitr, postgres.operator.backup.enabled=true,
# which needs scripts/install-cnpg.sh with WITH_BACKUP=1 and scripts/install-objectstore.sh), and the ingress on
# http://localhost:8080
#   kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80
# Method and results: docs/engineering/database-reliability.md
#
# failover: scripts/writeprobe.py writes steadily and remembers every acknowledged booking. At KILL_AT seconds the
# primary pod is deleted with no grace period, which is what a crashed node looks like to the cluster. The
# drill reports who became the primary and when, the longest time in which no write was acknowledged, and, after
# the probe has ended, how many acknowledged bookings are no longer there.
#
# pitr: a base backup is taken, bookings are written, the time T is noted, more bookings are written, and then
# every booking is deleted (the mistake). A second cluster is restored from the backup and the WAL to the time T.
# The drill reports the time that the restore took (the RTO), the age of the newest archived WAL file at the moment
# of the mistake (the RPO of the archive), and whether the restored data is exactly the data of the time T.
set -uo pipefail

MODE="${1:-}"
NS="${NAMESPACE:-campusslot}"
CLUSTER="${CLUSTER:-campusslot-pg}"
BASE="${BASE:-http://localhost:8080}"
SECONDS_TOTAL="${SECONDS_TOTAL:-90}"
KILL_AT="${KILL_AT:-20}"
RATE="${RATE:-5}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python}"
WORK="$(mktemp -d)"
# Python on Windows does not see the temporary directory of Git Bash by its /tmp name, so it is given the native path.
WORKP="$(cygpath -m "$WORK" 2>/dev/null || echo "$WORK")"
trap 'rm -rf "$WORK"' EXIT

primary() { kubectl get cluster "$CLUSTER" -n "$NS" -o jsonpath='{.status.currentPrimary}'; }
psql_primary() { kubectl exec -n "$NS" "$(primary)" -c postgres -- psql -U postgres -d campusslot -Atc "$1"; }

case "$MODE" in
  failover)
    echo "== failover: the primary is killed at +${KILL_AT} s, the users write for ${SECONDS_TOTAL} s (${RATE} per second)"
    kubectl get cluster "$CLUSTER" -n "$NS" >/dev/null || { echo "no Cluster $CLUSTER: install with postgres.operator.enabled=true"; exit 2; }
    OLD="$(primary)"
    echo "primary before: $OLD"
    kubectl get cluster "$CLUSTER" -n "$NS" -o jsonpath='{.spec.postgresql.synchronous}{"\n"}' | sed 's/^$/(asynchronous replication)/'

    "$PY" "$ROOT/scripts/writeprobe.py" run "$BASE" --seconds "$SECONDS_TOTAL" --rate "$RATE" --out "$WORKP/writes.json" --first-slot "${FIRST_SLOT:-0}" > "$WORK/probe.txt" 2>&1 &
    PROBE=$!
    "$PY" "$ROOT/scripts/cnpg_watch.py" --namespace "$NS" --cluster "$CLUSTER" --seconds "$SECONDS_TOTAL" > "$WORK/watch.txt" 2>&1 &
    WATCH=$!

    sleep "$KILL_AT"
    echo "+${KILL_AT} s  killing $OLD"
    kubectl delete pod "$OLD" -n "$NS" --grace-period=0 --force --wait=false >/dev/null 2>&1

    wait "$PROBE"; wait "$WATCH"
    echo "---- the cluster"
    cat "$WORK/watch.txt"
    echo "---- the users"
    cat "$WORK/probe.txt"
    echo "---- after the failover"
    echo "primary now: $(primary) (was $OLD)"
    "$PY" "$ROOT/scripts/cnpg_watch.py" --namespace "$NS" --cluster "$CLUSTER" --seconds 180 --until-healthy | tail -n 1
    "$PY" "$ROOT/scripts/writeprobe.py" verify "$BASE" "$WORKP/writes.json"
    ;;

  pitr)
    echo "== point in time recovery of $CLUSTER (namespace $NS)"
    kubectl get cluster "$CLUSTER" -n "$NS" >/dev/null || { echo "no Cluster $CLUSTER"; exit 2; }
    STAMP="$(date +%s)"

    echo "-- a base backup (the starting point of the recovery)"
    kubectl apply -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: pitr-base-$STAMP
  namespace: $NS
spec:
  cluster:
    name: $CLUSTER
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
EOF
    for _ in $(seq 1 90); do
      phase="$(kubectl get backup "pitr-base-$STAMP" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null)"
      [ "$phase" = "completed" ] && break
      [ "$phase" = "failed" ] && { echo "the backup failed:"; kubectl get backup "pitr-base-$STAMP" -n "$NS" -o jsonpath='{.status.error}'; exit 1; }
      sleep 2
    done
    echo "backup phase: $phase"
    [ "$phase" = "completed" ] || exit 1

    echo "-- the data that must survive"
    "$PY" "$ROOT/scripts/writeprobe.py" run "$BASE" --seconds 10 --rate 5 --out "$WORKP/before.json" --first-slot 5000 | head -n 1
    BEFORE="$(psql_primary 'select count(*) from bookings')"
    # The time T is read from the database itself, so that no clock of a laptop is involved.
    T="$(psql_primary "select to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS.US') || '+00'")"
    echo "bookings at T: $BEFORE, T = $T"
    sleep 3

    echo "-- data written after T (it must NOT come back)"
    "$PY" "$ROOT/scripts/writeprobe.py" run "$BASE" --seconds 5 --rate 5 --out "$WORKP/after.json" --first-slot 6000 | head -n 1

    ARCHIVE_AGE="$(psql_primary "select coalesce(extract(epoch from now() - last_archived_time)::int::text, 'never') from pg_stat_archiver")"
    psql_primary "select pg_switch_wal()" >/dev/null
    sleep 5
    echo "-- the mistake: every booking is deleted"
    psql_primary "delete from bookings" >/dev/null
    echo "bookings after the mistake: $(psql_primary 'select count(*) from bookings')"
    echo "age of the newest archived WAL file, before the mistake: ${ARCHIVE_AGE} s (the archive's data loss window is at most archive_timeout)"

    echo "-- restore a second cluster to $T"
    START="$(date +%s)"
    kubectl apply -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: $CLUSTER-restore
  namespace: $NS
spec:
  instances: 1
  imageName: $(kubectl get cluster "$CLUSTER" -n "$NS" -o jsonpath='{.spec.imageName}')
  storage:
    size: $(kubectl get cluster "$CLUSTER" -n "$NS" -o jsonpath='{.spec.storage.size}')
  bootstrap:
    recovery:
      source: origin
      recoveryTarget:
        targetTime: "$T"
  externalClusters:
    - name: origin
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: $CLUSTER-store
          serverName: $CLUSTER
EOF
    "$PY" "$ROOT/scripts/cnpg_watch.py" --namespace "$NS" --cluster "$CLUSTER-restore" --seconds 600 --until-healthy
    END="$(date +%s)"
    RESTORED="$(kubectl exec -n "$NS" "$(kubectl get cluster "$CLUSTER-restore" -n "$NS" -o jsonpath='{.status.currentPrimary}')" -c postgres -- psql -U postgres -d campusslot -Atc 'select count(*) from bookings')"
    echo "---- result"
    echo "restore time (RTO): $((END - START)) s"
    echo "bookings at T: $BEFORE, bookings in the restored cluster: $RESTORED"
    if [ "$RESTORED" = "$BEFORE" ]; then echo "PASS: the restored data is exactly the data of the time T"; else echo "FAIL: the restored data differs from the data of the time T"; fi
    echo "(the restored cluster stays for inspection: kubectl delete cluster $CLUSTER-restore -n $NS)"
    ;;

  *)
    echo "usage: $0 failover|pitr" >&2
    exit 2
    ;;
esac
