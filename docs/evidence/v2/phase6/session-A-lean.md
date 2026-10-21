# Game day, 2026-10-21 09:49 UTC

Namespace `campusslot`, 1 node(s). Rollout: False. Database operator: False.
Load per scenario: 10 reads and 3 writes per second through the ingress.

| Scenario | Verdict | Failed reads | Longest gap | Writes lost | Recovery | Alert seen |
|---|---|---|---|---|---|---|
| `backend-pod-kill` | PASS | 0 of 348 (0.00 %) | 0.3 s | 0 of 105 | 5 s | none |
| `database-pod-restart` | PASS | 19 of 384 (4.95 %) | 7.4 s | 0 of 110 | 8 s | none |

## One backend pod is deleted

**Hypothesis.** The pod stays in the service for 8 seconds while it stops (preStop), the other pod serves, and a new one starts. Measured before in docs/engineering/resilience.md: 0 failed of 600.

- PASS failed reads: 0.0 %, limit 0.5 %
- PASS longest time without an answer: 0.3 s, limit 3 s
- PASS acknowledged writes lost: 0, limit 0
- PASS time to recover: 4.7 s, limit 90 s
- PASS restarts of the backend: 0, limit 0

## The only database pod is deleted

**Hypothesis.** Reads and writes fail while the database is away, as handled 503 answers (a liveness probe that does not depend on the database keeps the backend from restarting). The data is on the volume, so no acknowledged write is lost.

- PASS longest time without an answer: 7.4 s, limit 90 s
- PASS acknowledged writes lost: 0, limit 0
- PASS time to recover: 8.2 s, limit 120 s
- PASS restarts of the backend: 0, limit 0
