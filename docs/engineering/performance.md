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

## Container images: size, build time and startup

The Dockerfiles are multi-stage and non-root, but I had never measured what that is worth. [`scripts/image-metrics.sh`](../../scripts/image-metrics.sh) builds the real images and, for comparison, naive single-stage versions (the full base image, everything copied before the dependencies are installed). It builds in a temporary copy and removes everything that it creates. The transcript is [`image-metrics.txt`](../evidence/image-metrics.txt).

| Measure | Real image | Naive single stage |
|---|---|---|
| Backend size, compressed (what a pull transfers) | **61 MB** | 432 MB (7 times larger) |
| Backend size, unpacked (the files on the node) | **199 MB** | 1228 MB (6 times larger) |
| Frontend size, compressed | **25 MB** | 477 MB (19 times larger) |
| Frontend size, unpacked | **56 MB** | 1373 MB (25 times larger) |
| Backend rebuild after a one-line code change | **3.2 s** | 25.6 s (8 times slower) |
| Frontend rebuild after a one-line code change | **5.0 s** | 11.3 s (2.3 times slower) |
| Backend startup, from `docker run` to the first answer (median of 5) | 1.50 s | 1.15 s |
| Frontend startup (median of 5) | **0.49 s** | 0.84 s |

What the numbers say:

- **The slim base image does most of the work for the backend.** The build stage alone is 63 MB compressed (203 MB unpacked) and the final image is 61 MB (199 MB), so splitting the build into two stages saves only the `pip` that is removed. The 6 to 7 times difference comes from `python:3.12-slim` against `python:3.12`. I keep the two stages because they cost nothing and keep build tools out of the image, but the claim that "multi-stage made the backend small" would be wrong.
- **The stage split matters a lot for the frontend.** The Node build stage is 117 MB compressed (289 MB unpacked) and the final image, which only holds the compiled files and nginx, is 25 MB (56 MB).
- **Layer order pays off on every commit.** The dependencies are installed before the application code is copied, so changing a source file rebuilds only the last layers. That is the difference between 3 and 26 seconds for the backend, and nearly every commit changes only source files.
- **One cost of the real backend image.** Startup is about 0.35 seconds slower than the naive image (1.50 against 1.15 seconds in the last run, and the same direction in every run), and I did not find why. It is small next to the probes, which check every 2 to 5 seconds, but it is real. A build from nothing shows no consistent difference between the two (31 against 25 seconds in one run, 35 against 36 in the next), so I do not rank them.
- **The frontend starts faster** than serving the build with a Node development server, because nginx does not boot a runtime.

Limits of this measurement:

- Docker's `.Size` is the **compressed** size of the layers (with the containerd image store), which is what a pull transfers. The files inside add up to about three times as much once unpacked (199 MB for the backend), and that is what a node stores. The table gives both. My first version of this section called the compressed number "uncompressed", which was wrong, and I found it because python:3.12-slim alone is larger than the 61 MB that I had reported.
- Build times include the package downloads, so they vary with the network: across the runs of the script, the backend build from nothing took 26 to 35 seconds and the frontend 9 to 22 seconds. Only the rebuild after a code change, which does not download anything, is a stable comparison.
- The naive images are my own idea of a typical first Dockerfile, not a standard.
- Both Dockerfiles start with `# syntax=docker/dockerfile:1`, which makes every build contact Docker Hub for the build frontend, even when every layer is cached. During this measurement a failed DNS lookup broke one build for that reason, so the script retries and times only the attempt that works. Removing the line, or pinning the frontend by digest, would take that network dependency out of the builds. I did not change it.
- My first versions of the script had two bugs, which I fixed before using any number: Git Bash rewrote the `/health` argument into a Windows path, so the startup test polled a wrong address, and the same comment was added on every run, so the layer cache of the previous run answered the rebuild of the naive image (25 seconds became 2.5).

## How to repeat it

```bash
kubectl run loadgen ...        # any pod with python, for example the backend image
kubectl exec -i loadgen -- python - http://campusslot-backend:8000/api/rooms --threads 16 --seconds 30 < scripts/loadgen.py
```

Change one value, for example `--set backend.resources.limits.cpu=1000m`, redeploy with one replica and the autoscaler off, and run it again. The image measurements run with `scripts/image-metrics.sh` and need only Docker.
