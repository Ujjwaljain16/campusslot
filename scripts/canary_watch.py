#!/usr/bin/env python3
"""Watch a release roll out and write down what happened, with times.

    python scripts/canary_watch.py rollout  --seconds 180 --prometheus http://localhost:9090
    python scripts/canary_watch.py deployment --seconds 180

It polls the Kubernetes object once a second and prints a line whenever something changes (the phase,
the step, the share of traffic for the canary, the replica counts), each with the seconds since the
start. At the end, for a rollout, it asks Prometheus how many requests each version really served, so
the share of users that met the new version is a measured number and not the configured weight.

Run it right after "helm upgrade", at the same moment as scripts/probe.py, which counts what the users saw.
"""

import argparse
import json
import subprocess
import time
import urllib.parse
import urllib.request


def kubectl_json(*args: str) -> dict:
    out = subprocess.run(["kubectl", *args, "-o", "json"], capture_output=True, text=True, timeout=20)
    return json.loads(out.stdout) if out.returncode == 0 and out.stdout else {}


def rollout_state(namespace: str, name: str) -> dict:
    obj = kubectl_json("get", "rollout", name, "-n", namespace)
    status = obj.get("status", {})
    weights = status.get("canary", {}).get("weights", {}).get("canary", {})
    return {
        "phase": status.get("phase", "?"),
        "step": status.get("currentStepIndex", "-"),
        "canary weight": weights.get("weight", 0),
        "message": status.get("message", ""),
        "canary hash": status.get("currentPodHash", ""),
        "stable hash": (status.get("stableRS") or ""),
    }


def deployment_state(namespace: str, name: str) -> dict:
    status = kubectl_json("get", "deployment", name, "-n", namespace).get("status", {})
    return {
        "updated": status.get("updatedReplicas", 0),
        "ready": status.get("readyReplicas", 0),
        "available": status.get("availableReplicas", 0),
        "replicas": status.get("replicas", 0),
    }


def prometheus_value(base: str, query: str) -> float:
    url = f"{base}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    with urllib.request.urlopen(url, timeout=10) as response:
        data = json.load(response)
    result = data["data"]["result"]
    return float(result[0]["value"][1]) if result else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["rollout", "deployment"])
    ap.add_argument("--namespace", default="campusslot")
    ap.add_argument("--name", default="campusslot-backend")
    ap.add_argument("--seconds", type=float, default=180)
    ap.add_argument("--prometheus", default="")
    args = ap.parse_args()

    read = rollout_state if args.kind == "rollout" else deployment_state
    start = time.time()
    last: dict = {}
    hashes: dict = {}
    # The analysis shows up as its own object. Its name and result are the evidence of why a rollout was aborted.
    seen_runs: dict = {}

    while time.time() - start < args.seconds:
        state = read(args.namespace, args.name)
        shown = {k: v for k, v in state.items() if k not in ("canary hash", "stable hash")}
        if shown != last:
            print(f"+{time.time() - start:6.1f} s  " + ", ".join(f"{k}={v}" for k, v in shown.items()), flush=True)
            last = shown
        if args.kind == "rollout":
            if state["canary hash"] and state["canary hash"] != state["stable hash"]:
                hashes = {"canary": state["canary hash"], "stable": state["stable hash"]}
            for run in kubectl_json("get", "analysisrun", "-n", args.namespace).get("items", []):
                phase = run.get("status", {}).get("phase", "?")
                key = run["metadata"]["name"]
                if seen_runs.get(key) != phase:
                    seen_runs[key] = phase
                    print(f"+{time.time() - start:6.1f} s  analysis {key}: {phase}", flush=True)
        time.sleep(1)

    if args.kind == "rollout" and args.prometheus and hashes:
        window = f"{int(args.seconds)}s"
        total = prometheus_value(args.prometheus, f'sum(increase(http_requests_total{{namespace="{args.namespace}",handler=~"/api.*"}}[{window}]))')
        for label, h in hashes.items():
            if not h:
                continue
            value = prometheus_value(
                args.prometheus,
                f'sum(increase(http_requests_total{{namespace="{args.namespace}",handler=~"/api.*",pod=~"{args.name}-{h}-.*"}}[{window}]))',
            )
            errors = prometheus_value(
                args.prometheus,
                f'sum(increase(http_requests_total{{namespace="{args.namespace}",handler=~"/api.*",status="5xx",pod=~"{args.name}-{h}-.*"}}[{window}]))',
            )
            share = 100 * value / total if total else 0
            print(f"{label} version ({h}): {value:.0f} of {total:.0f} requests ({share:.1f} percent), {errors:.0f} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
