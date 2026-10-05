# ADR 0011: Use one scanner for the infrastructure code and the manifests

Status: accepted

## Context

The pipeline scanned the container images and the dependencies, but not the Terraform or the Helm chart. Several tools cover this area, and they overlap heavily.

## Options considered

- Trivy for the images, Terraform and Kubernetes manifests, plus `kubeconform` for schema validation.
- Add `kube-linter` for pod policy, and `checkov` or `tfsec` for Terraform.
- Do nothing and rely on review.

## Decision

Trivy `config` for both Terraform and the Helm chart, because it is already in the pipeline for the images and uses the same ignore file format with written statements. `kubeconform` stays separate because it answers a different question, whether the manifests are valid Kubernetes, and not whether they are safe.

## Consequences

- One set of exceptions to maintain, each with a reason and, where it is a real to-do, an expiry date.
- Fewer false positives to triage than with three overlapping tools.
- Some checks that a dedicated tool such as `kube-linter` has are not present. I accept this for a project of this size.

## What I would do in production

Add an admission policy (Kyverno or Gatekeeper) so that the same rules are enforced at the cluster as well as in CI, and scan on a schedule so that a new rule is applied to old code.
