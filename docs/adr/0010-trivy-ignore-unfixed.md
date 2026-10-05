# ADR 0010: Gate on fixable HIGH and CRITICAL findings only

Status: accepted

## Context

A security gate that fails on things that nobody can fix blocks releases without making anything safer, and a gate that never fails is decoration.

## Options considered

- Fail on every finding of every severity.
- Fail on HIGH and CRITICAL findings, including those without a fix.
- Fail on HIGH and CRITICAL findings that have a fix available (`ignore-unfixed`).
- Report only, never fail.

## Decision

`severity: HIGH,CRITICAL`, `ignore-unfixed: true` and `exit-code: 1` for both images, before anything is pushed to the registry.

## Consequences

- Both images were clean on every run, so I never saw the gate fail, and I did not invent a failure for a screenshot.
- A clean result means that nothing fixable was known on that day. It does not prove that the images are safe.
- Findings without a fix still exist and are not shown by this configuration.

## What I would do in production

Also scan on a schedule, so that a new CVE in an old image is noticed without a new commit, and publish the SBOM so that affected images can be found quickly.
