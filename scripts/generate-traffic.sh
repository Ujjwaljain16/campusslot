#!/usr/bin/env bash
# Generate a realistic mix of requests so the Grafana dashboard has something to show.
#
#   scripts/generate-traffic.sh [seconds] [base-url]
#
# Each round does what a few real users would do: load the day view, create a booking in a free
# slot (201), try to take the same slot again (409), and look up a booking that does not exist (404).
set -uo pipefail

SECONDS_TO_RUN="${1:-120}"
BASE="${2:-http://localhost:8080}"
export MSYS_NO_PATHCONV=1

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
json=(-H 'Content-Type: application/json')

created=0; conflicts=0; notfound=0; reads=0
end=$((SECONDS + SECONDS_TO_RUN))
round=0
while [ "$SECONDS" -lt "$end" ]; do
  round=$((round + 1))
  room=$(( (round % 6) + 1 ))
  # A different future day for every round keeps the new booking from clashing with earlier ones.
  day=$(date -u -d "+$((round % 300 + 10)) days" +%Y-%m-%d 2>/dev/null || date -u -v+"$((round % 300 + 10))"d +%Y-%m-%d)
  body="{\"room_id\":$room,\"purpose\":\"Traffic round $round\",\"booked_by\":\"load-user\",\"start_time\":\"${day}T09:00:00Z\",\"end_time\":\"${day}T10:00:00Z\"}"

  for path in /api/info /api/rooms "/api/bookings?day=${day}" "/api/bookings/stats?day=${day}"; do
    code "$BASE$path" >/dev/null; reads=$((reads + 1))
  done

  [ "$(code -X POST "${json[@]}" -d "$body" "$BASE/api/bookings")" = "201" ] && created=$((created + 1))
  [ "$(code -X POST "${json[@]}" -d "$body" "$BASE/api/bookings")" = "409" ] && conflicts=$((conflicts + 1))
  [ "$(code "$BASE/api/bookings/999999")" = "404" ] && notfound=$((notfound + 1))
  sleep 0.2
done

echo "rounds=$round reads=$reads created(201)=$created conflicts(409)=$conflicts notfound(404)=$notfound"
