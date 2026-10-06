# ADR 0014: One uvicorn worker per pod, and more capacity from more pods

Status: accepted

## Context

A pod at the original 500m CPU limit handled 153 requests per second and was throttled in nearly every scheduling period. Two ways to get more capacity were on the table: give a pod more CPU, and run more worker processes inside it. The measurements are in [performance](../engineering/performance.md).

## Options considered

- Two or more uvicorn workers in each pod.
- A higher CPU limit with one worker.
- More pods, with the horizontal autoscaler.

## Decision

One worker per pod. The CPU limit is 1000m, because a single Python process stops getting faster at about one core. More capacity comes from more pods, which the autoscaler adds on CPU.

## Consequences

- At 1000m one pod handled about 342 requests per second on the room list, 2.2 times the baseline, and the p95 halved.
- Two workers gave no measurable gain at 500m, 1000m or 2000m (and a third less at 500m), and they used 170 MiB of memory instead of 75. I did not find out why, after ruling out the load generator, the node and long-lived connections.
- Two workers also made `/metrics` wrong: the Prometheus counters live inside each process, so a scrape returned about half of the 1404 requests I had sent. Every error ratio and alert would have been wrong. Using several workers would need a multiprocess metrics directory on a writable volume.
- The cost of this choice is that one pod cannot use more than about one core, so a very busy single pod is a ceiling. The autoscaler and the pod disruption budget already handle that.

## What I would do in production

Keep one worker per pod and scale out, as long as the pods are small. If memory per pod ever matters more than simplicity, test again with a multiprocess metrics directory first, and measure on a dedicated node, so that the result does not depend on a shared laptop cluster.
