# ADR 0016: Enforce what may run, and what may talk, at the cluster

Status: accepted (v2)

## Context

In v1 the pipeline scans and attests every image, and the deploy job verifies the attestations before it installs. That check lives in CI. Nothing in the **cluster** stops someone from running `kubectl run` with any image, from a laptop-built image with the right name, or from an old image that was never attested. Inside the namespace, every pod can reach every other pod and the whole internet, so one compromised pod can reach the database.

## Options considered

For what may run:

- Rely on the pipeline check. It does not cover a person with `kubectl`.
- Kyverno only, for everything. It can do all of it, but it is a controller to run, and a simple rule such as "only my registry, with a real tag" does not need one.
- The built-in `ValidatingAdmissionPolicy` for the simple rules, and Kyverno only for the one rule that needs to talk to the registry (the attestation check).

For what may talk:

- Nothing (v1). Simple, and open.
- A service mesh with mutual TLS and authorization policies. Strong, and far more than this project needs.
- `NetworkPolicy`: default deny, and an allow list written from what the application really calls.

## Decision

- **Images:** `policies/admission/restrict-images.yaml` is a built-in `ValidatingAdmissionPolicy` for the `campusslot` namespace. Only `ghcr.io/ujjwaljain16/campusslot-*` and `postgres` are accepted, and a tag is required that is not `latest`. It costs no memory, because the API server evaluates it.
- **Provenance:** `policies/kyverno/verify-image-attestations.yaml` makes Kyverno verify the build provenance attestation of every project image against the identity of this repository's workflow (keyless, a Sigstore bundle). It is the cluster side of the check that CI already runs with `gh attestation verify`. Only the admission controller is installed.
- **Network:** `helm/campusslot/templates/networkpolicy.yaml` (`networkPolicy.enabled`): deny all, allow DNS, then exactly: ingress controller to frontend and backend, frontend to backend, Prometheus to backend, backend to database, migration and backup jobs to database. The database and the frontend call nothing else.

## Consequences

- A pod with another image, an untagged or `latest` image, or an image that was not built and attested by this pipeline is refused at admission, so the guarantee holds for a person as well as for CI.
- The network policies only work where the network plugin enforces them (Calico or Cilium). On a plugin that does not, they are accepted and silently ignored, which is why the drill tests the connections, and does not trust the objects. They are off by default so that the CI cluster (kind) and a default Minikube stay what they were.
- Two more places can refuse a deployment. Both name the rule in the error message, so a refusal by a policy can be told from a failure of the application.
- The Kyverno policy is written from the documentation of the current Sigstore bundle verification, and Kyverno marks `ClusterPolicy` as deprecated in favour of `ImageValidatingPolicy`. If the drill shows that the newer type is the better target, this file is moved to it.

## What I would do in production

Run the policies in audit mode first and read what they would have refused, put the rules for all namespaces in a cluster-wide baseline, verify the SBOM attestation as well as the provenance, and enforce the network policy on egress to the Kubernetes API and the DNS service by label instead of by namespace name.
