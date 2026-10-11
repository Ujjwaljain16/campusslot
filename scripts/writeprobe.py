#!/usr/bin/env python3
"""Write steadily through the API, remember what was acknowledged, and later check that every acknowledged
write still exists. It measures what a failover or a restore did to the users' data.

    python scripts/writeprobe.py run    http://localhost:8080 --seconds 90 --rate 5 --out writes.json
    python scripts/writeprobe.py verify http://localhost:8080 writes.json

"run" creates one booking per request, each in its own free slot (a room and a quarter of an hour in 2032), so
every request passes the overlap check and inserts a row. It never retries. A request that fails is counted and
the next one goes ahead, so the outage shows as a run of failures and a gap between successes.

"verify" asks for every booking that was acknowledged with 201 and reports the ones that are gone. An
acknowledged write that is gone is data loss, which is what asynchronous replication risks during a failover and
what synchronous replication is meant to prevent. Standard library only.
"""

import argparse
import datetime as dt
import http.client
import json
import time
import urllib.parse


def connect(base: str) -> http.client.HTTPConnection:
    parts = urllib.parse.urlsplit(base)
    return http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=3)


def slot(i: int, rooms: int = 6) -> dict:
    start = dt.datetime(2032, 1, 1, tzinfo=dt.UTC) + dt.timedelta(minutes=20 * (i // rooms))
    return {
        "room_id": i % rooms + 1,
        "purpose": "write probe",
        "booked_by": "writeprobe",
        "start_time": start.isoformat().replace("+00:00", "Z"),
        "end_time": (start + dt.timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
    }


def run(args) -> int:
    began = time.perf_counter()
    interval = 1.0 / args.rate
    acknowledged: list[dict] = []
    failures: list[tuple[float, str]] = []
    successes: list[float] = []
    i = args.first_slot
    conn = connect(args.base)
    next_tick = began
    while time.perf_counter() - began < args.seconds:
        at = time.perf_counter() - began
        try:
            conn.request("POST", "/api/bookings", json.dumps(slot(i)), {"Content-Type": "application/json"})
            response = conn.getresponse()
            body = response.read()
            if response.status == 201:
                acknowledged.append({"id": json.loads(body)["id"], "at": round(at, 3)})
                successes.append(at)
            else:
                failures.append((at, f"HTTP {response.status}"))
        except Exception as exc:  # connection refused, reset, timeout
            failures.append((at, type(exc).__name__))
            conn.close()
            conn = connect(args.base)
        i += 1
        next_tick += interval
        time.sleep(max(0.0, next_tick - time.perf_counter()))

    sent = len(acknowledged) + len(failures)
    print(f"requests: {sent}, acknowledged: {len(acknowledged)}, failed: {len(failures)}")
    if failures:
        kinds: dict[str, int] = {}
        for _, kind in failures:
            kinds[kind] = kinds.get(kind, 0) + 1
        print(f"first failure at +{failures[0][0]:.1f} s, last at +{failures[-1][0]:.1f} s, kinds: {kinds}")
        # The longest time in which no write was acknowledged is the outage that a user could feel.
        gaps = [(b - a, a) for a, b in zip(successes, successes[1:])]
        if gaps:
            longest, since = max(gaps)
            print(f"longest time without an acknowledged write: {longest:.1f} s (from +{since:.1f} s)")
    json.dump({"base": args.base, "acknowledged": acknowledged}, open(args.out, "w"))
    print(f"wrote {args.out} ({len(acknowledged)} acknowledged bookings)")
    return 0


def verify(args) -> int:
    data = json.load(open(args.file))
    conn = connect(args.base)
    lost = []
    for entry in data["acknowledged"]:
        for attempt in range(3):   # the service may still be reconnecting for a moment after a failover
            try:
                conn.request("GET", f"/api/bookings/{entry['id']}")
                response = conn.getresponse()
                response.read()
                break
            except Exception:
                conn.close()
                conn = connect(args.base)
                time.sleep(1)
        else:
            lost.append(entry)
            continue
        if response.status == 404:
            lost.append(entry)
    total = len(data["acknowledged"])
    print(f"acknowledged writes: {total}, still present: {total - len(lost)}, LOST: {len(lost)}")
    if lost:
        print(f"first lost write was acknowledged at +{lost[0]['at']} s, the last at +{lost[-1]['at']} s")
    return 0 if not lost else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("base")
    r.add_argument("--seconds", type=float, default=60)
    r.add_argument("--rate", type=float, default=5, help="requests per second")
    r.add_argument("--out", default="writes.json")
    r.add_argument("--first-slot", type=int, default=0, help="start the slot numbering here to avoid an earlier run")
    r.set_defaults(func=run)
    v = sub.add_parser("verify")
    v.add_argument("base")
    v.add_argument("file")
    v.set_defaults(func=verify)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
