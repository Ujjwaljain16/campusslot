#!/usr/bin/env python3
"""Compute the four DORA metrics from the real GitHub Actions and git history of this repository.

    python scripts/dora.py                 # print a Markdown report
    python scripts/dora.py --write         # also write docs/engineering/dora.md

Definitions used here (a "deployment" is a green run of the pipeline on main, which ends with the
Helm deployment to a throw-away kind cluster; deployments to my local Minikube cluster are manual
and are not counted):

* Deployment frequency: runs on main per calendar day in which the deploy job succeeded.
* Lead time for changes: from the commit time of the pushed head commit to the end of its green run.
* Change failure rate: failed runs divided by all finished runs (cancelled runs are left out).
* Time to restore: from the end of a failed run to the end of the next green run.

The numbers describe a project that was built in a few days, so they say more about how the pipeline
behaved while I was learning than about a mature team.
"""

import argparse
import json
import statistics
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

REPO = "Ujjwaljain16/campusslot"
ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True, cwd=ROOT)


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def human(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


def load_runs() -> list[dict]:
    raw = run(
        [
            "gh",
            "run",
            "list",
            "-R",
            REPO,
            "--limit",
            "500",
            "--event",
            "push",
            "--branch",
            "main",
            "--json",
            "databaseId,headSha,conclusion,status,createdAt,updatedAt",
        ]
    )
    runs = [r for r in json.loads(raw) if r["status"] == "completed"]
    runs.sort(key=lambda r: r["createdAt"])
    return runs


def deployed(run_id: int) -> bool:
    """A deployment is a run in which the kind deploy job really succeeded. Since the pipeline skips
    the heavy jobs for documentation-only changes, a green run is not always a deployment."""
    jobs = json.loads(run(["gh", "run", "view", str(run_id), "-R", REPO, "--json", "jobs"]))["jobs"]
    return any(
        j["name"] == "Deploy with Helm (kind)" and j["conclusion"] == "success" for j in jobs
    )


def commit_time(sha: str) -> datetime:
    return parse(run(["git", "show", "-s", "--format=%cI", sha]).strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write docs/engineering/dora.md")
    args = parser.parse_args()

    runs = load_runs()
    finished = [r for r in runs if r["conclusion"] in ("success", "failure")]
    cancelled = [r for r in runs if r["conclusion"] == "cancelled"]
    green_all = [r for r in finished if r["conclusion"] == "success"]
    green = [r for r in green_all if deployed(r["databaseId"])]
    skipped_docs = len(green_all) - len(green)
    red = [r for r in finished if r["conclusion"] == "failure"]
    if not finished:
        print("no finished runs found", file=sys.stderr)
        return 1

    first, last = parse(finished[0]["createdAt"]), parse(finished[-1]["updatedAt"])
    days = max((last.date() - first.date()).days + 1, 1)
    per_day = Counter(parse(r["updatedAt"]).date().isoformat() for r in green)

    lead = []
    for r in green:
        try:
            lead.append(parse(r["updatedAt"]) - commit_time(r["headSha"]))
        except subprocess.CalledProcessError:
            continue  # the commit is not in this clone, so the lead time cannot be computed

    restore = []
    for r in red:
        later = [g for g in green if g["createdAt"] > r["createdAt"]]
        if later:
            restore.append(parse(later[0]["updatedAt"]) - parse(r["updatedAt"]))

    lines = [
        "# DORA metrics",
        "",
        f"Computed by `scripts/dora.py` from the Actions history of `{REPO}` on {datetime.now().date().isoformat()}. "  # noqa: E501
        f"Window: {first.date()} to {last.date()} ({days} calendar days).",
        "",
        "| Metric | Value | How it is measured |",
        "|---|---|---|",
        f"| Deployment frequency | {len(green)} deployments in {days} days, {len(green) / days:.1f} per day | Runs on main in which the kind deployment job succeeded, {skipped_docs} green runs without a deployment left out (earlier than the deploy job, or documentation only) |",  # noqa: E501
        f"| Lead time for changes | median {human(statistics.median(lead))}, longest {human(max(lead))} | Commit time of the pushed head commit to the end of its green run |",  # noqa: E501
        f"| Change failure rate | {len(red)} of {len(finished)} finished runs, {100 * len(red) / len(finished):.0f} percent | Failed runs divided by finished runs, {len(cancelled)} cancelled runs left out |",  # noqa: E501
        f"| Time to restore | median {human(statistics.median(restore)) if restore else 'n/a'}, longest {human(max(restore)) if restore else 'n/a'} | End of a failed run to the end of the next green run |",  # noqa: E501
        "",
        "## Green runs per day",
        "",
        "| Day | Deployments |",
        "|---|---|",
    ]
    lines += [f"| {day} | {count} |" for day, count in sorted(per_day.items())]
    lines += ["", "## Failed runs", "", "| Run | Commit | Restored after |", "|---|---|---|"]
    for r in red:
        later = [g for g in green if g["createdAt"] > r["createdAt"]]
        fixed = human(parse(later[0]["updatedAt"]) - parse(r["updatedAt"])) if later else "not yet"
        subject = run(["git", "show", "-s", "--format=%s", r["headSha"]]).strip()[:70]
        lines.append(f"| {r['databaseId']} | `{r['headSha'][:7]}` {subject} | {fixed} |")

    report = "\n".join(lines) + "\n"
    print(report)
    if args.write:
        out = ROOT / "docs" / "engineering" / "dora.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"written {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
