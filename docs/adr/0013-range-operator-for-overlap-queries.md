# ADR 0013: Ask "what overlaps this period" with a range operator and a GiST index

Status: accepted

## Context

The day view, the overlap check before a booking and the statistics all ask which bookings overlap a period. I wrote the question as two comparisons (`start_time < end AND end_time > start`). Measured on 1 thousand to 200 thousand bookings, the pages read grew in step with the table, from 12 to about 2500, because the first comparison is true for almost every old row and no B-tree can narrow that down. See [data-scale](../engineering/data-scale.md).

## Options considered

- Leave it. At campus volume (a few thousand bookings a year) it is fast enough today.
- A B-tree on `(room_id, end_time)`. It helps only when the room is known and it still reads the old rows on one side.
- Add a lower bound for `start_time` using the maximum booking length. It works with ordinary indexes, but it makes the query correct only while every row obeys a limit that the database does not enforce (the limit is a setting of the application).
- Range overlap (`&&`) and containment (`@>`) on `tstzrange(start_time, end_time, '[)')`, served by a GiST index.
- Partition the table by month. Useful for archiving, but a much bigger change for this size.

## Decision

The range operators, with the existing exclusion constraint index for the overlap check and a new GiST index (migration 0004) for the queries without a room and status. A helper in the booking routes falls back to the two comparisons on SQLite, which the fast tests use.

## Consequences

- At 200 thousand rows the pages read dropped from about 2500 to between 4 and 30 and stayed flat as the table grew. Through the API, the day view for all rooms went from 21 to 113 requests per second.
- Costs: 14 MB more index (48 percent), a bulk load about a third slower, and slightly slower queries on tiny tables (0.37 ms instead of 0.05 ms at 1 thousand rows).
- The `'[)'` bounds must be part of the SQL text. As a bind parameter, they prevent the planner from matching the index expression in a generic plan.
- Two PostgreSQL tests protect the result: one proves that the new predicate means exactly the same as the old one at every boundary, and one fails if these queries go back to a sequential scan.
- One linear query remains (the total count on the statistics page, about 57 ms at 200 thousand rows).

## What I would do in production

Create the index with `CREATE INDEX CONCURRENTLY`, so that bookings can still be written while it builds. Watch the real table growth before adding anything else, and partition by month only if old bookings need to be archived.
