# ADR 0002: Protect the booking rule in three layers

Status: accepted

## Context

The rule that two confirmed bookings never overlap in a room is the only thing the application must guarantee. A check in application code alone has a race: two requests can both see a free slot and both insert.

## Options considered

- Application check only: simple, but wrong under concurrency.
- Database constraint only: correct, but the error is a raw database error with no useful message.
- SERIALIZABLE transactions or advisory locks: correct, but they move complexity into every write path.
- Validation, an application check and an `EXCLUDE` constraint together.

## Decision

Three layers: Pydantic validation (HTTP 422), an application overlap check that names the blocking booking (HTTP 409), and a PostgreSQL `EXCLUDE USING gist` constraint over `tstzrange(start_time, end_time, '[)')` as the final safety net, which the API also turns into HTTP 409.

## Consequences

- Half open ranges make adjacent slots legal, and I tested both directions.
- SQLite cannot express the constraint, so a separate set of PostgreSQL tests proves it, including a concurrent race that creates exactly one booking.
- A metric `campusslot_booking_conflicts_total{layer}` shows which layer caught each conflict.

## What I would do in production

The same design. I would add an idempotency key to the create request, so a client retry cannot create a second booking by accident.
