# Running the drills of v2

Every phase of v2 was written and tested as far as it can be without a cluster, and **none of the drills has run on a cluster yet**. Each phase document has predictions that were written before the run and an empty "Results" section. This page is the order in which to run them, what to look at first, and how to write the results back.

## Rules for every session

- **One phase per session**, with Chrome and other heavy applications closed. The Docker VM is limited to 6 GB in `.wslconfig`, and a cluster that asked for 5 GB crashed Docker. Start a cluster with `minikube start -p campusslot --memory=3500 --cpus=3`, never with more.
- **Predictions stay as they are.** Add what was measured next to them. If a prediction was wrong, say so, and say why. That is the finding.
- **A failure of the first run is normal.** The least verified parts are listed below. Fix the code, rerun the drill, and keep the first failure in the document as a note ("the first run failed because ...").
- **After a session**: write the results into the phase document, change the status in [the table](README.md), commit, then `minikube delete -p campusslot`. Docker's disk file does not shrink by itself, so compact it afterwards (`diskpart` in an administrator shell, with Docker stopped).
- Port forwards are in the header of every drill script.

## The CI route (used since phase 1)

The drills can run on kind clusters of GitHub-hosted runners, with no load on the laptop: push `v2` to a branch named `drill/phaseN` (`git push -f origin v2:refs/heads/drill/phase1`), and the workflow `.github/workflows/drills.yml` runs that phase and saves the transcripts as artifacts (`gh run download <run-id>`). Phases 1 to 4 are ported and have run. Numbers from a runner are from a shared 4 vCPU machine, and the documents state it. Read the transcript of every job, not only its colour: the first run of phase 1 was green for a drill that had not run.

## The order, and what to check first

| # | Phase | Cluster | Run | The least verified parts (look here first) |
|---|---|---|---|---|
| 1 | [Canary releases](../engineering/canary-releases.md) | default network, ingress, Prometheus, Rollouts | `scripts/install-rollouts.sh`, `ROLLOUT=1 scripts/deploy-local.sh <sha>`, then `scripts/canary-drill.sh good`, `bad` and `control` | Whether the canary Ingress keeps the frontend rule or drops it (the Rollouts controller copies the stable Ingress). Whether the analysis queries return a number (the pod hash in the pod name). Whether the first reading is late because Prometheus has not discovered the new pods |
| 2 | [Policies](../engineering/admission-and-network-policy.md) | a Calico cluster: `--cni=calico` | `scripts/policy-drill.sh network` before and after enabling the policies, then `admission`, then Kyverno | The Kyverno policy (written from the documentation, and `ClusterPolicy` is marked deprecated in favour of `ImageValidatingPolicy`). Whether the CEL expressions of the admission policy are accepted |
| 3 | [Database](../engineering/database-reliability.md) | default network, about 1 GB more | `scripts/install-cnpg.sh`, then `scripts/db-drill.sh failover` (asynchronous, then synchronous). Then with `WITH_BACKUP=1`, the object store, and `scripts/db-drill.sh pitr` | The image tag of the laptop object store (a setting of `install-objectstore.sh`). The fields of the plugin's `ObjectStore`. Whether the backup sidecar passes the Pod Security profile |
| 4 | [Linked signals](../engineering/linked-signals.md) | the monitoring stack with Grafana and Loki, plus Tempo | `scripts/install-monitoring.sh`, `scripts/install-tracing.sh`, then `scripts/trace-drill.sh` | The Tempo chart (the single binary chart may be deprecated). Whether Grafana accepted the `$$` escapes in the derived field and the Tempo link |
| 5 | [Environments](../engineering/environments-and-promotion.md) | default network, Argo CD | `scripts/gitops-drill.sh setup`, `promote`, `drift`, `cleanup` | The `templatePatch` of the ApplicationSet. Whether the `Promote` workflow works (it can only be started after the branch is merged, and the repository setting for pull requests must be on) |
| 6 | [Game day](../engineering/game-day.md) | sessions A, B and C as described there | `python scripts/gameday.py run ...` and `overhead` | Whether the hypotheses hold. A hypothesis that was too optimistic is the most likely finding |

## Writing the results back

For every drill:

1. Save the transcript as a file in `docs/evidence/v2/` (the output of the script, with its numbers). A number in a document has a transcript behind it.
2. In the phase document, replace "Not measured yet." in the **Results** section with a table of the predictions next to what was measured, and a sentence for every difference.
3. In [README.md](README.md), change "drill not run yet" to the result in a few words.
4. If the code changed because of the run, say what and why, in the document's section of findings.
5. Add what the run taught to the decision record if it changed a decision.

## When all six have run

The README of the repository gets a section for v2 that links the results, the numbers go into the summary of the project (the resume bullets are better with measured numbers than with predictions), and the branch can be merged into `main` after the course grading is finished. Until then, `main` stays as it was submitted (tag `v1.0-capstone`).
