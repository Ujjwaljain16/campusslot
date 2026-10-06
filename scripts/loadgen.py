#!/usr/bin/env python3
"""A small load generator that needs nothing but the Python standard library.

    python loadgen.py http://campusslot-backend:8000/api/rooms --threads 16 --seconds 30
    python loadgen.py "http://host/a,http://host/b,http://host/a" --rate 50 --seconds 60

It runs inside the cluster (see docs/engineering/performance.md), so that the numbers describe the
backend and not the network path from a laptop.

By default it is a closed loop: each thread keeps one connection open and sends the next request as
soon as the last one has finished, so the offered load adapts to how fast the server is. That makes
the result a throughput measurement, which is what is needed to size a pod. With --rate N it sends
about N requests per second in total instead, which is what is needed to measure how much CPU and
memory a given amount of traffic costs.

Several URLs, separated by commas, are used in turn, so repeating one URL gives it a larger share.
With --conditional the generator behaves like a browser that revalidates: it sends the ETag of the
last answer back in If-None-Match. With --fresh every request uses a new connection, which spreads
the load over several server workers (a long-lived connection stays with the worker that took it).
"""

import argparse
import http.client
import statistics
import threading
import time
import urllib.parse


def worker(paths, host, port, stop_at, interval, latencies, errors, statuses, conditional, fresh):
    conn = http.client.HTTPConnection(host, port, timeout=10)
    mine = []
    codes: dict[int, int] = {}
    failed = 0
    etag = None
    turn = 0
    next_tick = time.perf_counter()
    while time.perf_counter() < stop_at:
        path = paths[turn % len(paths)]
        turn += 1
        began = time.perf_counter()
        try:
            headers = {"If-None-Match": etag} if (conditional and etag) else {}
            if fresh:
                headers["Connection"] = "close"
                conn = http.client.HTTPConnection(host, port, timeout=10)
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            response.read()
            if fresh:
                conn.close()
            codes[response.status] = codes.get(response.status, 0) + 1
            if conditional and response.getheader("ETag"):
                etag = response.getheader("ETag")
            if response.status >= 500:
                failed += 1
            else:
                mine.append((time.perf_counter() - began) * 1000)
        except Exception:
            failed += 1
            conn.close()
            conn = http.client.HTTPConnection(host, port, timeout=10)
        if interval:
            next_tick += interval
            time.sleep(max(0.0, next_tick - time.perf_counter()))
    latencies.extend(mine)
    errors.append(failed)
    statuses.append(codes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="one URL, or several separated by commas")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument(
        "--rate", type=float, default=0, help="total requests per second (0 = as fast as possible)"
    )
    ap.add_argument("--label", default="")
    ap.add_argument("--conditional", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="open a new connection for every request")
    args = ap.parse_args()

    urls = [urllib.parse.urlsplit(u) for u in args.url.split(",")]
    host, port = urls[0].hostname, urls[0].port or 80
    paths = [u.path + (f"?{u.query}" if u.query else "") for u in urls]
    interval = args.threads / args.rate if args.rate else 0

    latencies, errors, statuses = [], [], []
    stop_at = time.perf_counter() + args.seconds
    threads = [
        threading.Thread(
            target=worker,
            args=(
                paths,
                host,
                port,
                stop_at,
                interval,
                latencies,
                errors,
                statuses,
                args.conditional,
                args.fresh,
            ),
        )
        for _ in range(args.threads)
    ]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - started

    ordered = sorted(latencies)
    n = len(ordered)

    def pct(p):
        return ordered[min(n - 1, int(p * n))] if n else float("nan")

    merged: dict[int, int] = {}
    for codes in statuses:
        for code, count in codes.items():
            merged[code] = merged.get(code, 0) + count
    label = f"{args.label}: " if args.label else ""
    print(
        f"{label}threads={args.threads} requests={n} errors={sum(errors)} "
        f"throughput={n / elapsed:.0f} req/s "
        f"p50={statistics.median(ordered):.1f}ms p95={pct(0.95):.1f}ms p99={pct(0.99):.1f}ms "
        f"status={dict(sorted(merged.items()))}"
    )


if __name__ == "__main__":
    main()
