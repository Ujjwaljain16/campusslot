# Game day, 2026-10-21 09:54 UTC

Namespace `campusslot`, 1 node(s). Rollout: True. Database operator: False.
Load per scenario: 10 reads and 3 writes per second through the ingress.

| Scenario | Verdict | Failed reads | Longest gap | Writes lost | Recovery | Alert seen |
|---|---|---|---|---|---|---|
| `bad-release` | PASS | 44 of 1114 (3.95 %) | 0.5 s | 0 of 323 | 80 s | none |
| `slow-release` | PASS | 0 of 1091 (0.00 %) | 0.4 s | 0 of 328 | 78 s | none |

## A release that is ready but fails 30 percent of its requests

**Hypothesis.** The canary receives 10 percent of the traffic, its own error ratio breaches 2 percent, and the rollout aborts. About 3 percent of the requests fail until then (docs/engineering/canary-releases.md).

- PASS failed reads: 3.9 %, limit 5 %
- PASS acknowledged writes lost: 0, limit 0
- PASS time to recover: 80.2 s, limit 150 s

## A release that is ready but takes 400 ms for every request

**Hypothesis.** The canary's share of fast requests falls under 95 percent and the rollout aborts. Only the canary's share of the traffic (10 percent, then 50 percent if it got that far) is slow.

- PASS failed reads: 0.0 %, limit 1 %
- PASS slow answers: 9.3 %, limit 15 %
- PASS acknowledged writes lost: 0, limit 0
- PASS time to recover: 78.1 s, limit 150 s
