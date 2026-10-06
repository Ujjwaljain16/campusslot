#!/usr/bin/env python3
"""Measure how long the pipeline takes, so that a speed-up can be shown with numbers.

    python scripts/ci_timings.py                 # the last 8 green runs on main
    python scripts/ci_timings.py --runs 12 --since 2026-10-06

For every green run it records the wall-clock time from the start of the run to its end, and the
duration of each job. It prints the median over the runs, because a single run is noisy (runner
start-up and cache hits vary). The "critical path" is the wall-clock time, which is what a developer
waits for. The sum of the jobs is larger, because jobs run in parallel.
"""

import argparse
import json
import statistics
import subprocess
from datetime import datetime

REPO = "Ujjwaljain16/campusslot"


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True)


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument(
        "--since", default="", help="only runs created on or after this date, YYYY-MM-DD"
    )
    ap.add_argument("--sha", default="", help="restrict to runs whose head commit starts with this")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--event", default="push", help="push, pull_request or workflow_dispatch")
    args = ap.parse_args()

    listing = json.loads(
        gh(
            "run",
            "list",
            "-R",
            REPO,
            "--branch",
            args.branch,
            "--event",
            args.event,
            "--limit",
            "100",
            "--json",
            "databaseId,conclusion,status,createdAt,updatedAt,headSha",
        )
    )
    runs = [r for r in listing if r["conclusion"] == "success"]
    if args.since:
        runs = [r for r in runs if r["createdAt"][:10] >= args.since]
    if args.sha:
        runs = [r for r in runs if r["headSha"].startswith(args.sha)]
    runs = runs[: args.runs]

    wall, per_job, shas = [], {}, []
    for r in runs:
        detail = json.loads(
            gh(
                "run",
                "view",
                str(r["databaseId"]),
                "-R",
                REPO,
                "--json",
                "jobs,createdAt,updatedAt",
            )
        )
        starts = [parse(j["startedAt"]) for j in detail["jobs"] if j.get("startedAt")]
        ends = [parse(j["completedAt"]) for j in detail["jobs"] if j.get("completedAt")]
        wall.append((max(ends) - min(starts)).total_seconds())
        shas.append(r["headSha"][:7])
        for j in detail["jobs"]:
            if j["conclusion"] == "success":
                per_job.setdefault(j["name"], []).append(
                    (parse(j["completedAt"]) - parse(j["startedAt"])).total_seconds()
                )

    print(f"Runs measured: {len(runs)} ({', '.join(shas)})\n")
    print("| Job | Median | Fastest | Slowest |")
    print("|---|---|---|---|")
    for name, vals in sorted(per_job.items(), key=lambda kv: -statistics.median(kv[1])):
        print(
            f"| {name} | {statistics.median(vals):.0f} s | {min(vals):.0f} s | {max(vals):.0f} s |"
        )
    print(
        f"\nWall clock, start of the first job to the end of the last: median {statistics.median(wall):.0f} s "  # noqa: E501
        f"({statistics.median(wall) / 60:.1f} min), fastest {min(wall):.0f} s, slowest {max(wall):.0f} s"  # noqa: E501
    )


if __name__ == "__main__":
    main()
