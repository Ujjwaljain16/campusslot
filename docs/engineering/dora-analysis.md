# Reading the DORA numbers

The table in [dora.md](dora.md) is produced by [`scripts/dora.py`](../../scripts/dora.py) from the real Actions history, so I can regenerate it at any time. A table of four numbers does not improve anything by itself, so this page records what I learned from it and what I did about it.

## What the numbers say

| Metric | Result | My reading |
|---|---|---|
| Change failure rate | 4 of 26 finished runs, 15 percent | Looks high, but the average hides the pattern below |
| Time to restore | median 6.8 minutes, longest 26.1 minutes | Short for a pipeline fix, and the longest case was inflated by my parallel Terraform work |
| Lead time | median 4.6 minutes | Almost equal to the pipeline duration, so the pipeline is the only lever |
| Deployment frequency | 22 green runs on the day | Frequent, but 59 commits in 26 finished runs means that some pushes carried several commits |

## The failures had one cause

I looked at the failing job and step for each of the four red runs, using `gh run view --log-failed`:

| Run | Commit | Failing step | Cause |
|---|---|---|---|
| 37303336401 | `c84e634` | `helm upgrade --install` in the kind deploy job | The ingress admission webhook refused the connection |
| 37306992298 | `80739c6` | the same step | The same webhook refusal |
| 37309510333 | `f53e1d8` | the same step | The same webhook refusal, even after my first fix |
| 37317474907 | `dc987ac` | the smoke test in the same job | A `503` from the ingress, which had not yet learned the new backends |

All four failures were in one stage, and all four had the same kind of cause: the ingress controller is ready later than the pods that it routes to. Nothing in the application or the chart was wrong. The deployment test was racing the cluster.

## What I changed, one fix per observation

1. **Wait for the webhook endpoint** before installing the chart. This was not enough: the endpoint was ready, but the Service address still refused connections for a few seconds.
2. **Bounded retry around the install.** `--atomic` removes a failed release completely, so a retry starts clean.
3. **Retry inside the smoke test.** Every request waits for its own success, and I tested both the success and the failure path of the helper before pushing.

## Result

Before the last fix, 4 of 16 finished runs were red, which is 25 percent. Since it, the last 10 finished runs in a row were green, which is 0 percent. The sample is small and it covers a period in which I was still learning the system, so I do not claim more than this: the fixes addressed the cause that the logs showed, and the failures stopped.

## Caveats

- DORA metrics were designed for teams and for production changes. One person building a project in a few days produces numbers that are real but not comparable with a team.
- Only deployments to the throw-away kind cluster are visible in Actions. My deployments to the local Minikube cluster were manual and are not counted.
- The longest restore time of 26.1 minutes is the red run of the Terraform commit. The next green run came only after I had also fixed and re-applied the Terraform node group, which I was doing at the same time, so it measures my parallel work more than the difficulty of the fix.
- Lead time uses the commit time of the pushed head commit, so a push of several commits understates the lead time of the older ones.
