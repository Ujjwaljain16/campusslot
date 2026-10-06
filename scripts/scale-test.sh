#!/usr/bin/env bash
# Measure how the booking queries behave as the bookings table grows.
#
#   scripts/scale-test.sh 1000 10000 50000 200000
#
# For every size it reloads the table with non-overlapping bookings that end today, refreshes the
# planner statistics, and runs EXPLAIN (ANALYZE, BUFFERS) on the queries that the API sends. It
# prints one summary line per query and keeps the full plans in $OUT. The bookings table is emptied
# at the end, so run it only against a throw-away database (the local Minikube cluster).
# Details and results: docs/engineering/data-scale.md
set -euo pipefail

NAMESPACE="${NAMESPACE:-campusslot}"
POD="${POD:-campusslot-postgres-0}"
OUT="${OUT:-docs/evidence/scale}"
SIZES=("$@")
[ ${#SIZES[@]} -gt 0 ] || SIZES=(1000 10000 50000 200000)
mkdir -p "$OUT"

psql() { kubectl exec -i -n "$NAMESPACE" "$POD" -- psql -U campusslot -d campusslot -v ON_ERROR_STOP=1 "$@"; }

# Queries as the API issues them. VARIANT=before is the original predicate (two comparisons),
# VARIANT=after is the range overlap operator, which the GiST indexes can serve.
VARIANT="${VARIANT:-before}"
D="'$(date -u +%F) 00:00+00'::timestamptz"
if [ "$VARIANT" = after ]; then
  overlap() { echo "tstzrange(start_time, end_time, '[)') && tstzrange($1, $2, '[)')"; }
  RUNNING="tstzrange(start_time, end_time, '[)') @> now()"
else
  overlap() { echo "start_time < $2 AND end_time > $1"; }
  RUNNING="start_time <= now() AND end_time > now()"
fi
DAY="$(overlap "$D" "($D + interval '1 day')")"
SLOT="$(overlap "($D + interval '20 minutes')" "($D + interval '30 minutes')")"

queries() {
cat <<SQL
\echo ### Q1 day view of one room
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM bookings WHERE room_id = 1 AND $DAY ORDER BY start_time, id LIMIT 200;
\echo ### Q2 day view of all rooms
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM bookings WHERE $DAY ORDER BY start_time, id LIMIT 200;
\echo ### Q3 overlap check, slot is free
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM bookings WHERE room_id = 1 AND status = 'confirmed' AND $SLOT LIMIT 1;
\echo ### Q4 statistics, total confirmed
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM bookings WHERE status = 'confirmed';
\echo ### Q5 statistics, the bookings of the day
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM bookings WHERE status = 'confirmed' AND $DAY;
\echo ### Q6 statistics, rooms in use right now
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(DISTINCT room_id) FROM bookings WHERE status = 'confirmed' AND $RUNNING;
\echo ### Q7 insert one booking
BEGIN;
EXPLAIN (ANALYZE, BUFFERS)
INSERT INTO bookings (room_id, purpose, booked_by, start_time, end_time, status) VALUES (1, 'probe', 'probe', $D + interval '3 hours 5 minutes', $D + interval '3 hours 35 minutes', 'confirmed');
ROLLBACK;
SQL
}

for n in "${SIZES[@]}"; do
  echo "=== $n bookings"
  load_start=$SECONDS
  psql -q -v n="$n" <<'SQL'
TRUNCATE bookings RESTART IDENTITY;
WITH r AS (SELECT id, row_number() OVER (ORDER BY id) - 1 AS ri FROM rooms WHERE is_active),
     c AS (SELECT count(*) AS c FROM r),
     p AS (SELECT (date_trunc('day', now() AT TIME ZONE 'utc'))::date AS today, c.c AS rooms,
                  (((:n / c.c) - 1) / 12)::int AS last_day_offset FROM c)
INSERT INTO bookings (room_id, purpose, booked_by, start_time, end_time, status)
SELECT r.id, 'scale test', 'u' || g,
       ((p.today - p.last_day_offset + ((((g - 1) / p.rooms) / 12)::int)) + ((8 + ((g - 1) / p.rooms) % 12) * interval '1 hour'))::timestamp AT TIME ZONE 'UTC',
       ((p.today - p.last_day_offset + ((((g - 1) / p.rooms) / 12)::int)) + ((8 + ((g - 1) / p.rooms) % 12) * interval '1 hour') + interval '50 minutes')::timestamp AT TIME ZONE 'UTC',
       'confirmed'
FROM generate_series(1, :n) g CROSS JOIN p JOIN r ON r.ri = (g - 1) % p.rooms;
ANALYZE bookings;
SQL
  load_secs=$((SECONDS - load_start))
  echo "loaded in ${load_secs} s; table $(psql -At -c "SELECT pg_size_pretty(pg_table_size('bookings')) || ' table, ' || pg_size_pretty(pg_indexes_size('bookings')) || ' indexes, ' || count(*) || ' rows' FROM bookings")"
  # Run every query twice and keep the second run, so the numbers describe a warm cache.
  queries | psql -q > /dev/null
  queries | psql -q > "$OUT/explain-$n.txt"
  awk '
    function row() { if (q != "") printf "  %-38s %10s ms   %-44s %s\n", q, t, scan, buf }
    /^### /  { row(); q = substr($0, 5); scan = ""; buf = ""; t = ""; next }
    /(Seq Scan|Index Scan|Index Only Scan|Bitmap Heap Scan| Insert on)/ && scan == "" {
      line = $0; sub(/^ *(-> )?/, "", line); sub(/  *\(cost.*/, "", line); sub(/ \(actual.*/, "", line); scan = line }
    /Buffers: shared/ && buf == "" { line = $0; sub(/.*Buffers: /, "", line); buf = line }
    /Execution Time/ { t = $3 }
    END { row() }
  ' "$OUT/explain-$n.txt"
done
if [ "${KEEP_DATA:-0}" != 1 ]; then
  psql -q -c "TRUNCATE bookings RESTART IDENTITY"
  echo "bookings table emptied again"
fi
