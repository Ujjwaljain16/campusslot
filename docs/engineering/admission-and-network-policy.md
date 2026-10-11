# Admission policy and network policy

Status: **written and checked in CI (the manifests render and parse). Not run on a cluster yet.** The measured results are added next to the predictions below after the first run. The decision is in [ADR 0016](../adr/0016-admission-policy-and-default-deny-networking.md).

## What was built

| Part | File | What it does |
|---|---|---|
| Image rules, built into Kubernetes | `policies/admission/restrict-images.yaml` | In the `campusslot` namespace, only the project's registry and the postgres image are accepted, with a real tag |
| Provenance rule, Kyverno | `policies/kyverno/verify-image-attestations.yaml` | The image must have a build provenance attestation signed by this repository's workflow on `main` or `v2` |
| Default deny and an allow list | `helm/campusslot/templates/networkpolicy.yaml` | Six `NetworkPolicy` objects: deny all, DNS, frontend, backend, database, jobs |
| Installer | `scripts/install-kyverno.sh` | Kyverno with the admission controller only, to save memory |
| The drill | `scripts/policy-drill.sh` | Tries what must be refused and what must still work |

## How to run the drill

The network part needs a network plugin that enforces policy. On Minikube that means a Calico cluster, which uses more memory than the default network. Close heavy applications first.

```bash
minikube start -p campusslot --memory=3500 --cpus=3 --cni=calico
# ... ingress, the Prometheus stack, the application (scripts/deploy-local.sh <sha>) as for the canary drill
scripts/policy-drill.sh network                  # the control: nothing is enforced yet
helm upgrade campusslot helm/campusslot -n campusslot --reuse-values --set networkPolicy.enabled=true
scripts/policy-drill.sh network                  # the same checks, now with the policies

kubectl apply -f policies/admission/restrict-images.yaml
scripts/policy-drill.sh admission
scripts/install-kyverno.sh
kubectl apply -f policies/kyverno/verify-image-attestations.yaml
BAD_ATTEST=ghcr.io/ujjwaljain16/campusslot-backend:<sha-from-before-the-attestations> scripts/policy-drill.sh admission
```

Every admission request in the drill is a server side dry run (`kubectl run --dry-run=server`), so no pod is created and nothing is pulled. The connection checks use a plain TCP connect, so "blocked" cannot be confused with "the server answered something that is not HTTP".

## Predictions, written before the first run

| Check | Before the policies | After |
|---|---|---|
| The backend reaches the database | open | open |
| The frontend reaches the backend | open | open |
| The frontend reaches the database | open | **blocked** |
| The backend reaches the internet | open | **blocked** |
| The database reaches the internet | open | **blocked** |
| A pod in another namespace reaches the backend | open | **blocked** |
| An image from Docker Hub in the namespace | accepted | **refused** (built-in policy) |
| `campusslot-backend:latest`, or an image without a tag | accepted | **refused** (built-in policy) |
| The image that is running now | accepted | accepted |
| An image of the project without a build attestation | accepted | **refused** (Kyverno) |

The application itself must keep working with the policies on: the readiness probe (the database), a booking through the ingress (201 and 409), and the Prometheus targets (the backend stays scraped).

## Results

Not measured yet.

## Limits that are already known

- The Kyverno policy is the part most likely to need a correction after the first run. It is written from the documentation of `type: SigstoreBundle`, and the keyless identity uses a regular expression, which needs a Kyverno release that enforces it (1.14 or later, and the chart pins 1.19.1).
- A `NetworkPolicy` on a plugin that does not enforce it is silently ignored. That is why the drill tests connections, and why a green `kubectl get networkpolicy` proves nothing.
- The policies apply to one namespace. A cluster-wide baseline is the production version.
