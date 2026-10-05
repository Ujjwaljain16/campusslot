# Making the pipeline faster without weakening it

## Baseline

I measured the pipeline with [`scripts/ci_timings.py`](../../scripts/ci_timings.py), which reports the median over several green runs, because one run is noisy. The baseline is the last 8 green runs on `main`, before any change:

| Job | Median |
|---|---|
| Build, scan and push images | 98 s |
| Deploy with Helm (kind) | 97 s |
| PostgreSQL integration tests | 34 s |
| Backend tests | 29 s |
| Frontend build | 10 s |
| Secret scan | 6 s |

**Wall clock: median 238 s (4.0 minutes), range 211 to 275 s.** This is what a developer waits for.

## Where the time went

The jobs ran one after another: the gates (about 34 s), then the build, scan and push (about 98 s), then the deploy job (about 97 s). Two things in that picture were not necessary:

1. The deploy job spent about 58 s creating a kind cluster and installing the ingress controller. Neither step needs the images, yet they started only after the images were pushed.
2. The image build and the Trivy scans waited for the tests, although they do not depend on them. Only the push does.

A second measurement, from the history rather than a run: **13 of the 28 finished runs on `main` (46 percent) were pushes that touched documentation only**, and each of them ran the full pipeline.

## What I changed

| Change | Effect |
|---|---|
| The build, the scans and the cluster setup start at once, together with the gates | The two slow chains overlap with the gates |
| The push to the registry waits for every gate (`.github/scripts/wait-for-jobs.sh`) | The guarantee is unchanged: nothing is pushed unless all gates succeeded |
| The deploy job waits for the build job before it installs the images | A deployment still follows a successful push |
| Both images are built by one `docker buildx bake` | One command, built in parallel |
| `Detect changes` skips the heavy jobs for documentation-only changes | 46 percent of the past runs would not have run the pipeline at all |

## Result

The same measurement on the new pipeline, run from the branch with `workflow_dispatch` so that the deployment really runs. I ran it three times:

| Run | Wall clock |
|---|---|
| 1 (run 37360336891) | 115 s |
| 2 (run 37360647676) | 148 s |
| 3 (run 37360994832) | 205 s |

**Wall clock: median 148 s (2.5 minutes), range 115 to 205 s, against 238 s (4.0 minutes) before. That is 38 percent faster.**

The new pipeline also contains a job that the baseline did not have (the static analysis, about 55 s), so the comparison is conservative: the old structure with that job added would have been slower than 238 s.

## What I checked about the guarantees

A faster pipeline that stops protecting the registry is worse than a slow one, so I tested the failure path with a throw-away branch that contained a deliberately failing test:

| Result | Evidence |
|---|---|
| `Backend tests` failed | run 37361523026 |
| The build job stopped at `Wait for the other quality gates before pushing` and skipped the login and the push | step list of the run |
| The deploy job stopped at `Wait for the images that the build job publishes` and installed nothing | step list of the run |
| Neither image of that commit exists in GHCR | `docker manifest inspect` returned not found for both |

I deleted the branch afterwards.

## Honest limits

- **The samples are not independent.** The three runs used the same commit, so the layer caches were warm. Real pushes change code and may be a little slower. The baseline runs were real pushes, so the comparison favours the new pipeline slightly.
- **Runner start-up varies a lot.** The slowest sample was 205 s and the fastest 115 s with the same code. A median over more runs would be better than three.
- **A failing gate is noticed late by the build job.** In the failure test, the tests failed at 19:11:49, but the build job stopped only at 19:12:28, after it had finished building and scanning. About 40 seconds of compute were wasted. Nothing unsafe was published. A watcher that cancels the build as soon as a gate fails would remove the waste.
- **Polling the Actions API is unusual.** It is simple and it works here, but it needs the `actions: read` permission and a few lines of shell. Splitting the work into separate workflows would be the more conventional design, at the price of passing the images between them.
- **Documentation pushes now skip the deployment.** The DORA script counts only runs in which the deploy job succeeded, so a documentation push is not counted as a deployment.
