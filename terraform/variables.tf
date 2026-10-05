variable "region" {
  description = "AWS region for the network and the cluster"
  type        = string
  default     = "ap-south-1"
}

variable "cluster_name" {
  description = "Name of the EKS cluster and prefix for the network resources"
  type        = string
  default     = "campusslot"
}

variable "kubernetes_version" {
  description = "Kubernetes version of the control plane (a version in standard support)"
  type        = string
  default     = "1.36"
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to spread subnets over (EKS needs at least two)"
  type        = number
  default     = 2
}

variable "node_instance_type" {
  description = "Instance type of the worker nodes"
  type        = string
  default     = "t3.small"
}

variable "node_min_size" {
  description = "Minimum number of worker nodes"
  type        = number
  default     = 1
}

variable "node_desired_size" {
  description = "Desired number of worker nodes"
  type        = number
  default     = 1
}

variable "node_max_size" {
  description = "Maximum number of worker nodes"
  type        = number
  default     = 2
}

variable "api_allowed_cidrs" {
  description = "CIDR blocks allowed to reach the public Kubernetes API endpoint, for example [\"203.0.113.7/32\"]. There is deliberately no default, so the endpoint can never be opened to the whole internet by accident."
  type        = list(string)

  validation {
    condition     = length(var.api_allowed_cidrs) > 0 && !contains(var.api_allowed_cidrs, "0.0.0.0/0")
    error_message = "Provide at least one CIDR and do not use 0.0.0.0/0."
  }
}

# The three switches below are security controls that this demonstration leaves off to keep the cost
# of a short lived cluster close to zero. A production deployment turns them on, see
# terraform.tfvars.prod.example. They are variables so that the secure setting is one line away, and so
# that a scanner can check both profiles.
variable "enable_control_plane_logging" {
  description = "Send the Kubernetes API, audit, authenticator, controller manager and scheduler logs to CloudWatch"
  type        = bool
  default     = false
}

variable "enable_secrets_encryption" {
  description = "Encrypt Kubernetes Secrets in etcd with a customer managed KMS key"
  type        = bool
  default     = false
}

variable "enable_vpc_flow_logs" {
  description = "Capture network flow logs of the VPC in CloudWatch"
  type        = bool
  default     = false
}
