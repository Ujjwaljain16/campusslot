# ADR 0020: Break things on purpose, as hypotheses, under load

Status: accepted (v2)

## Context

Each phase of v2 has its own drill, and each drill answers one question in isolation: does the canary abort a bad release, does the operator fail over, does the policy refuse the image. A system is not used in isolation. It is used under traffic, while something else may be going on, and what matters is what the users saw. A drill that is run once, by hand, with the result judged afterwards, is also easy to read kindly: whatever number comes out can be explained.

## Options considered

- Keep the separate drills and call them the resilience testing. Every part is proven and the combination is not.
- A chaos engineering platform (Chaos Mesh, Litmus). They inject many kinds of faults, and they are a large installation, which a laptop cluster does not have the memory for.
- One script that injects the failures that the phases already know how to inject, under steady load, with the limits that the earlier documents promised.

## Decision

`scripts/gameday.py` runs scenarios one after another. Every scenario is the same procedure, so that the results can be compared:

- **A steady state comes first.** It checks that every backend pod is ready, that the database cluster and the rollout are healthy and that requests are answered, and it refuses to break a system that is not healthy, because the result would not say what the failure did.
- **The hypothesis is written before the run**, in the code next to the failure (`SCENARIOS`), as numbers: the share of failed reads, the longest time without an answer, the share of slow answers, the acknowledged writes that may be lost, the time to recover, and the restarts of the backend. The numbers come from the method documents of the phases, so the game day tests the promises that those made.
- **Load runs the whole time**: reads and writes through the ingress at a fixed rate. The writes are remembered, and afterwards every acknowledged write is asked for again, so a loss cannot hide behind a green dashboard.
- **The verdict is computed, not judged.** Every number is compared with its limit and reported as PASS or FAIL with the value, and a scenario that did not run to its end is never a pass.
- **There are guard rails.** A scenario that makes more than half of the reads fail for 20 seconds is stopped (the database scenarios are exempt, because failing reads is what they expect), and the system is put back, and the next scenario waits for the steady state again.
- **A scenario that does not apply says so** (no operator, no Rollout, one node) and is reported as skipped, with the reason, instead of passing by doing nothing.

The same tool measures what tracing costs (`overhead`): the same closed loop load with tracing off, at a ratio of 0.1 and at 1, in a different order in every round, and it reports the noise of the repeated runs next to the difference, so a cost is only called a cost when it is larger than the noise.

## Consequences

- The promises of the earlier phases are tested together, under traffic, with a verdict, and a failed hypothesis is a finding with numbers, not a surprise.
- The hypotheses can be wrong, and then the document and the code change together. That is the point of writing them first.
- On a laptop cluster not every scenario can run: a node drain needs two nodes, the failover needs the operator, the canary scenarios need the Rollouts controller and Prometheus. The tool detects what is there and skips the rest.
- The failures are the ones that a script can cause from outside the cluster: a pod, a release, a node. It does not cover a network partition, a full disk or a clock that jumps.
- A game day is a lab. It does not say how the people on call would react, which is the part of a game day that matters most in a team.

## What I would do in production

Run it on a schedule against a staging environment that looks like production, with the people who are on call, with a written record of what they did and how long they needed, and with the hypotheses reviewed by someone who did not write the system.
