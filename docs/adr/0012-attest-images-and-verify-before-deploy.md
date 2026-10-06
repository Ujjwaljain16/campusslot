# ADR 0012: Attest every image and verify it before the deploy

Status: accepted

## Context

The pipeline scans the images and pushes them with the commit SHA, but nothing proves afterwards that an image in the registry came from this pipeline and from that commit. Anyone with write access to the registry could replace a tag, and the deploy job would install it without noticing.

## Options considered

- Do nothing and rely on registry permissions.
- Sign the images with cosign and a long-lived key.
- Sign with cosign keyless, using the identity of the workflow run.
- Use GitHub artifact attestations, which are signed with the same workflow identity and stored by GitHub.

## Decision

GitHub artifact attestations (`actions/attest-build-provenance` and `actions/attest-sbom`) for both images, plus an SBOM in SPDX format from Syft. The deploy job runs `gh attestation verify` for each image and refuses to install anything without a valid attestation made by this repository's workflow. The attestations are bound to the image digest and no key is stored anywhere.

## Consequences

- Measured cost: one pair of runs on the same code, 143 seconds without and 202 seconds with attestations (about 59 seconds more, 41 percent). The build job grew from 102 to 140 seconds and the verification takes about 7 seconds per image. This is one pair of runs, so treat it as an estimate.
- An image that was not attested is rejected: an image from before this change fails verification (exit code 1, evidence in `docs/evidence/supply-chain.txt`).
- The first end to end run found a bug in my own check, which used the predicate type `https://spdx.dev/Spec/v2.3/` while the stored attestation has `https://spdx.dev/Document/v2.3`.
- Verification proves where the image came from. It does not prove that the code is free of vulnerabilities, which is the job of the scans.

## What I would do in production

Generate the SBOM during the build instead of pulling the image again, which should remove part of the added time. Enforce the same check inside the cluster with an admission policy (for example Kyverno or the Sigstore policy controller), so that nobody can bypass the deploy job with `kubectl`.
