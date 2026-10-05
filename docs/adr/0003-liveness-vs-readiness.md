# ADR 0003: Separate liveness from readiness

Status: accepted

## Context

A single health endpoint that checks the database makes every pod restart during a database outage, which turns a short outage into a longer one. A single endpoint that ignores the database sends traffic to pods that cannot serve it.

## Options considered

- One `/health` endpoint for everything.
- Liveness without a dependency check, readiness with one.

## Decision

`/health` never touches the database and is used for the startup and liveness probes. `/ready` checks the database and that the schema has been migrated, and only the readiness probe uses it.

## Consequences

- A database outage removes pods from the Service without restarting them. Troubleshooting lab 4 shows the pod running and not ready, and the same wrong database address in lab 3 shows the opposite behaviour when the process exits.
- Traffic cannot reach an empty database before the migration Job has finished.

## What I would do in production

The same split, plus a `preStop` delay so that in-flight requests finish during rollouts.
