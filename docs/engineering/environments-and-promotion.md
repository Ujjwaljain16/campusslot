# Environments and promotion through Git

Status: **written and tested where it can be without a cluster (21 unit tests of the promotion rules on real git repositories, every environment renders in CI, the change detection was tried on a throw-away repository). The drill has not been run on a cluster yet.** The measured results are added next to the predictions below after the first run. The decision is in [ADR 0019](../adr/0019-environments-as-directories-promotion-by-pull-request.md).

## The problem

In v1 there is one environment. A build goes straight to the only place that is used, the promotion is a hand edit of a file ([ADR 0008](../adr/0008-manual-promotion-via-git.md)), and nothing stops a build from skipping a step, because there is no step.

## What was built

| Part | File | What it does |
|---|---|---|
| An environment per directory | `gitops/envs/{dev,staging,prod}/values.yaml` | The image tags and the settings of each environment, over one chart. Prod uses the canary, the database operator, tracing and default deny networking; staging a part; dev the least |
| One Application per environment | `gitops/applicationset.yaml` | An ApplicationSet. Dev and staging synchronise by themselves and undo manual changes. **Prod does not synchronise by itself** |
| Namespaces | `k8s/environments.yaml` | One per environment, all with the restricted Pod Security profile and the label that the image policy selects |
| The rules | `scripts/promote.py`, `scripts/tests/test_promote.py` | `promote` moves a build to the next environment, `check` enforces the rules, `appset` prints the ApplicationSet for only some environments |
| The rules in CI | `.github/workflows/ci-cd.yml` (job `promotion-rules`) | The 21 tests, and the rules on every pull request. Every environment is also rendered and validated |
| Tag-only changes | `.github/scripts/changes.sh` | A change of only the tag lines skips the heavy jobs: the images already exist, and a promotion must not start another |
| One click | `.github/workflows/promote.yml` | Opens the promotion pull request, after it has verified the attestation of the images (dev) |
| The drill | `scripts/gitops-drill.sh` | `setup`, `promote`, `drift`, `cleanup`, in a git worktree of its own, on a branch of its own |

The rules, all checked in CI: the tags are full commit hashes; the backend and the frontend run the same commit; **staging only takes what dev runs at the base of the pull request, and prod only what staging runs**; a prod promotion changes nothing else.

Tested without a cluster: the rules against a throw-away git repository (a skipped environment is refused, dev and staging cannot move together in one pull request, a prod change that carries another change is refused, `latest` is not a tag), and `changes.sh`, where a tag-only change gave `code=false` and a change of a setting in the same file gave `code=true`.

## Found while writing it

- A first version of the drill committed on the current branch and ran `git reset --hard`, which could have destroyed uncommitted work. It now uses a separate worktree and a branch of its own, and never touches the working tree of the repository.
- The check "the rule stopped it" first counted any non-zero exit as a pass, so a tool that crashed would have looked like a rule that worked. The drill now requires the message of the rules.
- A worktree is made from a commit, so the drill can only run on committed files. That is what a drill of Git should demand anyway.

## How to run the drill

About 700 MB for Argo CD, plus a small application per environment (a backend, a frontend and a database each, no monitoring). The laptop runs dev and staging, and not prod (see the note in `gitops/envs/prod/values.yaml`).

```bash
minikube start -p campusslot --memory=3500 --cpus=3 && minikube addons enable ingress -p campusslot
scripts/gitops-drill.sh setup       # Argo CD, the ApplicationSet, dev and staging at the old build
scripts/gitops-drill.sh promote     # dev takes a new build, a wrong promotion is refused, staging takes what dev runs
scripts/gitops-drill.sh drift       # change the cluster by hand, and see it undone
scripts/gitops-drill.sh cleanup
```

The drill pushes one branch of its own (`promotion-drill`) to GitHub, because Argo CD follows what is on GitHub, and `cleanup` deletes it.

## Predictions, written before the first run

Argo CD polls Git every 30 seconds in this setup (`timeout.reconciliation`), and a rollout of one backend takes 20 to 40 seconds.

| What | Expected | Why |
|---|---|---|
| Dev runs the new image after the push | 40 to 100 seconds | Up to 30 seconds until the next poll, then the sync, the migration job, and a rolling update |
| Staging while dev has the new build | Still the old build | It was not promoted. That is the point of the step |
| A hand edit that gives staging a build that dev does not run | Refused by `check`, with the message of the rules | Rule: one environment at a time |
| Staging after its own promotion | 40 to 100 seconds after the push | Same path as dev |
| A manual scale of the backend in dev | Back to 1 replica within 5 to 20 seconds | Argo CD watches the objects, so it does not wait for the poll |
| A manual environment variable in dev | Removed within 5 to 20 seconds | Same |
| A deleted Service in dev | Recreated within 10 to 30 seconds | Same, plus the creation |
| Prod, if it were deployed | OutOfSync after a merged promotion, and unchanged until a person synchronises | `autoSync` is off for prod |

If the numbers differ, the difference is the finding.

## Results

Not measured yet.

## Limits that are already known

- Prod is declared and rendered in CI, and it has not been deployed. It needs the components of the earlier phases, which are run one by one in their own drills.
- A pull request that the `Promote` workflow opens with the default token does not start the other workflows. This and the setting that the workflow needs are in [repo settings](repo-settings.md).
- The `Promote` workflow could not be run before the branch is merged, because a workflow has to exist on the default branch to be started by hand. It is checked as YAML, and the logic that it calls is the tested script.
- One cluster with a namespace per environment separates names and policies, not failures. Production would use a cluster per environment.
