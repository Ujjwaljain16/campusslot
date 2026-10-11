#!/usr/bin/env python3
"""Watch a CloudNativePG cluster and print a line, with the seconds since the start, whenever something changes:
which instance is the primary, how many instances are ready, and the phase that the operator reports.

    python scripts/cnpg_watch.py --cluster campusslot-pg --seconds 120
    python scripts/cnpg_watch.py --cluster campusslot-pg-restore --until-healthy

It is the clock of the failover and the restore drills: the time from the moment the primary is killed to the moment
that another instance is the primary, and the time from "restore started" to "cluster in healthy state".
"""

import argparse
import json
import subprocess
import time


def cluster_state(namespace: str, name: str) -> dict:
    out = subprocess.run(
        ["kubectl", "get", "cluster", name, "-n", namespace, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if out.returncode != 0 or not out.stdout:
        return {"phase": "not found"}
    status = json.loads(out.stdout).get("status", {})
    return {
        "primary": status.get("currentPrimary", "-"),
        "ready": f"{status.get('readyInstances', 0)}/{status.get('instances', '?')}",
        "phase": status.get("phase", "?"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--namespace", default="campusslot")
    ap.add_argument("--cluster", default="campusslot-pg")
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--until-healthy", action="store_true", help="stop as soon as the cluster is healthy")
    args = ap.parse_args()

    start = time.time()
    last: dict = {}
    healthy_at = None
    while time.time() - start < args.seconds:
        state = cluster_state(args.namespace, args.cluster)
        if state != last:
            print(f"+{time.time() - start:6.1f} s  " + ", ".join(f"{k}={v}" for k, v in state.items()), flush=True)
            last = state
        if state.get("phase") == "Cluster in healthy state":
            healthy_at = healthy_at or time.time() - start
            if args.until_healthy:
                print(f"healthy after {healthy_at:.1f} s")
                return 0
        time.sleep(1)
    if args.until_healthy:
        print(f"not healthy after {args.seconds:.0f} s")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
