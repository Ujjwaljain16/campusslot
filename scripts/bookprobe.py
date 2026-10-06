#!/usr/bin/env python3
"""Create bookings one after another through the API and report how long each request took.

    python bookprobe.py http://campusslot-backend:8000 --count 36

It books free early-morning slots of today (00:00 to 08:00 UTC, before the opening hours that the
scale test uses), one room after another, so every request passes the overlap check and inserts a
row. That is the write path of the application. Standard library only, so it runs in the cluster.
"""

import argparse
import datetime as dt
import http.client
import json
import statistics
import time
import urllib.parse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--count", type=int, default=36)
    ap.add_argument("--rooms", type=int, default=6)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    parts = urllib.parse.urlsplit(args.base)
    conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=10)
    today = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    latencies, failures = [], 0
    for i in range(args.count):
        room = i % args.rooms + 1
        slot = i // args.rooms
        start = today + dt.timedelta(minutes=slot * 20)
        body = {
            "room_id": room,
            "purpose": "write probe",
            "booked_by": "probe",
            "start_time": start.isoformat().replace("+00:00", "Z"),
            "end_time": (start + dt.timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
        }
        began = time.perf_counter()
        conn.request(
            "POST", "/api/bookings", json.dumps(body), {"Content-Type": "application/json"}
        )
        response = conn.getresponse()
        response.read()
        if response.status == 201:
            latencies.append((time.perf_counter() - began) * 1000)
        else:
            failures += 1
    ordered = sorted(latencies)
    label = f"{args.label}: " if args.label else ""
    print(
        f"{label}created={len(ordered)} failed={failures} "
        f"median={statistics.median(ordered):.1f}ms "
        f"p95={ordered[int(0.95 * (len(ordered) - 1))]:.1f}ms max={ordered[-1]:.1f}ms"
    )


if __name__ == "__main__":
    main()
