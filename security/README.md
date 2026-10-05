# Security gates

Every layer of the supply chain has its own check, and each check runs in the pipeline on every push. The checks complement each other, and none of them replaces the others: a clean container scan says nothing about a secret in the history, and a secret scan says nothing about a vulnerable library.

| Layer | Tool | What it examines | Where it runs | Failure behaviour |
|---|---|---|---|---|
| SAST | Bandit | The backend source code for unsafe patterns | `backend-test` job | Fails the job on any finding of medium severity or above |
| SCA (Python) | pip-audit | The pinned backend dependencies against known vulnerabilities | `backend-test` job | Fails the job on any known vulnerability |
| SCA (JavaScript) | npm audit | The production dependencies of the frontend | `frontend-build` job | Fails the job on a high or critical advisory |
| Secret scanning | Gitleaks | Every commit in the history, not only the latest files | `secret-scan` job | Fails the job when a secret is found |
| Container scanning | Trivy | Operating system packages and libraries of both images | `build-scan-push` job | Fails the build on a fixable HIGH or CRITICAL finding, before anything is pushed |
| Pod hardening | Pod Security `restricted` | The pod specifications at admission time | The cluster | The API server rejects a pod that breaks the profile |

## Security gates

The jobs form a chain. The images are built only after the tests, the dependency audits and the secret scan have passed, they are pushed to the registry only after Trivy has passed for both of them, and the deployment starts only after the push. A failing check therefore stops a release at the earliest possible point, and an image with a fixable HIGH or CRITICAL vulnerability never reaches the registry.

## Running the checks locally

```bash
cd backend
bandit -r app -ll
pip-audit -r requirements.txt

cd ../frontend
npm audit --omit=dev --audit-level=high

cd ..
gitleaks detect --source .
```

## Reading a result

The Trivy scans of the pipeline run on 5 October 2026 reported zero HIGH or CRITICAL findings for both images, which are Debian 13.7 for the backend and Alpine 3.24.2 for the frontend. The reports are in [`docs/evidence/trivy-ci-output.txt`](../docs/evidence/trivy-ci-output.txt). A clean result means that, on that day, no vulnerability with an available fix was known for the installed packages. It does not mean that the images are safe, because new vulnerabilities are published every day, and the gate exists to catch them on the day that they appear.

The flag `ignore-unfixed` is set on purpose. A vulnerability without a published fix cannot be removed by the team, so failing the build because of it would block releases without improving security. Such findings are still visible in a report when the flag is switched off.

## Limits

The application has no authentication and the chart defines no network policies. The images are not signed, and the Software Bill of Materials is not published. I left these out of scope on purpose, and they would be the next steps for a production service.
