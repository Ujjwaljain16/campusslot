# Game day: several failures, under traffic, against written hypotheses

Status: **written and tested where it can be without a cluster (25 unit tests of the statistics, the verdicts, the load, the check for lost writes and the whole orchestration of a scenario against a fake service). The game day has not been run on a cluster yet.** The measured results are added next to the hypotheses below after the first run. The decision is in [ADR 0020](../adr/0020-failures-as-hypotheses-under-load.md).

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
| `node-drain` | The node with most backend pods is drained | at most 1 % | 5 s | | 0 | 180 s | The disruption budget keeps one pod, the others move, and the traffic follows the ready pods |

Common to all: the backend containers do not restart (where it is judged), the system returns to the steady state, and the acknowledged writes exist.

## Guard rails

- The steady state is checked first, and the scenario is skipped if it does not hold.
- A scenario that fails more than half of the reads for 20 seconds is stopped and the system is put back (not the database scenarios, where failing reads is the expected thing).
- After every scenario the release is reset (the faults off, the node uncordoned) and the next one waits for a healthy system. If the system does not come back in five minutes, the game day stops there.

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

Not measured yet.

## Limits that are already known

- The failures are the ones that a script can cause from outside: a pod, a release, a node. A network partition, a full disk and a clock that jumps are not covered.
- It does not test the people. The part of a game day that matters most in a team, how the people on call find and fix the problem, is not part of a script.
- The detection time of an alert is recorded, and it is not judged: the burn rate alerts wait 2 to 15 minutes on purpose, so that a short blip does not page anyone, and a scenario of one minute cannot fire them.
