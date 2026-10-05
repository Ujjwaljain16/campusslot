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

## What went wrong on the first apply

The first `terraform apply` created the VPC and the EKS control plane, and then failed on the node group after about a minute with `Ec2SubnetInvalidConfiguration`. The node group health check on the EKS side explained it: the public subnets did not automatically assign public IP addresses to instances. The VPC module defaults `map_public_ip_on_launch` to `false`, and I had assumed that public subnets would assign addresses on their own. Without NAT, a node can only reach the internet through its own public IP, so EKS refuses to create the group.

The saved plan had looked correct, because Terraform cannot know that EKS will reject a subnet setting. I found the cause with `aws eks describe-nodegroup` (the `health.issues` field), set `map_public_ip_on_launch = true` in `main.tf`, and made a second plan. That plan updated the two public subnets in place, replaced the tainted node group, and created the two add-ons that the failed run never reached, with nothing else changing. After the second apply, the node joined the cluster and became `Ready`. The transcripts are in [`docs/evidence`](../docs/evidence) as `terraform-apply.txt`, `terraform-replan.txt` and `terraform-apply2.txt`.

## The real run, start to finish

I applied this configuration to a real AWS account in `ap-south-1`, checked it, and destroyed it again within about 45 minutes. All times are UTC on 5 October 2026.

| Step | Time | Result |
|---|---|---|
| First `terraform apply` of the reviewed plan | 12:06 to 12:19 | VPC and control plane created, node group failed (see above) |
| Second plan and apply | 12:22 to 12:25 | `3 added, 2 changed, 1 destroyed`, node group `ACTIVE` |
| Verification | 12:30 | Cluster `ACTIVE` on 1.36, node `Ready`, API restricted to my address |
| `terraform plan -destroy`, then apply | 12:39 to 12:51 | `0 added, 0 changed, 48 destroyed` |
| Cleanup check | 12:51 | No EKS cluster, VPC, subnet, NAT gateway, Elastic IP, instance, volume, load balancer, IAM role or OIDC provider left |

Evidence, with the AWS account ID masked in the screenshots and transcripts:

- Terminal: [`terraform output` and the cluster status](../docs/evidence/terraform-output-terminal.png), and the [EKS and node check](../docs/evidence/eks-verification.txt), which includes `kubectl get nodes` and the `kube-system` pods
- AWS Console: [EKS cluster, Active, 1.36](../docs/evidence/aws-eks-cluster.png), [node group, Active](../docs/evidence/aws-eks-node-group.png), [VPC 10.0.0.0/16](../docs/evidence/aws-vpc.png), [four subnets](../docs/evidence/aws-subnets.png), and [no NAT gateways](../docs/evidence/aws-no-nat-gateways.png)
- Transcripts: [plan](../docs/evidence/terraform-plan.txt), [apply](../docs/evidence/terraform-apply.txt), [second plan](../docs/evidence/terraform-replan.txt), [second apply](../docs/evidence/terraform-apply2.txt), [destroy plan](../docs/evidence/terraform-destroy-plan.txt), [destroy](../docs/evidence/terraform-destroy.txt), and the [empty-account check](../docs/evidence/aws-cleanup-verification.txt)

One detail from the console is worth recording. The Compute tab of the EKS page first showed `Unauthorized` when listing nodes. The cluster's Kubernetes access list contains only the identity that Terraform used to create it, and my console login was not on it, so the console could not read the node list. The Node groups tab, which uses the AWS API and not the Kubernetes API, showed the group as `Active`. Nothing was wrong with the cluster, and giving a console user access would need one more `aws_eks_access_entry`.

## Limits of this setup

State is kept locally and is git-ignored. A team would keep it in an S3 bucket with locking. There is a single node, so the cluster has no node redundancy. These choices keep the demonstration cheap and are not meant as a production baseline.
