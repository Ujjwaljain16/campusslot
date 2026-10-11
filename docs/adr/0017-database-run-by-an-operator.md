# ADR 0017: Let an operator run the database, with a replica and a continuous archive

Status: accepted (v2)

## Context

In v1 the database is a single PostgreSQL pod with one volume, plus a `pg_dump` every few minutes to another volume of the same cluster ([backup drill](../engineering/backup-drill.md)). If the pod or its node is lost, there is no replica to take over, so the application is down until the pod is rescheduled and its volume is attached. The worst case data loss is the time between two dumps, and a restore means rebuilding from one dump file, with no way to stop at a chosen moment.

## Options considered

- Keep the single pod and shorten the dump interval. It stays one component to fail, and the data loss window gets smaller but never reaches the point that is needed after a mistake (a restore to the minute before it).
- A managed database (Amazon RDS). It is the right production answer, and it needs a cloud account and costs money, which this project does not use.
- Patroni, with a StatefulSet written by hand. It works, but it is a lot of fragile YAML for the part that an operator exists to own.
- The Zalando postgres-operator, or CloudNativePG. Both run a primary and replicas and promote one by themselves. CloudNativePG is configured by Kubernetes objects only (no extra consensus store), it is a CNCF project, and its backup and recovery are part of the same API.

## Decision

`postgres.operator.enabled` replaces the single pod with a **CloudNativePG `Cluster`** of two instances: a primary and a replica with streaming replication. The backend connects to the operator's `-rw` Service, which always points at the current primary, so a failover needs no change in the application. The connection pool already pings a connection before it uses it (`pool_pre_ping`), and a database that is briefly gone is a handled 503 with `Retry-After`, so the application was ready for this.

With `postgres.operator.backup.enabled` the cluster archives its WAL continuously to an S3 compatible object store, and takes a base backup on a schedule (the **Barman Cloud plugin**, because the backup that is built into the operator is deprecated since 1.26). Together they allow point-in-time recovery: a new cluster is bootstrapped from the base backup and replays the WAL up to a chosen time.

`postgres.operator.synchronous` makes a commit wait for one replica (quorum). It is off by default: with two instances, a replica that is down stops the writes, and the CloudNativePG documentation advises three instances for it. The failover drill measures both settings, so the choice is based on a number.

The object store of a laptop cluster is a stand-in (`k8s/objectstore.yaml`), in its own namespace and not in the application chart. In production it is a managed bucket, and only the endpoint and the credentials change.

## Consequences

- When the primary is lost, a replica is promoted by the operator, and the time without writes is measured instead of unbounded.
- The data loss window of a total loss is the `archive_timeout` of the WAL archive (60 seconds here), instead of the interval of a dump. A mistake can be undone to a chosen second.
- A lot more moving parts: the operator, cert-manager and the plugin for the backups, two database pods that each need memory, and a bucket. On a laptop that is about 1 GB more, so the default stays the single pod, and CI tests that path.
- The migration job, the alerts and the network policies had to learn about the operator mode. The pods carry the labels of the old `postgres` component, so most of that is automatic.
- Failover is only as good as its last test. Replicas can lag, and an asynchronous failover can lose the last transactions that the old primary acknowledged. The drill counts them.

## What I would do in production

Three instances in three zones with synchronous replication, backups to a bucket in another account or region with object lock, a restore test on a schedule (not once), and the operator's metrics in the same dashboards and burn rate alerts as the application.
