# ADR 0004: Collect logs with Grafana Alloy, not Promtail

Status: accepted

## Context

The dashboard needed logs next to the metrics. Promtail was the tool in most tutorials, but it has reached end of life.

## Options considered

- Promtail: well documented, but no longer maintained.
- Fluent Bit or Vector: good tools, but a second ecosystem to learn for a small project.
- Grafana Alloy: the supported successor, with the same Loki integration.

## Decision

Alloy as a DaemonSet that discovers the pods of the `campusslot` namespace and tails their logs through the Kubernetes API, writing to Loki in single binary mode.

## Consequences

- No host paths are mounted, which keeps the pod specification restricted.
- Only one namespace is collected, which keeps the volume small.
- Loki crashed on its first installation because the chart runs it with a read-only root file system and I had given it no volume. It now has a small PersistentVolumeClaim.

## What I would do in production

Object storage for Loki, retention per tenant, and log based alerts.
