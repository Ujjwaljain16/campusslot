# Service level objectives and alerts

## Why this exists

Before this change, the project had dashboards but no alerts. A dashboard needs a person to look at it. An alert needs a decision about what "broken" means, and that decision is a service level objective (SLO). I wrote two objectives, turned them into alert rules in the Helm chart, and gave every alert a runbook.

## The objectives

| Objective | Indicator (SLI) | Target | Window |
|---|---|---|---|
| Availability | Share of requests that do not fail with a 5xx status | 99.5 percent | 30 days |
| Latency | Share of requests that finish within 0.25 seconds | 95 percent | 10 minutes, rolling |

I count only 5xx responses as failures. A 409 conflict is the application working as designed, and a 422 or 404 is a client mistake. The probe endpoints (`/health`, `/ready`, `/metrics`) are excluded from the metrics, so they do not hide real errors behind healthy traffic. The threshold of 0.25 seconds is a bucket of the request duration histogram, which makes the SLI exact: a threshold between two buckets would be an interpolation.

## The error budget

An availability target of 99.5 percent means that 0.5 percent of requests may fail in 30 days. That is the **error budget**. It is a spending limit: while there is budget left, the team can ship changes and take risks, and when it is used up, reliability work comes first.

## How the alerts work

The error budget alerts use the **multi-window burn rate** method. The burn rate is how many times faster than allowed the budget is being spent.

| Alert | Burn rate | Windows | For | Severity | Meaning |
|---|---|---|---|---|---|
| `CampusSlotErrorBudgetFastBurn` | 14.4 (more than 7.2 percent errors) | 5 minutes and 1 hour | 2 minutes | critical | The 30 day budget would be gone in about two days |
| `CampusSlotErrorBudgetSlowBurn` | 6 (more than 3 percent errors) | 30 minutes and 6 hours | 15 minutes | warning | The budget would be gone in about five days |

Both windows must exceed the threshold. The short window makes the alert fast, and the long window stops a brief blip from paging anyone. A minimum traffic condition (more than 0.05 requests per second) stops one failed request on a quiet service from looking like a 100 percent error rate.

The other alerts describe the state of the system, not the user experience:

| Alert | Fires when | Runbook |
|---|---|---|
| `CampusSlotLatencySLOBreach` | Fewer than 95 percent of requests are fast, with real traffic, for 10 minutes | [latency](../runbooks/latency.md) |
| `CampusSlotBackendReplicasUnavailable` | A backend pod is running but not ready for 2 minutes | [backend not ready](../runbooks/backend-not-ready.md) |
| `CampusSlotBackendDown` | No backend pod is available | [backend not ready](../runbooks/backend-not-ready.md) |
| `CampusSlotDatabaseDown` | The PostgreSQL pod is not ready for 2 minutes | [database down](../runbooks/database-down.md) |
| `CampusSlotAutoscalerAtMaximum` | The autoscaler has been at its maximum for 10 minutes | [autoscaler](../runbooks/autoscaler-at-maximum.md) |
| `CampusSlotMetricsMissing` | Prometheus has no healthy backend target for 5 minutes | [metrics missing](../runbooks/metrics-missing.md) |

The last one matters because it watches the watchers: if metrics disappear, every other alert goes quiet, which looks exactly like a healthy system.

## Where it lives

- Rules: [`helm/campusslot/templates/prometheusrule.yaml`](../../helm/campusslot/templates/prometheusrule.yaml), enabled with `prometheusRule.enabled`, because it needs the Prometheus Operator CRDs.
- Thresholds come from the chart values, so changing the objective changes the alerts and nothing else.
- Runbooks: [`docs/runbooks`](../runbooks/README.md).

## Limits

- **There is no Alertmanager.** I disabled it to save memory on a small node, so alerts are visible on the Prometheus Alerts page and not delivered to a person. A production setup needs Alertmanager with a receiver such as e-mail, Slack or an on-call tool.
- **The indicator is measured inside the application.** It cannot see a failure that happens before a request reaches a pod, for example the ingress answering 503 because no backend pod is ready. Measuring at the ingress controller would close that gap and needs its metrics enabled. The database outage case is covered, because the backend answers it with a handled 503 (see [resilience](resilience.md)).
- **A 30 day window is long for a project that lives for hours.** The multi-window rules use windows of up to 6 hours, so they still work, but the error budget itself cannot be shown as consumed over 30 days.
- **The latency objective is rolling and short**, because a long window needs history that this cluster does not keep. Prometheus retains 6 hours here.
- **The objectives are my own choices**, not derived from user research. They are reasonable for a booking page, and a real service would agree on them with its users.
