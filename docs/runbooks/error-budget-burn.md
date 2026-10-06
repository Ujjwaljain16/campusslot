# Runbook: Error budget burn

**Alerts:** CampusSlotErrorBudgetFastBurn (critical), CampusSlotErrorBudgetSlowBurn (warning)

## What it means

A share of requests that is too large is failing with a 5xx status. The availability objective allows 0.5 percent over 30 days. The fast alert means the budget would be gone in about two days, the slow alert in about five.

## Impact

Users see errors when they book or list rooms. Conflicts (409) and invalid requests (4xx) do not count, only server errors.

## Diagnose

1. `kubectl get pods -n campusslot`
2. `kubectl logs -n campusslot -l app.kubernetes.io/component=backend --tail=50`
3. In Grafana, open the dashboard "CampusSlot overview" and look at the 5xx panel and at the request rate by route to see which route fails.
4. `kubectl get events -n campusslot --sort-by=.lastTimestamp | tail -15`

## Mitigate

- If a deployment started a few minutes before the alert, roll it back: revert the commit in gitops/values.yaml, or run `helm rollback`.
- If the logs show database errors, follow the database runbook.
- If one route fails and the others are fine, look at the recent change to that route.

## Verify that it is fixed

The 5xx panel is back to zero and the alert resolves after the short window has recovered.
