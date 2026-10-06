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
