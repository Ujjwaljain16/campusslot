# Backup and restore drill

## Why this exists

A backup that has never been restored is a hope. The project kept all its data in one PostgreSQL pod with one volume, and nothing copied it anywhere. I added a scheduled backup and then did the part that matters: I destroyed the data on purpose and restored it, and I measured the result.

## What was added

- A `CronJob` in the Helm chart ([`templates/backup.yaml`](../../helm/campusslot/templates/backup.yaml), enabled with `backup.enabled`) that runs `pg_dump --format=custom` and writes the file to its own volume. It keeps the newest `backup.keep` files and writes to a `.partial` name first, so a failed run never leaves a broken file that looks complete.
- [`scripts/restore-backup.sh`](../../scripts/restore-backup.sh), which starts a short-lived pod that mounts the backup volume read-only and runs `pg_restore --clean --if-exists --single-transaction` against the live database. It restores the newest backup, or the file named as the first argument.
- The pods use the same hardening as the rest of the chart: non-root user, read-only root filesystem, no capabilities, no service account token.

## The drill

The full transcript is [`docs/evidence/backup-drill.txt`](../evidence/backup-drill.txt).

| Step | What happened |
|---|---|
| 1. Known data | 40 bookings written. Row count and a checksum over all rows recorded: 40 rows, `a8892dcd...` |
| 2. Backup | A Job created from the CronJob finished in 4 seconds and wrote a 9138 byte file |
| 3. Writes after the backup | 5 more bookings written. State: 45 rows |
| 4. Disaster | `DELETE FROM bookings` with no `WHERE` clause. State: 0 rows. The API still answered with 200 and an empty list |
| 5. Restore | `scripts/restore-backup.sh` finished and the table had 40 rows |
| 6. Verification | Row count and checksum identical to step 1. The primary key, foreign key, check constraints and the overlap exclusion constraint were all present, and an overlapping booking was rejected |

## Results

| Measure | Value | How to read it |
|---|---|---|
| Restore result | identical (count and checksum) | The backup contained exactly the data of that moment |
| Recovery time (RTO) of the procedure | 4 seconds | From the disaster to a verified database, for a 40 row database. It grows with the size of the data and does not include the time a person needs to notice the problem and decide to restore |
| Data lost | the 5 rows written after the backup | Recovery point (RPO): the time since the last backup. With the 5 minute schedule used in `values-dev.yaml` it is at most 5 minutes. With the default daily schedule it is at most 24 hours |

The RPO is a choice and not a property of the tool. A shorter schedule costs a little more storage and a few seconds of database load per run, so the schedule should follow how much data the business can afford to lose.

## Limits

- **The backup lives in the same cluster.** The volume is separate from the database volume, so a mistake or a corrupted database volume is covered, but losing the node or the cluster loses both. Production needs the file copied off the cluster, for example to an S3 bucket in another region.
- **Restore replaces the tables.** Everything written after the backup is gone, and the application keeps running during the restore, so requests can wait briefly for the locks held by the single transaction.
- **No point in time recovery.** `pg_dump` is a snapshot at one moment. Recovering to a chosen second needs WAL archiving, or a managed database such as Amazon RDS with automated backups.
- **The backup is not encrypted by the application.** It relies on the volume. A production backup should be encrypted and access controlled.
- **A restore of a large database takes longer than 4 seconds**, and I did not measure that, because the project has a few thousand rows at most.

## How to repeat it

```bash
helm upgrade campusslot helm/campusslot ... --set backup.enabled=true
kubectl create job manual-backup --from=cronjob/campusslot-backup -n campusslot
scripts/restore-backup.sh            # newest backup
```
