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
| 1 | Canary releases that the SLO judges (Argo Rollouts and Prometheus analysis) | A release that is ready but bad is aborted by its own metrics | **drill run in CI:** aborted in 79 s with 45 of 1800 requests failed, against 521 of 1800 without a canary; it was at 50 percent by then, not 10 ([method and predictions](../engineering/canary-releases.md), [ADR 0015](../adr/0015-canary-releases-judged-by-their-own-metrics.md)) |
| 2 | Policy and supply chain enforced at admission (Kyverno, NetworkPolicies) | An unsigned image and an unwanted connection are both refused | written and checked in CI, drill not run yet ([method and predictions](../engineering/admission-and-network-policy.md), [ADR 0016](../adr/0016-admission-policy-and-default-deny-networking.md)) |
| 3 | Database reliability (operator, replica, point-in-time restore) | The primary is killed under load, with failover time, RPO and RTO measured | written and checked in CI, drill not run yet ([method and predictions](../engineering/database-reliability.md), [ADR 0017](../adr/0017-database-run-by-an-operator.md)) |
| 4 | Signals that link to each other (traces, error budget dashboards) | One slow request is followed from the alert to the trace to the log line | written, 7 unit tests pass, drill not run yet ([method and predictions](../engineering/linked-signals.md), [ADR 0018](../adr/0018-link-metrics-traces-and-logs-by-trace-id.md)) |
| 5 | Several environments with promotion through Git | A change moves from dev to staging to prod, and drift is reverted | written, 21 unit tests pass, drill not run yet ([method and predictions](../engineering/environments-and-promotion.md), [ADR 0019](../adr/0019-environments-as-directories-promotion-by-pull-request.md)) |
| 6 | Game day | Node, pod, database and a bad canary, all under steady load | written, 25 unit tests pass, run not done yet ([method and hypotheses](../engineering/game-day.md), [ADR 0020](../adr/0020-failures-as-hypotheses-under-load.md)) |

All six phases are written, and CI checks what it can without a cluster (the charts render, the policies and the
manifests are valid, the unit tests of the tools pass). **No drill has run on a cluster yet.** Every phase document has
predictions that were written before the run and an empty results section. The order of the runs, what to look at first
and how to write the results back are in [RUNNING-THE-DRILLS.md](RUNNING-THE-DRILLS.md).

Left out on purpose: service mesh, multi-cluster, multi-region, and anything that needs a paid cloud account.
