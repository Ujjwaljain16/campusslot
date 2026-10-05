# Static analysis of the infrastructure and the manifests

## Baseline

Before this change, nothing in the pipeline looked at the Terraform or at the Helm chart. Trivy checked the container images and the dependencies, but a misconfigured cluster or pod would have passed. I ran `trivy config` locally on a clean copy of the repository, the way CI sees it:

| Scan | Distinct rules that fired |
|---|---|
| Terraform (VPC and EKS) | 7 |
| Helm chart (rendered with the CI values) | 6 |

My first run on the working directory showed 23 Terraform rules. Sixteen of them came from Kubernetes example manifests inside the Terraform module cache (`.terraform/`), which is not part of my code and does not exist in a CI checkout, so I measure on a clean copy.

## What each finding turned into

I sorted every finding into one of three groups, because the right response is different for each.

### Fixed or made switchable (3)

| Rule | Finding | What I did |
|---|---|---|
| AWS-0038 | EKS control plane logging off | Variable `enable_control_plane_logging` |
| AWS-0039 | EKS Secrets not encrypted with a KMS key | Variable `enable_secrets_encryption` |
| AWS-0178 | VPC flow logs off | Variable `enable_vpc_flow_logs` |

These are real security controls that I had left off to keep a 45 minute cluster cheap. Instead of ignoring them, I made them variables, and I added `terraform.tfvars.prod.example` with all three on. The plan for the demonstration profile is unchanged at 48 resources. The production profile plans 58 resources, adding the KMS key, two log groups and the flow log. Nothing was applied.

The pipeline checks the claim on every run: it scans the production profile and fails if anything other than the four permanent exceptions remains. Locally it reported `['AWS-0040', 'AWS-0041', 'AWS-0104', 'AWS-0164']`, so the three cost-driven findings are gone when the switches are on.

### Accepted on purpose, with a written reason (4 Terraform, 5 Helm)

| Rule | Why I accept it | Where it is explained |
|---|---|---|
| AWS-0040, AWS-0041 | The API endpoint is public but restricted to my own address. The rule treats any public address, even a single `/32`, as open | `terraform/.trivyignore.yaml` |
| AWS-0104, AWS-0164 | Public IPs and open egress are the price of having no NAT gateway | `terraform/.trivyignore.yaml`, ADR 0001 |
| KSV-0014 (PostgreSQL only) | Needs two `emptyDir` mounts, which I will add and test on a cluster. **The exception expires on 2026-10-20** | `helm/.trivyignore.yaml` |
| KSV-0020, KSV-0021 | The nginx and postgres images run as uid 101 and uid 70, which own their files | `helm/.trivyignore.yaml` |
| KSV-0125 | Images come from my own registry, pinned to a commit SHA, and are scanned before they are pushed | `helm/.trivyignore.yaml` |
| KSV-0110 | An artefact of rendering the chart without a namespace | `helm/.trivyignore.yaml` |

### False positive (1)

KSV-01010 says that the ConfigMap stores sensitive content. The only key that it flagged is `LOG_LEVEL`. I did not rename the key to please the scanner. I recorded the reason instead.

## The gate really fails

A scan that always passes proves nothing, so I tested the negative cases on a copy:

| Change | Result |
|---|---|
| Remove the AWS-0164 exception | exit code 1, `AWS-0164 (HIGH): Subnet associates public IP address.` |
| Remove the KSV-0125 exception | exit code 1, `KSV-0125 (MEDIUM): ... image from an untrusted registry.` |
| Set `readOnlyRootFilesystem: false` in the shared security context | exit code 1, `KSV-0014 (HIGH): Container 'backend' ... should set readOnlyRootFilesystem to true` |

## Schema validation

`kubeconform` validates the rendered manifests against the Kubernetes 1.36 schemas for the three value sets that are really used: CI, local development, and what Argo CD renders. The result was 13, 14 and 15 resources, all valid, none invalid. One resource, the `ServiceMonitor`, is skipped because it is a custom resource without a schema in the default set. The binary is downloaded with a pinned version and checked against the published SHA-256 checksums.

## What I chose not to add

I did not add `kube-linter`. Its checks overlap with Trivy's Kubernetes rules, and a second scanner means a second set of exceptions to maintain. See [ADR 0011](../adr/0011-one-scanner-for-iac-and-manifests.md).

## Result

13 findings were examined. After the change, every one of them is either fixed behind a switch, accepted with a written reason that the pipeline enforces, or marked as a false positive, and none is unexplained. A new finding fails the build.
