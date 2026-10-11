# Database reliability: failover and point-in-time recovery

Status: **written and checked in CI (the chart renders, and the probe is tested against a local backend). The drills have not been run on a cluster yet.** The measured results are added next to the predictions below after the first run. The decision is in [ADR 0017](../adr/0017-database-run-by-an-operator.md).

## The problem

In v1 the database is one pod. Losing it means an outage for as long as it takes to reschedule it, and the only way back from a mistake is the last `pg_dump`, which can be minutes old.

## What was built

| Part | File | What it does |
|---|---|---|
| The database as an operator `Cluster` | `helm/campusslot/templates/cnpg.yaml` (`postgres.operator.enabled`) | A primary and a replica, streaming replication, automatic failover. The backend connects to the `-rw` Service |
| Continuous archive and backups | the same file (`postgres.operator.backup.enabled`) | `ObjectStore`, WAL archiving with `archive_timeout`, and a `ScheduledBackup` through the Barman Cloud plugin |
| Synchronous replication | `postgres.operator.synchronous` | A commit waits for one replica |
| Installers | `scripts/install-cnpg.sh`, `scripts/install-objectstore.sh`, `k8s/objectstore.yaml` | The operator, and with `WITH_BACKUP=1` cert-manager and the plugin. A laptop object store with random credentials |
| Alerts | `templates/prometheusrule.yaml` | The "database down" alert counts ready instances, and a new warning fires when an instance is missing (no spare to fail over to) |
| The write probe | `scripts/writeprobe.py` | Writes steadily, remembers every acknowledged booking, and later checks that each one still exists |
| The drills | `scripts/db-drill.sh`, `scripts/cnpg_watch.py` | `failover` and `pitr` |

`scripts/writeprobe.py` was run against a local backend before any cluster: 48 acknowledged and 48 present, and after two rows were deleted by hand, 2 reported as lost with a non-zero exit code. That is the check that a loss cannot hide.

## How to run the drills

About 1 GB more than the application alone needs, so close heavy applications first, and use a cluster of at least 3.5 GB.

```bash
scripts/install-cnpg.sh                          # the operator (WITH_BACKUP=1 adds cert-manager and the plugin)
scripts/install-objectstore.sh                   # for the backups only
helm upgrade --install campusslot helm/campusslot -n campusslot -f helm/campusslot/values-dev.yaml \
  --set backend.image.tag=<sha> --set frontend.image.tag=<sha> --set-string postgres.password="$(openssl rand -hex 16)" \
  --set postgres.operator.enabled=true --set postgres.operator.backup.enabled=true
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80 &

scripts/db-drill.sh failover                     # asynchronous replication
helm upgrade campusslot helm/campusslot -n campusslot --reuse-values --set postgres.operator.synchronous=true
scripts/db-drill.sh failover                     # synchronous replication, to compare
scripts/db-drill.sh pitr                         # delete everything by mistake and recover to the minute before
```

## Predictions, written before the first run

The users write 5 bookings per second for 90 seconds (about 450 requests), and the primary is killed at 20 seconds.

| What | Expected | Why |
|---|---|---|
| A replica becomes the primary | 5 to 20 seconds after the kill | The operator notices that the pod is gone and promotes the replica, and the `-rw` Service follows |
| The longest time without an acknowledged write | 8 to 25 seconds | Promotion, then the Service endpoint, then a connection that the pool has to replace (it pings before use) |
| Failed requests | About 40 to 120 of 450 | The rate times the gap. The failures are handled 503 responses, not crashes |
| Acknowledged writes lost, asynchronous | 0 or a very few | The replica is a few milliseconds behind at 5 writes per second, so the window is small but not closed |
| Acknowledged writes lost, synchronous | 0 | A commit is acknowledged only after the replica has it |
| Writes while the replica is down, synchronous | They pause | That is the price of `dataDurability: required`, and it is why the documentation wants three instances |
| Base backup | Done in 20 to 60 seconds | A small database |
| Restore to the time T (RTO) | 60 to 180 seconds | A new pod, the base backup, and the replay of a few WAL files. The image pull dominates when it is not cached |
| The restored data | Exactly the rows of the time T, and none written after it | `recoveryTarget.targetTime` |
| Age of the newest archived WAL before the mistake | Below 60 seconds | `archive_timeout`, which is the data loss window of the archive |

If the numbers differ, the difference is the finding.

## Results

Not measured yet.

## Limits that are already known

- Two instances is the smallest cluster that can fail over, and it is not the recommended size for synchronous replication. The drill shows the consequence, and does not hide it.
- A forced pod deletion is a crash of the process and not a node failure. The volume stays, and the operator behaves differently when a node is gone. A node loss is part of the later game day.
- The restore is a second cluster beside the first, so nothing is overwritten. Switching the application to it is a deliberate step and is not part of the drill.
- The Barman Cloud plugin and the laptop object store are the least verified parts. The image tag of the object store is a setting of the install script, and the plugin's `ObjectStore` fields are written from its documentation.
