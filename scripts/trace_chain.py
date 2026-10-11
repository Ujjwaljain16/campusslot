#!/usr/bin/env python3
"""Follow one slow request through the three signals, and say which link of the chain holds.

    python scripts/trace_chain.py --base http://localhost:8080 --prometheus http://localhost:9090 \
        --tempo http://localhost:3200 --loki http://localhost:3100

1. send requests through the ingress and keep the slowest one, with its X-Trace-Id
2. the metric: Prometheus shows that the share of fast requests dropped (the objective that the latency alert watches)
3. the trace: Tempo finds that request by a TraceQL search on its duration, and returns its spans
4. the log: Loki returns the log line of the same request, found by the trace id alone

A missing link is a finding, and the output names it. Standard library only.
"""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request


def get_json(url: str, timeout: float = 10):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def spans_of(node) -> list[dict]:
    """Every span in a Tempo response, whatever the nesting of the JSON is."""
    found: list[dict] = []
    if isinstance(node, dict):
        if "startTimeUnixNano" in node and "endTimeUnixNano" in node and "name" in node:
            found.append(node)
        for value in node.values():
            found.extend(spans_of(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(spans_of(item))
    return found


def attribute(span: dict, key: str):
    for item in span.get("attributes", []):
        if item.get("key") == key:
            value = item.get("value", {})
            return next(iter(value.values()), None)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--path", default="/api/rooms")
    ap.add_argument("--prometheus", default="http://localhost:9090")
    ap.add_argument("--tempo", default="http://localhost:3200")
    ap.add_argument("--loki", default="http://localhost:3100")
    ap.add_argument("--requests", type=int, default=40)
    ap.add_argument("--slow-ms", type=int, default=250)
    ap.add_argument("--wait", type=int, default=45, help="seconds to wait for Tempo and Loki to show the request")
    args = ap.parse_args()

    passed = failed = 0

    def result(ok: bool, what: str, detail: str = "") -> None:
        nonlocal passed, failed
        passed += ok
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {what}")
        if detail:
            print(f"      {detail}")

    # 1. the requests
    observed = []
    for _ in range(args.requests):
        began = time.perf_counter()
        try:
            with urllib.request.urlopen(args.base + args.path, timeout=10) as response:
                response.read()
                observed.append(((time.perf_counter() - began) * 1000, response.headers.get("X-Trace-Id"), response.status))
        except urllib.error.HTTPError as exc:
            observed.append(((time.perf_counter() - began) * 1000, exc.headers.get("X-Trace-Id"), exc.code))
        time.sleep(0.05)
    slowest = max(observed)
    millis, trace_id, status = slowest
    print(f"sent {len(observed)} requests, the slowest took {millis:.0f} ms (HTTP {status})")
    result(bool(trace_id), "the response of the slowest request names its trace (X-Trace-Id)", trace_id or "tracing is off: set tracing.enabled=true")
    if not trace_id:
        return 1

    # 2. the metric
    try:
        data = get_json(f"{args.prometheus}/api/v1/query?" + urllib.parse.urlencode({"query": "campusslot:http_fast_ratio:rate10m"}))
        samples = data["data"]["result"]
        ratio = float(samples[0]["value"][1]) if samples else None
        if ratio is None:
            result(False, "the metric: the share of fast requests", "no data yet: is prometheusRule.enabled on, and has a rate window passed?")
        else:
            result(ratio < 0.95, "the metric: the share of fast requests is below the objective of 95 percent", f"{ratio:.1%} of the requests of the last 10 minutes were within 0.25 s")
    except Exception as exc:
        result(False, "the metric: Prometheus could not be asked", str(exc))

    # 3. the trace
    deadline = time.time() + args.wait
    found = False
    trace = None
    while time.time() < deadline:
        try:
            query = f'{{resource.service.name="campusslot-backend" && duration > {args.slow_ms}ms}}'
            window = {"q": query, "limit": 100, "start": int(time.time()) - 900, "end": int(time.time()) + 60}
            search = get_json(f"{args.tempo}/api/search?" + urllib.parse.urlencode(window))
            ids = {t["traceID"] for t in search.get("traces", [])}
            if trace_id in ids:
                found = True
                trace = get_json(f"{args.tempo}/api/traces/{trace_id}")
                break
        except Exception as exc:
            last_error = str(exc)
        time.sleep(3)
    result(found, f"the trace: Tempo finds the request with a TraceQL search for duration > {args.slow_ms} ms", f"trace id {trace_id}")
    if trace is not None:
        spans = spans_of(trace)
        server = [s for s in spans if attribute(s, "http.route")]
        database = [s for s in spans if attribute(s, "db.system")]
        if server:
            total_ms = (int(server[0]["endTimeUnixNano"]) - int(server[0]["startTimeUnixNano"])) / 1e6
            in_db = sum((int(s["endTimeUnixNano"]) - int(s["startTimeUnixNano"])) / 1e6 for s in database)
            result(
                True,
                f"the trace has {len(spans)} spans: the request ({attribute(server[0], 'http.route')}) and {len(database)} database statements",
                f"the request took {total_ms:.0f} ms, the database part {in_db:.1f} ms, so {total_ms - in_db:.0f} ms were spent outside the database",
            )
        else:
            result(False, "the trace has a span of the request", f"{len(spans)} spans, none with an http.route")

    # 4. the log
    deadline = time.time() + args.wait
    lines: list[str] = []
    while time.time() < deadline and not lines:
        try:
            now = time.time_ns()
            query = f'{{namespace="campusslot", component="backend"}} | json | trace_id="{trace_id}"'
            params = {"query": query, "start": now - 900 * 10**9, "end": now + 60 * 10**9, "limit": 20}
            logs = get_json(f"{args.loki}/loki/api/v1/query_range?" + urllib.parse.urlencode(params))
            for stream in logs["data"]["result"]:
                lines.extend(value[1] for value in stream["values"])
        except Exception as exc:
            last_error = str(exc)
        if not lines:
            time.sleep(3)
    result(bool(lines), "the log: Loki returns the log line of the same request, found by the trace id alone", lines[0][:240] if lines else "no line")

    print("----")
    print(f"passed: {passed}, failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
