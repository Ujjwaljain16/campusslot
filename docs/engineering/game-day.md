# Game day: several failures, under traffic, against written hypotheses

Status: **built, and the game day has run** in five sessions on kind clusters of GitHub-hosted runners (21 October 2026, [run 39579493390](https://github.com/Ujjwaljain16/campusslot/actions/runs/39579493390), after a first run that found three faults in the harness itself). Every scenario passed its hypothesis. The hypotheses that were too loose and the prediction that was wrong are listed in the results. The decision is in [ADR 0020](../adr/0020-failures-as-hypotheses-under-load.md).

## What it is

`scripts/gameday.py` breaks the system on purpose, one failure after another, with reads and writes running the whole time, and compares what happened with a hypothesis that was written before. The failures are the ones that the earlier phases built the defences for, so this is the test of the whole.

```bash
python scripts/gameday.py list
python scripts/gameday.py run --scenarios backend-pod-kill,database-pod-restart --out gameday.md
python scripts/gameday.py run --scenarios all --out gameday.md
python scripts/gameday.py overhead --rounds 3 --seconds 45
```

For each scenario: check the steady state, start the load (10 reads and 3 writes per second) and a watcher of the alerts, inject the failure 15 seconds in, wait until the system has recovered, stop the load, ask for every acknowledged write again, judge every number, put the system back, and wait for the steady state before the next scenario. A scenario that cannot apply (no operator, no Rollout, one node) is skipped with its reason.

## The hypotheses

These are the numbers that the earlier phases promised. They are in `SCENARIOS` in the code, and a number that is wrong is changed there and here together, after the run, with the reason.

| Scenario | What is broken | Failed reads | Longest gap | Slow | Writes lost | Recovery | Why this is expected |
|---|---|---|---|---|---|---|---|
| `backend-pod-kill` | One backend pod is deleted | at most 0.5 % | 3 s | | 0 | 90 s | The pod stays in the Service for 8 seconds while it stops, the other pod serves. Measured before: 0 failed of 600 ([resilience](resilience.md)) |
| `database-pod-restart` | The only database pod is deleted | not judged | 90 s | | 0 | 120 s | Reads and writes fail as handled 503 answers while it is away, the backend must not restart (its liveness probe does not depend on the database), the data is on the volume |
| `database-primary-failover` | The primary of the operator's cluster is killed with no grace period | not judged | 30 s | | 0 (5 when replication is asynchronous) | 180 s | The replica is promoted, the `-rw` Service follows ([database reliability](database-reliability.md)). Asynchronous replication may lose a few writes, and the loss is reported either way |
| `bad-release` | A release that is ready and fails 30 percent of its requests | at most 5 % | | | 0 | 150 s to the abort | The canary gets 10 percent of the traffic, so about 3 percent fail until the analysis aborts it ([canary releases](canary-releases.md)) |
| `slow-release` | A release that takes 400 ms per request | at most 1 % | | at most 15 % | 0 | 150 s to the abort | The canary's share of fast requests falls under 95 percent |
| `node-drain` | The node with most backend pods, **that does not also hold the database**, is drained | at most 1 % | 5 s | | 0 | 180 s | The disruption budget keeps one pod, the others move, and the traffic follows the ready pods |

Common to all: the backend containers do not restart (where it is judged), the system returns to the steady state, and the acknowledged writes exist.

## Guard rails

- The steady state is checked first, and the scenario is skipped if it does not hold.
- A scenario that fails more than half of the reads for 20 seconds is stopped and the system is put back (not the database scenarios, where failing reads is the expected thing).
- After every scenario the release is reset (the faults off, the node uncordoned) and the next one waits for a healthy system. If the system does not come back in five minutes, the game day stops there.

## How it was run

No laptop: the job `phase6` of `.github/workflows/drills.yml` runs the five sessions below in parallel on kind clusters of GitHub-hosted runners (push the branch `drill/phase6`). Session D has a control plane and three workers (`ci/kind-multinode.yaml`), and the others have one node. The section after this one is the same plan for a laptop.

## What a laptop can run

The scenarios need different parts, and the laptop cannot hold all of them at once. Three sessions, each with Chrome closed:

| Session | What is installed | Scenarios | Memory |
|---|---|---|---|
| A, lean | The application as a plain Deployment, one database pod | `backend-pod-kill`, `database-pod-restart` | the base |
| B, canary | Prometheus, the Rollouts controller, the application with `ROLLOUT=1` (and Tempo for the overhead measurement) | `bad-release`, `slow-release`, `overhead` | about 1 GB more |
| C, database | The operator (and the plugin and the object store for backups), the application with `postgres.operator.enabled` | `database-primary-failover` | about 1 GB more |

`node-drain` needs a cluster with two nodes. A kind cluster with a control plane and two workers fits better than a second Minikube node, and it was not tried.

## What tracing costs

The `overhead` command runs the same closed loop (8 connections, `GET /api/rooms`, 10 seconds of warm-up that is thrown away, 45 seconds measured) with tracing off, at a sample ratio of 0.1 and at 1, three rounds, in a different order each round. The first measurement of this project said that repeated runs of the same thing differed by up to 18 percent, so the report states the noise of the runs with tracing off, and only calls a difference a cost when it is larger than that.

Prediction: tracing at a ratio of 1 adds a few percent to the p95 (a span for the request and one for each statement, and a batch export on a background thread), which is smaller than the noise, so the honest result is probably "not distinguishable from the noise". If it turns out to be a cost of more than 10 percent, the ratio is lowered, and the number goes into the sizing document.

## Results

Environment: GitHub-hosted runners with 4 vCPU and 16 GB, Kubernetes v1.35.0 ([session A](../evidence/v2/phase6/environment-A.txt), [session D](../evidence/v2/phase6/environment-D.txt)), the images of commit `2ca20e4`, 10 reads and 3 writes per second through the ingress. Reports: [A](../evidence/v2/phase6/session-A-lean.md), [B](../evidence/v2/phase6/session-B-canary.md), [C async](../evidence/v2/phase6/session-C-database-async.md), [C sync](../evidence/v2/phase6/session-C-database-sync.md), [D](../evidence/v2/phase6/session-D-node-drain.md).

| Scenario | Failed reads (limit) | Longest gap (limit) | Slow (limit) | Writes lost (limit) | Recovery (limit) | Verdict |
|---|---|---|---|---|---|---|
| `backend-pod-kill` | 0 of 348 (0.5 %) | 0.3 s (3 s) | | 0 of 105 (0) | 4.7 s (90 s) | PASS |
| `database-pod-restart` | 19 of 384, 4.95 % (not judged) | 7.4 s (90 s) | | 0 of 110 (0) | 8.2 s (120 s) | PASS |
| `database-primary-failover`, asynchronous | 36 of 629, 5.7 % (not judged) | 17.5 s (30 s) | | 0 of 181 (5) | 32.7 s (180 s) | PASS |
| `database-primary-failover`, synchronous | 201 of 610, 33 % (not judged) | 20.2 s (30 s) | | 0 of 122 (0) | 30.8 s (180 s) | PASS |
| `bad-release` | 44 of 1114, 3.95 % (5 %) | 0.5 s | | 0 of 323 (0) | 80 s to the abort (150 s) | PASS |
| `slow-release` | 0 of 1091 (1 %) | 0.4 s | 9.3 % (15 %) | 0 of 328 (0) | 78 s to the abort (150 s) | PASS |
| `node-drain` | 0 of 405 (1 %) | 0.3 s (5 s) | | 0 of 122 (0) | see below (180 s) | PASS |

The backend containers did not restart in any scenario where it was judged. No alert fired in any scenario: the burn rate alerts wait 2 to 15 minutes on purpose, and a scenario of a minute or two cannot fire them (a limit that was known before the run).

What the numbers say about the earlier phases: a killed backend pod and a drained node cost the users nothing measurable (0 failed of about 350 and 400 reads); a bad or slow release is aborted by its own metrics in about 80 s, with 3.95 % of the reads failing for the bad one and none for the slow one; and no acknowledged write was lost in any scenario, including the failover of the database. The canary figures agree with the drill of phase 1 (aborted at 78.6 s then, 80 s now).

### Where the hypotheses or the predictions were wrong

1. **Tracing costs far more than predicted, and that is the one clear miss.** The prediction was a few percent, "probably not distinguishable from the noise". Two runs of the measurement, on different runners ([run 1](../evidence/v2/phase6/tracing-overhead-run1.txt), [run 2](../evidence/v2/phase6/tracing-overhead-run2.txt)), three rounds each in a changing order:

   | Tracing | p95, run 1 | p95, run 2 | Throughput, run 1 | Throughput, run 2 |
   |---|---|---|---|---|
   | off | 46.5 ms | 39.2 ms | 330 req/s | 394 req/s |
   | ratio 0.1 | 53.3 ms (+15 %) | 46.1 ms (+18 %) | 287 (-13 %) | 337 (-14 %) |
   | ratio 1 | 75.0 ms (+61 %) | 59.9 ms (+53 %) | 254 (-23 %) | 297 (-25 %) |

   The noise of the runs with tracing off was 5 and 2 percent, so these are costs and not noise, and the two runs agree on the relative cost although the absolute speed of the two runners differs. Two things limit what the numbers mean. The load is a closed loop of 8 connections that saturates a backend limited to 500m CPU, so the figure is the cost when the CPU is the limit; at the 10 requests per second of the scenarios the service is nowhere near that, and the cost is a few extra milliseconds of CPU per request. And the whole monitoring stack and Tempo run on the same single node. For the decision: **sampling at 0.1 still leaves +15 to +18 % of the +53 to +61 % at ratio 1, so a good part of the cost seems to be in creating the spans and not in exporting the sampled ones.** That is an inference from the shape of the numbers and was not profiled. Consequence: tracing stays off by default in the chart (as it is), a production use should start at a low ratio and measure its own p95, and the instrumentation (the span of every SQL statement is the likely candidate) is the place to look if the cost matters. The cost was not added to the sizing document.
2. **The hypotheses for the single database pod were far too loose.** The limits were 90 s for the gap and 120 s for the recovery, and the measured values are 7.4 s and 8.2 s. A limit that is ten times the result judges nothing. The numbers were written before any run, from the worst case of a volume that has to be reattached, and a kind cluster with local volumes is the best case. They are left as they are, because on a network volume they may be right, and this document says that the pass is not a close one.
3. **Failed reads during a database failover vary a lot for the same outage.** The asynchronous failover failed 36 of 629 reads (5.7 %) in the run above and 217 of 633 (34 %) in the first run ([first run](../evidence/v2/phase6/first-run-C-database-async.md)), with a longest gap of 17.5 s and 21.8 s. The synchronous failover failed 33 %. The gap is similar and the count is not, and this experiment cannot say why (the share of requests that hang until a timeout and the share that are refused at once is not recorded). The hypothesis does not judge the number, and this document reports the range, 6 to 34 %.
4. **Asynchronous and synchronous replication are again not told apart.** Both lost nothing (0 of 181 and 0 of 122). The claim "synchronous replication prevents the loss" is still the design of the setting and not a result of these runs, for the reason given in [database reliability](database-reliability.md).
5. **The node drain is measured after the drain has returned.** The injection (`kubectl drain`) waits until the node is empty, which took about 10 s here (injected at +15 s, back at +25 s), and the "recovery" of 0.3 s is counted from the end of the command. The users saw nothing during those 10 s (0 failed reads), which is the result; the recovery figure alone would understate the work. The drain chose a worker that held a backend pod and no database pod, evicted that pod, and the replacement started on another worker.

### What the first run of the game day found about the game day

The first run passed, and three of its numbers were wrong because of faults in the harness:

1. **`slow-release` never ran.** After `bad-release` the harness set the release back and stopped sending traffic. The rollout that undoes the fault is itself a canary, and a canary with no traffic has no numbers, so its analysis was "inconclusive" for ever (the known limit of the canary, in [canary releases](canary-releases.md)) and the system never returned to the steady state. The harness now sends a few requests per second while it puts the system back.
2. **A recovery of 0.1 s for the database pod was false.** A pod that has been deleted stays in the list, and stays Ready, until it has stopped, so "the database is back" was true before it had gone. The check now needs a different pod from the one that was deleted.
3. **The second database run measured nothing.** It used the same booking slots as the first, so every write was refused as a conflict and only one was acknowledged (0 of 1 lost is not 0 of 120). The run now takes its first slot as an option, and the second run uses another range.

The reports of the first run are not kept as evidence, apart from the first asynchronous failover, which was valid and is cited above.

## Limits that are already known

- The failures are the ones that a script can cause from outside: a pod, a release, a node. A network partition, a full disk and a clock that jumps are not covered.
- Every cluster is a kind cluster on a shared runner: a node is a container, the volumes are local, and a drain is gentle compared with a lost machine. The results show that the defences of the earlier phases work there, and not how long a real node loss takes.
- It does not test the people. The part of a game day that matters most in a team, how the people on call find and fix the problem, is not part of a script.
- The detection time of an alert is recorded, and it is not judged: the burn rate alerts wait 2 to 15 minutes on purpose, so that a short blip does not page anyone, and a scenario of one minute cannot fire them.
