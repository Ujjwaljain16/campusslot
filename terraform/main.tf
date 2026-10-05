data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  # /24 subnets carved from the VPC CIDR: private ones from 10.0.0.0/24, public ones from 10.0.100.0/24.
  private_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i)]
  public_subnets  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 100)]
}

################################################################################
# Network
#
# Public worker subnets and NO NAT gateway are a deliberate academic simplification for cost
# control (a NAT gateway costs about 0.045 USD per hour plus data charges). The nodes get a
# public IP so they can reach the internet gateway directly to register with the control plane
# and pull images. A production design would place the nodes in the private subnets and send
# their egress through NAT gateways or VPC endpoints. The private subnets are created here so
# that change is a one line edit (subnet_ids) and not a redesign.
################################################################################

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name = var.cluster_name
  cidr = var.vpc_cidr
  azs  = local.azs

  private_subnets = local.private_subnets
  public_subnets  = local.public_subnets

  enable_nat_gateway   = false
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Required by the design above: without a NAT gateway the nodes reach the internet only through
  # a public IP, and EKS rejects a node group whose subnets do not assign one.
  map_public_ip_on_launch = true

  # Network flow logs, off in the demonstration profile to save cost (see var.enable_vpc_flow_logs).
  enable_flow_log                      = var.enable_vpc_flow_logs
  create_flow_log_cloudwatch_log_group = var.enable_vpc_flow_logs
  create_flow_log_cloudwatch_iam_role  = var.enable_vpc_flow_logs
  flow_log_max_aggregation_interval    = 60

  # Kubernetes uses these tags to find the subnets for load balancers.
  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
  }
}

################################################################################
# EKS cluster with one small managed node group
################################################################################

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.26.0"

  name               = var.cluster_name
  kubernetes_version = var.kubernetes_version

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.public_subnets
  control_plane_subnet_ids = module.vpc.private_subnets

  # The API is reachable only from the addresses listed in api_allowed_cidrs.
  endpoint_public_access       = true
  endpoint_public_access_cidrs = var.api_allowed_cidrs
  endpoint_private_access      = true

  # Gives the identity that runs Terraform admin rights inside the cluster, so kubectl works.
  enable_cluster_creator_admin_permissions = true

  # Cost trimming for a short lived demo: no customer managed KMS key and no control plane
  # log group. A production cluster would enable both.
  create_kms_key              = var.enable_secrets_encryption
  encryption_config           = var.enable_secrets_encryption ? { resources = ["secrets"] } : null
  enabled_log_types           = var.enable_control_plane_logging ? ["api", "audit", "authenticator", "controllerManager", "scheduler"] : []
  create_cloudwatch_log_group = var.enable_control_plane_logging

  addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni = {
      before_compute = true
    }
  }

  eks_managed_node_groups = {
    default = {
      instance_types = [var.node_instance_type]
      capacity_type  = "ON_DEMAND"

      min_size     = var.node_min_size
      desired_size = var.node_desired_size
      max_size     = var.node_max_size

      # Public subnets, see the note on the network above.
      subnet_ids = module.vpc.public_subnets
    }
  }
}
