# Load test: what limits one backend pod, and what I changed

## Why this exists

The backend had never been tested at its limits, so the numbers in the chart (500m CPU, one uvicorn process) were guesses. A capacity number is the basis for three decisions: how many pods to run, what CPU to give each one, and when the autoscaler should add more. I measured one pod under saturating load and changed one variable at a time, keeping only what helped.

## Method

- [`scripts/loadgen.py`](../../scripts/loadgen.py) runs in a pod inside the cluster, so the numbers describe the backend and not my laptop's network. 16 threads each keep one connection open and send the next request as soon as the last one has finished, for 30 seconds. That measures throughput.
- One backend replica, autoscaler off, and 200 thousand bookings in the database, so the day view includes the cost of a big table (see [data-scale](data-scale.md)).
- CPU, throttling and memory come from Prometheus (the cAdvisor series `container_cpu_cfs_throttled_periods_total` and `container_cpu_usage_seconds_total`), for the 30 seconds of each run.
- Two workloads: `GET /api/rooms` (the hottest route, a tiny query) and `GET /api/bookings?day=today` (the day view over a big table). Each run was repeated twice, and the table shows the median of the two.
- The transcripts are in [`docs/evidence`](../evidence) (`load-C0.txt` to `load-C6.txt`, `load-connections.txt`, `load-metrics-two-workers.txt`).

**What this does not show:** the node has 4 CPUs and also runs Prometheus, Grafana, Loki and PostgreSQL, so absolute numbers are lower than a dedicated machine would give, and they vary. Two runs of the same configuration differed by anything from 0 to 18 percent (the two day-view runs at 2000m gave 250 and 296 requests per second), so differences smaller than about 15 percent below are not results. Only writes were measured separately (see [data-scale](data-scale.md)), not as part of this load.

## Baseline

At the original settings (500m CPU limit, one worker) one pod handled **153 requests per second on `/api/rooms`** (p95 178 ms) and **102 on the day view** (p95 248 ms). The pod used 0.43 to 0.50 cores, which is exactly its limit, and the kernel throttled it in 96 to 100 percent of the scheduling periods. The pod was waiting for CPU quota and not for anything else.

## One variable at a time

| Run | What changed | `/api/rooms` req/s (p95) | Day view req/s (p95) | Throttled | Memory | Decision |
|---|---|---|---|---|---|---|
| C0 | nothing (500m, 1 worker) | 153 (178 ms) | 102 (248 ms) | 96 to 100% | 75 MiB | baseline |
| C1 | CPU limit 500m to **1000m** | **342 (74 ms)** | **254 (95 ms)** | 67 to 87% | 75 MiB | **adopted** |
| C5 | CPU limit 2000m | 392 (65 ms) | 273 (101 ms) | 0% | 75 MiB | not adopted |
| C3 | 2 workers at 500m | 102 (306 ms) | 92 (348 ms) | 83 to 96% | 171 to 233 MiB | not adopted, worse |
| C2 | 2 workers at 1000m | 316 (70 ms) | 226 (136 ms) | 7 to 94% | 167 MiB | not adopted, no gain |
| C6 | 2 workers at 2000m | 312 (74 ms) | 289 (126 ms) | 0% | 166 MiB | not adopted, no gain |
| C4 | ETag revalidation on `/api/rooms` at 500m | 165 (178 ms) | not applicable | 74 to 100% | 74 MiB | not adopted, no gain |

### What I adopted: a CPU limit of 1000m

Doubling the limit made one pod 2.2 times faster on the room list and 2.5 times faster on the day view, and it halved the p95. A single Python process cannot use much more than one core (it peaked at 0.89 to 1.13 cores even with a 2000m limit), so the next step to 2000m gained only 7 to 15 percent, which is within the noise of this setup. 1000m is the point where the extra CPU stops paying for itself, so that is the value I chose.

The **trade-off** is that the limit is not a reservation: a pod may now take up to a full core from its neighbours when it is busy. On a small node that matters, which is why the request (what the scheduler reserves) is sized separately in [cost-and-sizing](cost-and-sizing.md).

### What I did not adopt, and why

- **Two uvicorn workers.** I expected this to help, and it did not. At the same 500m limit it was a third slower and the p95 nearly doubled, because both processes compete for the same quota and each one loads its own copy of the application (170 MiB instead of 75). With more quota it was no faster than one worker: 316 against 342 requests per second at 1000m, and 312 against 392 at 2000m. I checked three explanations. The load generator was not the limit (it used 0.08 cores). The node was not the limit (all pods together used 0.94 of 4 cores, PostgreSQL 0.11). Long-lived connections sticking to one worker was not the cause either: with a new connection for every request, two workers still reached only 273 requests per second against 302 for one ([`load-connections.txt`](../evidence/load-connections.txt)). **I did not find the cause**, so I report the result and not an explanation.
- **Two workers also break the metrics.** Prometheus counters live inside each process. With two workers and no multiprocess directory, I sent 1404 requests and `/metrics` reported 736 on most scrapes and 668 on one, which is one worker's share each time ([`load-metrics-two-workers.txt`](../evidence/load-metrics-two-workers.txt)). Every request count, error ratio and alert built on them would be wrong. Adopting more workers would need `PROMETHEUS_MULTIPROC_DIR` on a writable volume, and nothing here justifies that work. More capacity comes from more pods, which the autoscaler already does.
- **ETag and `Cache-Control: no-cache` on the room list.** A client that sends the ETag back gets an empty 304 and not the list. The server still runs the query to compute the ETag, so the CPU saved is small: 155 and 175 requests per second against 153. That is inside the noise (up to 18 percent between repeats of one configuration), so I removed the code. It would save bandwidth, which I did not measure, and the browser would still make a request on every page load.

## What the load test taught me

- **A resource limit is a performance setting, not only a safety net.** The first thing that limited the service was the limit I had written down without measuring.
- **The expected win is not always real.** Two of the three ideas on my list (workers and caching) did nothing, and one made things worse. Keeping them out of the code is as much a result as the CPU change.
- **Measure the scaling signal too.** The autoscaler works on CPU as a percentage of the request, so the sizing below matters as much as the limit.

## How to repeat it

```bash
kubectl run loadgen ...        # any pod with python, for example the backend image
kubectl exec -i loadgen -- python - http://campusslot-backend:8000/api/rooms --threads 16 --seconds 30 < scripts/loadgen.py
```

Change one value, for example `--set backend.resources.limits.cpu=1000m`, redeploy with one replica and the autoscaler off, and run it again.
