# Database reliability: failover and point-in-time recovery

Status: **built, and the drills have run** on a kind cluster of a GitHub-hosted runner (20 October 2026, [run 39495055248](https://github.com/Ujjwaljain16/campusslot/actions/runs/39495055248)). The results are below, next to the predictions. The decision is in [ADR 0017](../adr/0017-database-run-by-an-operator.md).

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

The route that was used, with no laptop: push the branch `drill/phase3` (`git push -f origin v2:refs/heads/drill/phase3`), and the job `phase3` of `.github/workflows/drills.yml` builds the cluster, installs the operator, cert-manager, the backup plugin and the object store, and runs the three drills. On a laptop:

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

Environment ([environment.txt](../evidence/v2/phase3/environment.txt)): a GitHub-hosted runner, 4 vCPU, 16 GB, one kind node with Kubernetes v1.35.0, the storage class `standard` (a local disk of the runner), a two-instance cluster, the images of commit `2ca20e4`. The users write 5 bookings per second for 90 seconds (450 requests), and the primary is killed at +20 s.

### Failover

| What | Predicted | Asynchronous ([transcript](../evidence/v2/phase3/failover-async.txt)) | Synchronous ([transcript](../evidence/v2/phase3/failover-sync.txt)) |
|---|---|---|---|
| A replica becomes the primary | 5 to 20 s after the kill | **+20.6 s** (the operator noticed at +0.9 s, `Failing over`) | **+20.7 s** |
| Longest time without an acknowledged write | 8 to 25 s | **26.4 s** | **25.2 s** |
| Failed requests | 40 to 120 of 450 | **131** (130 HTTP 503, 1 timeout) | **111** (110 HTTP 503, 1 timeout) |
| Acknowledged writes lost | 0 or a very few | **0 of 319** | **0 of 339** |
| The cluster is healthy again (2 of 2) | not predicted | +52.1 s | +52.2 s |

The failover works, and the writes that were acknowledged are all still there. Every failed request is a handled 503, not a crash.

**Where the predictions were off**

1. **The promotion took about 20 s, at the top of the predicted range and past it for the whole gap.** The operator saw the dead primary within a second, so the detection is not the delay. About 20 s passed between "Failing over" and the new primary. This run does not say which part of the promotion takes that long, and I did not guess. The gap seen by the users (26.4 s and 25.2 s) is a little above the predicted 25 s at the top, and the failed requests (131 and 111) are above the predicted 120 for the same reason: the rate times the gap.
2. **The asynchronous run lost nothing.** The prediction allowed "a very few". At 5 writes per second the replica is milliseconds behind, and the window is too small to hit.
3. **So this drill cannot tell asynchronous from synchronous replication.** Both lost nothing. The claim "synchronous replication prevents the loss of an acknowledged write" is the design of the setting and is **not proven by this test**. Showing the difference needs a load that keeps the replica behind (a lagging replica, or a much higher write rate) and a kill timed against it. That is a better test for the game day, and it is stated there as an open point.
4. **The prediction that writes pause in the synchronous mode while the replica is down was not seen.** In the synchronous run the writes were acknowledged again at about +44 s, while the cluster still reported 1 of 2 instances ready until +52 s. Either the replica was already streaming before its readiness probe passed (so the quorum was met), or the pause is shorter than a second at this load. The run cannot separate the two, so the consequence of two instances under `dataDurability: required` stays untested.

### Point in time recovery ([transcript](../evidence/v2/phase3/pitr.txt))

| What | Predicted | Measured |
|---|---|---|
| Base backup | done in 20 to 60 s | **completed** (the time was not recorded: the script polls until the phase is `completed`) |
| Restore to the time T (RTO) | 60 to 180 s | **53 s**, from the creation of the second cluster to `Cluster in healthy state` |
| The restored data | exactly the rows of the time T, none written after | **709 rows at T, 709 in the restored cluster**: the 25 rows written after T and the deletion of everything were not applied |
| Age of the newest archived WAL before the mistake | below 60 s | **22 s** |

The restore was faster than predicted, because the images were already on the node and the data is small (709 rows). The runner's disk is local, so the same restore on network volumes would be slower, and the 53 s should not be quoted as a general number. What it shows is that the whole chain works: the plugin, the object store, the archive, the base backup, the recovery to a time, and an exact result.

### What the known risks turned out to be

| Risk named before the run | Result |
|---|---|
| The image tag of the laptop object store | `rustfs/rustfs:1.0.3` ran. The script default was `1.0.0`, which was never run, and it is now `1.0.3` |
| The fields of the plugin's `ObjectStore` | Accepted: the archive worked (WAL archived, base backup completed, recovery from both) |
| Whether the backup sidecar passes the Pod Security profile | It does: the cluster pods ran in the `restricted` namespace with the sidecar |

There was one warning and no failure: the one-off pod that creates the bucket does not meet the `restricted` profile (the object-store namespace enforces `baseline` and only warns about `restricted`, as its manifest says).

## Limits that are already known

- Two instances is the smallest cluster that can fail over, and it is not the recommended size for synchronous replication. The drill shows the consequence, and does not hide it.
- A forced pod deletion is a crash of the process and not a node failure. The volume stays, and the operator behaves differently when a node is gone. A node loss is part of the later game day.
- The restore is a second cluster beside the first, so nothing is overwritten. Switching the application to it is a deliberate step and is not part of the drill.
- The Barman Cloud plugin and the laptop object store are the least verified parts. The image tag of the object store is a setting of the install script, and the plugin's `ObjectStore` fields are written from its documentation.
