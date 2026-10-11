# ADR 0019: Environments as directories, and promotion by pull request

Status: accepted (v2)

## Context

In v1 there is one environment and one file, `gitops/values.yaml`, whose two tags are changed by hand ([ADR 0008](0008-manual-promotion-via-git.md)). That ADR named the next step: a promotion that is a pull request with an approval. A single environment also means that every build goes straight to the only place that anyone uses, with nothing in between to learn from.

## Options considered

- A branch per environment (`dev`, `staging`, `prod`), with promotion as a merge. The environments drift apart in ways that are hard to see, and a merge brings along every difference that is not about the promotion.
- A repository per environment. Strong separation and access control, and a lot of overhead for one service.
- A directory per environment in one repository, with one chart. Every difference between the environments is a visible file, and a promotion is a diff of two lines.
- CI that deploys with `helm upgrade` to each environment. Simple, and the cluster is again not described only by Git.
- A promotion tool such as Kargo or Argo CD Image Updater. They do this well, and they are another system to run, and the rule that I wanted to teach is small enough to write down in a script.

## Decision

- **A directory per environment**: `gitops/envs/<env>/values.yaml` for dev, staging and prod, over the one chart. What is the same is in the chart, and what differs is in the file: the image tags, the number of replicas, and which of the features of the earlier phases are switched on (canary releases, the database operator, tracing, default deny networking). Prod uses all of them, staging a part, dev the least.
- **One ApplicationSet** (`gitops/applicationset.yaml`) makes an Argo CD Application for each environment from one template. Dev and staging are synchronised automatically, and a manual change in the cluster is undone (selfHeal). **Prod is not synchronised automatically**: a merged promotion makes it OutOfSync, and a person synchronises it. That is the second approval of prod, and Argo CD enforces it.
- **Promotion is a pull request** that changes two lines (the backend and the frontend tag, always the same commit). `scripts/promote.py` makes the change, and the `Promote` workflow opens the pull request after it has verified, for dev, that the images carry a build attestation from this repository's workflow.
- **The rules are code, and CI checks them on every pull request** (`scripts/promote.py check`, tested with 21 unit tests that build real git repositories): the tags are full commit hashes; the backend and the frontend run the same commit; staging may only take what dev runs at the base of the pull request, and prod only what staging runs, so a build cannot skip an environment; and a prod promotion changes nothing else.
- **A tag-only change does not rebuild anything.** The images of that commit already exist, so `changes.sh` treats a change of only the tag lines as a deployment decision and skips the heavy jobs. That also stops a promotion from starting another one.

## Consequences

- Staging and prod only ever run builds that ran in the environment before, and a promotion is two lines that a reviewer can read. Every environment has a history in Git, and a rollback is a revert of one commit.
- All environments are rendered and validated in CI on every change, including prod, which a laptop cannot run.
- One cluster with a namespace per environment is a lab arrangement. It separates names and policies, and it does not separate a failure or an attacker. Production would use a cluster (or an account) per environment.
- The base of the rule is the pull request's base commit. Two promotions that are in flight at the same time are checked against the same base, so the second one fails until it is rebased. That is slow and safe.
- A pull request that a workflow opens with the default token does not start the other workflows, so the checks have to be started by closing and opening it. A GitHub App token removes that step.
- The rules are enforced for a pull request. A person with the right to push to the branch can still bypass them, which is what branch protection is for.

## What I would do in production

A GitHub App token, a smoke test and a soak time in each environment before the next promotion is allowed, a notification when prod is OutOfSync, a separate cluster and account per environment, a webhook instead of polling, and a record of who approved which promotion.
