# Does it stay fast when the table grows?

## Why this exists

All my tests and drills used a few dozen bookings. A query that is instant on 40 rows can scan every row on 200 thousand. The indexes in the first migration looked reasonable, but I had never checked that PostgreSQL uses them for the questions that the API really asks. I loaded 1 thousand, 10 thousand, 50 thousand and 200 thousand bookings and ran `EXPLAIN (ANALYZE, BUFFERS)` on every query that the booking routes send.

## Method

- [`scripts/scale-test.sh`](../../scripts/scale-test.sh) empties the table, loads N non-overlapping bookings for the 6 rooms (12 one-hour slots per day, the last one today), runs `ANALYZE`, and then runs each query twice and keeps the second run (warm cache).
- The queries are the ones that SQLAlchemy sends for the day view, the overlap check before a booking, and the statistics page. The full plans are in [`docs/evidence/scale-before`](../evidence/scale-before) and [`docs/evidence/scale-after`](../evidence/scale-after).
- **Shared buffer hits** (the `Buffers: shared hit=N` line of the plan) is the number I compare. A hit is an access to a block that was already in PostgreSQL's shared buffers, so it counts accesses and not distinct pages, and these plans contain no `shared read` at all because the cache is warm. It is a repeatable measure of database work for this experiment, not a substitute for latency or I/O measurements. It is the same on every run. Timings are not: on this shared 4-CPU Minikube node the same sequential scan took between 9 and 32 ms in three runs, so I give medians and ranges for time.
- The data is synthetic and regular, with no cancelled bookings and a warm cache. It shows the shape of the growth, not the production numbers.

## Baseline: the cost grew with the table

| Query | Plan at 200k rows | Shared buffer hits at 1k / 10k / 50k / 200k | Time at 200k (median of 3, range) |
|---|---|---|---|
| Day view of one room | Bitmap scan | 20 / 137 / 656 / 2605 | 7.1 ms (6.8 to 8.2) |
| Day view of all rooms | Parallel sequential scan | 12 / 123 / 617 / 2515 | 9.3 ms (8.0 to 52.3) |
| Overlap check before a booking | Sequential scan | 12 / 123 / 617 / 2469 | 19.5 ms (9.2 to 32.2) |
| Statistics: bookings of the day | Parallel sequential scan | 12 / 123 / 617 / 2469 | 17.2 ms (8.8 to 84.2) |
| Statistics: rooms in use right now | Parallel sequential scan | 12 / 123 / 617 / 2469 | 82.0 ms (74.1 to 87.1) |
| Statistics: total confirmed | Parallel sequential scan | 12 / 123 / 617 / 2469 | 79.7 ms (14.7 to 87.8) |
| Insert one booking | Insert | 79 / 79 / 81 / 83 | 1.6 ms (1.4 to 2.9) |

The buffer hits grow in exact proportion to the table: 10 times the rows, 10 times the hits. Only the insert stays flat, because the exclusion constraint checks one place in its index.

**Why the indexes did not help.** The question "which bookings overlap this period" was written as `start_time < end AND end_time > start`. For a period near today, `start_time < end` is true for almost every old row, and the index on `end_time` does not exist, so PostgreSQL correctly decides that reading the whole table is cheapest. A B-tree supports inequality scans, and PostgreSQL can use multicolumn indexes, but two opposed inequalities on two different columns do not narrow the candidates enough here, and an index scan that matches most of the table is worse than reading it once. I checked ordinary B-tree alternatives against the range form (an index on `(room_id, end_time)`, on `(room_id, start_time, end_time)`, and `(room_id, start_time)` with a one-day lower bound) at three positions in the data: a plain B-tree is fast only at one end of the data, and the lower-bound variant is as fast as the range form but is correct only while no booking is longer than the bound, which the database does not enforce. The range form needs no new index for the overlap check and carries no such assumption. The method and the plans are in [`overlap-alternatives.sql`](https://github.com/Ujjwaljain16/Personal-Portfolio-Cortex/blob/main/blog-assets/postgres-overlap-queries/overlap-alternatives.sql).

## The change

The same question as a range: `tstzrange(start_time, end_time, '[)') && tstzrange(start, end, '[)')`. It means the same thing for the inputs this project allows (periods that only touch do not overlap, as before), and a GiST index on that expression can answer it by looking at the few ranges that are near the period.

- **When the two forms are equivalent.** Both columns are `NOT NULL`, the table has `CHECK (end_time > start_time)` (`ck_bookings_end_after_start`), and the API rejects a probe whose end is not after its start. For such inputs the range form and the two comparisons give the same answer, and a test checks nine boundary cases, including bookings that only touch. They are not interchangeable for every possible input: in a PostgreSQL 17 test fixture a zero-length probe matched one row with the two comparisons and none with `&&`, because an empty range overlaps nothing, and a reversed probe makes PostgreSQL raise `range lower bound must be less than or equal to range upper bound` when the range is built. Neither can reach the query through the API; the equivalence is a property of the validated inputs, not of the SQL alone. The reproduction is in [`overlap-alternatives.sql`](https://github.com/Ujjwaljain16/Personal-Portfolio-Cortex/blob/main/blog-assets/postgres-overlap-queries/overlap-alternatives.sql) (the last statements).
- The overlap check already had such an index: the exclusion constraint `ex_bookings_no_overlap` (room and range). Writing the query as a range overlap lets PostgreSQL use it.
- The day view and the statistics have no room or status in every query, so the partial index cannot serve them. Migration [`0004`](../../backend/alembic/versions/0004_index_booking_time_ranges.py) adds a GiST index on the range alone.
- "Running right now" became a range containment (`@>`), for the same reason.
- The `'[)'` bounds are written into the SQL text and not sent as a parameter. With a parameter, the planner cannot match the query to the index expression once it switches to a generic plan.
- SQLite, which the fast tests use, has no range type, so the helper falls back to the two comparisons there ([`_overlaps` and `_contains`](../../backend/app/routes/bookings.py)).

## Result

| Query | Shared buffer hits at 200k, before and after | Time at 200k, median of 3 (before and after) |
|---|---|---|
| Day view of one room | 2605 to 11 | 7.05 ms to 0.20 ms |
| Day view of all rooms | 2515 to 5 | 9.28 ms to 0.11 ms |
| Overlap check | 2469 to 30 | 19.47 ms to 0.41 ms |
| Statistics: bookings of the day | 2469 to 5 | 17.21 ms to 0.10 ms |
| Statistics: rooms in use now | 2469 to 4 | 81.95 ms to 0.11 ms |
| Insert one booking | 83 to 48 | 1.61 ms to 1.16 ms |

After the change the buffer hits are flat from 1 thousand to 200 thousand rows (the day view touches 4 or 5 buffers at every size), which is the property I wanted. Through the whole API, at 200 thousand rows, one backend replica and 4 client threads ([`scale-api.txt`](../evidence/scale-api.txt)):

| Request | Before | After |
|---|---|---|
| Day view, all rooms | 21 req/s, median 197 ms, p95 305 ms | 113 req/s, median 14 ms, p95 81 ms |
| Day view, one room | 70 req/s, median 73 ms, p95 103 ms | 110 req/s, median 15 ms, p95 85 ms |
| Statistics | 7 req/s, median 593 ms, p95 897 ms | 16 req/s, median 211 ms, p95 400 ms |
| Create a booking | median 16.7 ms, p95 52 ms | median 4.9 ms, p95 28.5 ms |

## What the first attempt missed

My first scale test covered the day view, the overlap check and the two statistics queries that I had noticed. After the fix, the statistics endpoint was still slow (median 508 ms). The reason was a query I had overlooked: "how many rooms are in use right now", which still used the old form and scanned the whole table (11.8 ms in my first measurement of it and a median of 82 ms in three repeats at 200 thousand rows). I found it only because I also measured through the API and not just in SQL, and then I added it to the script. The lesson is to measure at the level that users see, and to read every query on the route.

## What did not change

- **The total count is still linear.** `count(*)` of confirmed bookings on the statistics page reads the whole table: about 57 ms at 200 thousand rows (range 42 to 60 after the change). It is one number on a dashboard card. Options are a maintained counter, an estimate from the planner statistics, or dropping the number. I did not build any of them, because the cost is acceptable at this size and each option adds code that must stay correct.
- **Small tables got slightly slower.** At 1 thousand rows the overlap check takes 0.37 ms instead of 0.05 ms, because touching 12 buffers is cheaper than walking an index. At real campus volume, a few thousand bookings a year, both are far below anything a user can feel, so the honest summary is that this change is headroom for growth and not a fix for a slowness that exists today.

## What it costs

| Cost | Before | After |
|---|---|---|
| Index size at 200k rows | 29 MB | 43 MB (14 MB more, 48 percent) |
| Bulk load of 200k rows | 27 s | 37 s (about a third longer) |
| Single insert | median 1.6 ms | median 1.2 ms (no visible cost, within the noise) |

## Guards so that it stays fast

Two PostgreSQL tests in [`test_postgres.py`](../../backend/tests/test_postgres.py) run in CI against a real database:

- The range form and the two comparisons give the same answer for nine boundary cases, including bookings that only touch and a booking that starts or ends exactly now.
- With 30 thousand bookings loaded, the overlap check and the day view must not use a sequential scan. If someone rewrites a query back into the slow form, this test fails.

## How to repeat it

```bash
scripts/scale-test.sh 1000 10000 50000 200000          # before the migration (VARIANT=before is the default)
VARIANT=after scripts/scale-test.sh 1000 10000 50000 200000   # after migration 0004
```

Run it only against a throw-away database: it empties the bookings table.

The API numbers were measured from a pod inside the cluster with [`scripts/loadgen.py`](../../scripts/loadgen.py) for the reads and [`scripts/bookprobe.py`](../../scripts/bookprobe.py) for the writes (it creates 36 bookings in free slots and reports the latency of each request).
