# Right-sizing: CPU and memory from measurements

## Why this exists

Every container in the chart has a CPU and memory request (what the scheduler reserves) and a limit (the most it may use). I had written them as round numbers. They matter more than they look, because the autoscaler measures CPU as a percentage of the request. A request that is too low makes a quiet service look overloaded and the autoscaler adds pods that nothing needs. I measured what real traffic costs and set the values from that.

## Method

[`docs/evidence/sizing-usage.txt`](../evidence/sizing-usage.txt) was produced with one backend replica, 5 thousand bookings in the database (a few years of campus use), and a mix of requests: half room lists, the rest day views and one statistics call in ten, sent at a fixed rate by [`scripts/loadgen.py`](../../scripts/loadgen.py) from a pod in the cluster. The frontend received the same number of requests per second. CPU and memory come from Prometheus (cAdvisor), as the median and the 95th percentile of 5 second samples during each run.

## What traffic costs

| Level | Backend CPU (median, p95) | Backend memory | Frontend CPU, memory | PostgreSQL CPU, memory |
|---|---|---|---|---|
| Idle | 4 m, 5 m | 67 MiB | 0 m, 9 MiB | 7 m (p95 30 m), 30 MiB after a restart |
| 10 requests per second | 39 m, 51 m | 69 MiB | 2 m, 9 MiB | 21 m (p95 29 m), not measured clean |
| 50 requests per second | 203 m, 264 m | 70 MiB | 5 m, 9 MiB | 111 m (p95 144 m), 32 MiB |
| 150 requests per second | 493 m, 579 m | 71 MiB | 12 m, 9 MiB | 244 m (p95 260 m), not measured clean |

The backend costs 3 to 4 millicores of CPU per request per second. Its memory does not depend on traffic. 10 requests per second is already about 860 thousand requests a day, far more than a campus booking system receives.

**A trap I fell into:** my first reading of PostgreSQL said 137 to 140 MiB at every level (the cells marked "not measured clean" above are from that run), which was above its request and looked like a problem. That was page cache from loading 200 thousand rows earlier. After restarting the pod it used 30 to 32 MiB ([`sizing-postgres.txt`](../evidence/sizing-postgres.txt)). Memory measured after a bulk load describes the load and not the service. Measure from a clean start.

## The rule I used

- **CPU request:** what the container uses at the busiest level I expect, taken at the 95th percentile. It is the share that the scheduler guarantees, and the base of the autoscaler's percentage.
- **CPU limit:** the point where more CPU stops helping. CPU can be throttled without harm, so the limit may be generous. For the backend that point was measured in [performance](performance.md): about one core.
- **Memory request:** the highest measured use plus about a third.
- **Memory limit:** several times the use. Memory cannot be taken back, so a container above its limit is killed, and an OOM kill costs far more than a few unused megabytes.

## The values

| Container | Request before | Request now | Limit before | Limit now | Basis |
|---|---|---|---|---|---|
| Backend | 100m, 128 Mi | **250m, 96 Mi** | 500m, 256 Mi | **1000m**, 256 Mi | p95 264m and 70 MiB at 50 requests per second. The limit comes from the load test |
| Frontend | 25m, 32 Mi | **10m, 16 Mi** | 200m, 128 Mi | unchanged | 14m and 9 MiB at 150 requests per second |
| PostgreSQL | 100m, 128 Mi | **150m, 64 Mi** | 500m, 256 Mi | unchanged | p95 144m and 32 MiB at 50 requests per second, with room for the cache to grow |

The memory limits stay where they were on purpose: the use is far below them, and lowering them would save nothing while adding the risk of a kill. The production profile ([`values-prod.yaml`](../../helm/campusslot/values-prod.yaml)) already asks for a 250m backend request, which agrees with the measurement, so I left it alone.

The autoscaler target changed from 50 to **70 percent** of the request, so that it now means 175m per pod, about 40 requests per second per pod.

## What changed, measured

**Same traffic, different number of pods.** I sent 60 requests per second for 4 minutes against the old and the new sizing, both with the 1000m limit and the autoscaler allowed to run 2 to 5 pods ([`hpa-sizing.txt`](../evidence/hpa-sizing.txt)):

| | Old (100m request, scale at 50%) | New (250m request, scale at 70%) |
|---|---|---|
| Pods at the end | **5** (reached 90 seconds after the load began) | **2** |
| CPU reserved by requests | 500m | 500m |
| Memory reserved by requests | 640 MiB | 192 MiB |
| Latency, median and p95 | 9.8 ms, 29.6 ms | 7.8 ms, 23.7 ms |
| Failed requests | 0 of 14400 | 0 of 14400 |

With the old request, 60 requests per second looked like 111 to 154 percent utilization and filled the maximum of 5 pods. With the new one, the same load was 50 percent and two pods were enough. The new sizing reserved the same CPU, a third of the memory, and was slightly faster. One detail: for the first 45 seconds of the new run the autoscaler *reported* that it wanted 5 pods, while freshly started pods had no metrics yet, and it never acted on it.

**A real traffic spike.** With the new defaults, 150 requests per second for 150 seconds moved the autoscaler from 2 to 3 pods when the average reached 102 percent of the request, with 22 504 requests, 0 errors, a p95 of 31 ms, no restarts and no OOM kills ([`sizing-verification.txt`](../evidence/sizing-verification.txt)).

**Rollouts still lose nothing.** 4 rollouts (2 backend, 2 frontend) under the new settings lost 0 of 2400 requests ([`rollout-after-sizing.txt`](../evidence/rollout-after-sizing.txt)).

## What it costs

Right-sizing did not shrink everything. It moved the numbers to where the measurements are:

| Reserved by requests | Before | After |
|---|---|---|
| Default deployment (2 backend, 2 frontend, 1 database): CPU | 350m | 670m (+91 percent) |
| Default deployment: memory | 448 Mi | 288 Mi (-36 percent) |
| At the autoscaler maximum (5 backends): CPU, memory | 650m, 832 Mi | 1420m, 576 Mi |

The CPU request went up because the old 100m was an underestimate. That is also the reason that I did not simply shrink everything: a request that is too low is as wrong as one that is too high, and it hides in the autoscaler's behaviour.

On a small node, this matters. The demo EKS node (a `t3.small`, 2 vCPU) would hold the default deployment, but five backend pods at 250m plus the system pods would be close to the limit. That is arithmetic, not a measurement, because I did not run this sizing on EKS. The production profile has more nodes for that reason.

## Limits of this work

- One node, one traffic pattern (mixed reads, no writes during the measurement) and a few minutes per level. A real campus has daily and weekly cycles that I did not simulate.
- Memory was measured after a warm-up and not over days. A slow leak would not show.
- The autoscaler comparison is one run per configuration.
- A vertical autoscaler could keep the requests current. I did not try it, because for a service this small, rechecking the numbers when traffic changes is enough.

## How to repeat it

```bash
kubectl run loadgen ...        # a pod with python
kubectl exec -i loadgen -- python - "<url>,<url>" --threads 8 --rate 50 --seconds 60 < scripts/loadgen.py
# then read the CPU and memory of each container from Prometheus (container_cpu_usage_seconds_total,
# container_memory_working_set_bytes), after a restart of the pod so that the cache is clean
```
