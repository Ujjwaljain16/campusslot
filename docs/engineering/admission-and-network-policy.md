# Admission policy and network policy

Status: **built, and the drill has run** on a kind cluster with Calico on a GitHub-hosted runner (20 October 2026, [run 39493683204](https://github.com/Ujjwaljain16/campusslot/actions/runs/39493683204)). Every prediction below held. The measured results are in the results section. The decision is in [ADR 0016](../adr/0016-admission-policy-and-default-deny-networking.md).

## What was built

| Part | File | What it does |
|---|---|---|
| Image rules, built into Kubernetes | `policies/admission/restrict-images.yaml` | In the `campusslot` namespace, only the project's registry and the postgres image are accepted, with a real tag |
| Provenance rule, Kyverno | `policies/kyverno/verify-image-attestations.yaml` | The image must have a build provenance attestation signed by this repository's workflow on `main` or `v2` |
| Default deny and an allow list | `helm/campusslot/templates/networkpolicy.yaml` | Six `NetworkPolicy` objects: deny all, DNS, frontend, backend, database, jobs |
| Installer | `scripts/install-kyverno.sh` | Kyverno with the admission controller only, to save memory |
| The drill | `scripts/policy-drill.sh` | Tries what must be refused and what must still work |

## How to run the drill

The route that was used, with no laptop: push the branch `drill/phase2` (`git push -f origin v2:refs/heads/drill/phase2`), and the job `phase2` of `.github/workflows/drills.yml` builds a kind cluster without a network plugin (`ci/kind-calico.yaml`), installs Calico, the ingress and Prometheus, and runs the steps below.

On a laptop: the network part needs a network plugin that enforces policy. On Minikube that means a Calico cluster, which uses more memory than the default network. Close heavy applications first.

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

Environment ([environment.txt](../evidence/v2/phase2/environment.txt)): a GitHub-hosted runner, 4 vCPU, 16 GB, one kind node with Kubernetes v1.35.0 and Calico v3.30.3, the images of commit `2ca20e4`.

| Check | Before the policies | After | Predicted |
|---|---|---|---|
| The backend reaches the database | open | open | as predicted |
| The frontend reaches the backend | open | open | as predicted |
| The frontend reaches the database | open | **blocked** | as predicted |
| The backend reaches the internet | open | **blocked** | as predicted |
| The database reaches the internet | open | **blocked** | as predicted |
| A pod in another namespace reaches the backend | open | **blocked** | as predicted |

The control matters as much as the result: **before** the policies, 2 of the 6 checks pass and the 4 "blocked" ones fail ([network-before.txt](../evidence/v2/phase2/network-before.txt)); **after**, 6 of 6 pass ([network-after.txt](../evidence/v2/phase2/network-after.txt)). So the drill can fail, and the policies are what changed it.

With the policies on, the application still works ([application-with-policies.txt](../evidence/v2/phase2/application-with-policies.txt)): all pods Ready, the rooms through the ingress `200`, a booking `201` and the same slot again `409`, and Prometheus scrapes 2 of 2 backend pods.

| Image check (namespace `campusslot`) | Result |
|---|---|
| An image from Docker Hub | refused by the built-in policy `campusslot-restrict-images`: "image not allowed in this namespace" |
| `campusslot-backend:latest` | refused ("the tag must not be latest"). With Kyverno on, Kyverno answers first: it finds no attestation for `:latest` |
| An image without a tag (`postgres`) | refused by the built-in policy |
| The image that runs now (`2ca20e4`) | **accepted**, with both policies on |
| The image of the last commit of `main` before the attestations existed (`6f22604`) | **refused by Kyverno**: "no matching signatures found" |

Transcripts: [admission.txt](../evidence/v2/phase2/admission.txt) (CEL policy alone) and [admission-with-kyverno.txt](../evidence/v2/phase2/admission-with-kyverno.txt) (both policies).

### What the known risks turned out to be

| Risk named before the run | Result |
|---|---|
| The CEL expressions might not be accepted | They were accepted at the first apply, with no type-checking warnings (`typeChecking: {}` in [vap-status.json](../evidence/v2/phase2/vap-status.json)) |
| The Kyverno policy was written from the documentation, and `ClusterPolicy` is marked deprecated | It was accepted by Kyverno 1.19.1 and enforced, and it accepts the attested image and refuses the old one with the signer identity pattern as written. No correction was needed. The deprecation is still real, and moving to `ImageValidatingPolicy` stays on the list |

### The first run proved half of it, and the other half for the wrong reason

The first run of this phase had a clean network result and a misleading admission result. The drill's test pod was a bare `kubectl run` pod, and the namespace enforces the **Pod Security `restricted`** profile. Pod Security refused every test pod before the image policies were asked: the three "refused" checks passed because of the wrong policy, and the check "the image that is running now is accepted" failed because the bare pod was not compliant. A pass for the wrong reason is worse than a failure.

The drill now builds a test pod that meets the profile (non-root, no privilege escalation, all capabilities dropped, the runtime default seccomp profile), and a refusal only counts when its message names one of this project's policies. The results above are from the second run, after that change. The first run's transcript shows the Pod Security message and is not kept as evidence.

## Limits that are already known

- The Kyverno policy is the part most likely to need a correction after the first run. It is written from the documentation of `type: SigstoreBundle`, and the keyless identity uses a regular expression, which needs a Kyverno release that enforces it (1.14 or later, and the chart pins 1.19.1).
- A `NetworkPolicy` on a plugin that does not enforce it is silently ignored. That is why the drill tests connections, and why a green `kubectl get networkpolicy` proves nothing.
- The policies apply to one namespace. A cluster-wide baseline is the production version.
