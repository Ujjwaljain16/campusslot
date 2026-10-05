output "vpc_id" {
  description = "ID of the VPC"
  value       = module.vpc.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnets (the worker nodes run here)"
  value       = module.vpc.public_subnets
}

output "private_subnet_ids" {
  description = "Private subnets (control plane network interfaces)"
  value       = module.vpc.private_subnets
}

output "cluster_name" {
  description = "Name of the EKS cluster"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "Kubernetes API endpoint"
  value       = module.eks.cluster_endpoint
}

output "configure_kubectl" {
  description = "Command that writes the cluster into your kubeconfig"
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}
