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

output "ack_prod_controller_role_arn" {
  description = "Controller role of the ACK EKS PROD ServiceAccount for IRSA"
  value       = module.ack_prod_controller_role.iam_role_arn
}

output "lb_controller_prod_role_arn" {
  description = "Provider role of the LB controller EKS PROD ServiceAccount for IRSA"
  value       = module.aws_load_balancer_prod_role.iam_role_arn
}

output "argo_rollouts_prod_role_arn" {
  description = "Provider role of the Argo Rollouts EKS PROD ServiceAccount for IRSA"
  value       = module.argo_rollouts_prod_role.iam_role_arn
}
