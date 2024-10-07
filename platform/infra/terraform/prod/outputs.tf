output "prod_cluster_name" {
  description = "EKS Prod Cluster name"
  value       = module.eks_blueprints_prod.eks_cluster_id
}

output "configure_kubectl" {
  description = "Configure kubectl: make sure you're logged in with the correct AWS profile and run the following command to update your kubeconfig"
  value       = module.eks_blueprints_prod.configure_kubectl
}

output "crossplane_prod_provider_role_arn" {
  description = "Provider role of the Crossplane EKS PROD ServiceAccount for IRSA"
  value       = module.crossplane_prod_provider_role.iam_role_arn
}