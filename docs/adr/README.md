# Architecture decision records

Short records of the choices that shaped this project, with the options that I rejected and what I would change in production.

| Record | Decision |
|---|---|
| [0001](0001-public-subnets-no-nat.md) | Public worker subnets and no NAT gateway on EKS |
| [0002](0002-three-layer-conflict-protection.md) | Protect the booking rule in three layers |
| [0003](0003-liveness-vs-readiness.md) | Separate liveness from readiness |
| [0004](0004-alloy-instead-of-promtail.md) | Collect logs with Grafana Alloy, not Promtail |
| [0005](0005-kind-in-ci-minikube-locally.md) | Deploy to kind in CI and to Minikube on the laptop |
| [0006](0006-sqlite-fast-tests-plus-postgres.md) | Fast SQLite tests plus a smaller set of real PostgreSQL tests |
| [0007](0007-wait-vs-retry-ingress-race.md) | Retry the deployment steps instead of adding sleeps |
| [0008](0008-manual-promotion-via-git.md) | Promote builds with a commit to the GitOps values |
| [0009](0009-standalone-repository.md) | Build the capstone in its own repository |
| [0010](0010-trivy-ignore-unfixed.md) | Gate on fixable HIGH and CRITICAL findings only |
| [0011](0011-one-scanner-for-iac-and-manifests.md) | Use one scanner for the infrastructure code and the manifests |
| [0012](0012-attest-images-and-verify-before-deploy.md) | Attest every image and verify it before the deploy |
| [0013](0013-range-operator-for-overlap-queries.md) | Ask "what overlaps this period" with a range operator and a GiST index |
| [0014](0014-one-worker-per-pod-scale-with-pods.md) | One uvicorn worker per pod, and more capacity from more pods |
| [0015](0015-canary-releases-judged-by-their-own-metrics.md) | Judge canary releases by their own metrics (v2) |
| [0016](0016-admission-policy-and-default-deny-networking.md) | Enforce what may run, and what may talk, at the cluster (v2) |
| [0017](0017-database-run-by-an-operator.md) | Let an operator run the database, with a replica and a continuous archive (v2) |
| [0018](0018-link-metrics-traces-and-logs-by-trace-id.md) | Link metrics, traces and logs by one trace id (v2) |
| [0019](0019-environments-as-directories-promotion-by-pull-request.md) | Environments as directories, and promotion by pull request (v2) |
