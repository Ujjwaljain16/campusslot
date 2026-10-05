# ADR 0007: Retry the deployment steps instead of adding sleeps

Status: accepted

## Context

The kind deploy job failed four times, always because the ingress controller was ready later than the pods behind it (see [the DORA analysis](../engineering/dora-analysis.md)).

## Options considered

- A fixed `sleep` before the install: simple, slow on every run, and still a guess.
- Delete the validating webhook configuration: removes the check that protects the cluster from bad ingresses.
- Wait for the webhook endpoint: addresses the symptom that I saw first, but the Service address still refused connections afterwards.
- A bounded retry around the install, and a retry inside every smoke test request.

## Decision

A bounded retry of three attempts around `helm upgrade --install --atomic`, and a `fetch` helper in the smoke test that retries each request until it succeeds or gives up after about 80 seconds.

## Consequences

- `--atomic` removes a failed release completely, so a retry always starts clean.
- A real chart failure still fails the job after the attempts are used, so the retry does not hide it.
- After the fixes, 10 consecutive runs were green, after 4 failures in 16 runs before.

## What I would do in production

Readiness gates on the ingress itself, and a smoke test that follows the same path as a real client.
