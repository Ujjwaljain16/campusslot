# CampusSlot v2

`main` is the version that was submitted for the course (tag `v1.0-capstone`). This branch, `v2`, is where the project
grows from "built and deployed" into a platform that releases, protects and recovers itself. Nothing here is merged into
`main` until the course grading is finished.

## Rules

- The same method as v1: measure, change one thing, prove it with a number, write a decision record, keep the failures.
- Everything runs on local clusters (Minikube or kind). **No cloud account and no cost.**
- Every phase ends with a drill that has a result a reviewer can open.

## Phases

| # | Phase | The drill that proves it | Status |
|---|---|---|---|
| 1 | Canary releases that the SLO judges (Argo Rollouts and Prometheus analysis) | A release that is ready but bad is aborted at 10 percent of the traffic | built and checked in CI, drill not run yet ([method and predictions](../engineering/canary-releases.md), [ADR 0015](../adr/0015-canary-releases-judged-by-their-own-metrics.md)) |
| 2 | Policy and supply chain enforced at admission (Kyverno, NetworkPolicies) | An unsigned image and an unwanted connection are both refused | planned |
| 3 | Database reliability (operator, replica, point-in-time restore) | The primary is killed under load, with failover time, RPO and RTO measured | planned |
| 4 | Signals that link to each other (traces, error budget dashboards) | One slow request is followed from the alert to the trace to the log line | planned |
| 5 | Several environments with promotion through Git | A change moves from dev to staging to prod, and drift is reverted | planned |
| 6 | Game day | Node, pod, database and a bad canary, all under steady load | planned |

Left out on purpose: service mesh, multi-cluster, multi-region, and anything that needs a paid cloud account.
