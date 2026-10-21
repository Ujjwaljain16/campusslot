# Game day, 2026-10-21 09:32 UTC

Namespace `campusslot`, 1 node(s). Rollout: False. Database operator: True (synchronous: False).
Load per scenario: 10 reads and 3 writes per second through the ingress.

| Scenario | Verdict | Failed reads | Longest gap | Writes lost | Recovery | Alert seen |
|---|---|---|---|---|---|---|
| `database-primary-failover` | PASS | 217 of 633 (34.28 %) | 21.8 s | 0 of 125 | 33 s | none |

## The primary database pod is killed with no grace period

**Hypothesis.** The operator promotes the replica and the -rw Service follows. With asynchronous replication, the last few writes can be lost, and a loss is a finding. Synchronous replication must lose none.

- PASS longest time without an answer: 21.8 s, limit 30 s
- PASS acknowledged writes lost: 0, limit 5
- PASS time to recover: 33.1 s, limit 180 s
- PASS restarts of the backend: 0, limit 0
