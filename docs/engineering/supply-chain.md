# Supply chain: knowing where the images come from

## Why this exists

The pipeline scanned the images for known vulnerabilities, but nothing answered a different question: is the image that the cluster pulls really the one that this pipeline built from this commit? A scan describes what is inside an image. It does not say who made it. I added two things: signed records of where each image came from (and what is inside), and a check in the deploy job that installs only images with such a record. I also added Dependabot, so that outdated dependencies arrive as reviewed pull requests.

## What the pipeline does now

1. After the push, the build job resolves the digest of each image, because a tag can be moved and a digest cannot.
2. It generates an SBOM (a list of every package inside the image) in SPDX format with Syft.
3. It creates two signed attestations per image with GitHub: the build provenance (which repository, workflow, commit and runner produced the image) and the SBOM. The signing uses the identity of the workflow run, so there is no key to store or leak.
4. The deploy job runs `gh attestation verify` for both attestations of both images before `helm upgrade`. If one is missing or was made by another workflow, the job fails and nothing is installed.

## Evidence

[`docs/evidence/supply-chain.txt`](../evidence/supply-chain.txt) was produced from my laptop against the real registry:

| Check | Result |
|---|---|
| Image built by CI after the change, build provenance | verified, exit code 0 |
| The same image, SBOM | verified, exit code 0 |
| Image from before the change (no attestation) | rejected, exit code 1 |
| What the signed certificate says | signed by `ci-cd.yml` of this repository, on a GitHub-hosted runner, for the commit that I expected |

## What it costs

| | Without | With |
|---|---|---|
| Wall clock of a full run | 143 s | 202 s |
| Build, scan and push job | 102 s | 140 s |
| Verification in the deploy job | none | about 7 s per image |

This is one pair of runs with warm caches, so the real difference may be a little higher or lower. The cost is real: about a minute on every push to `main`. I accepted it because the check protects the step where an attack or a mistake is hardest to see afterwards. The cheaper variants are listed in [ADR 0012](../adr/0012-attest-images-and-verify-before-deploy.md).

## What I found while building it

The first full run failed in the deploy job with `HTTP 404`. The provenance check had passed, so the SBOM check was the problem. I listed the attestations stored for the digest through the API and found that the SBOM predicate type is `https://spdx.dev/Document/v2.3`, while my check asked for `https://spdx.dev/Spec/v2.3/`. I corrected the check and ran the pipeline again. The fix was a one-line change, and it would have blocked every deployment if I had merged the code without running it.

## Dependabot

[`.github/dependabot.yml`](../../.github/dependabot.yml) checks the Python and npm dependencies, the GitHub Actions and the Docker base images every week. Minor and patch updates are grouped to keep the number of pull requests small, and every update goes through the same required checks as my own changes.

## Limits

- The check runs in the pipeline, not in the cluster. Someone with `kubectl` access can still run an unverified image. An admission policy would close that gap.
- An attestation proves the origin. A compromised workflow would produce valid attestations for a bad image, so the workflow itself must be protected, which is what branch protection and required reviews are for.
- Attestations on a private repository need a paid GitHub plan. This repository is public.
