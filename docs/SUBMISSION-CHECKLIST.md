# Submission checklist

This maps every item of the instructor's grading rubric (`session21-python/GRADING.md`, 100 points) to the file or screenshot that shows it. I checked each row again on 6 October 2026 against the repository, the pipeline and the AWS account, and the last section lists what I could not fully show.

## Where to look first

| Item | Link |
|---|---|
| Repository | https://github.com/Ujjwaljain16/campusslot |
| Pipeline runs, all green on `main` | https://github.com/Ujjwaljain16/campusslot/actions |
| Container images, tagged with the commit SHA | [backend](https://github.com/Ujjwaljain16/campusslot/pkgs/container/campusslot-backend), [frontend](https://github.com/Ujjwaljain16/campusslot/pkgs/container/campusslot-frontend) |
| README (20 sections, then the engineering results) | [`README.md`](../README.md) |
| Recorded demo (4 min 22 s, the failure drill runs live in it) | [`docs/demo/CampusSlot-demo.mp4`](demo/CampusSlot-demo.mp4) |
| Presentation (15 slides with speaker notes, and a PDF copy) | [`CampusSlot-final-presentation.pptx`](presentation/CampusSlot-final-presentation.pptx) |

## M1 Application (10 points)

| Criterion | Evidence |
|---|---|
| Backend starts and answers `/health` | [`backend/app/main.py`](../backend/app/main.py), `/health` and `/ready`, tested in `tests/test_health.py` |
| At least 4 REST endpoints with GET, POST, PUT and DELETE | 11 resource endpoints in [`routes/rooms.py`](../backend/app/routes/rooms.py) and [`routes/bookings.py`](../backend/app/routes/bookings.py), including PUT and DELETE for both resources |
| PostgreSQL with a table managed by Alembic | 4 migrations in [`backend/alembic/versions`](../backend/alembic/versions) (tables, the overlap constraint, seed rooms, the range index) |
| Frontend renders and calls the API | [`frontend/`](../frontend), screenshots [`app-desktop.png`](evidence/app-desktop.png) and [`app-compose.png`](evidence/app-compose.png) |
| Responsive, usable UI | [`app-mobile.png`](evidence/app-mobile.png) |
| Also submitted | `docker-compose.yml`, `backend/requirements.txt` |

## M2 Testing (10 points)

| Criterion | Evidence |
|---|---|
| `pytest` runs without errors | 47 passed, coverage 89.79 percent against a floor of 85: [`backend-tests.txt`](evidence/backend-tests.txt) |
| At least 5 tests over at least 3 endpoints | 47 backend tests in 5 files over rooms, bookings, statistics, health, metrics and logging, plus 7 PostgreSQL tests and 12 frontend tests |
| A test database, not the real one | `conftest.py` sets `DATABASE_URL=sqlite://` before the application is imported. The PostgreSQL tests refuse to run unless the database name contains "test" |
| `pytest.ini` or `conftest.py` | both are in `backend/` |
| Terminal screenshot of `pytest -v` | [`terminal-pytest.png`](evidence/terminal-pytest.png) |

## M3 Git and GitHub (5 points)

| Criterion | Evidence |
|---|---|
| Public repository | public, default branch `main` |
| Meaningful commit messages | more than 80 commits on `main`, none of them a bare "update", "fix" or "test" (checked with `git log`) |
| `.gitignore` for `.env`, `__pycache__`, `node_modules`, `.venv` | all four are in [`.gitignore`](../.gitignore) |
| Commit history screenshot, at least 10 commits | [`github-commit-history.png`](evidence/github-commit-history.png) |

## M4 Docker (10 points)

| Criterion | Evidence |
|---|---|
| Backend Dockerfile builds | [`backend/Dockerfile`](../backend/Dockerfile), built on every pipeline run |
| Frontend multi-stage build (Node, then Nginx) | [`frontend/Dockerfile`](../frontend/Dockerfile): `node:26-alpine` build stage, `nginx-unprivileged` runtime |
| Non-root users | backend `USER 10001`, frontend `USER 101`, proof in [`terminal-docker-nonroot-id.png`](evidence/terminal-docker-nonroot-id.png) |
| Also measured | image sizes (61 MB and 25 MB compressed, 199 MB and 56 MB unpacked), rebuild time and startup time against naive single-stage builds: [`image-metrics.txt`](evidence/image-metrics.txt) |
| `docker compose up --build` starts three services | [`terminal-docker-compose-up-build.png`](evidence/terminal-docker-compose-up-build.png) and [`terminal-docker-compose-ps.png`](evidence/terminal-docker-compose-ps.png): postgres, backend and frontend, all healthy, frontend on port 3000 |

## M5 CI/CD (15 points)

| Criterion | Evidence |
|---|---|
| A workflow file | [`.github/workflows/ci-cd.yml`](../.github/workflows/ci-cd.yml) |
| Triggers on push to `main` | `on: push: branches: [main]` (and on pull requests) |
| `pytest` runs and fails the build | the `Backend tests` and `PostgreSQL integration tests` jobs. A deliberately failing test stopped the push of the images: [`ci-speed.md`](engineering/ci-speed.md) |
| Frontend built in the pipeline | the `Frontend build` job |
| Both images built | `docker buildx bake` ([`docker-bake.hcl`](../docker-bake.hcl)) |
| Pushed to GHCR | [`ghcr-backend-package.png`](evidence/ghcr-backend-package.png), [`ghcr-frontend-package.png`](evidence/ghcr-frontend-package.png) |
| Tags use the commit SHA | the only tag is the 40-character commit SHA. `latest` is never pushed |
| Green run | [`github-actions-run.png`](evidence/github-actions-run.png) and the run link above |

## M6 DevSecOps (5 points)

| Criterion | Evidence |
|---|---|
| Trivy on both images | steps `Scan backend image (Trivy)` and `Scan frontend image (Trivy)`, screenshot [`github-trivy-scan-steps.png`](evidence/github-trivy-scan-steps.png), reports [`trivy-backend-report.png`](evidence/trivy-backend-report.png) and [`trivy-frontend-report.png`](evidence/trivy-frontend-report.png) |
| Fails on HIGH or CRITICAL | `severity: HIGH,CRITICAL`, `ignore-unfixed: true`, `exit-code: "1"`, before anything is pushed ([ADR 0010](adr/0010-trivy-ignore-unfixed.md)) |
| Can explain the result | README section 11 explains what was scanned and what a clean result means |
| Also | Bandit, `pip-audit`, `npm audit`, Gitleaks, and Trivy on the Terraform and the Helm chart |

## M7 Terraform (15 points)

| Criterion | Evidence |
|---|---|
| `terraform/` with valid HCL | [`terraform/`](../terraform), `terraform validate` is part of the pipeline |
| `terraform init` | [`terraform-init.txt`](evidence/terraform-init.txt): initialized successfully from a clean state, then `fmt` and `validate` pass |
| Non-empty plan | 48 resources to add: [`terminal-terraform-plan.png`](evidence/terminal-terraform-plan.png) |
| VPC with at least two public subnets | 2 public and 2 private subnets: [`aws-vpc.png`](evidence/aws-vpc.png), [`aws-subnets.png`](evidence/aws-subnets.png) |
| EKS with a node group | cluster Active and a managed node group: [`aws-eks-cluster.png`](evidence/aws-eks-cluster.png), [`aws-eks-node-group.png`](evidence/aws-eks-node-group.png), region `ap-south-1` visible in the address bar |
| `terraform destroy` | 48 destroyed, then an empty account: [`terminal-terraform-destroy-transcript.png`](evidence/terminal-terraform-destroy-transcript.png) |
| `terraform.tfvars.example` and no credentials | [`terraform.tfvars.example`](../terraform/terraform.tfvars.example) is the only variables file in Git. State files and real variables are ignored, and a scan of the whole Git history for AWS keys, private keys and tokens finds nothing |

## M8 Kubernetes and Helm (15 points)

| Criterion | Evidence |
|---|---|
| `k8s/namespace.yaml` | [`k8s/namespace.yaml`](../k8s/namespace.yaml), applied by `scripts/deploy-local.sh` |
| Helm chart | [`helm/campusslot`](../helm/campusslot): `Chart.yaml`, `values.yaml` (plus dev, CI and prod values) and 13 manifest templates |
| `helm upgrade --install` works | used by the deploy script and by the kind deploy job of every pipeline run |
| Backend and frontend with at least 2 replicas | 2 and 2, shown in [`terminal-kubectl-helm.png`](evidence/terminal-kubectl-helm.png) |
| ClusterIP services | the same screenshot (`kubectl get svc`) |
| Ingress routes `/` and `/api` | [`templates/ingress.yaml`](../helm/campusslot/templates/ingress.yaml), `kubectl get ingress` in the same screenshot |
| All pods Running | the same screenshot (`kubectl get pods`), and `helm list` |
| Browser through the Ingress | [`app-desktop.png`](evidence/app-desktop.png), served through the Ingress at `localhost:8080` |

## M9 Observability (10 points)

| Criterion | Evidence |
|---|---|
| `/metrics` in Prometheus format | [`terminal-monitoring-metrics.png`](evidence/terminal-monitoring-metrics.png) |
| Prometheus scraping the application | [`prometheus-targets.png`](evidence/prometheus-targets.png): 5 of 5 backend targets UP |
| Grafana installed and reachable | [`grafana-dashboard.png`](evidence/grafana-dashboard.png) |
| A panel with live application metrics | request rate, latency percentiles, 5xx rate, conflicts, CPU and autoscaler replicas |
| `monitoring/` values files | [`monitoring/`](../monitoring) |

## M10 Presentation and documentation (5 points)

| Criterion | Evidence |
|---|---|
| `README.md` explaining the application | [`README.md`](../README.md) |
| Live demo: commit, pipeline, deployment | rehearsed end to end: [`rehearsal.txt`](evidence/rehearsal.txt) and [`rehearsal-after-deploy.png`](evidence/rehearsal-after-deploy.png). The recorded demo is [`docs/demo/CampusSlot-demo.mp4`](demo/CampusSlot-demo.mp4), and the failure drill in it is measured in [`bad-release-drill.md`](engineering/bad-release-drill.md) |
| Presentation | 15 slides with speaker notes, one slide per course topic, and three on the engineering results |

## Beyond the rubric

Argo CD GitOps, Loki and Alloy logs, a ConfigMap, a Pod Security profile, four troubleshooting labs, DORA metrics, 14 decision records, alert rules with runbooks, measured rollouts, a bad release that rolls back by itself, a restored backup, signed image provenance, query scale tests, a load test and measured sizing. They are summarised in the README section [Engineering decisions and results](../README.md#engineering-decisions-and-results).

## What I rechecked on 6 October 2026

| Check | Result |
|---|---|
| Backend, PostgreSQL and frontend tests, run again from a clean state | 47 passed (89.79 percent coverage), 7 passed against a real PostgreSQL 16, 12 passed. Transcripts refreshed in `docs/evidence` |
| Pipeline | the last three runs on `main` are green, including the Helm deploy to a kind cluster |
| Links | 166 local links in 38 Markdown files, none broken |
| Secrets | no AWS key, private key or token pattern in any commit, and no Terraform state, plan or variables file tracked at `HEAD`. An early commit briefly contained a saved Terraform plan with non-secret infrastructure metadata, and the next commit removed it. No credentials were committed |
| AWS | every region (18) and every service that can bill was checked: nothing is running or stored ([`aws-final-sweep.txt`](evidence/aws-final-sweep.txt)). The free plan credit is 119.94 USD |

## What I could not fully show

- **The two browser screenshots of the application** ([`app-compose.png`](evidence/app-compose.png) and [`app-desktop.png`](evidence/app-desktop.png)) are captures of the page and do not show the address bar, so the port (3000 for Compose, 8080 for the Ingress through a port-forward) is stated in the README and not visible in the image.
- **The `pytest -v` screenshot** shows 42 passed. The suite has 47 tests now. The README says so, and the current run is in `backend-tests.txt`.
- **The Ingress run on Minikube used a port-forward**, because Minikube has no external load balancer. The EKS cluster was destroyed after the infrastructure was proven and never ran the application.
- **The recorded demo has captions and no audio**, and it captures only the browser viewport (the live drill is shown through a page that follows its real log). The commit and pull request step is not in it.
- **Cost Explorer is not enabled for this account**, so the billed amount cannot be read directly. The empty account and the unchanged credit are the evidence that nothing is billing.
