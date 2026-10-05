# ADR 0008: Promote builds with a commit to the GitOps values

Status: accepted

## Context

CI builds and publishes images, and Argo CD applies what Git says. Something has to connect the two.

## Options considered

- CI deploys with `helm upgrade`: simple, but the cluster state is no longer described only by Git.
- CI commits the new tag to `main` automatically: fully automatic, but a bot writes to the protected branch and can loop.
- Argo CD Image Updater: automatic, one more component to run.
- A person (or a controlled job) changes the tag in `gitops/values.yaml` and commits it.

## Decision

The desired state lives in `gitops/values.yaml`. Promoting a build is a commit that changes the tags, and Argo CD rolls it out.

## Consequences

- Every deployment has a commit, an author and a diff, and manual changes in the cluster are undone within seconds.
- The step is manual today, which keeps it visible and reviewable, but it is also slower and easy to forget.

## What I would do in production

A promotion job that opens a pull request with the new tag after a green build, with an approval required for production. I treat this as the next improvement.
