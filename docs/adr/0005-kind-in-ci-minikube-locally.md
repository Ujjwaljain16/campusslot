# ADR 0005: Deploy to kind in CI and to Minikube on the laptop

Status: accepted

## Context

A GitHub hosted runner cannot reach a cluster on my laptop. The pipeline should still prove that the chart installs and that the application works through the ingress.

## Options considered

- A self-hosted runner on the laptop: reaches the cluster, but a self-hosted runner on a public repository is a real security risk.
- Deploy to EKS from CI: realistic, but it costs money for every run.
- A throw-away kind cluster inside the runner: free, and it uses the same chart and the same images.

## Decision

The pipeline installs the chart into a kind cluster and runs a smoke test through the ingress. The persistent Minikube cluster is updated with `scripts/deploy-local.sh <sha>`, or by Argo CD.

## Consequences

- CI proves the chart and the images, and the Minikube cluster shows the long lived behaviour such as autoscaling and monitoring.
- Most of the pipeline failures in [the DORA analysis](../engineering/dora-analysis.md) came from this job racing the ingress controller.

## What I would do in production

Deploy to a real staging cluster from CI, with an environment approval before production.
