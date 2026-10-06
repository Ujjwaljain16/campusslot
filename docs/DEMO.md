# Demo guide

A 6 to 7 minute demo with one message: **the system does not only deploy, it behaves safely when a deployment is broken.** It works live and as a recording. The grading rubric asks for "commit a change, watch the pipeline run, see the deployment update", and the demo adds what happens when a release is bad.

## Before you start (about 10 minutes)

The local cluster is deleted between sessions, so rebuild it first. Docker Desktop must be running.

```bash
minikube start -p campusslot
minikube addons enable ingress -p campusslot
minikube addons enable metrics-server -p campusslot
scripts/install-monitoring.sh                  # Prometheus, Grafana, Loki
scripts/deploy-local.sh 58f286ab6ea1a3fe62cf997041019ef61df33aa2    # a commit that has images in GHCR
```

Then start the port-forwards and keep the three browser tabs ready:

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80 &            # the app
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090 &  # Prometheus
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80 &                       # Grafana
```

| Tab | Address |
|---|---|
| The application | http://localhost:8080 |
| Prometheus alerts | http://localhost:9090/alerts |
| The pipeline | https://github.com/Ujjwaljain16/campusslot/actions |

Check that `kubectl get pods -n campusslot` shows every pod `Running`, and that `curl http://localhost:8080/api/info` answers.

## The story

| Minute | What you show | What you say |
|---|---|---|
| 0:00 | The application and the green run of the pipeline | "A campus room booking service. Every push runs the tests, scans the code and the images, builds, and deploys to a test cluster." |
| 1:00 | `kubectl get pods,svc,ingress,hpa -n campusslot` and `helm list -n campusslot` | "Two copies of the backend and the frontend, behind an Ingress, with an autoscaler and metrics." |
| 2:00 | **Commit a change.** Edit the subtitle in `frontend/src/App.jsx`, open a pull request, watch the checks, merge. Start it first, because the pipeline takes about 4 minutes | "Main is protected, so every change goes through a pull request with the same checks." Run the next step while it builds |
| 2:30 | `scripts/bad-release-drill.sh broken` (see below) | "Now I will deploy a deliberately broken release." |
| 6:00 | The pipeline is green. Deploy that commit with `scripts/deploy-local.sh <sha>` and reload the page | "The new version is live, and `/api/info` reports exactly this commit." |

If time is short, skip the commit and deploy the commit that is already running, and keep the failure drill, which is the part that shows the engineering.

## The failure drill (3 minutes)

```bash
scripts/bad-release-drill.sh broken
```

It builds a broken version of the backend (it listens on the wrong port), deploys it with `helm upgrade --atomic --timeout 60s`, and keeps sending requests through the Ingress. Say what you see as it happens:

1. **`T+3 s`** A new pod appears and stays at `0/1`. "The container runs, but Kubernetes cannot reach it on the port it checks."
2. **`T+5 s`** Kubernetes reports the first failed probe. "The failure is known within seconds."
3. **`T+62 s`** Helm gives up and rolls back by itself. "I allow 60 seconds, about 3.5 times the slowest normal rollout that I measured."
4. **`T+72 s`** Only the previous release is left. "Back to normal, without anyone doing anything."
5. **The last lines.** "Users sent 1600 requests during this, and none failed. The old pods kept serving the whole time."

The numbers to quote (three runs, [`bad-release-drill.md`](engineering/bad-release-drill.md)): first signal 3.6 to 5.4 s, decision at 62 s, previous release alone at 72 s, 0 of 4800 requests failed. Without `--atomic` the broken pod stays until a person rolls back: the alert fires after 150 to 187 s.

Show the Prometheus alerts tab if there is time: the alert goes to pending and clears, because the problem was over before its 2 minute window.

## Questions that may come

- **Why did no request fail?** Three settings from earlier work: the rolling update never removes a healthy pod before the new one is ready, the readiness probe keeps the broken pod out of the traffic, and the old pods keep serving.
- **Then what does `--atomic` add?** It removes the stuck release and the need for a person. The control run shows the broken pod staying until someone acts.
- **What does it not catch?** A release that becomes ready and then returns errors. That is the job of the SLO alerts, and a person or a canary to act on them. I did not build a canary.
- **Why 60 seconds?** A healthy rollout takes 9 seconds and one with a new image 17 seconds, so 60 seconds avoids rolling back slow releases without leaving a broken one waiting for minutes.

## If something goes wrong during the demo

- The drill refuses to start with "the broken image is not on the node": run it again, the image build had a transient failure.
- A pod stays `Pending` or `ContainerCreating` for a long time: Docker Desktop has probably run out of memory. Restart it and run `minikube start -p campusslot`.
- No time to rebuild the cluster: show the transcripts instead. [`bad-release-run1.txt`](evidence/bad-release-run1.txt) is the full output of the drill, and the numbers above come from it.

## After the demo

```bash
minikube delete -p campusslot
```

The cluster costs nothing in the cloud, but it uses memory on the laptop. AWS holds no resources (see [`aws-final-sweep.txt`](evidence/aws-final-sweep.txt)).
