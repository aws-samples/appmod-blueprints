output "dev_cluster_name" {
  description = "EKS DEV Cluster name"
  value       = module.eks_blueprints_dev.eks_cluster_id
}

output "configure_kubectl" {
  description = "Configure kubectl: make sure you're logged in with the correct AWS profile and run the following command to update your kubeconfig"
  value       = module.eks_blueprints_dev.configure_kubectl
}

output "crossplane_dev_provider_role_arn" {
  description = "Provider role of the Crossplane EKS DEV ServiceAccount for IRSA"
  value       = module.crossplane_dev_provider_role.iam_role_arn
}

output "ack_dev_controller_role_arn" {
  description = "Controller role of the ACK EKS DEV ServiceAccount for IRSA"
  value       = module.ack_dev_controller_role.iam_role_arn
}

output "lb_controller_dev_role_arn" {
  description = "Provider role of the LB controller EKS DEV ServiceAccount for IRSA"
  value       = module.aws_load_balancer_dev_role.iam_role_arn
}

output "argo_rollouts_dev_role_arn" {
  description = "Provider role of the Argo Rollouts EKS DEV ServiceAccount for IRSA"
  value       = module.argo_rollouts_dev_role.iam_role_arn
}
