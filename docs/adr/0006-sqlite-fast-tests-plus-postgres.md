# ADR 0006: Fast SQLite tests plus a smaller set of real PostgreSQL tests

Status: accepted

## Context

Tests that need a database server are slower and harder to run, but SQLite cannot reproduce the PostgreSQL features that the design depends on.

## Options considered

- PostgreSQL for every test.
- SQLite for every test.
- SQLite for most tests and a marked set of PostgreSQL tests.

## Decision

46 tests run on in-memory SQLite through a dependency override, and 4 tests marked `postgres` run only when `POSTGRES_TEST_URL` is set, in a separate CI job with a service container. A custom `UTCDateTime` type makes both databases behave the same for time zones.

## Consequences

- The default run takes about a second and runs anywhere.
- The constraint, the migrations and the concurrent race are proven on the real database.
- The two suites must not drift apart, so the PostgreSQL tests cover only what SQLite cannot.

## What I would do in production

The same split, and PostgreSQL started with Testcontainers so that no manual setup is needed.
