#!/usr/bin/env python3
"""Send a steady stream of requests and report how many failed, so that a rollout or a failure
can be judged with numbers.

    python scripts/probe.py http://localhost:8080/api/rooms --seconds 90 --interval 0.1

Every request has a timeout. A failure is a connection error, a timeout or a status of 500 or
higher. The result lists the failures with the time at which they happened, which shows whether
they came in one burst (a short outage) or were spread out (flaky).
"""

import argparse
import statistics
import time
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--interval", type=float, default=0.1)
    ap.add_argument("--timeout", type=float, default=3)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    start = time.perf_counter()
    latencies: list[float] = []
    failures: list[tuple[float, str]] = []
    total = 0
    next_tick = start

    while time.perf_counter() - start < args.seconds:
        total += 1
        began = time.perf_counter()
        try:
            with urllib.request.urlopen(args.url, timeout=args.timeout) as response:
                response.read()
            latencies.append((time.perf_counter() - began) * 1000)
        except urllib.error.HTTPError as exc:
            if exc.code >= 500:
                failures.append((began - start, f"HTTP {exc.code}"))
            else:
                latencies.append((time.perf_counter() - began) * 1000)
        except Exception as exc:  # connection refused, reset, timeout
            failures.append((began - start, type(exc).__name__))
        next_tick += args.interval
        time.sleep(max(0.0, next_tick - time.perf_counter()))

    label = f"[{args.label}] " if args.label else ""
    print(
        f"{label}requests: {total}, failed: {len(failures)} "
        f"({100 * len(failures) / total:.2f} percent)"
    )
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[int(0.95 * (len(ordered) - 1))]
        print(
            f"{label}latency of successful requests: median {statistics.median(ordered):.1f} ms, "
            f"p95 {p95:.1f} ms, slowest {ordered[-1]:.1f} ms"
        )
    if failures:
        print(f"{label}first failure at +{failures[0][0]:.1f} s, last at +{failures[-1][0]:.1f} s")
        kinds: dict[str, int] = {}
        for _, kind in failures:
            kinds[kind] = kinds.get(kind, 0) + 1
        print(f"{label}kinds: {kinds}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
