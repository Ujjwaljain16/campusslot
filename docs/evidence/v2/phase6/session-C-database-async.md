# Game day, 2026-10-21 09:49 UTC

Namespace `campusslot`, 1 node(s). Rollout: False. Database operator: True (synchronous: False).
Load per scenario: 10 reads and 3 writes per second through the ingress.

| Scenario | Verdict | Failed reads | Longest gap | Writes lost | Recovery | Alert seen |
|---|---|---|---|---|---|---|
| `database-primary-failover` | PASS | 36 of 629 (5.72 %) | 17.5 s | 0 of 181 | 33 s | none |

## The primary database pod is killed with no grace period

**Hypothesis.** The operator promotes the replica and the -rw Service follows. With asynchronous replication, the last few writes can be lost, and a loss is a finding. Synchronous replication must lose none.

- PASS longest time without an answer: 17.5 s, limit 30 s
- PASS acknowledged writes lost: 0, limit 5
- PASS time to recover: 32.7 s, limit 180 s
- PASS restarts of the backend: 0, limit 0
