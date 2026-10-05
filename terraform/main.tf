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
  create_kms_key              = false
  encryption_config           = null
  enabled_log_types           = []
  create_cloudwatch_log_group = false

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
