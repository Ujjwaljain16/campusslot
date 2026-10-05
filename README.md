# CampusSlot

CampusSlot is a room and lab booking service for a campus. Students and staff reserve a room for a time slot, and the system guarantees that two confirmed bookings can never overlap in the same room. I built it as the final project of a DevOps and cloud course, and the application is deliberately small so that most of the effort goes into how it is built, tested, secured, shipped and observed.

![CampusSlot day view](docs/evidence/app-desktop.png)

## 1. Overview

| Area | What I built |
|---|---|
| Application | FastAPI backend, React frontend, PostgreSQL database, Alembic migrations |
| Tests | 42 backend tests on SQLite, 4 PostgreSQL integration tests, 12 frontend tests, coverage floor of 85 percent |
| Containers | Two multi-stage, non-root images with health checks, and a Docker Compose stack |
| CI/CD | GitHub Actions: lint, tests, secret scan, image build, Trivy gate, push to GHCR with commit SHA tags, Helm deploy to a kind cluster |
| Kubernetes | A Helm chart deployed on Minikube with ingress, a migration Job, an autoscaler, disruption budgets and a restricted pod security namespace |
| Infrastructure | Terraform for a VPC and an EKS cluster, applied for real and destroyed again |
| Observability | Prometheus and Grafana with a provisioned dashboard built from application and cluster metrics |
| Troubleshooting | Four failures that I created on purpose and fixed, with transcripts |

The public repository is `Ujjwaljain16/campusslot`. Images are published as `ghcr.io/ujjwaljain16/campusslot-backend` and `ghcr.io/ujjwaljain16/campusslot-frontend`, both tagged with the Git commit SHA.

## 2. Problem statement

Shared rooms and labs are usually booked through a spreadsheet or a chat message, and double bookings follow. The difficult part of the problem is not storing a booking. It is guaranteeing that two people who press the button at the same moment cannot both win.

I therefore protect the rule in three independent layers, and I test each one separately:

1. **Request validation** rejects an end time that is not after the start time, a zero length slot, and a slot longer than 12 hours, with HTTP 422.
2. **An application check** looks for an overlapping confirmed booking in the same room and answers HTTP 409, naming the booking that blocks the request.
3. **A database constraint** is the final safety net. On PostgreSQL an `EXCLUDE` constraint over `tstzrange(start_time, end_time, '[)')` makes an overlapping insert impossible even if two requests pass the application check at the same time. The API converts that database error into the same HTTP 409.

Time ranges are half open, so a booking from 10:00 to 11:00 and another from 11:00 to 12:00 are both allowed. A cancelled booking frees its slot. I wrote the application on purpose without login, roles or notifications, because those features would add code without adding to the DevOps story.

## 3. Architecture

```
                          Browser
                             |
                   http://localhost:8080 (Ingress) or :3000 (Compose)
                             |
              +--------------v--------------+
              |   nginx (frontend, port 8080, non-root)
              |   serves the React build, proxies /api
              +--------------+--------------+
                             |  /api  (relative URL, the browser never sees a backend host name)
              +--------------v--------------+
              |   FastAPI backend (port 8000, non-root)     <---  /metrics  <---  Prometheus  --->  Grafana
              |   /health  /ready  /api/rooms  /api/bookings
              +--------------+--------------+
                             |
              +--------------v--------------+
              |   PostgreSQL 16 (StatefulSet + volume, or Compose volume)
              |   EXCLUDE constraint on overlapping bookings
              +-----------------------------+

   git push --> GitHub Actions --> tests --> Trivy --> GHCR (tag = commit SHA) --> Helm deploy
                                                                                      |
                                   Terraform --> VPC + EKS (proof of reproducible infrastructure only)
```

Four decisions shape the design:

- **The browser calls only relative `/api` paths.** nginx proxies them to the backend, with the upstream taken from environment variables, so the same image works in Compose and in Kubernetes.
- **Liveness and readiness are different questions.** `/health` never touches the database, so a database outage cannot cause pods to restart. `/ready` checks the database and the migrated schema, so a pod without a database never receives traffic.
- **Migrations run once.** In Kubernetes a Helm hook Job applies them, so two replicas never migrate at the same moment. Compose runs them in the backend entrypoint because there is only one backend container.
- **Secrets are never committed.** The database password is generated at install time and lives only in a Kubernetes Secret.

## 4. Repository structure

```
backend/         FastAPI app, Alembic migrations (3), tests, Dockerfile
frontend/        React 19 and Vite 8 app, nginx config, Dockerfile
helm/campusslot  Chart with values for dev, ci and prod, 12 template files
k8s/             Namespace with restricted Pod Security labels
ci/              kind cluster configuration used by the pipeline
monitoring/      kube-prometheus-stack values, Grafana dashboard (generated by monitoring/make_dashboard.py)
scripts/         deploy-local, install-monitoring, load-test, generate-traffic
terraform/       VPC and EKS configuration, plan, README with the design notes
troubleshooting/ Four failure labs with manifests and write-ups
docs/evidence/   Transcripts and screenshots from real runs
.github/workflows/ci-cd.yml
docker-compose.yml, .env.example
```

## 5. Prerequisites

I developed and ran everything on Windows 11 with WSL2 and Docker Desktop. The versions I used:

| Tool | Version |
|---|---|
| Python | 3.11 locally, 3.12 in the images and in CI |
| Node.js | 22 |
| Docker Desktop | engine 29.0.1 |
| Minikube | 1.39.0 (Kubernetes 1.37.0, Docker driver) |
| Helm | 3.22.0 |
| Terraform | 1.9.8 with AWS provider 6.67.0 |

## 6. Run locally

This path needs no Docker. The backend runs against SQLite, and the Alembic migration that adds the PostgreSQL-only constraint is skipped on SQLite.

```bash
cd backend
pip install -r requirements-dev.txt
DATABASE_URL=sqlite:///./local-demo.db alembic upgrade head
DATABASE_URL=sqlite:///./local-demo.db uvicorn app.main:app --port 8000

cd ../frontend
npm ci
npm run dev        # http://localhost:5173, the dev server proxies /api to port 8000
```

I ran these steps and recorded the output in [`docs/evidence/run-locally.txt`](docs/evidence/run-locally.txt). The migrations created the schema and seeded six rooms, `/health` and `/ready` answered, and a request to `http://localhost:5173/api/info` through the Vite proxy returned the application metadata.

### Configuration

| Variable | Used by | Meaning | Default |
|---|---|---|---|
| `DATABASE_URL` | backend | SQLAlchemy URL of the database, for example `postgresql+psycopg://user:password@host:5432/db` | required |
| `APP_ENV` | backend | Environment name reported by `/api/info` | `development` |
| `LOG_LEVEL` | backend | Log verbosity | `INFO` |
| `RUN_MIGRATIONS` | backend entrypoint | When `true`, run `alembic upgrade head` before starting (used by Compose, not by Kubernetes) | `false` |
| `GIT_SHA`, `APP_VERSION` | backend | Build metadata baked into the image and shown by `/api/info` and the page footer | `dev`, `1.0.0` |
| `MAX_BOOKING_HOURS`, `DAY_OPEN_HOUR`, `DAY_CLOSE_HOUR` | backend | Longest booking and the opening window used for the utilisation figures | 12, 8, 20 |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Compose | Database credentials, read from the git-ignored `.env` | see `.env.example` |
| `BACKEND_HOST`, `BACKEND_PORT` | frontend (nginx) | Upstream that nginx proxies `/api` to | `backend`, `8000` |
| `POSTGRES_TEST_URL` | tests | Enables the PostgreSQL integration tests against that database | unset |

## 7. Docker

Both images use a multi-stage build and run as a non-root user.

| | Backend | Frontend |
|---|---|---|
| Base | `python:3.12-slim` | `node:22-alpine` build stage, then `nginxinc/nginx-unprivileged:1.30-alpine` |
| User | `10001` | `101` |
| Port | 8000 | 8080 |
| Health check | Python request to `/health` | `wget` request to `/healthz` |
| Extras | `apt-get upgrade` at build time, an entrypoint that can retry the migration | Security headers, a content security policy, asset caching, SPA fallback |

The official `nginx` image runs as root, so I used the unprivileged variant to meet the non-root requirement for both images.

## 8. Docker Compose

```bash
cp .env.example .env     # then put a real random password in .env, which is git-ignored
docker compose up --build -d
docker compose ps
```

The stack has a PostgreSQL service with a `pg_isready` health check and a named volume, a backend that starts only after the database is healthy, and the frontend on port 3000. I recorded the full proof in [`docs/evidence/docker-proof.txt`](docs/evidence/docker-proof.txt):

- All three services reported healthy, and `/health`, `/ready` and `/api/rooms` through the nginx proxy answered.
- A booking returned HTTP 201 and the identical request returned HTTP 409.
- After `docker compose down` and `docker compose up -d` the booking was still present, because the named volume survived. `docker compose down -v` removed the volume and the data with it.
- `id` inside the containers shows `uid=10001(app)` for the backend and `uid=101(nginx)` for the frontend.

One failure is worth recording. My first start of this proof failed with a database authentication error. A volume from an earlier run still held the old password, and PostgreSQL applies `POSTGRES_PASSWORD` only when it initialises an empty volume. I confirmed that the volume was mine, removed it and started again.

![docker compose ps](docs/evidence/terminal-docker-compose-ps.png)
![docker compose up --build -d](docs/evidence/terminal-docker-compose-up-build.png)
![Non-root users](docs/evidence/terminal-docker-nonroot-id.png)
![Data survives down and up](docs/evidence/terminal-docker-persistence.png)
![The application under Compose](docs/evidence/app-compose.png)

## 9. Testing

```bash
cd backend
ruff check . && ruff format --check .
bandit -r app -ll
pytest -v --cov=app --cov-report=term-missing --cov-fail-under=85          # SQLite, fast
POSTGRES_TEST_URL=postgresql+psycopg://... pytest -v -m postgres            # a real PostgreSQL

cd ../frontend
npm test && npm audit --omit=dev --audit-level=high && npm run build
```

| Suite | Result | Transcript |
|---|---|---|
| Backend, SQLite | 42 passed, coverage 89.86 percent against a floor of 85 | [backend-tests.txt](docs/evidence/backend-tests.txt) |
| Backend, PostgreSQL 16 | 4 passed: migrations, the overlap constraint, the database layer returning 409, and a concurrent race that creates exactly one booking | [postgres-tests.txt](docs/evidence/postgres-tests.txt) |
| Frontend | 12 passed, 0 audit vulnerabilities, production build succeeds | [frontend-tests.txt](docs/evidence/frontend-tests.txt) |

![pytest -v, 42 passed](docs/evidence/terminal-pytest.png)

The backend tests cover health, readiness with the database down and with an unmigrated schema, every route of rooms and bookings, and the rules from section 2, including the adjacent slot case in both directions and a booking that is extended without conflicting with itself. I ran the PostgreSQL tests against a throwaway container that I removed afterwards. Bandit reports no issue of medium or high severity, and one low severity note that the `-ll` flag filters out.

## 10. CI/CD

The workflow in [`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml) runs on every push and pull request to `main`, with least privilege permissions and a concurrency group.

```
backend tests ----+
frontend build ---+--> build and scan images --> push to GHCR --> deploy with Helm to kind --> smoke test
postgres tests ---+     (Trivy gate, SHA tags)
secret scan ------+
```

A successful run took 3 minutes and 59 seconds: backend tests 19 s, frontend 9 s, PostgreSQL tests 34 s, secret scan 7 s, build, scan and push 98 s, Helm deploy 98 s.

The deploy job creates a throw-away kind cluster, installs the ingress controller, installs the chart with the SHA tagged images, and tests the application through the ingress: the frontend health check, at least six rooms from the API, the deployed commit equal to the commit under test, a booking that returns 201, and the same slot that returns 409. A GitHub runner cannot reach my laptop cluster, so the persistent demo cluster is updated with `scripts/deploy-local.sh <sha>`, which uses the same chart and the same images.

![A green pipeline run](docs/evidence/github-actions-run.png)
![Images in GHCR, tagged with commit SHAs](docs/evidence/ghcr-backend-package.png)

The pipeline was not green on the first try, and three failures taught me something:

- **Webhook race.** The deploy job failed twice because the ingress admission webhook refused connections for a few seconds after its endpoint became ready. I first added a wait for the webhook endpoint, which was not enough, and then wrapped the Helm install in a bounded retry. This is safe because `--atomic` fully removes a failed release. The later runs passed on the first attempt, so the retry path itself has not been exercised yet.
- **A bad action pin** in an earlier module taught me to verify every action version against the GitHub API before committing, which I did for this workflow.
- **A smoke test race.** During the final rehearsal the Helm install succeeded, but my smoke test received a `503` from `/api/rooms` through the ingress. Helm waits for the pods to be Ready, and the ingress controller learns about new backends a few seconds later. My test called the API once without waiting. Every smoke test call now retries until it succeeds, and I checked both the success and the failure path of that helper before pushing.

### Final rehearsal

I rehearsed the live demo end to end and recorded it in [`rehearsal.txt`](docs/evidence/rehearsal.txt): I changed the page subtitle in `frontend/src/App.jsx`, ran the frontend tests and build, committed with a meaningful message and pushed to `main`. The pipeline built and scanned both images and pushed them with the commit SHA. I then ran `scripts/deploy-local.sh <sha>`, and Kubernetes rolled both Deployments to the new images while the migration Job completed. The chart allows no unavailable replicas during a rollout, but I did not measure downtime during this run. I verified three things from the outside: `/api/info` reported exactly the commit that I had pushed, the rendered page showed the new subtitle with the footer `Build 5e03c9a`, and all existing bookings were still in the database.

The first push of this rehearsal failed in the smoke test described above, so the loop took about eleven minutes from the first push to the new version being live, including the diagnosis and the fix. A clean run takes about four minutes for the pipeline plus about one minute for the local deploy.

![The application after the rehearsal deployment](docs/evidence/rehearsal-after-deploy.png)

## 11. Security

| Control | Where |
|---|---|
| Both images run as non-root users and have health checks | Dockerfiles, proof in section 8 |
| Pods run with `runAsNonRoot`, no privilege escalation, all capabilities dropped, the `RuntimeDefault` seccomp profile and a read-only root file system with a temporary volume | Helm chart |
| The namespace enforces the Pod Security `restricted` profile | `k8s/namespace.yaml` |
| Trivy fails the build on any fixable HIGH or CRITICAL finding in either image, before anything is pushed | CI |
| Secret scanning over the complete Git history | gitleaks in CI, and locally: no leaks found |
| Static analysis and dependency audit | bandit, `npm audit` |
| The database password never enters Git. It is passed with `--set-string` and stored in a Secret | `scripts/deploy-local.sh` |
| The Kubernetes API of the EKS cluster accepted only my address, and the configuration refuses `0.0.0.0/0` | Terraform |
| Security headers and a content security policy | nginx |

The Trivy scans of the pipeline run on 5 October 2026 reported zero HIGH or CRITICAL findings for both images (Debian 13.7 for the backend, Alpine 3.24.2 for the frontend). I did not inject a fake vulnerability to produce a failing screenshot. A clean result shows that the gate passes today, and it does not prove that the images are safe, because a new vulnerability can be published tomorrow and the gate exists for exactly that day.

Limits: the application has no authentication, and the chart does not define network policies. I left both out of scope on purpose.

The Trivy report of both scans, copied from the pipeline log, is in [`trivy-ci-output.txt`](docs/evidence/trivy-ci-output.txt). It lists the Debian packages and every Python package of the backend, and the Alpine packages of the frontend, each with zero findings.

![Both Trivy scan steps succeeded in the pipeline](docs/evidence/github-trivy-scan-steps.png)
![Trivy report for the backend image, 0 vulnerabilities](docs/evidence/trivy-backend-report.png)
![Trivy report for the frontend image, 0 vulnerabilities](docs/evidence/trivy-frontend-report.png)

## 12. Terraform

The configuration in [`terraform/`](terraform) builds a VPC with two public and two private subnets, and an EKS cluster with one `t3.small` managed node. It uses pinned community modules and keeps the Kubernetes API reachable only from my address. The design notes, the cost estimate and the destroy procedure are in [`terraform/README.md`](terraform/README.md).

```bash
cd terraform
terraform init && terraform fmt -check && terraform validate
terraform plan -out=tfplan          # Plan: 48 to add, 0 to change, 0 to destroy
terraform apply tfplan              # only after reviewing the plan
terraform plan -destroy -out=destroy.tfplan && terraform apply destroy.tfplan
```

I applied the plan to a real account in `ap-south-1` and destroyed it about 45 minutes later:

- The first apply failed on the node group, because the public subnets did not assign public IP addresses and EKS rejects a node group in such subnets when no NAT gateway exists. I found the cause with `aws eks describe-nodegroup`, set `map_public_ip_on_launch = true`, and applied a second reviewed plan.
- The cluster was `ACTIVE` on Kubernetes 1.36, the node was `Ready`, and `kubectl get nodes` worked through the restricted public endpoint.
- The destroy plan removed exactly the 48 resources, and a final check found no cluster, VPC, subnet, NAT gateway, Elastic IP, instance, volume, load balancer, role or OIDC provider left in the region.

Public worker subnets and no NAT gateway are an intentional simplification for cost. A NAT gateway costs about 0.045 USD per hour, and the whole run cost an estimated 10 US cents. A production design would place the nodes in private subnets with controlled egress.

![terraform output and cluster status](docs/evidence/terraform-output-terminal.png)
![terraform validate and plan, 48 to add](docs/evidence/terminal-terraform-plan.png)
![The recorded destroy transcript and the empty cluster list. The destroy itself ran earlier and is not repeated here](docs/evidence/terminal-terraform-destroy-transcript.png)
![EKS cluster in the console](docs/evidence/aws-eks-cluster.png)
![Node group in the console](docs/evidence/aws-eks-node-group.png)
![VPC](docs/evidence/aws-vpc.png)
![Subnets](docs/evidence/aws-subnets.png)
![No NAT gateways](docs/evidence/aws-no-nat-gateways.png)

I masked the AWS account number in the screenshots and the transcripts. The application itself is not deployed to EKS.

## 13. Kubernetes

I ran the application on a dedicated Minikube profile:

```bash
minikube start -p campusslot --driver=docker --memory=3584 --cpus=3 --addons=ingress,metrics-server
```

My first attempt failed because earlier failed starts had left a stale profile whose certificates had expired. Deleting the profile with `minikube delete -p campusslot` and starting again fixed it.

The release contains a StatefulSet for PostgreSQL, a migration Job, two Deployments with two replicas each, ClusterIP Services, an Ingress, an autoscaler and two disruption budgets. Probes are separate: a startup probe and a liveness probe on `/health`, and a readiness probe on `/ready`. The application is reached through the ingress controller:

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80      # http://localhost:8080
```

![kubectl get pods, svc, helm list, ingress and hpa](docs/evidence/terminal-kubectl-helm.png)
![The application through the Ingress](docs/evidence/app-desktop.png)

### Autoscaling

The backend autoscaler targets 50 percent CPU with 2 to 5 replicas. I generated load from pods inside the cluster with `scripts/load-test.sh 150 240`, which records a timestamped line every ten seconds ([`hpa-timeline.txt`](docs/evidence/hpa-timeline.txt)):

| Time | Event |
|---|---|
| 16:42:30 | 4 load pods start, 2 backend replicas, CPU 3 percent of the request |
| 16:43:52 | CPU reaches 428 percent, three new backend pods appear |
| 16:44:13 | 5 replicas |
| 16:45:00 | Load stops |
| 16:47:08 | CPU back to 3 percent |
| 16:48:51 | Scaled back down to 2 replicas |

At first the autoscaler showed `<unknown>` for about two minutes, because metrics-server had only just started. I repeated the test later while Prometheus was recording, and the dashboard in section 15 shows the same shape.

## 14. Helm

The chart in [`helm/campusslot`](helm/campusslot) refuses to render without an image tag and without a database password, so nothing can be deployed with `latest` or with a default credential. Values files exist for local development, CI and production, where production expects an external database Secret and TLS.

```bash
helm lint helm/campusslot -f helm/campusslot/values-ci.yaml --set backend.image.tag=x --set frontend.image.tag=x --set-string postgres.password=x
scripts/deploy-local.sh <commit-sha>
```

`scripts/deploy-local.sh` reuses the database password already stored in the cluster on every upgrade, because PostgreSQL fixes it when its volume is first initialised. I found while testing the script that it looked for the wrong Secret name, which would have generated a new password and broken the database on the second deploy. I fixed it and then proved it: a second deploy reused the password and all existing bookings survived.

## 15. Monitoring

`scripts/install-monitoring.sh` installs kube-prometheus-stack 91.9.0, trimmed to Prometheus, Grafana, the operator and kube-state-metrics, and loads the dashboard from a ConfigMap. The chart's ServiceMonitor makes Prometheus scrape `/metrics` from every backend pod. `scripts/generate-traffic.sh` produced a realistic mix of reads, bookings, double booking attempts and missing resources.

The backend exposes the standard HTTP metrics and two of its own, `campusslot_bookings_total` and `campusslot_booking_conflicts_total{layer}`. I recorded a sample of `/metrics` and the PromQL results in [`metrics-and-promql.txt`](docs/evidence/metrics-and-promql.txt).

![Prometheus targets, 5 of 5 backend pods up](docs/evidence/prometheus-targets.png)
![ServiceMonitor, monitoring pods and the /metrics output](docs/evidence/terminal-monitoring-metrics.png)
![Grafana dashboard](docs/evidence/grafana-dashboard.png)

The dashboard shows request rate by route, latency percentiles, the 5xx rate, rejected bookings by layer, CPU per backend pod, and current against desired replicas. Two details came from real problems. The first latency panel showed every route at exactly 0.1 seconds, because the default histogram has no bucket below that value, so I switched to the high resolution histogram. Grafana was also killed once for exceeding my 300 MiB memory limit while it rendered the dashboard, and I raised the limit to 512 MiB.

## 16. Troubleshooting

I broke the running application in four ways and fixed each one by following the same routine: identify, investigate, find the root cause, apply the smallest fix, and verify. The write-ups and transcripts are in [`troubleshooting/README.md`](troubleshooting/README.md).

| Lab | Symptom | Root cause |
|---|---|---|
| 1 | `ImagePullBackOff` | The image tag does not exist in the registry |
| 2 | Healthy pod, Service refuses connections | A typo in the Service selector left it without endpoints |
| 3 | Rising restart count | A bad database URL made the migration step exit with status 1 |
| 4 | Pod `Running` but `0/1` Ready | The same bad URL without migrations, so `/ready` failed while `/health` stayed healthy |

On Kubernetes 1.37 lab 3 never displayed the literal word `CrashLoopBackOff` in the status column. The status alternated between `Running` and `Error`, and the back-off appeared only as an event. I recorded this as observed.

## 17. Evidence

All transcripts and screenshots are in [`docs/evidence`](docs/evidence). Every command output was captured from a real run. The only edits are masked account identifiers.

| Topic | Evidence |
|---|---|
| Application | `app-desktop.png`, `app-mobile.png`, `app-compose.png`, `api-docs.png`, `postgres-data-proof.txt` (tables, Alembic version 0003, seeded rooms, bookings and the `EXCLUDE` constraint, read with `psql` inside the database pod) |
| Tests | `backend-tests.txt`, `postgres-tests.txt`, `frontend-tests.txt`, `terminal-pytest.png` |
| Docker | `docker-proof.txt`, three `terminal-docker-*.png` screenshots |
| Git and CI/CD | `github-commit-history.png`, `github-actions-run.png`, `ghcr-backend-package.png`, `ghcr-frontend-package.png`, `trivy-ci-output.txt` and `trivy-*-report.png` (the Trivy report of both images from the pipeline log) |
| Kubernetes and the final rehearsal | `hpa-timeline.txt`, `rehearsal.txt`, `rehearsal-after-deploy.png` |
| Monitoring | `prometheus-targets.png`, `grafana-dashboard.png`, `metrics-and-promql.txt` |
| Troubleshooting | `lab1` to `lab4` transcripts |
| Terraform and AWS | plan, apply, second apply, destroy transcripts, `eks-verification.txt`, `aws-cleanup-verification.txt`, console screenshots |

Known limitations, stated plainly:

- The Minikube demo runs only on my laptop. The pipeline proves the same chart on kind, and the screenshots show the local result.
- The Trivy gate passed on every run, so I have no failing scan to show.
- The EKS cluster ran for under an hour and carried no workload.
- The retry around the Helm install has not yet been needed, because the runs after the fix passed on the first attempt.

## 18. Cleanup

What I already shut down and verified:

```bash
docker compose down                  # the stack; "down -v" also removes the database volume
terraform apply destroy.tfplan       # 48 resources destroyed, then checked with the AWS CLI
```

After the destroy I checked the region with the AWS CLI. It reported no EKS cluster, no VPC other than the default one, and no NAT gateway, Elastic IP, instance, volume or load balancer ([`aws-cleanup-verification.txt`](docs/evidence/aws-cleanup-verification.txt)).
