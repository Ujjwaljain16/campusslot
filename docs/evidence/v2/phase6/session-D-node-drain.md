# Game day, 2026-10-21 09:48 UTC

Namespace `campusslot`, 4 node(s). Rollout: False. Database operator: False.
Load per scenario: 10 reads and 3 writes per second through the ingress.

| Scenario | Verdict | Failed reads | Longest gap | Writes lost | Recovery | Alert seen |
|---|---|---|---|---|---|---|
| `node-drain` | PASS | 0 of 405 (0.00 %) | 0.3 s | 0 of 122 | 0 s | none |

## The node with most backend pods is drained

**Hypothesis.** The disruption budget keeps one backend pod, the others move to another node, and the traffic follows the ready pods.

- PASS failed reads: 0.0 %, limit 1 %
- PASS longest time without an answer: 0.3 s, limit 5 s
- PASS acknowledged writes lost: 0, limit 0
- PASS time to recover: 0.3 s, limit 180 s
