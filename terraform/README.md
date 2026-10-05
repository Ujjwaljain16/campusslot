# Terraform: network and EKS cluster

This configuration builds the AWS side of the project: a VPC with public and private subnets across two availability zones, and an Amazon EKS cluster with one small managed node group. It uses two pinned community modules (`terraform-aws-modules/vpc` 6.7.3 and `terraform-aws-modules/eks` 21.26.0) and the AWS provider 6.x. The provider selections are recorded in `.terraform.lock.hcl`.

The application itself is not deployed to EKS. Kubernetes, Helm, monitoring and the troubleshooting labs run on Minikube. EKS exists here to show that the infrastructure is reproducible from code, and it is destroyed immediately afterwards to keep the cost close to zero.

## Files

| File | Purpose |
|---|---|
| `versions.tf` | Terraform and provider version constraints, region, default tags on every resource |
| `variables.tf` | Inputs. `api_allowed_cidrs` has no default on purpose |
| `main.tf` | VPC module, EKS module, managed node group |
| `outputs.tf` | VPC and subnet IDs, cluster name and endpoint, the `update-kubeconfig` command |
| `terraform.tfvars.example` | Template for the local, git-ignored `terraform.tfvars` |

## Design decisions

**Public worker subnets and no NAT gateway.** This is an intentional academic simplification for cost control. A NAT gateway costs about 0.045 USD per hour plus data charges, which would be the largest line of the bill for a demo that runs for an hour. Without NAT, the worker nodes live in the public subnets and receive a public IP, so they can reach the internet gateway directly to join the cluster and pull images. The security group still blocks all unsolicited inbound traffic to the nodes. A production design would place the nodes in the private subnets and send their egress through NAT gateways or VPC endpoints. The private subnets are created here, and the control plane network interfaces use them, so the production change is a one line edit of `subnet_ids` for the node group, not a redesign.

**The Kubernetes API is not open to the internet.** The public endpoint is restricted to the CIDRs in `api_allowed_cidrs`, and a validation rule rejects an empty list and `0.0.0.0/0`. Anyone using this configuration has to state which address may reach the API.

**No customer managed KMS key and no control plane log group.** Both add small recurring charges and are not needed for a short lived demonstration. A production cluster should enable secrets encryption with KMS and ship the audit log to CloudWatch.

**Cluster creator access.** `enable_cluster_creator_admin_permissions` creates an EKS access entry that gives the identity running Terraform admin rights in the cluster, so `kubectl` works straight after the apply.

## Usage

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # then put your own address in api_allowed_cidrs
terraform init
terraform fmt -check
terraform validate
terraform plan -out=tfplan
```

The plan in this repository, saved in [`docs/evidence/terraform-plan.txt`](../docs/evidence/terraform-plan.txt), reports `Plan: 48 to add, 0 to change, 0 to destroy.` It contains no NAT gateway, Elastic IP, KMS key, log group or load balancer.

Applying always goes through the reviewed plan file, never `-auto-approve`:

```bash
terraform apply tfplan
aws eks update-kubeconfig --region ap-south-1 --name campusslot
kubectl get nodes
```

## Cost estimate

| Item | Rate | Source |
|---|---|---|
| EKS control plane | 0.10 USD per hour | AWS published list price |
| One t3.small node, on demand | 0.0224 USD per hour | AWS Price List API, ap-south-1, Linux |
| Public IPv4 address of the node | 0.005 USD per hour | AWS published list price |
| 20 GB gp3 root volume | a fraction of a cent per hour | AWS published list price |

That comes to roughly 0.13 USD per hour, or about 3 USD for a full day left running by mistake. The account is on the AWS Free plan with a 120 USD credit, which is drawn down before anything is charged. The point of the destroy procedure below is to make sure the cluster never runs for a full day.

## Destroy and verify

```bash
terraform plan -destroy -out=destroy.tfplan
terraform apply destroy.tfplan

# Prove that nothing is left
aws eks list-clusters --region ap-south-1
aws ec2 describe-nat-gateways --region ap-south-1 --query 'NatGateways[?State!=`deleted`]'
aws ec2 describe-instances --region ap-south-1 --filters Name=instance-state-name,Values=running,pending
aws ec2 describe-vpcs --region ap-south-1 --filters Name=tag:Project,Values=campusslot
```

Every resource carries the tags `Project=campusslot` and `ManagedBy=terraform`, so anything that survived is easy to find in the console.

## Limits of this setup

State is kept locally and is git-ignored. A team would keep it in an S3 bucket with locking. There is a single node, so the cluster has no node redundancy. These choices keep the demonstration cheap and are not meant as a production baseline.
