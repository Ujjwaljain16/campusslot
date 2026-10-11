# ADR 0015: Judge canary releases by their own metrics

Status: accepted (v2)

## Context

In v1 a bad release is caught by the Kubernetes probes. `helm upgrade --atomic` rolled a release back by itself when the new pod never became ready ([bad release drill](../engineering/bad-release-drill.md)). That only covers a release that is **broken**. A release that starts, passes every probe and then fails a share of its requests, or answers slowly, is **ready but bad**. Kubernetes sees a healthy pod, `--atomic` sees a finished upgrade, and every user of the new pods meets the fault until someone notices an alert.

## Options considered

- Keep `--atomic` and rely on the burn rate alerts. The alerts work, but they fire minutes after the whole fleet already runs the bad version, and a person has to roll back.
- Blue/green. A fast switch back, but the whole traffic moves at once, so the whole user base sees the fault before anything judges it.
- Argo Rollouts with a canary: a small share of the traffic goes to the new version first, and an analysis decides whether to go on.
- Flagger. The same idea, and it works with an Argo CD setup too, but it is a second controller beside Argo CD with its own custom resources, and Argo Rollouts shares the Argo CD health model and its tooling.
- A service mesh for the traffic split. It gives header based and exact routing, but it is a large dependency for a lesson that the ingress controller already teaches.

## Decision

The backend can run as an **Argo Rollout** (`rollout.enabled`) with a canary strategy. The ingress controller splits the traffic by weight (10 percent, then 50 percent, then everything), and an **AnalysisTemplate** reads, from Prometheus, the error ratio and the share of fast requests **of the canary pods only**. The definitions are the same as the availability and latency SLIs that the alerts already use, so one definition of "healthy" serves the dashboard, the alerts and the release. A bad reading aborts the rollout by itself, and all the traffic goes back to the stable version.

The Deployment stays the default (`rollout.enabled: false`), because the CI deploy job and the GitOps path test it, and the Rollout needs a controller that a plain cluster does not have.

To test this without shipping a faulty version of the code, the backend has a drill switch: `FAULT_ERROR_RATE` and `FAULT_LATENCY_MS` make a share of the API requests fail or slow down while the probes keep answering. The switch is ignored when `APP_ENV` is `production`, and it is changed through the ConfigMap, so a drill is an ordinary release of the same image.

## Consequences

- A release that is ready but bad is exposed to a small, known share of the users instead of all of them, and the abort needs no person.
- Helm cannot wait for a Rollout: `helm upgrade --atomic` returns when the objects are applied, and the rollout continues in the background. The release verdict moves from Helm to the Rollout (and to Argo CD, which understands a Rollout natively).
- The analysis needs traffic. With no requests there is no number, and a missing number counts as inconclusive, so the rollout waits and does not promote. That is the safe default, and a quiet staging cluster needs a load generator.
- The analysis has a delay (the scrape interval, the first reading after 45 seconds, and a limit of bad readings), so the time to abort is a trade-off between speed and false alarms. The drill measures it.
- One more controller to run, and the alerts for replicas that are unavailable are written against pods instead of the Deployment while the Rollout is on.

## What I would do in production

Analyse more than two metrics (for example the booking conflict ratio, which is a business signal), use longer steps at a low weight during busy hours, send a notification when a rollout aborts, route a test user to the canary by header before the weight starts, and let Argo CD drive the rollout so that the promotion and the analysis live in Git.
