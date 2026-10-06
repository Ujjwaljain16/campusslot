# ADR 0001: Public worker subnets and no NAT gateway on EKS

Status: accepted

## Context

A NAT gateway costs about 0.045 USD per hour plus data charges, which would be the largest line of the bill for a cluster that lives for under an hour. The nodes still need a path to the internet to register with the control plane and to pull images.

## Options considered

- Private subnets with a NAT gateway: the production pattern, but the highest cost here.
- Private subnets with VPC endpoints for ECR, S3, STS and EC2: no NAT, but several endpoints with their own hourly cost.
- Public subnets, public IPs on the nodes, no NAT: cheapest, and the security group still blocks unsolicited inbound traffic.

## Decision

Public subnets with `map_public_ip_on_launch = true`, no NAT gateway, the API endpoint restricted to my own address, and private subnets created anyway for the control plane network interfaces.

## Consequences

- The first apply failed on the node group because the subnets did not assign public IPs, and EKS refuses such a group when no NAT exists. The fix and the diagnosis are in `terraform/README.md`.
- The whole 48 resource cluster used about 6 US cents of credit (the account credit went from 120 to 119.94 USD).

## What I would do in production

Nodes in private subnets, egress through NAT gateways or VPC endpoints, one NAT per availability zone, and a KMS key for secrets encryption.
