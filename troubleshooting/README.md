# Troubleshooting labs

I broke the application on purpose in four different ways, on the real Minikube cluster, and fixed each failure by following the same routine: identify the symptom, investigate with `kubectl`, name the root cause, apply the smallest fix, and verify. Every command and every line of output in the evidence files was captured from a real run, and none of the output has been edited.

The manifests are in this folder and use a scratch namespace called `ts-lab`, so the real `campusslot` release was never touched. The raw transcripts are in [`docs/evidence`](../docs/evidence).

| Lab | Symptom | Root cause | Manifest | Transcript |
|---|---|---|---|---|
| 1 | `ErrImagePull`, then `ImagePullBackOff` | The image tag does not exist in GHCR | [01](01-broken-image.yaml) | [lab1](../docs/evidence/lab1-imagepullbackoff.txt) |
| 2 | Pod healthy, Service refuses connections | The Service selector contains a typo, so it has no endpoints | [02](02-broken-service.yaml) | [lab2](../docs/evidence/lab2-service-no-endpoints.txt) |
| 3 | Restart count keeps rising | A bad `DATABASE_URL` makes the migration step fail and the container exit with status 1 | [03](03-crashloop.yaml) | [lab3](../docs/evidence/lab3-crashloopbackoff.txt) |
| 4 | Pod is `Running` but `0/1` Ready | The same bad `DATABASE_URL`, but the app stays alive and `/ready` fails | [04](04-readiness-fail.yaml) | [lab4](../docs/evidence/lab4-readiness-failure.txt) |

Run a lab with `kubectl apply -f troubleshooting/00-namespace.yaml -f troubleshooting/01-broken-image.yaml`, and remove everything afterwards with `kubectl delete namespace ts-lab`.

## Lab 1: ImagePullBackOff

**Identify.** `kubectl get pods` showed `ErrImagePull`, and later `ImagePullBackOff`, with the container never starting.

**Investigate.** The events at the end of `kubectl describe pod` said that pulling `campusslot-backend:v9.9.9-does-not-exist` failed with `NotFound`. I asked the registry directly with `docker manifest inspect`. The bad tag answered `manifest unknown`, while the real commit tag returned a manifest.

**Root cause.** The tag was never published. Images are only pushed by the pipeline, tagged with a commit SHA, so a hand-typed tag such as `v9.9.9` cannot exist.

**Fix.** `kubectl set image` pointed the Deployment at the real SHA tag.

**Verify.** The rollout completed and the new pod reached `1/1 Running`.

**Prevention.** The chart refuses to render without an image tag, and the pipeline deploys only SHAs that it has just pushed.

## Lab 2: Service with no endpoints

**Identify.** The pod was `1/1 Running`, yet a request to the Service from another pod failed with `Connection refused`.

**Investigate.** `kubectl get endpoints` showed `<none>`. Comparing `kubectl get svc -o jsonpath` with `--show-labels` on the pod showed that the Service selected `tier=backned` while the pod carried `tier=backend`. Selecting pods with the typo returned `No resources found`.

**Root cause.** A one-letter typo in the Service selector. A Service only routes to pods that match every label in its selector, and a selector that matches nothing is not an error, so Kubernetes accepted it silently.

**Fix.** I patched the selector to `tier=backend`.

**Verify.** The endpoints listed the pod address, and `/health` through the Service returned `{"status":"ok"}`.

**Prevention.** The Helm chart builds the selector and the pod labels from the same helper template, so they cannot drift apart.

## Lab 3: CrashLoopBackOff

**Identify.** The pod restarted again and again. I expected the literal word `CrashLoopBackOff`, but on Kubernetes 1.37 the status column alternated between `Running` and `Error` while the restart count rose from 3 to 4. The back-off showed up in the events as `Back-off restarting failed container`. The failure was the same, only the label differed from what older documentation shows.

**Investigate.** `kubectl describe` reported `Last State: Terminated`, `Reason: Error`, `Exit Code: 1`. `kubectl logs --previous` showed fifteen retries of `failed to resolve host 'no-such-db'` followed by `Migrations still failing after 15 attempts, giving up`. Printing the `DATABASE_URL` with the credentials masked showed the host `no-such-db`, whereas the real database is the Service `campusslot-postgres`.

**Root cause.** This lab sets `RUN_MIGRATIONS=true`, so the entrypoint runs Alembic before starting the server. With an unreachable database it gives up after 15 attempts and exits with status 1, and the kubelet restarts the container with growing delays.

**Fix.** I created a Secret holding the correct URL, with the host written as `campusslot-postgres.campusslot.svc.cluster.local` because the lab runs in a different namespace from the database, and I pointed the Deployment at it with `secretKeyRef`. I did not print the secret value at any point.

**Verify.** The new pod ran the migration step, logged `Application startup complete`, and stayed `1/1 Running` with 0 restarts.

**Prevention.** In the real chart the migration runs once in a Helm hook Job, not in every pod, and credentials always come from a Secret.

## Lab 4: Running but never Ready

**Identify.** The pod was `Running` with 0 restarts, yet `READY` stayed at `0/1`.

**Investigate.** The events showed `Readiness probe failed`, first with `connection refused` while the server started, then repeatedly with `context deadline exceeded`. The EndpointSlice marked the pod address `ready: false`, so the Service listed no endpoints. I then asked the application directly from inside the pod: `/health` returned `200`, while `/ready` returned `503 {"status":"unavailable","detail":"database unreachable"}`.

**Root cause.** The database host was unreachable, exactly as in lab 3, but this time without the migration step, so the process stayed alive. Liveness (`/health`) does not look at the database, so Kubernetes correctly did not restart the pod, and readiness (`/ready`) did look at it, so the pod was correctly kept out of the Service. One detail surprised me: the kubelet saw timeouts rather than `503` responses, because resolving the dead hostname takes longer than the probe's one second timeout. The behaviour is still correct, since either result keeps the pod out of rotation.

**Fix.** I pointed the Deployment at the Secret created in lab 3.

**Verify.** The new pod became `1/1 Running` and the Service listed its address as an endpoint.

**Prevention.** This lab is the reason liveness and readiness are separate endpoints. If both pointed at the database, a database outage would restart every pod at once and turn a short outage into a longer one.

## Labs 3 and 4 side by side

Both labs have the same root cause and show two different symptoms. The difference lies in whether the process exits (lab 3) or keeps running while reporting that it is not ready (lab 4). Telling the two apart quickly is the main skill this exercise trains: a rising restart count points at the process, a `0/1` Ready pod with no restarts points at the readiness probe.
