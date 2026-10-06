# Runbooks

One page per alert, linked from the `runbook_url` annotation of the alert rule.

| Runbook | Alerts |
|---|---|
| [Error budget burn](error-budget-burn.md) | CampusSlotErrorBudgetFastBurn (critical), CampusSlotErrorBudgetSlowBurn (warning) |
| [Latency objective breached](latency.md) | CampusSlotLatencySLOBreach (warning) |
| [Backend pods unavailable](backend-not-ready.md) | CampusSlotBackendReplicasUnavailable (warning), CampusSlotBackendDown (critical) |
| [Database not ready](database-down.md) | CampusSlotDatabaseDown (critical) |
| [Autoscaler at its maximum](autoscaler-at-maximum.md) | CampusSlotAutoscalerAtMaximum (warning) |
| [Metrics missing](metrics-missing.md) | CampusSlotMetricsMissing (warning) |
