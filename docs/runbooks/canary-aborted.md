# Runbook: A canary release was aborted

**Signal:** the Rollout phase is `Degraded`, with the message `RolloutAborted ... Metric "error-ratio" assessed Failed` (or `fast-ratio`). There is no alert for it yet, because the Argo Rollouts metrics are not scraped in the default setup, so it is found with `kubectl`.

## What it means

The new version got a small share of the traffic, and the analysis of its own metrics (error ratio over 2 percent, or fewer than 95 percent of requests within 0.25 seconds) was bad for too many readings. The rollout stopped and all the traffic went back to the stable version. **Users are not affected now.** The new version is still running, with the weight set to 0, so that it can be inspected.

## Diagnose

1. `kubectl get rollout campusslot-backend -n campusslot` (phase and message)
2. `kubectl get analysisrun -n campusslot` and `kubectl describe analysisrun <name> -n campusslot` (which metric failed, the readings, and when)
3. The logs of the canary pods: `kubectl logs -n campusslot -l app.kubernetes.io/component=backend --tail=100` (look at the pods whose name has the canary hash)
4. What changed in the release? `helm get values campusslot -n campusslot` against the previous revision with `helm history`.

## Mitigate

- The cause is a defect in the new version: fix it and release again. A new release resets the rollout.
- To go back to the previous configuration with Helm: `helm rollback campusslot <revision> -n campusslot`.
- A false alarm (for example a quiet service whose few requests gave a noisy reading): check the request rate in Prometheus, and consider a longer `rollout.analysis.initialDelay` or a higher `failureLimit`. Do not promote by hand without a reason, and write the reason down.
- Nothing is being judged because there is no traffic (the rollout stays Paused with an inconclusive analysis): send traffic through the ingress, for example `python scripts/probe.py http://localhost:8080/api/rooms --seconds 120`.

## Verify that it is fixed

`kubectl get rollout campusslot-backend -n campusslot` shows `Healthy`, and the error ratio of the stable pods is back below the objective ([SLO](../engineering/slo.md)).

## Prevent

The drill that exercises this is [canary releases](../engineering/canary-releases.md): `scripts/canary-drill.sh bad`.
